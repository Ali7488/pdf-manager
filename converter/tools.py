"""Locating and running the external programs: Tesseract OCR and LibreOffice."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path


def run_command(cmd: Sequence[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    options = {"capture_output": True, "text": True, "timeout": timeout}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(list(map(str, cmd)), **options)


def find_tesseract(configured: str | Path | None = None) -> Path | None:
    """Find Tesseract in PATH, known Windows folders and installer registry entries.

    Installed WinGet packages can be per-user and may not be in PATH in an
    already-running session, so path detection alone was unreliable in v1.0.
    """
    possible: list[Path] = []
    if configured:
        possible.append(Path(configured).expanduser())
    located = shutil.which("tesseract")
    if located:
        possible.append(Path(located))
    if os.name == "nt":
        roots = [
            os.getenv("ProgramFiles"),
            os.getenv("ProgramFiles(x86)"),
            os.getenv("LOCALAPPDATA"),
        ]
        for root in filter(None, roots):
            base = Path(root)
            possible.extend(
                (
                    base / "Tesseract-OCR" / "tesseract.exe",
                    base / "Programs" / "Tesseract-OCR" / "tesseract.exe",
                )
            )
        try:
            import winreg

            hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
            keys = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tesseract.exe",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Tesseract-OCR_is1",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Tesseract-OCR_is1",
                r"SOFTWARE\Tesseract-OCR",
            )
            for hive in hives:
                for keyname in keys:
                    try:
                        with winreg.OpenKey(hive, keyname) as key:
                            for value_name in ("InstallLocation", "Path", "DisplayIcon", ""):
                                try:
                                    value, _ = winreg.QueryValueEx(key, value_name)
                                except OSError:
                                    continue
                                if not isinstance(value, str) or not value.strip():
                                    continue
                                cleaned = os.path.expandvars(
                                    value.strip().strip('"').split('",')[0]
                                )
                                path = Path(cleaned)
                                possible.append(
                                    path
                                    if path.suffix.lower() == ".exe"
                                    else path / "tesseract.exe"
                                )
                    except OSError:
                        continue
        except ImportError:
            pass
    seen = set()
    for path in possible:
        normalized = str(path).casefold()
        if normalized not in seen and path.is_file():
            return path
        seen.add(normalized)
    return None


def require_tesseract(configured: str | Path | None = None) -> Path:
    engine = find_tesseract(configured)
    if engine is None:
        raise RuntimeError(
            "OCR engine missing. Click 'Install OCR' or 'Find OCR' in the dashboard, then retry."
        )
    return engine


def find_libreoffice() -> Path | None:
    for name in ("soffice", "libreoffice"):
        value = shutil.which(name)
        if value:
            return Path(value)
    if os.name == "nt":
        for root in (
            os.getenv("ProgramFiles"),
            os.getenv("ProgramFiles(x86)"),
            os.getenv("LOCALAPPDATA"),
        ):
            if root:
                for sub in (
                    "LibreOffice/program/soffice.exe",
                    "Programs/LibreOffice/program/soffice.exe",
                ):
                    value = Path(root) / sub
                    if value.is_file():
                        return value
    return None
