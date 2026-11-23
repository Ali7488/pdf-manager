"""Collect the licences of everything bundled into PDF Manager, and write the notices file.

    uv run scripts/collect_licenses.py

Writes (both committed, and shipped next to the installed app):

* ``licenses/<component>/``: the licence files each bundled component ships
  with. Python packages are read from the installed package, or, when they're
  only used on another platform (for example Windows-only packages when this
  runs on Linux), from their official wheel on PyPI. Components that ship no
  licence file get the official text of their declared licence from the SPDX
  licence list.
* ``THIRD_PARTY_NOTICES.md``: one table of every bundled component, its version,
  its licence and the platforms it is bundled on.

Only *runtime* dependencies that are bundled on Windows or Linux are included
(macOS-only packages, development tools and test libraries are not shipped).
"""

from __future__ import annotations

import importlib.metadata as md
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSES = ROOT / "licenses"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
FRONTEND = ROOT / "frontend"
SPDX_TEXT = "https://raw.githubusercontent.com/spdx/license-list-data/main/text/{}.txt"
# Must match packaging/build.ps1 (its bootloader is part of the built app).
PYINSTALLER_VERSION = "6.22.3"
# Copyleft licences: always ship the full official text, even when a package
# ships its own (short or partial) licence file. PyMuPDF's COPYING is one line.
COPYLEFT = {"AGPL-3.0-only", "GPL-3.0-only", "LGPL-3.0-only", "GPL-2.0-only"}
LICENSE_NAME = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/]*$", re.IGNORECASE)

# Declared licences that need a normalized SPDX id (metadata is free text).
SPDX_FROM_TEXT = {
    "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License": "AGPL-3.0-only",
    "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only": "LGPL-3.0-only",
}
# Packages whose metadata has no usable licence field; checked by hand against the
# licence file each one ships (clr-loader's LICENSE is the MIT License).
KNOWN_LICENSE = {"proxy-tools": "MIT", "clr-loader": "MIT"}
# The LGPL-3.0 is a set of extra permissions on top of the GPL-3.0, so its text
# must be shipped together with the GPL-3.0 text.
ALSO_SHIP = {"LGPL-3.0-only": ["GPL-3.0-only"]}


@dataclass
class Component:
    """One bundled third-party component."""

    name: str
    version: str
    license: str
    platforms: set[str] = field(default_factory=set)
    used_for: str = ""
    files: list[str] = field(default_factory=list)


def runtime_python_packages() -> dict[str, tuple[str, set[str]]]:
    """Runtime packages from the lockfile: name → (version, platforms bundled on)."""
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
        name, _, version = spec.strip().partition("==")
        platforms = {"windows", "linux"}
        if "sys_platform == 'win32'" in marker or 'sys_platform == "win32"' in marker:
            platforms = {"windows"}
        elif "sys_platform == 'linux'" in marker or 'sys_platform == "linux"' in marker:
            platforms = {"linux"}
        elif "sys_platform == 'darwin'" in marker or 'sys_platform == "darwin"' in marker:
            continue  # macOS only: never bundled in the Windows or Linux builds.
        elif "platform_system == 'Windows'" in marker:
            platforms = {"windows"}
        packages[name.lower()] = (version, platforms)
    return packages


def _license_from_metadata(meta) -> str:
    """Best licence identifier from package metadata."""
    expression = meta.get("License-Expression")
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) < 80:
        return SPDX_FROM_TEXT.get(text, text)
    if text.startswith("BSD 3-Clause"):
        return "BSD-3-Clause"
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License :: OSI Approved :: "):
            name = classifier.rsplit(" :: ", 1)[1]
            return {
                "MIT License": "MIT",
                "BSD License": "BSD-3-Clause",
                "Python Software Foundation License": "PSF-2.0",
                "Apache Software License": "Apache-2.0",
            }.get(name, name)
    return SPDX_FROM_TEXT.get(text, "UNKNOWN")


def _from_installed(name: str, target: Path) -> tuple[str, list[str]] | None:
    """Licence id and copied files from an installed distribution, or None."""
    try:
        dist = md.distribution(name)
    except md.PackageNotFoundError:
        return None
    copied = []
    for file in dist.files or []:
        if LICENSE_NAME.search(str(file)) and not str(file).endswith(".py"):
            source = Path(dist.locate_file(file))
            if source.is_file():
                target.mkdir(parents=True, exist_ok=True)
                dest = target / Path(str(file)).name
                shutil.copyfile(source, dest)
                copied.append(dest.name)
    return _license_from_metadata(dist.metadata), copied


