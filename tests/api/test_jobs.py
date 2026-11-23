"""Tests for api.jobs: the job manager and the progress throttle, with a fake run_action."""

from __future__ import annotations

import threading
import time
import zipfile
from pathlib import Path

import pytest

from api import jobs
from api.jobs import JobManager, ProgressThrottle
from converter import pipeline
from converter.common import (
    Action,
    ActionData,
    ActionSettings,
    JobResult,
    OutputFile,
    ProgressEvent,
    Stage,
)
from converter.issues import (
    Cancelled,
    ConversionError,
    IssueCode,
    empty_pdf,
    powerpoint_fallback,
)


class Recorder:
    """Collects emitted events and signals when a job finishes."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self.finished = threading.Event()

    def __call__(self, name, payload):
        self.events.append((name, payload))
        if name == "jobFinished":
            self.finished.set()

    def named(self, name):
        """Payloads of one event type, in order."""
        return [payload for event, payload in self.events if event == name]

    def finish(self):
        """Wait for jobFinished and return its payload."""
        assert self.finished.wait(5), "job did not finish"
        return self.named("jobFinished")[-1]


def make_outputs(scratch: Path, *names: str) -> list[OutputFile]:
    """Write small output files into scratch and describe them."""
    outputs = []
    for index, name in enumerate(names):
        path = scratch / f"out_{index}.pdf"
        path.write_bytes(b"%PDF-1.4 sample " + name.encode())
        outputs.append(OutputFile(name, path, 1, path.stat().st_size))
    return outputs


def succeeding(*names, warnings=()):
    """A fake run_action that writes outputs and reports progress."""

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        progress(ProgressEvent(Stage.PREPARING, 1, 1, None, None, 0.0, "Preparing"))
        progress(ProgressEvent(Stage.FINISHING, 1, 1, None, None, 1.0, "Finishing"))
        return JobResult(make_outputs(scratch, *names), list(warnings))

    return run


@pytest.fixture
def recorder():
    return Recorder()


@pytest.fixture
def make_manager(recorder, tmp_path, logs):
    """Build a JobManager with a fake run_action and scratch under tmp_path."""
    managers = []

    def build(run, **kwargs):
        manager = JobManager(recorder, run_action=run, temp_dir=tmp_path, **kwargs)
        managers.append(manager)
        return manager

    yield build
    for manager in managers:
        manager.shutdown()


DATA = ActionData([Path("/inputs/Report.pdf"), Path("/inputs/Notes.pdf")])


def test_success_emits_progress_and_finished(make_manager, recorder):
    """A successful job reports progress and finishes with its outputs."""
    manager = make_manager(succeeding("Report - Flattened.pdf"))
    job_id = manager.start(Action.FLATTEN, ActionSettings(), DATA)
    finished = recorder.finish()
    assert finished["jobId"] == job_id
    assert finished["status"] == "succeeded"
    assert finished["outputs"][0]["name"] == "Report - Flattened.pdf"
    assert finished["error"] is None
    # The final progress update always arrives, before jobFinished.
    progress_events = recorder.named("jobProgress")
    assert progress_events[-1]["message"] == "Finishing"
    assert progress_events[-1]["jobId"] == job_id
    assert [name for name, _ in recorder.events][-1] == "jobFinished"


def test_default_run_action_is_looked_up_at_call_time(monkeypatch, recorder, tmp_path, logs):
    """Without an injected run_action, converter.pipeline.run_action is used."""
    monkeypatch.setattr(pipeline, "run_action", succeeding("a.pdf"))
    manager = JobManager(recorder, temp_dir=tmp_path)
    manager.start(Action.MERGE, ActionSettings(), DATA)
    assert recorder.finish()["status"] == "succeeded"
    manager.shutdown()


def test_warnings_are_logged_and_sent(make_manager, recorder, logs):
    """Warnings are sent with logFile set, and written to the log."""
    warning = powerpoint_fallback("Slides.pptx", "raw renderer output")
    manager = make_manager(succeeding("a.pdf", warnings=[warning]))
    manager.start(Action.FLATTEN, ActionSettings(), DATA)
    finished = recorder.finish()
    assert finished["warnings"][0]["code"] == "POWERPOINT_FALLBACK"
    assert finished["warnings"][0]["logFile"] == str(logs)
    assert "raw renderer output" in logs.read_text(encoding="utf-8")


def test_conversion_error_fails_with_its_issue(make_manager, recorder, tmp_path):
    """A ConversionError ends the job as failed with its issue; scratch is removed."""

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        raise ConversionError(empty_pdf("Report.pdf"))

    manager = make_manager(run)
    manager.start(Action.FLATTEN, ActionSettings(), DATA)
    finished = recorder.finish()
    assert finished["status"] == "failed"
    assert finished["error"]["code"] == "EMPTY_PDF"
    assert finished["error"]["logFile"]
    assert finished["outputs"] == []
    assert not list(tmp_path.glob("pdf-manager-*"))


def test_unexpected_exception_reports_traceback(make_manager, recorder, logs):
    """Any other exception becomes UNEXPECTED_ERROR with the traceback in details and log."""

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        raise KeyError("missing piece")

    manager = make_manager(run)
    manager.start(Action.SPLIT, ActionSettings(), DATA)
    finished = recorder.finish()
    assert finished["status"] == "failed"
    assert finished["error"]["code"] == "UNEXPECTED_ERROR"
    assert "KeyError" in finished["error"]["details"]
    assert "Traceback" in logs.read_text(encoding="utf-8")


def test_cancel(make_manager, recorder):
    """Cancelling a running job ends it with status cancelled."""
    started = threading.Event()

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        started.set()
        while True:
            cancel.check()  # Raises Cancelled once cancel() was called.
            time.sleep(0.01)

    manager = make_manager(run)
    job_id = manager.start(Action.FLATTEN, ActionSettings(), DATA)
    assert started.wait(5)
    assert manager.cancel(job_id)
    finished = recorder.finish()
    assert finished["status"] == "cancelled"
    assert finished["error"] is None
    assert manager.running_job() is None
    assert not manager.cancel(job_id)  # Already finished.


def test_error_after_cancel_is_reported_as_cancelled(make_manager, recorder):
    """A crash caused by stopping a program counts as cancelled, not failed."""
    started = threading.Event()

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        started.set()
        while not cancel.cancelled:
            time.sleep(0.01)
        raise RuntimeError("program was killed")

    manager = make_manager(run)
    job_id = manager.start(Action.FLATTEN, ActionSettings(), DATA)
    assert started.wait(5)
    manager.cancel(job_id)
    assert recorder.finish()["status"] == "cancelled"


def test_only_one_job_at_a_time(make_manager, recorder):
    """A second start while one runs raises JOB_ALREADY_RUNNING."""
    release = threading.Event()

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        release.wait(5)
        return JobResult(make_outputs(scratch, "a.pdf"))

    manager = make_manager(run)
    first = manager.start(Action.MERGE, ActionSettings(), DATA)
    with pytest.raises(ConversionError) as info:
        manager.start(Action.MERGE, ActionSettings(), DATA)
    assert info.value.issue.code == IssueCode.JOB_ALREADY_RUNNING
    assert manager.running_job() == first
    release.set()
    recorder.finish()
    # Once finished, a new job can start (finished results don't block).
    assert manager.start(Action.MERGE, ActionSettings(), DATA) != first


def test_each_job_gets_its_own_scratch(make_manager, recorder):
    """Scratch folders are separate, under the configured temp dir, with the app prefix."""
    seen = []

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        seen.append(scratch)
        return JobResult(make_outputs(scratch, "a.pdf"))

    manager = make_manager(run)
    for _ in range(2):
        recorder.finished.clear()
        manager.start(Action.MERGE, ActionSettings(), DATA)
        recorder.finish()
    assert len(set(seen)) == 2
    assert all(path.name.startswith("pdf-manager-") for path in seen)


def test_throttle_keeps_last_event(make_manager, recorder):
    """Many fast updates are thinned out, but the last one is always delivered."""

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        for i in range(1, 201):
            progress(ProgressEvent(Stage.OCR, 1, 1, i, 200, i / 200, f"p{i}"))
        return JobResult(make_outputs(scratch, "a.pdf"))

    manager = make_manager(run, progress_interval=60)
    manager.start(Action.FLATTEN, ActionSettings(), DATA)
    recorder.finish()
    messages = [p["message"] for p in recorder.named("jobProgress")]
    assert messages == ["p1", "p200"]


def test_progress_throttle_unit():
    """The first item goes at once; later ones within the interval collapse into the last."""
    delivered = []
    now = [0.0]
    throttle = ProgressThrottle(delivered.append, interval=60, clock=lambda: now[0])
    for i in range(5):
        throttle.submit(i)
    assert delivered == [0]
    now[0] = 61.0
    throttle.submit(5)  # Interval over: goes straight out.
    assert delivered == [0, 5]
    throttle.submit(6)
    throttle.close()
    assert delivered == [0, 5, 6]
    throttle.submit(7)  # Ignored after close.
    assert delivered == [0, 5, 6]


def test_progress_throttle_trailing_timer():
    """A pending item is delivered when the interval ends, even with no new updates."""
    delivered = []
    throttle = ProgressThrottle(delivered.append, interval=0.05)
    throttle.submit("first")
    throttle.submit("second")
    deadline = time.monotonic() + 5
    while len(delivered) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert delivered == ["first", "second"]
    throttle.close()
    assert delivered == ["first", "second"]


def test_progress_throttle_survives_broken_delivery():
    """An exception while delivering is logged, not raised into the job."""

    def broken(_):
        raise RuntimeError("window gone")

    ProgressThrottle(broken).submit("x")


def finished_job(make_manager, recorder, *names, action=Action.FLATTEN, data=DATA):
    """Run a successful job and return (manager, job id)."""
    manager = make_manager(succeeding(*names))
    job_id = manager.start(action, ActionSettings(), data)
    assert recorder.finish()["status"] == "succeeded"
    return manager, job_id


def test_save_never_overwrites(make_manager, recorder, tmp_path):
    """Existing names (and duplicates within the batch) get (2), (3)..."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "Report - Flattened.pdf").write_bytes(b"existing")
    manager, job_id = finished_job(
        make_manager, recorder, "Report - Flattened.pdf", "Report - Flattened.pdf"
    )
    saved = manager.save(job_id, out, as_zip=False)
    assert [p.name for p in saved] == ["Report - Flattened (2).pdf", "Report - Flattened (3).pdf"]
    assert (out / "Report - Flattened.pdf").read_bytes() == b"existing"
    assert all(p.read_bytes().startswith(b"%PDF") for p in saved)
    # After a successful save the results are gone from scratch.
    assert not list(tmp_path.glob("pdf-manager-*"))
    with pytest.raises(ConversionError):
        manager.save(job_id, out, as_zip=False)


