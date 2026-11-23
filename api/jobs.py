"""Running conversion jobs: one at a time, on a worker thread, with progress and cancel.

Each job gets its own scratch folder and a worker thread that calls the
service layer's single entry point, ``converter.pipeline.run_action``. When
the job ends, ``jobFinished`` is emitted. Results stay in the scratch folder
until :meth:`JobManager.save` or :meth:`JobManager.discard` (decision F12:
cancelling the folder picker never loses results). Every scratch folder is
removed on :meth:`JobManager.shutdown`.

The manager knows nothing about pywebview: it emits events through a plain
``emit(name, payload)`` callback supplied by the bridge.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from converter import pipeline
from converter.common import Action, ActionData, ActionSettings, OutputFile, ProgressEvent
from converter.context import CancelToken
from converter.issues import (
    Cancelled,
    ConversionError,
    Issue,
    job_already_running,
    save_failed,
    unexpected_error,
)
from converter.output import safe_destination

from . import dto
from .logging_setup import log_issue

log = logging.getLogger(__name__)

# emit(event name, JSON payload); see the Events table in docs/API.md.
Emit = Callable[[str, dict], None]

# At most this many progress events per second reach the UI (the last one always does).
PROGRESS_INTERVAL_SEC = 0.1
SCRATCH_PREFIX = "pdf-manager-"
RUNNING = "running"

# Used in zip names: "<first input name> - <label>.zip".
ZIP_LABELS: dict[Action, str] = {
    Action.FLATTEN: "Flattened",
    Action.FLATTEN_MERGE: "Flattened Merged",
    Action.MERGE: "Merged",
    Action.SPLIT: "Split",
    Action.IMAGES_TO_PDF: "Images",
    Action.COMPRESS: "Compressed",
}


class ProgressThrottle:
    """Pass on at most one item per interval, without ever losing the latest one.

    The first item is delivered at once. Items arriving within the interval
    replace each other as "pending"; a timer delivers the pending item when
    the interval ends, so the UI is never left showing a stale status while a
    slow page runs. :meth:`close` delivers whatever is still pending, so the
    final progress update always arrives before ``jobFinished``.

    Args:
        deliver: Called with each item that is passed on. Exceptions are logged.
        interval: Minimum seconds between deliveries.
        clock: Monotonic clock (injectable for tests).
    """

    def __init__(
        self,
        deliver: Callable[[Any], None],
        interval: float = PROGRESS_INTERVAL_SEC,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._deliver = deliver
        self._interval = interval
        self._clock = clock
        self._lock = threading.Lock()
        self._last: float | None = None  # Clock time of the last delivery.
        self._pending: Any = None
        self._has_pending = False
        self._timer: threading.Timer | None = None
        self._closed = False

    def submit(self, item: Any) -> None:
        """Offer an item; it is delivered now or later, or replaced by a newer one. Never raises."""
        with self._lock:
            if self._closed:
                return
            now = self._clock()
            if self._last is None or now - self._last >= self._interval:
                self._send(item, now)
                return
            self._pending, self._has_pending = item, True
            if self._timer is None:
                # Deliver the pending item when the interval is over.
                delay = max(self._interval - (now - self._last), 0.0)
                self._timer = threading.Timer(delay, self._on_timer)
                self._timer.daemon = True
                self._timer.start()

    def close(self) -> None:
        """Deliver the pending item, if any, and stop accepting new ones."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._has_pending and not self._closed:
                self._send(self._pending, self._clock())
            self._closed = True

    def _on_timer(self) -> None:
        """Timer callback: deliver the pending item."""
        with self._lock:
            self._timer = None
            if self._has_pending and not self._closed:
                self._send(self._pending, self._clock())

    def _send(self, item: Any, now: float) -> None:
        """Deliver an item (lock held, so deliveries stay in order)."""
        self._last = now
        self._pending, self._has_pending = None, False
        try:
            self._deliver(item)
        except Exception:  # A broken progress display must never stop the job.
            log.exception("Couldn't deliver a progress update")


@dataclass
class _Job:
    """One job's state. Only the manager touches it, under its lock."""

    id: str
    action: Action
    data: ActionData
    scratch: Path
    cancel: CancelToken = field(default_factory=CancelToken)
    thread: threading.Thread | None = None
    status: str = RUNNING  # Then dto.SUCCEEDED, dto.FAILED or dto.CANCELLED.
    outputs: list[OutputFile] = field(default_factory=list)


def _remove_tree(path: Path) -> None:
    """Delete a scratch folder, ignoring errors.

    Known issue: on Windows a just-closed file can stay locked for a moment
    (antivirus, the search indexer), so a folder may survive; it is in the
    system temp folder, which Windows cleans up over time.
    """
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        log.debug("Scratch folder not fully removed (probably locked): %s", path)


