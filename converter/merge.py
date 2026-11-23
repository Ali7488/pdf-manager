"""Merging several PDFs into one, keeping links and annotations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import fitz

from .common import Progress


def merge_pdfs(sources: Sequence[Path], target: Path, report: Progress) -> None:
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
                output.insert_pdf(part, links=True, annots=True)
        output.save(str(target), garbage=4, deflate=True)
    with fitz.open(str(target)) as result:
        if len(result) != expected:
            raise RuntimeError("Merge verification failed: page counts do not match.")
