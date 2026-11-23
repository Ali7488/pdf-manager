"""Tests for api.settings_store: defaults, validation, damaged files and atomic saves."""

import errno
import json
import os
import threading
from pathlib import Path

import pytest

from api import settings_store
from api.service import IssueCode, Severity
from api.settings_store import DEFAULTS, SettingsStore, validate_patch


@pytest.fixture
def store(tmp_path):
    """A store whose file lives in a not-yet-existing folder."""
    return SettingsStore(tmp_path / "config" / "settings.json")


def test_defaults_when_file_missing(store):
    """First launch: no file, contract defaults."""
    assert store.load() == {
        "theme": "system",
        "defaultSaveFolder": None,
        "dpi": 200,
        "ocrLanguage": "eng",
        "ocrPageTimeoutSec": 120,
        "tesseractPath": None,
    }


def test_corrupt_file_falls_back_to_defaults(store, caplog):
    """A damaged file is logged and replaced by defaults."""
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    assert store.load() == DEFAULTS
    assert "unreadable" in caplog.text


def test_non_object_file_falls_back_to_defaults(store):
    """A JSON file that isn't an object is ignored."""
    store.path.parent.mkdir(parents=True)
    store.path.write_text("[1, 2]", encoding="utf-8")
    assert store.load() == DEFAULTS


def test_invalid_saved_values_reset_individually(store, caplog):
    """Only the invalid fields fall back to defaults."""
    store.path.parent.mkdir(parents=True)
    saved = {"theme": "dark", "dpi": "high", "ocrPageTimeoutSec": 5, "extra": 1}
    store.path.write_text(json.dumps(saved), encoding="utf-8")
    loaded = store.load()
    assert loaded["theme"] == "dark"
    assert loaded["dpi"] == 200
    assert loaded["ocrPageTimeoutSec"] == 120
    assert "extra" not in loaded
    assert "unknown setting 'extra'" in caplog.text


@pytest.mark.parametrize(
    ("patch", "accepted"),
    [
        ({"theme": "green"}, True),
        ({"theme": "blue"}, False),
        ({"dpi": 300}, True),
        ({"dpi": 300.0}, True),
        ({"dpi": 300.5}, False),
        ({"dpi": True}, False),
        ({"dpi": 10}, False),
        ({"dpi": 5000}, False),
        ({"ocrLanguage": "eng+deu"}, True),
        ({"ocrLanguage": "chi_sim"}, True),
        ({"ocrLanguage": "eng; rm -rf"}, False),
        ({"ocrLanguage": 3}, False),
        ({"ocrPageTimeoutSec": 60}, True),
        ({"ocrPageTimeoutSec": 0}, False),
        ({"defaultSaveFolder": "C:\\Users\\Example\\Documents"}, True),
        ({"defaultSaveFolder": None}, True),
        ({"defaultSaveFolder": 12}, False),
        ({"tesseractPath": None}, True),
        ({"tesseractPath": ["x"]}, False),
    ],
)
def test_validate_patch(patch, accepted):
    """Each field is type- and range-checked."""
    valid, problems = validate_patch(patch)
    assert (valid != {}) is accepted
    assert (problems == []) is accepted


def test_validate_patch_rejects_non_object():
    """A patch must be an object."""
    assert validate_patch("dark") == ({}, ["settings must be an object, got str"])


def test_empty_path_is_stored_as_none(store):
    """An empty default folder means "not set"."""
    store.load()
    assert store.update({"defaultSaveFolder": "  "}).settings["defaultSaveFolder"] is None


def test_update_merges_persists_and_skips_invalid(store):
    """update() applies valid fields, skips invalid ones and writes the file."""
    store.load()
    update = store.update({"theme": "dark", "dpi": "lots", "ocrLanguage": "deu"})
    assert update.issue is None
    result = update.settings
    assert result["theme"] == "dark"
    assert result["dpi"] == 200
    assert result["ocrLanguage"] == "deu"
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    assert on_disk == result
    # A fresh store reads the same values back.
    assert SettingsStore(store.path).load() == result


def test_get_returns_a_copy(store):
    """Callers can't change the stored settings by mutating the result."""
    store.load()
    store.get()["theme"] = "dark"
    assert store.get()["theme"] == "system"


def test_atomic_write_keeps_old_file_on_failure(store, monkeypatch):
    """If the final replace fails, the old file is intact and no temp file is left."""
    store.load()
    store.update({"theme": "light"})
    before = store.path.read_text(encoding="utf-8")

    def broken_replace(src, dst):
        raise PermissionError("file is locked")

    monkeypatch.setattr(settings_store.os, "replace", broken_replace)
    update = store.update({"theme": "dark"})
    # The new value applies for this session, and the failure is reported...
    assert update.settings["theme"] == "dark"
    assert update.issue.code == IssueCode.SETTINGS_SAVE_FAILED
    assert "file is locked" in update.issue.details
    # ...but the file still holds the old one, and no temp files are left behind.
    assert store.path.read_text(encoding="utf-8") == before
    assert os.listdir(store.path.parent) == ["settings.json"]


# ----- Save failures are reported (audit R6) -----


