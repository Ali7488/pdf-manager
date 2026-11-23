"""Per-job context: cancellation, progress reporting and warning collection.

Every step of a job receives the same :class:`JobContext`, so cancellation,
progress and warnings work the same way everywhere.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field

from .common import ActionSettings, Progress, ProgressEvent, Stage
from .issues import Cancelled, Issue


class CancelToken:
    """Thread-safe cancel flag that can also stop a running external program.

    The API layer calls :meth:`cancel` from the UI thread. The job, on its
    worker thread, calls :meth:`check` between pages and files. While an
    external program (Tesseract, LibreOffice) runs, it is registered here so
    cancelling can stop it immediately instead of waiting for it to finish.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._killer = None  # Callable[[subprocess.Popen], None], set by tools.run_command.

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        """Request cancellation and stop the running external program, if any."""
        self._event.set()
        with self._lock:
            if self._process is not None and self._killer is not None:
                self._killer(self._process)

    def check(self) -> None:
        """Raise :class:`Cancelled` if cancellation was requested."""
        if self._event.is_set():
            raise Cancelled()

    def attach(self, process: subprocess.Popen, killer) -> None:
        """Register the external program currently running for this job."""
        with self._lock:
            self._process, self._killer = process, killer
        if self._event.is_set():  # Cancelled just before the program started.
            killer(process)

    def detach(self) -> None:
        """Forget the external program once it has finished."""
        with self._lock:
            self._process, self._killer = None, None


def _ignore(_: ProgressEvent) -> None:
    """Default progress callback that discards updates."""


@dataclass
class JobContext:
    """State shared by every step of one job.

    Attributes:
        settings: The job's settings.
        cancel: Cancellation flag; steps call ``ctx.check_cancel()`` often.
        progress: Callback that receives :class:`ProgressEvent` updates.
        warnings: Non-fatal issues collected during the job.
        file_index: 1-based index of the input file being processed.
        file_count: Number of input files in the job.
    """

    settings: ActionSettings = field(default_factory=ActionSettings)
    cancel: CancelToken = field(default_factory=CancelToken)
    progress: Progress = _ignore
    warnings: list[Issue] = field(default_factory=list)
    file_index: int = 1
    file_count: int = 1

    def check_cancel(self) -> None:
        """Stop the job here if the user pressed Cancel."""
        self.cancel.check()

    def warn(self, issue: Issue) -> None:
        """Record a non-fatal problem; it is shown when the job finishes."""
        self.warnings.append(issue)

    def report(
        self,
        stage: Stage,
        message: str,
        page: int | None = None,
        page_count: int | None = None,
        within_file: float | None = None,
    ) -> None:
        """Send a progress update.

        Overall progress gives each input file an equal share. Within a file,
        ``within_file`` (0 to 1) is used if given, otherwise page / page_count.

        Args:
            stage: Current phase.
            message: Plain-language status line, e.g. "Reading text: page 3 of 12".
            page: Current page, if working page by page.
            page_count: Pages in the current file, if known.
            within_file: Progress through the current file, 0 to 1.
        """
        if within_file is None:
            within_file = (page - 1) / page_count if page and page_count else 0.0
        count = max(self.file_count, 1)
        fraction = ((self.file_index - 1) + min(max(within_file, 0.0), 1.0)) / count
        self.progress(
            ProgressEvent(
                stage, self.file_index, self.file_count, page, page_count, fraction, message
            )
        )
