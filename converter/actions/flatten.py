"""Flattening: turning every page into a single image, optionally with a searchable OCR layer."""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from ..core.context import JobContext
from ..core.issues import (
    ConversionError,
    empty_pdf,
    flatten_check_failed,
    password_protected,
    unreadable_file,
)
from ..core.types import Stage
from ..ocr import ocr_image_to_pdf, render_page, require_ocr
from ..pdf import read_bookmarks, set_bookmarks

log = logging.getLogger(__name__)


def flatten_pdf(source: Path, target: Path, work: Path, ctx: JobContext, file_label: str) -> None:
    """Turn a PDF into one where every page is a single image.

    This is the core "Flatten" feature: layers, fonts, form fields and
    annotations are all drawn into one picture per page, which apps that
    struggle with complex PDFs (such as some tablet note-taking apps) open
    reliably. Each page goes through:

    1. **Render** the page at ``settings.dpi``.
    2. **OCR** (only if ``settings.use_ocr``): Tesseract writes a one-page PDF
       holding the image plus an invisible text layer, so the text can still be
       searched and copied. Without OCR the image is placed on the page as is.
    3. **Assemble** the new page at the original page's size.

    Bookmarks are copied over (pages keep their numbers). The result must pass
    a strict check: same page count as the input, and every page image-backed.

    Args:
        source: PDF to flatten. It is only read, never modified.
        target: Where to save the flattened PDF.
        work: Scratch folder for page images and OCR output.
        ctx: Job context (settings, progress, cancel).
        file_label: Input file name, for messages.

    Raises:
        ConversionError: Unreadable, password-protected or empty input; OCR
            missing, failing or timing out; or the final check failed.
        Cancelled: The user cancelled.
    """
    use_ocr = ctx.settings.use_ocr
    tesseract = require_ocr(ctx) if use_ocr else None
    work.mkdir(parents=True, exist_ok=True)
    try:
        original = pymupdf.open(str(source))
    except Exception as exc:
        raise ConversionError(unreadable_file(file_label, str(exc))) from exc
    with original:
        if original.needs_pass:
            raise ConversionError(password_protected(file_label))
        count = len(original)
        if count == 0:
            raise ConversionError(empty_pdf(file_label))
        with pymupdf.open() as finished:
            for index, page in enumerate(original):
                ctx.check_cancel()
                number = index + 1
                verb = "Flattening and reading text" if use_ocr else "Flattening"
                stage = Stage.OCR if use_ocr else Stage.FLATTENING
                ctx.report(stage, f"{verb}: page {number} of {count}", number, count)
                # 1. Render (rotation is baked into the image, so the new page
                #    uses the page's displayed size and needs no rotation).
                image = render_page(page, ctx.settings.dpi, work / f"page_{number:05d}.png")
                output = finished.new_page(width=page.rect.width, height=page.rect.height)
                if tesseract is not None:
                    # 2. OCR, then 3. stamp the OCR page (image + invisible text)
                    #    stretched to fill the page exactly so the text stays aligned.
                    ocr_pdf = ocr_image_to_pdf(
                        tesseract,
                        image,
                        work / f"ocr_{number:05d}",
                        ctx,
                        file_label=file_label,
                        page_number=number,
                    )
                    with pymupdf.open(str(ocr_pdf)) as scanned:
                        output.show_pdf_page(output.rect, scanned, 0, keep_proportion=False)
                else:
                    output.insert_image(output.rect, filename=str(image), keep_proportion=False)
                # Page images and OCR PDFs stay in the scratch folder until the
                # whole job is finished. Deleting them immediately can fail on
                # Windows (WinError 32) because a PDF renderer or a real-time
                # virus scanner may still hold them open. The API layer deletes
                # the scratch folder after the results are saved or discarded.
            set_bookmarks(finished, read_bookmarks(original))
            # garbage=4 removes unused and duplicate objects; deflate compresses streams.
            finished.save(str(target), garbage=4, deflate=True)

    verify_flattened(target, count, file_label)


def verify_flattened(path: Path, expected_pages: int, file_label: str) -> None:
    """Strict final check: the page count matches and every page has an image.

    Raises:
        ConversionError: ``FLATTEN_CHECK_FAILED`` describing what's wrong.
    """
    with pymupdf.open(str(path)) as check:
        if len(check) != expected_pages:
            details = f"Expected {expected_pages} pages, found {len(check)}."
            raise ConversionError(flatten_check_failed(file_label, details))
        missing = [i + 1 for i, page in enumerate(check) if not page.get_images()]
        if missing:
            details = "Pages without an image: " + ", ".join(map(str, missing[:20]))
            raise ConversionError(flatten_check_failed(file_label, details))
    log.debug("Flatten check passed for %s (%d pages)", file_label, expected_pages)
