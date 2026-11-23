"""Pieces shared by more than one platform module (not part of the interface).

Only the platform modules import this file; shared API code goes through
:mod:`api.platforms`.
"""

from __future__ import annotations

import os
from pathlib import Path

# Native picker filters, in pywebview's "Description (*.ext;*.ext)" format. The
# Windows (WinForms) and Cocoa backends read this format as is; pywebview's Qt
# backend turns each ";" into the space Qt expects, so the strings are the same
# everywhere.
FILE_FILTERS: dict[str, tuple[str, ...]] = {
    "all": ("Supported files (*.pdf;*.pptx;*.ppt;*.png;*.jpg;*.jpeg)",),
    "documents": ("PDF and PowerPoint files (*.pdf;*.pptx;*.ppt)",),
    "images": ("Images (*.png;*.jpg;*.jpeg)",),
}

# Folder name under the XDG base folders (~/.config, ~/.local/state).
XDG_APP_FOLDER = "pdf-manager"


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