def _from_wheel(name: str, version: str, platform: str, target: Path) -> tuple[str, list[str]]:
    """Licence id and copied files from the package's official wheel on PyPI."""
    tag = {"windows": "win_amd64", "linux": "manylinux2014_x86_64"}[platform]
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                f"{name}=={version}",
                "--no-deps",
                "--only-binary=:all:",
                "--platform",
                tag,
                "--python-version",
                "3.13",
                "--implementation",
                "cp",
                "--dest",
                tmp,
                "--quiet",
            ],
            check=True,
        )
        wheel = next(Path(tmp).glob("*.whl"))
        copied, meta_text = [], ""
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.namelist():
                if member.endswith(".dist-info/METADATA"):
                    meta_text = archive.read(member).decode("utf-8", "replace")
                elif ".dist-info/" in member and LICENSE_NAME.search(member):
                    target.mkdir(parents=True, exist_ok=True)
                    dest = target / Path(member).name
                    dest.write_bytes(archive.read(member))
                    copied.append(dest.name)
    from email.parser import Parser

    return _license_from_metadata(Parser().parsestr(meta_text)), copied


def _standard_text(spdx: str, target: Path) -> list[str]:
    """Fetch the official text of an SPDX licence into ``target``."""
    ids = [part.strip("() ") for part in re.split(r"\s+(?:OR|AND)\s+", spdx)]
    ids += [extra for spdx_id in list(ids) for extra in ALSO_SHIP.get(spdx_id, [])]
    copied = []
    for spdx_id in ids:
        if not spdx_id or spdx_id == "UNKNOWN":
            continue
        with urllib.request.urlopen(SPDX_TEXT.format(spdx_id), timeout=60) as response:
            text = response.read()
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{spdx_id}.txt").write_bytes(text)
        copied.append(f"{spdx_id}.txt")
    return copied


def python_components() -> list[Component]:
    """Every bundled Python package with its licence files."""
    components = []
    for name, (version, platforms) in sorted(runtime_python_packages().items()):
        target = LICENSES / "python" / f"{name}-{version}"
        found = _from_installed(name, target)
        if found is None:
            found = _from_wheel(name, version, sorted(platforms)[0], target)
        spdx, files = found
        spdx = KNOWN_LICENSE.get(name, spdx)
        ids = set(re.split(r"\s+(?:OR|AND)\s+", spdx))
        if not files or ids & COPYLEFT:
            files += [f for f in _standard_text(spdx, target) if f not in files]
        components.append(
            Component(
                name,
                version,
                spdx,
                platforms,
                files=[f"python/{name}-{version}/{f}" for f in files],
            )
        )
    return components


