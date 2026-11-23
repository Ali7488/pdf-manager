"""Running external programs (Tesseract, LibreOffice) so they can time out or be cancelled.

Platform-independent. How a program is started without a console window and
how its whole process tree is stopped comes from ``converter.platforms``.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Sequence

from .. import platforms
from ..core.context import CancelToken
from ..core.issues import Cancelled

# Verbose (DEBUG) records are written in development mode; the API layer
# chooses the level. Errors are always logged with full details.
log = logging.getLogger(__name__)

# Re-exported so callers don't need to know which platform module provides it.
kill_process_tree = platforms.kill_process_tree


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
