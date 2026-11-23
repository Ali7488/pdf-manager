"""Bookmark (table of contents) helpers shared by flatten, merge and split."""

from __future__ import annotations

import logging

import pymupdf

log = logging.getLogger(__name__)

# A bookmark as PyMuPDF's simple TOC format: [level, title, 1-based page].
Bookmark = list


def normalize_toc(toc: list[Bookmark], page_count: int) -> list[Bookmark]:
    """Repair a bookmark list so PyMuPDF will accept it.

    Real-world PDFs often have slightly broken outlines. PyMuPDF rejects a TOC
    whose first entry isn't level 1, or where a level jumps by more than one
    (e.g. 1 → 3). This:

    * drops entries pointing outside ``1..page_count`` (or with no page),
    * makes the first entry level 1 and caps each level at previous + 1,
    * gives untitled entries a placeholder title.

    Args:
        toc: Entries as ``[level, title, page]`` (extra items are ignored).
        page_count: Pages in the document the TOC will be set on.

    Returns:
        A new, valid list of ``[level, title, page]`` entries.
    """
    cleaned: list[Bookmark] = []
    previous_level = 0
    for entry in toc:
        level, title, page = int(entry[0]), str(entry[1] or "").strip(), int(entry[2])
        if not 1 <= page <= page_count:
            continue
        level = max(1, min(level, previous_level + 1))
        cleaned.append([level, title or "Untitled", page])
        previous_level = level
    return cleaned


def set_bookmarks(doc: pymupdf.Document, toc: list[Bookmark]) -> None:
    """Set ``doc``'s bookmarks, repairing them first. Never fails the job.

    If PyMuPDF still rejects the list, the document is saved without
    bookmarks and the problem is logged; losing bookmarks is better than
    losing the whole conversion.
    """
    cleaned = normalize_toc(toc, len(doc))
    try:
        doc.set_toc(cleaned)
    except Exception:
        log.warning("Couldn't set %d bookmarks; saving without them.", len(cleaned), exc_info=True)


def read_bookmarks(doc: pymupdf.Document) -> list[Bookmark]:
    """Return ``doc``'s bookmarks as ``[level, title, page]``, or ``[]`` if unreadable."""
    try:
        return [list(entry[:3]) for entry in doc.get_toc(simple=True)]
    except Exception:
        log.debug("Couldn't read bookmarks.", exc_info=True)
        return []
