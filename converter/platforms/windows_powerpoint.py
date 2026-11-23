"""Optional slide renderer: Microsoft PowerPoint, automated through COM (Windows only).

PowerPoint gives the most faithful slide rendering, but it is never required:
LibreOffice is the cross-platform renderer and the fallback. pywin32 modules are
imported inside functions so this module is importable (and testable with
fakes) on any system.

Behaviour that protects the user's own work:

* PowerPoint runs as a single instance. If the user already has it open, the
  converter attaches to that instance and **never quits it**; it only closes
  the presentation it opened.
* The export runs on a helper thread so it can time out or be cancelled. If it
  hangs (for example on PowerPoint's "Waiting for printer connection" dialog),
  the converter kills PowerPoint **only if the converter started it**.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
import traceback
from pathlib import Path

from ..core.context import CancelToken
from ..core.issues import Cancelled

log = logging.getLogger(__name__)

PP_SAVE_AS_PDF = 32  # PowerPoint's ppSaveAsPDF file format constant.


class PowerPointExportError(RuntimeError):
    """PowerPoint couldn't export the slides. The message holds technical details."""


def _process_id(app) -> int | None:
    """PowerPoint's process id, found through its main window handle (None if unknown)."""
    try:
        import win32process

        return win32process.GetWindowThreadProcessId(app.HWND)[1]
    except Exception:
        return None


def _kill(pid: int) -> None:
    """Force-stop a PowerPoint process the converter started. Never raises."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        log.debug("Couldn't kill PowerPoint pid %s", pid, exc_info=True)


def _export(source: Path, output: Path, state: dict) -> None:
    """Helper-thread body: open the file read-only and hidden, save it as PDF, clean up.

    Results go into ``state``: ``was_running``, ``pid`` (only when the converter
    started PowerPoint), and ``error`` / ``traceback`` on failure.
    """
    import pythoncom
    import win32com.client

    # COM must be initialised on every thread that uses it.
    pythoncom.CoInitialize()
    app = None
    presentation = None
    try:
        try:
            win32com.client.GetActiveObject("PowerPoint.Application")
            state["was_running"] = True
        except Exception:
            state["was_running"] = False
        app = win32com.client.DispatchEx("PowerPoint.Application")
        if not state["was_running"]:
            state["pid"] = _process_id(app)
        log.debug("PowerPoint attached (already running: %s)", state["was_running"])
        # Open(FileName, ReadOnly=True, Untitled=False, WithWindow=False)
        presentation = app.Presentations.Open(str(source), True, False, False)
        presentation.SaveAs(str(output), PP_SAVE_AS_PDF)
    except Exception as exc:
        state["error"] = exc
        state["traceback"] = traceback.format_exc()
    finally:
        if presentation is not None:
            try:
                presentation.Close()
            except Exception:
                log.debug("Closing the presentation failed", exc_info=True)
        # Quit only a PowerPoint the converter started, and only if nothing else
        # is open in it. The user's own PowerPoint is never closed (decision C2).
        if app is not None and not state.get("was_running", True):
            try:
                if app.Presentations.Count == 0:
                    app.Quit()
            except Exception:
                log.debug("Quitting PowerPoint failed", exc_info=True)
        pythoncom.CoUninitialize()


def export_slides(source: Path, output: Path, timeout: float, cancel: CancelToken) -> None:
    """Export a presentation to PDF with Microsoft PowerPoint.

    Args:
        source: Presentation to export (a scratch copy; see ``powerpoint.py``).
        output: PDF path to write.
        timeout: Seconds to wait before giving up.
        cancel: The job's cancel token.

    Raises:
        PowerPointExportError: PowerPoint failed, timed out, or wrote no PDF.
        Cancelled: The user cancelled.
    """
    state: dict = {}
    worker = threading.Thread(
        target=_export, args=(source, output, state), name="powerpoint-export", daemon=True
    )
    started = time.monotonic()
    worker.start()
    while worker.is_alive():
        worker.join(0.25)
        timed_out = time.monotonic() - started > timeout
        if worker.is_alive() and (cancel.cancelled or timed_out):
            pid = state.get("pid")
            if pid:
                _kill(pid)  # Only ever set when the converter started PowerPoint.
            if cancel.cancelled:
                raise Cancelled()
            note = "" if pid else " PowerPoint was already open, so it was left running."
            raise PowerPointExportError(
                f"PowerPoint didn't finish within {int(timeout)} seconds. It may be waiting "
                f"on a dialog such as 'Waiting for printer connection'.{note}"
            )
    if "error" in state:
        error = state["error"]
        raise PowerPointExportError(
            f"{type(error).__name__}: {error}\n{state.get('traceback', '')}".strip()
        )
    if not output.is_file() or output.stat().st_size == 0:
        raise PowerPointExportError("PowerPoint finished but didn't write a PDF.")
    log.debug("PowerPoint exported %s in %.1fs", source.name, time.monotonic() - started)
