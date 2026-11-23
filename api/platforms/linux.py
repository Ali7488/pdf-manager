"""Linux implementation of the API layer's platform interface.

* The window uses pywebview's Qt backend with **PySide6** (decisions P18,
  P19), never PyQt6.
* Folders open with ``xdg-open`` in the desktop's file manager.
* Settings follow XDG: ``$XDG_CONFIG_HOME/pdf-manager`` (default
  ``~/.config/pdf-manager``).
* The installed app logs to ``$XDG_STATE_HOME/pdf-manager/logs`` (default
  ``~/.local/state/pdf-manager/logs``), because a packaged app lives in a
  read-only system folder (decision C15). From source, logs stay in the
  repository's ``logs/`` (see :func:`api.paths.logs_dir`).
* "Install OCR" never installs anything and never runs ``sudo`` (decision
  C16): it finishes at once with an issue holding the exact command for the
  user's distribution, which the UI shows with a Copy button.

Other POSIX systems without their own module (for example the BSDs) use this
one as well; their desktops provide ``xdg-open`` too.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from ..service import Issue, IssueCode, Severity
from ._common import FILE_FILTERS, XDG_APP_FOLDER, xdg_dir

LOGS_FOLDER = "logs"

# Distribution families, matched against ID and ID_LIKE in os-release.
DEBIAN = "debian"
ARCH = "arch"
_FAMILY_IDS = {
    "debian": DEBIAN,
    "ubuntu": DEBIAN,
    "arch": ARCH,
}
# The exact commands from decision C16.
OCR_INSTALL_COMMANDS = {
    DEBIAN: "sudo apt install tesseract-ocr tesseract-ocr-eng",
    ARCH: "sudo pacman -S tesseract tesseract-data-eng",
}


def platform_name() -> str:
    """The contract's ``AppInfo.platform``."""
    return "linux"


def prepare_gui() -> str:
    """Make pywebview use Qt WebEngine through PySide6.

    pywebview's Qt backend imports Qt through QtPy, which picks the binding
    named in ``QT_API``. It is set unconditionally, so PyQt6 (GPL) is never
    used even if it happens to be installed (decision P19). Must run before
    ``webview.start``, which is when QtPy is first imported.

    Returns:
        ``"qt"``, the pywebview GUI to request.
    """
    os.environ["QT_API"] = "pyside6"
    return "qt"


