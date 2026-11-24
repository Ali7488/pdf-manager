"""Windows implementation of the API layer's platform interface.

Behaviour is unchanged from before the platform split: Explorer through
``os.startfile``, settings under ``%LOCALAPPDATA%\\PDFManager``, logs next to
the installed app (decision C4) and the in-app OCR install through winget.
Browser mode adds native file and folder pickers (pywin32) and the default
browser lookup. Windows-only modules are imported inside the functions that
need them, so this module can be imported (and its parsing tested) anywhere.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .. import service
from ..service import Issue, ocr_install_failed
from ._common import APP_MODE_BROWSERS, FILE_FILTERS, WINDOW_TITLE, DefaultBrowser, parse_filter

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


# ----- Browser mode: the default browser -----

# Where Windows records the user's choice of browser for web links.
_URL_CHOICE_KEY = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{}\UserChoice"
# ProgId prefixes of the Chromium-family browsers (stable, beta, dev and canary
# channels share them: MSEdgeHTM, MSEdgeBHTML, ChromeHTML, ChromeBHTML, ...).
_PROGID_PREFIXES = (
    ("MSEdge", "edge"),
    ("ChromeHTML", "chrome"),
    ("ChromeBHTML", "chrome"),
    ("ChromeDHTML", "chrome"),
    ("ChromeSSHTM", "chrome"),
    ("Brave", "brave"),
    ("ChromiumHTM", "chromium"),
)


def classify_progid(progid: str) -> str | None:
    """Which app-mode browser a Windows ProgId belongs to (a key of APP_MODE_BROWSERS)."""
    for prefix, key in _PROGID_PREFIXES:
        if progid.startswith(prefix):
            return key
    return None


def command_executable(command: str) -> str | None:
    """The program in a registry ``shell\\open\\command`` value.

    Args:
        command: For example ``"C:\\...\\msedge.exe" --single-argument %1``.

    Returns:
        The executable path, or ``None`` if the value is empty.
    """
    command = command.strip()
    match = re.match(r'^"([^"]+)"', command) or re.match(r"^(\S+)", command)
    return match.group(1) if match else None


def default_browser() -> DefaultBrowser:
    """The browser Windows opens web links with, and how to start it in app mode."""
    import winreg

    progid = ""
    for scheme in ("https", "http"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _URL_CHOICE_KEY.format(scheme)) as key:
                progid = str(winreg.QueryValueEx(key, "ProgId")[0])
                break
        except OSError:
            continue
    browser = classify_progid(progid)
    if browser is None:
        return DefaultBrowser(progid or "unknown")
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command") as key:
            exe = command_executable(str(winreg.QueryValueEx(key, "")[0]))
    except OSError:
        exe = None
    if not exe or not Path(exe).is_file():
        log.info("Default browser %s: its program wasn't found", progid)
        return DefaultBrowser(progid)
    return DefaultBrowser(APP_MODE_BROWSERS[browser], (exe,))


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
        creationflags=subprocess.DETACHED_PROCESS,
    )


def open_url(url: str) -> None:
    """Open a URL with the system's default handler (a normal browser tab).

    Raises:
        OSError: It couldn't be opened.
    """
    os.startfile(url)


# ----- Browser mode: native pickers (pywin32) -----

OFN_HIDEREADONLY = 0x4
OFN_NOCHANGEDIR = 0x8
OFN_ALLOWMULTISELECT = 0x200
OFN_PATHMUSTEXIST = 0x800
OFN_FILEMUSTEXIST = 0x1000
OFN_EXPLORER = 0x80000
BIF_RETURNONLYFSDIRS = 0x1
BIF_NEWDIALOGSTYLE = 0x40  # Resizable, with "Make new folder"; not in pywin32's shellcon.
BFFM_INITIALIZED = 1
BFFM_SETSELECTIONW = 0x400 + 103


def dialogs_available() -> bool:
    """Whether the native pickers can be shown (pywin32 is installed)."""
    try:
        import win32gui  # noqa: F401
        from win32com.shell import shell  # noqa: F401
    except ImportError:
        return False
    return True


def split_open_result(result: str) -> list[Path]:
    """Turn ``GetOpenFileNameW``'s result into paths.

    One file comes back as its full path. Several come back as the folder, then
    each file name, separated by NUL characters.
    """
    parts = [part for part in result.split("\0") if part]
    if len(parts) <= 1:
        return [Path(part) for part in parts]
    folder = Path(parts[0])
    return [folder / name for name in parts[1:]]


def open_filter_spec(filters: tuple[str, ...]) -> str | None:
    """The ``lpstrFilter`` string for ``GetOpenFileNameW`` ("Name\\0*.a;*.b\\0...")."""
    spec = "".join(
        f"{name}\0{';'.join(patterns)}\0" for name, patterns in map(parse_filter, filters)
    )
    return spec or None


@contextlib.contextmanager
def _dialog_owner() -> Iterator[int]:
    """The window a picker belongs to, attached so the picker can come to the front.

    Browser mode's pickers are opened by this process while the browser window
    has the focus, and Windows doesn't let a background process take the
    foreground. The picker is owned by the app's browser window (its title
    starts with the page title) and this thread's input is attached to that
    window's thread while it is open. That is what makes the picker appear in
    front of the window; it must be confirmed on a real PC (docs/BROWSER_MODE.md).
    """
    import win32api
    import win32gui
    import win32process

    owner = win32gui.GetForegroundWindow()
    if not owner or not win32gui.GetWindowText(owner).startswith(WINDOW_TITLE):
        try:
            owner = win32gui.FindWindow(None, WINDOW_TITLE)
        except win32gui.error:
            owner = 0
    attached = None
    if owner:
        current = win32api.GetCurrentThreadId()
        target = win32process.GetWindowThreadProcessId(owner)[0]
        if target and target != current:
            try:
                win32process.AttachThreadInput(current, target, True)
                attached = (current, target)
            except win32process.error:
                log.debug("Couldn't attach to the browser window's input", exc_info=True)
    try:
        yield owner or 0
    finally:
        if attached:
            with contextlib.suppress(win32process.error):
                win32process.AttachThreadInput(*attached, False)


def ask_files(filters: tuple[str, ...], multiple: bool) -> list[Path]:
    """Show the native Open dialog.

    Args:
        filters: ``"Description (*.a;*.b)"`` entries.
        multiple: Allow selecting several files.

    Returns:
        The chosen files; empty if the user cancelled.
    """
    import win32gui

    flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY
    flags |= OFN_NOCHANGEDIR | (OFN_ALLOWMULTISELECT if multiple else 0)
    with _dialog_owner() as owner:
        try:
            result, _, _ = win32gui.GetOpenFileNameW(
                hwndOwner=owner, Filter=open_filter_spec(filters), Flags=flags, MaxFile=65536
            )
        except win32gui.error as exc:
            if exc.winerror == 0:  # Cancelled (CommDlgExtendedError() is 0).
                return []
            raise
    return split_open_result(result)


def ask_folder(start: str) -> Path | None:
    """Show the native folder picker, starting in ``start`` if it is set.

    Returns:
        The chosen folder, or ``None`` if the user cancelled.
    """
    import pythoncom
    import win32gui
    from win32com.shell import shell

    def on_message(hwnd, message, _lparam, data):
        if message == BFFM_INITIALIZED and data:
            win32gui.SendMessage(hwnd, BFFM_SETSELECTIONW, 1, data)

    pythoncom.CoInitialize()  # The new dialog style needs COM on this thread.
    try:
        with _dialog_owner() as owner:
            result = shell.SHBrowseForFolder(
                owner,
                None,
                "Choose a folder",
                BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE,
                on_message,
                start or None,
            )
        pidl = result[0] if result else None
        return Path(shell.SHGetPathFromIDListW(pidl)) if pidl else None
    finally:
        pythoncom.CoUninitialize()


def lock_instance(path: Path) -> BinaryIO | None:
    """Take this user's browser-mode instance lock, or return ``None`` if it is held.

    Locks the first byte of ``path`` (created if needed) with
    ``msvcrt.locking(LK_NBLCK)``. The returned file must stay open for as long
    as the instance runs: Windows releases the lock when it is closed or when
    the process ends, so a killed instance never leaves a stale lock
    (decision P41).
    """
    import msvcrt

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle
