"""Flattening PDF pages to images and adding a searchable Tesseract OCR text layer."""

from __future__ import annotations

from pathlib import Path

import fitz

from .common import DPI, Progress
from .tools import require_tesseract, run_command


def flatten_searchable(
    source: Path,
    target: Path,
    work: Path,
    report: Progress,
    engine: str | Path | None = None,
    dpi: int = DPI,
) -> None:
    """Turn a PDF into an image-only PDF that is still searchable.

    This is the core "Flatten" feature. Each page goes through three steps:

    1. **Render**: draw the page (text, vector graphics, annotations,
       everything visible) to a single RGB image at ``dpi``. This removes the
       layers, fonts and form fields that some PDF apps struggle with.
    2. **OCR**: run Tesseract on the image. With the ``pdf`` output option,
       Tesseract writes a one-page PDF holding the image plus an invisible text
       layer positioned over the words, so the text can be searched and
       selected.
    3. **Assemble**: place that OCR page into the output at the original
       page's size.

    Afterwards the output is checked for page images.

    Args:
        source: PDF to flatten. It is only read, never modified.
        target: Where to save the flattened PDF.
        work: Scratch folder for the per-page images and OCR PDFs.
        report: Progress callback; called once per page.
        engine: Optional user-chosen path to ``tesseract.exe``.
        dpi: Render resolution. Note: :func:`converter.pipeline.process_files`
            doesn't pass this, so it is currently always :data:`DPI`.

    Raises:
        RuntimeError: Tesseract is missing or failed on a page, or the output
            has no page images.
        ValueError: The PDF is password-protected or has no pages.
        subprocess.TimeoutExpired: Tesseract took over 5 minutes on one page.
    """
    tess = require_tesseract(engine)
    work.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(source)) as original:
        if original.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        if len(original) == 0:
            raise ValueError("PDF has no pages.")
        with fitz.open() as finished:
            for page_no, page in enumerate(original, 1):
                report(f"Flattening and OCR: page {page_no} / {len(original)}")
                # 1. Render. PDF units are 1/72 inch, so scale by dpi / 72.
                # No alpha channel: the page is drawn onto a white background.
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=fitz.csRGB, alpha=False
                )
                img = work / f"page_{page_no:05d}.png"
                pix.save(str(img))
                # 2. OCR. Tesseract appends ".pdf" to the output base name.
                # "--dpi" tells it the image resolution so the PDF page gets the
                # right physical size; "-l eng" selects English.
                ocr_base = work / f"ocr_{page_no:05d}"
                proc = run_command(
                    [str(tess), str(img), str(ocr_base), "-l", "eng", "--dpi", str(dpi), "pdf"],
                    timeout=300,
                )
                if proc.returncode:
                    raise RuntimeError(f"OCR failed on page {page_no}: {proc.stderr.strip()[:400]}")
                ocr_pdf = Path(str(ocr_base) + ".pdf")
                if not ocr_pdf.is_file():
                    raise RuntimeError(f"OCR did not generate a PDF for page {page_no}.")
                # 3. Assemble. Stamp the OCR page (image + invisible text) onto
                # a new page with the original dimensions, stretched to fill it
                # exactly so the text layer stays aligned with the image.
                with fitz.open(str(ocr_pdf)) as scanned:
                    output = finished.new_page(width=page.rect.width, height=page.rect.height)
                    output.show_pdf_page(output.rect, scanned, 0, keep_proportion=False)
                # Intentionally keep page images and OCR PDFs in the dedicated
                # scratch folder until the *entire* finished document is saved
                # and closed. Immediate unlink can raise WinError 32 on Windows
                # because the OCR PDF may still be locked by a PDF renderer or
                # real-time scanner. The app cleans scratch only after final
                # results have been copied to the user-selected save folder.
            # garbage=4 removes unused and duplicate objects; deflate compresses
            # streams. Both keep the output file small.
            finished.save(str(target), garbage=4, deflate=True)

    # Sanity check. Note: this passes if *any* page has an image, so it would
    # not catch a single page that failed to flatten.
    with fitz.open(str(target)) as check:
        if not any(page.get_images() for page in check):
            raise RuntimeError("Flattening failed: no image-backed pages found.")
