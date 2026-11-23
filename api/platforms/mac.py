"""macOS fallback for the API layer's platform interface (not a supported target).

macOS isn't on the roadmap (decision P14). This module only keeps the app
working from source on a Mac exactly as it did before the platform split:
folders open with ``open``, pywebview picks its Cocoa backend, settings use
the XDG layout, logs stay next to the app, and there is no in-app OCR install.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..service import Issue, ocr_install_failed
from ._common import FILE_FILTERS, XDG_APP_FOLDER, DefaultBrowser, xdg_dir

LOGS_FOLDER = "logs"


def platform_name() -> str:
    """The contract's ``AppInfo.platform``."""
    return "mac"


def prepare_gui() -> str | None:
    """Let pywebview pick its default macOS backend (Cocoa / WebKit)."""
    return None


def open_folder(folder: Path) -> None:
    """Open a folder in Finder with ``open``.

    Args:
        folder: An existing folder (checked by the caller).

    Raises:
        OSError: ``open`` couldn't be started.
    """
    subprocess.Popen(
        ["open", str(folder)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def file_filters() -> dict[str, tuple[str, ...]]:
    """Native file picker filters for ``pick_files``, by kind."""
    return FILE_FILTERS


def program_filters() -> tuple[str, ...]:
    """No filter when the user looks for Tesseract: programs have no extension."""
    return ()


def tesseract_file_name() -> str:
    """File name the user must pick in "Search for OCR"."""
    return "tesseract"


def settings_dir() -> Path:
    """Settings folder: ``$XDG_CONFIG_HOME/pdf-manager`` (default ``~/.config/pdf-manager``)."""
    return xdg_dir("XDG_CONFIG_HOME", (".config",)) / XDG_APP_FOLDER


def installed_logs_dir(app_dir: Path) -> Path:
    """Logs folder of a packaged app: next to it (there is no macOS package)."""
    return app_dir / LOGS_FOLDER


def ocr_install_unavailable() -> Issue:
    """There is no in-app OCR install on macOS."""
    return ocr_install_failed(
        "Automatic install isn't available on this system. "
        "Install Tesseract OCR yourself, then click Search for OCR in Settings."
    )


def run_ocr_install() -> str:
    """Never used: :func:`ocr_install_unavailable` always returns an issue.

    Raises:
        RuntimeError: Always.
    """
    raise RuntimeError("There is no in-app OCR install on macOS.")


# ----- Browser mode: a normal tab and the browser's own file selection -----


def default_browser() -> DefaultBrowser:
    """Not looked up on macOS: the URL goes to ``open`` (a normal tab)."""
    return DefaultBrowser("unknown (macOS)")


def start_browser(command: list[str]) -> None:
    """Start the browser for browser mode, detached from this app.

    Raises:
        OSError: It couldn't be started.
    """
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )


def open_url(url: str) -> None:
    """Open a URL with ``open``."""
    subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dialogs_available() -> bool:
    """No native pickers in browser mode on macOS; the page uses the browser's own."""
    return False


def ask_files(filters: tuple[str, ...], multiple: bool) -> list[Path]:
    """Never called: :func:`dialogs_available` is False."""
    return []


def ask_folder(start: str) -> Path | None:
    """Never called: :func:`dialogs_available` is False."""
    return None
