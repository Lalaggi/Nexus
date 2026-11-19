from __future__ import annotations

import base64

import pytest
from PIL import Image
from pypdf import PdfWriter

from nexus.agent import _compact_data
from nexus.config import CONFIG
from nexus.tools.base import ToolContext
from nexus.tools.files import list_files, read_file

CHAT = "testchat"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(CONFIG, "home", home)
    (home / "useruploads" / CHAT).mkdir(parents=True)
    (home / "outputs" / CHAT).mkdir(parents=True)
    (home / ".workspaces" / CHAT).mkdir(parents=True)
    return ToolContext(chat_id=CHAT, db=None)  # type: ignore[arg-type]


async def test_binary_read_reports_binary_and_emits_no_file(ctx):
    (CONFIG.chat_uploads_dir(CHAT) / "archive.zip").write_bytes(b"PK\x03\x04\x00\x00payload")

    result = await read_file(ctx, {"path": "/mnt/useruploads/archive.zip"})

    assert result.ok is False
    assert result.summary == "Binary file"
    assert "sandbox" in result.content
    assert result.data == {}
    # Previously this fabricated {"name": "file", "path": "", "url": ""},
    # which showed up as a phantom "file" chip in the UI.
    assert _compact_data("read_file", result.data) == {}


async def test_reading_a_directory_points_at_list_files(ctx):
    result = await read_file(ctx, {"path": "/mnt/useruploads"})

    assert result.ok is False
    assert result.summary == "Folder"
    assert "list_files" in result.content


async def test_read_file_rejects_traversal_out_of_sandbox(ctx, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")

    result = await read_file(ctx, {"path": "/mnt/outputs/../../secret.txt"})

    assert result.ok is False
    assert "top secret" not in result.content


async def test_list_files_reports_all_areas_and_returns_entries(ctx):
    (CONFIG.chat_uploads_dir(CHAT) / "notes.txt").write_text("hello")
    (CONFIG.chat_workspace_dir(CHAT) / "scratch.py").write_text("print(1)")

    result = await list_files(ctx, {})

    assert result.ok is True
    assert result.summary == "1 upload · 0 outputs · 1 workspace file"
    assert result.data["files"][0]["name"] == "notes.txt"
    assert result.data["files"][0]["url"].startswith("file:///mnt/useruploads/")
    assert "notes.txt" in result.content

    compact = _compact_data("list_files", result.data)
    assert compact["files"][0]["name"] == "notes.txt"
    assert "Workspace scratch files" in compact["content"]


def test_failed_write_does_not_fabricate_a_file():
    compact = _compact_data("write_file", {})

    assert "files" not in compact


async def test_image_is_returned_as_native_media(ctx):
    path = CONFIG.chat_uploads_dir(CHAT) / "photo.png"
    Image.new("RGB", (800, 600), (180, 30, 30)).save(path)

    result = await read_file(ctx, {"path": "/mnt/useruploads/photo.png"})

    assert result.ok is True
    assert result.summary == "Viewed photo.png"
    assert len(result.media) == 1
    item = result.media[0]
    assert item["mime"] == "image/jpeg"
    assert item["label"] == "photo.png"
    assert item["width"] <= CONFIG.vision_max_dimension
    assert base64.b64decode(item["data"]).startswith(b"\xff\xd8")
    assert result.data["pages"] == 1


async def test_pdf_pages_are_returned_as_native_media(ctx):
    path = CONFIG.chat_uploads_dir(CHAT) / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)

    result = await read_file(ctx, {"path": "/mnt/useruploads/report.pdf"})

    assert result.ok is True
    assert result.data["pages"] == 2
    assert [item["label"] for item in result.media] == ["Page 1", "Page 2"]
    assert all(item["mime"] == "image/jpeg" for item in result.media)
    assert "2 page(s)" in result.content


async def test_text_only_model_does_not_get_image_parts(ctx):
    path = CONFIG.chat_uploads_dir(CHAT) / "photo.png"
    Image.new("RGB", (64, 64), "blue").save(path)
    text_only = ToolContext(chat_id=CHAT, db=None, supports_vision=False)  # type: ignore[arg-type]

    result = await read_file(text_only, {"path": "/mnt/useruploads/photo.png"})

    assert result.ok is False
    assert result.summary == "No vision support"
    assert result.media == []


async def test_blank_pdf_falls_back_to_text_without_vision(ctx):
    path = CONFIG.chat_uploads_dir(CHAT) / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with path.open("wb") as handle:
        writer.write(handle)
    text_only = ToolContext(chat_id=CHAT, db=None, supports_vision=False)  # type: ignore[arg-type]

    result = await read_file(text_only, {"path": "/mnt/useruploads/blank.pdf"})

    assert result.ok is False
    assert result.summary == "No text layer"

