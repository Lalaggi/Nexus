from __future__ import annotations

import threading
from pathlib import Path

import pytest

from nexus.agent import _elide_tool_outputs
from nexus.config import CONFIG
from nexus.tools import sandbox
from nexus.tools.base import ToolContext
from nexus.tools.files import _sandbox_path, read_file

CHAT = "testchat"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(CONFIG, "home", home)
    (home / "useruploads" / CHAT).mkdir(parents=True)
    (home / "outputs" / CHAT).mkdir(parents=True)
    (home / ".workspaces" / CHAT).mkdir(parents=True)
    return ToolContext(chat_id=CHAT, db=None)  # type: ignore[arg-type]


async def test_read_file_does_not_read_past_the_output_limit(ctx, monkeypatch):
    # 5 MB of text, but max_chars is clamped by the tool's own minimum.
    path = CONFIG.chat_uploads_dir(CHAT) / "huge.txt"
    path.write_text("a" * 5_000_000, encoding="utf-8")

    reads: list[int] = []
    real_open = Path.open

    class TrackingReader:
        def __init__(self, handle):
            self._handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._handle.close()
            return False

        def read(self, size=-1):
            reads.append(size)
            return self._handle.read(size)

    def tracking_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        if self == path and args and args[0] == "rb":
            return TrackingReader(handle)
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)
    result = await read_file(ctx, {"path": "/mnt/useruploads/huge.txt", "max_chars": 1000})

    # read_file asks for max_chars * 4 bytes rather than the 5 MB file.
    assert sum(size for size in reads if size > 0) <= 8_096
    assert len(result.content) < 2_000
    assert "Truncated: showing the first 1,000 characters" in result.content


async def test_read_file_still_rejects_binary_files(ctx):
    (CONFIG.chat_uploads_dir(CHAT) / "archive.zip").write_bytes(b"PK\x03\x04\x00\x00payload")

    result = await read_file(ctx, {"path": "/mnt/useruploads/archive.zip"})

    assert result.ok is False
    assert result.summary == "Binary file"


def test_sandbox_path_never_returns_a_host_path(ctx):
    assert _sandbox_path(Path("/etc/passwd"), CHAT) == "<outside-sandbox>"


async def test_sandbox_status_probes_off_the_event_loop(monkeypatch):
    seen: dict[str, threading.Thread] = {}

    def fake_status() -> dict:
        seen["thread"] = threading.current_thread()
        return {"available": True}

    monkeypatch.setattr(sandbox, "_sandbox_status_uncached", fake_status)
    monkeypatch.setattr(sandbox, "_STATUS_CACHE", None)

    assert await sandbox.sandbox_status() == {"available": True}
    assert seen["thread"] is not threading.main_thread()


def test_sanitize_pythonpath_removes_auto_executed_files(tmp_path):
    (tmp_path / "sitecustomize.py").write_text("print('payload')")
    (tmp_path / "usercustomize.py").write_text("print('payload')")
    (tmp_path / "sitecustomize").mkdir()
    (tmp_path / "sitecustomize" / "__init__.py").write_text("print('payload')")
    (tmp_path / "requests.py").write_text("# a real package module")

    sandbox._sanitize_pythonpath(tmp_path)

    assert not (tmp_path / "sitecustomize.py").exists()
    assert not (tmp_path / "usercustomize.py").exists()
    assert not (tmp_path / "sitecustomize").exists()
    assert (tmp_path / "requests.py").exists()


def test_tool_output_elision_keeps_recent_results(monkeypatch):
    monkeypatch.setattr(CONFIG, "max_tool_output_chars", 1_000)
    monkeypatch.setattr(CONFIG, "tool_result_keep_recent", 1)

    messages: list[dict] = []
    entries: list[dict] = []
    for _ in range(3):
        messages.append({"role": "tool", "content": "x" * 600})
        entries.append(
            {
                "index": len(messages) - 1,
                "name": "read_file",
                "summary": "Read notes.txt",
                "chars": 600,
                "elided": False,
            }
        )
        _elide_tool_outputs(messages, entries)

    assert messages[0]["content"].startswith("[Earlier read_file output elided")
    assert "Read notes.txt" in messages[0]["content"]
    assert messages[1]["content"].startswith("[Earlier read_file output elided")
    assert messages[2]["content"] == "x" * 600


def test_tool_output_elision_is_a_noop_under_budget(monkeypatch):
    monkeypatch.setattr(CONFIG, "max_tool_output_chars", 10_000)
    monkeypatch.setattr(CONFIG, "tool_result_keep_recent", 2)

    messages = [{"role": "tool", "content": "x" * 500}]
    entries = [
        {
            "index": 0,
            "name": "read_file",
            "summary": "",
            "chars": 500,
            "elided": False,
        }
    ]

    _elide_tool_outputs(messages, entries)

    assert messages[0]["content"] == "x" * 500
    assert entries[0]["elided"] is False
