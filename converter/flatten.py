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
    """Rasterize all visible content, then add Tesseract English OCR text per page."""
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
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=fitz.csRGB, alpha=False
                )
                img = work / f"page_{page_no:05d}.png"
                pix.save(str(img))
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
                with fitz.open(str(ocr_pdf)) as scanned:
                    output = finished.new_page(width=page.rect.width, height=page.rect.height)
                    output.show_pdf_page(output.rect, scanned, 0, keep_proportion=False)
                # Intentionally keep page images and OCR PDFs in the dedicated
                # scratch folder until the *entire* finished document is saved
                # and closed. Immediate unlink can raise WinError 32 on Windows
                # because the OCR PDF may still be locked by a PDF renderer or
                # real-time scanner. The app cleans scratch only after final
                # results have been copied to the user-selected save folder.
            finished.save(str(target), garbage=4, deflate=True)

    with fitz.open(str(target)) as check:
        if not any(page.get_images() for page in check):
            raise RuntimeError("Flattening failed: no image-backed pages found.")
