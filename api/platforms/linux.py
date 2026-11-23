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
* Browser mode uses ``zenity`` or ``kdialog`` for native pickers when one is
  installed (otherwise the browser's own file selection), and finds the
  default browser with ``xdg-settings`` and its desktop file.

Other POSIX systems without their own module (for example the BSDs) use this
one as well; their desktops provide ``xdg-open`` too.
"""

from __future__ import annotations

import logging
import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

from ..service import Issue, IssueCode, Severity
from ._common import (
    APP_MODE_BROWSERS,
    FILE_FILTERS,
    XDG_APP_FOLDER,
    DefaultBrowser,
    parse_filter,
    xdg_dir,
)

log = logging.getLogger(__name__)

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


# ----- Browser mode: the default browser -----

# Desktop file names of the app-mode browsers, by the word they contain
# (microsoft-edge.desktop, google-chrome.desktop, brave-browser.desktop,
# com.brave.Browser.desktop for the Flatpak, chromium(-browser).desktop).
_DESKTOP_WORDS = (("microsoft-edge", "edge"), ("chrome", "chrome"), ("brave", "brave"))


def classify_desktop_id(desktop_id: str) -> str | None:
    """Which app-mode browser a desktop file name belongs to (a key of APP_MODE_BROWSERS)."""
    name = desktop_id.lower()
    if "chromium" in name:
        return "chromium"
    for word, key in _DESKTOP_WORDS:
        if word in name:
            return key
    return None


def desktop_exec_command(exec_line: str) -> tuple[str, ...] | None:
    """The command of a desktop file's ``Exec`` value, without its field codes.

    Field codes such as ``%U`` and the Flatpak markers ``@@u``/``@@`` are
    dropped, so the URL can be added as ``--app=<url>``.
    """
    try:
        words = shlex.split(exec_line)
    except ValueError:
        return None
    words = [w for w in words if not (w.startswith("%") and len(w) == 2) and w not in ("@@u", "@@")]
    return tuple(words) or None


def _desktop_file(desktop_id: str) -> Path | None:
    """Find a desktop file in the XDG data folders (including Flatpak's exports)."""
    homes = [xdg_dir("XDG_DATA_HOME", (".local", "share"))]
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    homes += [Path(d) for d in dirs.split(":") if d]
    homes += [Path("/var/lib/flatpak/exports/share")]
    for home in homes:
        candidate = home / "applications" / desktop_id
        if candidate.is_file():
            return candidate
    return None


def _desktop_exec(path: Path) -> str | None:
    """The ``Exec`` value of a desktop file's main ``[Desktop Entry]`` section."""
    section = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
        elif section == "[Desktop Entry]" and line.startswith("Exec="):
            return line.removeprefix("Exec=")
    return None


def default_browser() -> DefaultBrowser:
    """The desktop's default browser, and how to start it in app mode."""
    try:
        proc = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return DefaultBrowser("unknown (xdg-settings unavailable)")
    desktop_id = proc.stdout.strip()
    browser = classify_desktop_id(desktop_id)
    if not desktop_id or browser is None:
        return DefaultBrowser(desktop_id or "unknown")
    path = _desktop_file(desktop_id)
    exec_line = _desktop_exec(path) if path else None
    command = desktop_exec_command(exec_line) if exec_line else None
    if not command:
        log.info("Default browser %s: no usable Exec line", desktop_id)
        return DefaultBrowser(desktop_id)
    return DefaultBrowser(APP_MODE_BROWSERS[browser], command)


def open_url(url: str) -> None:
    """Open a URL with ``xdg-open`` (the default browser, in a normal tab).

    Raises:
        OSError: ``xdg-open`` couldn't be started.
    """
    subprocess.Popen(
        ["xdg-open", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# ----- Browser mode: native pickers (zenity, kdialog) -----


def _picker() -> tuple[str, str] | None:
    """``("zenity" | "kdialog", path)`` for the first installed picker program."""
    for name in ("zenity", "kdialog"):
        found = shutil.which(name)
        if found:
            return name, found
    return None


def dialogs_available() -> bool:
    """Whether a native picker program (zenity or kdialog) is installed."""
    return _picker() is not None


def files_command(program: str, path: str, filters: tuple[str, ...], multiple: bool) -> list[str]:
    """The zenity or kdialog command line for an Open dialog."""
    parsed = [parse_filter(f) for f in filters]
    if program == "zenity":
        cmd = [path, "--file-selection", "--title=Add files"]
        if multiple:
            cmd += ["--multiple", "--separator=\n"]
        return cmd + [f"--file-filter={name} | {' '.join(pats)}" for name, pats in parsed]
    spec = "\n".join(f"{' '.join(pats)}|{name}" for name, pats in parsed)
    cmd = [path, "--title", "Add files", "--getopenfilename", str(Path.home()), spec]
    return cmd + (["--multiple", "--separate-output"] if multiple else [])


def folder_command(program: str, path: str, start: str) -> list[str]:
    """The zenity or kdialog command line for a folder picker."""
    start = start or str(Path.home())
    if program == "zenity":
        return [
            path,
            "--file-selection",
            "--directory",
            "--title=Choose a folder",
            f"--filename={start.rstrip('/')}/",
        ]
    return [path, "--title", "Choose a folder", "--getexistingdirectory", start]


def _run_picker(cmd: list[str]) -> list[str]:
    """Run a picker and return the chosen paths (none if cancelled or it failed)."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:  # 1: cancelled. Anything else: logged.
        if proc.returncode != 1:
            log.warning("%s exited with %d: %s", cmd[0], proc.returncode, proc.stderr.strip())
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def ask_files(filters: tuple[str, ...], multiple: bool) -> list[Path]:
    """Show zenity's or kdialog's Open dialog. Returns the chosen files (empty if cancelled)."""
    picker = _picker()
    if picker is None:
        return []
    return [Path(p) for p in _run_picker(files_command(*picker, filters, multiple))]


def ask_folder(start: str) -> Path | None:
    """Show zenity's or kdialog's folder picker. Returns the folder, or ``None``."""
    picker = _picker()
    if picker is None:
        return None
    chosen = _run_picker(folder_command(*picker, start))
    return Path(chosen[0]) if chosen else None
