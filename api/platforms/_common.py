"""Pieces shared by more than one platform module (not part of the interface).

Only the platform modules import this file; shared API code goes through
:mod:`api.platforms`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Native picker filters, as "Description (*.ext;*.ext)". Each platform's dialog
# code turns them into its own format with parse_filter.
FILE_FILTERS: dict[str, tuple[str, ...]] = {
    "all": ("Supported files (*.pdf;*.pptx;*.ppt;*.png;*.jpg;*.jpeg)",),
    "documents": ("PDF and PowerPoint files (*.pdf;*.pptx;*.ppt)",),
    "images": ("Images (*.png;*.jpg;*.jpeg)",),
}

# Folder name under the XDG base folders (~/.config, ~/.local/state).
XDG_APP_FOLDER = "pdf-manager"

# The interface's page title, which app-mode browsers show as the window title.
# The Windows dialogs use it to find the window they belong to.
WINDOW_TITLE = "PDF Manager"


def parse_filter(text: str) -> tuple[str, list[str]]:
    """Split a ``"Description (*.a;*.b)"`` filter into its parts.

    Args:
        text: One entry of :data:`FILE_FILTERS` (or of ``program_filters()``).

    Returns:
        ``(description, ["*.a", "*.b"])``. Without a pattern list, the
        patterns are ``["*"]``.
    """
    description, _, rest = text.partition("(")
    patterns = [p.strip() for p in rest.rstrip(")").split(";") if p.strip()]
    return description.strip(), patterns or ["*"]


@dataclass(frozen=True)
class DefaultBrowser:
    """The user's default web browser, as browser mode sees it.

    Attributes:
        name: What it is, for the log (for example ``"Microsoft Edge"`` or a
            Windows ProgId / Linux desktop file it didn't recognise).
        app_command: The command that starts it, without the URL, when it is
            a Chromium-family browser that opens ``--app=<url>`` as a window
            without tabs (Edge, Chrome, Brave, Chromium). ``None`` otherwise:
            the URL then goes to the system's URL opener, which shows a tab.
    """

    name: str
    app_command: tuple[str, ...] | None = None


# Chromium-family browsers that browser mode opens in app mode, by the words
# their Windows ProgId or Linux desktop file name starts with or contains.
APP_MODE_BROWSERS = {
    "edge": "Microsoft Edge",
    "chrome": "Google Chrome",
    "brave": "Brave",
    "chromium": "Chromium",
}


def xdg_dir(variable: str, default: tuple[str, ...]) -> Path:
    """Resolve an XDG base folder, such as ``$XDG_CONFIG_HOME``.

    The XDG Base Directory specification says a relative value must be
    ignored, so only an absolute path from the environment is used.

    Args:
        variable: Environment variable, e.g. ``"XDG_STATE_HOME"``.
        default: The default below the home folder, e.g. ``(".local", "state")``.

    Returns:
        The base folder (not created here).
    """
    value = os.environ.get(variable, "")
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home().joinpath(*default)
