"""Run shell commands inside a locked-down, rootless Podman container."""

from __future__ import annotations

import asyncio
import os
import pwd
import shutil
import time
import uuid
from pathlib import Path

from ..config import CONFIG
from .base import Tool, ToolContext, ToolResult, register
from .files import _file_url, _human_size, _sandbox_path

_STATUS_CACHE: tuple[float, dict] | None = None

PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": (
                "Shell command to run in the sandbox. It has Python, git, curl, Node, a "
                "compiler, and common CLI tools. Working directory is /workspace, which "
                "persists for this conversation. Uploads are read-only at /mnt/useruploads; "
                "write anything the user should see to /mnt/outputs."
            ),
        },
        "timeout": {
            "type": "integer",
            "description": "Seconds before the command is killed (default 90, max 180).",
            "minimum": 1,
            "maximum": 180,
        },
    },
    "required": ["command"],
}


def podman_path() -> str | None:
    return shutil.which("podman")


def sandbox_account() -> pwd.struct_passwd | None:
    name = CONFIG.sandbox_account.strip()
    if not name:
        return None
    try:
        return pwd.getpwnam(name)
    except KeyError:
        return None


def podman_command() -> list[str] | None:
    """Return the argv prefix used to reach the sandbox's rootless Podman.

    When the dedicated account and its root-owned wrapper exist, commands run
    through `sudo -u sandbox`. That keeps images, layers, and container storage
    on the sandbox user's capped filesystem and away from the app user's keys.
    """
    account = sandbox_account()
    wrapper = Path(CONFIG.sandbox_podman_wrapper)
    sudo = shutil.which("sudo")
    if (
        account is not None
        and sudo
        and wrapper.is_file()
        and os.access(wrapper, os.X_OK)
        and os.getuid() != account.pw_uid
    ):
        return [sudo, "-n", "-u", account.pw_name, str(wrapper)]
    podman = podman_path()
    return [podman] if podman else None


def sandbox_status() -> dict:
    global _STATUS_CACHE
    now = time.monotonic()
    if _STATUS_CACHE is not None and now - _STATUS_CACHE[0] < 10:
        return _STATUS_CACHE[1]
    result = _sandbox_status_uncached()
    _STATUS_CACHE = (now, result)
    return result


def _sandbox_status_uncached() -> dict:
    prefix = podman_command()
    account = sandbox_account()
    mode = (
        f"dedicated user {account.pw_name}"
        if account and prefix and prefix[0].endswith("sudo")
        else "current user (development mode)"
    )
    if not prefix:
        return {
            "available": False,
            "podman": False,
            "image": False,
            "image_name": CONFIG.sandbox_image,
            "mode": mode,
            "detail": "Podman is not installed.",
        }
    try:
        import subprocess

        image = subprocess.run(
            [*prefix, "image", "exists", CONFIG.sandbox_image],
            capture_output=True,
            timeout=20,
            check=False,
        )
        version = subprocess.run(
            [*prefix, "--version"], capture_output=True, text=True, timeout=15, check=False
        ).stdout.strip()
        return {
            "available": image.returncode == 0,
            "podman": True,
            "image": image.returncode == 0,
            "image_name": CONFIG.sandbox_image,
            "mode": mode,
            "version": version,
            "detail": (
                f"Sandbox ready ({mode})."
                if image.returncode == 0
                else (
                    "Podman is installed but the sandbox image is missing. Run "
                    "./scripts/build-sandbox.sh (or scripts/setup-sandbox-user.sh first)."
                )
            ),
        }
    except Exception as exc:
        return {
            "available": False,
            "podman": True,
            "image": False,
            "image_name": CONFIG.sandbox_image,
            "mode": mode,
            "detail": f"Could not query Podman: {exc}",
        }


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    state: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return state
    for path in root.rglob("*"):
        try:
            if path.is_file():
                stat = path.stat()
                state[str(path)] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            continue
    return state


