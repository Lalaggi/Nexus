"""FastAPI application entry point."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import CONFIG
from .db import Database
from .routes import chats, files, notes, settings
from .tools.base import load_builtin_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs every request at INFO; that clutters the debug log. Silence the
# request trace while keeping the application's own error logging intact.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("nexus")

PUBLIC_API = {"/api/login", "/api/auth", "/api/health"}


def _session_token() -> str:
    if CONFIG.password:
        return hmac.new(
            CONFIG.password.encode("utf-8"), b"nexus-session-v1", hashlib.sha256
        ).hexdigest()
    return secrets.token_urlsafe(32)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_builtin_tools()
    db = Database(CONFIG.db_path)
    await db.connect()
    app.state.db = db
    app.state.session_token = _session_token()
    logger.info("data=%s uploads=%s outputs=%s", CONFIG.data_dir, CONFIG.uploads_dir, CONFIG.outputs_dir)
    logger.info(
        "database encryption enabled (%s)",
        "ASSISTANT_ENCRYPTION_KEY"
        if CONFIG.encryption_key.strip()
        else f"key file: {CONFIG.secret_key_path}",
    )
    if CONFIG.password:
        logger.info("password protection is enabled")
    else:
        logger.warning("no ASSISTANT_PASSWORD set; bind to 127.0.0.1 or put this behind a reverse proxy")
    yield
    await db.close()


app = FastAPI(title="Nexus", version="0.1.0", lifespan=lifespan, docs_url="/api/docs")


def _request_token(request: Request) -> str:
    """Session token from the web cookie, a bearer header, or a file URL.

    The packaged Android app runs on https://localhost, so it cannot use the
    web app's same-site cookie. It sends Authorization: Bearer instead, and
    appends ?access_token= to file URLs loaded by <img>/<iframe>/download links
    where a header cannot be attached.
    """
    cookie = request.cookies.get("assistant_session", "")
    if cookie:
        return cookie
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    if request.method == "GET" and request.url.path.startswith("/api/files/"):
        return request.query_params.get("access_token", "")
    return ""


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    request.state.authenticated = False
    if request.method == "OPTIONS":
        # CORS preflight never carries credentials.
        return await call_next(request)
    if CONFIG.password and request.url.path.startswith("/api/"):
        supplied = _request_token(request)
        request.state.authenticated = hmac.compare_digest(supplied, request.app.state.session_token)
        if not request.state.authenticated and request.url.path not in PUBLIC_API:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
    else:
        request.state.authenticated = True
    return await call_next(request)


# Added after the auth middleware so CORS wraps it and can answer preflight
# requests and add headers to 401 responses. The app does not use cookies
# cross-origin; auth is a bearer token.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG.cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    expose_headers=["Content-Disposition"],
    max_age=3600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), usb=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'self'; "
        "form-action 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' http: https:; "
        "font-src 'self' data:; frame-src 'self' blob:",
    )
    return response


app.include_router(chats.router)
app.include_router(files.router)
app.include_router(files.upload_router)
app.include_router(notes.router)
app.include_router(settings.router)


@app.get("/api")
async def api_root() -> dict:
    return {"name": "Nexus", "version": "0.1.0"}


if (CONFIG.web_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=CONFIG.web_dist / "assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
async def index():
    target = CONFIG.web_dist / "index.html"
    if target.exists():
        return FileResponse(target)
    return HTMLResponse(
        """
        <html><body style="font-family:system-ui;background:#141218;color:#e6e0e9;padding:3rem">
        <h1>Nexus API is running</h1>
        <p>The web UI has not been built yet. Run <code>npm --prefix web install && npm --prefix web run build</code>,
        then restart the server. For development, run <code>npm --prefix web run dev</code> and open port 5173.</p>
        </body></html>
        """
    )


@app.get("/{path:path}")
async def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    target = CONFIG.web_dist / "index.html"
    if target.exists():
        return FileResponse(target)
    return JSONResponse({"detail": "UI not built"}, status_code=404)
