"""File tools constrained to the current chat's uploads, outputs, and workspace."""

from __future__ import annotations

import asyncio
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from ..config import CONFIG
from ..media import (
    MediaError,
    extract_pdf_text,
    is_image_suffix,
    is_pdf_suffix,
    render_media,
)
from .base import Tool, ToolContext, ToolResult, register

TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".log", ".xml", ".html", ".htm", ".css", ".js", ".jsx",
    ".ts", ".tsx", ".py", ".rb", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".sh",
    ".sql", ".tex", ".rst", ".srt", ".vtt",
}


def safe_filename(name: str, fallback: str = "file") -> str:
    name = unicodedata.normalize("NFC", os.path.basename(name or ""))
    name = name.replace("\\", "-").replace("/", "-")
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if not name or name in {".", ".."}:
        name = fallback
    return name[:180]


def _sandbox_roots(chat_id: str | None) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    if chat_id:
        roots.extend(
            [
                (CONFIG.chat_outputs_dir(chat_id), "/mnt/outputs"),
                (CONFIG.chat_uploads_dir(chat_id), "/mnt/useruploads"),
                (CONFIG.chat_workspace_dir(chat_id), "/workspace"),
            ]
        )
    return roots


def _sandbox_path(path: Path, chat_id: str | None = None) -> str:
    """Express a host path as the path the sandbox sees.

    The model only ever sees /mnt/outputs, /mnt/useruploads, and /workspace;
    keeping host paths out of tool results avoids leaking the machine's layout
    into chat.
    """
    resolved = path.resolve()
    for root, prefix in _sandbox_roots(chat_id):
        base = root.resolve()
        if resolved == base:
            return prefix
        if resolved.is_relative_to(base):
            relative = resolved.relative_to(base).as_posix()
            return f"{prefix}/{relative}"
    # Never expose the host filesystem layout, even on an unexpected path.
    return "<outside-sandbox>"


def _file_url(path: Path, chat_id: str | None = None) -> str:
    sandbox = _sandbox_path(path, chat_id)
    if sandbox.startswith(("/mnt/outputs/", "/mnt/useruploads/")):
        return "file://" + quote(sandbox, safe="/")
    return ""


def _markdown_link(path: Path, chat_id: str | None = None) -> str:
    return f"[{path.name}]({_file_url(path, chat_id)})"


def _resolve(path_text: str, base: Path) -> Path:
    token = unquote(path_text.strip())
    if token.startswith("file://"):
        token = urlparse(token).path
    candidate = Path(token).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    root = base.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Paths must stay inside the allowed folder.")
    return resolved


def _relative_target(path_text: str, chat_id: str) -> Path:
    token = unquote(path_text.strip())
    if token.startswith("file://"):
        token = urlparse(token).path
    if token.startswith("/mnt/outputs/"):
        token = token[len("/mnt/outputs/") :]
    elif token.startswith("/mnt/useruploads"):
        raise ValueError("Uploads are read-only. Write to /mnt/outputs instead.")
    elif token == "/mnt/outputs":
        token = ""
    candidate = Path(token)
    if candidate.is_absolute():
        absolute = candidate.resolve()
        root = CONFIG.chat_outputs_dir(chat_id).resolve()
        if absolute.is_relative_to(root):
            return absolute.relative_to(root)
        raise ValueError("Output files must stay inside the outputs folder.")
    parts = []
    for part in candidate.parts:
        if part in {"", ".", ".."}:
            raise ValueError("Relative paths cannot contain '.' or '..'.")
        parts.append(safe_filename(part))
    if not parts:
        raise ValueError("A filename is required.")
    return Path(*parts)


