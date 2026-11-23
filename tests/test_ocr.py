"""Tests for the OCR text layer (needs Tesseract with English installed)."""

from __future__ import annotations

import shutil

import fitz
import pytest

from converter.common import ActionSettings
from converter.context import JobContext
from converter.issues import ConversionError, IssueCode
from converter.ocr import add_text_layer
from tests.helpers import page_texts, scanned_pdf, text_pdf

needs_tesseract = pytest.mark.skipif(
    not shutil.which("tesseract"), reason="Tesseract not installed"
)


@needs_tesseract
def test_text_layer_added_only_to_image_pages(tmp_path):
    scanned = scanned_pdf(tmp_path / "scan.pdf", ["Quarterly summary"])
    texty = text_pdf(tmp_path / "text.pdf", ["Already searchable"])
    with fitz.open(str(scanned)) as a, fitz.open(str(texty)) as b, fitz.open() as mixed:
        mixed.insert_pdf(a)
        mixed.insert_pdf(b)
        mixed.save(str(tmp_path / "mixed.pdf"))
    done = add_text_layer(
        tmp_path / "mixed.pdf", tmp_path / "out.pdf", tmp_path / "w", JobContext(), "mixed.pdf"
    )
    assert done == 1
    texts = page_texts(tmp_path / "out.pdf")
    assert "Quarterly" in texts[0]
    assert "Already searchable" in texts[1]
    with fitz.open(str(tmp_path / "out.pdf")) as out:
        assert out[0].get_images(), "the page should still look the same (image kept)"


@needs_tesseract
def test_text_layer_lines_up_on_rotated_page(tmp_path):
    src = scanned_pdf(tmp_path / "rot.pdf", ["Rotated sample page"], rotation=90)
    add_text_layer(src, tmp_path / "out.pdf", tmp_path / "w", JobContext(), "rot.pdf")
    with fitz.open(str(tmp_path / "out.pdf")) as doc:
        page = doc[0]
        assert "Rotated" in page.get_text()
        # Every recognised word must sit inside the visible page area.
        for word in page.get_text("words"):
            assert fitz.Rect(word[:4]).intersects(page.rect)


def test_missing_tesseract_is_a_clear_issue(tmp_path, monkeypatch):
    monkeypatch.setattr("converter.ocr.find_tesseract", lambda configured=None: None)
    src = scanned_pdf(tmp_path / "scan.pdf", ["x"])
    with pytest.raises(ConversionError) as err:
        add_text_layer(
            src, tmp_path / "o.pdf", tmp_path / "w", JobContext(ActionSettings()), "scan.pdf"
        )
    assert err.value.issue.code is IssueCode.OCR_MISSING
