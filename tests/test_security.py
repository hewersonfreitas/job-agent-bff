import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from bff.app import create_app
from bff.config import COOKIE
from bff.store import Store
from tests.conftest import ORIGIN, PASSWORD, login


def test_login_cookie_logout_revocation(api, settings):
    result = login(api)
    cookie = result.headers["set-cookie"]
    for expected in (COOKIE, "HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert expected in cookie
    assert "Domain=" not in cookie
    token = api.cookies.get(COOKIE)
    csrf = api.headers["X-CSRF-Token"]
    with sqlite3.connect(settings.database) as db:
        assert token not in str(db.execute("SELECT * FROM sessions").fetchall())
        assert csrf not in str(db.execute("SELECT * FROM sessions").fetchall())
    assert api.get("/workspace/auth/session").json()["authenticated"] is True
    assert api.post("/workspace/auth/logout").status_code == 204
    api.cookies.set(COOKIE, token)
    assert api.get("/workspace/auth/session").json()["authenticated"] is False
    assert api.get("/workspace/ats/resumes").status_code == 401


def test_bad_login_rate_limit_persists(api, settings, clock):
    for _ in range(settings.login_attempts):
        response = api.post("/workspace/auth/login", json={"password": "incorrect"})
        assert response.status_code == 401
        assert "incorrect" not in response.text
    assert api.post("/workspace/auth/login", json={"password": PASSWORD}).status_code == 429
    assert Store(settings, lambda: clock[0]).attempt("testclient") is False


@pytest.mark.parametrize("elapsed", [1801, 28801])
def test_expiry(api, clock, elapsed):
    login(api)
    clock[0] += elapsed
    assert api.get("/workspace/ats/resumes").status_code == 401


def test_absolute_expiry_despite_activity(api, clock):
    login(api)
    for _ in range(29):
        clock[0] += 1000
        response = api.get("/workspace/ats/resumes")
    assert response.status_code == 401


def test_rotation_fixation_limit(api, settings):
    api.cookies.set(COOKIE, "attacker-chosen", domain="workspace.test", path="/")
    old = []
    for _ in range(5):
        login(api)
        current = api.cookies.get(COOKIE)
        assert current != "attacker-chosen"
        assert current not in old
        old.append(current)
    with sqlite3.connect(settings.database) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_session_cap_and_restart(api, settings, clock):
    tokens = []
    for _ in range(5):
        api.cookies.clear()
        login(api)
        tokens.append(api.cookies.get(COOKIE))
    with sqlite3.connect(settings.database) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == settings.max_sessions
    transport = httpx.AsyncClient(
        base_url="https://ats-service:8766",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])),
    )
    with TestClient(
        create_app(settings, transport, lambda: clock[0]), base_url=ORIGIN
    ) as restarted:
        restarted.cookies.set(COOKIE, tokens[-1])
        assert restarted.get("/workspace/auth/session").json()["authenticated"] is True
        Store(settings).revoke()
        assert restarted.get("/workspace/auth/session").json()["authenticated"] is False


def test_password_rotation_revokes(api, settings):
    from argon2 import PasswordHasher

    login(api)
    settings.password_file.write_text(PasswordHasher().hash("new-synthetic-password"))
    assert api.get("/workspace/ats/resumes").status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"X-CSRF-Token": ""},
        {"X-CSRF-Token": "invalid"},
        {"Origin": "https://evil.test"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"X-ATS-Operator": "attacker"},
        {"X-ATS-Service": "trusted"},
        {"Authorization": "Bearer injected"},
        {"X-SSL-Client-Verify": "SUCCESS"},
        {"Host": "evil.test"},
        {"Content-Encoding": "gzip"},
    ],
)
def test_mutation_http_guards(api, upstream, headers):
    login(api)
    response = api.post("/workspace/ats/jobs/1/requirements/analyze", headers=headers)
    assert response.status_code in (403, 415)
    assert not upstream[0]
    assert response.headers["cache-control"] == "no-store"


def test_missing_origin_and_csrf(api, upstream):
    login(api)
    del api.headers["Origin"]
    assert api.post("/workspace/auth/logout").status_code == 403
    api.headers["Origin"] = ORIGIN
    del api.headers["X-CSRF-Token"]
    assert api.post("/workspace/ats/jobs/1/requirements/analyze").status_code == 403
    assert not upstream[0]


@pytest.mark.parametrize(
    "path",
    [
        op
        for op in (
            "/workspace/ats/resumes",
            "/workspace/ats/resumes/1",
            "/workspace/ats/jobs/1/resumes",
            "/workspace/auth/csrf",
            "/workspace/ats/resumes/versions/1/export",
        )
    ],
)
def test_anonymous(api, upstream, path):
    assert api.get(path).status_code == 401
    assert not upstream[0]


def test_login_csrf_payload_methods(api):
    assert (
        api.post(
            "/workspace/auth/login", json={"password": PASSWORD}, headers={"Origin": "null"}
        ).status_code
        == 403
    )
    assert api.get("/workspace/auth/login").status_code == 405
    assert api.post("/workspace/auth/session").status_code == 405
    assert (
        api.post(
            "/workspace/auth/login", json={"password": PASSWORD, "extra": "private"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/workspace/auth/login", content="private", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        api.post(
            "/workspace/auth/login",
            content="x" * 5000,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_no_private_data_in_errors_logs(api, caplog, settings):
    login(api)
    secret = "private-profile-that-must-not-be-echoed"
    response = api.patch("/workspace/ats/resumes/1/profile", json={"profile": secret})
    assert response.status_code == 422
    assert secret not in response.text + caplog.text
    with sqlite3.connect(settings.database) as db:
        audit = str(db.execute("SELECT * FROM audit").fetchall())
    for value in (secret, PASSWORD, api.cookies.get(COOKIE), api.headers["X-CSRF-Token"]):
        assert value not in audit


def test_fail_closed_audit(api, monkeypatch):
    login(api)

    def fail(*args):
        raise sqlite3.OperationalError("private internals")

    monkeypatch.setattr(api.app.state.store, "audit", fail)
    response = api.get("/workspace/ats/resumes")
    assert response.status_code == 503
    assert "private internals" not in response.text


def test_duplicate_sensitive_headers(api):
    login(api)
    response = api.post("/workspace/auth/logout", headers=[("Origin", ORIGIN), ("Origin", ORIGIN)])
    assert response.status_code == 403


def test_revoked_old_session_after_rotation(api):
    login(api)
    token = api.cookies.get(COOKIE)
    login(api)
    api.cookies.clear()
    api.cookies.set(COOKIE, token)
    assert api.get("/workspace/ats/resumes").status_code == 401