def frontend_components() -> list[Component]:
    """Every runtime npm package inlined into the UI, with its licence files."""
    out = subprocess.run(
        ["npm", "ls", "--omit=dev", "--all", "--json"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    seen: dict[str, Component] = {}

    def walk(deps: dict) -> None:
        for name, info in (deps or {}).items():
            version = info.get("version", "")
            if name not in seen:
                folder = FRONTEND / "node_modules" / name
                meta = json.loads((folder / "package.json").read_text(encoding="utf-8"))
                target = LICENSES / "frontend" / f"{name.replace('/', '__')}-{version}"
                files = []
                for source in sorted(folder.iterdir()):
                    if source.is_file() and LICENSE_NAME.search(source.name):
                        target.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target / source.name)
                        files.append(source.name)
                spdx = meta.get("license") or "UNKNOWN"
                if not files:
                    files = _standard_text(spdx, target)
                rel = f"frontend/{target.name}"
                seen[name] = Component(
                    name, version, spdx, {"windows", "linux"}, files=[f"{rel}/{f}" for f in files]
                )
            walk(info.get("dependencies"))

    walk(json.loads(out).get("dependencies"))
    return sorted(seen.values(), key=lambda c: c.name)


# Short descriptions of what each notable component is used for.
USED_FOR = {
    "pymupdf": "All PDF work (rendering, OCR placement, merging, splitting, compressing)",
    "pywebview": "The desktop window and the JavaScript ↔ Python bridge",
    "pythonnet": "Edge WebView2 window on Windows (via pywebview)",
    "clr-loader": "Loads .NET for pythonnet",
    "pywin32": "Optional Microsoft PowerPoint automation on Windows",
    "pyside6": "Qt window on Linux (via pywebview)",
    "react": "User interface",
    "react-dom": "User interface",
    "@dnd-kit/core": "Drag to reorder files",
    "@dnd-kit/sortable": "Drag to reorder files",
    "@fontsource-variable/open-sans": "Bundled font (Open Sans)",
}


def other_components() -> list[Component]:
    """Parts of the built app that aren't Python or npm packages."""
    out = []
    # The Python runtime (PyInstaller bundles it). Its LICENSE.txt also covers the
    # third-party software CPython itself incorporates.
    runtime = (
        Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    )
    for candidate in (runtime / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"):
        if candidate.is_file():
            target = LICENSES / "other" / "python-runtime"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate, target / "LICENSE.txt")
            version = f"{sys.version_info.major}.{sys.version_info.minor}"
            out.append(
                Component(
                    "Python runtime",
                    version,
                    "PSF-2.0",
                    {"windows", "linux"},
                    "Runs the app (bundled by PyInstaller)",
                    ["other/python-runtime/LICENSE.txt"],
                )
            )
            break
    # PyInstaller's bootloader is linked into the app's executable.
    target = LICENSES / "other" / f"pyinstaller-{PYINSTALLER_VERSION}"
    _, files = _from_wheel("pyinstaller", PYINSTALLER_VERSION, "windows", target)
    out.append(
        Component(
            "PyInstaller bootloader",
            PYINSTALLER_VERSION,
            "GPL-2.0-or-later WITH Bootloader-exception",
            {"windows", "linux"},
            "Starts the app; the exception allows any licence for the app",
            [f"other/{target.name}/{f}" for f in files],
        )
    )
    # Icons: drawn inline in frontend/src/components/Icon/Icon.tsx. The settings
    # gear closely follows Feather Icons' design, so Feather is credited.
    target = LICENSES / "other" / "feather-icons"
    target.mkdir(parents=True, exist_ok=True)
    mit = urllib.request.urlopen(SPDX_TEXT.format("MIT"), timeout=60).read().decode()
    (target / "LICENSE").write_text(
        mit.replace("<year>", "2013-2017").replace("<copyright holders>", "Cole Bemis"),
        encoding="utf-8",
    )
    out.append(
        Component(
            "Feather Icons (design of some icons)",
            "4.x",
            "MIT",
            {"windows", "linux"},
            "Some interface icon shapes",
            ["other/feather-icons/LICENSE"],
        )
    )
    # Microsoft WebView2 SDK binaries, shipped inside pywebview's Windows wheel.
    out.append(
        Component(
            "Microsoft WebView2 SDK binaries (Microsoft.Web.WebView2.Core.dll, "
            "Microsoft.Web.WebView2.WinForms.dll, WebView2Loader.dll)",
            "bundled with pywebview",
            "Microsoft (see note)",
            {"windows"},
            "Edge WebView2 window on Windows",
            [],
        )
    )
    return out


def write_notices(
    python: list[Component], frontend: list[Component], other: list[Component]
) -> None:
    """Write THIRD_PARTY_NOTICES.md."""

    def rows(components: list[Component]) -> list[str]:
        out = []
        for c in components:
            where = ", ".join(sorted(p.capitalize() for p in c.platforms))
            files = ", ".join(f"[`{Path(f).name}`](licenses/{f})" for f in c.files) or "—"
            used = c.used_for or USED_FOR.get(c.name, "")
            out.append(f"| {c.name} | {c.version} | {c.license} | {where} | {used} | {files} |")
        return out

    header = (
        "| Component | Version | Licence | Bundled on | Used for | Licence text |\n"
        "| --- | --- | --- | --- | --- | --- |"
    )
    text = f"""# Third-party notices

PDF Manager's own code is released under the [MIT License](LICENSE), © 2026 Mohannad Ali.

The distributed app (the Windows installer and the Linux packages) also includes the
open-source components below. Each keeps its own licence; the licence texts are in the
[`licenses/`](licenses) folder, which is installed next to the app.

**PyMuPDF is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)**, or
a commercial licence from Artifex. Because the distributed app includes PyMuPDF, the
app as a whole is distributed under the terms of the AGPL-3.0. Its complete source code
is available at <https://github.com/Ali7488/pdf-manager>.

This file is generated by `scripts/collect_licenses.py` from the packages actually
bundled; regenerate it whenever dependencies change. It is not legal advice.

## Python packages (the app's engine and window)

{header}
{chr(10).join(rows(python))}

## Interface packages (inlined into the app's single HTML file)

{header}
{chr(10).join(rows(frontend))}

## Also included in the built app

{header}
{chr(10).join(rows(other))}

**Note on the Microsoft WebView2 SDK binaries:** these closed-source Microsoft
files come inside pywebview's Windows wheel and talk to the WebView2 Runtime that
is part of Windows 11. They are redistributed under Microsoft's WebView2 SDK
licence; check that licence, and how it fits with the AGPL-3.0 (for example under
the AGPL's "System Libraries" provision), before relying on this notice.

## Not included (installed separately, by the user or the installer wizard)

| Program | Licence | Notes |
| --- | --- | --- |
| Tesseract OCR | Apache-2.0 | Optional; installed with winget or the system package manager. |
| LibreOffice | MPL-2.0 | Optional; installed separately. |
| Microsoft PowerPoint | Proprietary | Optional; used only if already installed. |
| Microsoft Edge WebView2 Runtime | Microsoft software licence | Part of Windows 11. |
| Segoe UI font | Proprietary | Used only if Windows provides it; never bundled. |
"""
    NOTICES.write_text(text, encoding="utf-8")


def main() -> int:
    if LICENSES.exists():
        shutil.rmtree(LICENSES)
    python = python_components()
    frontend = frontend_components()
    other = other_components()
    write_notices(python, frontend, other)
    print(f"{len(python)} Python and {len(frontend)} interface components; see {NOTICES.name}")
    unknown = [c.name for c in python + frontend + other if c.license == "UNKNOWN"]
    if unknown:
        print("WARNING: unknown licence for:", ", ".join(unknown))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