def assert_save_failed(update, expected_theme, logs):
    """The new value applies in memory and a logged SETTINGS_SAVE_FAILED warning is returned."""
    assert update.settings["theme"] == expected_theme
    issue = update.issue
    assert issue is not None
    assert issue.code == IssueCode.SETTINGS_SAVE_FAILED
    assert issue.severity == Severity.WARNING
    assert issue.troubleshooting
    assert issue.log_file == str(logs)
    assert "SETTINGS_SAVE_FAILED" in logs.read_text(encoding="utf-8")


def can_block_writes(folder: Path) -> bool:
    """Whether a read-only folder really refuses new files here (not as root, not on Windows)."""
    probe = folder / "probe"
    try:
        probe.write_text("x")
    except OSError:
        return True
    probe.unlink()
    return False


def test_read_only_folder_reports_issue(tmp_path, logs):
    """A folder the app may not write to: values apply, the old file stays, an issue is returned."""
    folder = tmp_path / "config"
    store = SettingsStore(folder / "settings.json")
    store.load()
    assert store.update({"theme": "light"}).issue is None
    before = store.path.read_text(encoding="utf-8")
    folder.chmod(0o500)
    try:
        if not can_block_writes(folder):
            pytest.skip("read-only folders don't block writes here (root or Windows)")
        update = store.update({"theme": "dark"})
    finally:
        folder.chmod(0o700)
    assert_save_failed(update, "dark", logs)
    assert store.get()["theme"] == "dark"
    assert store.path.read_text(encoding="utf-8") == before
    assert os.listdir(folder) == ["settings.json"]


def test_missing_parent_that_cannot_be_created_reports_issue(tmp_path, logs):
    """The settings folder can't be created (a file is in the way): an issue, not silence."""
    blocker = tmp_path / "config"
    blocker.write_text("not a folder", encoding="utf-8")
    store = SettingsStore(blocker / "settings.json")
    store.load()
    update = store.update({"theme": "dark"})
    assert_save_failed(update, "dark", logs)
    assert blocker.read_text(encoding="utf-8") == "not a folder"


def test_disk_full_reports_issue_and_leaves_no_temp_file(store, monkeypatch, logs):
    """A write that runs out of space keeps the old file and removes its temp file."""
    store.load()
    store.update({"theme": "light"})
    before = store.path.read_text(encoding="utf-8")

    def full(fd):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(settings_store.os, "fsync", full)
    update = store.update({"theme": "dark"})
    assert_save_failed(update, "dark", logs)
    assert "No space left on device" in update.issue.details
    assert store.path.read_text(encoding="utf-8") == before
    assert os.listdir(store.path.parent) == ["settings.json"]


def test_save_survives_restart(store):
    """A successful save is read back by a new store, as after restarting the app."""
    store.load()
    update = store.update({"theme": "green", "dpi": 300, "defaultSaveFolder": "/sample/out"})
    assert update.issue is None
    restarted = SettingsStore(store.path)
    assert restarted.get() == DEFAULTS  # Nothing is known before loading.
    assert restarted.load() == update.settings


def test_failed_save_is_lost_after_restart_but_next_save_persists(store, monkeypatch):
    """Unsaved values are gone after a restart; a later successful save writes everything."""
    store.load()
    real_write = store._write

    def broken(values):
        raise PermissionError("blocked")

    monkeypatch.setattr(store, "_write", broken)
    assert store.update({"theme": "dark"}).issue is not None
    assert SettingsStore(store.path).load()["theme"] == "system"
    monkeypatch.setattr(store, "_write", real_write)
    assert store.update({"dpi": 300}).issue is None
    reloaded = SettingsStore(store.path).load()
    assert reloaded["theme"] == "dark" and reloaded["dpi"] == 300


def test_updates_apply_in_call_order(store, monkeypatch):
    """Updates queued behind a slow write run first come, first served.

    The first update blocks inside its write. Two more are queued one after
    the other (the test waits until each holds its ticket), then the write is
    released: the writes and the final file follow the call order.
    """
    store.load()
    real_write = store._write
    in_write = threading.Event()
    release = threading.Event()
    written: list[dict] = []

    def slow_write(values):
        written.append(values)
        if len(written) == 1:
            in_write.set()
            assert release.wait(5)
        real_write(values)

    monkeypatch.setattr(store, "_write", slow_write)
    results: dict[str, dict] = {}

    def call(name, patch):
        results[name] = store.update(patch).settings

    threads = []
    for index, (name, patch) in enumerate(
        [("first", {"theme": "dark"}), ("second", {"dpi": 300}), ("third", {"theme": "green"})]
    ):
        thread = threading.Thread(target=call, args=(name, patch))
        thread.start()
        threads.append(thread)
        if index == 0:
            assert in_write.wait(5)
        else:
            with store._turn:  # Wait until this caller holds its place in the queue.
                assert store._turn.wait_for(lambda: store._next_ticket == index + 1, 5)
    release.set()
    for thread in threads:
        thread.join(5)
    assert [(v["theme"], v["dpi"]) for v in written] == [
        ("dark", 200),
        ("dark", 300),
        ("green", 300),
    ]
    assert results["third"] == {**DEFAULTS, "theme": "green", "dpi": 300}
    assert SettingsStore(store.path).load() == results["third"]
