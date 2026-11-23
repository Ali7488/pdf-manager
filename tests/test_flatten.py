"""Tests for flattening (OCR tests need Tesseract)."""

from __future__ import annotations

import shutil

import pymupdf
import pytest

from converter.actions.flatten import flatten_pdf, verify_flattened
from converter.core.context import JobContext
from converter.core.issues import ConversionError, IssueCode
from converter.core.types import ActionSettings
from tests.helpers import page_texts, text_pdf

needs_tesseract = pytest.mark.skipif(
    not shutil.which("tesseract"), reason="Tesseract not installed"
)
TOC = [[1, "Intro", 1], [2, "Detail", 2], [1, "End", 3]]


def flatten(tmp_path, use_ocr, **kwargs):
    src = text_pdf(tmp_path / "in.pdf", ["Alpha page", "Beta page", "Gamma page"], toc=TOC)
    out = tmp_path / "out.pdf"
    flatten_pdf(
        src, out, tmp_path / "w", JobContext(ActionSettings(use_ocr=use_ocr, **kwargs)), "in.pdf"
    )
    return src, out


def test_without_ocr_pages_become_images_with_no_text(tmp_path):
    src, out = flatten(tmp_path, use_ocr=False, dpi=100)
    with pymupdf.open(str(out)) as doc:
        assert len(doc) == 3
        assert all(page.get_images() for page in doc)
    assert all(not text.strip() for text in page_texts(out)), "no OCR means no text layer"


@needs_tesseract
def test_with_ocr_pages_are_images_and_searchable(tmp_path):
    _, out = flatten(tmp_path, use_ocr=True)
    texts = page_texts(out)
    assert "Alpha" in texts[0] and "Gamma" in texts[2]
    with pymupdf.open(str(out)) as doc:
        assert all(page.get_images() for page in doc)


def test_bookmarks_are_kept(tmp_path):
    _, out = flatten(tmp_path, use_ocr=False, dpi=72)
    with pymupdf.open(str(out)) as doc:
        assert doc.get_toc(simple=True) == TOC


def test_source_is_not_modified(tmp_path):
    src = text_pdf(tmp_path / "in.pdf", ["Alpha"])
    before = src.read_bytes()
    flatten_pdf(
        src, tmp_path / "o.pdf", tmp_path / "w", JobContext(ActionSettings(dpi=72)), "in.pdf"
    )
    assert src.read_bytes() == before


def test_password_protected_input_is_a_clear_issue(tmp_path):
    src = tmp_path / "locked.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(str(src), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="o")
    with pytest.raises(ConversionError) as err:
        flatten_pdf(src, tmp_path / "o.pdf", tmp_path / "w", JobContext(), "locked.pdf")
    assert err.value.issue.code is IssueCode.PASSWORD_PROTECTED


def test_strict_check_catches_a_page_without_an_image(tmp_path):
    bad = text_pdf(tmp_path / "bad.pdf", ["text only"])
    with pytest.raises(ConversionError) as err:
        verify_flattened(bad, 1, "bad.pdf")
    assert err.value.issue.code is IssueCode.FLATTEN_CHECK_FAILED
    with pytest.raises(ConversionError):
        verify_flattened(bad, 2, "bad.pdf")  # page count mismatch