class JobManager:
    """Runs one job at a time and keeps finished results until saved or discarded.

    Args:
        emit: ``emit(name, payload)`` for ``jobProgress`` and ``jobFinished``.
        run_action: The service entry point; defaults to
            ``converter.pipeline.run_action`` (looked up at call time).
        progress_interval: Minimum seconds between progress events.
        temp_dir: Parent folder for scratch folders (default: system temp).
    """

    def __init__(
        self,
        emit: Emit,
        *,
        run_action: Callable[..., Any] | None = None,
        progress_interval: float = PROGRESS_INTERVAL_SEC,
        temp_dir: Path | None = None,
    ):
        self._emit = emit
        self._run_action = run_action
        self._progress_interval = progress_interval
        self._temp_dir = temp_dir
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()  # One save at a time.
        self._jobs: dict[str, _Job] = {}

    def running_job(self) -> str | None:
        """Return the id of the running job, or ``None`` if none is running."""
        with self._lock:
            return next((j.id for j in self._jobs.values() if j.status == RUNNING), None)

    def start(self, action: Action, settings: ActionSettings, data: ActionData) -> str:
        """Start a job on a worker thread.

        Args:
            action: What to do.
            settings: Full service-layer settings.
            data: Input files in the user's order.

        Returns:
            The new job's id.

        Raises:
            ConversionError: Another job is still running (``JOB_ALREADY_RUNNING``),
                or the scratch folder couldn't be created.
        """
        with self._lock:
            if any(j.status == RUNNING for j in self._jobs.values()):
                raise ConversionError(job_already_running())
            try:
                scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=self._temp_dir))
            except OSError as exc:
                raise ConversionError(unexpected_error(f"Couldn't create a work folder: {exc}"))
            job = _Job(uuid.uuid4().hex, action, data, scratch)
            job.thread = threading.Thread(
                target=self._work,
                args=(job, settings),
                name=f"job-{job.id[:8]}",
                daemon=True,  # Never keep the app alive after the window closes.
            )
            self._jobs[job.id] = job
        log.info("Job %s started: %s, %d file(s)", job.id, action, len(data.files))
        log.debug(
            "Job %s settings: %s; saved: dpi=%s lang=%s timeout=%s tesseract=%s; files: %s",
            job.id,
            dto.action_settings_to_json(settings),
            settings.dpi,
            settings.ocr_language,
            settings.ocr_page_timeout_sec,
            settings.tesseract_path,
            [str(f) for f in data.files],
        )
        job.thread.start()
        return job.id

    def cancel(self, job_id: str) -> bool:
        """Ask a running job to stop. It then ends with status ``"cancelled"``.

        Args:
            job_id: The job.

        Returns:
            True if a running job was told to stop.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != RUNNING:
                log.info("Cancel ignored: job %s isn't running", job_id)
                return False
        log.info("Cancelling job %s", job_id)
        job.cancel.cancel()  # Outside the lock: it may kill a running program.
        return True

    def wait(self, job_id: str, timeout: float | None = None) -> bool:
        """Wait for a job's worker thread to end.

        Args:
            job_id: The job.
            timeout: Seconds to wait, or ``None`` for no limit.

        Returns:
            True if the job is no longer running.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.thread is None:
            return True
        job.thread.join(timeout)
        return not job.thread.is_alive()

    def _call_run_action(self, job: _Job, settings: ActionSettings, progress) -> Any:
        """Call the service entry point (resolved now, so tests can replace it)."""
        run = self._run_action or pipeline.run_action
        return run(
            job.action,
            settings,
            job.data,
            scratch=job.scratch,
            progress=progress,
            cancel=job.cancel,
        )

    def _work(self, job: _Job, settings: ActionSettings) -> None:
        """Worker thread: run the job, then record the result and emit ``jobFinished``.

        Never raises: every outcome becomes a ``jobFinished`` event.
        """

        def deliver(event: ProgressEvent) -> None:
            self._emit("jobProgress", dto.progress_to_json(job.id, event))

        throttle = ProgressThrottle(deliver, self._progress_interval)
        started = time.monotonic()
        outputs: list[OutputFile] = []
        warnings: list[Issue] = []
        error: Issue | None = None
        try:
            result = self._call_run_action(job, settings, throttle.submit)
            outputs, warnings, status = list(result.outputs), list(result.warnings), dto.SUCCEEDED
        except Cancelled:
            status = dto.CANCELLED
        except ConversionError as exc:
            if job.cancel.cancelled:
                # Stopping a program mid-run can surface as a conversion error;
                # the user asked to stop, so report it as cancelled.
                log.info("Job %s failed after cancel; reporting cancelled: %s", job.id, exc)
                status = dto.CANCELLED
            else:
                status, error = dto.FAILED, log_issue(exc.issue, exc)
        except Exception as exc:  # A bug: report it as unexpected, with the traceback.
            if job.cancel.cancelled:
                log.info("Job %s raised after cancel; reporting cancelled", job.id, exc_info=True)
                status = dto.CANCELLED
            else:
                status = dto.FAILED
                error = log_issue(unexpected_error(traceback.format_exc()), exc)
        finally:
            throttle.close()  # The last progress update goes out before jobFinished.
        warnings = [log_issue(w) for w in warnings]
        with self._lock:
            job.status, job.outputs = status, outputs
        log.info(
            "Job %s %s after %.1fs with %d output(s) and %d warning(s)",
            job.id,
            status,
            time.monotonic() - started,
            len(outputs),
            len(warnings),
        )
        if status != dto.SUCCEEDED:
            _remove_tree(job.scratch)  # Nothing worth keeping.
        payload = dto.job_finished_json(job.id, status, outputs, warnings, error)
        try:
            self._emit("jobFinished", payload)
        except Exception:
            log.exception("Couldn't send jobFinished for job %s", job.id)

    def _finished_job(self, job_id: str) -> _Job:
        """Look up a job whose results can be saved.

        Raises:
            ConversionError: ``SAVE_FAILED`` if the job is unknown, still
                running, failed, or its results were already saved or discarded.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ConversionError(save_failed(f"No results found for job {job_id}."))
        if job.status != dto.SUCCEEDED or not job.outputs:
            raise ConversionError(save_failed(f"Job {job_id} has no results ({job.status})."))
        return job

    def save(self, job_id: str, folder: Path, as_zip: bool) -> list[Path]:
        """Copy a finished job's results into a folder, never overwriting anything.

        Names that already exist get `` (2)``, `` (3)`` and so on
        (:func:`converter.output.safe_destination`). With ``as_zip``, all
        outputs go into one ``.zip`` named after the first input file, for
        example ``"Report - Split.zip"``. After a successful save the scratch
        folder is deleted; after a failed one, results are kept so the user
        can try again, and any files written by the failed attempt are removed.

        Args:
            job_id: The finished job.
            folder: Destination folder; must exist.
            as_zip: Save everything as one zip file.

        Returns:
            Full paths written.

        Raises:
            ConversionError: ``SAVE_FAILED`` (results are kept).
        """
        with self._save_lock:
            job = self._finished_job(job_id)
            if not folder.is_dir():
                raise ConversionError(save_failed(f"Folder not found: {folder}"))
            written: list[Path] = []
            try:
                if as_zip:
                    written.append(self._write_zip(job, folder))
                else:
                    reserved: set[str] = set()
                    for output in job.outputs:
                        written.append(_copy_new(output.path, folder, output.name, reserved))
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                for path in written:
                    path.unlink(missing_ok=True)
                raise ConversionError(save_failed(f"{type(exc).__name__}: {exc}")) from exc
            with self._lock:
                self._jobs.pop(job_id, None)
            _remove_tree(job.scratch)
            log.info("Job %s saved: %s", job_id, [str(p) for p in written])
            return written

    def _write_zip(self, job: _Job, folder: Path) -> Path:
        """Write all outputs of a job into one new zip file in ``folder``.

        Raises:
            OSError: Writing failed (the partial zip is removed).
            RuntimeError: No free file name.
        """
        stem = job.data.files[0].stem if job.data.files else Path(job.outputs[0].name).stem
        zip_name = f"{stem} - {ZIP_LABELS.get(job.action, 'Results')}.zip"
        # Entry names must be unique inside the zip too. safe_destination is
        # pointed at a folder that doesn't exist, so only `names` decides.
        names: set[str] = set()
        no_folder = job.scratch / ".zip-entries"
        for _ in range(3):  # Retry if another program grabs the name meanwhile.
            target = safe_destination(folder, zip_name)
            try:
                handle = open(target, "xb")  # "x": never overwrite, even in a race.
            except FileExistsError:
                continue
            try:
                with handle, zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
                    for output in job.outputs:
                        entry = safe_destination(no_folder, output.name, names).name
                        archive.write(output.path, entry)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            return target
        raise RuntimeError(f"Could not choose a unique name for {zip_name}.")

    def discard(self, job_id: str) -> None:
        """Delete a finished job's results. Unknown or running jobs are ignored.

        Args:
            job_id: The job.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job.status == RUNNING:
                log.info("Discard ignored: job %s is still running", job_id)
                return
            self._jobs.pop(job_id)
        _remove_tree(job.scratch)
        log.info("Job %s results discarded", job_id)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cancel a running job and delete every scratch folder. Never raises.

        Args:
            timeout: Seconds to wait for a running job to stop.
        """
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
        for job in jobs:
            if job.status == RUNNING:
                log.info("Shutting down: cancelling job %s", job.id)
                job.cancel.cancel()
                if job.thread is not None and job.thread.is_alive():
                    job.thread.join(timeout)
        for job in jobs:
            _remove_tree(job.scratch)


def _copy_new(source: Path, folder: Path, name: str, reserved: set[str]) -> Path:
    """Copy one file into ``folder`` under a collision-safe name, never overwriting.

    Args:
        source: File in scratch.
        folder: Destination folder.
        name: Suggested file name.
        reserved: Names already used in this save batch (see safe_destination).

    Returns:
        The path written.

    Raises:
        OSError: The copy failed (a partial file is removed).
        RuntimeError: No free file name.
    """
    for _ in range(3):  # Retry if another program grabs the name meanwhile.
        target = safe_destination(folder, name, reserved)
        try:
            handle = open(target, "xb")  # "x": fail instead of overwriting.
        except FileExistsError:
            continue
        try:
            with handle, open(source, "rb") as src:
                shutil.copyfileobj(src, handle, 1024 * 1024)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target
    raise RuntimeError(f"Could not choose a unique name for {name}.")
