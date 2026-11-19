"""Render images and PDF pages so vision-capable models can read them natively.

The database stores only text, so this module is a pure on-demand converter:
the caller gets base64 image bytes and decides whether to attach them to the
next model request. Nothing rendered here is written to disk.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image, ImageOps
from pypdf import PdfReader

from .config import CONFIG

IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
}
PDF_SUFFIXES = {".pdf"}


class MediaError(RuntimeError):
    pass


@dataclass
class RenderedMedia:
    """Visual content ready to be sent as OpenAI-style ``image_url`` parts."""

    kind: str  # "image" or "pdf"
    items: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 1
    text: str = ""

    @property
    def truncated(self) -> bool:
        return self.page_count > len(self.items)


def is_image_suffix(suffix: str) -> bool:
    return suffix.lower() in IMAGE_SUFFIXES


def is_pdf_suffix(suffix: str) -> bool:
    return suffix.lower() in PDF_SUFFIXES


def _budget_bytes() -> int:
    return int(CONFIG.vision_max_total_mb * 1_000_000)


def _encode_jpeg(image: Image.Image) -> tuple[str, int, int]:
    """Downscale and JPEG-encode one image, staying under the payload budget."""
    image = ImageOps.exif_transpose(image)
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        flattened = Image.new("RGB", rgba.size, (255, 255, 255))
        flattened.paste(rgba, mask=rgba.split()[-1])
        image = flattened
    else:
        image = image.convert("RGB")

    image.thumbnail(
        (CONFIG.vision_max_dimension, CONFIG.vision_max_dimension),
        Image.Resampling.LANCZOS,
    )
    per_image_limit = max(400_000, _budget_bytes() // 3)

    while True:
        for quality in (85, 75, 65, 55):
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            raw = buffer.getvalue()
            if len(raw) <= per_image_limit:
                return base64.b64encode(raw).decode("ascii"), image.width, image.height
        # Very detailed images can still exceed the limit at low quality.
        if min(image.size) <= 128:
            return base64.b64encode(raw).decode("ascii"), image.width, image.height
        image = image.resize(
            (max(1, image.width // 2), max(1, image.height // 2)),
            Image.Resampling.LANCZOS,
        )


def render_image(path: Path) -> RenderedMedia:
    if path.stat().st_size > CONFIG.vision_max_file_mb * 1024 * 1024:
        raise MediaError(f"{path.name} is larger than the {CONFIG.vision_max_file_mb} MB vision limit.")
    try:
        with Image.open(path) as image:
            image.load()
            data, width, height = _encode_jpeg(image)
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(f"Could not decode {path.name} as an image: {exc}") from exc
    return RenderedMedia(
        kind="image",
        items=[
            {
                "label": path.name,
                "mime": "image/jpeg",
                "data": data,
                "width": width,
                "height": height,
            }
        ],
    )


def extract_pdf_text(path: Path, max_chars: int = 30_000) -> str:
    try:
        reader = PdfReader(str(path))
        chunks = [(page.extract_text() or "") for page in reader.pages[:60]]
    except Exception:
        return ""
    return "\n\n".join(chunk for chunk in chunks if chunk).strip()[:max_chars]


def render_pdf(path: Path) -> RenderedMedia:
    if path.stat().st_size > CONFIG.vision_max_file_mb * 1024 * 1024:
        raise MediaError(f"{path.name} is larger than the {CONFIG.vision_max_file_mb} MB vision limit.")
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise MediaError(f"Could not open {path.name} as a PDF: {exc}") from exc

    items: list[dict[str, Any]] = []
    total = 0
    budget = _budget_bytes()
    page_count = 0
    try:
        page_count = len(document)
        for index in range(min(page_count, CONFIG.vision_max_pages)):
            page = document[index]
            width, height = page.get_size()
            scale = min(3.0, CONFIG.vision_max_dimension / max(width, height))
            bitmap = page.render(scale=max(scale, 0.5))
            try:
                data, rendered_width, rendered_height = _encode_jpeg(bitmap.to_pil())
            finally:
                bitmap.close()
            if items and total + len(data) > budget:
                break
            items.append(
                {
                    "label": f"Page {index + 1}",
                    "mime": "image/jpeg",
                    "data": data,
                    "width": rendered_width,
                    "height": rendered_height,
                }
            )
            total += len(data)
    finally:
        document.close()

    return RenderedMedia(
        kind="pdf",
        items=items,
        page_count=page_count,
        text=extract_pdf_text(path),
    )


def render_media(path: Path) -> RenderedMedia:
    suffix = path.suffix.lower()
    if is_image_suffix(suffix):
        return render_image(path)
    if is_pdf_suffix(suffix):
        return render_pdf(path)
    raise MediaError(f"{path.name} is not a supported image or PDF.")
