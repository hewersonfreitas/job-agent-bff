"""Real TLS and actual backend v0.8. Requires ATS_BACKEND_DIRECTORY checkout."""

import importlib.util
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from bff.app import create_app
from bff.config import Settings
from bff.upstream import client as ats_client
from tests.conftest import ORIGIN, PASSWORD, login

BACKEND = os.getenv("ATS_BACKEND_DIRECTORY")
pytestmark = pytest.mark.skipif(
    not BACKEND, reason="Set ATS_BACKEND_DIRECTORY to the pinned v0.8 checkout"
)


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    backend = Path(BACKEND)
    spec = importlib.util.spec_from_file_location(
        "fixture_pki", backend / "scripts/ats_test_credentials.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    temp = tmp_path_factory.mktemp("real-ats")
    material = fixtures.generate(temp / "pki")
    for path in material["root"].glob("*"):
        if path.is_file():
            path.chmod(0o600)
    env = {
        **os.environ,
        **fixtures.environment(material),
        "DATABASE_PATH": str(temp / "jobs.db"),
        "RESUME_ROOT": str(temp / "resumes"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # Seed only a temporary synthetic workspace using the upstream helper.
    subprocess.run(
        [os.getenv("ATS_PYTHON", sys.executable), "-m", "scripts.ats_tls_probe", "--seed"],
        cwd=backend,
        env=env,
        check=True,
        capture_output=True,
    )
    log = (temp / "server.log").open("w+")
    proc = subprocess.Popen(
        [os.getenv("ATS_PYTHON", sys.executable), "-m", "app.ats_server"],
        cwd=backend,
        env=env,
        stdout=log,
        stderr=log,
    )
    try:
        for _ in range(100):
            if proc.poll() is not None:
                log.seek(0)
                pytest.fail("Synthetic ATS server startup failed: " + log.read())
            try:
                with socket.create_connection(("127.0.0.1", 8766), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("Synthetic ATS server readiness timeout")
        yield material, temp, backend
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        log.close()


@pytest.fixture
def real_settings(service, tmp_path):
    material, _, _ = service
    root = material["root"]
    password = tmp_path / "operator.hash"
    password.write_text(PasswordHasher().hash(PASSWORD))
    password.chmod(0o600)
    return Settings(
        origin=ORIGIN,
        operator_id="synthetic-operator",
        password_file=password,
        token_file=root / "token",
        ca_file=root / "ca.crt",
        cert_file=root / "client.crt",
        key_file=root / "client.key",
        database=tmp_path / "sessions.db",
    )


def test_complete_real_ats_flow(real_settings, service):
    _, _, backend = service
    with TestClient(create_app(real_settings), base_url=ORIGIN) as browser:
        browser.headers.update({"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"})
        login(browser)

        def call(method, path, **kwargs):
            response = browser.request(method, "/workspace/ats" + path, **kwargs)
            assert response.status_code == 200, (path, response.status_code, response.text)
            assert response.headers["cache-control"] == "no-store"
            return response

        profile = json.loads((backend / "examples/master-profile.example.json").read_text())
        resume = call("POST", "/resumes/import", json=profile).json()["id"]
        assert call("GET", "/resumes").json()[0]["id"] == resume
        call("GET", f"/resumes/{resume}")
        record = call("GET", f"/resumes/{resume}/profile").json()
        call(
            "PATCH",
            f"/resumes/{resume}/profile",
            json={
                "expected_revision": 1,
                "profile": record["profile"],
                "confirm_all": True,
                "notes": "Synthetic confirmation",
            },
        )
        assert (
            browser.patch(
                f"/workspace/ats/resumes/{resume}/profile",
                json={
                    "expected_revision": 1,
                    "profile": record["profile"],
                    "notes": "Synthetic stale",
                },
            ).status_code
            == 409
        )
        call("POST", "/jobs/1/requirements/analyze")
        version = call(
            "POST", "/jobs/1/resumes/tailor", json={"resume_id": resume, "language": "en"}
        ).json()
        identifier = version["id"]
        call("GET", "/jobs/1/resumes")
        call("GET", f"/resumes/versions/{identifier}/diff")
        decisions = [
            {"id": s["id"], "decision": "accepted"}
            for s in version["suggestions"]
            if s["decision"] == "pending"
        ]
        call(
            "PATCH",
            f"/resumes/versions/{identifier}/review",
            json={"expected_revision": 1, "decisions": decisions, "notes": "Synthetic review"},
        )
        call(
            "POST",
            f"/resumes/versions/{identifier}/approve",
            json={"expected_revision": 2, "acknowledge_gaps": True, "notes": "Synthetic approval"},
        )
        call("GET", f"/resumes/versions/{identifier}/ats-report")
        for extension, mime in [
            ("pdf", "application/pdf"),
            ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ]:
            response = call("GET", f"/resumes/versions/{identifier}/export?format={extension}")
            assert response.headers["content-type"] == mime
            assert (
                response.headers["content-disposition"]
                == f'attachment; filename="resume-version-{identifier}.{extension}"'
            )
            call(
                "POST",
                "/resumes/import",
                content=response.content,
                headers={"Content-Type": mime, "X-Filename": "synthetic." + extension},
            )
        assert browser.post("/workspace/auth/logout").status_code == 204
        assert browser.get("/workspace/ats/resumes").status_code == 401


@pytest.mark.parametrize("certificate", [None, "rogue", "expired"])
def test_reject_missing_invalid_client(service, certificate):
    material, _, _ = service
    root = material["root"]
    ctx = ssl.create_default_context(cafile=str(root / "ca.crt"))
    if certificate:
        ctx.load_cert_chain(str(root / (certificate + ".crt")), str(root / (certificate + ".key")))
    with httpx.Client(verify=ctx, trust_env=False, timeout=3) as connection:
        with pytest.raises(httpx.TransportError):
            connection.get("https://ats-service:8766/health")


def test_invalid_ca(real_settings):
    settings = real_settings.model_copy(
        update={"ca_file": real_settings.ca_file.with_name("rogue-ca.crt")}
    )
    import asyncio

    async def run():
        async with ats_client(settings) as connection:
            with pytest.raises(httpx.TransportError):
                await connection.get("/health")

    asyncio.run(run())


def test_hostname_mismatch(service):
    material, _, _ = service
    root = material["root"]
    ctx = ssl.create_default_context(cafile=str(root / "ca.crt"))
    ctx.load_cert_chain(str(root / "client.crt"), str(root / "client.key"))
    with socket.create_connection(("127.0.0.1", 8766), timeout=3) as connection:
        with pytest.raises(ssl.SSLCertVerificationError):
            with ctx.wrap_socket(connection, server_hostname="wrong.invalid"):
                pass


@pytest.mark.parametrize(
    "kind,status",
    [
        ("token", 401),
        ("operator", 403),
        ("unknown", 403),
        ("revoked", 403),
        ("disabled", 403),
        ("scope", 403),
        ("resource", 404),
    ],
)
def test_upstream_authorization(real_settings, service, tmp_path, kind, status):
    material, _, _ = service
    policy = json.loads(json.dumps(material["policy"]))
    settings = real_settings
    if kind == "token":
        token = tmp_path / "wrong-token"
        token.write_text("z" * 40)
        token.chmod(0o600)
        settings = settings.model_copy(update={"token_file": token})
    elif kind == "operator":
        settings = settings.model_copy(update={"operator_id": "unapproved"})
    elif kind == "unknown":
        settings = settings.model_copy(
            update={
                "cert_file": material["root"] / "unknown.crt",
                "key_file": material["root"] / "unknown.key",
            }
        )
    elif kind == "disabled":
        policy["services"][0]["enabled"] = False
    elif kind == "revoked":
        policy["services"][0]["certificates"][0]["revoked"] = True
    elif kind == "scope":
        policy["services"][0]["scopes"] = ["ats:export"]
    elif kind == "resource":
        policy["services"][0]["resume_ids"] = [999]
    material["policy_file"].write_text(json.dumps(policy))
    try:
        with TestClient(create_app(settings), base_url=ORIGIN) as browser:
            browser.headers["Origin"] = ORIGIN
            login(browser)
            path = "/workspace/ats/resumes/1" if kind == "resource" else "/workspace/ats/resumes"
            assert browser.get(path).status_code == status
    finally:
        material["policy_file"].write_text(json.dumps(material["policy"]))
