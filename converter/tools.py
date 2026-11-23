"""Locating and running the external programs: Tesseract OCR and LibreOffice.

Shared, platform-independent logic. Anything that differs per operating
system (process handling, install locations, PowerPoint detection) comes
from ``converter.platforms``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from . import platforms
from .context import CancelToken
from .issues import Cancelled

# Verbose (DEBUG) records are written in development mode; the API layer
# chooses the level. Errors are always logged with full details.
log = logging.getLogger(__name__)

# Re-exported so callers don't need to know which platform module provides them.
kill_process_tree = platforms.kill_process_tree
powerpoint_installed = platforms.powerpoint_installed


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
    # No console window on Windows; own process group elsewhere (so the whole
    # tree can be stopped). See converter/platforms.
    options.update(platforms.popen_options())
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


def _first_existing(candidates: Sequence[Path]) -> Path | None:
    """Return the first candidate that is a file, checking each distinct path once.

    Paths are compared case-insensitively for de-duplication (harmless on
    case-sensitive systems: it only skips re-checking).
    """
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


def find_tesseract(configured: str | Path | None = None) -> Path | None:
    """Find the Tesseract OCR executable, or return ``None`` if it isn't installed.

    Candidates are checked in this order, and the first one that exists wins:

    1. ``configured``: a path the user picked earlier with "Search for OCR".
    2. ``tesseract`` on the system ``PATH``.
    3. Platform-specific places (on Windows: install folders and the paths the
       Tesseract installer recorded in the registry).

    Args:
        configured: Optional user-chosen path to the Tesseract executable.
    """
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    located = shutil.which("tesseract")
    if located:
        candidates.append(Path(located))
    candidates += platforms.tesseract_candidates()
    return _first_existing(candidates)


def require_tesseract(configured: str | Path | None = None) -> Path:
    """Legacy helper for the old pipeline: like :func:`find_tesseract`, but raises if missing.

    Raises:
        RuntimeError: Tesseract could not be found.
    """
    engine = find_tesseract(configured)
    if engine is None:
        raise RuntimeError("OCR engine missing. Install OCR or search for it in Settings.")
    return engine


def find_libreoffice() -> Path | None:
    """Find the LibreOffice executable (``soffice``), or return ``None``.

    Checks ``PATH`` first (``soffice`` or ``libreoffice``), then the platform's
    usual install folders.
    """
    for name in ("soffice", "libreoffice"):
        value = shutil.which(name)
        if value:
            return Path(value)
    return _first_existing(platforms.libreoffice_candidates())


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


def find_powerpoint() -> Path | None:
    """Path of Microsoft PowerPoint's executable if installed (Windows only), for display."""
    return platforms.powerpoint_path()
