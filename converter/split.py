"""Split: divide one PDF into several, by custom page ranges, every N pages, or per page.

``pipeline.run_action`` calls these. :func:`parse_page_ranges` turns the text
the user typed into page ranges, :func:`plan_split` turns the Split settings
into the list of ranges to write, and :func:`split_pdf` writes one PDF per range.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .common import OutputFile, SplitMethod, SplitSettings
from .context import JobContext
from .issues import ConversionError, invalid_page_ranges

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


def split_pdf(
    source: Path, out_dir: Path, base_name: str, settings: SplitSettings, ctx: JobContext
) -> list[OutputFile]:
    """Write one PDF per planned range into ``out_dir``.

    Output names: ``"<base_name> - pages <a>-<b>.pdf"``, or
    ``"<base_name> - page <a>.pdf"`` for a single page. Links and annotations
    are kept, and bookmarks that fall inside a range are kept with page numbers
    shifted. Reports progress (``Stage.SPLITTING``) and checks for cancel
    between parts.
    """
    raise NotImplementedError
