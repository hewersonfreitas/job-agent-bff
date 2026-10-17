import json
from contextlib import contextmanager

import httpx
from fastapi.testclient import TestClient

from bff.app import create_app
from tests.conftest import ORIGIN, login

TOKEN = "a" * 43


def source():
    return {
        "id": 7,
        "provider": "greenhouse",
        "token": "public-board-id",
        "company": "Synthetic Employer",
        "active": True,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "last_collected_at": None,
        "last_result": None,
    }


@contextmanager
def application(settings, calls, code=200, payload=None):
    def handler(request):
        calls.append(request)
        if payload is not None:
            return httpx.Response(code, json=payload)
        if request.method == "POST" and request.url.path == "/admin/sources":
            return httpx.Response(201, json=source())
        if request.method == "POST" and request.url.path == "/admin/sources/import":
            return httpx.Response(
                200, json={"created": 2, "skipped": 1, "configuration_mode": "database"}
            )
        if request.method == "POST" and request.url.path == "/admin/collections/run":
            return httpx.Response(
                200, json={"run_id": 9, "imported": {}, "errors": [], "requests": 0}
            )
        if request.method == "POST" and request.url.path == "/admin/collections/start":
            return httpx.Response(
                202,
                json={
                    "run_id": 10,
                    "status": "running",
                    "selected_source_ids": [7],
                    "started_at": "2026-01-01T00:00:00Z",
                },
            )
        if request.method == "GET" and request.url.path == "/admin/collections/status":
            return httpx.Response(
                200,
                json={
                    "configuration_mode": "legacy",
                    "scheduler_enabled": False,
                    "interval_seconds": 3600,
                    "scheduler_task_running": False,
                    "scheduler_last_error": None,
                    "running": False,
                    "lease_expires_at": None,
                    "next_run_at": None,
                    "last_run": None,
                },
            )
        return httpx.Response(
            200, json={"items": [source()], "total": 1, "limit": 50, "offset": 0, "has_next": False}
        )

    ats = httpx.AsyncClient(
        base_url="https://ats-service:8766",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[])),
    )
    with TestClient(
        create_app(settings, ats, admin_transport=httpx.MockTransport(handler)),
        base_url=ORIGIN,
    ) as browser:
        browser.headers.update({"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"})
        yield browser


def test_admin_route_requires_operator_session(settings):
    calls = []
    with application(settings, calls) as browser:
        response = browser.get("/workspace/admin/sources")
        assert response.status_code == 401
        assert not calls


def test_session_admin_call_adds_server_secret_only(settings, caplog):
    calls = []
    with application(settings, calls) as browser:
        login(browser)
        response = browser.get("/workspace/admin/sources", params={"provider": "greenhouse"})
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["company"] == "Synthetic Employer"
        upstream = calls[0]
        assert upstream.url.host == "api"
        assert upstream.headers["authorization"] == "Bearer " + TOKEN
        for name in ("cookie", "origin", "sec-fetch-site", "x-csrf-token"):
            assert name not in upstream.headers
        assert TOKEN not in response.text
        assert TOKEN not in caplog.text
        assert response.headers["cache-control"] == "no-store"


def test_browser_cannot_supply_backend_bearer(settings):
    calls = []
    with application(settings, calls) as browser:
        login(browser)
        response = browser.get(
            "/workspace/admin/sources", headers={"Authorization": "Bearer " + TOKEN}
        )
        assert response.status_code == 403
        assert TOKEN not in response.text
        assert not calls


def test_admin_write_requires_valid_csrf_and_preserves_contract(settings):
    calls = []
    with application(settings, calls) as browser:
        login(browser)
        browser.headers["X-CSRF-Token"] = "invalid"
        rejected = browser.post(
            "/workspace/admin/sources",
            json={
                "provider": "greenhouse",
                "token": "public-board-id",
                "company": "Synthetic Employer",
            },
        )
        assert rejected.status_code == 403
        assert not calls
        login(browser)
        accepted = browser.post(
            "/workspace/admin/sources",
            json={
                "provider": "greenhouse",
                "token": "public-board-id",
                "company": "Synthetic Employer",
            },
        )
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["id"] == 7
        assert len(calls) == 1
        assert calls[0].method == "POST"
        assert calls[0].url.path == "/admin/sources"


def test_explicit_import_and_manual_collection_are_session_and_csrf_gated(settings):
    calls = []
    with application(settings, calls) as browser:
        login(browser)
        imported = browser.post("/workspace/admin/sources/import")
        assert imported.status_code == 200
        assert imported.json() == {
            "created": 2,
            "skipped": 1,
            "configuration_mode": "database",
        }
        assert (
            browser.get("/workspace/admin/collections/status").json()["scheduler_enabled"] is False
        )
        run = browser.post("/workspace/admin/collections/run")
        assert run.status_code == 200
        assert run.json()["run_id"] == 9
        assert [call.url.path for call in calls] == [
            "/admin/sources/import",
            "/admin/collections/status",
            "/admin/collections/run",
        ]


def test_async_collection_start_is_session_csrf_and_payload_gated(settings):
    calls = []
    with application(settings, calls) as browser:
        assert (
            browser.post("/workspace/admin/collections/start", json={"source_ids": [7]}).status_code
            == 401
        )
        login(browser)
        browser.headers["X-CSRF-Token"] = "invalid"
        rejected = browser.post("/workspace/admin/collections/start", json={"source_ids": [7]})
        assert rejected.status_code == 403 and not calls
        login(browser)
        invalid = browser.post("/workspace/admin/collections/start", json={"source_ids": [7, 7]})
        assert invalid.status_code == 422 and not calls
        accepted = browser.post("/workspace/admin/collections/start", json={"source_ids": [7]})
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["run_id"] == 10
        assert accepted.json()["selected_source_ids"] == [7]
        assert len(calls) == 1
        assert calls[0].url.path == "/admin/collections/start"
        assert json.loads(calls[0].content) == {"source_ids": [7]}
        assert calls[0].headers["authorization"] == "Bearer " + TOKEN
        assert TOKEN not in accepted.text


def test_admin_input_and_query_are_allowlisted(settings):
    calls = []
    with application(settings, calls) as browser:
        login(browser)
        assert browser.get("/workspace/admin/sources?unexpected=x").status_code == 422
        assert browser.get("/workspace/admin/collections/status?unexpected=x").status_code == 422
        assert browser.post("/workspace/admin/sources/import?unexpected=x").status_code == 422
        assert (
            browser.post(
                "/workspace/admin/sources",
                json={"provider": "unknown", "token": "x", "company": "Company", "extra": True},
            ).status_code
            == 422
        )
        assert not calls


def test_admin_missing_credential_and_upstream_failure_are_sanitized(settings):
    calls = []
    original_settings = settings
    settings = original_settings.model_copy(update={"admin_token_file": None})
    with application(settings, calls) as browser:
        login(browser)
        result = browser.get("/workspace/admin/sources")
        assert result.status_code == 503
        assert not calls

    settings = original_settings
    calls = []
    with application(settings, calls, code=401, payload={"detail": TOKEN}) as browser:
        login(browser)
        result = browser.get("/workspace/admin/sources")
        assert result.status_code == 401
        assert TOKEN not in result.text
