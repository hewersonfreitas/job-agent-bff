"""Explicit, operator-session protected discovery administration routes."""

from typing import TypeVar

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, ValidationError

from bff import admin_models as models
from bff.config import load_admin_token

T = TypeVar("T", bound=BaseModel)


def create_router(authenticated, csrf_check):
    router = APIRouter(prefix="/workspace/admin", tags=["discovery-admin"])

    def authorize(request):
        session = authenticated(request)
        if "discovery:admin" not in request.app.state.settings.scopes:
            raise HTTPException(403, "Administrative operation denied")
        return session

    def check_query(request, allowed):
        if any(
            name not in allowed or len(request.query_params.getlist(name)) != 1
            for name in request.query_params
        ):
            raise HTTPException(422, "Invalid administrative query")

    async def require_empty_body(request):
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 1:
                raise HTTPException(413, "Unexpected administrative request body")
        if size:
            raise HTTPException(422, "Unexpected administrative request body")

    async def call(request, method, path, response_model, *, params=None, body=None, status=200):
        authorize(request)
        conf = request.app.state.settings
        try:
            token = load_admin_token(conf)
        except (OSError, UnicodeError, ValueError):
            raise HTTPException(503, "Administrative service unavailable") from None
        headers = {"Authorization": "Bearer " + token}
        timeout = None
        if method == "POST" and path == "/admin/collections/run":
            timeout = httpx.Timeout(connect=5, read=1850, write=10, pool=5)
        try:
            response = await request.app.state.admin_http.request(
                method,
                path,
                params=params,
                json=body,
                headers=headers,
                timeout=timeout,
            )
        except (httpx.HTTPError, OSError):
            raise HTTPException(503, "Administrative service unavailable") from None
        if response.status_code != status:
            code = response.status_code
            if code not in (401, 403, 404, 409, 422, 502, 503):
                code = 502
            messages = {
                401: "Administrative service authentication failed",
                403: "Administrative operation denied",
                404: "Administrative resource not found",
                409: "Administrative operation conflicts with current state",
                422: "Invalid administrative request",
                502: "Administrative service failed",
                503: "Administrative service unavailable",
            }
            raise HTTPException(code, messages[code])
        try:
            return response_model.model_validate(response.json())
        except (ValueError, ValidationError, TypeError):
            raise HTTPException(502, "Invalid administrative service response") from None

    @router.get("/sources", response_model=models.SourcePage)
    async def list_sources(
        request: Request,
        provider: models.AdminProvider | None = None,
        active: bool | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        check_query(request, {"provider", "active", "limit", "offset"})
        params = {
            k: v
            for k, v in {
                "provider": provider,
                "active": active,
                "limit": limit,
                "offset": offset,
            }.items()
            if v is not None
        }
        return await call(request, "GET", "/admin/sources", models.SourcePage, params=params)

    @router.post("/sources", response_model=models.ManagedSource, status_code=201)
    async def add_source(request: Request, value: models.SourceInput):
        check_query(request, set())
        session = authorize(request)
        csrf_check(request, session)
        return await call(
            request,
            "POST",
            "/admin/sources",
            models.ManagedSource,
            body=value.model_dump(),
            status=201,
        )

    @router.post("/sources/import", response_model=models.ImportResult)
    async def import_sources(request: Request):
        check_query(request, set())
        session = authorize(request)
        csrf_check(request, session)
        await require_empty_body(request)
        return await call(request, "POST", "/admin/sources/import", models.ImportResult)

    @router.get("/sources/{source_id}", response_model=models.ManagedSource)
    async def get_source(request: Request, source_id: int = Path(..., gt=0)):
        check_query(request, set())
        return await call(request, "GET", f"/admin/sources/{source_id}", models.ManagedSource)

    @router.patch("/sources/{source_id}", response_model=models.ManagedSource)
    async def edit_source(
        request: Request, value: models.SourcePatch, source_id: int = Path(..., gt=0)
    ):
        check_query(request, set())
        session = authorize(request)
        csrf_check(request, session)
        return await call(
            request,
            "PATCH",
            f"/admin/sources/{source_id}",
            models.ManagedSource,
            body=value.model_dump(exclude_unset=True),
        )

    @router.get("/sources/{source_id}/errors", response_model=models.ErrorPage)
    async def source_errors(
        request: Request,
        source_id: int = Path(..., gt=0),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        check_query(request, {"limit", "offset"})
        return await call(
            request,
            "GET",
            f"/admin/sources/{source_id}/errors",
            models.ErrorPage,
            params={"limit": limit, "offset": offset},
        )

    @router.get("/collections/status", response_model=models.AutomationStatus)
    async def collection_status(request: Request):
        check_query(request, set())
        return await call(request, "GET", "/admin/collections/status", models.AutomationStatus)

    @router.post("/collections/run", response_model=models.ManualResult)
    async def run_collection(request: Request):
        check_query(request, set())
        session = authorize(request)
        csrf_check(request, session)
        await require_empty_body(request)
        return await call(request, "POST", "/admin/collections/run", models.ManualResult)

    @router.post("/collections/start", response_model=models.CollectionAccepted, status_code=202)
    async def start_collection(request: Request, value: models.CollectionStartRequest):
        check_query(request, set())
        session = authorize(request)
        csrf_check(request, session)
        return await call(
            request,
            "POST",
            "/admin/collections/start",
            models.CollectionAccepted,
            body=value.model_dump(),
            status=202,
        )

    @router.get("/collections/runs", response_model=models.RunPage)
    async def collection_runs(
        request: Request,
        source_id: int | None = Query(None, gt=0),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        check_query(request, {"source_id", "limit", "offset"})
        params = {"limit": limit, "offset": offset}
        if source_id is not None:
            params["source_id"] = source_id
        return await call(request, "GET", "/admin/collections/runs", models.RunPage, params=params)

    @router.get("/collections/runs/{run_id}", response_model=models.RunDetail)
    async def run_detail(request: Request, run_id: int = Path(..., gt=0)):
        check_query(request, set())
        return await call(request, "GET", f"/admin/collections/runs/{run_id}", models.RunDetail)

    @router.get("/collections/errors", response_model=models.ErrorPage)
    async def collection_errors(
        request: Request,
        source_id: int | None = Query(None, gt=0),
        run_id: int | None = Query(None, gt=0),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        check_query(request, {"source_id", "run_id", "limit", "offset"})
        params = {"limit": limit, "offset": offset}
        if source_id is not None:
            params["source_id"] = source_id
        if run_id is not None:
            params["run_id"] = run_id
        return await call(
            request, "GET", "/admin/collections/errors", models.ErrorPage, params=params
        )

    return router
