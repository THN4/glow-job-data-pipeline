"""Turns an uploaded file into model input: extracted text and/or page images.

PDFs are classified page by page so mixed text/scanned documents retain both forms of content.
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
from ..extraction.contracts import PageImage, PreparedCv, PreparedPage

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

    def __post_init__(self) -> None:
        if self.max_pdf_pages < 1 or self.max_image_pages < 1:
            raise ValueError("PDF and image page limits must be at least one.")


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
    image = _to_model_jpeg(data)
    return PreparedCv(kind="images", page_count=1, images=[image], pages=[PreparedPage(page_number=1, image=image)])


def is_usable_page_text(text: str) -> bool:
    """A page is text-readable only when it contains enough clean extracted text."""
    visible = "".join(text.split())
    if len(visible) < MIN_CHARS_PER_PAGE:
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
        page_texts = [_clean_text(doc[i].get_text("text", sort=False)) for i in range(page_count)]
        text_pages = [i for i, text in enumerate(page_texts) if is_usable_page_text(text)]
        image_pages = [i for i in range(page_count) if i not in text_pages]
        selected_image_pages = image_pages[: limits.max_image_pages]
        omitted_pages = [i + 1 for i in image_pages[limits.max_image_pages :]]

        selected_images = {i: _render_page(doc[i]) for i in selected_image_pages}
        pages: list[PreparedPage] = []
        for i, text in enumerate(page_texts):
            if i in text_pages:
                pages.append(PreparedPage(page_number=i + 1, text=text.strip()))
            elif i in selected_images:
                image = selected_images[i]
                pages.append(PreparedPage(page_number=i + 1, image=image))

        text = "\n\n".join(
            f"--- page {page.page_number} ---\n{page.text}" for page in pages if page.text is not None
        )
        images = [page.image for page in pages if page.image is not None]
        has_text = bool(text_pages)
        has_images = bool(images)
        kind = "text" if has_text and not has_images else "images" if has_images and not has_text else "mixed"
        warnings = []
        if omitted_pages:
            omitted_list = ", ".join(str(page) for page in omitted_pages)
            warnings.append(
                f"Scanned content on PDF page(s) {omitted_list} was omitted because the image-page limit "
                f"is {limits.max_image_pages}; the extraction is partial."
            )
        return PreparedCv(
            kind=kind,
            page_count=page_count,
            text=text,
            images=images,
            pages=pages,
            omitted_pages=omitted_pages,
            warnings=warnings,
        )
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
