"""Tests for api.jobs: the job manager and the progress throttle, with a fake run_action."""

from __future__ import annotations

import threading
import time
import zipfile
from pathlib import Path

import pytest

from api import jobs, service
from api.jobs import JobManager, ProgressThrottle
from api.service import (
    Action,
    ActionData,
    ActionSettings,
    Cancelled,
    ConversionError,
    IssueCode,
    JobResult,
    OutputFile,
    ProgressEvent,
    Stage,
)

empty_pdf = service.issues.empty_pdf


def file_warning(file: str, details: str | None) -> service.Issue:
    """A warning about one input file (a job may return such warnings with its results)."""
    return service.Issue(
        IssueCode.OCR_FAILED,
        service.issues.Severity.WARNING,
        "One page wasn't read",
        "Its text isn't searchable.",
        (),
        details,
        file,
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
    """Without an injected run_action, the service run_action is used."""
    monkeypatch.setattr(service, "run_action", succeeding("a.pdf"))
    manager = JobManager(recorder, temp_dir=tmp_path)
    manager.start(Action.MERGE, ActionSettings(), DATA)
    assert recorder.finish()["status"] == "succeeded"
    manager.shutdown()


def test_warnings_are_logged_and_sent(make_manager, recorder, logs):
    """Warnings are sent with logFile set, and written to the log."""
    warning = file_warning("Slides.pptx", "raw renderer output")
    manager = make_manager(succeeding("a.pdf", warnings=[warning]))
    manager.start(Action.FLATTEN, ActionSettings(), DATA)
    finished = recorder.finish()
    assert finished["warnings"][0]["code"] == "OCR_FAILED"
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
    real_copy = jobs._copy_stream
    calls = []

    def flaky_copy(src, dst, abort):
        calls.append(1)
        if len(calls) == 2:
            dst.write(b"%PDF-partial")  # Half a file, then the disk is full.
            raise OSError(28, "No space left on device")
        real_copy(src, dst, abort)

    monkeypatch.setattr(jobs, "_copy_stream", flaky_copy)
    with pytest.raises(ConversionError) as info:
        manager.save(job_id, out, as_zip=False)
    assert info.value.issue.code == IssueCode.SAVE_FAILED
    assert "No space left" in info.value.issue.details
    assert list(out.iterdir()) == []  # The first, completed copy was rolled back too.
    monkeypatch.setattr(jobs, "_copy_stream", real_copy)
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


def test_discard_after_save_is_a_no_op(make_manager, recorder, tmp_path):
    """The UI discards when the results are closed, even after saving: that must be safe."""
    out = tmp_path / "out"
    out.mkdir()
    manager, job_id = finished_job(make_manager, recorder, "a.pdf")
    saved = manager.save(job_id, out, as_zip=False)
    manager.discard(job_id)
    manager.discard(job_id)
    assert saved[0].is_file()  # Saved files are never touched by discard.


def test_new_stage_values_pass_through(make_manager, recorder):
    """Stage values are sent as their strings, so new service stages need no API change."""

    def run(action, settings, data, *, scratch, progress=None, cancel=None):
        stage = getattr(Stage, "CONVERTING_IMAGES", Stage.FINISHING)
        progress(ProgressEvent(stage, 1, 1, None, None, 0.5, "Converting images"))
        return JobResult(make_outputs(scratch, "a.pdf"))

    manager = make_manager(run)
    manager.start(Action.IMAGES_TO_PDF, ActionSettings(), DATA)
    recorder.finish()
    expected = getattr(Stage, "CONVERTING_IMAGES", Stage.FINISHING).value
    assert recorder.named("jobProgress")[-1]["stage"] == expected


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


# ----- Save, discard and shutdown at the same time (audit R4) -----
#
# Every test below is ordered with events, never sleeps: a patched copy writes
# half of a file and then blocks, so a discard or shutdown arrives exactly
# mid-copy.


class BlockingCopy:
    """Replaces ``jobs._copy_stream``: the ``block_on``-th copy stops halfway.

    It writes the first half of the file, sets ``mid_copy`` and waits, either
    for ``release`` or, with ``until_abort``, for the save to be aborted. Then
    the real copy finishes the rest (and raises SaveAborted if aborted).
    With ``fail``, it raises OSError instead of finishing.
    """

    def __init__(self, block_on=1, until_abort=False, fail=False):
        self.real = jobs._copy_stream
        self.block_on = block_on
        self.until_abort = until_abort
        self.fail = fail
        self.calls = 0
        self.mid_copy = threading.Event()
        self.release = threading.Event()

    def __call__(self, src, dst, abort):
        self.calls += 1
        if self.calls == self.block_on:
            data = src.read()
            dst.write(data[: len(data) // 2])
            src.seek(len(data) // 2)
            self.mid_copy.set()
            assert (abort if self.until_abort else self.release).wait(5)
            if self.fail:
                raise OSError(28, "No space left on device")
        self.real(src, dst, abort)


class SaveThread(threading.Thread):
    """Runs ``manager.save`` on its own thread (like a bridge call) and keeps the outcome."""

    def __init__(self, manager, job_id, folder, as_zip=False):
        super().__init__(daemon=True)
        self.manager, self.job_id, self.folder, self.as_zip = manager, job_id, folder, as_zip
        self.saved = None
        self.error = None

    def run(self):
        try:
            self.saved = self.manager.save(self.job_id, self.folder, as_zip=self.as_zip)
        except ConversionError as exc:
            self.error = exc

    def outcome(self):
        """Wait for the save to end and return (saved paths, ConversionError)."""
        self.join(5)
        assert not self.is_alive(), "save did not finish"
        return self.saved, self.error


def expected_contents(*names):
    """The bytes make_outputs writes for each output name."""
    return [b"%PDF-1.4 sample " + name.encode() for name in names]


def assert_complete(saved, as_zip, names):
    """The saved files (or zip entries) hold exactly the full outputs."""
    if as_zip:
        assert len(saved) == 1
        with zipfile.ZipFile(saved[0]) as archive:
            assert archive.testzip() is None
            assert [archive.read(n) for n in archive.namelist()] == expected_contents(*names)
    else:
        assert [p.read_bytes() for p in saved] == expected_contents(*names)


def scratch_folders(tmp_path):
    """The job scratch folders that still exist."""
    return list(tmp_path.glob("pdf-manager-*"))


def wait_state(manager, predicate):
    """Block until predicate() holds; the manager signals every state change."""
    with manager._changed:
        assert manager._changed.wait_for(predicate, 5)


@pytest.mark.parametrize("as_zip", [False, True])
def test_discard_during_save_is_applied_after_it(
    make_manager, recorder, tmp_path, monkeypatch, as_zip
):
    """A discard (twice, even) mid-copy waits for the save; the saved files are complete."""
    out = tmp_path / "out"
    out.mkdir()
    names = ("a.pdf", "b.pdf")
    manager, job_id = finished_job(make_manager, recorder, *names, action=Action.SPLIT)
    job = manager._jobs[job_id]
    copy = BlockingCopy(block_on=2)
    monkeypatch.setattr(jobs, "_copy_stream", copy)
    save = SaveThread(manager, job_id, out, as_zip)
    save.start()
    assert copy.mid_copy.wait(5)
    manager.discard(job_id)  # Returns at once: deferred until the save ends.
    manager.discard(job_id)
    assert job.drop_requested
    assert all(output.path.is_file() for output in job.outputs)  # Nothing deleted mid-copy.
    copy.release.set()
    saved, error = save.outcome()
    assert error is None
    assert_complete(saved, as_zip, names)
    assert not scratch_folders(tmp_path)
    with pytest.raises(ConversionError) as info:
        manager.save(job_id, out, as_zip=as_zip)
    assert "No results found" in info.value.issue.details


def test_discard_during_failed_save_leaves_nothing_behind(
    make_manager, recorder, tmp_path, monkeypatch
):
    """If the save fails after a discard was requested, its files and the results are removed."""
    out = tmp_path / "out"
    out.mkdir()
    manager, job_id = finished_job(make_manager, recorder, "a.pdf", "b.pdf")
    copy = BlockingCopy(block_on=2, fail=True)
    monkeypatch.setattr(jobs, "_copy_stream", copy)
    save = SaveThread(manager, job_id, out)
    save.start()
    assert copy.mid_copy.wait(5)
    manager.discard(job_id)
    assert len(scratch_folders(tmp_path)) == 1
    copy.release.set()
    saved, error = save.outcome()
    assert error.issue.code == IssueCode.SAVE_FAILED
    assert list(out.iterdir()) == []  # Neither the complete first file nor the partial one.
    assert not scratch_folders(tmp_path)  # The discard was applied after the save.


def test_save_after_discard_reports_results_gone(make_manager, recorder, tmp_path):
    """Saving discarded results is the usual SAVE_FAILED "no results" issue."""
    out = tmp_path / "out"
    out.mkdir()
    manager, job_id = finished_job(make_manager, recorder, "a.pdf")
    manager.discard(job_id)
    with pytest.raises(ConversionError) as info:
        manager.save(job_id, out, as_zip=False)
    assert info.value.issue.code == IssueCode.SAVE_FAILED
    assert info.value.issue.details == f"No results found for job {job_id}."
    assert list(out.iterdir()) == []


def test_concurrent_discards_delete_once(make_manager, recorder, tmp_path, monkeypatch):
    """A second discard while the first is deleting is a no-op, not a second delete."""
    manager, job_id = finished_job(make_manager, recorder, "a.pdf")
    real_remove = jobs._remove_tree
    removing = threading.Event()
    release = threading.Event()
    removed = []

    def slow_remove(path):
        removed.append(path)
        removing.set()
        assert release.wait(5)
        real_remove(path)

    monkeypatch.setattr(jobs, "_remove_tree", slow_remove)
    first = threading.Thread(target=manager.discard, args=(job_id,), daemon=True)
    first.start()
    assert removing.wait(5)
    manager.discard(job_id)  # Returns at once: the job is already gone.
    assert len(removed) == 1
    release.set()
    first.join(5)
    assert not first.is_alive()
    assert len(removed) == 1
    assert not scratch_folders(tmp_path)


@pytest.mark.parametrize("as_zip", [False, True])
def test_shutdown_during_save_waits_for_it(make_manager, recorder, tmp_path, monkeypatch, as_zip):
    """Shutdown mid-copy lets the save finish, then deletes the scratch folder."""
    out = tmp_path / "out"
    out.mkdir()
    names = ("a.pdf", "b.pdf")
    manager, job_id = finished_job(make_manager, recorder, *names, action=Action.SPLIT)
    job = manager._jobs[job_id]
    copy = BlockingCopy(block_on=2)
    monkeypatch.setattr(jobs, "_copy_stream", copy)
    save = SaveThread(manager, job_id, out, as_zip)
    save.start()
    assert copy.mid_copy.wait(5)
    shutdown = threading.Thread(target=manager.shutdown, kwargs={"timeout": 5}, daemon=True)
    shutdown.start()
    wait_state(manager, lambda: job.drop_requested)  # Shutdown has seen the save...
    assert all(output.path.is_file() for output in job.outputs)  # ...and deleted nothing.
    copy.release.set()
    saved, error = save.outcome()
    shutdown.join(5)
    assert not shutdown.is_alive()
    assert error is None
    assert_complete(saved, as_zip, names)
    assert not job.abort.is_set()  # It finished in time, so it wasn't aborted.
    assert not scratch_folders(tmp_path)


@pytest.mark.parametrize("as_zip", [False, True])
def test_shutdown_aborts_a_slow_save_and_rolls_it_back(
    make_manager, recorder, tmp_path, monkeypatch, as_zip
):
    """A save still copying when the shutdown timeout ends is aborted: no partial files remain."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_bytes(b"user file")
    manager, job_id = finished_job(make_manager, recorder, "a.pdf", "b.pdf", action=Action.SPLIT)
    job = manager._jobs[job_id]
    copy = BlockingCopy(block_on=2, until_abort=True)  # Never finishes unless aborted.
    monkeypatch.setattr(jobs, "_copy_stream", copy)
    save = SaveThread(manager, job_id, out, as_zip)
    save.start()
    assert copy.mid_copy.wait(5)
    manager.shutdown(timeout=0.01)  # The first wait runs out (the copy is blocked): abort.
    saved, error = save.outcome()
    assert job.abort.is_set()
    assert saved is None
    assert error.issue.code == IssueCode.SAVE_FAILED
    assert "SaveAborted" in error.issue.details
    assert [p.name for p in out.iterdir()] == ["keep.txt"]  # Partial and completed files gone.
    assert (out / "keep.txt").read_bytes() == b"user file"
    assert not scratch_folders(tmp_path)  # The save removed it once it had stopped.


def test_save_after_shutdown_reports_results_gone(make_manager, recorder, tmp_path):
    """After shutdown, saving is the usual "no results" issue and writes nothing."""
    out = tmp_path / "out"
    out.mkdir()
    manager, job_id = finished_job(make_manager, recorder, "a.pdf")
    manager.shutdown()
    with pytest.raises(ConversionError) as info:
        manager.save(job_id, out, as_zip=False)
    assert "No results found" in info.value.issue.details
    assert list(out.iterdir()) == []
    assert not scratch_folders(tmp_path)


def test_save_with_keep_leaves_results_for_another_save(make_manager, recorder, tmp_path):
    """keep=True (browser download copies): the results stay until saved or discarded."""
    first, second = tmp_path / "copy", tmp_path / "out"
    first.mkdir()
    second.mkdir()
    manager, job_id = finished_job(make_manager, recorder, "a.pdf")
    kept = manager.save(job_id, first, as_zip=False, keep=True)
    assert [p.name for p in kept] == ["a.pdf"] and scratch_folders(tmp_path)
    saved = manager.save(job_id, second, as_zip=False)
    assert [p.name for p in saved] == ["a.pdf"] and not scratch_folders(tmp_path)


def test_no_new_job_after_shutdown(make_manager, recorder, tmp_path):
    """Once shut down, the manager refuses new jobs and leaves no scratch folder."""
    manager = make_manager(succeeding("a.pdf"))
    manager.shutdown()
    with pytest.raises(ConversionError) as info:
        manager.start(Action.FLATTEN, ActionSettings(), DATA)
    assert "closing" in info.value.issue.details
    assert not scratch_folders(tmp_path)


def test_unsaved_jobs_are_succeeded_results_not_yet_saved_or_delivered(make_manager, recorder):
    """Decision P35: what idle shutdown and Quit must not silently lose."""
    manager = make_manager(succeeding("a.pdf"))
    assert manager.unsaved_jobs() == []
    first = manager.start(Action.FLATTEN, ActionSettings(), DATA)
    recorder.finish()
    assert manager.unsaved_jobs() == [first]
    # A failed save keeps them unsaved.
    with pytest.raises(service.ConversionError):
        manager.save(first, Path("/no/such/folder"), False)
    assert manager.unsaved_jobs() == [first]


def test_a_folder_save_or_a_delivered_copy_ends_unsaved(make_manager, recorder, tmp_path):
    manager = make_manager(succeeding("a.pdf"))
    out = tmp_path / "out"
    out.mkdir()
    saved = manager.start(Action.FLATTEN, ActionSettings(), DATA)
    recorder.finish()
    recorder.finished.clear()
    manager.save(saved, out, False)
    assert manager.unsaved_jobs() == []
    delivered = manager.start(Action.FLATTEN, ActionSettings(), DATA)
    recorder.finish()
    manager.save(delivered, out, False, keep=True)  # A browser download's copy.
    assert manager.unsaved_jobs() == []
    assert manager.save(delivered, out, False, keep=True)  # Download again still works.


def test_failed_and_cancelled_jobs_are_never_unsaved(make_manager, recorder):
    def failing(action, settings, data, *, scratch, progress=None, cancel=None):
        raise service.ConversionError(service.unexpected_error("boom"))

    manager = make_manager(failing)
    manager.start(Action.FLATTEN, ActionSettings(), DATA)
    recorder.finish()
    assert manager.unsaved_jobs() == []
