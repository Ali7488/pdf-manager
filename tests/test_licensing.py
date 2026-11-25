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
import struct
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


def _pe(imports=(), delay=(), linker=(14, 44)) -> bytes:
    """A minimal 64-bit PE image that imports ``imports`` (and delay-loads ``delay``).

    Enough structure for ``check_licenses.pe_imports``: DOS and PE headers, a PE32+
    optional header with the linker version and data directories, one section holding
    the import and delay-load descriptor tables and the DLL names.
    """
    section_rva, section_raw = 0x1000, 0x200
    tables = len(imports) * 20 + 20
    delay_at = tables
    names_at = delay_at + len(delay) * 32 + 32
    body = bytearray(names_at)
    names = b""
    for i, name in enumerate(list(imports) + list(delay)):
        rva = section_rva + names_at + len(names)
        names += name.encode() + b"\0"
        if i < len(imports):
            struct.pack_into("<I", body, i * 20 + 12, rva)
        else:
            struct.pack_into("<I", body, delay_at + (i - len(imports)) * 32 + 4, rva)
    body += names
    optional = bytearray(240)
    struct.pack_into("<HBB", optional, 0, 0x20B, *linker)
    struct.pack_into("<II", optional, 112 + 8 * 1, section_rva, tables)
    if delay:
        struct.pack_into("<II", optional, 112 + 8 * 13, section_rva + delay_at, len(delay) * 32)
    header = bytearray(0x40)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x40)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, len(optional), 0x22)
    section = b".idata\0\0" + struct.pack(
        "<IIII12xI", len(body), section_rva, len(body), section_raw, 0xC0000040
    )
    image = bytes(header) + coff + bytes(optional) + section
    return image.ljust(section_raw, b"\0") + bytes(body)


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to read uv.lock")
def test_repository_inventory_is_complete_and_current():
    assert _failures(check.check_repo) == []


def test_new_python_dependency_without_notice_fails(monkeypatch):
    if shutil.which("uv") is None:
        pytest.skip("needs uv")
    locked = check.locked_python_packages()
    monkeypatch.setattr(
        check, "locked_python_packages", lambda *extra: {**locked, "newpackage": "1.0"}
    )
    failures = _failures(check.check_repo)
    assert any("newpackage" in f for f in failures)


def test_version_bump_without_regenerating_fails(monkeypatch):
    if shutil.which("uv") is None:
        pytest.skip("needs uv")
    locked = check.locked_python_packages()
    monkeypatch.setattr(
        check, "locked_python_packages", lambda *extra: {**locked, "pymupdf": "9.9.9"}
    )
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
        ("unins000.exe", "INNO SETUP"),
        ("_internal/python313.dll", "PYTHON RUNTIME"),
        ("_internal/vcruntime140_1.dll", None),
        ("_internal/MSVCP140.dll", None),
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


def test_complete_fake_app_passes_the_bundle_check(tmp_path):
    """Every component type in one app folder: nothing may be reported for them."""
    app = _fake_app(tmp_path)
    internal = app / "_internal"
    for relative in [
        "unins000.exe",
        "_internal/mupdfcpp64.dll",
        "_internal/libcrypto-3.dll",
        "_internal/pythonnet/runtime/Python.Runtime.dll",
        "_internal/clr_loader/ffi/dlls/amd64/ClrLoader.dll",
        "_internal/pywin32_system32/pythoncom313.dll",
        "_internal/_cffi_backend.cp313-win_amd64.pyd",
    ]:
        (app / relative).parent.mkdir(parents=True, exist_ok=True)
        (app / relative).write_bytes(b"MZ")
    del internal
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    # Only the WebView2 files can differ here (the fake app has placeholders when the
    # pywebview wheel isn't cached) and the Python version (this isn't a Windows build).
    assert [f for f in failures if "WebView2" not in f and "Python" not in f] == []


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


