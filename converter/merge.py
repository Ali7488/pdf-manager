"""Merging several PDFs into one, keeping links and annotations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import fitz

from .common import Progress


def merge_pdfs(sources: Sequence[Path], target: Path, report: Progress) -> None:
    """Combine PDFs into a single file, in the order given.

    Pages are copied as they are: text stays selectable, and links and
    annotations (highlights, comments) are kept. After saving, the result is
    re-opened to confirm its page count equals the sum of the inputs.

    Bookmarks (the table of contents) are not carried over.

    Args:
        sources: PDFs to merge, in output order. They are only read.
        target: Where to save the merged PDF.
        report: Progress callback; called once per input file.

    Raises:
        ValueError: No inputs, or an input is password-protected or empty.
        RuntimeError: The saved file's page count doesn't match the inputs.
    """
    if not sources:
        raise ValueError("No PDF inputs available to merge.")
    with fitz.open() as output:
        expected = 0
        for i, source in enumerate(sources, 1):
            report(f"Merging {i} / {len(sources)}: {source.name}")
            with fitz.open(str(source)) as part:
                if part.needs_pass:
                    raise ValueError(f"Password-protected PDF: {source.name}")
                if len(part) == 0:
                    raise ValueError(f"Empty PDF: {source.name}")
                expected += len(part)
                # Append all pages of this input to the end of the output.
                output.insert_pdf(part, links=True, annots=True)
        # garbage=4 removes unused and duplicate objects; deflate compresses streams.
        output.save(str(target), garbage=4, deflate=True)
    # Verify the file on disk, not just the in-memory document.
    with fitz.open(str(target)) as result:
        if len(result) != expected:
            raise RuntimeError("Merge verification failed: page counts do not match.")
