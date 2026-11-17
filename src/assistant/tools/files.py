"""File tools constrained to the current chat's uploads, outputs, and workspace."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from ..config import CONFIG
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
    # Legacy locations used before uploads and outputs became per-chat.
    roots.extend(
        [
            (CONFIG.outputs_dir, "/mnt/outputs"),
            (CONFIG.uploads_dir, "/mnt/useruploads"),
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
    return resolved.as_posix()


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
    candidates: list[Path] = []

    if token.startswith("/mnt/outputs/"):
        candidates.append(outputs / token[len("/mnt/outputs/") :])
    elif token == "/mnt/outputs":
        candidates.append(outputs)
    elif token.startswith("/mnt/useruploads/"):
        candidates.append(uploads / token[len("/mnt/useruploads/") :])
    elif token == "/mnt/useruploads":
        candidates.append(uploads)
    elif token.startswith("/workspace/"):
        candidates.append(workspace / token[len("/workspace/") :])
    elif token == "/workspace":
        candidates.append(workspace)
    elif Path(token).is_absolute():
        absolute = Path(token).resolve()
        for root in (outputs, uploads, workspace):
            if absolute.is_relative_to(root.resolve()):
                candidates.append(absolute)
                break
    else:
        relative = Path(token)
        for base in (outputs, uploads, workspace):
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
                "and /workspace/script.py also work."
            ),
        },
        "max_chars": {"type": "integer", "minimum": 1000, "maximum": 100000},
    },
    "required": ["path"],
}


async def read_file(ctx: ToolContext, args: dict) -> ToolResult:
    path_text = str(args.get("path", "")).strip()
    if not path_text:
        return ToolResult(content="A path is required.", ok=False)
    max_chars = max(1000, min(100_000, int(args.get("max_chars") or 30_000)))

    token = path_text
    if token.startswith("file://"):
        token = urlparse(token).path

    existing = next((p for p in _candidates(token, ctx.chat_id) if p.is_file()), None)
    if existing is None:
        return ToolResult(
            content=f"File not found: {path_text}. Use list_files to see available files.",
            ok=False,
            summary="Not found",
        )

    raw = existing.read_bytes()
    if b"\x00" in raw[:4096]:
        return ToolResult(
            content=f"{existing.name} looks binary and cannot be read as text. Images are already visible to you when attached.",
            ok=False,
        )
    text = raw.decode("utf-8", "replace")
    clipped = text[:max_chars]
    suffix = ""
    if len(text) > len(clipped):
        suffix = f"\n\n[Truncated at {max_chars} of {len(text):,} characters.]"
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

    return ToolResult(content="\n".join(lines), summary=f"{len(outputs)} outputs")


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
            "Read a text file from this chat's outputs, uploads, or /workspace. Use list_files "
            "first if you are unsure of the name. Uploaded documents are also summarized into "
            "the conversation automatically, so this is mainly for following up on specific "
            "files or reading something you created in the workspace."
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