@pytest.mark.parametrize(
    "relative",
    [
        "_internal/ucrtbase.dll",
        "_internal/api-ms-win-crt-heap-l1-1-0.dll",
        "_internal/mfc140u.dll",
        "_internal/VCRUNTIME140.dll",
        "_internal/VCRUNTIME140_1.dll",
        "_internal/MSVCP140.dll",
        "_internal/msvcp140_2.dll",
        "_internal/concrt140.dll",
        "_internal/vcomp140.dll",
        # Anywhere in the app, not just next to python313.dll.
        "_internal/pymupdf/msvcp140.dll",
        "_internal/pythonwin/mfc140u.dll",
        "vcruntime140.dll",
    ],
)
def test_microsoft_runtime_files_must_not_be_bundled(tmp_path, relative):
    app = _fake_app(tmp_path)
    (app / relative).parent.mkdir(parents=True, exist_ok=True)
    (app / relative).write_bytes(b"MZ")
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any(f.startswith(f"{relative} shouldn't be bundled") for f in failures)


@pytest.mark.parametrize(
    "name",
    [
        "vcruntime140.dll",
        "VCRUNTIME140_1.dll",
        "msvcp140.dll",
        "msvcp140_atomic_wait.dll",
        "mfc140u.dll",
        "mfcm140u.dll",
        "vccorlib140.dll",
        "vcamp140.dll",
    ],
)
def test_visual_cpp_runtime_names_are_recognised(name):
    assert check.VC_RUNTIME_DLL.match(name)


@pytest.mark.parametrize(
    "name", ["python313.dll", "mupdfcpp64.dll", "msvcrt.dll", "libcrypto-3.dll", "vcruntime.txt"]
)
def test_other_dlls_are_not_taken_for_the_visual_cpp_runtime(name):
    assert not check.VC_RUNTIME_DLL.match(name)


def test_the_spec_excludes_the_same_runtime_files_the_check_rejects():
    spec = (ROOT / "packaging" / "pdf-manager.spec").read_text(encoding="utf-8")
    assert check.VC_RUNTIME_DLL.pattern in spec
    assert "_VC_RUNTIME_DLL.match(name)" in spec


def test_pe_imports_reads_normal_and_delay_loaded_imports(tmp_path):
    path = tmp_path / "module.pyd"
    path.write_bytes(_pe(["KERNEL32.dll", "VCRUNTIME140.dll"], ["ole32.dll"], (14, 50)))
    assert check.pe_imports(path) == (["kernel32.dll", "vcruntime140.dll", "ole32.dll"], (14, 50))


@pytest.mark.parametrize("data", [b"", b"MZ", b"MZ" + b"\0" * 100, b"not a binary"])
def test_pe_imports_ignores_files_that_are_not_pe_images(tmp_path, data):
    path = tmp_path / "broken.dll"
    path.write_bytes(data)
    assert check.pe_imports(path) is None


def test_installer_checks_for_the_visual_cpp_redistributable():
    files, minimum = check.installer_vc_runtime()
    assert {"vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"} <= files
    assert minimum >= (14, 44)


def test_runtime_dll_the_installer_doesnt_check_for_fails(tmp_path, monkeypatch):
    app = _fake_app(tmp_path)
    (app / "_internal" / "pymupdf" / "_mupdf.pyd").write_bytes(
        _pe(["mupdfcpp64.dll", "MSVCP140.dll", "VCRUNTIME140.dll", "VCOMP140.dll"])
    )
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any(
        "_internal/pymupdf/_mupdf.pyd needs vcomp140.dll" in f and "VCRuntimeFiles" in f
        for f in failures
    )
    assert not any("needs msvcp140.dll" in f or "needs vcruntime140.dll" in f for f in failures)
    monkeypatch.setattr(check, "installer_vc_runtime", lambda: None)
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any("doesn't check for the Microsoft Visual C++ Redistributable" in f for f in failures)


