"""Merging several PDFs into one, with bookmarks, an optional contents page and page labels."""

from __future__ import annotations

import html
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from ..core.context import JobContext
from ..core.issues import (
    ConversionError,
    empty_pdf,
    merge_failed,
    password_protected,
    unreadable_file,
)
from ..core.types import Stage
from ..pdf import Bookmark, read_bookmarks, set_bookmarks

log = logging.getLogger(__name__)

# Contents page layout, in PDF points (1/72 inch).
MARGIN = 56
TITLE_HEIGHT = 48
ROW_HEIGHT = 24
PAGES_COLUMN = 110  # Width of the right-hand "Pages 3–7" column.
CONTENTS_CSS = "* {font-family: sans-serif; font-size: 12px; color: #111;}"


@dataclass
class Part:
    """One input in a merge: its title (shown in bookmarks and contents) and its PDF."""

    title: str
    path: Path


@dataclass
class PartRange:
    """Where a part ended up in the merged document (0-based, inclusive page indexes)."""

    title: str
    first: int
    last: int


def merge_documents(
    parts: Sequence[Part], target: Path, ctx: JobContext, contents_page: bool = False
) -> int:
    """Combine PDFs into one file, in the order given.

    Pages are copied as they are (text stays selectable; links and annotations
    are kept). Bookmarks: every part gets a top-level bookmark named after it,
    and the part's own bookmarks are nested underneath with page numbers
    shifted (decision C6). With ``contents_page`` (decision C7, off by default),
    a clickable contents page listing every part and its page range is added at
    the start. Page labels (decision C8) number the content pages 1…N in PDF
    viewers, and the contents pages i, ii, …, without printing anything on the
    pages.

    Args:
        parts: Inputs in output order. They are only read.
        target: Where to save the merged PDF.
        ctx: Job context (progress, cancel).
        contents_page: Add the clickable contents page at the start.

    Returns:
        Number of pages in the merged file.

    Raises:
        ConversionError: An input is unreadable, password-protected or empty, or
            the result failed verification.
        Cancelled: The user cancelled.
    """
    if not parts:
        raise ConversionError(merge_failed("No files to merge."))
    with pymupdf.open() as out:
        ranges: list[PartRange] = []
        toc: list[Bookmark] = []
        for index, part in enumerate(parts, 1):
            ctx.check_cancel()
            ctx.file_index = index
            ctx.report(Stage.MERGING, f"Combining {index} of {len(parts)}: {part.title}")
            try:
                doc = pymupdf.open(str(part.path))
            except Exception as exc:
                raise ConversionError(unreadable_file(part.title, str(exc))) from exc
            with doc:
                if doc.needs_pass:
                    raise ConversionError(password_protected(part.title))
                if len(doc) == 0:
                    raise ConversionError(empty_pdf(part.title))
                first = len(out)
                out.insert_pdf(doc, links=True, annots=True)
                ranges.append(PartRange(part.title, first, len(out) - 1))
                # Top-level bookmark for the part, then its own bookmarks one level deeper.
                toc.append([1, part.title, first + 1])
                toc += [
                    [level + 1, title, first + page] for level, title, page in read_bookmarks(doc)
                ]
        content_pages = len(out)

        lead = _add_contents_pages(out, ranges) if contents_page else 0
        if lead:
            toc = [[1, "Contents", 1]] + [[lvl, title, page + lead] for lvl, title, page in toc]
        set_bookmarks(out, toc)
        _set_page_labels(out, lead)

        ctx.report(Stage.FINISHING, "Saving the combined PDF", within_file=1.0)
        try:
            out.save(str(target), garbage=4, deflate=True)
        except Exception as exc:
            raise ConversionError(merge_failed(str(exc))) from exc

    expected = content_pages + lead
    with pymupdf.open(str(target)) as result:
        if len(result) != expected:
            details = f"Expected {expected} pages, found {len(result)}."
            raise ConversionError(merge_failed(details))
    log.debug("Merged %d parts into %d pages (%d contents pages)", len(parts), expected, lead)
    return expected


def _pages_label(first: int, last: int) -> str:
    """'Page 4' or 'Pages 4–9', counting content pages from 1."""
    return f"Page {first + 1}" if first == last else f"Pages {first + 1}–{last + 1}"


def _add_contents_pages(doc: pymupdf.Document, ranges: list[PartRange]) -> int:
    """Insert contents page(s) at the start of ``doc``, with a link per part.

    Pages are inserted first and drawn afterwards, so every link can target its
    part's final page index. Inserting pages at the front doesn't break the
    existing links inside the parts: PDF links point at page objects, not
    page numbers. Text is drawn with HTML boxes, which fall back to fonts that
    cover non-Latin scripts (file names can be in any language).

    Returns:
        Number of contents pages inserted.
    """
    width, height = doc[0].rect.width, doc[0].rect.height
    first_rows = max(1, int((height - 2 * MARGIN - TITLE_HEIGHT) // ROW_HEIGHT))
    other_rows = max(1, int((height - 2 * MARGIN) // ROW_HEIGHT))
    # Split the entries over as many pages as needed.
    pages: list[list[tuple[int, PartRange]]] = [[]]
    for number, part in enumerate(ranges, 1):
        limit = first_rows if len(pages) == 1 else other_rows
        if len(pages[-1]) == limit:
            pages.append([])
        pages[-1].append((number, part))
    lead = len(pages)
    for index in range(lead):
        doc.new_page(pno=index, width=width, height=height)

    for index, entries in enumerate(pages):
        page = doc[index]
        top = MARGIN
        if index == 0:
            title = pymupdf.Rect(MARGIN, MARGIN, width - MARGIN, MARGIN + TITLE_HEIGHT)
            page.insert_htmlbox(title, "<b style='font-size:20px'>Contents</b>", css=CONTENTS_CSS)
            top += TITLE_HEIGHT
        for row, (number, part) in enumerate(entries):
            y = top + row * ROW_HEIGHT
            name_box = pymupdf.Rect(MARGIN, y, width - MARGIN - PAGES_COLUMN, y + ROW_HEIGHT)
            pages_box = pymupdf.Rect(
                width - MARGIN - PAGES_COLUMN, y, width - MARGIN, y + ROW_HEIGHT
            )
            page.insert_htmlbox(name_box, f"{number}. {html.escape(part.title)}", css=CONTENTS_CSS)
            page.insert_htmlbox(
                pages_box,
                f"<div style='text-align:right'>{_pages_label(part.first, part.last)}</div>",
                css=CONTENTS_CSS,
            )
            # The whole row is clickable and jumps to the part's first page.
            row_rect = pymupdf.Rect(MARGIN, y, width - MARGIN, y + ROW_HEIGHT)
            page.insert_link(
                {
                    "kind": pymupdf.LINK_GOTO,
                    "from": row_rect,
                    "page": part.first + lead,
                    "to": pymupdf.Point(0, 0),
                }
            )
    return lead


def _set_page_labels(doc: pymupdf.Document, lead: int) -> None:
    """Viewer page numbers: contents pages i, ii, …; content pages 1…N (decision C8)."""
    labels = [{"startpage": lead, "prefix": "", "style": "D", "firstpagenum": 1}]
    if lead:
        labels.insert(0, {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1})
    try:
        doc.set_page_labels(labels)
    except Exception:
        log.warning("Couldn't set page labels; viewers will number pages from 1.", exc_info=True)
