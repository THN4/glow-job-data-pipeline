"""Turns an uploaded file into model input: extracted text (preferred) or page images.

Qwen can't read PDF files, so everything becomes text or JPEG pages.
This module does not own upload handling or job lifecycle.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
from dataclasses import dataclass

import filetype
import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

from ..errors import ResumeProcessingError
from ..extraction.contracts import PageImage, PreparedCv

ALLOWED_MIME = ("application/pdf", "image/jpeg", "image/png", "image/webp")

IMAGE_LONG_EDGE = 1280
JPEG_QUALITY = 85
MIN_CHARS_PER_PAGE = 100
MAX_GARBLED_RATIO = 0.05

# Some fonts (e.g. Tahoma) map the plain hyphen to a soft hyphen (U+00AD): "081-000-0002" -> "081­000­0002".
# Only fix it next to digits/spaces, so real soft hyphens inside words (line-break hints) are left alone.
_SOFT_HYPHEN_AS_DASH = re.compile(r"(?<=[\d\s])­|­(?=[\d\s])")

# U+FFFD, C0/C1 controls and private-use glyphs indicate a broken font encoding.
_GARBLED = re.compile("[�\x00-\x1f\x7f-\x9f-]")

Image.MAX_IMAGE_PIXELS = 60_000_000  # guard against decompression bombs


@dataclass(frozen=True)
class Limits:
    max_pdf_pages: int = 10
    max_image_pages: int = 4


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_mime(data: bytes) -> str:
    """Detects the real file type from magic bytes (the extension / declared type is not trusted)."""
    kind = filetype.guess(data)
    if kind is None or kind.mime not in ALLOWED_MIME:
        raise ResumeProcessingError("UNSUPPORTED_FILE_TYPE")
    return kind.mime


def prepare_cv(data: bytes, limits: Limits = Limits()) -> PreparedCv:
    """CPU-bound: call from a worker thread (asyncio.to_thread) inside async code."""
    mime = detect_mime(data)
    if mime == "application/pdf":
        return _prepare_pdf(data, limits)
    return PreparedCv(kind="images", page_count=1, images=[_to_model_jpeg(data)])


def is_usable_text(pages: list[str]) -> bool:
    """Text is usable when there is enough of it and it is not mostly broken glyphs."""
    if not pages:
        return False
    visible = "".join("".join(pages).split())
    if len(visible) / len(pages) < MIN_CHARS_PER_PAGE:
        return False
    return len(_GARBLED.findall(visible)) / len(visible) <= MAX_GARBLED_RATIO


def _prepare_pdf(data: bytes, limits: Limits) -> PreparedCv:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as err:  # corrupt PDF
        raise ResumeProcessingError("UNREADABLE_DOCUMENT", "The PDF is damaged and could not be opened.") from err
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise ResumeProcessingError("UNREADABLE_DOCUMENT", "The PDF is encrypted and could not be opened.")
        page_count = doc.page_count
        if page_count == 0:
            raise ResumeProcessingError("UNREADABLE_DOCUMENT", "The PDF has no pages.")
        if page_count > limits.max_pdf_pages:
            raise ResumeProcessingError(
                "TOO_MANY_PAGES",
                f"The PDF has {page_count} pages; the maximum is {limits.max_pdf_pages}.",
            )

        # sort=False keeps the PDF's own reading order, so multi-column layouts stay column by column
        # (sort=True sorts purely by position and interleaves the columns line by line).
        pages = [_clean_text(doc[i].get_text("text", sort=False)) for i in range(page_count)]
        if is_usable_text(pages):
            text = "\n\n".join(f"--- page {i + 1} ---\n{p.strip()}" for i, p in enumerate(pages))
            return PreparedCv(kind="text", page_count=page_count, text=text)

        # Scanned (or badly encoded) PDF: render pages to images for a vision model.
        render_count = min(page_count, limits.max_image_pages)
        warnings = []
        if render_count < page_count:
            warnings.append(f"Only the first {render_count} of {page_count} scanned pages were analyzed.")
        images = [_render_page(doc[i]) for i in range(render_count)]
        return PreparedCv(kind="images", page_count=page_count, images=images, warnings=warnings)
    except ResumeProcessingError:
        raise
    except Exception as err:
        raise ResumeProcessingError("UNREADABLE_DOCUMENT", "The PDF could not be read.") from err
    finally:
        doc.close()


def _clean_text(text: str) -> str:
    return _SOFT_HYPHEN_AS_DASH.sub("-", text).replace(" ", " ")


def _render_page(page: "pymupdf.Page") -> PageImage:
    rect = page.rect
    # Points -> pixels: at most ~150 DPI and at most IMAGE_LONG_EDGE px on the long side.
    scale = min(150 / 72, IMAGE_LONG_EDGE / max(rect.width, rect.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return _to_model_jpeg(pix.tobytes("png"))


def _to_model_jpeg(data: bytes) -> PageImage:
    """EXIF-rotate, downscale to IMAGE_LONG_EDGE and re-encode as JPEG."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((IMAGE_LONG_EDGE, IMAGE_LONG_EDGE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=JPEG_QUALITY)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as err:
        raise ResumeProcessingError("UNREADABLE_DOCUMENT", "The image could not be read.") from err
    return PageImage(b64=base64.b64encode(out.getvalue()).decode("ascii"))