def _changed(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[Path]:
    changed = []
    for name, meta in after.items():
        if before.get(name) != meta:
            changed.append(Path(name))
    return sorted(changed)


async def run_sandbox(ctx: ToolContext, args: dict) -> ToolResult:
    command_text = args.get("command")
    if not isinstance(command_text, str) or not command_text.strip():
        return ToolResult(content="A shell command is required.", ok=False)
    if len(command_text.encode("utf-8")) > 400_000:
        return ToolResult(content="The command is too large (400 KB limit).", ok=False)
    if not CONFIG.sandbox_enabled:
        return ToolResult(content="The code sandbox is disabled by configuration.", ok=False)

    podman = podman_command()
    if not podman:
        return ToolResult(
            content=(
                "The sandbox is unavailable right now. Tell the user and do not pretend code ran."
            ),
            ok=False,
            summary="Sandbox unavailable",
        )
    status = sandbox_status()
    if not status.get("image"):
        return ToolResult(
            content=(
                "The sandbox is not ready right now. Tell the user the code sandbox is "
                "unavailable and do not pretend code ran."
            ),
            ok=False,
            summary="Sandbox not ready",
        )

    timeout = max(1, min(180, int(args.get("timeout") or CONFIG.sandbox_timeout)))
    workspace = CONFIG.chat_workspace_dir(ctx.chat_id)
    uploads = CONFIG.chat_uploads_dir(ctx.chat_id)
    outputs = CONFIG.chat_outputs_dir(ctx.chat_id)
    for directory in (workspace, uploads, outputs):
        directory.mkdir(parents=True, exist_ok=True)

    # Persistent Python site-packages so pip-installed packages survive across
    # sandbox calls. Each call is a fresh --rm container whose root filesystem
    # is discarded, so packages installed into the container's site-packages
    # vanish when it exits. We install into the mounted workspace instead and
    # tell both Python and pip to look there.
    py_packages_dir = workspace / ".python-packages"
    pip_conf_dir = workspace / ".pip"
    py_packages_dir.mkdir(parents=True, exist_ok=True)
    pip_conf_dir.mkdir(parents=True, exist_ok=True)
    (pip_conf_dir / "pip.conf").write_text(
        "[install]\ntarget = /workspace/.python-packages\n", encoding="utf-8"
    )
    name = f"assistant-sbx-{uuid.uuid4().hex[:12]}"

    outputs_before = _snapshot(outputs)
    workspace_before = _snapshot(workspace)

    network_args: list[str] = []
    if CONFIG.sandbox_network:
        for resolver in CONFIG.sandbox_dns.split(","):
            if resolver.strip():
                network_args += ["--dns", resolver.strip()]
    else:
        network_args.append("--network=none")

    command = [
        *podman,
        "run",
        "--rm",
        "--name",
        name,
        "--pull=never",
        *network_args,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
        f"--memory={CONFIG.sandbox_memory}",
        f"--memory-swap={CONFIG.sandbox_memory}",
        f"--cpus={CONFIG.sandbox_cpus}",
        "--pids-limit=128",
        "--ulimit",
        "nofile=256:256",
        "--userns=keep-id:uid=1000,gid=1000",
        "--user",
        "1000:1000",
        "--init",
        "-v",
        f"{workspace}:/workspace:rw",
        "-v",
        f"{uploads}:/mnt/useruploads:ro",
        "-v",
        f"{outputs}:/mnt/outputs:rw",
        "-w",
        "/workspace",
        "-e",
        "HOME=/tmp",
        "-e",
        "MPLCONFIGDIR=/tmp/matplotlib",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "PYTHONPATH=/workspace/.python-packages",
        "-e",
        "PIP_CONFIG_FILE=/workspace/.pip/pip.conf",
        "-e",
        "MPLBACKEND=Agg",
        "-e",
        "GIT_AUTHOR_NAME=Assistant",
        "-e",
        "GIT_AUTHOR_EMAIL=assistant@localhost",
        "-e",
        "GIT_COMMITTER_NAME=Assistant",
        "-e",
        "GIT_COMMITTER_EMAIL=assistant@localhost",
        CONFIG.sandbox_image,
        "sh",
        "-lc",
        command_text,
    ]

    started = time.monotonic()
    timed_out = False
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError:
            timed_out = True
            process.kill()
            await process.communicate()
            stdout_b, stderr_b = b"", b""
            cleanup = await asyncio.create_subprocess_exec(
                *podman,
                "rm",
                "-f",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await cleanup.wait()
    except FileNotFoundError:
        return ToolResult(content="Podman could not be started.", ok=False)
    except Exception as exc:
        return ToolResult(content=f"Sandbox failed to start: {exc}", ok=False, summary="Sandbox error")

    duration = time.monotonic() - started
    stdout = stdout_b.decode("utf-8", "replace") if stdout_b else ""
    stderr = stderr_b.decode("utf-8", "replace") if stderr_b else ""
    exit_code = process.returncode

    outputs_after = _snapshot(outputs)
    workspace_after = _snapshot(workspace)
    new_outputs = _changed(outputs_before, outputs_after)
    changed_workspace = _changed(workspace_before, workspace_after)

    def clip(text: str, limit: int = 15_000) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n...[truncated {len(text) - limit:,} chars]"

    sections = [f"Exit code: {exit_code} · {duration:.1f}s"]
    if timed_out:
        sections.append(f"Timed out after {timeout}s and the container was removed.")
    sections.append("STDOUT:\n" + (clip(stdout) if stdout.strip() else "(empty)"))
    if stderr.strip():
        sections.append("STDERR:\n" + clip(stderr))
    if new_outputs:
        links = [
            f"- /mnt/outputs/{p.relative_to(outputs).as_posix()} -> {_file_url(p, ctx.chat_id)}"
            for p in new_outputs[:25]
        ]
        sections.append("New/updated files in outputs:\n" + "\n".join(links))
    if changed_workspace:
        listing = [
            f"- /workspace/{p.relative_to(workspace).as_posix()} ({_human_size(p.stat().st_size)})"
            for p in changed_workspace[:25]
        ]
        sections.append(
            "Files changed in the scratch workspace (not user-visible; copy anything the user "
            "needs into /mnt/outputs):\n" + "\n".join(listing)
        )

    ok = exit_code == 0 and not timed_out
    return ToolResult(
        content="\n\n".join(sections),
        summary=(
            "Timed out"
            if timed_out
            else f"Sandbox exit {exit_code}" + (f" · {len(new_outputs)} file(s)" if new_outputs else "")
        ),
        data={
            "stdout": clip(stdout, 8000),
            "stderr": clip(stderr, 8000),
            "exit_code": exit_code,
            "files": [
                {"path": _sandbox_path(p, ctx.chat_id), "url": _file_url(p, ctx.chat_id), "name": p.name}
                for p in new_outputs[:25]
            ],
        },
        ok=ok,
    )


register(
    Tool(
        name="sandbox",
        description=(
            "Run a shell command in your Linux code sandbox. It has Python, git, curl, Node, "
            "a compiler, and common CLI tools, plus internet access for public resources. "
            "Working directory is /workspace, which persists for this conversation. Uploads "
            "are read-only at /mnt/useruploads; write anything the user should see to "
            "/mnt/outputs and link it with file://. Use it to compute, analyze data, make "
            "charts, convert files, and verify code."
        ),
        parameters=PARAMETERS,
        handler=run_sandbox,
    )
)
