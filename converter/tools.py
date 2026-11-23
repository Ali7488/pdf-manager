"""Locating and running the external programs: Tesseract OCR and LibreOffice."""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from .context import CancelToken
from .issues import Cancelled

# Verbose (DEBUG) records are written in development mode; the API layer
# chooses the level. Errors are always logged with full details.
log = logging.getLogger(__name__)


def kill_process_tree(process: subprocess.Popen) -> None:
    """Stop a program and every program it started. Never raises.

    LibreOffice's ``soffice`` launches a child process (``soffice.bin``), so
    killing only the parent would leave the real worker running.
    """
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            # /T kills the whole tree, /F forces it.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            # The program was started in its own session, so its process
            # group id equals its pid and covers all of its children.
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass


def run_command(
    cmd: Sequence[str], timeout: float = 600, cancel: CancelToken | None = None
) -> subprocess.CompletedProcess[str]:
    """Run an external program and wait for it to finish.

    Output is captured as text instead of being printed. On Windows the program
    is started without a console window, so no black terminal flashes up while
    the app is running. If the job is cancelled while the program runs, the
    program (and anything it started) is killed straight away.

    Args:
        cmd: The program and its arguments. Items may be paths; they are
            converted to strings.
        timeout: Seconds to wait before giving up.
        cancel: The job's cancel token, so Cancel can stop the program.

    Returns:
        The finished process, with ``returncode``, ``stdout`` and ``stderr``.
        A non-zero exit code is not raised as an error; callers check it.

    Raises:
        subprocess.TimeoutExpired: The program ran longer than ``timeout``
            (it has been killed).
        Cancelled: The job was cancelled while the program ran.
        FileNotFoundError: The program does not exist.
    """
    args = list(map(str, cmd))
    options: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        # Tool output isn't always UTF-8 on Windows; never fail on decoding.
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True  # Own process group, see kill_process_tree.
    log.debug("Running (timeout %ss): %s", timeout, subprocess.list2cmdline(args))
    started = time.monotonic()
    process = subprocess.Popen(args, **options)
    if cancel is not None:
        cancel.attach(process, kill_process_tree)
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("Timed out after %ss, killing: %s", timeout, args[0])
            kill_process_tree(process)
            process.communicate()
            raise
    finally:
        if cancel is not None:
            cancel.detach()
    log.debug(
        "Exit code %s after %.1fs: %s\n--- stdout ---\n%s\n--- stderr ---\n%s",
        process.returncode,
        time.monotonic() - started,
        args[0],
        (stdout or "").strip(),
        (stderr or "").strip(),
    )
    if cancel is not None and cancel.cancelled:
        log.info("Cancelled while running: %s", args[0])
        raise Cancelled()
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def exe_from_registry_value(value: str, exe_name: str = "tesseract.exe") -> Path:
    """Turn a registry value into the path of an executable.

    Installers store paths in several shapes; all of these give
    ``C:\\Tools\\tesseract.exe``:

    * ``C:\\Tools\\tesseract.exe`` (plain path)
    * ``"C:\\Tools\\tesseract.exe",0`` (quoted, with an icon index)
    * ``C:\\Tools\\tesseract.exe,0`` (unquoted, with an icon index)
    * ``C:\\Tools`` (a folder: ``exe_name`` is appended)

    Environment variables such as ``%ProgramFiles%`` are expanded.
    """
    text = os.path.expandvars(value.strip())
    if text.startswith('"'):
        # Quoted: the path is everything up to the closing quote.
        text = text[1:].split('"', 1)[0]
    else:
        # Unquoted: drop a trailing icon index such as ",0" or ",-101".
        text = re.sub(r",\s*-?\d+$", "", text)
    path = Path(text)
    return path if path.suffix.lower() == ".exe" else path / exe_name


