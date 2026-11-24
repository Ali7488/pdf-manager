"""Finding the external programs: Tesseract OCR and LibreOffice.

Platform-independent: ``PATH`` is searched here, and each platform adds its
own usual install locations through ``converter.platforms``.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .. import platforms
from .process import run_command


def _first_existing(candidates: Sequence[Path]) -> Path | None:
    """Return the first candidate that is a file, checking each distinct path once.

    Paths are compared case-insensitively for de-duplication (harmless on
    case-sensitive systems: it only skips re-checking).
    """
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


def find_tesseract(configured: str | Path | None = None) -> Path | None:
    """Find the Tesseract OCR executable, or return ``None`` if it isn't installed.

    Candidates are checked in this order, and the first one that exists wins:

    1. ``configured``: a path the user picked earlier with "Search for OCR".
    2. ``tesseract`` on the system ``PATH``.
    3. Platform-specific places (on Windows: install folders and the paths the
       Tesseract installer recorded in the registry).

    Args:
        configured: Optional user-chosen path to the Tesseract executable.
    """
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    located = shutil.which("tesseract")
    if located:
        candidates.append(Path(located))
    candidates += platforms.tesseract_candidates()
    return _first_existing(candidates)


def find_libreoffice() -> Path | None:
    """Find the LibreOffice executable (``soffice``), or return ``None``.

    Checks ``PATH`` first (``soffice`` or ``libreoffice``), then the platform's
    usual install folders.
    """
    for name in ("soffice", "libreoffice"):
        value = shutil.which(name)
        if value:
            return Path(value)
    return _first_existing(platforms.libreoffice_candidates())


def tesseract_languages(tesseract: Path) -> list[str]:
    """List the OCR languages installed for Tesseract, e.g. ``["deu", "eng"]``.

    The ``osd`` entry (orientation detection, not a language) is left out.
    Returns an empty list if Tesseract can't be run.
    """
    try:
        proc = run_command([tesseract, "--list-langs"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    # Output: a header line ("List of available languages ..."), then one code per line.
    lines = (proc.stdout or proc.stderr or "").splitlines()[1:]
    return sorted({line.strip() for line in lines if line.strip() and line.strip() != "osd"})