def open_folder(folder: Path) -> None:
    """Open a folder in the desktop's file manager with ``xdg-open``.

    Args:
        folder: An existing folder (checked by the caller).

    Raises:
        OSError: ``xdg-open`` couldn't be started (for example it isn't installed).
    """
    subprocess.Popen(
        ["xdg-open", str(folder)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # Don't tie the file manager to this app's lifetime.
    )


def file_filters() -> dict[str, tuple[str, ...]]:
    """Native file picker filters for ``pick_files``, by kind."""
    return FILE_FILTERS


def program_filters() -> tuple[str, ...]:
    """No filter when the user looks for Tesseract: Linux programs have no extension."""
    return ()


def tesseract_file_name() -> str:
    """File name the user must pick in "Search for OCR"."""
    return "tesseract"


def settings_dir() -> Path:
    """Settings folder: ``$XDG_CONFIG_HOME/pdf-manager`` (default ``~/.config/pdf-manager``)."""
    return xdg_dir("XDG_CONFIG_HOME", (".config",)) / XDG_APP_FOLDER


def installed_logs_dir(app_dir: Path) -> Path:
    """Logs folder of the installed app, in the XDG state folder (decision C15).

    Args:
        app_dir: The folder the executable is in. Unused: a packaged app's
            folder is read-only on Linux.

    Returns:
        ``$XDG_STATE_HOME/pdf-manager/logs`` (default
        ``~/.local/state/pdf-manager/logs``), not created here.
    """
    return xdg_dir("XDG_STATE_HOME", (".local", "state")) / XDG_APP_FOLDER / LOGS_FOLDER


def read_os_release() -> dict[str, str]:
    """Read ``/etc/os-release`` (or ``/usr/lib/os-release``).

    Returns:
        Its fields, e.g. ``{"ID": "ubuntu", "ID_LIKE": "debian", ...}``; empty
        if neither file can be read.
    """
    try:
        return platform.freedesktop_os_release()
    except OSError:
        return {}


def distribution_family(os_release: dict[str, str]) -> str | None:
    """Which package family a distribution belongs to.

    ``ID`` is checked first, then each entry of ``ID_LIKE`` in order, so a
    derivative such as Linux Mint (``ID_LIKE="ubuntu debian"``) or CachyOS
    (``ID_LIKE=arch``) maps to its parent.

    Args:
        os_release: Fields from :func:`read_os_release`.

    Returns:
        ``"debian"`` (Debian, Ubuntu and their derivatives), ``"arch"`` (Arch
        and its derivatives), or ``None`` if unknown.
    """
    candidates = [os_release.get("ID", ""), *os_release.get("ID_LIKE", "").split()]
    for candidate in candidates:
        family = _FAMILY_IDS.get(candidate.strip().lower())
        if family:
            return family
    return None


def ocr_install_command(os_release: dict[str, str]) -> str | None:
    """The exact command that installs Tesseract with English data (decision C16).

    Args:
        os_release: Fields from :func:`read_os_release`.

    Returns:
        The command for the user's distribution, or ``None`` if it isn't known.
    """
    family = distribution_family(os_release)
    return OCR_INSTALL_COMMANDS.get(family) if family else None


def ocr_install_issue(os_release: dict[str, str]) -> Issue:
    """The issue shown when the user clicks "Install OCR" on Linux.

    Proposed: this wording should move to ``converter/core/issues.py`` as its
    own factory (next to ``ocr_install_failed``), so all user-facing text lives
    in one place.

    Args:
        os_release: Fields from :func:`read_os_release`.

    Returns:
        An ``OCR_INSTALL_FAILED`` issue. For a known distribution, ``command``
        holds the exact install command; otherwise it is ``None`` and the
        steps point at the system's software manager.
    """
    command = ocr_install_command(os_release)
    detected = (
        f"Detected system: ID={os_release.get('ID') or 'unknown'}, "
        f"ID_LIKE={os_release.get('ID_LIKE') or 'none'}"
    )
    if command:
        return Issue(
            IssueCode.OCR_INSTALL_FAILED,
            Severity.ERROR,
            "Install OCR with one command",
            "On Linux, PDF Manager doesn't install programs itself. "
            "Run the command below in a terminal to install OCR (Tesseract).",
            (
                "Click Copy, open a terminal, paste the command and press Enter.",
                "Type your password if asked. Nothing appears while you type it; that's normal.",
                "When it has finished, click Search for OCR in Settings.",
            ),
            details=f"{detected}\nCommand: {command}",
            command=command,
        )
    return Issue(
        IssueCode.OCR_INSTALL_FAILED,
        Severity.ERROR,
        "Install OCR from your software manager",
        "On Linux, PDF Manager doesn't install programs itself. "
        "Install the OCR program (Tesseract) with your system's software manager.",
        (
            "Open your system's software manager and install Tesseract OCR "
            "with its English language data.",
            "When it has finished, click Search for OCR in Settings.",
        ),
        details=detected,
    )


def ocr_install_unavailable() -> Issue:
    """The app never installs OCR on Linux; explain how to do it instead.

    Returns:
        The issue from :func:`ocr_install_issue` for this system.
    """
    return ocr_install_issue(read_os_release())


def run_ocr_install() -> str:
    """Never used on Linux: :func:`ocr_install_unavailable` always returns an issue.

    Raises:
        RuntimeError: Always. The app never runs package installs or ``sudo``.
    """
    raise RuntimeError("PDF Manager never installs programs on Linux (decision C16).")
