"""Same-origin single-operator session boundary and explicit ATS routes."""

import json
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from bff import models
from bff.config import COOKIE, Settings, load_password, load_token
from bff.contracts import OPERATIONS, validate_schema
from bff.store import Store, digest
from bff.uploads import MEDIA, validate_upload
from bff.upstream import client


async def bounded_body(request, maximum):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            raise HTTPException(413, "Request too large")
        data.extend(chunk)
    return bytes(data)


def json_body(data):
    try:
        # Reject nonstandard NaN/Infinity and duplicate keys.
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result

        return json.loads(
            data,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, "Invalid request") from None


def create_app(settings: Settings | None = None, transport=None, clock=time.time):
    @asynccontextmanager
    async def lifespan(app):
        conf = settings or Settings.environment()
        load_password(conf)
        load_token(conf)
        app.state.settings = conf
        app.state.store = Store(conf, clock)
        app.state.ats = transport or client(conf)
        yield
        await app.state.ats.aclose()

    app = FastAPI(
        title="Job Agent BFF",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        start = time.monotonic()
        try:
            if request.url.path.startswith("/workspace"):
                conf = app.state.settings
                if request.headers.getlist("host") != [urlsplit(conf.origin).netloc]:
                    raise HTTPException(403, "Request denied")
                forbidden = {
                    "authorization",
                    "forwarded",
                    "x-ssl-client-cert",
                    "x-ssl-client-verify",
                    "x-forwarded-client-cert",
                }
                if any(k in forbidden or k.startswith("x-ats-") for k in request.headers):
                    raise HTTPException(403, "Request denied")
                for name in (
                    "origin",
                    "sec-fetch-site",
                    "x-csrf-token",
                    "content-type",
                    "x-filename",
                    "cookie",
                ):
                    if len(request.headers.getlist(name)) > 1:
                        raise HTTPException(403, "Request denied")
                if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
                    raise HTTPException(403, "Request denied")
                origin = request.headers.get("origin")
                if origin is not None and origin != conf.origin:
                    raise HTTPException(403, "Request denied")
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    if origin != conf.origin or request.headers.get("sec-fetch-site") == "none":
                        raise HTTPException(403, "Request denied")
                if request.headers.get("content-encoding", "identity") != "identity":
                    raise HTTPException(415, "Unsupported encoding")
            response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        except (OSError, sqlite3.Error, ValueError):
            response = JSONResponse({"detail": "Service unavailable"}, status_code=503)
        if request.url.path.startswith("/workspace"):
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                }
            )
            route = request.scope.get("route")
            operation = request.method + " " + (route.path if route else "/workspace/denied")
            resource = ",".join(
                str(v)
                for v in request.path_params.values()
                if str(v).isascii() and str(v).isdigit() and len(str(v)) <= 18
            )
            try:
                app.state.store.audit(
                    operation,
                    resource,
                    response.status_code,
                    int((time.monotonic() - start) * 1000),
                )
            except (OSError, sqlite3.Error):
                return JSONResponse(
                    {"detail": "Service unavailable; reload state before retrying"},
                    status_code=503,
                    headers={"Cache-Control": "no-store"},
                )
        return response

    def authenticated(request):
        conf = app.state.settings
        credential = digest(load_password(conf))
        row = app.state.store.session(request.cookies.get(COOKIE), credential)
        if row is None:
            raise HTTPException(401, "Authentication required")
        return row

    def csrf_check(request, session):
        token = request.headers.get("x-csrf-token", "")
        if len(token) > 128 or not secrets.compare_digest(digest(token), session["csrf_hash"]):
            raise HTTPException(403, "Request denied")

    @app.get("/healthz", response_model=dict[str, bool])
    def health():
        with app.state.store.connection() as db:
            db.execute("SELECT 1 FROM sessions LIMIT 1")
        return {"ok": True}

    @app.post("/workspace/auth/login", response_model=models.Session)
    async def login(request: Request, response: Response):
        conf = app.state.settings
        if request.query_params:
            raise HTTPException(422, "Invalid request")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "Use application/json")
        if not app.state.store.attempt(request.client.host if request.client else "unknown"):
            raise HTTPException(
                429, "Try again later", headers={"Retry-After": str(conf.login_window)}
            )
        try:
            value = models.Login.model_validate(json_body(await bounded_body(request, 4096)))
        except ValidationError:
            raise HTTPException(422, "Invalid request") from None
        password_hash = load_password(conf)

        def verify():
            try:
                return PasswordHasher().verify(password_hash, value.password)
            except VerificationError:
                return False

        if not await run_in_threadpool(verify):
            raise HTTPException(401, "Authentication failed")
        token, _ = app.state.store.create(digest(password_hash), request.cookies.get(COOKIE))
        response.set_cookie(
            COOKIE,
            token,
            max_age=conf.absolute_seconds,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
        return models.Session(authenticated=True, operator_id=conf.operator_id)

    @app.get("/workspace/auth/session", response_model=models.Session)
    def session(request: Request):
        try:
            authenticated(request)
        except HTTPException as exc:
            if exc.status_code == 401:
                return models.Session(authenticated=False)
            raise
        return models.Session(authenticated=True, operator_id=app.state.settings.operator_id)

    @app.get("/workspace/auth/csrf", response_model=models.CSRF)
    def csrf(request: Request):
        authenticated(request)
        return models.CSRF(csrf_token=app.state.store.csrf(request.cookies[COOKIE]))

    @app.post("/workspace/auth/logout", status_code=204)
    async def logout(request: Request):
        row = authenticated(request)
        csrf_check(request, row)
        if request.query_params or await bounded_body(request, 1):
            raise HTTPException(422, "Invalid request")
        app.state.store.revoke(request.cookies[COOKIE])
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    def make_endpoint(op):
        async def endpoint(request: Request):
            conf = app.state.settings
            row = authenticated(request)
            path = request.url.path.removeprefix("/workspace/ats")
            if not op.match(request.method, path):
                raise HTTPException(422, "Invalid resource identifier")
            if op.scope not in conf.scopes:
                raise HTTPException(403, "Operation denied")
            if request.method != "GET":
                csrf_check(request, row)
            params = {}
            allowed = (
                {"limit", "offset"}
                if op.path in ("/resumes", "/jobs/{job_id}/resumes")
                else ({"format"} if op.response is bytes else set())
            )
            if any(
                k not in allowed or len(request.query_params.getlist(k)) != 1
                for k in request.query_params
            ):
                raise HTTPException(422, "Invalid query")
            for key, value in request.query_params.items():
                if key == "format":
                    if value not in ("pdf", "docx"):
                        raise HTTPException(422, "Invalid export format")
                elif (
                    not value.isascii()
                    or not value.isdigit()
                    or len(value) > 9
                    or (key == "limit" and not 1 <= int(value) <= 200)
                ):
                    raise HTTPException(422, "Invalid pagination")
                params[key] = value
            data = await bounded_body(
                request, conf.max_upload if op.body == "upload" else 1024 * 1024
            )
            headers = {
                "Authorization": "Bearer " + load_token(conf),
                "X-ATS-Operator": conf.operator_id,
            }
            if op.body:
                media = request.headers.get("content-type", "").split(";")[0].strip()
                if op.body == "upload":
                    if media == "application/json":
                        json_body(data)
                    name = request.headers.get(
                        "x-filename", "master." + MEDIA.get(media, "invalid")
                    )
                    try:
                        headers["X-Filename"] = validate_upload(data, media, name)
                    except SchemaError:
                        raise HTTPException(422, "Invalid request") from None
                else:
                    if media != "application/json":
                        raise HTTPException(415, "Use application/json")
                    try:
                        validate_schema(op.body, json_body(data))
                    except (SchemaError, RecursionError):
                        raise HTTPException(422, "Invalid request") from None
                headers["Content-Type"] = media
            elif data:
                raise HTTPException(422, "Unexpected body")
            try:
                async with app.state.ats.stream(
                    op.method, path, params=params, content=data, headers=headers
                ) as upstream:
                    if upstream.status_code != 200:
                        code = (
                            upstream.status_code
                            if upstream.status_code in (401, 403, 404, 409, 413, 415, 422, 502, 503)
                            else 502
                        )
                        raise HTTPException(
                            code, "Private operation failed; reload state before retrying"
                        )
                    body = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        if len(body) + len(chunk) > conf.max_response:
                            raise HTTPException(502, "Invalid private response")
                        body.extend(chunk)
                    if op.response is bytes:
                        extension = params.get("format", "pdf")
                        mime = next(k for k, v in MEDIA.items() if v == extension)
                        if upstream.headers.get("content-type", "").split(";")[0] != mime:
                            raise HTTPException(502, "Invalid private response")
                        identifier = request.path_params["version_id"]
                        state = upstream.headers.get("x-resume-state")
                        outgoing = {
                            "Content-Disposition": f'attachment; filename="resume-version-{identifier}.{extension}"'
                        }
                        if state in (
                            "draft",
                            "pending_review",
                            "approved",
                            "rejected",
                            "superseded",
                        ):
                            outgoing["X-Resume-State"] = state
                        return Response(bytes(body), media_type=mime, headers=outgoing)
                    if upstream.headers.get("content-type", "").split(";")[0] != "application/json":
                        raise HTTPException(502, "Invalid private response")
                    try:
                        value = json_body(body)
                    except HTTPException:
                        raise HTTPException(502, "Invalid private response") from None
                    TypeAdapter(op.response).validate_python(value)
                    if isinstance(value, dict) and "profile" in value:
                        validate_schema("ProfessionalProfile", value["profile"])
                    return JSONResponse(value)
            except (ValidationError, SchemaError):
                raise HTTPException(502, "Invalid private response") from None
            except httpx.HTTPError:
                raise HTTPException(
                    503, "Private service unavailable; reload state before retrying"
                ) from None

        return endpoint

    for op in OPERATIONS:
        app.add_api_route(
            "/workspace/ats" + op.path,
            make_endpoint(op),
            methods=[op.method],
            name=op.method.lower() + "_" + op.path.replace("/", "_"),
            response_model=None,
        )
    return app


app = create_app()