def _file_entry(path: Path, chat_id: str) -> dict[str, str]:
    return {
        "name": path.name,
        "path": _sandbox_path(path, chat_id),
        "url": _file_url(path, chat_id),
    }


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _candidates(token: str, chat_id: str) -> list[Path]:
    outputs = CONFIG.chat_outputs_dir(chat_id)
    uploads = CONFIG.chat_uploads_dir(chat_id)
    workspace = CONFIG.chat_workspace_dir(chat_id)
    roots = (
        ("/mnt/outputs", outputs),
        ("/mnt/useruploads", uploads),
        ("/workspace", workspace),
    )
    candidates: list[Path] = []

    for prefix, base in roots:
        if token == prefix or token.startswith(prefix + "/"):
            relative = token[len(prefix) :].lstrip("/")
            candidate = (base / relative).resolve()
            if candidate.is_relative_to(base.resolve()):
                candidates.append(candidate)
            return candidates

    if Path(token).is_absolute():
        absolute = Path(token).resolve()
        for _prefix, root in roots:
            if absolute.is_relative_to(root.resolve()):
                candidates.append(absolute)
                break
    else:
        relative = Path(token)
        for _prefix, base in roots:
            candidate = (base / relative).resolve()
            if candidate.is_relative_to(base.resolve()):
                candidates.append(candidate)
    return candidates


# --------------------------------------------------------------------- tools
WRITE_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Destination filename inside this chat's outputs folder, optionally with "
                "subfolders, e.g. 'report.md', 'charts/sales.png', or '/mnt/outputs/report.md'."
            ),
        },
        "content": {"type": "string", "description": "Full UTF-8 file content."},
    },
    "required": ["path", "content"],
}


async def write_file(ctx: ToolContext, args: dict) -> ToolResult:
    target = _relative_target(str(args.get("path", "")), ctx.chat_id)
    content = args.get("content")
    if not isinstance(content, str):
        return ToolResult(content="content must be a string.", ok=False)
    if len(content.encode("utf-8")) > 8_000_000:
        return ToolResult(content="File is too large (8 MB limit for write_file).", ok=False)

    base = CONFIG.chat_outputs_dir(ctx.chat_id)
    destination = (base / target).resolve()
    if not destination.is_relative_to(base.resolve()):
        return ToolResult(content="Invalid destination path.", ok=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(destination)
    size = destination.stat().st_size
    return ToolResult(
        content=(
            f"Wrote {target.as_posix()} ({_human_size(size)}) to the outputs folder.\n"
            f"Link it for the user exactly as: {_markdown_link(destination, ctx.chat_id)}"
        ),
        summary=f"Wrote {target.as_posix()}",
        data={
            "path": _sandbox_path(destination, ctx.chat_id),
            "url": _file_url(destination, ctx.chat_id),
            "name": destination.name,
            "content": content[:20_000],
        },
    )


READ_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "File to read. A bare filename is looked up in outputs, uploads, then the "
                "workspace. Paths like /mnt/outputs/report.md, /mnt/useruploads/notes.txt, "
                "and /workspace/script.py also work. Images (PNG/JPEG/WebP/GIF/BMP/TIFF) "
                "and PDFs are returned as native visual content for vision-capable models."
            ),
        },
        "max_chars": {"type": "integer", "minimum": 1000, "maximum": 100000},
    },
    "required": ["path"],
}


