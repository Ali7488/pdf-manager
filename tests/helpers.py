"""Shared builders for test documents. Neutral sample text only."""

from __future__ import annotations

from pathlib import Path

import fitz


def text_pdf(path: Path, pages: list[str], size=(600, 400), toc=None) -> Path:
    """Write a PDF with one line of real (extractable) text per page."""
    with fitz.open() as doc:
        for text in pages:
            page = doc.new_page(width=size[0], height=size[1])
            page.insert_text((40, 120), text, fontsize=28)
        if toc:
            doc.set_toc(toc)
        doc.save(str(path))
    return path


def scanned_pdf(path: Path, pages: list[str], size=(600, 400), rotation: int = 0) -> Path:
    """Write a PDF whose pages are *images* of text (like a scan): no extractable text."""
    with fitz.open() as doc:
        for text in pages:
            with fitz.open() as tmp:
                src = tmp.new_page(width=size[0], height=size[1])
                src.insert_text((40, 120), text, fontsize=28)
                png = src.get_pixmap(dpi=200).tobytes("png")
            page = doc.new_page(width=size[0], height=size[1])
            page.insert_image(page.rect, stream=png)
            if rotation:
                page.set_rotation(rotation)
        doc.save(str(path))
    return path


def page_texts(path: Path) -> list[str]:
    with fitz.open(str(path)) as doc:
        return [page.get_text() for page in doc]
