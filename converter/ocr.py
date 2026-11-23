"""OCR with Tesseract: reading the text in page images and making it searchable.

Two ways OCR is used:

* **Flatten** (``flatten.py``) replaces each page with an image plus an
  invisible text layer, using :func:`ocr_image_to_pdf`.
* **Text layer only** (:func:`add_text_layer`) keeps every page exactly as it
  is and adds invisible text to pages that have none (scans, photos). Used by
  Merge, Split and Images to PDF when "Use OCR" is ticked.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import fitz

from .common import Stage
from .context import JobContext
from .issues import ConversionError, ocr_failed, ocr_missing, ocr_timeout, unreadable_file
from .tools import find_tesseract, run_command

log = logging.getLogger(__name__)


def require_ocr(ctx: JobContext) -> Path:
    """Return the Tesseract executable, or stop the job with a clear OCR-missing issue."""
    tesseract = find_tesseract(ctx.settings.tesseract_path)
    if tesseract is None:
        raise ConversionError(ocr_missing())
    return tesseract


def render_page(page: fitz.Page, dpi: int, target: Path) -> Path:
    """Draw a page (everything visible on it) as an RGB PNG image at ``dpi``.

    PDF units are 1/72 inch, so the page is scaled by ``dpi / 72``. There's no
    transparency: the page is drawn on white.
    """
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=fitz.csRGB, alpha=False
    )
    pixmap.save(str(target))
    return target


def ocr_image_to_pdf(
    tesseract: Path,
    image: Path,
    out_base: Path,
    ctx: JobContext,
    *,
    file_label: str,
    page_number: int,
    text_only: bool = False,
) -> Path:
    """Run Tesseract on one page image and get a one-page PDF back.

    Args:
        tesseract: The Tesseract executable.
        image: Page image to read.
        out_base: Output path without extension; Tesseract adds ".pdf".
        ctx: Job context (language, DPI, page timeout and cancel come from here).
        file_label: Input file name, for messages.
        page_number: 1-based page number, for messages.
        text_only: If True, the PDF contains only the invisible text layer (no
            image), ready to be laid over an existing page.

    Returns:
        Path of the PDF Tesseract wrote.

    Raises:
        ConversionError: Tesseract is missing, failed, or took longer than the
            OCR page timeout (it is stopped).
        Cancelled: The user cancelled while Tesseract was running.
    """
    settings = ctx.settings
    # "--dpi" tells Tesseract the image resolution so the PDF page gets the
    # right physical size; "pdf" asks for PDF output.
    args = [tesseract, image, out_base, "-l", settings.ocr_language, "--dpi", str(settings.dpi)]
    if text_only:
        args += ["-c", "textonly_pdf=1"]
    args.append("pdf")
    try:
        proc = run_command(args, timeout=settings.ocr_page_timeout_sec, cancel=ctx.cancel)
    except subprocess.TimeoutExpired:
        raise ConversionError(
            ocr_timeout(file_label, page_number, settings.ocr_page_timeout_sec)
        ) from None
    except FileNotFoundError:
        raise ConversionError(ocr_missing()) from None
    if proc.returncode:
        raise ConversionError(ocr_failed(file_label, page_number, proc.stderr or proc.stdout))
    pdf = Path(f"{out_base}.pdf")
    if not pdf.is_file():
        raise ConversionError(
            ocr_failed(file_label, page_number, "Tesseract finished but wrote no PDF.")
        )
    return pdf


def page_needs_ocr(page: fitz.Page) -> bool:
    """True if a page has no extractable text, i.e. it is an image of text (or blank)."""
    return not page.get_text().strip()


def add_text_layer(source: Path, target: Path, work: Path, ctx: JobContext, file_label: str) -> int:
    """Make image-only pages searchable without changing how any page looks.

    Pages that already contain text are left untouched. Each page without text
    is rendered, read by Tesseract in text-only mode, and the invisible text is
    laid over the original page. Bookmarks, links and annotations are kept
    because the original document is modified in memory and saved as a copy.

    Args:
        source: PDF to read (never modified).
        target: Where to save the searchable copy.
        work: Scratch folder for page images and OCR output.
        ctx: Job context.
        file_label: Input file name, for messages.

    Returns:
        Number of pages that were OCR'd (0 means the copy equals the original).
    """
    tesseract = require_ocr(ctx)
    work.mkdir(parents=True, exist_ok=True)
    try:
        doc = fitz.open(str(source))
    except Exception as exc:
        raise ConversionError(unreadable_file(file_label, str(exc))) from exc
    with doc:
        count = len(doc)
        done = 0
        for index, page in enumerate(doc):
            ctx.check_cancel()
            number = index + 1
            if not page_needs_ocr(page):
                continue
            ctx.report(Stage.OCR, f"Reading text: page {number} of {count}", number, count)
            image = render_page(page, ctx.settings.dpi, work / f"page_{number:05d}.png")
            text_pdf = ocr_image_to_pdf(
                tesseract,
                image,
                work / f"text_{number:05d}",
                ctx,
                file_label=file_label,
                page_number=number,
                text_only=True,
            )
            with fitz.open(str(text_pdf)) as text_doc:
                # The rendered image (and so the text layer) shows the page as
                # displayed, including rotation; undo the rotation so the text
                # lands on the right spot in the page's own coordinates.
                page.show_pdf_page(page.rect, text_doc, 0, overlay=True, rotate=-page.rotation)
            done += 1
        log.debug("OCR text layer added to %d of %d pages of %s", done, count, file_label)
        doc.save(str(target), garbage=4, deflate=True)
    return done
