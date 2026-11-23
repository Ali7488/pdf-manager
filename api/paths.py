"""Where the app, its bundled files, its logs and its settings live.

Two run modes are supported:

* **Source** (development): ``uv run main.py`` from the repository. The app
  and resource folders are the repository root, and logs go to its ``logs/``
  folder on every platform.
* **Frozen** (the installed app): a PyInstaller executable. Bundled files
  (the built UI) are unpacked to ``sys._MEIPASS``. The logs folder is chosen
  by the platform module: next to the executable on Windows (decision C4;
  the app installs per user, decision F17, so that folder is writable), and
  the XDG state folder on Linux (decision C15).

Settings live in the platform's per-user settings folder in both modes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import platforms

# Repository root: this file is <root>/api/paths.py.
_REPO_ROOT = Path(__file__).resolve().parents[1]

# Folder and file names, in one place.
SETTINGS_FILE = "settings.json"
LOGS_FOLDER = "logs"


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
    """The logs folder.

    Returns:
        From source, the repository's ``logs/`` folder. Installed, the
        platform's choice (:func:`api.platforms.installed_logs_dir`): next to
        the app on Windows (decision C4), ``$XDG_STATE_HOME/pdf-manager/logs``
        on Linux (decision C15). Not created here.
    """
    if not is_frozen():
        return _REPO_ROOT / LOGS_FOLDER
    return platforms.installed_logs_dir(app_dir())


def settings_path() -> Path:
    """Where the user's settings are saved.

    The folder is per user and comes from the platform module:
    ``%LOCALAPPDATA%\\PDFManager`` on Windows (it survives reinstalls and
    needs no admin rights), ``$XDG_CONFIG_HOME/pdf-manager`` (default
    ``~/.config/pdf-manager``) on Linux.

    Returns:
        Full path of ``settings.json``. Neither the file nor its folder is
        created here.
    """
    return platforms.settings_dir() / SETTINGS_FILE
