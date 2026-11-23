"""Licence inventory checks (scripts/check_licenses.py, scripts/collect_licenses.py,
scripts/collect_sources.py).

The first test is the real check: it fails CI whenever ``THIRD_PARTY_NOTICES.md`` and
``licenses/`` are out of date with the lockfiles or the build pins. The others prove
that the checks catch what they are meant to catch, using fake app folders.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check = _load("check_licenses")
collect = _load("collect_licenses")
sources = _load("collect_sources")


def _failures(run) -> list[str]:
    report = check.Report()
    run(report)
    return report.failures


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to read uv.lock")
def test_repository_inventory_is_complete_and_current():
    assert _failures(check.check_repo) == []


def test_new_python_dependency_without_notice_fails(monkeypatch):
    if shutil.which("uv") is None:
        pytest.skip("needs uv")
    locked = check.locked_python_packages()
    monkeypatch.setattr(check, "locked_python_packages", lambda: {**locked, "newpackage": "1.0"})
    failures = _failures(check.check_repo)
    assert any("newpackage" in f for f in failures)


def test_version_bump_without_regenerating_fails(monkeypatch):
    if shutil.which("uv") is None:
        pytest.skip("needs uv")
    locked = check.locked_python_packages()
    monkeypatch.setattr(check, "locked_python_packages", lambda: {**locked, "pymupdf": "9.9.9"})
    assert any("pymupdf" in f and "9.9.9" in f for f in _failures(check.check_repo))


def test_new_frontend_dependency_without_notice_fails(monkeypatch):
    if shutil.which("uv") is None:
        pytest.skip("needs uv")
    locked = check.locked_frontend_packages()
    monkeypatch.setattr(check, "locked_frontend_packages", lambda: {**locked, "left-pad": "1.3.0"})
    assert any("left-pad" in f for f in _failures(check.check_repo))


def test_frontend_inventory_reads_only_runtime_packages():
    packages = check.locked_frontend_packages()
    assert "react" in packages
    assert "vite" not in packages and "vitest" not in packages


@pytest.mark.parametrize(
    ("relative", "component"),
    [
        ("PDF Manager.exe", "PyInstaller bootloader"),
        ("_internal/python313.dll", "PYTHON RUNTIME"),
        ("_internal/vcruntime140_1.dll", "MSVC RUNTIME"),
        ("_internal/MSVCP140.dll", "MSVC RUNTIME"),
        ("_internal/mupdfcpp64.dll", "pymupdf"),
        ("_internal/libcrypto-3.dll", "PYTHON RUNTIME"),
        ("_internal/_ssl.pyd", "PYTHON RUNTIME"),
        ("_internal/pymupdf/mupdfcpp64.dll", "pymupdf"),
        ("_internal/webview/lib/Microsoft.Web.WebView2.Core.dll", "WEBVIEW2"),
        ("_internal/webview/lib/runtimes/win-x64/native/WebView2Loader.dll", "WEBVIEW2"),
        ("_internal/pythonnet/runtime/Python.Runtime.dll", "pythonnet"),
        ("_internal/pywin32_system32/pywintypes313.dll", "pywin32"),
        ("_internal/somepackage/native.dll", None),
        ("_internal/unknown.dll", None),
    ],
)
def test_native_files_map_to_components(relative, component):
    assert check.classify(relative) == component


def _fake_app(tmp_path: Path) -> Path:
    """A minimal Windows app folder whose files all have notices."""
    manifest = check.load_manifest()
    app = tmp_path / "PDF Manager"
    internal = app / "_internal"
    (internal / "pymupdf").mkdir(parents=True)
    (app / "PDF Manager.exe").write_bytes(b"MZ")
    (internal / "python313.dll").write_bytes(b"MZ")
    (internal / "pymupdf" / "_mupdf.pyd").write_bytes(b"MZ")
    cache = collect.CACHE
    wheels = sorted(cache.glob("pywebview-*.whl")) if cache.is_dir() else []
    for in_wheel in manifest["webview2_sdk"]["sha256"]:
        target = internal / in_wheel
        target.parent.mkdir(parents=True, exist_ok=True)
        if wheels:
            import zipfile

            with zipfile.ZipFile(wheels[0]) as archive:
                target.write_bytes(archive.read(in_wheel))
    return app


def test_unknown_native_file_in_bundle_fails(tmp_path):
    app = _fake_app(tmp_path)
    (app / "_internal" / "mystery.dll").write_bytes(b"MZ")
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any("_internal/mystery.dll belongs to no listed component" in f for f in failures)


def test_changed_webview2_file_fails(tmp_path):
    app = _fake_app(tmp_path)
    core = app / "_internal" / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll"
    core.write_bytes(b"a different build")
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any(
        "Microsoft.Web.WebView2.Core.dll isn't the Microsoft.Web.WebView2" in f for f in failures
    )


@pytest.mark.parametrize("name", ["ucrtbase.dll", "api-ms-win-crt-heap-l1-1-0.dll", "mfc140u.dll"])
def test_microsoft_files_windows_provides_must_not_be_bundled(tmp_path, name):
    app = _fake_app(tmp_path)
    (app / "_internal" / name).write_bytes(b"MZ")
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any(f"_internal/{name} shouldn't be bundled" in f for f in failures)


def test_qt_in_windows_bundle_fails(tmp_path):
    app = _fake_app(tmp_path)
    (app / "_internal" / "Qt6Core.dll").write_bytes(b"MZ")
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any("Qt/PySide6" in f for f in failures)


def test_unlisted_python_package_in_bundle_fails(tmp_path):
    app = _fake_app(tmp_path)
    (app / "_internal" / "requests-2.0.dist-info").mkdir()
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any("requests" in f for f in failures)


def test_installed_app_needs_identical_licence_files(tmp_path):
    app = _fake_app(tmp_path)
    shutil.copytree(ROOT / "licenses", app / "licenses")
    for source, name in check.TOP_LEVEL.items():
        shutil.copyfile(ROOT / source, app / name)
    before = _failures(lambda r: check.check_bundle(r, app, installed=True))
    assert not [f for f in before if "differs" in f or "lacks" in f or "Stale" in f]

    (app / "licenses" / "mupdf" / "COPYING").write_text("tampered", encoding="utf-8")
    (app / "LICENSE-AGPL-3.0.txt").unlink()
    (app / "licenses" / "old-component.txt").write_text("old", encoding="utf-8")
    failures = _failures(lambda r: check.check_bundle(r, app, installed=True))
    assert any("licenses/mupdf/COPYING differs" in f for f in failures)
    assert any("lacks LICENSE-AGPL-3.0.txt" in f for f in failures)
    assert any("Stale licence files" in f for f in failures)


def test_licence_files_with_the_same_name_are_all_kept(tmp_path):
    first = collect._keep(tmp_path, "win32/License.txt", b"one")
    second = collect._keep(tmp_path, "pythonwin/License.txt", b"two")
    meta = collect._keep(tmp_path, "pkg-1.0.dist-info/licenses/LICENSE", b"three")
    assert (first, second, meta) == ("win32/License.txt", "pythonwin/License.txt", "LICENSE")
    assert (tmp_path / "win32" / "License.txt").read_bytes() == b"one"
    assert (tmp_path / "pythonwin" / "License.txt").read_bytes() == b"two"


def test_every_copyleft_component_ships_the_full_text():
    manifest = check.load_manifest()
    for component in manifest["components"]:
        if component["license"].startswith(("AGPL", "LGPL")) and component["group"] == "python":
            names = {Path(f).name for f in component["files"]}
            assert names & {"AGPL-3.0-only.txt", "LGPL-3.0-only.txt"}, component["name"]


def test_notices_cover_mupdf_webview2_and_the_windows_runtime():
    manifest = check.load_manifest()
    names = " ".join(c["name"] for c in manifest["components"])
    for expected in ("MuPDF", "Tesseract", "FreeType", "WebView2", "python.org Windows"):
        assert expected in names
    webview2 = next(c for c in manifest["components"] if "WebView2" in c["name"])
    assert any(f.endswith("NOTICE.txt") for f in webview2["files"])


def test_source_download_rejects_a_wrong_checksum(tmp_path):
    archive = tmp_path / "pkg-1.0.tar.gz"
    archive.write_bytes(b"source")
    out = tmp_path / "out"
    out.mkdir()
    url = archive.as_uri()
    good = hashlib.sha256(b"source").hexdigest()
    assert sources.fetch(url, out, sha256=good).read_bytes() == b"source"
    (out / archive.name).unlink()
    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        sources.fetch(url, out, sha256="0" * 64)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(b"other").digest()).decode()
    with pytest.raises(SystemExit, match="Integrity mismatch"):
        sources.fetch(url, out, integrity=integrity)


def test_every_bundled_python_package_has_a_source_location():
    manifest = check.load_manifest()
    listed = {check._norm(s["component"]) for s in manifest["sources"]["python"]}
    bundled = {check._norm(c["name"]) for c in manifest["components"] if c["group"] == "python"}
    assert bundled <= listed
    assert all(s["url"].startswith("https://") for s in manifest["sources"]["python"])
    assert json.dumps(manifest["sources"]["mupdf"]).count("mupdf.com") == 1
