"""Split: divide one PDF into several, by custom page ranges, every N pages, or per page.

Interface stub: implemented in a separate change. Signatures and behaviour
below are the contract; ``pipeline.run_action`` calls these.
"""

from __future__ import annotations

from pathlib import Path

from .common import OutputFile, SplitSettings
from .context import JobContext


def parse_page_ranges(text: str, page_count: int) -> list[tuple[int, int]]:
    """Parse user-typed ranges such as ``"1-3, 5, 8-10"`` into 1-based, inclusive pairs.

    Ranges are returned in the order typed. Spaces are ignored; a single page
    ``5`` gives ``(5, 5)``.

    Raises:
        ConversionError: With an ``invalid_page_ranges`` issue whose message
            says exactly what's wrong in plain words (empty input, not a number,
            start after end, page beyond ``page_count``, page 0).
    """
    raise NotImplementedError


def plan_split(settings: SplitSettings, page_count: int) -> list[tuple[int, int]]:
    """Turn Split settings into the list of 1-based, inclusive page ranges to write."""
    raise NotImplementedError


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
