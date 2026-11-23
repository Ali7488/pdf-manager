"""Tests for api.paths in source and frozen (PyInstaller) mode."""

import sys
import tomllib
from pathlib import Path

import api
from api import paths

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_source_mode_uses_repo_root(monkeypatch):
    """From source, every folder is relative to the repository root."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert not paths.is_frozen()
    assert paths.app_dir() == REPO_ROOT
    assert paths.resource_dir() == REPO_ROOT
    assert paths.ui_index() == REPO_ROOT / "frontend" / "dist" / "index.html"
    assert paths.logs_dir() == REPO_ROOT / "logs"


def test_frozen_mode_uses_exe_folder_and_meipass(monkeypatch, tmp_path):
    """Frozen, logs go next to the exe and bundled files come from _MEIPASS."""
    install = tmp_path / "install"
    bundle = tmp_path / "bundle"
    install.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "PDF Manager.exe"))
    assert paths.is_frozen()
    assert paths.app_dir() == install.resolve()
    assert paths.resource_dir() == bundle
    assert paths.ui_index() == bundle / "frontend" / "dist" / "index.html"
    assert paths.logs_dir() == install.resolve() / "logs"


def test_frozen_without_meipass_falls_back_to_exe_folder(monkeypatch, tmp_path):
    """A freezer that sets sys.frozen but not _MEIPASS still finds bundled files."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert paths.resource_dir() == tmp_path.resolve()


def test_settings_path_windows(monkeypatch, tmp_path):
    """On Windows, settings live under %LOCALAPPDATA%\\PDFManager."""
    monkeypatch.setattr(paths, "on_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.settings_path() == tmp_path / "PDFManager" / "settings.json"


def test_settings_path_xdg(monkeypatch, tmp_path):
    """Elsewhere, settings follow $XDG_CONFIG_HOME, defaulting to ~/.config."""
    monkeypatch.setattr(paths, "on_windows", lambda: False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.settings_path() == tmp_path / "pdf-manager" / "settings.json"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    # Patch the home lookup itself: Windows finds home via USERPROFILE, not HOME.
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    expected = tmp_path / "home" / ".config" / "pdf-manager" / "settings.json"
    assert paths.settings_path() == expected


def test_version_matches_pyproject():
    """The version constant shown in the app matches pyproject.toml."""
    with open(REPO_ROOT / "pyproject.toml", "rb") as handle:
        project = tomllib.load(handle)["project"]
    assert api.__version__ == project["version"]