async def _read_visual(
    ctx: ToolContext, path: Path, max_chars: int
) -> ToolResult:
    """Return an image/PDF as native visual content for a vision model."""
    sandbox_path = _sandbox_path(path, ctx.chat_id)
    suffix = path.suffix.lower()

    if not (CONFIG.vision_enabled and ctx.supports_vision):
        if is_pdf_suffix(suffix):
            text = await asyncio.to_thread(extract_pdf_text, path, max_chars)
            if text:
                return ToolResult(
                    content=f"Contents of {sandbox_path} (text layer only):\n\n{text}",
                    summary=f"Read {path.name}",
                    data={
                        "path": sandbox_path,
                        "name": path.name,
                        "url": _file_url(path, ctx.chat_id),
                    },
                )
            return ToolResult(
                content=(
                    f"{path.name} has no extractable text layer, and this model cannot "
                    "view page images natively. Use the sandbox to OCR or convert it."
                ),
                ok=False,
                summary="No text layer",
            )
        return ToolResult(
            content=(
                f"This model cannot view images natively, so {path.name} was not opened. "
                "Use the sandbox with OCR or an image-analysis script instead."
            ),
            ok=False,
            summary="No vision support",
        )

    try:
        rendered = await asyncio.to_thread(render_media, path)
    except MediaError as exc:
        return ToolResult(content=str(exc), ok=False, summary="Media failed")
    except Exception as exc:  # rendering must never kill the stream
        return ToolResult(
            content=f"Could not render {path.name}: {type(exc).__name__}: {exc}",
            ok=False,
            summary="Media failed",
        )

    if not rendered.items:
        return ToolResult(
            content=f"{path.name} could not be rendered into an image.",
            ok=False,
            summary="Media failed",
        )

    if rendered.kind == "image":
        item = rendered.items[0]
        content = (
            f"Opened {path.name} as an image ({item['width']}x{item['height']}). "
            "Its visual content is attached to the conversation below."
        )
        summary = f"Viewed {path.name}"
    else:
        lines = [
            f"Opened {path.name}: {rendered.page_count} page(s). "
            f"{len(rendered.items)} page image(s) are attached below."
        ]
        if rendered.truncated:
            lines.append(
                f"[Only the first {len(rendered.items)} page(s) were rendered to keep "
                "the request small.]"
            )
        if rendered.text:
            lines.append(
                "Extracted text (up to 60 pages):\n\n" + rendered.text[:max_chars]
            )
        content = "\n\n".join(lines)
        summary = f"Viewed {len(rendered.items)} page(s) of {path.name}"

    return ToolResult(
        content=content,
        summary=summary,
        data={
            "path": sandbox_path,
            "name": path.name,
            "url": _file_url(path, ctx.chat_id),
            "pages": rendered.page_count,
        },
        media=rendered.items,
    )


async def read_file(ctx: ToolContext, args: dict) -> ToolResult:
    path_text = str(args.get("path", "")).strip()
    if not path_text:
        return ToolResult(content="A path is required.", ok=False)
    try:
        max_chars = max(1000, min(100_000, int(args.get("max_chars") or 30_000)))
    except (TypeError, ValueError):
        max_chars = 30_000

    token = path_text
    if token.startswith("file://"):
        token = urlparse(token).path

    candidates = _candidates(token, ctx.chat_id)
    existing = next((p for p in candidates if p.is_file()), None)
    if existing is None:
        if any(p.is_dir() for p in candidates):
            return ToolResult(
                content=f"{path_text} is a folder, not a file. Use list_files to see its contents.",
                ok=False,
                summary="Folder",
            )
        return ToolResult(
            content=f"File not found: {path_text}. Use list_files to see available files.",
            ok=False,
            summary="Not found",
        )

    suffix = existing.suffix.lower()
    if is_image_suffix(suffix) or is_pdf_suffix(suffix):
        return await _read_visual(ctx, existing, max_chars)

    # Read only what can be returned. Decoding the whole file first (the old
    # behaviour) made a large upload an OOM vector even though max_chars caps
    # the output. Four bytes is the UTF-8 worst case per character.
    read_limit = max_chars * 4 + 4096
    file_size = existing.stat().st_size
    with existing.open("rb") as handle:
        head = handle.read(4096)
        if b"\x00" in head:
            return ToolResult(
                content=(
                    f"{existing.name} is binary data, and read_file only returns UTF-8 text "
                    "for non-image files. Inspect it with the sandbox instead (for example "
                    "`file`, `unzip -l`, or a small Python script)."
                ),
                ok=False,
                summary="Binary file",
            )
        raw = head + handle.read(max(0, read_limit - len(head)))
    truncated_file = file_size > len(raw)
    text = raw.decode("utf-8", "replace")
    clipped = text[:max_chars]
    suffix = ""
    if truncated_file:
        suffix = (
            f"\n\n[Truncated: showing the first {max_chars:,} characters of a "
            f"{_human_size(file_size)} file.]"
        )
    elif len(text) > len(clipped):
        suffix = f"\n\n[Truncated at {max_chars:,} of {len(text):,} characters.]"
    return ToolResult(
        content=f"Contents of {_sandbox_path(existing, ctx.chat_id)}:\n\n{clipped}{suffix}",
        summary=f"Read {existing.name}",
        data={
            "path": _sandbox_path(existing, ctx.chat_id),
            "name": existing.name,
            "url": _file_url(existing, ctx.chat_id),
        },
    )


