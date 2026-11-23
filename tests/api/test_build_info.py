"""Tests for api.build_info: the exact revision behind Settings > About's source link (P37)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from api import build_info, paths
from api.build_info import BuildInfoError, write_build_info

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs Git")


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("PDF_MANAGER_SOURCE_REVISION", raising=False)
    monkeypatch.delenv("PDF_MANAGER_ALLOW_DIRTY", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    (root / "app.py").write_text("print('v1')\n")
    git(root, "add", "app.py")
    git(root, "commit", "-q", "-m", "one")
    return root


def test_a_clean_checkout_records_its_commit(repo, tmp_path):
    target = tmp_path / "out" / "build-info.json"
    info = write_build_info(repo, target)
    assert info == {"revision": git(repo, "rev-parse", "HEAD"), "modified": False}
    assert json.loads(target.read_text()) == info


def test_changed_tracked_files_stop_the_build(repo, tmp_path, monkeypatch):
    (repo / "app.py").write_text("print('changed')\n")
    with pytest.raises(BuildInfoError, match="differ from the commit"):
        write_build_info(repo, tmp_path / "b.json")
    monkeypatch.setenv("PDF_MANAGER_ALLOW_DIRTY", "1")
    assert write_build_info(repo, tmp_path / "b.json")["modified"] is True


def test_untracked_files_dont_count_as_changes(repo, tmp_path):
    (repo / "notes.txt").write_text("scratch")  # Like frontend/dist or build/.
    assert write_build_info(repo, tmp_path / "b.json")["modified"] is False


def test_the_expected_revision_must_match_the_checkout(repo, tmp_path, monkeypatch):
    head = git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("PDF_MANAGER_SOURCE_REVISION", head.upper())
    assert write_build_info(repo, tmp_path / "b.json")["revision"] == head
    monkeypatch.setenv("PDF_MANAGER_SOURCE_REVISION", "f" * 40)
    with pytest.raises(BuildInfoError, match="but the checkout is"):
        write_build_info(repo, tmp_path / "b.json")


def test_not_a_checkout(tmp_path):
    with pytest.raises(BuildInfoError, match="isn't a Git checkout"):
        write_build_info(tmp_path, tmp_path / "b.json")


def test_the_packaged_app_reads_its_bundled_file(tmp_path, monkeypatch):
    build_info.source_revision.cache_clear()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "build-info.json").write_text(json.dumps({"revision": "a" * 40, "modified": False}))
    try:
        assert paths.is_frozen()
        assert build_info.source_revision() == {"revision": "a" * 40, "modified": False}
        build_info.source_revision.cache_clear()
        (tmp_path / "build-info.json").write_text('{"revision": "v0.5.0"}')  # Not a commit.
        assert build_info.source_revision() is None
    finally:
        build_info.source_revision.cache_clear()


def test_from_source_it_is_this_checkout():
    build_info.source_revision.cache_clear()
    try:
        info = build_info.source_revision()
        if info is not None:  # A source tarball without .git has no revision.
            assert info["revision"] == git(paths.app_dir(), "rev-parse", "HEAD")
    finally:
        build_info.source_revision.cache_clear()
