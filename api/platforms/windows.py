"""Windows implementation of the API layer's platform interface.

Behaviour is unchanged from before the platform split: Explorer through
``os.startfile``, settings under ``%LOCALAPPDATA%\\PDFManager``, logs next to
the installed app (decision C4) and the in-app OCR install through winget.
Nothing here imports Windows-only modules, so it can be imported (and tested)
on any system.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from .. import service
from ..service import Issue, ocr_install_failed
from ._common import FILE_FILTERS

log = logging.getLogger(__name__)

APP_FOLDER = "PDFManager"  # Under %LOCALAPPDATA%.
LOGS_FOLDER = "logs"

# Tesseract from the UB Mannheim build, the usual Windows distribution.
WINGET_INSTALL = (
    "winget",
    "install",
    "--id",
    "UB-Mannheim.TesseractOCR",
    "-e",
    "--silent",
    "--accept-source-agreements",
    "--accept-package-agreements",
)
WINGET_TIMEOUT_SEC = 20 * 60


def platform_name() -> str:
    """The contract's ``AppInfo.platform``."""
    return "windows"


def prepare_gui() -> str | None:
    """Let pywebview pick its default Windows backend (Edge WebView2).

    Returns:
        ``None``: no GUI is forced, exactly as before the platform split.
    """
    return None


def open_folder(folder: Path) -> None:
    """Open a folder in File Explorer.

    Args:
        folder: An existing folder. The caller checks it is a folder, because
            ``os.startfile`` on a file would open (or run) it.

    Raises:
        OSError: Explorer couldn't be started.
    """
    os.startfile(str(folder))


def file_filters() -> dict[str, tuple[str, ...]]:
    """Native file picker filters for ``pick_files``, by kind."""
    return FILE_FILTERS


def program_filters() -> tuple[str, ...]:
    """Picker filter used when the user looks for ``tesseract.exe`` themselves."""
    return ("Programs (*.exe)",)


def tesseract_file_name() -> str:
    """File name the user must pick in "Search for OCR"."""
    return "tesseract.exe"


def settings_dir() -> Path:
    """Per-user settings folder: ``%LOCALAPPDATA%\\PDFManager``.

    It survives reinstalls and needs no admin rights.

    Returns:
        The folder (not created here).
    """
    base = os.environ.get("LOCALAPPDATA")
    # LOCALAPPDATA is always set in a normal Windows session; this is a fallback.
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / APP_FOLDER


def installed_logs_dir(app_dir: Path) -> Path:
    """Logs folder of the installed app: next to it (decision C4).

    The app installs per user (decision F17), so that folder is writable.

    Args:
        app_dir: The folder the executable is in.

    Returns:
        ``<app_dir>/logs`` (not created here).
    """
    return app_dir / LOGS_FOLDER


def ocr_install_unavailable() -> Issue | None:
    """Why the app can't install OCR itself, or ``None`` when it can.

    Returns:
        ``None`` when winget (App Installer) is available, otherwise an
        ``OCR_INSTALL_FAILED`` issue explaining the manual install.
    """
    if shutil.which("winget") is not None:
        return None
    return ocr_install_failed(
        "Automatic install needs winget (App Installer). "
        "Install Tesseract OCR yourself, then click Search for OCR in Settings."
    )


def run_ocr_install() -> str:
    """Install Tesseract with winget and wait for it to finish.

    Runs on a background thread. Success is judged afterwards by looking for
    Tesseract, not by the exit code (winget also exits non-zero when it's
    already installed).

    Returns:
        Technical details of the run (exit code and output, or why it
        couldn't run), for the issue's "Show details" section.
    """
    log.info("Installing OCR: %s", " ".join(WINGET_INSTALL))
    try:
        proc = service.run_command(WINGET_INSTALL, timeout=WINGET_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return f"winget didn't finish within {WINGET_TIMEOUT_SEC // 60} minutes."
    except OSError as exc:
        return f"Couldn't run winget: {exc}"
    return (
        f"winget exit code {proc.returncode}\n"
        f"{(proc.stdout or '').strip()}\n{(proc.stderr or '').strip()}"
    ).strip()
