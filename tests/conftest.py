import httpx
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from bff.app import create_app
from bff.config import COOKIE, Settings

ORIGIN = "https://workspace.test"
PASSWORD = "synthetic-test-password-only"


@pytest.fixture
def settings(tmp_path):
    paths = {}
    for name in (
        "password_file",
        "token_file",
        "admin_token_file",
        "ca_file",
        "cert_file",
        "key_file",
    ):
        path = tmp_path / name
        path.write_text(
            PasswordHasher().hash(PASSWORD)
            if name == "password_file"
            else ("a" * 43 if name == "admin_token_file" else "x" * 40)
        )
        path.chmod(0o600)
        paths[name] = path
    return Settings(
        origin=ORIGIN, operator_id="synthetic-operator", database=tmp_path / "sessions.db", **paths
    )


@pytest.fixture
def clock():
    return [1000000.0]


@pytest.fixture
def upstream():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[])

    return calls, handler


@pytest.fixture
def api(settings, clock, upstream):
    client = httpx.AsyncClient(
        base_url="https://ats-service:8766", transport=httpx.MockTransport(upstream[1])
    )
    app = create_app(settings, transport=client, clock=lambda: clock[0])
    with TestClient(app, base_url=ORIGIN) as browser:
        browser.headers.update({"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"})
        yield browser


def login(api):
    result = api.post("/workspace/auth/login", json={"password": PASSWORD})
    assert result.status_code == 200, result.text
    assert COOKIE in api.cookies
    csrf = api.get("/workspace/auth/csrf")
    assert csrf.status_code == 200
    api.headers["X-CSRF-Token"] = csrf.json()["csrf_token"]
    return result
