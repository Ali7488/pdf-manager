"""Tests for bookmark repair."""

from __future__ import annotations

import fitz

from converter.pdf.bookmarks import normalize_toc, read_bookmarks, set_bookmarks


def test_normalize_fixes_levels_and_drops_bad_pages():
    toc = [[2, "Starts too deep", 1], [4, "Jumps", 2], [1, "", 3], [1, "Out of range", 9]]
    assert normalize_toc(toc, page_count=3) == [
        [1, "Starts too deep", 1],
        [2, "Jumps", 2],
        [1, "Untitled", 3],
    ]


def test_set_bookmarks_never_raises_and_round_trips():
    with fitz.open() as doc:
        for _ in range(3):
            doc.new_page()
        set_bookmarks(doc, [[3, "A", 1], [1, "B", 3]])
        assert read_bookmarks(doc) == [[1, "A", 1], [1, "B", 3]]
