"""Images to PDF: turn PNG/JPG images into PDF pages.

Interface stub: implemented in a separate change. Signatures and behaviour
below are the contract; ``pipeline.run_action`` calls this.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .common import OutputFile
from .context import JobContext


def images_to_pdf(
    images: Sequence[Path], out_dir: Path, combine: bool, ctx: JobContext
) -> list[OutputFile]:
    """Convert images to PDF, either into one combined PDF or one PDF per image.

    Images keep their order and their camera orientation (EXIF rotation).
    Combined output is named ``"<first name> - Images.pdf"`` (one image) or
    ``"<first name> + N more - Images.pdf"``; per-image output is
    ``"<image name>.pdf"``. OCR is not done here (the pipeline adds it when
    requested). Reports progress and checks for cancel between images.

    Raises:
        ConversionError: An image can't be read (``unreadable_file``).
    """
    raise NotImplementedError
