"""End-to-end tests through run_action, the single entry point.

Needs Tesseract (English) and LibreOffice; tests that need a missing tool are skipped.
Split, Images to PDF and Compress have their own module tests.
"""

from __future__ import annotations

import hashlib
import shutil

import fitz
import pytest
from pptx import Presentation

from converter import (
    Action,
    ActionData,
    ActionSettings,
    Cancelled,
    CancelToken,
    CompressLevel,
    ConversionError,
    IssueCode,
    SplitMethod,
    run_action,
    safe_destination,
)
from tests.helpers import page_texts, scanned_pdf, text_pdf

needs_ocr = pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")
needs_lo = pytest.mark.skipif(
    not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice not installed"
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    pdf = text_pdf(tmp_path / "Document A.pdf", ["Quarterly summary document"], size=(480, 300))
    pres = Presentation()
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    box = slide.shapes.add_textbox(1_000_000, 1_000_000, 7_000_000, 1_000_000)
    box.text_frame.text = "Project overview and timeline"
    slide.notes_slide.notes_text_frame.text = "Presenter notes: never in the output."
    pptx = tmp_path / "Document B.pptx"
    pres.save(str(pptx))
    return pdf, pptx


def run(action, files, tmp_path, name, **settings):
    events = []
    result = run_action(
        action,
        ActionSettings(**settings),
        ActionData(files),
        scratch=tmp_path / name,
        progress=events.append,
    )
    return result, events


@needs_ocr
@needs_lo
def test_flatten_with_ocr(tmp_path, inputs):
    pdf, pptx = inputs
    before = {p: sha(p) for p in inputs}
    result, events = run(Action.FLATTEN, [pdf, pptx], tmp_path, "w", use_ocr=True)
    assert [o.name for o in result.outputs] == [
        "Document A - Flattened Searchable.pdf",
        "Document B - Flattened Searchable.pdf",
    ]
    for output in result.outputs:
        with fitz.open(str(output.path)) as doc:
            assert len(doc) == output.page_count == 1
            assert all(page.get_images() for page in doc)
    assert "Quarterly" in page_texts(result.outputs[0].path)[0]
    assert "overview" in page_texts(result.outputs[1].path)[0].lower()
    assert "Presenter notes" not in "".join(page_texts(result.outputs[1].path))
    assert {p: sha(p) for p in inputs} == before, "inputs must never change"
    fractions = [e.fraction for e in events]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0


def test_flatten_without_ocr_has_no_text_layer(tmp_path, inputs):
    pdf, _ = inputs
    result, _ = run(Action.FLATTEN, [pdf], tmp_path, "w", dpi=100)
    assert result.outputs[0].name == "Document A - Flattened.pdf"
    assert not page_texts(result.outputs[0].path)[0].strip()


@needs_ocr
@needs_lo
def test_flatten_merge_keeps_order_and_adds_contents(tmp_path, inputs):
    pdf, pptx = inputs
    result, events = run(
        Action.FLATTEN_MERGE, [pptx, pdf], tmp_path, "w", use_ocr=True, contents_page=True
    )
    [output] = result.outputs
    assert output.name == "Document B + 1 more - Flattened Searchable Merged.pdf"
    texts = page_texts(output.path)
    assert len(texts) == 3 and "Contents" in texts[0]
    assert "overview" in texts[1].lower() and "Quarterly" in texts[2]
    with fitz.open(str(output.path)) as doc:
        # Top level: the contents page, then one bookmark per file in order. (LibreOffice adds
        # its own "Slide N" bookmarks to rendered slides; those are nested one level down.)
        top = [title for level, title, _ in doc.get_toc(simple=True) if level == 1]
        assert top == ["Contents", "Document B", "Document A"]
    fractions = [e.fraction for e in events]
    assert fractions == sorted(fractions), "progress must never go backwards"


@needs_lo
def test_merge_keeps_original_text(tmp_path, inputs):
    pdf, pptx = inputs
    result, _ = run(Action.MERGE, [pdf, pptx], tmp_path, "w")
    [output] = result.outputs
    assert output.name == "Document A + 1 more - Merged.pdf"
    with fitz.open(str(output.path)) as doc:
        assert len(doc) == 2
        assert not doc[0].get_images(), "Merge must not rasterize the PDF"
        assert "Quarterly" in doc[0].get_text()


@needs_ocr
def test_merge_with_ocr_makes_scans_searchable(tmp_path):
    scan = scanned_pdf(tmp_path / "Scan.pdf", ["Scanned sample page"])
    result, _ = run(Action.MERGE, [scan], tmp_path, "w", use_ocr=True)
    assert "Scanned" in page_texts(result.outputs[0].path)[0]


def test_wrong_file_type_for_action(tmp_path, inputs):
    pdf, _ = inputs
    with pytest.raises(ConversionError) as err:
        run(Action.IMAGES_TO_PDF, [pdf], tmp_path, "w")
    assert err.value.issue.code is IssueCode.UNSUPPORTED_FILE


def test_missing_ocr_stops_before_any_work(tmp_path, inputs, monkeypatch):
    monkeypatch.setattr("converter.ocr.find_tesseract", lambda configured=None: None)
    with pytest.raises(ConversionError) as err:
        run(Action.FLATTEN, [inputs[0]], tmp_path, "w", use_ocr=True)
    assert err.value.issue.code is IssueCode.OCR_MISSING
    assert not (tmp_path / "w" / "item_001").exists()


def test_cancel_stops_the_job(tmp_path, inputs):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        run_action(
            Action.FLATTEN,
            ActionSettings(),
            ActionData([inputs[0]]),
            scratch=tmp_path / "w",
            cancel=token,
        )


def test_safe_destination_never_overwrites(tmp_path):
    first = safe_destination(tmp_path, "Sample.pdf")
    first.write_text("existing", encoding="utf-8")
    taken: set[str] = set()
    assert safe_destination(tmp_path, "Sample.pdf", taken).name == "Sample (2).pdf"
    assert safe_destination(tmp_path, "Sample.pdf", taken).name == "Sample (3).pdf"


def test_split_ranges_through_run_action(tmp_path):
    src = text_pdf(tmp_path / "Report.pdf", [f"Page {i}" for i in range(1, 7)])
    settings = ActionSettings()
    settings.split.ranges = "1-2, 5"
    result = run_action(Action.SPLIT, settings, ActionData([src]), scratch=tmp_path / "w")
    assert [(o.name, o.page_count) for o in result.outputs] == [
        ("Report - pages 1-2.pdf", 2),
        ("Report - page 5.pdf", 1),
    ]


def test_split_bad_ranges_is_a_clear_issue(tmp_path):
    src = text_pdf(tmp_path / "Report.pdf", ["one", "two"])
    settings = ActionSettings()
    settings.split.ranges = "1-9"
    with pytest.raises(ConversionError) as err:
        run_action(Action.SPLIT, settings, ActionData([src]), scratch=tmp_path / "w")
    assert err.value.issue.code is IssueCode.INVALID_PAGE_RANGES


@needs_lo
def test_split_accepts_powerpoint(tmp_path, inputs):
    _, pptx = inputs
    settings = ActionSettings()
    settings.split.method = SplitMethod.PER_PAGE
    result = run_action(Action.SPLIT, settings, ActionData([pptx]), scratch=tmp_path / "w")
    assert [o.name for o in result.outputs] == ["Document B - page 1.pdf"]


def png(path, text):
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=300)
        page.insert_text((40, 120), text, fontsize=30)
        page.get_pixmap(dpi=150).save(str(path))
    return path


