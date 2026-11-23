"""Compress PDF: make a PDF smaller at one of three levels.

Interface stub: implemented in a separate change. Signatures and behaviour
below are the contract; ``pipeline.run_action`` calls this.
"""

from __future__ import annotations

from pathlib import Path

from .common import CompressLevel
from .context import JobContext


def compress_pdf(source: Path, target: Path, level: CompressLevel, ctx: JobContext) -> None:
    """Write a smaller copy of ``source`` to ``target``.

    * ``LIGHT``: lossless clean-up only (remove unused objects, compress streams).
    * ``BALANCED``: also re-encode large images at a moderate resolution and quality.
    * ``STRONG``: lower image resolution and quality for the smallest files.

    Text, links and bookmarks are kept. The result is never bigger than the
    input: if compression doesn't help, the input is copied unchanged.
    Reports progress (``Stage.COMPRESSING``) and checks for cancel.
    """
    raise NotImplementedError