def test_save_as_zip(make_manager, recorder, tmp_path):
    """as_zip writes one zip named after the first input, with unique entries."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "Report - Split.zip").write_bytes(b"existing")
    manager, job_id = finished_job(
        make_manager,
        recorder,
        "Report - Pages 1-3.pdf",
        "Report - Pages 4-5.pdf",
        "Report - Pages 4-5.pdf",
        action=Action.SPLIT,
    )
    saved = manager.save(job_id, out, as_zip=True)
    assert [p.name for p in saved] == ["Report - Split (2).zip"]
    with zipfile.ZipFile(saved[0]) as archive:
        assert archive.namelist() == [
            "Report - Pages 1-3.pdf",
            "Report - Pages 4-5.pdf",
            "Report - Pages 4-5 (2).pdf",
        ]
        assert archive.read("Report - Pages 1-3.pdf").startswith(b"%PDF")


def test_failed_save_keeps_results(make_manager, recorder, tmp_path, monkeypatch):
    """A failed save raises SAVE_FAILED, removes partial files and keeps the results."""
    out = tmp_path / "out"
    out.mkdir()
    manager, job_id = finished_job(make_manager, recorder, "a.pdf", "b.pdf")
    real_copy = jobs.shutil.copyfileobj
    calls = []

    def flaky_copy(src, dst, length=0):
        calls.append(1)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        real_copy(src, dst, length)

    monkeypatch.setattr(jobs.shutil, "copyfileobj", flaky_copy)
    with pytest.raises(ConversionError) as info:
        manager.save(job_id, out, as_zip=False)
    assert info.value.issue.code == IssueCode.SAVE_FAILED
    assert "No space left" in info.value.issue.details
    assert list(out.iterdir()) == []  # The first, completed copy was rolled back too.
    monkeypatch.setattr(jobs.shutil, "copyfileobj", real_copy)
    # Results were kept, so a retry works.
    assert [p.name for p in manager.save(job_id, out, as_zip=False)] == ["a.pdf", "b.pdf"]


def test_save_to_missing_folder_fails(make_manager, recorder, tmp_path):
    """Saving into a folder that doesn't exist is SAVE_FAILED, results kept."""
    manager, job_id = finished_job(make_manager, recorder, "a.pdf")
    with pytest.raises(ConversionError) as info:
        manager.save(job_id, tmp_path / "missing", as_zip=False)
    assert info.value.issue.code == IssueCode.SAVE_FAILED
    assert len(list(tmp_path.glob("pdf-manager-*"))) == 1