@needs_ocr
def test_images_combined_with_ocr(tmp_path):
    images = [png(tmp_path / "First.png", "Image one text"), png(tmp_path / "b.png", "Second")]
    result = run_action(
        Action.IMAGES_TO_PDF,
        ActionSettings(use_ocr=True, combine_images=True),
        ActionData(images),
        scratch=tmp_path / "w",
    )
    [output] = result.outputs
    assert output.name == "First + 1 more - Images.pdf" and output.page_count == 2
    assert "Image one" in page_texts(output.path)[0]


def test_images_one_pdf_each(tmp_path):
    images = [png(tmp_path / "a.png", "A"), png(tmp_path / "b.png", "B")]
    result = run_action(
        Action.IMAGES_TO_PDF,
        ActionSettings(combine_images=False),
        ActionData(images),
        scratch=tmp_path / "w",
    )
    assert [o.name for o in result.outputs] == ["a.pdf", "b.pdf"]


def test_compress_through_run_action(tmp_path):
    src = text_pdf(tmp_path / "Report.pdf", ["Keep this text"])
    before = sha(src)
    result = run_action(
        Action.COMPRESS,
        ActionSettings(compress_level=CompressLevel.STRONG),
        ActionData([src]),
        scratch=tmp_path / "w",
    )
    [output] = result.outputs
    assert output.name == "Report - Compressed.pdf"
    assert output.size_bytes <= src.stat().st_size
    assert "Keep this text" in page_texts(output.path)[0]
    assert sha(src) == before
