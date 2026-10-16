"""Isolated real-DNS Compose test. Generates only disposable synthetic credentials."""

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command(args, env=None, timeout=180):
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:])
    return result.stdout


def run(backend, bff_image, ats_image, validation_image):
    print(command(["docker", "compose", "version"]).strip(), flush=True)
    required_services = ("ats-service", "bff", "public-stub", "web")
    spec = importlib.util.spec_from_file_location(
        "synthetic_pki", backend / "scripts/ats_test_credentials.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    with tempfile.TemporaryDirectory(prefix="bff-synthetic-") as directory:
        temp = Path(directory)
        material = fixtures.generate(temp / "pki")
        root = material["root"]
        for path in root.iterdir():
            if path.is_file():
                path.chmod(0o600)
        for name in ("data", "resumes", "bff-data"):
            (temp / name).mkdir(mode=0o700)
        # Synthetic hash only; real provisioning remains an explicit interactive operator action.
        password_hash = command(
            [
                "docker",
                "run",
                "--rm",
                validation_image,
                "python",
                "-c",
                "from argon2 import PasswordHasher; print(PasswordHasher().hash('synthetic-test-password-only'))",
            ]
        ).strip()
        password = temp / "operator.hash"
        password.write_text(password_hash)
        password.chmod(0o600)
        # Browser HTTPS uses its own synthetic leaf; the ATS leaf remains unchanged.
        fixtures.command(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            root / "browser.key",
            "-out",
            root / "browser.csr",
            "-subj",
            "/CN=workspace.test",
        )
        (root / "browser.ext").write_text(
            "subjectAltName=DNS:workspace.test\nextendedKeyUsage=serverAuth\n"
        )
        fixtures.command(
            "x509",
            "-req",
            "-in",
            root / "browser.csr",
            "-CA",
            root / "ca.crt",
            "-CAkey",
            root / "ca.key",
            "-set_serial",
            "900",
            "-days",
            "1",
            "-extfile",
            root / "browser.ext",
            "-out",
            root / "browser.crt",
        )
        (root / "browser.key").chmod(0o600)
        nginx = temp / "nginx.conf"
        snippet = (ROOT / "deploy/workspace.nginx.conf").read_text()
        nginx.write_text(
            "pid /tmp/nginx.pid; error_log /dev/stderr; events {} http { access_log off; "
            "client_body_temp_path /tmp/client; proxy_temp_path /tmp/proxy; "
            "fastcgi_temp_path /tmp/fastcgi; uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi; "
            "server { listen 8443 ssl; ssl_certificate /tls/browser.crt; "
            "ssl_certificate_key /tls/browser.key; "
            'location = /healthz { return 200 "ok"; } ' + snippet + " } }"
        )
        runtime_user = f"{os.getuid()}:{os.getgid()}"
        env = {
            **os.environ,
            "BFF_DIRECTORY": str(ROOT),
            "BFF_RUNTIME_USER": runtime_user,
            "BFF_ORIGIN": "https://workspace.test:8443",
            "BFF_OPERATOR_ID": "synthetic-operator",
            "BFF_PASSWORD_FILE": str(password),
            "BFF_CA_FILE": str(root / "ca.crt"),
            "BFF_CERT_FILE": str(root / "client.crt"),
            "BFF_KEY_FILE": str(root / "client.key"),
            "ATS_POLICY_DIRECTORY": str(material["policy_file"].parent),
            "ATS_TOKEN_FILE": str(root / "token"),
            "ATS_SERVER_CERT_FILE": str(root / "server.crt"),
            "ATS_SERVER_KEY_FILE": str(root / "server.key"),
            "ATS_CLIENT_CA_FILE": str(root / "ca.crt"),
        }
        override = {
            "services": {
                "ats-service": {
                    "image": ats_image,
                    "user": runtime_user,
                    "build": {"context": str(backend)},
                },
                "bff": {"image": bff_image, "volumes": [str(temp / "bff-data") + ":/data"]},
                "probe": {
                    "image": validation_image,
                    "profiles": ["validation"],
                    "user": runtime_user,
                    "networks": ["bff-edge"],
                    "environment": {"BFF_ORIGIN": "https://workspace.test:8443"},
                    "volumes": [
                        str(ROOT) + ":/app:ro",
                        str(backend) + ":/upstream:ro",
                        str(temp) + ":/synthetic:ro",
                        str(temp / "bff-data") + ":/restart",
                    ],
                    "command": ["python", "-m", "scripts.smoke_probe"],
                },
            }
        }
        override["services"]["public-stub"] = {
            "healthcheck": {
                "test": [
                    "CMD",
                    "python",
                    "-c",
                    "import socket; socket.create_connection(('127.0.0.1', 8765), timeout=2).close()",
                ],
                "interval": "2s",
                "timeout": "3s",
                "retries": 15,
            },
            "image": bff_image,
            "user": runtime_user,
            "command": [
                "python",
                "-m",
                "http.server",
                "8765",
                "--directory",
                "/nonexistent-synthetic-public",
            ],
            "networks": {"bff-edge": {"aliases": ["api"]}},
        }
        override["services"]["web"] = {
            "image": "nginx:stable-alpine",
            "depends_on": {
                "bff": {"condition": "service_healthy"},
                "public-stub": {"condition": "service_healthy"},
            },
            "user": runtime_user,
            "entrypoint": ["nginx"],
            "command": ["-g", "daemon off;"],
            "networks": {"bff-edge": {"aliases": ["workspace.test"]}},
            "volumes": [str(nginx) + ":/etc/nginx/nginx.conf:ro", str(root) + ":/tls:ro"],
            "healthcheck": {
                "test": ["CMD", "nc", "-z", "127.0.0.1", "8443"],
                "interval": "2s",
                "timeout": "2s",
                "retries": 15,
            },
        }
        config = temp / "override.json"
        config.write_text(json.dumps(override))
        compose = [
            "docker",
            "compose",
            "--project-directory",
            str(temp),
            "-p",
            "bff-test-" + uuid.uuid4().hex[:8],
            "-f",
            str(backend / "compose.yaml"),
            "-f",
            str(backend / "compose.ats.yaml"),
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(config),
        ]
        command([*compose, "config", "--quiet"], env)
        resolved = json.loads(command([*compose, "config", "--format", "json"], env))
        for name in required_services:
            service = resolved["services"][name]
            healthcheck = service.get("healthcheck", {})
            test = healthcheck.get("test", [])
            assert not healthcheck.get("disable"), f"{name}: resolved healthcheck is disabled"
            assert len(test) > 1 and test[0] in {"CMD", "CMD-SHELL"}, (
                f"{name}: resolved healthcheck must have an executable test"
            )
            assert not service.get("ports"), f"{name}: smoke must not publish ports"
            print(f"{name}: compose config has an enabled {test[0]} healthcheck", flush=True)
        assert resolved["networks"]["ats-private"]["internal"]
        assert resolved["networks"]["bff-edge"]["internal"]
        try:
            command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--user",
                    runtime_user,
                    "-e",
                    "DATABASE_PATH=/data/jobs.db",
                    "-v",
                    str(temp / "data") + ":/data",
                    "-v",
                    str(backend) + ":/upstream:ro",
                    "-w",
                    "/upstream",
                    validation_image,
                    "/opt/ats/bin/python",
                    "-m",
                    "scripts.ats_tls_probe",
                    "--seed",
                ]
            )
            command(
                [
                    *compose,
                    "up",
                    "-d",
                    "--no-build",
                    "--no-deps",
                    "--wait",
                    "--wait-timeout",
                    "60",
                    "ats-service",
                    "bff",
                    "public-stub",
                    "web",
                ],
                env,
            )
            for name in required_services:
                identifier = command([*compose, "ps", "-q", name], env).strip()
                meta = json.loads(command(["docker", "inspect", identifier]))[0]
                assert (
                    meta["Config"].get("Healthcheck", {}).get("Test")
                    == resolved["services"][name]["healthcheck"]["test"]
                ), f"{name}: container healthcheck differs from compose config"
                assert not meta["HostConfig"]["PortBindings"]
                assert meta["State"].get("Health", {}).get("Status") == "healthy", (
                    f"{name}: container must report healthy"
                )
                print(
                    f"{name}: docker inspect confirms the configured healthcheck is healthy",
                    flush=True,
                )
            first = command([*compose, "run", "--rm", "--no-deps", "probe"], env)
            print(first.strip())
            command([*compose, "restart", "bff"], env)
            command([*compose, "up", "-d", "--no-build", "--no-deps", "--wait", "bff"], env)
            print(
                command(
                    [
                        *compose,
                        "run",
                        "--rm",
                        "--no-deps",
                        "probe",
                        "python",
                        "-m",
                        "scripts.smoke_probe",
                        "--restart",
                    ],
                    env,
                ).strip()
            )
            logs = command([*compose, "logs", "--no-color", "bff", "ats-service", "web"], env)
            assert material["token"] not in logs and "synthetic-test-password-only" not in logs
            assert password_hash not in logs
            print(
                "Compose: private ports, internal networks, healthchecks, persistence and clean logs verified."
            )
        except Exception:
            print(command([*compose, "logs", "--no-color", "--tail", "30", "web", "bff"], env))
            raise
        finally:
            # Only this unique project is stopped. No --volumes; existing user volumes untouched.
            command([*compose, "down", "--remove-orphans"], env)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--bff-image", default="job-agent-bff:v0.1")
    parser.add_argument("--ats-image", default="job-agent-ats:v0.8")
    parser.add_argument("--validation-image", default="job-agent-bff:validation")
    args = parser.parse_args()
    run(args.backend.resolve(), args.bff_image, args.ats_image, args.validation_image)