def find_tesseract(configured: str | Path | None = None) -> Path | None:
    """Find the Tesseract OCR executable, or return ``None`` if it isn't installed.

    Candidates are checked in this order, and the first one that exists wins:

    1. ``configured``: a path the user picked earlier with "Find OCR".
    2. ``tesseract`` on the system ``PATH``.
    3. (Windows) The standard install folders under Program Files and
       LocalAppData.
    4. (Windows) Paths recorded in the registry by the Tesseract installer.

    The registry and folder checks exist because a fresh ``winget`` install can
    be per-user and isn't on ``PATH`` until a new session starts, so ``PATH``
    alone was unreliable.

    Args:
        configured: Optional user-chosen path to ``tesseract.exe``.

    Returns:
        Path to the executable, or ``None`` if no candidate exists.
    """
    possible: list[Path] = []
    if configured:
        possible.append(Path(configured).expanduser())
    located = shutil.which("tesseract")
    if located:
        possible.append(Path(located))
    if os.name == "nt":
        # Default install locations for machine-wide and per-user installs.
        roots = [
            os.getenv("ProgramFiles"),
            os.getenv("ProgramFiles(x86)"),
            os.getenv("LOCALAPPDATA"),
        ]
        for root in filter(None, roots):
            base = Path(root)
            possible.extend(
                (
                    base / "Tesseract-OCR" / "tesseract.exe",
                    base / "Programs" / "Tesseract-OCR" / "tesseract.exe",
                )
            )
        try:
            import winreg

            # Registry keys the Tesseract installer is known to write. Each key is
            # checked in both the machine-wide and the current-user hive.
            hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
            keys = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tesseract.exe",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Tesseract-OCR_is1",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Tesseract-OCR_is1",
                r"SOFTWARE\Tesseract-OCR",
            )
            for hive in hives:
                for keyname in keys:
                    try:
                        with winreg.OpenKey(hive, keyname) as key:
                            # "" is the key's default value (App Paths stores the
                            # full exe path there). The others hold an install
                            # folder or an icon path pointing at the exe.
                            for value_name in ("InstallLocation", "Path", "DisplayIcon", ""):
                                try:
                                    value, _ = winreg.QueryValueEx(key, value_name)
                                except OSError:
                                    continue
                                if not isinstance(value, str) or not value.strip():
                                    continue
                                # Handles quoted/unquoted paths, icon indexes
                                # and folders; see exe_from_registry_value.
                                possible.append(exe_from_registry_value(value))
                    except OSError:
                        continue  # Key doesn't exist on this machine.
        except ImportError:
            pass
    # Return the first candidate that exists, checking each distinct path
    # (compared case-insensitively, as Windows does) only once.
    seen: set[str] = set()
    for path in possible:
        normalized = str(path).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.is_file():
            return path
    return None


def require_tesseract(configured: str | Path | None = None) -> Path:
    """Return the Tesseract executable, or raise a user-facing error if it's missing.

    Same search as :func:`find_tesseract`, for code paths that cannot continue
    without OCR (Flatten and Flatten + Merge).

    Args:
        configured: Optional user-chosen path to ``tesseract.exe``.

    Raises:
        RuntimeError: Tesseract could not be found. The message tells the user
            how to install or locate it from the dashboard.
    """
    engine = find_tesseract(configured)
    if engine is None:
        raise RuntimeError(
            "OCR engine missing. Click 'Install OCR' or 'Find OCR' in the dashboard, then retry."
        )
    return engine


def find_libreoffice() -> Path | None:
    """Find the LibreOffice executable (``soffice``), or return ``None``.

    Checks ``PATH`` first (``soffice`` or ``libreoffice``), then on Windows the
    standard install folders under Program Files and LocalAppData.

    Returns:
        Path to the executable, or ``None`` if LibreOffice isn't installed.
    """
    for name in ("soffice", "libreoffice"):
        value = shutil.which(name)
        if value:
            return Path(value)
    if os.name == "nt":
        for root in (
            os.getenv("ProgramFiles"),
            os.getenv("ProgramFiles(x86)"),
            os.getenv("LOCALAPPDATA"),
        ):
            if root:
                for sub in (
                    "LibreOffice/program/soffice.exe",
                    "Programs/LibreOffice/program/soffice.exe",
                ):
                    value = Path(root) / sub
                    if value.is_file():
                        return value
    return None


def tesseract_languages(tesseract: Path) -> list[str]:
    """List the OCR languages installed for Tesseract, e.g. ``["deu", "eng"]``.

    The ``osd`` entry (orientation detection, not a language) is left out.
    Returns an empty list if Tesseract can't be run.
    """
    try:
        proc = run_command([tesseract, "--list-langs"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    # Output: a header line ("List of available languages ..."), then one code per line.
    lines = (proc.stdout or proc.stderr or "").splitlines()[1:]
    return sorted({line.strip() for line in lines if line.strip() and line.strip() != "osd"})


def powerpoint_installed() -> bool:
    """Whether Microsoft PowerPoint can be automated on this computer (Windows only).

    Checks that the ``PowerPoint.Application`` automation class is registered,
    which is what the converter uses. Doesn't start PowerPoint.
    """
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application\CLSID"):
            return True
    except (ImportError, OSError):
        return False


def find_powerpoint() -> Path | None:
    """Path to ``POWERPNT.EXE`` if PowerPoint is installed, for display in the tool check.

    Uses the "App Paths" registry entry Office writes. Returns ``None`` if
    PowerPoint isn't installed or the path isn't recorded.
    """
    if not powerpoint_installed():
        return None
    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key_name = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\powerpnt.exe"
                with winreg.OpenKey(hive, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    path = exe_from_registry_value(value, "POWERPNT.EXE")
                    if path.is_file():
                        return path
            except OSError:
                continue
    except ImportError:
        pass
    return None
