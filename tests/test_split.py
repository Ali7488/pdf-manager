"""Tests for converter.split: range parsing, split planning and writing the parts."""

from __future__ import annotations

import pytest

from converter.common import SplitMethod, SplitSettings
from converter.issues import ConversionError, IssueCode
from converter.split import parse_page_ranges, plan_split


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
