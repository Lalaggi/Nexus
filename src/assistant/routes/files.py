"""Upload handling and read-only serving of user-visible files."""

from __future__ import annotations

import io
import mimetypes
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..config import CONFIG
from ..db import Database
from ..tools.files import TEXT_SUFFIXES, _resolve, safe_filename

router = APIRouter(prefix="/api/files", tags=["files"])
upload_router = APIRouter(prefix="/api", tags=["uploads"])

# Never render these inline on the app's origin. User/model-controlled HTML,
# SVG, or JavaScript could otherwise run with access to the chat API.
ACTIVE_SUFFIXES = {
    ".html",
    ".htm",
    ".xhtml",
    ".xht",
    ".svg",
    ".svgz",
    ".xml",
    ".xsl",
    ".xslt",
    ".js",
    ".mjs",
    ".cjs",
}


def db_of(request: Request) -> Database:
    return request.app.state.db


def _chat_dir(chat_id: str, kind: str) -> Path:
    return CONFIG.chat_outputs_dir(chat_id) if kind == "outputs" else CONFIG.chat_uploads_dir(chat_id)


async def _require_chat(request: Request, chat_id: str) -> None:
    if await db_of(request).get_chat(chat_id) is None:
        raise HTTPException(404, "Chat not found")


def _unique_name(directory: Path, name: str) -> str:
    candidate = name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 2
    while (directory / candidate).exists():
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
        if counter > 500:
            raise HTTPException(409, "Too many files with that name.")
    return candidate


def _extract_text(name: str, mime: str, raw: bytes) -> str:
    suffix = Path(name).suffix.lower()
    if mime.startswith("image/") or mime.startswith("video/") or mime.startswith("audio/"):
        return ""
    if suffix == ".pdf" or mime == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages[:60])[:100_000]
        except Exception:
            return ""
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                xml = archive.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            text = re.sub(r"<[^>]+>", "", xml)
            return text[:100_000]
        except Exception:
            return ""
    if suffix in TEXT_SUFFIXES or mime.startswith("text/") or mime in {
        "application/json",
        "application/xml",
        "application/x-yaml",
    }:
        if b"\x00" in raw[:4096]:
            return ""
        return raw.decode("utf-8", "replace")[:100_000]
    return ""


def _mime_for(name: str, provided: str | None) -> str:
    if provided and provided != "application/octet-stream":
        return provided
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def _file_response(file_path: Path, download: bool = False) -> FileResponse:
    suffix = file_path.suffix.lower()
    active = suffix in ACTIVE_SUFFIXES
    media_type = (
        "text/plain" if active else (mimetypes.guess_type(file_path.name)[0] or "application/octet-stream")
    )
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=file_path.name,
        content_disposition_type="attachment" if (download or active) else "inline",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=60",
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:",
        },
    )


@upload_router.post("/uploads")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    chat_id: str | None = Form(None),
):
    if chat_id:
        await _require_chat(request, chat_id)
        directory = CONFIG.chat_uploads_dir(chat_id)
        directory.mkdir(parents=True, exist_ok=True)
        url_base = f"/api/files/chats/{quote(chat_id)}/uploads"
    else:
        directory = CONFIG.uploads_dir
        directory.mkdir(parents=True, exist_ok=True)
        url_base = "/api/files/uploads"

    db = db_of(request)
    limit = CONFIG.max_upload_mb * 1024 * 1024
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, f"File is larger than {CONFIG.max_upload_mb} MB.")
    if not raw:
        raise HTTPException(400, "File is empty.")

    name = safe_filename(file.filename or "upload")
    mime = _mime_for(name, file.content_type)
    name = _unique_name(directory, name)
    destination = directory / name
    destination.write_bytes(raw)
    text = _extract_text(name, mime, raw)
    record = await db.add_upload(name, mime, len(raw), text, chat_id)
    return {
        **record,
        "url": f"{url_base}/{quote(name)}",
        "kind": "uploads",
        "has_text": bool(text),
    }


@router.get("/list")
async def list_files(request: Request, kind: str = "outputs", chat_id: str | None = None) -> dict:
    if kind not in {"outputs", "uploads"}:
        raise HTTPException(400, "kind must be outputs or uploads")
    if not chat_id:
        return {"files": [], "kind": kind}
    await _require_chat(request, chat_id)
    base = _chat_dir(chat_id, kind)
    base.mkdir(parents=True, exist_ok=True)
    files = []
    for path in base.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        relative = path.relative_to(base).as_posix()
        files.append(
            {
                "name": path.name,
                "path": relative,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "url": f"/api/files/chats/{quote(chat_id)}/{kind}/{quote(relative)}",
                "kind": kind,
                "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            }
        )
    files.sort(key=lambda item: item["mtime"], reverse=True)
    return {"files": files[:400], "kind": kind}


@router.get("/chats/{chat_id}/{kind}/{path:path}")
async def serve_chat_file(
    request: Request,
    chat_id: str,
    kind: str,
    path: str,
    download: bool = False,
):
    if kind not in {"outputs", "uploads"}:
        raise HTTPException(404, "Unknown file area")
    await _require_chat(request, chat_id)
    base = _chat_dir(chat_id, kind)
    try:
        file_path = _resolve(path, base)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not file_path.is_file():
        # Compatibility for links from chats created before files became
        # per-chat. New files never live in these legacy folders.
        legacy = CONFIG.outputs_dir if kind == "outputs" else CONFIG.uploads_dir
        try:
            legacy_path = _resolve(path, legacy)
        except ValueError:
            legacy_path = None
        if legacy_path is None or not legacy_path.is_file():
            raise HTTPException(404, "File not found")
        file_path = legacy_path
    return _file_response(file_path, download)


@router.get("/{kind}/{path:path}")
async def serve_legacy_file(
    request: Request,
    kind: str,
    path: str,
    download: bool = False,
):
    if kind not in {"outputs", "uploads"}:
        raise HTTPException(404, "Unknown file area")
    base = CONFIG.outputs_dir if kind == "outputs" else CONFIG.uploads_dir
    try:
        file_path = _resolve(path, base)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not file_path.is_file():
        # Fall back to per-chat directories: files written after per-chat
        # isolation live under data/home/<kind>/<chat_id>/<path>, but old
        # file:// links only encode the kind and relative path. Search all
        # chat subdirectories for a matching relative path.
        search_root = CONFIG.outputs_dir if kind == "outputs" else CONFIG.uploads_dir
        if search_root.exists():
            for chat_dir in sorted(search_root.iterdir(), reverse=True):
                if not chat_dir.is_dir():
                    continue
                try:
                    candidate = _resolve(path, chat_dir)
                except ValueError:
                    continue
                if candidate.is_file():
                    file_path = candidate
                    break
            else:
                raise HTTPException(404, "File not found")
        else:
            raise HTTPException(404, "File not found")
    return _file_response(file_path, download)
