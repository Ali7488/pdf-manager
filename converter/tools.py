"""Locating and running the external programs: Tesseract OCR and LibreOffice."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path


def run_command(cmd: Sequence[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    """Run an external program and wait for it to finish.

    Output is captured as text instead of being printed. On Windows the program
    is started without a console window, so no black terminal flashes up while
    the GUI is running.

    Args:
        cmd: The program and its arguments. Items may be paths; they are
            converted to strings.
        timeout: Seconds to wait before giving up.

    Returns:
        The finished process, with ``returncode``, ``stdout`` and ``stderr``.
        A non-zero exit code is not raised as an error; callers check it.

    Raises:
        subprocess.TimeoutExpired: The program ran longer than ``timeout``.
        FileNotFoundError: The program does not exist.
    """
    options = {"capture_output": True, "text": True, "timeout": timeout}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(list(map(str, cmd)), **options)


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
                                # Strip quotes and a trailing icon index, e.g.
                                # '"C:\...\tesseract.exe",0' -> 'C:\...\tesseract.exe',
                                # then expand variables like %ProgramFiles%.
                                # Note: an unquoted 'C:\...\tesseract.exe,0' is not
                                # handled and yields a wrong candidate (harmless,
                                # since it just won't exist).
                                cleaned = os.path.expandvars(
                                    value.strip().strip('"').split('",')[0]
                                )
                                path = Path(cleaned)
                                # A folder value gets "tesseract.exe" appended.
                                possible.append(
                                    path
                                    if path.suffix.lower() == ".exe"
                                    else path / "tesseract.exe"
                                )
                    except OSError:
                        continue  # Key doesn't exist on this machine.
        except ImportError:
            pass
    # Return the first candidate that exists. The "seen" set skips duplicate
    # paths (compared case-insensitively, as Windows does).
    seen = set()
    for path in possible:
        normalized = str(path).casefold()
        if normalized not in seen and path.is_file():
            return path
        seen.add(normalized)
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
