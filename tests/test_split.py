"""Tests for converter.split: range parsing, split planning and writing the parts."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from converter.common import SplitMethod, SplitSettings, Stage
from converter.context import JobContext
from converter.issues import Cancelled, ConversionError, IssueCode
from converter.split import _fix_toc_levels, parse_page_ranges, plan_split, split_pdf


def _reason(text: str, page_count: int = 10) -> str:
    """Parse ``text`` expecting failure and return the user-facing message.

    Args:
        text: Range text to parse.
        page_count: Pages in the pretend document.

    Returns:
        The issue message carried by the raised ConversionError.
    """
    with pytest.raises(ConversionError) as info:
        parse_page_ranges(text, page_count)
    assert info.value.issue.code == IssueCode.INVALID_PAGE_RANGES
    return info.value.issue.message


# --- parse_page_ranges: valid input ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1-3, 5, 8-10", [(1, 3), (5, 5), (8, 10)]),
        ("5", [(5, 5)]),
        ("1-10", [(1, 10)]),
        ("10, 1", [(10, 10), (1, 1)]),  # Typed order is kept.
        ("  2 -  4 ,6  ", [(2, 4), (6, 6)]),  # Spaces anywhere around numbers and dashes.
        ("\t1-2,\n3", [(1, 2), (3, 3)]),  # Tabs and newlines count as spaces.
        ("1–3", [(1, 3)]),  # En dash.
        ("1 – 3, 4—5, 6−7", [(1, 3), (4, 5), (6, 7)]),  # En, em dash, minus.
        ("4-4", [(4, 4)]),  # A one-page range written as a range.
        ("1-3, 2-5", [(1, 3), (2, 5)]),  # Overlaps are allowed.
        ("1-3,", [(1, 3)]),  # Trailing comma.
        ("1,,2", [(1, 1), (2, 2)]),  # Empty item between commas.
        ("007", [(7, 7)]),  # Leading zeros.
    ],
)
def test_parse_valid(text, expected):
    assert parse_page_ranges(text, 10) == expected


# --- parse_page_ranges: errors, with message checks -----------------------------------


@pytest.mark.parametrize("text", ["", "   ", ",", " , , "])
def test_parse_empty_input(text):
    message = _reason(text)
    assert "Type the pages" in message
    assert "1-3, 5, 8-10" in message


def test_parse_page_beyond_end():
    assert _reason("12") == "Page 12 doesn't exist; this document has 10 pages."


def test_parse_range_end_beyond_end():
    assert _reason("8-12") == "Page 12 doesn't exist; this document has 10 pages."


def test_parse_beyond_end_singular_page():
    assert _reason("2", page_count=1) == "Page 2 doesn't exist; this document has 1 page."


def test_parse_start_after_end():
    message = _reason("3-1")
    assert message.startswith("'3-1' starts after it ends.")
    assert "1-3" in message.split("ends.")[1]  # Suggests the fixed range.


def test_parse_start_after_end_quotes_en_dash_as_typed():
    assert _reason("3–1").startswith("'3–1' starts after it ends.")


@pytest.mark.parametrize("text", ["0", "0-3", "1, 0"])
def test_parse_page_zero(text):
    assert _reason(text) == "There's no page 0; pages start at 1."


@pytest.mark.parametrize("text", ["abc", "1.5", "two", "²", "1 0"])
def test_parse_not_a_number(text):
    assert _reason(text) == f"'{text}' isn't a page number. Use whole numbers such as 4 or 4-7."


def test_parse_not_a_number_inside_range():
    message = _reason("2-x")
    assert message.startswith("'x' in '2-x' isn't a page number.")


def test_parse_missing_start():
    assert _reason("-3").startswith("'-3' is missing the first page.")


def test_parse_missing_end():
    assert _reason("3-").startswith("'3-' is missing the last page.")


def test_parse_lone_dash():
    assert _reason("-").startswith("'-' needs page numbers on both sides of the dash")


def test_parse_too_many_dashes():
    assert _reason("1-2-3").startswith("'1-2-3' has more than one dash.")


def test_parse_first_error_wins_in_typed_order():
    # "abc" comes before the out-of-range page, so it is the one reported.
    assert "'abc'" in _reason("1, abc, 99")


def test_parse_error_issue_has_no_file_and_has_steps():
    with pytest.raises(ConversionError) as info:
        parse_page_ranges("99", 10)
    issue = info.value.issue
    assert issue.file is None
    assert issue.troubleshooting  # Generic steps from invalid_page_ranges.
    assert str(info.value) == issue.message


# --- plan_split -----------------------------------------------------------------------


def test_plan_ranges_uses_parser():
    settings = SplitSettings(method=SplitMethod.RANGES, ranges="1-2, 4")
    assert plan_split(settings, 5) == [(1, 2), (4, 4)]


def test_plan_ranges_propagates_errors():
    with pytest.raises(ConversionError):
        plan_split(SplitSettings(method=SplitMethod.RANGES, ranges=""), 5)


def test_plan_ranges_accepts_plain_string_method():
    # The API layer may pass the enum's string value.
    assert plan_split(SplitSettings(method="ranges", ranges="2"), 5) == [(2, 2)]


@pytest.mark.parametrize(
    ("n", "page_count", "expected"),
    [
        (3, 10, [(1, 3), (4, 6), (7, 9), (10, 10)]),  # Last chunk shorter.
        (5, 10, [(1, 5), (6, 10)]),  # Divides evenly.
        (1, 3, [(1, 1), (2, 2), (3, 3)]),
        (20, 7, [(1, 7)]),  # N larger than the document: one part.
        (2, 1, [(1, 1)]),
    ],
)
def test_plan_every_n(n, page_count, expected):
    settings = SplitSettings(method=SplitMethod.EVERY_N, every_n=n)
    assert plan_split(settings, page_count) == expected


@pytest.mark.parametrize("n", [0, -2, True, 2.5])
def test_plan_every_n_rejects_invalid(n):
    settings = SplitSettings(method=SplitMethod.EVERY_N, every_n=n)
    with pytest.raises(ConversionError) as info:
        plan_split(settings, 10)
    assert info.value.issue.code == IssueCode.INVALID_PAGE_RANGES
    assert "1 or more" in info.value.issue.message


def test_plan_per_page():
    settings = SplitSettings(method=SplitMethod.PER_PAGE)
    assert plan_split(settings, 4) == [(1, 1), (2, 2), (3, 3), (4, 4)]


def test_plan_per_page_ignores_other_fields():
    settings = SplitSettings(method=SplitMethod.PER_PAGE, ranges="nonsense", every_n=0)
    assert plan_split(settings, 2) == [(1, 1), (2, 2)]


# --- split_pdf ------------------------------------------------------------------------

PAGES = 10

# Nested outline used by the fixture: (level, title, page).
SOURCE_TOC = [
    [1, "Chapter A", 1],
    [2, "Section A1", 2],
    [1, "Chapter B", 5],
    [2, "Section B1", 6],
    [3, "Detail B1a", 7],
    [1, "Chapter C", 9],
]


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Build a 10-page PDF with text, bookmarks, links and an annotation.

    Page 1 has a link to page 3 and a web link; page 2 has a text note.

    Args:
        tmp_path: pytest's temporary folder.

    Returns:
        Path to the saved PDF.
    """
    path = tmp_path / "Sample.pdf"
    with fitz.open() as doc:
        for number in range(1, PAGES + 1):
            page = doc.new_page()
            page.insert_text((72, 72), f"Sample page {number}")
        goto = {"kind": fitz.LINK_GOTO, "from": fitz.Rect(72, 100, 200, 120), "page": 2}
        web = {"kind": fitz.LINK_URI, "from": fitz.Rect(72, 130, 200, 150)}
        web["uri"] = "https://example.com/"
        doc[0].insert_link(goto)
        doc[0].insert_link(web)
        doc[1].add_text_annot((72, 200), "A sample note")
        doc.set_toc(SOURCE_TOC)
        doc.set_metadata({"title": "Sample title"})
        doc.save(str(path))
    return path


