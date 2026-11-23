"""Tests for api.settings_store: defaults, validation, damaged files and atomic saves."""

import json
import os

import pytest

from api import settings_store
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
    assert store.update({"defaultSaveFolder": "  "})["defaultSaveFolder"] is None


def test_update_merges_persists_and_skips_invalid(store):
    """update() applies valid fields, skips invalid ones and writes the file."""
    store.load()
    result = store.update({"theme": "dark", "dpi": "lots", "ocrLanguage": "deu"})
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
    result = store.update({"theme": "dark"})
    # The new value applies for this session...
    assert result["theme"] == "dark"
    # ...but the file still holds the old one, and no temp files are left behind.
    assert store.path.read_text(encoding="utf-8") == before
    assert os.listdir(store.path.parent) == ["settings.json"]
