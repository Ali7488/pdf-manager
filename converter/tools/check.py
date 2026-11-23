"""The tool check behind the Convert modal: which programs this job needs, and are they here."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import platforms
from ..core.issues import (
    Issue,
    ocr_missing,
    slide_renderer_missing,
    untrusted_needs_libreoffice,
)
from ..core.types import POWERPOINT_EXTENSIONS, Action, ActionData, ActionSettings
from .locate import find_libreoffice, find_powerpoint, find_tesseract, powerpoint_installed


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
    powerpoint: ToolStatus
    libreoffice: ToolStatus
    issues: list[Issue] = field(default_factory=list)


def check_tools(action: Action, settings: ActionSettings, data: ActionData) -> ToolCheck:
    """Check only the programs this job needs.

    * **OCR (Tesseract)** is required when ``settings.use_ocr`` is on (never
      for Compress).
    * **Slide rendering** is required when the files include PPT/PPTX:
      Microsoft PowerPoint is preferred and LibreOffice is the backup. If
      PowerPoint is present, a missing LibreOffice is reported as not present
      but doesn't block the job. If neither is present, the job can't start.
    * **Downloaded presentations** (Windows Mark-of-the-Web) are never opened
      with PowerPoint (decision C14), so they need LibreOffice even when
      PowerPoint is installed.

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

    slides = [Path(f) for f in data.files if Path(f).suffix.lower() in POWERPOINT_EXTENSIONS]
    needs_slides = bool(slides)
    untrusted = [f for f in slides if platforms.is_untrusted(f)]
    has_powerpoint = powerpoint_installed()
    libreoffice_path = find_libreoffice()
    powerpoint = ToolStatus(needs_slides, has_powerpoint, find_powerpoint())
    # LibreOffice is relevant whenever slides are involved, so the modal shows it
    # (as "not present" if missing). It only *blocks* the job when PowerPoint is
    # missing too; that decision is made by `ok` below, not by `required`.
    libreoffice = ToolStatus(needs_slides, libreoffice_path is not None, libreoffice_path)
    if libreoffice_path is None and untrusted:
        issues.append(untrusted_needs_libreoffice(untrusted[0].name))
    elif needs_slides and not has_powerpoint and libreoffice_path is None:
        issues.append(slide_renderer_missing())

    return ToolCheck(not issues, ocr, powerpoint, libreoffice, issues)
