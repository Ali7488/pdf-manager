"""The tool check behind the Convert modal: which programs this job needs, and are they here."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.issues import Issue, ocr_missing, slide_renderer_missing
from ..core.types import POWERPOINT_EXTENSIONS, Action, ActionData, ActionSettings
from .locate import find_libreoffice, find_tesseract


@dataclass
class ToolStatus:
    """One row of the tool check."""

    required: bool  # Does this job need the tool?
    present: bool
    path: Path | None = None


@dataclass
class ToolCheck:
    """Result of :func:`check_tools`. ``ok`` is True if the job can start."""

    ok: bool
    ocr: ToolStatus
    libreoffice: ToolStatus
    issues: list[Issue] = field(default_factory=list)


def check_tools(action: Action, settings: ActionSettings, data: ActionData) -> ToolCheck:
    """Check only the programs this job needs.

    * **OCR (Tesseract)** is required when ``settings.use_ocr`` is on (never
      for Compress).
    * **LibreOffice Impress** is required when the files include PPT/PPTX
      (decision C17: it converts every presentation, wherever it came from).
      PDF and image jobs never need it.

    Args:
        action: The action about to run.
        settings: Its settings (``use_ocr`` and ``tesseract_path`` matter here).
        data: Its input files.

    Returns:
        A :class:`ToolCheck`; when ``ok`` is False, ``issues`` says why.
    """
    issues: list[Issue] = []

    needs_ocr = settings.use_ocr and action is not Action.COMPRESS
    tesseract = find_tesseract(settings.tesseract_path)
    ocr = ToolStatus(needs_ocr, tesseract is not None, tesseract)
    if needs_ocr and tesseract is None:
        issues.append(ocr_missing())

    needs_slides = any(Path(f).suffix.lower() in POWERPOINT_EXTENSIONS for f in data.files)
    libreoffice_path = find_libreoffice() if needs_slides else None
    libreoffice = ToolStatus(needs_slides, libreoffice_path is not None, libreoffice_path)
    if needs_slides and libreoffice_path is None:
        issues.append(slide_renderer_missing())

    return ToolCheck(not issues, ocr, libreoffice, issues)
