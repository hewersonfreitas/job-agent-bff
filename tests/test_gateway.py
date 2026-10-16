import json

import httpx
import pytest
from fastapi.testclient import TestClient

from bff.app import create_app
from bff.contracts import OPERATIONS
from bff.uploads import validate_upload
from tests.conftest import ORIGIN, login


def test_finite_allowlist_contract():
    from scripts.check_contract import check

    check()


def test_headers_not_forwarded(api, upstream):
    login(api)
    assert (
        api.get("/workspace/ats/resumes", headers={"X-Forwarded-For": "attacker"}).status_code
        == 200
    )
    request = upstream[0][-1]
    assert request.headers["host"] == "ats-service:8766"
    assert request.headers["authorization"].startswith("Bearer ")
    assert request.headers["x-ats-operator"] == "synthetic-operator"
    for name in ("cookie", "origin", "sec-fetch-site", "x-forwarded-for", "x-csrf-token"):
        assert name not in request.headers


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/ats/resumes/0",
        "/workspace/ats/resumes/-1",
        "/workspace/ats/resumes/9999999999999999999",
        "/workspace/ats/resumes/1?url=https://evil.test",
        "/workspace/ats/resumes?limit=201",
        "/workspace/ats/resumes?offset=-1",
        "/workspace/ats/resumes?limit=1&limit=2",
        "/workspace/ats/resumes/versions/1/export?format=../../secret",
        "/workspace/ats/admin/sources",
        "/workspace/ats/https://evil.test",
    ],
)
def test_no_arbitrary_paths_queries(api, upstream, path):
    login(api)
    assert api.get(path).status_code in (404, 422)
    assert not upstream[0]


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_operation_requires_session_and_csrf(api, upstream, operation):
    path = "/workspace/ats" + operation.path.replace("{resume_id}", "1").replace(
        "{job_id}", "1"
    ).replace("{version_id}", "1")
    assert api.request(operation.method, path).status_code == 401
    login(api)
    if operation.method != "GET":
        del api.headers["X-CSRF-Token"]
        assert api.request(operation.method, path).status_code == 403
    assert not upstream[0]


@pytest.mark.parametrize("code", [401, 403, 404, 409, 422, 503])
def test_upstream_errors_sanitized_no_retry(settings, code):
    count = []

    def handler(request):
        count.append(request)
        return httpx.Response(code, json={"detail": "secret private document"})

    transport = httpx.AsyncClient(
        base_url="https://ats-service:8766", transport=httpx.MockTransport(handler)
    )
    with TestClient(create_app(settings, transport), base_url=ORIGIN) as browser:
        browser.headers["Origin"] = ORIGIN
        login(browser)
        response = browser.post("/workspace/ats/jobs/1/requirements/analyze")
        assert response.status_code == code
        assert "secret private document" not in response.text
        assert len(count) == 1


def test_timeout_no_retry(settings):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret error")

    transport = httpx.AsyncClient(
        base_url="https://ats-service:8766", transport=httpx.MockTransport(handler)
    )
    with TestClient(create_app(settings, transport), base_url=ORIGIN) as browser:
        browser.headers["Origin"] = ORIGIN
        login(browser)
        response = browser.post("/workspace/ats/jobs/1/requirements/analyze")
        assert response.status_code == 503
        assert "secret error" not in response.text
        assert len(calls) == 1


@pytest.mark.parametrize("payload", [None, {}, {"unexpected": "private"}, [1]])
def test_strict_response_validation(settings, payload):
    transport = httpx.AsyncClient(
        base_url="https://ats-service:8766",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)),
    )
    with TestClient(create_app(settings, transport), base_url=ORIGIN) as browser:
        browser.headers["Origin"] = ORIGIN
        login(browser)
        assert browser.get("/workspace/ats/resumes").status_code == 502


def test_scope_deny(settings):
    transport = httpx.AsyncClient(
        base_url="https://ats-service:8766",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])),
    )
    with TestClient(
        create_app(settings.model_copy(update={"scopes": frozenset()}), transport), base_url=ORIGIN
    ) as browser:
        browser.headers["Origin"] = ORIGIN
        login(browser)
        assert browser.get("/workspace/ats/resumes").status_code == 403


@pytest.mark.parametrize(
    "name", ["../master.json", "bad\\master.json", "bad\r\n.json", ".hidden.json", "wrong.pdf"]
)
def test_upload_filenames(api, upstream, name):
    login(api)
    assert (
        api.post(
            "/workspace/ats/resumes/import",
            content=b"{}",
            headers={"Content-Type": "application/json", "X-Filename": name},
        ).status_code
        == 422
    )
    assert not upstream[0]


@pytest.mark.parametrize(
    "media,body",
    [
        ("application/pdf", b"fake"),
        ("application/json", b"{"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"fake"),
        ("multipart/form-data", b"fake"),
    ],
)
def test_malformed_upload(api, upstream, media, body):
    login(api)
    assert api.post(
        "/workspace/ats/resumes/import", content=body, headers={"Content-Type": media}
    ).status_code in (415, 422)
    assert not upstream[0]


def test_upload_limit(api, settings):
    login(api)
    result = api.post(
        "/workspace/ats/resumes/import",
        content=b"x" * (settings.max_upload + 1),
        headers={"Content-Type": "application/pdf"},
    )
    assert result.status_code == 413


def test_json_upload_wrapper_name():
    assert (
        validate_upload(
            json.dumps({"profile": {}, "filename": "master.json"}).encode(),
            "application/json",
            "ignored.json",
        )
        == "master.json"
    )
