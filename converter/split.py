"""Split: divide one PDF into several, by custom page ranges, every N pages, or per page.

``pipeline.run_action`` calls these. :func:`parse_page_ranges` turns the text
the user typed into page ranges, :func:`plan_split` turns the Split settings
into the list of ranges to write, and :func:`split_pdf` writes one PDF per range.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import time
from pathlib import Path

import fitz

from .common import OutputFile, SplitMethod, SplitSettings, Stage
from .context import JobContext
from .issues import (
    ConversionError,
    empty_pdf,
    invalid_page_ranges,
    password_protected,
    unreadable_file,
)

log = logging.getLogger(__name__)

# Characters accepted as the dash in a range: hyphen, en dash, em dash and the
# minus sign. Word processors and phones often swap a typed hyphen for one of these.
_DASHES = "-–—−"
_DASH_RE = re.compile(f"[{_DASHES}]")

# Plain ASCII digits only: ``str.isdigit`` would also accept characters such as
# superscripts that ``int`` can't convert.
_NUMBER_RE = re.compile(r"[0-9]+")

# Shown when the input has no ranges at all.
_EXAMPLE = "1-3, 5, 8-10"


def _pages_word(count: int) -> str:
    """Return "1 page" or "N pages".

    Args:
        count: Number of pages.

    Returns:
        The count followed by the correctly pluralised word.
    """
    return f"{count} page" if count == 1 else f"{count} pages"


def _fail(reason: str) -> ConversionError:
    """Build the error raised for a range problem.

    Args:
        reason: Plain-language explanation shown to the user.

    Returns:
        A :class:`ConversionError` carrying an ``invalid_page_ranges`` issue.
    """
    return ConversionError(invalid_page_ranges(None, reason))


def _parse_page(text: str, item: str, page_count: int) -> int:
    """Convert one page number from a range item and check it exists.

    Args:
        text: The number as typed, already stripped of surrounding spaces.
        item: The whole comma-separated item, quoted in error messages.
        page_count: Pages in the document.

    Returns:
        The 1-based page number.

    Raises:
        ConversionError: Not a whole number, page 0, or beyond the last page.
    """
    if not _NUMBER_RE.fullmatch(text):
        if item == text:
            raise _fail(f"'{item}' isn't a page number. Use whole numbers such as 4 or 4-7.")
        raise _fail(f"'{text}' in '{item}' isn't a page number. Use whole numbers such as 4-7.")
    page = int(text)
    if page == 0:
        raise _fail("There's no page 0; pages start at 1.")
    if page > page_count:
        raise _fail(f"Page {page} doesn't exist; this document has {_pages_word(page_count)}.")
    return page


def parse_page_ranges(text: str, page_count: int) -> list[tuple[int, int]]:
    """Parse user-typed ranges such as ``"1-3, 5, 8-10"`` into 1-based, inclusive pairs.

    Ranges are returned in the order typed. Spaces are ignored; a single page
    ``5`` gives ``(5, 5)``. Hyphens, en dashes (``–``), em dashes and minus
    signs all work as the dash. Empty items between commas (for example a
    trailing comma) are skipped. Overlapping or repeated ranges are allowed and
    kept as typed.

    Args:
        text: What the user typed.
        page_count: Pages in the document the ranges refer to.

    Returns:
        ``(first, last)`` pairs, 1-based and inclusive, in typed order.

    Raises:
        ConversionError: With an ``invalid_page_ranges`` issue whose message
            says exactly what's wrong in plain words (empty input, not a number,
            start after end, page beyond ``page_count``, page 0).
    """
    ranges: list[tuple[int, int]] = []
    for raw in text.split(","):
        item = raw.strip()
        if not item:
            continue  # Tolerate "1-3,,5" and a trailing comma.
        parts = _DASH_RE.split(item)
        if len(parts) == 1:
            page = _parse_page(item, item, page_count)
            ranges.append((page, page))
            continue
        if len(parts) > 2:
            raise _fail(f"'{item}' has more than one dash. A range looks like 4-7.")
        start_text, end_text = parts[0].strip(), parts[1].strip()
        if not start_text and not end_text:
            raise _fail(f"'{item}' needs page numbers on both sides of the dash, like 4-7.")
        if not start_text:
            raise _fail(f"'{item}' is missing the first page. A range looks like 4-7.")
        if not end_text:
            raise _fail(f"'{item}' is missing the last page. A range looks like 4-7.")
        start = _parse_page(start_text, item, page_count)
        end = _parse_page(end_text, item, page_count)
        if start > end:
            raise _fail(f"'{item}' starts after it ends. Did you mean {end}-{start}?")
        ranges.append((start, end))
    if not ranges:
        raise _fail(f"Type the pages to keep, for example: {_EXAMPLE}.")
    return ranges


def plan_split(settings: SplitSettings, page_count: int) -> list[tuple[int, int]]:
    """Turn Split settings into the list of 1-based, inclusive page ranges to write.

    * ``RANGES``: the ranges the user typed (see :func:`parse_page_ranges`).
    * ``EVERY_N``: consecutive chunks of ``every_n`` pages; the last chunk
      holds whatever is left and may be shorter.
    * ``PER_PAGE``: one range per page.

    Args:
        settings: The job's Split settings.
        page_count: Pages in the document being split.

    Returns:
        ``(first, last)`` pairs, 1-based and inclusive, in output order.

    Raises:
        ConversionError: Invalid typed ranges, or ``every_n`` below 1
            (``invalid_page_ranges``).
        ValueError: Unknown split method.
    """
    method = SplitMethod(settings.method)
    if method is SplitMethod.RANGES:
        return parse_page_ranges(settings.ranges, page_count)
    if method is SplitMethod.EVERY_N:
        n = settings.every_n
        # bool is a subclass of int; reject it so True isn't taken as 1.
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise _fail("Choose how many pages go in each file: a whole number of 1 or more.")
        return [(start, min(start + n - 1, page_count)) for start in range(1, page_count + 1, n)]
    if method is SplitMethod.PER_PAGE:
        return [(page, page) for page in range(1, page_count + 1)]
    raise ValueError(f"Unknown split method: {method}")  # Unreachable unless the enum grows.


def _part_name(base_name: str, start: int, end: int) -> str:
    """Return the suggested file name for one split part.

    Args:
        base_name: Name of the source document, without extension.
        start: First page of the part (1-based).
        end: Last page of the part (1-based, inclusive).

    Returns:
        ``"<base_name> - pages <a>-<b>.pdf"``, or ``"<base_name> - page <a>.pdf"``
        for a single page.
    """
    if start == end:
        return f"{base_name} - page {start}.pdf"
    return f"{base_name} - pages {start}-{end}.pdf"


def _fix_toc_levels(toc: list[list]) -> list[list]:
    """Renumber bookmark levels so the outline is valid after some entries were dropped.

    PyMuPDF's ``set_toc`` requires the first entry to be level 1 and each entry
    to be at most one level deeper than the one before it. Dropping bookmarks
    outside a range can break that (for example when a chapter heading is
    dropped but its sub-headings are kept). Each entry's new level is the
    number of kept ancestors plus one, so siblings stay siblings and children
    stay children.

    Args:
        toc: Bookmark entries ``[level, title, page, ...]`` in document order.
            Modified in place.

    Returns:
        The same list, with valid levels.
    """
    ancestors: list[int] = []  # Original levels of the kept entries enclosing this one.
    for entry in toc:
        level = entry[0]
        # Leave the branch of every kept entry that isn't an ancestor of this one.
        while ancestors and ancestors[-1] >= level:
            ancestors.pop()
        entry[0] = len(ancestors) + 1
        ancestors.append(level)
    return toc


def _toc_for_range(toc: list[list], start: int, end: int) -> list[list]:
    """Pick the bookmarks that point inside a range and shift them to the part's numbering.

    Args:
        toc: The source document's detailed outline (``get_toc(simple=False)``).
        start: First page of the range (1-based).
        end: Last page of the range (1-based, inclusive).

    Returns:
        A valid outline for the part: entries outside the range (and ones with
        no page target, such as web links) are dropped, page numbers are
        shifted so ``start`` becomes page 1, and levels are repaired.
    """
    kept: list[list] = []
    for level, title, page, *rest in toc:
        if not start <= page <= end:
            continue  # Outside this part, or not a page target (page is -1 then).
        new_page = page - start + 1
        entry = [level, title, new_page]
        if rest and isinstance(rest[0], dict):
            dest = dict(rest[0])
            if dest.get("kind") == fitz.LINK_GOTO:
                # Keep the position on the page (and style); point it at the new page.
                dest["page"] = new_page - 1  # Detailed destinations use 0-based pages.
                entry.append(dest)
        kept.append(entry)
    return _fix_toc_levels(kept)


def _open_source(source: Path) -> fitz.Document:
    """Open the PDF to split, turning low-level failures into user-facing errors.

    Args:
        source: PDF to open; only read.

    Returns:
        The open document. The caller closes it.

    Raises:
        ConversionError: The file can't be read, needs a password, or has no pages.
    """
    try:
        doc = fitz.open(str(source))
    except Exception as exc:  # MuPDF raises several types for damaged or missing files.
        raise ConversionError(unreadable_file(source.name, str(exc))) from exc
    if doc.needs_pass:
        doc.close()
        raise ConversionError(password_protected(source.name))
    if doc.page_count < 1:
        doc.close()
        raise ConversionError(empty_pdf(source.name))
    return doc


def split_pdf(
    source: Path, out_dir: Path, base_name: str, settings: SplitSettings, ctx: JobContext
) -> list[OutputFile]:
    """Write one PDF per planned range into ``out_dir``.

    Output names: ``"<base_name> - pages <a>-<b>.pdf"``, or
    ``"<base_name> - page <a>.pdf"`` for a single page. Links and annotations
    are kept, and bookmarks that fall inside a range are kept with page numbers
    shifted. Reports progress (``Stage.SPLITTING``) and checks for cancel
    between parts.

    Files are written in ``out_dir`` as ``part_001.pdf``, ``part_002.pdf`` and
    so on, so repeated ranges never overwrite each other; the suggested name is
    in :attr:`OutputFile.name`.

    Args:
        source: PDF to split; only read.
        out_dir: Scratch folder for the parts; created if needed.
        base_name: Name used to build the suggested output names.
        settings: How to split.
        ctx: Job context for progress, cancel and warnings.

    Returns:
        One :class:`OutputFile` per range, in output order.

    Raises:
        ConversionError: Invalid ranges (with the file name filled in), or the
            source can't be read, needs a password, or has no pages.
        Cancelled: The user pressed Cancel.
    """
    started = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    with _open_source(source) as doc:
        page_count = doc.page_count
        try:
            ranges = plan_split(settings, page_count)
        except ConversionError as exc:
            # The parser doesn't know the file; add it so the message names it.
            raise ConversionError(dataclasses.replace(exc.issue, file=source.name)) from exc
        log.debug(
            "Splitting %s (%d pages, method=%s) into %d part(s): %s",
            source.name,
            page_count,
            settings.method,
            len(ranges),
            ranges,
        )
        toc = doc.get_toc(simple=False)
        # Keep the document's descriptive metadata (title, author...) on every part.
        metadata = {
            k: v for k, v in (doc.metadata or {}).items() if k not in ("format", "encryption")
        }
        outputs: list[OutputFile] = []
        for index, (start, end) in enumerate(ranges, 1):
            ctx.check_cancel()
            ctx.report(
                Stage.SPLITTING,
                f"Splitting: part {index} of {len(ranges)}",
                within_file=(index - 1) / len(ranges),
            )
            target = out_dir / f"part_{index:03d}.pdf"
            with fitz.open() as part:
                # insert_pdf takes 0-based, inclusive page numbers. Links between
                # pages inside the range are re-pointed; ones to other pages are dropped.
                part.insert_pdf(doc, from_page=start - 1, to_page=end - 1, links=True, annots=True)
                part.set_metadata(metadata)
                part_toc = _toc_for_range(toc, start, end)
                if part_toc:
                    part.set_toc(part_toc)
                # garbage=4 removes unused and duplicate objects; deflate compresses streams.
                part.save(str(target), garbage=4, deflate=True)
            size = target.stat().st_size
            log.debug(
                "Wrote part %d: pages %d-%d, %d bookmark(s), %d bytes",
                index,
                start,
                end,
                len(part_toc),
                size,
            )
            outputs.append(
                OutputFile(_part_name(base_name, start, end), target, end - start + 1, size)
            )
    done = "1 file" if len(outputs) == 1 else f"{len(outputs)} files"
    ctx.report(Stage.SPLITTING, f"Split into {done}", within_file=1.0)
    log.debug("Split %s in %.2f s", source.name, time.perf_counter() - started)
    return outputs
