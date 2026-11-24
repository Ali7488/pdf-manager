"""The API layer's platform-specific behaviour behind one minimal interface (P15, P17).

Shared API code never checks the operating system itself; it calls these
functions, which come from ``windows.py`` on Windows, ``mac.py`` on macOS and
``linux.py`` everywhere else (Linux, and other POSIX desktops with
``xdg-open``). The module is chosen once, at import time, in the same style as
``converter/platforms/``. See ``docs/PORTABILITY.md``.

Shared code calls them through this package (``platforms.open_folder(...)``),
so tests can replace one function in one place.

Interface:
    platform_name() -> str
        The contract's ``AppInfo.platform``: ``"windows"``, ``"linux"`` or ``"mac"``.
    prepare_gui() -> str | None
        Prepare the environment for the window toolkit and return the
        pywebview GUI to request (``"qt"`` on Linux, PySide6 only), or ``None``
        for pywebview's default (Edge WebView2 on Windows).
    open_folder(folder) -> None
        Open an existing folder in the file manager (Explorer, ``xdg-open``).
        Raises ``OSError`` if that fails.
    file_filters() -> dict[str, tuple[str, ...]]
        Native picker filters for ``pick_files`` by kind (``all``,
        ``documents``, ``images``).
    program_filters() -> tuple[str, ...]
        Picker filters used when the user looks for Tesseract themselves.
    tesseract_file_name() -> str
        The Tesseract program's file name (``tesseract.exe`` / ``tesseract``).
    settings_dir() -> Path
        Per-user settings folder (``%LOCALAPPDATA%\\PDFManager``,
        ``$XDG_CONFIG_HOME/pdf-manager``).
    installed_logs_dir(app_dir) -> Path
        Logs folder of the installed (frozen) app: next to it on Windows (C4),
        ``$XDG_STATE_HOME/pdf-manager/logs`` on Linux (C15). From source the
        logs always stay in the repository's ``logs/`` (``api.paths``).
    ocr_install_unavailable() -> Issue | None
        ``None`` if the app can install OCR itself (Windows with winget);
        otherwise the issue to show straight away. On Linux it always returns
        an issue carrying the distribution's install command (C16).
    run_ocr_install() -> str
        Run the OCR install and wait; returns technical details for the log.
        Only called when ``ocr_install_unavailable()`` returned ``None``.

Browser mode only (``api.web``):
    default_browser() -> DefaultBrowser
        The user's default browser, with its app-mode command when it is
        Edge, Chrome, Brave or Chromium.
    open_url(url) -> None
        Open a URL with the system's handler (a normal tab).
    start_browser(command) -> None
        Start a browser command (app mode), detached from the app.
    dialogs_available() -> bool
        Whether native file and folder pickers can be shown.
    ask_files(filters, multiple) -> list[Path]
        Native Open dialog; empty if cancelled.
    ask_folder(start) -> Path | None
        Native folder picker; ``None`` if cancelled.
"""

from __future__ import annotations

import os
import sys

from ._common import DefaultBrowser

if os.name == "nt":
    from .windows import (
        ask_files,
        ask_folder,
        default_browser,
        dialogs_available,
        file_filters,
        installed_logs_dir,
        lock_instance,
        ocr_install_unavailable,
        open_folder,
        open_url,
        platform_name,
        prepare_gui,
        program_filters,
        run_ocr_install,
        settings_dir,
        start_browser,
        tesseract_file_name,
    )
elif sys.platform == "darwin":
    from .mac import (
        ask_files,
        ask_folder,
        default_browser,
        dialogs_available,
        file_filters,
        installed_logs_dir,
        lock_instance,
        ocr_install_unavailable,
        open_folder,
        open_url,
        platform_name,
        prepare_gui,
        program_filters,
        run_ocr_install,
        settings_dir,
        start_browser,
        tesseract_file_name,
    )
else:
    from .linux import (
        ask_files,
        ask_folder,
        default_browser,
        dialogs_available,
        file_filters,
        installed_logs_dir,
        lock_instance,
        ocr_install_unavailable,
        open_folder,
        open_url,
        platform_name,
        prepare_gui,
        program_filters,
        run_ocr_install,
        settings_dir,
        start_browser,
        tesseract_file_name,
    )

__all__ = [
    "start_browser",
    "DefaultBrowser",
    "ask_files",
    "ask_folder",
    "default_browser",
    "dialogs_available",
    "file_filters",
    "installed_logs_dir",
    "lock_instance",
    "ocr_install_unavailable",
    "open_folder",
    "open_url",
    "platform_name",
    "prepare_gui",
    "program_filters",
    "run_ocr_install",
    "settings_dir",
    "tesseract_file_name",
]
