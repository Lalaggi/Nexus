"""FastAPI application entry point."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import CONFIG
from .db import Database
from .routes import chats, files, settings
from .tools.base import load_builtin_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("assistant")

PUBLIC_API = {"/api/login", "/api/auth", "/api/health"}


def _session_token() -> str:
    if CONFIG.password:
        return hmac.new(
            CONFIG.password.encode("utf-8"), b"assistant-session-v1", hashlib.sha256
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
    if CONFIG.password:
        logger.info("password protection is enabled")
    else:
        logger.warning("no ASSISTANT_PASSWORD set; bind to 127.0.0.1 or put this behind a reverse proxy")
    yield
    await db.close()


app = FastAPI(title="Assistant", version="0.1.0", lifespan=lifespan, docs_url="/api/docs")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    request.state.authenticated = False
    if CONFIG.password and request.url.path.startswith("/api/"):
        cookie = request.cookies.get("assistant_session", "")
        request.state.authenticated = hmac.compare_digest(cookie, request.app.state.session_token)
        if not request.state.authenticated and request.url.path not in PUBLIC_API:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
    else:
        request.state.authenticated = True
    return await call_next(request)


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
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "font-src 'self' data:; frame-src 'self' blob:",
    )
    return response


app.include_router(chats.router)
app.include_router(files.router)
app.include_router(files.upload_router)
app.include_router(settings.router)


@app.get("/api")
async def api_root() -> dict:
    return {"name": "Assistant", "version": "0.1.0"}


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
        <h1>Assistant API is running</h1>
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