LIST_PARAMETERS = {"type": "object", "properties": {}, "required": []}


async def list_files(ctx: ToolContext, args: dict) -> ToolResult:
    uploads_dir = CONFIG.chat_uploads_dir(ctx.chat_id)
    outputs_dir = CONFIG.chat_outputs_dir(ctx.chat_id)
    workspace_dir = CONFIG.chat_workspace_dir(ctx.chat_id)

    lines = ["User uploads (read-only):"]
    uploads = sorted(
        (p for p in uploads_dir.rglob("*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not uploads:
        lines.append("- (none)")
    for path in uploads[:80]:
        lines.append(
            f"- {path.relative_to(uploads_dir).as_posix()} ({_human_size(path.stat().st_size)})"
        )

    lines.append("\nOutput files (writable, user-visible):")
    outputs = sorted(
        (p for p in outputs_dir.rglob("*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not outputs:
        lines.append("- (none)")
    for path in outputs[:120]:
        lines.append(
            f"- {path.relative_to(outputs_dir).as_posix()} "
            f"({_human_size(path.stat().st_size)}, {_markdown_link(path, ctx.chat_id)})"
        )

    lines.append("\nWorkspace scratch files (not user-visible):")
    workspace = sorted(
        (p for p in workspace_dir.rglob("*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not workspace:
        lines.append("- (none)")
    for path in workspace[:80]:
        lines.append(
            f"- {path.relative_to(workspace_dir).as_posix()} ({_human_size(path.stat().st_size)})"
        )

    listing = "\n".join(lines)
    summary = (
        f"{len(uploads)} upload{'s' if len(uploads) != 1 else ''} · "
        f"{len(outputs)} output{'s' if len(outputs) != 1 else ''} · "
        f"{len(workspace)} workspace file{'s' if len(workspace) != 1 else ''}"
    )
    return ToolResult(
        content=listing,
        summary=summary,
        data={
            # Uploads and outputs are clickable in the UI. Workspace files stay
            # in the text listing because they are scratch files, not user-visible.
            "files": [_file_entry(path, ctx.chat_id) for path in (*uploads[:80], *outputs[:120])],
            "content": listing,
        },
    )


register(
    Tool(
        name="write_file",
        description=(
            "Create or overwrite a UTF-8 file in this chat's user-visible outputs folder. Use "
            "this for reports, notes, code, CSV, SVG, and other documents. Always give the user "
            "the file:// markdown link returned by this tool."
        ),
        parameters=WRITE_PARAMETERS,
        handler=write_file,
    )
)
register(
    Tool(
        name="read_file",
        description=(
            "Read a text file from this chat's outputs, uploads, or /workspace. Images and "
            "PDFs are rendered and attached as native visual content when the model supports "
            "vision. Use list_files first if you are unsure of the name. Uploaded documents "
            "are also summarized into the conversation automatically, so this is mainly for "
            "following up on specific files or reading something you created in the workspace."
        ),
        parameters=READ_PARAMETERS,
        handler=read_file,
    )
)
register(
    Tool(
        name="list_files",
        description=(
            "List this chat's uploaded files, user-visible outputs, and workspace scratch files."
        ),
        parameters=LIST_PARAMETERS,
        handler=list_files,
    )
)
