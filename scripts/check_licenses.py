"""Check that PDF Manager's licence inventory is complete and up to date.

    uv run scripts/check_licenses.py repo
    uv run scripts/check_licenses.py bundle "dist/PDF Manager"
    uv run scripts/check_licenses.py bundle "%LOCALAPPDATA%/Programs/PDF Manager" --installed

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
app must be byte-identical to the repository's.

Exit code 0 means every check passed; 1 lists the failures. It doesn't decide legal
questions: see LICENSING.md and docs/LICENSING_AUDIT_2026-11-23.md for those.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
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
    ("_internal/vcruntime140*.dll", "MSVC RUNTIME"),
    ("_internal/msvcp140*.dll", "MSVC RUNTIME"),
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
    "MSVC RUNTIME": "Visual C++ runtime",
    "PyInstaller bootloader": "PyInstaller bootloader",
    "INNO SETUP": "Inno Setup",
}


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


def locked_python_packages() -> dict[str, str]:
    """Runtime packages bundled on Windows or Linux, from ``uv export`` of uv.lock."""
    out = subprocess.run(
        ["uv", "export", "--no-dev", "--frozen", "--no-hashes", "--no-emit-project"],
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

    # 5. The notices, installer and user-facing documents.
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for c in components:
        report.check(f"| {c['name']} |" in notices, f"THIRD_PARTY_NOTICES.md lacks {c['name']}")
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    for source in TOP_LEVEL:
        report.check(f'{{#RepoRoot}}\\{source}"' in iss, f"installer.iss doesn't install {source}")
    report.check(
        '{#RepoRoot}\\licenses\\*"' in iss and "recursesubdirs" in iss,
        "installer.iss doesn't install the whole licenses folder",
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


def check_bundle(report: Report, app: Path, installed: bool) -> None:
    """Check a built (``dist/PDF Manager``) or installed Windows app folder."""
    manifest = load_manifest()
    names = {_norm(c["name"]) for c in manifest["components"] if c["group"] == "python"}
    report.check((app / "PDF Manager.exe").is_file(), f"No PDF Manager.exe in {app}")
    internal = app / "_internal"

    # Every native file belongs to a listed component.
    unknown = []
    counts: dict[str, int] = {}
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in NATIVE:
            continue
        relative = path.relative_to(app).as_posix()
        component = classify(relative)
        if component is None:
            unknown.append(relative)
            continue
        counts[component] = counts.get(component, 0) + 1
        print(f"  {relative}: {component}")
        if component not in NON_PACKAGE:
            report.check(_norm(component) in names, f"{relative}: {component} isn't listed")
    for relative in unknown:
        report.fail(f"{relative} belongs to no listed component; add its notice")
    listed = " ".join(c["name"] for c in manifest["components"])
    for component, words in NON_PACKAGE.items():
        if counts.get(component):
            report.check(words in listed, f"The notices don't list the {component.lower()}")
    print("Native files by component:", json.dumps(counts, sort_keys=True))

    # Microsoft files Windows provides itself must not be shipped (see pdf-manager.spec).
    for path in app.rglob("*"):
        if re.match(r"(ucrtbase|api-ms-win-.*|mfc140u)\.dll$", path.name, re.I):
            report.fail(f"{path.relative_to(app).as_posix()} shouldn't be bundled")

    # Qt is Linux-only (decision P19).
    qt = [
        p.name for p in app.rglob("*") if re.match(r"(qt6.*\.dll|pyside6|shiboken6)$", p.name, re.I)
    ]
    report.check(not qt, f"Qt/PySide6 files in the Windows app: {qt[:5]}")

    # The WebView2 SDK files are exactly the ones whose licence we ship.
    for in_wheel, sha in manifest["webview2_sdk"]["sha256"].items():
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
        for source, name in TOP_LEVEL.items():
            target = app / name
            report.check(target.is_file(), f"Installed app lacks {name}")
            if target.is_file():
                report.check(_sha256(target) == _sha256(ROOT / source), f"{name} differs")
        for path in sorted(LICENSES.rglob("*")):
            if path.is_file():
                relative = path.relative_to(ROOT)
                target = app / relative
                report.check(target.is_file(), f"Installed app lacks {relative.as_posix()}")
                if target.is_file():
                    report.check(_sha256(target) == _sha256(path), f"{relative.as_posix()} differs")
        extra = [
            p.relative_to(app).as_posix()
            for p in (app / "licenses").rglob("*")
            if p.is_file() and not (ROOT / p.relative_to(app)).is_file()
        ]
        report.check(not extra, f"Stale licence files in the installed app: {extra[:5]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("repo", help="check the repository's inventory (no network)")
    bundle = sub.add_parser("bundle", help="check a built or installed Windows app folder")
    bundle.add_argument("app", type=Path)
    bundle.add_argument("--installed", action="store_true", help="also compare licence files")
    args = parser.parse_args(argv)
    report = Report()
    if args.mode == "repo":
        check_repo(report)
        return report.finish("repository")
    check_bundle(report, args.app, args.installed)
    return report.finish(f"app at {args.app}")


if __name__ == "__main__":
    sys.exit(main())
