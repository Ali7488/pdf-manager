"""Log files, log levels and the logging of every issue shown to the user.

Decision C13: **development mode** (running from source, or with
``PDF_MANAGER_DEBUG=1``) logs verbosely at DEBUG level, including commands,
timings, tool output and tracebacks, and also prints to the console.
**Production** (the installed app) logs at INFO level, but errors are always
written in full, with details and tracebacks.

Where the log files live (:func:`api.paths.logs_dir`), which Settings can
open in the file manager: the repository's ``logs/`` folder from source; for
the installed app, next to it on Windows (decision C4) and
``$XDG_STATE_HOME/pdf-manager/logs`` on Linux (decision C15).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import tempfile
import traceback
from pathlib import Path

from . import __version__, paths
from .service import Issue, Severity

log = logging.getLogger(__name__)

LOG_FILE_NAME = "pdf-manager.log"
LOG_MAX_BYTES = 2 * 1024 * 1024  # Rotate at 2 MB...
LOG_BACKUPS = 5  # ...keeping 5 old files: at most about 12 MB of logs.
DEBUG_ENV = "PDF_MANAGER_DEBUG"
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"

# The log file in use, set by configure_logging(). Issues point at it.
_log_file: Path | None = None
# Handlers this module added, so configure_logging() can be called again safely.
_handlers: list[logging.Handler] = []


def dev_mode() -> bool:
    """Whether verbose development logging (and devtools) is on.

    Returns:
        True when running from source, or when ``PDF_MANAGER_DEBUG=1`` is set
        (useful to diagnose a problem in the installed app).
    """
    return not paths.is_frozen() or os.environ.get(DEBUG_ENV) == "1"


def log_file() -> Path | None:
    """The log file currently written to.

    Returns:
        Its path, or ``None`` if :func:`configure_logging` hasn't run yet.
    """
    return _log_file


def _open_log_handler(folder: Path) -> logging.Handler:
    """Create the rotating file handler, making the folder if needed.

    Args:
        folder: Folder to write ``pdf-manager.log`` into.

    Returns:
        The handler.

    Raises:
        OSError: The folder or the file couldn't be created.
    """
    folder.mkdir(parents=True, exist_ok=True)
    return logging.handlers.RotatingFileHandler(
        folder / LOG_FILE_NAME,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUPS,
        encoding="utf-8",
        # Open the file now, so an unwritable folder raises here and the
        # caller can fall back to another folder.
        delay=False,
    )


def configure_logging() -> Path:
    """Set up the log file (and the console in dev mode) and log the app start.

    Safe to call more than once: handlers from an earlier call are replaced.
    If the logs folder next to the app can't be written (unexpected, since
    the app installs per user), a folder in the system temp directory is used
    instead, so logging never stops the app from starting.

    Returns:
        Path of the log file in use.
    """
    global _log_file
    verbose = dev_mode()
    root = logging.getLogger()
    for handler in _handlers:
        root.removeHandler(handler)
        handler.close()
    _handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)
    folder = paths.logs_dir()
    fallback_reason = None
    try:
        file_handler = _open_log_handler(folder)
    except OSError as exc:
        # Known issue: only expected if the install folder is read-only.
        fallback_reason = f"{folder}: {exc}"
        folder = Path(tempfile.gettempdir()) / "pdf-manager-logs"
        file_handler = _open_log_handler(folder)
    file_handler.setFormatter(formatter)
    _handlers.append(file_handler)

    # A windowed (no console) PyInstaller build has sys.stderr set to None.
    if verbose and sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        _handlers.append(console)

    for handler in _handlers:
        root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    _log_file = folder / LOG_FILE_NAME

    log.info(
        "PDF Manager %s starting (%s mode, %s, Python %s)",
        __version__,
        "development" if verbose else "production",
        platform.platform(),
        platform.python_version(),
    )
    log.info(
        "Frozen: %s; app folder: %s; resources: %s; logs: %s; settings: %s",
        paths.is_frozen(),
        paths.app_dir(),
        paths.resource_dir(),
        folder,
        paths.settings_path(),
    )
    if fallback_reason:
        log.warning("Logs folder not writable, using %s instead (%s)", folder, fallback_reason)
    return _log_file


def log_issue(issue: Issue, exc: BaseException | None = None) -> Issue:
    """Write an issue to the log and point it at the log file.

    Every issue sent to the UI goes through here, so the logs folder holds
    the full record (decision C4). Errors are logged at ERROR level and
    warnings at WARNING level, so both appear in production logs.

    Args:
        issue: The issue about to be shown to the user.
        exc: The exception behind it, if any; its traceback is logged too.

    Returns:
        A copy of ``issue`` with ``log_file`` set, or the issue unchanged if
        logging hasn't been configured.
    """
    level = logging.ERROR if issue.severity == Severity.ERROR else logging.WARNING
    lines = [f"Issue {issue.code}: {issue.title}", f"Message: {issue.message}"]
    if issue.file:
        lines.append(f"File: {issue.file}")
    if issue.details:
        lines.append(f"Details:\n{issue.details}")
    if exc is not None:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        lines.append(f"Traceback:\n{trace.rstrip()}")
    log.log(level, "\n".join(lines))
    return issue.with_log_file(str(_log_file)) if _log_file is not None else issue