def test_binary_built_by_a_newer_toolset_than_the_installer_requires_fails(tmp_path):
    app = _fake_app(tmp_path)
    _, (major, minor) = check.installer_vc_runtime()
    internal = app / "_internal"
    (internal / "python313.dll").write_bytes(_pe(["VCRUNTIME140.dll"], linker=(major, minor)))
    assert not [
        f
        for f in _failures(lambda r: check.check_bundle(r, app, installed=False))
        if "linked by MSVC" in f
    ]
    (internal / "python313.dll").write_bytes(_pe(["VCRUNTIME140.dll"], linker=(major, minor + 1)))
    failures = _failures(lambda r: check.check_bundle(r, app, installed=False))
    assert any(
        f"_internal/python313.dll was linked by MSVC {major}.{minor + 1}" in f for f in failures
    )
    # A newer linker doesn't matter for files that don't use the Visual C++ runtime.
    (internal / "python313.dll").write_bytes(_pe(["KERNEL32.dll"], linker=(major, minor + 5)))
    assert not [
        f
        for f in _failures(lambda r: check.check_bundle(r, app, installed=False))
        if "linked by MSVC" in f
    ]


def test_installer_without_a_runtime_check_fails_the_repo_check(monkeypatch):
    if shutil.which("uv") is None:
        pytest.skip("needs uv")
    monkeypatch.setattr(check, "installer_vc_runtime", lambda: None)
    assert any(
        "doesn't check for the Microsoft Visual C++ Redistributable" in f
        for f in _failures(check.check_repo)
    )


def test_installer_never_offers_to_start_the_app_without_the_runtime():
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    run = [line for line in iss.splitlines() if line.startswith("Filename:")]
    assert run and all("Check: CanStartApp" in line for line in run)
    body = iss.split("function CanStartApp", 1)[1].split("end;", 1)[0]
    assert "IsVCRuntimeInstalled" in body and "IsWebView2Installed" in body
    # Offered before installing and again after, and never downloaded or run silently.
    assert iss.count("OfferVCRuntimeDownload('VCRuntime") == 2
    assert "https://aka.ms/vc14/vc_redist.x64.exe" in iss
    assert "vc_redist.x64.exe /" not in iss and "DownloadTemporaryFile" not in iss


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
    # The Visual C++ runtime isn't bundled, so it isn't listed as a bundled component,
    # and the notices say it is a separately installed prerequisite.
    assert "Visual C++" not in names
    assert not (ROOT / "licenses" / "other" / "microsoft-vc-runtime").exists()
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Microsoft Visual C++ Redistributable (x64)" in notices.split("## Not included")[1]
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


def test_collector_deduplicates_license_paths(monkeypatch):
    monkeypatch.setattr(
        collect,
        "runtime_python_packages",
        lambda: {"example": ("1.0", {"windows"})},
    )
    monkeypatch.setattr(
        collect,
        "_from_installed",
        lambda name, target: ("MIT", ["LICENSE", "LICENSE"]),
    )
    result = collect.python_components()
    assert result[0].files == ["python/example-1.0/LICENSE"]


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_duplicate_manifest_license_paths_fail(monkeypatch):
    manifest = check.load_manifest()
    component = next(c for c in manifest["components"] if c["name"] == "pywin32")
    component["files"].append(component["files"][0])
    monkeypatch.setattr(check, "load_manifest", lambda: manifest)
    assert any("duplicate licence paths" in failure for failure in _failures(check.check_repo))


def test_pywin32_source_uses_fixed_upstream_commit():
    item = next(
        s for s in check.load_manifest()["sources"]["python"] if s["component"] == "pywin32"
    )
    assert item["url"] == (
        "https://github.com/mhammond/pywin32/archive/"
        "2a277cb5552756c2b4d42b524dc36d25e0bb6354.tar.gz"
    )


def test_cpython_source_archive_has_pinned_sha256():
    item = check.load_manifest()["sources"]["python_runtime"]
    assert item["url"].endswith("Python-3.13.17.tar.xz")
    assert item["sha256"] == ("6020bd10aff3bf4821be16f088ebb1591beb7b811dcd8fab1da8f7c22a7b27e7")


