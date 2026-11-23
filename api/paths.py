"""Where the app, its bundled files, its logs and its settings live.

Two run modes are supported:

* **Source** (development): ``uv run main.py`` from the repository. Every
  folder is relative to the repository root.
* **Frozen** (the installed app): a PyInstaller executable. Bundled files
  (the built UI) are unpacked to ``sys._MEIPASS``; the logs folder sits next
  to the executable (decision C4). The app installs per user (decision F17),
  so that folder is writable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repository root: this file is <root>/api/paths.py.
_REPO_ROOT = Path(__file__).resolve().parents[1]

# Folder and file names, in one place.
APP_FOLDER_WINDOWS = "PDFManager"  # Under %LOCALAPPDATA%.
APP_FOLDER_OTHER = "pdf-manager"  # Under $XDG_CONFIG_HOME.
SETTINGS_FILE = "settings.json"
LOGS_FOLDER = "logs"


def on_windows() -> bool:
    """Whether the app runs on Windows (a function so tests can switch it).

    Returns:
        True on Windows.
    """
    return os.name == "nt"


def is_frozen() -> bool:
    """Whether the app runs as a packaged (PyInstaller) executable.

    Returns:
        True for the installed app, False when running from source.
    """
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """The folder the app is installed in (or the repository root from source).

    Returns:
        The executable's folder when frozen, otherwise the repository root.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _REPO_ROOT


def resource_dir() -> Path:
    """The folder holding bundled read-only files, such as the built UI.

    PyInstaller unpacks bundled data to ``sys._MEIPASS`` (a temporary folder
    for one-file builds, the ``_internal`` folder for one-folder builds).

    Returns:
        ``sys._MEIPASS`` when frozen, otherwise the repository root.
    """
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        # Some freezers set sys.frozen without _MEIPASS; fall back to the exe folder.
        return Path(meipass) if meipass else app_dir()
    return _REPO_ROOT


def ui_index() -> Path:
    """Path of the built UI's entry page.

    Returns:
        ``<resource_dir>/frontend/dist/index.html``. It may not exist (for
        example before ``npm run build``); the caller checks.
    """
    return resource_dir() / "frontend" / "dist" / "index.html"


def logs_dir() -> Path:
    """The logs folder, next to the installed app (decision C4).

    Returns:
        ``<app_dir>/logs``. Not created here.
    """
    return app_dir() / LOGS_FOLDER


def settings_path() -> Path:
    """Where the user's settings are saved.

    On Windows this is per user, under ``%LOCALAPPDATA%\\PDFManager``, so it
    survives reinstalls and needs no admin rights. Elsewhere it follows the
    XDG convention (``$XDG_CONFIG_HOME``, default ``~/.config``).

    Returns:
        Full path of ``settings.json``. Neither the file nor its folder is
        created here.
    """
    if on_windows():
        base = os.environ.get("LOCALAPPDATA")
        # LOCALAPPDATA is always set on a normal Windows session; this is a fallback.
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / APP_FOLDER_WINDOWS / SETTINGS_FILE
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_FOLDER_OTHER / SETTINGS_FILE
