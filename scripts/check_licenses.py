"""Check that PDF Manager's licence inventory is complete and up to date.

    uv run scripts/check_licenses.py repo
    uv run scripts/check_licenses.py bundle "dist/PDF Manager"
    uv run scripts/check_licenses.py bundle "%LOCALAPPDATA%/Programs/PDF Manager" --installed
    uv run scripts/check_licenses.py bundle "dist/PDF Manager (browser)" --installed --build browser

``repo`` (no network; run by the test suite in CI) compares ``licenses/manifest.json``
with what the lockfiles say is bundled and with the build pins, and checks that every
listed licence file exists, that copyleft licences ship their full text, and that the
installer and the user-facing documents carry the licence files and the AGPL-3.0
statement.

``bundle`` (run by ``packaging/build.ps1`` and the Windows build workflow) checks a
built or installed Windows app: every native binary in it must belong to a component in
the manifest; the WebView2 SDK files must be the exact files whose licence we ship;
the bundled Python must be the version whose licence we ship; every bundled Python
package must be in the manifest; and, with ``--installed``, the licence files next to the
app must be byte-identical to the repository's. ``--build browser`` checks the
browser-mode ZIP's folder: nothing of the desktop window's toolkit (pywebview,
pythonnet, Qt, the WebView2 SDK) or the installer may be in it, and its licence
files must be exactly those of the components it ships.

``bundle`` also keeps the Microsoft Visual C++ runtime out of the app (decision P32): no
Visual C++ runtime DLL may be bundled anywhere in it. The app relies on the separately
installed Microsoft Visual C++ Redistributable instead, so the check reads every bundled
binary's import table and fails unless ``packaging/installer.iss`` checks for each runtime
DLL they import (``VCRuntimeFiles``) and requires a redistributable at least as new as the
newest MSVC toolset that linked them (``VCRuntimeMinMajor``/``VCRuntimeMinMinor``).

Exit code 0 means every check passed; 1 lists the failures. It doesn't decide legal
questions: see LICENSING.md and docs/LICENSING_AUDIT_2026-11-23.md for those.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSES = ROOT / "licenses"
MANIFEST = LICENSES / "manifest.json"

# Files that must sit next to the installed app (decision P31; packaging/installer.iss).
TOP_LEVEL = {
    "LICENSE": "LICENSE.txt",
    "LICENSE-AGPL-3.0.txt": "LICENSE-AGPL-3.0.txt",
    "LICENSING.md": "LICENSING.md",
    "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
}
# The same for the browser-mode ZIP, which has its own notices (scripts/stage_licenses.py).
BROWSER_TOP_LEVEL = {**TOP_LEVEL, "THIRD_PARTY_NOTICES-browser.md": "THIRD_PARTY_NOTICES.md"}
del BROWSER_TOP_LEVEL["THIRD_PARTY_NOTICES.md"]
BUILDS = ("desktop", "browser")
# Components that aren't Python packages and ship only in the desktop build.
DESKTOP_ONLY = ("WEBVIEW2", "INNO SETUP")
COPYLEFT_MARKERS = {
    "AGPL-3.0-only.txt": "GNU AFFERO GENERAL PUBLIC LICENSE",
    "GPL-3.0-only.txt": "GNU GENERAL PUBLIC LICENSE",
    "LGPL-3.0-only.txt": "GNU LESSER GENERAL PUBLIC LICENSE",
}
# Native files in a Windows build, by the component that ships them. Paths are
# relative to the app folder (``PDF Manager.exe`` and ``_internal/``), lower case.
# The Python runtime's own files are matched separately (see _runtime_rules).
BINARY_RULES = [
    ("pdf manager.exe", "PyInstaller bootloader"),
    ("unins*.exe", "INNO SETUP"),
    ("_internal/pymupdf/*", "pymupdf"),
    ("_internal/mupdfcpp64.dll", "pymupdf"),
    ("_internal/webview/lib/microsoft.web.webview2.*.dll", "WEBVIEW2"),
    ("_internal/webview/lib/runtimes/*/native/webview2loader.dll", "WEBVIEW2"),
    ("_internal/webview/lib/webbrowserinterop.*.dll", "pywebview"),
    ("_internal/pythonnet/*", "pythonnet"),
    ("_internal/clr_loader/*", "clr-loader"),
    ("_internal/_cffi_backend*.pyd", "cffi"),
    ("_internal/pywin32_system32/*", "pywin32"),
    ("_internal/win32/*", "pywin32"),
    ("_internal/win32com/*", "pywin32"),
    ("_internal/win32comext/*", "pywin32"),
    ("_internal/pythonwin/*", "pywin32"),
    ("_internal/pythoncom3*.dll", "pywin32"),
    ("_internal/pywintypes3*.dll", "pywin32"),
]
# The python.org Windows build's native files (python-3.x.y-embed-amd64.zip, plus the
# extension modules the full installer adds). Anything else at the top of _internal
# is reported, so a new runtime DLL can't slip in without a notice.
RUNTIME_FILES = [
    "python3.dll",
    "python3??.dll",
    "libcrypto-3*.dll",
    "libssl-3*.dll",
    "libffi-*.dll",
    "sqlite3.dll",
    "_*.pyd",
    "pyexpat.pyd",
    "select.pyd",
    "unicodedata.pyd",
    "winsound.pyd",
]
NATIVE = {".dll", ".pyd", ".exe", ".so"}
# Components that aren't Python packages, and words their manifest entry's name contains.
NON_PACKAGE = {
    "WEBVIEW2": "WebView2",
    "PYTHON RUNTIME": "python.org Windows",
    "PyInstaller bootloader": "PyInstaller bootloader",
    "INNO SETUP": "Inno Setup",
}
# DLLs of the Microsoft Visual C++ Redistributable (v14: Visual Studio 2015-2026):
# the C/C++ runtime, OpenMP, C++ AMP, ConcRT and MFC. None of them may be bundled
# (decision P32); the installer checks that the redistributable provides them.
VC_RUNTIME_DLL = re.compile(
    r"(vcruntime|msvcp|concrt|vccorlib|vcomp|vcamp|mfcm?)14\d\w*\.dll$", re.I
)
# Windows provides the Universal C Runtime itself (Windows 10 and later).
WINDOWS_PROVIDED_DLL = re.compile(r"(ucrtbase|api-ms-win-.*)\.dll$", re.I)


class Report:
    """Collects failures and prints them at the end."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def check(self, ok: bool, message: str) -> None:
        if not ok:
            self.fail(message)

    def finish(self, what: str) -> int:
        if self.failures:
            print(f"Licence check ({what}) FAILED:")
            for failure in self.failures:
                print(f"  - {failure}")
            print(
                "Fix the cause, or regenerate: uv run --with pip python scripts/collect_licenses.py"
            )
            return 1
        print(f"Licence check ({what}) passed.")
        return 0


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_python_packages(*extra: str) -> dict[str, str]:
    """Runtime packages bundled on Windows or Linux, from ``uv export`` of uv.lock.

    Args:
        *extra: More ``uv export`` options (``"--no-group", "desktop"``: browser mode's).
    """
    out = subprocess.run(
        ["uv", "export", "--no-dev", "--frozen", "--no-hashes", "--no-emit-project", *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    packages = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        spec, _, marker = line.partition(";")
        if "darwin" in marker:
            continue
        name, _, version = spec.strip().partition("==")
        packages[_norm(name)] = version
    return packages


def browser_python_packages() -> dict[str, str]:
    """The packages the browser-mode ZIP bundles: no desktop window toolkit."""
    return locked_python_packages("--no-group", "desktop")


def components_for(manifest: dict, build: str) -> list[dict]:
    """The manifest's components that ``build`` ships."""
    return [c for c in manifest["components"] if build in c.get("builds", BUILDS)]


def licence_files(manifest: dict, build: str) -> list[str]:
    """Paths under licenses/ of every licence text ``build`` must carry."""
    return sorted({f for c in components_for(manifest, build) for f in c["files"]})


def locked_frontend_packages() -> dict[str, str]:
    """Packages inlined into the UI: the non-development entries of package-lock.json."""
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    return {
        path.removeprefix("node_modules/"): info["version"]
        for path, info in lock["packages"].items()
        if path and not info.get("dev") and not info.get("devOptional")
    }


def _pin(path: str, pattern: str) -> str | None:
    match = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"))
    return match.group(1) if match else None


def check_repo(report: Report) -> None:
    """Everything that can be checked from the repository alone."""
    manifest = load_manifest()
    components = manifest["components"]
    by_group: dict[str, dict[str, dict]] = {}
    for c in components:
        by_group.setdefault(c["group"], {})[
            _norm(c["name"]) if c["group"] == "python" else c["name"]
        ] = c

    # 1. The inventory matches the lockfiles (stale after a dependency change).
    python = by_group.get("python", {})
    for name, version in locked_python_packages().items():
        entry = python.get(name)
        report.check(
            entry is not None, f"Python package {name} {version} is bundled but not listed"
        )
        if entry:
            report.check(
                entry["version"] == version,
                f"{name}: lockfile has {version}, notices list {entry['version']}",
            )
    for name in set(python) - set(locked_python_packages()):
        report.fail(f"Python package {name} is listed but no longer bundled")
    # Which build ships what: the browser build is the lockfile without the desktop group.
    browser = browser_python_packages()
    for c in components:
        builds = c.get("builds")
        report.check(
            bool(builds) and set(builds) <= set(BUILDS),
            f"{c['name']}: builds must be some of {BUILDS}",
        )
        if c["group"] == "python" and builds:
            expected = _norm(c["name"]) in browser
            report.check(
                ("browser" in builds) == expected,
                f"{c['name']}: the lockfile's browser build "
                f"{'includes' if expected else 'leaves it out'}, but the notices disagree",
            )
    for name in set(browser) - set(python):
        report.fail(f"Python package {name} is in the browser build but not listed")
    for c in components:
        if any(words in c["name"] for words in ("WebView2", "Inno Setup")):
            report.check(c.get("builds") == ["desktop"], f"{c['name']} must be desktop-only")
    frontend = by_group.get("frontend", {})
    for name, version in locked_frontend_packages().items():
        entry = frontend.get(name)
        report.check(entry is not None, f"Interface package {name} {version} is not listed")
        if entry:
            report.check(
                entry["version"] == version,
                f"{name}: package-lock has {version}, notices list {entry['version']}",
            )
    for name in set(frontend) - set(locked_frontend_packages()):
        report.fail(f"Interface package {name} is listed but no longer bundled")

    # 2. The build pins the manifest was made for.
    report.check(
        _pin("packaging/build.ps1", r"pyinstaller==([\d.]+)") == manifest["pyinstaller"],
        "packaging/build.ps1 pins a different PyInstaller than the notices",
    )
    report.check(
        _pin(".github/workflows/build-windows.yml", r"python-version:\s*'([\d.]+)'")
        == manifest["python_windows"],
        "build-windows.yml installs a different Python than the notices",
    )
    report.check(
        _pin(".github/workflows/build-windows.yml", r"innosetup --version ([\d.]+)")
        == manifest["inno_setup"],
        "build-windows.yml installs a different Inno Setup than the notices",
    )
    pymupdf = python.get("pymupdf", {}).get("version", "")
    report.check(
        manifest["mupdf"].split(".")[:2] == pymupdf.split(".")[:2],
        f"MuPDF {manifest['mupdf']} doesn't look like the one inside PyMuPDF {pymupdf}",
    )

    # 3. Every listed licence file exists, and copyleft texts are complete.
    for c in components:
        report.check(bool(c["files"]), f"{c['name']} has no licence text")
        report.check(
            len(c["files"]) == len(set(c["files"])),
            f"{c['name']}: duplicate licence paths in the manifest",
        )
        for file in c["files"]:
            path = LICENSES / file
            if not path.is_file():
                report.fail(f"{c['name']}: missing licences/{file}")
                continue
            marker = COPYLEFT_MARKERS.get(path.name)
            if marker:
                text = path.read_text(encoding="utf-8", errors="replace")
                report.check(
                    marker in text and len(text) > 7000,
                    f"licenses/{file} isn't the full {marker} text",
                )
    agpl = (ROOT / "LICENSE-AGPL-3.0.txt").read_text(encoding="utf-8")
    report.check(
        "GNU AFFERO GENERAL PUBLIC LICENSE" in agpl and "END OF TERMS AND CONDITIONS" in agpl,
        "LICENSE-AGPL-3.0.txt isn't the full AGPL-3.0 text",
    )
    report.check(
        "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8"),
        "LICENSE should be the MIT grant for the original code",
    )

    # 4. Source locations for every bundled package.
    sources = manifest["sources"]
    listed = {_norm(s["component"]) for s in sources["python"]}
    for name in python:
        report.check(name in listed, f"No source location recorded for {name}")
    for s in sources["python"]:
        report.check(bool(s["url"]), f"No source URL for {s['component']}")
        if "download.qt.io" in s["url"]:
            report.check(
                ".".join(s["version"].split(".")[:3]) in s["url"],
                f"The Qt source URL for {s['component']} {s['version']} names another version",
            )
    for key in ("mupdf", "pyinstaller", "python_runtime"):
        report.check(bool(sources.get(key, {}).get("url")), f"No source URL for {key}")
        report.check(
            bool(re.fullmatch(r"[0-9a-f]{64}", sources.get(key, {}).get("sha256", ""))),
            f"No pinned SHA-256 for {key} source archive",
        )

    # 5. The notices, installer and user-facing documents.
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for c in components:
        report.check(f"| {c['name']} |" in notices, f"THIRD_PARTY_NOTICES.md lacks {c['name']}")
    browser_notices = (ROOT / "THIRD_PARTY_NOTICES-browser.md").read_text(encoding="utf-8")
    for c in components:
        listed = f"| {c['name']} |" in browser_notices
        ships = "browser" in c.get("builds", BUILDS)
        report.check(
            listed == ships,
            f"THIRD_PARTY_NOTICES-browser.md {'lacks' if ships else 'wrongly lists'} {c['name']}",
        )
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    for source in TOP_LEVEL:
        report.check(f'{{#RepoRoot}}\\{source}"' in iss, f"installer.iss doesn't install {source}")
    report.check(
        '{#RepoRoot}\\licenses\\*"' in iss and "recursesubdirs" in iss,
        "installer.iss doesn't install the whole licenses folder",
    )
    # The Visual C++ runtime isn't bundled (decision P32): the installer must check for
    # the redistributable, and must not offer to start the app without it.
    vc_runtime = installer_vc_runtime()
    report.check(
        vc_runtime is not None and {"vcruntime140.dll", "msvcp140.dll"} <= vc_runtime[0],
        "installer.iss doesn't check for the Microsoft Visual C++ Redistributable",
    )
    report.check(
        bool(re.search(r"^Filename: .*AppExeName.*Check: CanStartApp", iss, re.M))
        and "IsVCRuntimeInstalled" in iss.split("function CanStartApp", 1)[-1][:400],
        "installer.iss offers to start the app without checking for the Visual C++ runtime",
    )
    report.check(
        "Visual C++ Redistributable" in notices.split("## Not included", 1)[-1],
        "THIRD_PARTY_NOTICES.md doesn't list the Visual C++ Redistributable as not included",
    )
    if vc_runtime:
        minimum = f"{vc_runtime[1][0]}.{vc_runtime[1][1]}"
        for doc in ("THIRD_PARTY_NOTICES.md", "README.md", "packaging/README.md"):
            report.check(
                f"version {minimum} or newer" in (ROOT / doc).read_text(encoding="utf-8"),
                f"{doc} doesn't give the Visual C++ Redistributable version the installer "
                f"requires ({minimum} or newer)",
            )
    for doc in ("README.md", "LICENSING.md", "docs/releases/v0.5.0.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        report.check("AGPL-3.0" in text, f"{doc} doesn't say the distributed app is AGPL-3.0")
        report.check(
            not re.search(r"(app|application) is (released )?(under )?(the )?MIT", text, re.I),
            f"{doc} describes the app as MIT-licensed",
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pe_imports(path: Path) -> tuple[list[str], tuple[int, int]] | None:
    """Read the DLLs a Windows binary imports, and the linker version that built it.

    Covers normal and delay-loaded imports. Pure Python, so it also runs on Linux.

    Args:
        path: A ``.dll``, ``.pyd`` or ``.exe`` file.

    Returns:
        ``(lower-case DLL names, (linker major, linker minor))``, or None when the file
        isn't a readable PE image.
    """
    data = path.read_bytes()
    try:
        if data[:2] != b"MZ":
            return None
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe : pe + 4] != b"PE\0\0":
            return None
        sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
        optional = pe + 24
        magic, major, minor = struct.unpack_from("<HBB", data, optional)
        directories = optional + (112 if magic == 0x20B else 96)
        table = []
        for i in range(sections):
            size, address, raw_size, raw = struct.unpack_from(
                "<IIII", data, optional + optional_size + 40 * i + 8
            )
            table.append((address, max(size, raw_size), raw))

        def offset(rva: int) -> int | None:
            for address, size, raw in table:
                if address <= rva < address + size:
                    return rva - address + raw
            return None

        names = []
        # Data directory 1: imports (20-byte entries, name at 12); 13: delay-load
        # imports (32-byte entries, name at 4).
        for index, entry_size, name_at in ((1, 20, 12), (13, 32, 4)):
            rva = struct.unpack_from("<I", data, directories + 8 * index)[0]
            at = offset(rva) if rva else None
            while at is not None and at + entry_size <= len(data):
                entry = data[at : at + entry_size]
                if not any(entry):
                    break
                name = offset(struct.unpack_from("<I", entry, name_at)[0])
                if name is not None:
                    names.append(data[name : data.index(b"\0", name)].decode("latin-1").lower())
                at += entry_size
        return names, (major, minor)
    except (struct.error, ValueError):
        return None


def installer_vc_runtime() -> tuple[set[str], tuple[int, int]] | None:
    """What ``packaging/installer.iss`` checks for before it lets the app start.

    Returns:
        ``(DLL names it looks for in System32, (minimum major, minor version))``, or
        None when the installer has no Visual C++ Redistributable check.
    """
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    files = re.search(r"VCRuntimeFiles\s*=\s*'([^']+)'", iss)
    major = re.search(r"VCRuntimeMinMajor\s*=\s*(\d+)", iss)
    minor = re.search(r"VCRuntimeMinMinor\s*=\s*(\d+)", iss)
    if not (files and major and minor):
        return None
    names = {name.strip().lower() for name in files.group(1).split(",") if name.strip()}
    return names, (int(major.group(1)), int(minor.group(1)))


def classify(relative: str) -> str | None:
    """The component a native file in the Windows app belongs to, or None."""
    lower = relative.lower()
    for pattern, component in BINARY_RULES:
        if fnmatch.fnmatch(lower, pattern):
            return component
    if lower.startswith("_internal/") and lower.count("/") == 1:
        name = lower.removeprefix("_internal/")
        if any(fnmatch.fnmatch(name, p) for p in RUNTIME_FILES):
            return "PYTHON RUNTIME"
    return None


def check_bundle(report: Report, app: Path, installed: bool, build: str = "desktop") -> None:
    """Check a built (``dist/PDF Manager``) or installed Windows app folder.

    Args:
        report: Collects the failures.
        app: The app folder.
        installed: Also compare the licence files next to the app with the repository's.
        build: ``"desktop"`` (the installer's app) or ``"browser"`` (the browser-mode
            ZIP, which must contain nothing of the desktop window's toolkit).
    """
    manifest = load_manifest()
    shipped = components_for(manifest, build)
    names = {_norm(c["name"]) for c in shipped if c["group"] == "python"}
    desktop_only = {
        _norm(c["name"]) for c in manifest["components"] if c.get("builds") == ["desktop"]
    }
    report.check((app / "PDF Manager.exe").is_file(), f"No PDF Manager.exe in {app}")
    internal = app / "_internal"

    # Every native file belongs to a listed component.
    unknown = []
    counts: dict[str, int] = {}
    # Visual C++ runtime DLLs the bundled binaries import, and who imports them.
    needed: dict[str, str] = {}
    newest: tuple[tuple[int, int], str] = ((0, 0), "")
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in NATIVE:
            continue
        relative = path.relative_to(app).as_posix()
        info = pe_imports(path) if not VC_RUNTIME_DLL.match(path.name) else None
        if info:
            runtime = [name for name in info[0] if VC_RUNTIME_DLL.match(name)]
            for name in runtime:
                needed.setdefault(name, relative)
            if runtime and info[1] > newest[0]:
                newest = (info[1], relative)
        component = classify(relative)
        if component is None:
            unknown.append(relative)
            continue
        counts[component] = counts.get(component, 0) + 1
        print(f"  {relative}: {component}")
        if build == "browser" and (component in DESKTOP_ONLY or _norm(component) in desktop_only):
            report.fail(f"{relative}: {component} belongs to the desktop build only")
        elif component not in NON_PACKAGE:
            report.check(_norm(component) in names, f"{relative}: {component} isn't listed")
    for relative in unknown:
        report.fail(f"{relative} belongs to no listed component; add its notice")
    listed = " ".join(c["name"] for c in manifest["components"])
    for component, words in NON_PACKAGE.items():
        if counts.get(component) and not (build == "browser" and component in DESKTOP_ONLY):
            report.check(words in listed, f"The notices don't list the {component.lower()}")
    print("Native files by component:", json.dumps(counts, sort_keys=True))

    # Microsoft runtime files must not be shipped (see pdf-manager.spec): Windows
    # provides the Universal C Runtime, and the separately installed Microsoft Visual C++
    # Redistributable provides the Visual C++ runtime (decision P32).
    for path in sorted(app.rglob("*")):
        relative = path.relative_to(app).as_posix()
        if WINDOWS_PROVIDED_DLL.match(path.name):
            report.fail(f"{relative} shouldn't be bundled: Windows provides it")
        elif VC_RUNTIME_DLL.match(path.name):
            report.fail(
                f"{relative} shouldn't be bundled: the Microsoft Visual C++ "
                "Redistributable provides it (exclude it in pdf-manager.spec)"
            )

    # What the app needs from the redistributable is what the installer checks for.
    vc_runtime = installer_vc_runtime()
    if vc_runtime is None:
        report.fail("installer.iss doesn't check for the Microsoft Visual C++ Redistributable")
    else:
        checked, minimum = vc_runtime
        for name, importer in sorted(needed.items()):
            report.check(
                name in checked,
                f"{importer} needs {name} from the Visual C++ Redistributable, but "
                "installer.iss doesn't check for it (VCRuntimeFiles)",
            )
        (major, minor), importer = newest
        report.check(
            (major, minor) <= minimum,
            f"{importer} was linked by MSVC {major}.{minor}, newer than the Visual C++ "
            f"Redistributable installer.iss requires ({minimum[0]}.{minimum[1]}); raise "
            "VCRuntimeMinMajor/VCRuntimeMinMinor",
        )
        print(
            "Needs from the Microsoft Visual C++ Redistributable:",
            ", ".join(sorted(needed)) or "nothing",
            f"(newest MSVC linker {major}.{minor}, in {importer or '-'}; the installer "
            f"requires {minimum[0]}.{minimum[1]} or newer)",
        )

    # Qt is Linux-only (decision P19).
    qt = [
        p.name for p in app.rglob("*") if re.match(r"(qt6.*\.dll|pyside6|shiboken6)$", p.name, re.I)
    ]
    report.check(not qt, f"Qt/PySide6 files in the Windows app: {qt[:5]}")

    # The WebView2 SDK files are exactly the ones whose licence we ship.
    for in_wheel, sha in (manifest["webview2_sdk"]["sha256"] if build == "desktop" else {}).items():
        path = internal / in_wheel
        report.check(path.is_file(), f"Missing {in_wheel}")
        if path.is_file():
            report.check(
                _sha256(path) == sha,
                f"{in_wheel} isn't the Microsoft.Web.WebView2 "
                f"{manifest['webview2_sdk']['version']} file; regenerate the notices",
            )

    # Every bundled Python distribution is listed.
    for info in internal.glob("*.dist-info"):
        name = _norm(info.name.rsplit("-", 1)[0])
        report.check(name in names, f"Bundled Python package {name} isn't listed")

    # The bundled Python is the one whose licence we ship. The bundle is built by
    # (and this check runs under) the project's uv environment.
    version = sys.version.split()[0]
    expected = manifest["python_windows"]
    if sys.platform == "win32":
        report.check(
            version == expected,
            f"The build used Python {version}, but the notices are for {expected}",
        )
        ours = LICENSES / "other" / f"python-runtime-windows-{expected}" / "LICENSE.txt"
        theirs = Path(sys.base_prefix) / "LICENSE.txt"
        if theirs.is_file() and ours.is_file():
            report.check(
                theirs.read_bytes().replace(b"\r\n", b"\n")
                == ours.read_bytes().replace(b"\r\n", b"\n"),
                f"{theirs} differs from the Python licence we ship",
            )

    # The licence files next to the installed app are the repository's.
    if installed:
        for source, name in (BROWSER_TOP_LEVEL if build == "browser" else TOP_LEVEL).items():
            target = app / name
            report.check(target.is_file(), f"Installed app lacks {name}")
            if target.is_file():
                report.check(_sha256(target) == _sha256(ROOT / source), f"{name} differs")
        # The installer copies the whole licenses/ folder; the browser ZIP exactly the
        # licence texts of the components it ships (scripts/stage_licenses.py).
        if build == "browser":
            wanted = {f"licenses/{f}" for f in licence_files(manifest, build)}
        else:
            wanted = {p.relative_to(ROOT).as_posix() for p in LICENSES.rglob("*") if p.is_file()}
        for relative in sorted(wanted):
            target = app / relative
            report.check(target.is_file(), f"Installed app lacks {relative}")
            if target.is_file():
                report.check(_sha256(target) == _sha256(ROOT / relative), f"{relative} differs")
        extra = [
            p.relative_to(app).as_posix()
            for p in (app / "licenses").rglob("*")
            if p.is_file() and p.relative_to(app).as_posix() not in wanted
        ]
        report.check(not extra, f"Stale licence files in the installed app: {extra[:5]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("repo", help="check the repository's inventory (no network)")
    bundle = sub.add_parser("bundle", help="check a built or installed Windows app folder")
    bundle.add_argument("app", type=Path)
    bundle.add_argument("--installed", action="store_true", help="also compare licence files")
    bundle.add_argument(
        "--build", choices=BUILDS, default="desktop", help="which build the folder is"
    )
    args = parser.parse_args(argv)
    report = Report()
    if args.mode == "repo":
        check_repo(report)
        return report.finish("repository")
    check_bundle(report, args.app, args.installed, args.build)
    return report.finish(f"app at {args.app}")


if __name__ == "__main__":
    sys.exit(main())