def test_every_bundled_python_package_has_a_source_location():
    manifest = check.load_manifest()
    listed = {check._norm(s["component"]) for s in manifest["sources"]["python"]}
    bundled = {check._norm(c["name"]) for c in manifest["components"] if c["group"] == "python"}
    assert bundled <= listed
    assert all(s["url"].startswith("https://") for s in manifest["sources"]["python"])
    assert json.dumps(manifest["sources"]["mupdf"]).count("mupdf.com") == 1


def test_frontend_upstream_source_pins_match_the_lockfile():
    npm_sources = collect.frontend_sources()
    archives = collect.frontend_upstream_sources(npm_sources)
    assert archives == check.load_manifest()["sources"]["frontend_upstream"]
    assert len(archives) == 2

    react = next(item for item in npm_sources if item["component"] == "react")
    react["version"] = "0.0.0"
    with pytest.raises(SystemExit, match="Review the upstream source pin for react 0.0.0"):
        collect.frontend_upstream_sources(npm_sources)


# ----- The browser-mode ZIP (browser build) -----

stage = _load("stage_licenses")


def _browser_app(tmp_path: Path) -> Path:
    """A minimal browser-mode app folder: no window toolkit, no installer."""
    app = tmp_path / "PDF Manager (browser)"
    internal = app / "_internal"
    (internal / "pymupdf").mkdir(parents=True)
    for relative in ("PDF Manager.exe", "_internal/python313.dll", "_internal/pymupdf/_mupdf.pyd"):
        (app / relative).write_bytes(b"MZ")
    return app


def _bundle_failures(app, installed=False):
    return _failures(lambda r: check.check_bundle(r, app, installed=installed, build="browser"))


def test_the_manifest_knows_which_build_ships_what():
    manifest = check.load_manifest()
    builds = {check._norm(c["name"]): c["builds"] for c in manifest["components"]}
    assert builds["pymupdf"] == ["desktop", "browser"]
    assert builds["pywin32"] == ["desktop", "browser"]
    for desktop_only in ("pywebview", "pythonnet", "clr-loader", "pyside6"):
        assert builds[desktop_only] == ["desktop"], desktop_only
    webview2 = next(c for c in manifest["components"] if "WebView2" in c["name"])
    assert webview2["builds"] == ["desktop"]


def test_a_clean_browser_app_passes(tmp_path):
    app = _browser_app(tmp_path)
    assert [f for f in _bundle_failures(app) if "Python" not in f] == []


@pytest.mark.parametrize(
    "relative",
    [
        "_internal/webview/lib/Microsoft.Web.WebView2.Core.dll",
        "_internal/pythonnet/runtime/Python.Runtime.dll",
        "_internal/clr_loader/ffi/dlls/amd64/ClrLoader.dll",
        "_internal/webview/lib/WebBrowserInterop.x64.dll",
        "unins000.exe",
    ],
)
def test_the_desktop_toolkit_or_installer_in_the_browser_app_fails(tmp_path, relative):
    app = _browser_app(tmp_path)
    (app / relative).parent.mkdir(parents=True, exist_ok=True)
    (app / relative).write_bytes(b"MZ")
    assert any("desktop build only" in f for f in _bundle_failures(app))


def test_a_desktop_package_in_the_browser_app_fails(tmp_path):
    app = _browser_app(tmp_path)
    (app / "_internal" / "pywebview-6.2.1.dist-info").mkdir()
    assert any("pywebview" in f for f in _bundle_failures(app))


