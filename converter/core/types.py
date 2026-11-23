"""Shared constants and types used across the converter (service layer).

These types are the service layer's interface. The API layer (``api/``)
converts the frontend's camelCase JSON into them and back; nothing in
``converter/`` knows about the UI or the bridge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# Resolution used when rendering each page to an image for flattening and OCR.
# Higher values give sharper pages and better OCR, but larger files and slower runs.
DPI = 200

# Default seconds Tesseract may spend on one page before the page is abandoned.
OCR_PAGE_TIMEOUT_SEC = 120

# Default Tesseract language code ("eng" = English; "eng+deu" combines languages).
OCR_LANGUAGE = "eng"

# Input file extensions, compared lower-case.
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".pptx", ".ppt"})
POWERPOINT_EXTENSIONS = frozenset({".pptx", ".ppt"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})


class Action(StrEnum):
    """What a job does. Every conversion goes through ``run_action(action, settings, data)``."""

    FLATTEN = "flatten"
    FLATTEN_MERGE = "flatten_merge"
    MERGE = "merge"
    SPLIT = "split"
    IMAGES_TO_PDF = "images_to_pdf"
    COMPRESS = "compress"


# The file types each action accepts. The API layer and frontend use the same table.
ACCEPTS: dict[Action, frozenset[str]] = {
    Action.FLATTEN: DOCUMENT_EXTENSIONS,
    Action.FLATTEN_MERGE: DOCUMENT_EXTENSIONS,
    Action.MERGE: DOCUMENT_EXTENSIONS,
    Action.SPLIT: DOCUMENT_EXTENSIONS,
    Action.IMAGES_TO_PDF: IMAGE_EXTENSIONS,
    Action.COMPRESS: frozenset({".pdf"}),
}


class SplitMethod(StrEnum):
    """How Split divides a document."""

    RANGES = "ranges"  # Custom page ranges such as "1-3, 5, 8-10"; each range is one file.
    EVERY_N = "every_n"  # Consecutive chunks of N pages.
    PER_PAGE = "per_page"  # One file per page.


class CompressLevel(StrEnum):
    """How hard Compress works. Stronger levels shrink images more and lose more quality."""

    LIGHT = "light"
    BALANCED = "balanced"
    STRONG = "strong"


@dataclass
class SplitSettings:
    """Settings used only by :attr:`Action.SPLIT`."""

    method: SplitMethod = SplitMethod.RANGES
    ranges: str = ""
    every_n: int = 1


@dataclass
class ActionSettings:
    """Everything that controls one job. Each action reads only the fields relevant to it.

    The first group comes from the frontend's per-job options; the second group
    from the user's saved Settings, filled in by the API layer.
    """

    # Per-job options (frontend ``ActionSettings``).
    use_ocr: bool = False
    contents_page: bool = False
    split: SplitSettings = field(default_factory=SplitSettings)
    combine_images: bool = True
    compress_level: CompressLevel = CompressLevel.BALANCED

    # From saved settings.
    dpi: int = DPI
    ocr_language: str = OCR_LANGUAGE
    ocr_page_timeout_sec: int = OCR_PAGE_TIMEOUT_SEC
    tesseract_path: str | None = None


@dataclass
class ActionData:
    """What a job works on: the input files, in the order the user arranged them."""

    files: list[Path]


class Stage(StrEnum):
    """Coarse job phase, shown in progress messages."""

    PREPARING = "preparing"
    RENDERING_SLIDES = "rendering_slides"
    FLATTENING = "flattening"
    OCR = "ocr"
    MERGING = "merging"
    SPLITTING = "splitting"
    COMPRESSING = "compressing"
    CONVERTING_IMAGES = "converting_images"
    FINISHING = "finishing"


@dataclass
class ProgressEvent:
    """One progress update. ``fraction`` is the overall job progress from 0 to 1."""

    stage: Stage
    file_index: int
    file_count: int
    page: int | None
    page_count: int | None
    fraction: float
    message: str


# Progress callback: receives a ProgressEvent. Must be fast and must not raise.
Progress = Callable[[ProgressEvent], None]


@dataclass
class OutputFile:
    """One finished result, still in the job's scratch folder."""

    name: str  # Suggested file name, e.g. "Report - Merged.pdf".
    path: Path  # Where it is in scratch.
    page_count: int
    size_bytes: int


@dataclass
class JobResult:
    """What a successful job produced, plus any non-fatal warnings."""

    outputs: list[OutputFile]
    warnings: list = field(default_factory=list)  # list[converter.issues.Issue]