def _split(source: Path, out_dir: Path, settings: SplitSettings, ctx: JobContext | None = None):
    """Run split_pdf with the base name "Sample" and a default context.

    Args:
        source: PDF to split.
        out_dir: Output folder.
        settings: Split settings.
        ctx: Optional job context.

    Returns:
        The list of OutputFile entries.
    """
    return split_pdf(source, out_dir, "Sample", settings, ctx or JobContext())


def _page_text(path: Path, page: int = 0) -> str:
    """Return the text of one page of a PDF, stripped.

    Args:
        path: PDF to read.
        page: 0-based page index.

    Returns:
        The page text.
    """
    with fitz.open(str(path)) as doc:
        return doc[page].get_text().strip()


def _toc(path: Path) -> list[list]:
    """Return a PDF's simple outline.

    Args:
        path: PDF to read.

    Returns:
        ``[level, title, page]`` entries.
    """
    with fitz.open(str(path)) as doc:
        return doc.get_toc()


def test_split_ranges_names_counts_and_content(sample_pdf, tmp_path):
    settings = SplitSettings(method=SplitMethod.RANGES, ranges="1-3, 5, 8–10")
    outputs = _split(sample_pdf, tmp_path / "out", settings)
    assert [o.name for o in outputs] == [
        "Sample - pages 1-3.pdf",
        "Sample - page 5.pdf",
        "Sample - pages 8-10.pdf",
    ]
    assert [o.page_count for o in outputs] == [3, 1, 3]
    for output in outputs:
        assert output.path.is_file()
        assert output.path.parent == tmp_path / "out"
        assert output.size_bytes == output.path.stat().st_size
        with fitz.open(str(output.path)) as doc:
            assert doc.page_count == output.page_count
            assert doc.metadata["title"] == "Sample title"
    assert _page_text(outputs[1].path) == "Sample page 5"
    assert _page_text(outputs[2].path, 2) == "Sample page 10"