def test_staged_browser_licences_are_exactly_the_builds(tmp_path):
    app = _browser_app(tmp_path)
    count = stage.stage(app, "browser")
    manifest = check.load_manifest()
    assert count == len(check.licence_files(manifest, "browser"))
    notices = (app / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "| pywebview |" not in notices and "| pymupdf |" in notices
    assert not (app / "licenses" / "other" / "inno-setup").exists()
    assert not [f for f in _bundle_failures(app, installed=True) if "Python" not in f]

    (app / "licenses" / "other" / "inno-setup").mkdir(parents=True)
    (app / "licenses" / "other" / "inno-setup" / "license.txt").write_text("x")
    next(iter((app / "licenses" / "mupdf").rglob("*.txt"))).unlink()
    failures = _bundle_failures(app, installed=True)
    assert any("Stale licence files" in f and "inno-setup" in f for f in failures)
    assert any(f.startswith("Installed app lacks licenses/mupdf/") for f in failures)


def test_wrong_build_marks_fail_the_repo_check(monkeypatch):
    if shutil.which("uv") is None:
        pytest.skip("needs uv")
    manifest = check.load_manifest()
    for component in manifest["components"]:
        if component["name"] == "pywebview":
            component["builds"] = ["desktop", "browser"]
    monkeypatch.setattr(check, "load_manifest", lambda: manifest)
    failures = _failures(check.check_repo)
    assert any("pywebview: the lockfile's browser build leaves it out" in f for f in failures)
    assert any("THIRD_PARTY_NOTICES-browser.md lacks pywebview" in f for f in failures)


def test_the_python_runtimes_own_libraries_have_pinned_source():
    """OpenSSL, libffi, bzip2, xz, mpdecimal and zlib ship inside the Windows runtime.

    CPython's tarball doesn't contain them, so the source bundle carries the
    cpython-source-deps archives (the owner's artifact review).
    """
    manifest = check.load_manifest()
    items = manifest["sources"]["python_runtime_externals"]
    names = {item["component"].split()[0] for item in items}
    assert names == {"OpenSSL", "libffi", "bzip2", "xz", "mpdecimal", "zlib"}
    for item in items:
        assert item["url"].startswith("https://github.com/python/cpython-source-deps/archive/")
        assert len(item["sha256"]) == 64
    collector = (ROOT / "scripts" / "collect_sources.py").read_text(encoding="utf-8")
    assert 'sources["python_runtime_externals"]' in collector
    generator = (ROOT / "scripts" / "collect_licenses.py").read_text(encoding="utf-8")
    for item in items:
        assert item["sha256"] in generator, "manifest and generator disagree"


def _listing(tmp_path, build, distributions, unowned=()):
    path = tmp_path / f"bundle-python-{build}.json"
    path.write_text(
        json.dumps({"build": build, "distributions": distributions, "unowned": list(unowned)})
    )
    return path


@pytest.mark.parametrize(
    "distributions,unowned,problem",
    [
        ({"pymupdf": "1.28.2"}, (), None),
        ({"pymupdf": "1.28.2", "setuptools": "80.9.0"}, (), "setuptools 80.9.0 isn't in"),
        ({"pymupdf": "1.28.1"}, (), "the notices list 1.28.2"),
        ({"pymupdf": "1.28.2"}, ("jaraco",), "'jaraco' belongs to no installed distribution"),
        ({"pywebview": "6.2.1"}, (), "pywebview 6.2.1 isn't in the browser notices"),
    ],
)
def test_bundled_python_distributions_must_be_in_the_notices(
    tmp_path, capsys, distributions, unowned, problem
):
    report = check.Report()
    check.check_python_distributions(
        report, _listing(tmp_path, "browser", distributions, unowned), "browser"
    )
    if problem is None:
        assert report.failures == []
    else:
        assert any(problem in failure for failure in report.failures), report.failures


def test_packaging_is_listed_for_the_linux_desktop_build_only(tmp_path, monkeypatch):
    """packaging comes with qtpy (Linux); on Windows it would be an unlisted extra."""
    for platform, listed in (("linux", True), ("win32", False)):
        monkeypatch.setattr(check.sys, "platform", platform)
        report = check.Report()
        listing = _listing(tmp_path, "desktop", {"packaging": "26.3"})
        check.check_python_distributions(report, listing, "desktop")
        flagged = any("packaging 26.3 isn't in" in failure for failure in report.failures)
        assert flagged is not listed, (platform, report.failures)