def test_save_unknown_job_fails(make_manager):
    """An unknown job id can't be saved."""
    manager = make_manager(succeeding("a.pdf"))
    with pytest.raises(ConversionError) as info:
        manager.save("nope", Path("."), as_zip=False)
    assert info.value.issue.code == IssueCode.SAVE_FAILED


def test_discard(make_manager, recorder, tmp_path):
    """discard deletes the scratch folder; unknown ids are ignored."""
    manager, job_id = finished_job(make_manager, recorder, "a.pdf")
    assert len(list(tmp_path.glob("pdf-manager-*"))) == 1
    manager.discard(job_id)
    assert not list(tmp_path.glob("pdf-manager-*"))
    manager.discard(job_id)  # No-op.
    manager.discard("unknown")


def test_shutdown_cancels_and_cleans_up(make_manager, recorder, tmp_path):
    """shutdown cancels the running job and removes every scratch folder."""
    manager, _ = finished_job(make_manager, recorder, "a.pdf")
    started = threading.Event()

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        started.set()
        while True:
            cancel.check()
            time.sleep(0.01)

    manager._run_action = run
    recorder.finished.clear()
    running = manager.start(Action.FLATTEN, ActionSettings(), DATA)
    assert started.wait(5)
    manager.shutdown(timeout=5)
    assert manager.wait(running, 5)
    assert recorder.finish()["status"] == "cancelled"
    assert not list(tmp_path.glob("pdf-manager-*"))


def test_cancelled_raised_directly(make_manager, recorder):
    """Cancelled raised by run_action is reported as cancelled."""

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        raise Cancelled()

    manager = make_manager(run)
    manager.start(Action.COMPRESS, ActionSettings(), DATA)
    assert recorder.finish()["status"] == "cancelled"