def test_split_repeated_range_gets_separate_files(sample_pdf, tmp_path):
    outputs = _split(sample_pdf, tmp_path / "out", SplitSettings(ranges="2, 2"))
    assert [o.name for o in outputs] == ["Sample - page 2.pdf", "Sample - page 2.pdf"]
    assert outputs[0].path != outputs[1].path
    assert all(o.path.is_file() for o in outputs)


def test_split_every_n(sample_pdf, tmp_path):
    settings = SplitSettings(method=SplitMethod.EVERY_N, every_n=4)
    outputs = _split(sample_pdf, tmp_path / "out", settings)
    assert [o.name for o in outputs] == [
        "Sample - pages 1-4.pdf",
        "Sample - pages 5-8.pdf",
        "Sample - pages 9-10.pdf",
    ]
    assert [o.page_count for o in outputs] == [4, 4, 2]
    assert _page_text(outputs[2].path) == "Sample page 9"


def test_split_per_page(sample_pdf, tmp_path):
    outputs = _split(sample_pdf, tmp_path / "out", SplitSettings(method=SplitMethod.PER_PAGE))
    assert len(outputs) == PAGES
    assert outputs[6].name == "Sample - page 7.pdf"
    assert all(o.page_count == 1 for o in outputs)
    assert _page_text(outputs[6].path) == "Sample page 7"


def test_split_bookmarks_shifted_and_levels_fixed(sample_pdf, tmp_path):
    outputs = _split(sample_pdf, tmp_path / "out", SplitSettings(ranges="6-10, 1-3, 5, 3-4"))
    # Chapter B (level 1) is outside 6-10, so its children move up one level.
    assert _toc(outputs[0].path) == [
        [1, "Section B1", 1],
        [2, "Detail B1a", 2],
        [1, "Chapter C", 4],
    ]
    assert _toc(outputs[1].path) == [[1, "Chapter A", 1], [2, "Section A1", 2]]
    assert _toc(outputs[2].path) == [[1, "Chapter B", 1]]
    assert _toc(outputs[3].path) == []  # No bookmarks on pages 3-4.


def test_split_bookmark_keeps_position_on_page(tmp_path):
    source = tmp_path / "Positioned.pdf"
    with fitz.open() as doc:
        for _ in range(3):
            doc.new_page()
        dest = {"kind": fitz.LINK_GOTO, "page": 2, "to": fitz.Point(0, 300), "zoom": 0}
        doc.set_toc([[1, "Lower on page 3", 3, dest]])
        doc.save(str(source))
    (output,) = _split(source, tmp_path / "out", SplitSettings(ranges="2-3"))
    with fitz.open(str(output.path)) as doc:
        ((level, title, page, detail),) = doc.get_toc(simple=False)
    assert (level, title, page) == (1, "Lower on page 3", 2)
    assert detail["page"] == 1
    assert detail["to"].y == pytest.approx(300, abs=1)


def test_fix_toc_levels_keeps_structure():
    toc = [[3, "a", 1], [4, "b", 1], [3, "c", 2], [2, "d", 3], [5, "e", 3], [3, "f", 4]]
    # a and c are siblings; d is a shallower heading; e and f both sit under d.
    assert [entry[0] for entry in _fix_toc_levels(toc)] == [1, 2, 1, 1, 2, 2]


def test_split_keeps_links_and_annotations(sample_pdf, tmp_path):
    outputs = _split(sample_pdf, tmp_path / "out", SplitSettings(ranges="1-3, 2"))
    with fitz.open(str(outputs[0].path)) as doc:
        links = doc[0].get_links()
        internal = [link for link in links if link["kind"] == fitz.LINK_GOTO]
        external = [link for link in links if link["kind"] == fitz.LINK_URI]
        assert [link["page"] for link in internal] == [2]  # Still points at "Sample page 3".
        assert [link["uri"] for link in external] == ["https://example.com/"]
        assert [annot.info["content"] for annot in doc[1].annots()] == ["A sample note"]
    with fitz.open(str(outputs[1].path)) as doc:
        assert [annot.info["content"] for annot in doc[0].annots()] == ["A sample note"]


def test_split_drops_links_to_pages_outside_the_part(sample_pdf, tmp_path):
    (output,) = _split(sample_pdf, tmp_path / "out", SplitSettings(ranges="1-2"))
    with fitz.open(str(output.path)) as doc:
        kinds = [link["kind"] for link in doc[0].get_links()]
    assert fitz.LINK_URI in kinds
    assert fitz.LINK_GOTO not in kinds  # Page 3 isn't in this part.


def test_split_reports_progress(sample_pdf, tmp_path):
    events = []
    ctx = JobContext(progress=events.append)
    _split(sample_pdf, tmp_path / "out", SplitSettings(ranges="1, 2, 3, 4"), ctx)
    assert {event.stage for event in events} == {Stage.SPLITTING}
    fractions = [event.fraction for event in events]
    assert fractions == sorted(fractions)
    assert fractions[0] == 0.0 and fractions[-1] == 1.0
    assert events[0].message == "Splitting: part 1 of 4"


def test_split_cancel_stops_between_parts(sample_pdf, tmp_path):
    ctx = JobContext()

    def cancel_on_first_report(event):
        """Press Cancel as soon as the first part starts."""
        ctx.cancel.cancel()

    ctx.progress = cancel_on_first_report
    out_dir = tmp_path / "out"
    with pytest.raises(Cancelled):
        _split(sample_pdf, out_dir, SplitSettings(method=SplitMethod.PER_PAGE), ctx)
    # The part in progress finishes; nothing after it is started.
    assert sorted(p.name for p in out_dir.iterdir()) == ["part_001.pdf"]


def test_split_cancel_before_start_writes_nothing(sample_pdf, tmp_path):
    ctx = JobContext()
    ctx.cancel.cancel()
    out_dir = tmp_path / "out"
    with pytest.raises(Cancelled):
        _split(sample_pdf, out_dir, SplitSettings(method=SplitMethod.PER_PAGE), ctx)
    assert list(out_dir.iterdir()) == []


def test_split_invalid_ranges_names_the_file(sample_pdf, tmp_path):
    with pytest.raises(ConversionError) as info:
        _split(sample_pdf, tmp_path / "out", SplitSettings(ranges="11"))
    assert info.value.issue.code == IssueCode.INVALID_PAGE_RANGES
    assert info.value.issue.file == "Sample.pdf"
    assert info.value.issue.message == "Page 11 doesn't exist; this document has 10 pages."


def test_split_leaves_source_unchanged(sample_pdf, tmp_path):
    before = sample_pdf.read_bytes()
    _split(sample_pdf, tmp_path / "out", SplitSettings(method=SplitMethod.EVERY_N, every_n=3))
    assert sample_pdf.read_bytes() == before


def test_split_unreadable_file(tmp_path):
    broken = tmp_path / "Broken.pdf"
    broken.write_bytes(b"this is not a pdf")
    with pytest.raises(ConversionError) as info:
        _split(broken, tmp_path / "out", SplitSettings(ranges="1"))
    assert info.value.issue.code == IssueCode.UNREADABLE_FILE
    assert info.value.issue.file == "Broken.pdf"


def test_split_password_protected(tmp_path):
    locked = tmp_path / "Locked.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(locked), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(ConversionError) as info:
        _split(locked, tmp_path / "out", SplitSettings(ranges="1"))
    assert info.value.issue.code == IssueCode.PASSWORD_PROTECTED
