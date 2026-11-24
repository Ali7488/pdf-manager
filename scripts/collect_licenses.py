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
* ``licenses/manifest.json``: the same inventory in machine-readable form, plus the
  exact versions and checksums ``scripts/check_licenses.py`` uses to detect a stale
  inventory (in CI) and to check a built or installed app against it.

Besides the Python and npm packages it covers the parts that aren't packages: the
Windows Python runtime (python.org build, the exact version the Windows build
uses), the PyInstaller bootloader, the Microsoft WebView2 SDK files inside
pywebview (licence and notice from Microsoft's matching NuGet package, checked
byte-for-byte against pywebview's copies), and MuPDF with the third-party
libraries and fonts it compiles into PyMuPDF (licence files from the exact MuPDF
source release). Downloads are cached in ``build/license-cache``.

Only *runtime* dependencies that are bundled on Windows or Linux are included
(macOS-only packages, development tools and test libraries are not shipped).
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSES = ROOT / "licenses"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
# The notices of the browser-mode ZIP (PDF Manager in the user's own browser),
# which ships a subset of the components: no window toolkit, no installer.
BROWSER_NOTICES = ROOT / "THIRD_PARTY_NOTICES-browser.md"
BUILDS = ("desktop", "browser")
FRONTEND = ROOT / "frontend"
SPDX_TEXT = "https://raw.githubusercontent.com/spdx/license-list-data/main/text/{}.txt"
MANIFEST = LICENSES / "manifest.json"
CACHE = ROOT / "build" / "license-cache"
# Must match packaging/build.ps1 (its bootloader is part of the built app).
PYINSTALLER_VERSION = "6.22.3"
# The python.org CPython the Windows build bundles. Must match
# .github/workflows/build-windows.yml; scripts/check_licenses.py fails the build
# when the bundled interpreter is a different version.
PYTHON_WINDOWS_VERSION = "3.13.17"
FEATHER_VERSION = "v4.29.2"

# Libraries the python.org Windows build of PYTHON_WINDOWS_VERSION compiles in or ships
# as DLLs, from source that isn't in CPython's tarball: CPython fetches it from
# python/cpython-source-deps at these tags (PCbuild/get_externals.bat). The corresponding
# source bundle includes them (decision P42 follow-up; the owner's artifact review).
# (name, version, cpython-source-deps tag, SHA-256 of GitHub's tag archive, shipped in)
RUNTIME_EXTERNALS = [
    (
        "OpenSSL",
        "3.5.9",
        "openssl-3.5.9",
        "d6cf0d9a651f25fe506f6b3dc133a80b9b79a0bc565f570dcf8fdbd597551485",
        "libssl-3.dll, libcrypto-3.dll",
    ),
    (
        "libffi",
        "3.4.4",
        "libffi-3.4.4",
        "9d802681adfea27d84cae0487a785fb9caa925bdad44c401b364c59ab2b8edda",
        "libffi-8.dll",
    ),
    (
        "bzip2",
        "1.0.8",
        "bzip2-1.0.8",
        "ab8d1b0cc087c20d4c32c0e4fcf7d0c733a95da12cedc6d63b3f0a9af07427e2",
        "_bz2.pyd",
    ),
    (
        "xz (liblzma)",
        "5.2.5",
        "xz-5.2.5",
        "a15c168e39e87d750c3dc766edc7f19bdda57dacf01e509678467eace91ad282",
        "_lzma.pyd",
    ),
    (
        "mpdecimal",
        "4.0.0",
        "mpdecimal-4.0.0",
        "338fac3fb8cdd60f406b6326431338756f58a8af94229ffd9bf1e7c2b1ad71ca",
        "_decimal.pyd",
    ),
    (
        "zlib",
        "1.3.1",
        "zlib-1.3.1",
        "e3f3fb32564952006eb18b091ca8464740e5eca29d328cfb0b2da22768e0b638",
        "python313.dll",
    ),
]


def runtime_external_sources() -> list[dict]:
    """Source archives of the libraries inside the python.org Windows runtime."""
    return [
        {
            "component": (
                f"{name} {version} (in the Python {PYTHON_WINDOWS_VERSION} runtime: {where})"
            ),
            "url": f"https://github.com/python/cpython-source-deps/archive/refs/tags/{tag}.tar.gz",
            "sha256": sha256,
        }
        for name, version, tag, sha256, where in RUNTIME_EXTERNALS
    ]


# The Inno Setup compiler the Windows build installs (build-windows.yml). Its
# uninstaller (unins000.exe) is installed next to the app.
INNO_SETUP_VERSION = "6.7.1"
# The Microsoft.Web.WebView2 NuGet release whose DLLs pywebview ships.
WEBVIEW2_SDK_VERSION = "1.0.3856.49"
WEBVIEW2_DLLS = {
    # path inside pywebview's wheel: path inside the NuGet package
    "webview/lib/Microsoft.Web.WebView2.Core.dll": "lib/net462/Microsoft.Web.WebView2.Core.dll",
    "webview/lib/Microsoft.Web.WebView2.WinForms.dll": (
        "lib/net462/Microsoft.Web.WebView2.WinForms.dll"
    ),
    "webview/lib/runtimes/win-x64/native/WebView2Loader.dll": "build/native/x64/WebView2Loader.dll",
    "webview/lib/runtimes/win-x86/native/WebView2Loader.dll": "build/native/x86/WebView2Loader.dll",
    "webview/lib/runtimes/win-arm64/native/WebView2Loader.dll": (
        "build/native/arm64/WebView2Loader.dll"
    ),
}
# Third-party code MuPDF compiles into PyMuPDF, from MuPDF's thirdparty/ and
# resources/fonts/ folders: folder -> (name, licence, licence files in that folder).
# curl and freeglut are left out: MuPDF uses them only in its own viewer apps, and
# PyMuPDF's Windows library shows no trace of either. Including a notice for a
# library that turns out not to be compiled in is harmless; missing one is not.
MUPDF_PARTS = {
    "thirdparty/brotli": ("Brotli", "MIT", ["LICENSE"]),
    "thirdparty/cmark-gfm": ("cmark-gfm", "BSD-2-Clause and others (see COPYING)", ["COPYING"]),
    "thirdparty/extract": ("extract (Artifex)", "AGPL-3.0", ["COPYING"]),
    "thirdparty/freetype": ("FreeType", "FTL OR GPL-2.0-or-later", ["LICENSE.TXT", "docs/FTL.TXT"]),
    "thirdparty/gumbo-parser": ("Gumbo HTML parser", "Apache-2.0", ["COPYING"]),
    "thirdparty/harfbuzz": ("HarfBuzz", 'MIT ("Old MIT")', ["COPYING"]),
    "thirdparty/jbig2dec": ("jbig2dec (Artifex)", "AGPL-3.0-or-later", ["LICENSE", "COPYING"]),
    "thirdparty/lcms2": ("Little CMS (lcms2mt)", "MIT", ["LICENSE"]),
    "thirdparty/leptonica": ("Leptonica", "BSD-2-Clause", ["leptonica-license.txt"]),
    "thirdparty/libjpeg": ("IJG libjpeg", "IJG (see LEGAL ISSUES in README)", ["README"]),
    "thirdparty/mujs": ("MuJS (Artifex)", "ISC", ["COPYING"]),
    "thirdparty/openjpeg": ("OpenJPEG", "BSD-2-Clause", ["LICENSE"]),
    "thirdparty/tesseract": ("Tesseract OCR engine (library)", "Apache-2.0", ["LICENSE"]),
    "thirdparty/zint": ("Zint barcode library (backend)", "BSD-3-Clause", ["LICENSE"]),
    "thirdparty/zlib": ("zlib", "Zlib", ["LICENSE"]),
    "thirdparty/zxing-cpp": ("ZXing-C++", "Apache-2.0", ["LICENSE"]),
    "resources/fonts/droid": ("Droid fonts", "Apache-2.0", ["NOTICE"]),
    "resources/fonts/han": ("Source Han fonts", "OFL-1.1", ["LICENSE.txt"]),
    "resources/fonts/noto": ("Noto fonts", "OFL-1.1", ["COPYING"]),
    "resources/fonts/sil": ("Charis SIL font", "OFL-1.1", ["OFL.txt"]),
}
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
    group: str = ""
    # Which builds ship it: the desktop installer and/or the browser-mode ZIP.
    builds: set[str] = field(default_factory=lambda: set(BUILDS))


def runtime_python_packages(*extra: str) -> dict[str, tuple[str, set[str]]]:
    """Runtime packages from the lockfile: name → (version, platforms bundled on).

    Args:
        *extra: More ``uv export`` options; ``"--no-group", "desktop"`` gives
            browser mode's packages (no window toolkit).
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
                copied.append(_keep(target, str(file), source.read_bytes()))
    return _license_from_metadata(dist.metadata), copied


def _keep(target: Path, member: str, data: bytes) -> str:
    """Save one licence file under ``target`` and return its relative name.

    Files are kept under their path inside the package (minus a leading
    ``*.dist-info/licenses/`` or ``*.dist-info/`` part), so a package with several
    ``License.txt`` files in different folders (pywin32) keeps all of them.
    """
    parts = Path(member).parts
    if parts and parts[0].endswith(".dist-info"):
        parts = parts[2:] if len(parts) > 2 and parts[1] == "licenses" else parts[1:]
    relative = Path(*parts)
    dest = target / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return relative.as_posix()


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
                elif LICENSE_NAME.search(member) and not member.endswith(".py"):
                    copied.append(_keep(target, member, archive.read(member)))
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
        # A wheel can list the same licence through multiple metadata locations.
        # Preserve its first occurrence without duplicating notice/manifest entries.
        files = list(dict.fromkeys(files))
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
    "pywin32": "Browser mode's native file pickers (Windows)",
    "pyside6": "Qt window on Linux (via pywebview)",
    "react": "User interface",
    "react-dom": "User interface",
    "@dnd-kit/core": "Drag to reorder files",
    "@dnd-kit/sortable": "Drag to reorder files",
    "@fontsource-variable/open-sans": "Bundled font (Open Sans)",
}


def _download(url: str, name: str, sha256: str | None = None) -> Path:
    """Download ``url`` into the cache (once) and check its SHA-256 if given."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.is_file():
        with urllib.request.urlopen(url, timeout=300) as response:
            data = response.read()
        path.write_bytes(data)
    if sha256 and _sha256(path.read_bytes()) != sha256:
        path.unlink()
        raise SystemExit(f"Checksum mismatch for {url}")
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wheel(name: str, version: str, platform: str) -> Path:
    """The package's official wheel for ``platform``, downloaded into the cache."""
    found = sorted(CACHE.glob(f"{name.replace('-', '_')}-{version}-*.whl"))
    if found:
        return found[0]
    tag = {"windows": "win_amd64", "linux": "manylinux2014_x86_64"}[platform]
    CACHE.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "download", f"{name}=={version}", "--no-deps"]
        + ["--only-binary=:all:", "--platform", tag, "--python-version", "3.13"]
        + ["--implementation", "cp", "--dest", str(CACHE), "--quiet"],
        check=True,
    )
    return sorted(CACHE.glob(f"{name.replace('-', '_')}-{version}-*.whl"))[0]


def python_runtime_components() -> list[Component]:
    """The Python runtime PyInstaller bundles, per platform.

    Windows: the python.org build of ``PYTHON_WINDOWS_VERSION`` (what the Windows
    build workflow installs). Its ``LICENSE.txt`` holds the PSF licence, the terms
    for the Microsoft C++ runtime it is built with, and the licences of the
    libraries shipped beside it (bzip2, libffi, OpenSSL's Apache-2.0, Tcl/Tk).
    CPython's ``Doc/license.rst`` adds the notices for code compiled into the
    interpreter itself (expat, libmpdec, mimalloc, HACL*, zlib and others).

    Linux (packages from v0.75): the interpreter running this script, for now.
    """
    out = []
    version = PYTHON_WINDOWS_VERSION
    target = LICENSES / "other" / f"python-runtime-windows-{version}"
    target.mkdir(parents=True, exist_ok=True)
    embed = _download(
        f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip",
        f"python-{version}-embed-amd64.zip",
    )
    with zipfile.ZipFile(embed) as archive:
        (target / "LICENSE.txt").write_bytes(archive.read("LICENSE.txt"))
    rst = _download(
        f"https://raw.githubusercontent.com/python/cpython/v{version}/Doc/license.rst",
        f"cpython-{version}-license.rst",
    )
    shutil.copyfile(rst, target / "license.rst")
    out.append(
        Component(
            "Python runtime (python.org Windows build)",
            version,
            "PSF-2.0 (and the bundled libraries' licences inside)",
            {"windows"},
            "Runs the app (bundled by PyInstaller)",
            [f"other/{target.name}/LICENSE.txt", f"other/{target.name}/license.rst"],
            "other",
        )
    )
    local = sys.version.split()[0]
    runtime = Path(sys.base_prefix) / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}"
    for candidate in (runtime / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"):
        if candidate.is_file():
            target = LICENSES / "other" / "python-runtime-linux"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate, target / "LICENSE.txt")
            out.append(
                Component(
                    "Python runtime (Linux packages; confirm with the v0.75 build)",
                    local,
                    "PSF-2.0",
                    {"linux"},
                    "Runs the app (bundled by PyInstaller)",
                    [f"other/{target.name}/LICENSE.txt"],
                    "other",
                )
            )
            break
    return out


def webview2_component(pywebview_version: str) -> tuple[Component, dict[str, str]]:
    """Microsoft's WebView2 SDK files inside pywebview's wheel.

    Downloads Microsoft's NuGet package of ``WEBVIEW2_SDK_VERSION``, checks that
    pywebview's copies are byte-identical to it (so the package's licence really is
    the licence of the files we ship), and keeps its LICENSE.txt and NOTICE.txt.

    Returns:
        The component and the SHA-256 of each DLL, by its path inside the wheel.
    """
    nupkg = _download(
        f"https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/{WEBVIEW2_SDK_VERSION}",
        f"microsoft.web.webview2.{WEBVIEW2_SDK_VERSION}.nupkg",
    )
    wheel = _wheel("pywebview", pywebview_version, "windows")
    hashes = {}
    with zipfile.ZipFile(nupkg) as sdk, zipfile.ZipFile(wheel) as pkg:
        for in_wheel, in_sdk in WEBVIEW2_DLLS.items():
            ours = pkg.read(in_wheel)
            if ours != sdk.read(in_sdk):
                raise SystemExit(
                    f"{in_wheel} in pywebview {pywebview_version} is not the file from "
                    f"Microsoft.Web.WebView2 {WEBVIEW2_SDK_VERSION}; update WEBVIEW2_SDK_VERSION."
                )
            hashes[in_wheel] = _sha256(ours)
        target = LICENSES / "other" / f"microsoft-webview2-sdk-{WEBVIEW2_SDK_VERSION}"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("LICENSE.txt", "NOTICE.txt"):
            (target / name).write_bytes(sdk.read(name))
    component = Component(
        "Microsoft WebView2 SDK files (Microsoft.Web.WebView2.Core.dll, "
        "Microsoft.Web.WebView2.WinForms.dll, WebView2Loader.dll), inside pywebview",
        WEBVIEW2_SDK_VERSION,
        "BSD-3-Clause-style Microsoft licence (no source published; see note)",
        {"windows"},
        "Connects the window to the Edge WebView2 Runtime on Windows",
        [f"other/{target.name}/LICENSE.txt", f"other/{target.name}/NOTICE.txt"],
        "other",
    )
    return component, hashes


def mupdf_components(mupdf_version: str) -> tuple[list[Component], dict]:
    """MuPDF and the third-party code it compiles into PyMuPDF.

    PyMuPDF's wheel carries only a one-line COPYING, and PyMuPDF's source
    distribution doesn't contain MuPDF (it downloads MuPDF at build time), so the
    licence files come from the exact MuPDF source release.

    Returns:
        The components and the source archive's URL and SHA-256.
    """
    url = f"https://mupdf.com/downloads/archive/mupdf-{mupdf_version}-source.tar.gz"
    archive_path = _download(url, f"mupdf-{mupdf_version}-source.tar.gz")
    wanted = {"COPYING": "mupdf/COPYING"}
    for folder, (_, _, files) in MUPDF_PARTS.items():
        for name in files:
            wanted[f"{folder}/{name}"] = f"mupdf/{folder.split('/')[-1]}/{name}"
    found = {}
    with tarfile.open(archive_path) as archive:
        prefix = f"mupdf-{mupdf_version}-source/"
        for member in archive.getmembers():
            relative = member.name.removeprefix(prefix)
            if member.isfile() and relative in wanted:
                dest = LICENSES / wanted[relative]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.extractfile(member).read())
                found[relative] = wanted[relative]
    missing = sorted(set(wanted) - set(found))
    if missing:
        raise SystemExit(f"MuPDF {mupdf_version} source lacks: {', '.join(missing)}")
    out = [
        Component(
            "MuPDF (inside PyMuPDF)",
            mupdf_version,
            "AGPL-3.0",
            {"windows", "linux"},
            "PDF engine compiled into PyMuPDF",
            [found["COPYING"]],
            "mupdf",
        )
    ]
    for folder, (name, spdx, files) in MUPDF_PARTS.items():
        out.append(
            Component(
                name,
                f"from MuPDF {mupdf_version}",
                spdx,
                {"windows", "linux"},
                "Compiled into PyMuPDF by MuPDF",
                [found[f"{folder}/{f}"] for f in files],
                "mupdf",
            )
        )
    source = {"url": url, "sha256": _sha256(archive_path.read_bytes())}
    return out, source


def other_components() -> list[Component]:
    """The PyInstaller bootloader, Inno Setup and the icon credit."""
    out = []
    # PyInstaller's bootloader is linked into the app's executable.
    target = LICENSES / "other" / f"pyinstaller-{PYINSTALLER_VERSION}"
    with zipfile.ZipFile(_wheel("pyinstaller", PYINSTALLER_VERSION, "windows")) as archive:
        files = [
            _keep(target, member, archive.read(member))
            for member in archive.namelist()
            if member.endswith(".dist-info/licenses/COPYING.txt")
            or member.endswith(".dist-info/COPYING.txt")
        ]
    if not files:
        raise SystemExit(f"PyInstaller {PYINSTALLER_VERSION}'s wheel has no COPYING.txt")
    out.append(
        Component(
            "PyInstaller bootloader",
            PYINSTALLER_VERSION,
            "GPL-2.0-or-later WITH Bootloader-exception",
            {"windows", "linux"},
            "Starts the app; the exception allows any licence for the app",
            [f"other/{target.name}/{f}" for f in files],
            "other",
        )
    )
    # Inno Setup: the installer and the uninstaller it leaves next to the app.
    target = LICENSES / "other" / "inno-setup"
    target.mkdir(parents=True, exist_ok=True)
    inno = _download("https://jrsoftware.org/files/is/license.txt", "inno-setup-license.txt")
    shutil.copyfile(inno, target / "license.txt")
    out.append(
        Component(
            "Inno Setup (the installer and unins000.exe)",
            INNO_SETUP_VERSION,
            "Inno Setup License (permissive)",
            {"windows"},
            "Installs and uninstalls the app",
            ["other/inno-setup/license.txt"],
            "other",
        )
    )
    # Icons: drawn inline in frontend/src/components/Icon/Icon.tsx. The settings
    # gear is Feather's "settings" path with its numbers rounded, so Feather's own
    # licence file (from the v4.29.2 tag) is shipped.
    target = LICENSES / "other" / "feather-icons"
    target.mkdir(parents=True, exist_ok=True)
    feather = _download(
        f"https://raw.githubusercontent.com/feathericons/feather/{FEATHER_VERSION}/LICENSE",
        f"feather-{FEATHER_VERSION}-LICENSE",
    )
    shutil.copyfile(feather, target / "LICENSE")
    out.append(
        Component(
            "Feather Icons (design of the settings icon)",
            FEATHER_VERSION,
            "MIT",
            {"windows", "linux"},
            "The settings gear icon is derived from Feather's",
            ["other/feather-icons/LICENSE"],
            "other",
        )
    )
    return out


QT_SOURCE = (
    "https://download.qt.io/official_releases/qt/6.12/6.12.0/single/qt-everywhere-src-6.12.0.tar.xz"
)
PYSIDE_SOURCE = (
    "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/"
    "pyside-setup-everywhere-src-6.12.0.tar.xz"
)
# Packages that publish no source distribution on PyPI: where their source is.
# The Qt entries are Linux-only (v0.75); they must be revisited with that build.
NO_SDIST = {
    # pywin32 b312: pin the resolved upstream commit, not a mutable tag reference.
    "pywin32": "https://github.com/mhammond/pywin32/archive/2a277cb5552756c2b4d42b524dc36d25e0bb6354.tar.gz",
    "pyside6": PYSIDE_SOURCE,
    "pyside6-addons": f"{PYSIDE_SOURCE} and {QT_SOURCE}",
    "pyside6-essentials": f"{PYSIDE_SOURCE} and {QT_SOURCE}",
    "pyside6-pdf": f"{PYSIDE_SOURCE} and {QT_SOURCE}",
    "pyside6-webengine": f"{PYSIDE_SOURCE} and {QT_SOURCE}",
    "shiboken6": PYSIDE_SOURCE,
}


def python_sources(packages: dict[str, tuple[str, set[str]]]) -> list[dict]:
    """Where each bundled Python package's source is published, from uv.lock."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    by_name = {p["name"]: p for p in lock["package"]}
    out = []
    for name, (version, platforms) in sorted(packages.items()):
        entry = by_name[name]
        sdist = entry.get("sdist")
        if sdist:
            url, sha = sdist["url"], sdist["hash"].removeprefix("sha256:")
        elif name in NO_SDIST:
            url, sha = NO_SDIST[name].format(version=version), ""
        else:
            raise SystemExit(f"No published source for {name} {version} in uv.lock")
        out.append(
            {
                "component": name,
                "version": version,
                "url": url,
                "sha256": sha,
                "platforms": sorted(platforms),
            }
        )
    return out


def frontend_sources() -> list[dict]:
    """npm tarballs (with integrity hashes) of the packages inlined into the UI."""
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    out = []
    for path, info in sorted(lock["packages"].items()):
        if not path or info.get("dev") or info.get("devOptional"):
            continue
        out.append(
            {
                "component": path.removeprefix("node_modules/"),
                "version": info["version"],
                "url": info["resolved"],
                "integrity": info.get("integrity", ""),
                "platforms": ["linux", "windows"],
            }
        )
    return out


def _pypi_sdist(name: str, version: str) -> dict:
    """URL and SHA-256 of a package's source distribution on PyPI."""
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as r:
        files = json.load(r)["urls"]
    sdist = next(f for f in files if f["packagetype"] == "sdist")
    return {"url": sdist["url"], "sha256": sdist["digests"]["sha256"]}


def write_manifest(components: list[Component], extra: dict) -> None:
    """Write licenses/manifest.json (read by scripts/check_licenses.py)."""
    data = {
        "generated_by": "scripts/collect_licenses.py",
        **extra,
        "components": [
            {
                "name": c.name,
                "version": c.version,
                "license": c.license,
                "platforms": sorted(c.platforms),
                "builds": [b for b in BUILDS if b in c.builds],
                "group": c.group,
                "files": c.files,
            }
            for c in components
        ],
    }
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


VC_REDIST = "Microsoft Visual C++ Redistributable (x64)"
SEGOE_UI = ("Segoe UI font", "Proprietary", "Used only if Windows provides it; never bundled.")
OPTIONAL_PROGRAMS = [
    (
        "Tesseract OCR program",
        "Apache-2.0",
        "Optional; installed with winget or a package manager.",
    ),
    ("LibreOffice", "MPL-2.0", "Optional, for PowerPoint files; installed separately."),
]


def _not_included(rows: list[tuple[str, str, str]], how: str) -> str:
    """The "Not included" table and the Visual C++ Redistributable sentence."""
    table = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)
    return (
        f"{table}\n\nThe {VC_REDIST.replace(' (x64)', '')} (x64, version 14.44 or newer) is "
        f"installed from\n{how} It is never shipped with the app."
    )


def write_notices(groups: dict[str, list[Component]], build: str | None = None) -> None:
    """Write THIRD_PARTY_NOTICES.md (every build), or one build's notices.

    Args:
        groups: The components, by section.
        build: ``None`` for THIRD_PARTY_NOTICES.md, which lists every build with
            a "Builds" column; ``"browser"`` for THIRD_PARTY_NOTICES-browser.md,
            which lists only what the browser-mode ZIP ships.
    """
    if build is not None:
        groups = {k: [c for c in v if build in c.builds] for k, v in groups.items()}

    def rows(components: list[Component]) -> str:
        out = []
        for c in components:
            where = ", ".join(sorted(p.capitalize() for p in c.platforms))
            files = ", ".join(f"[`{f.split('/', 1)[-1]}`](licenses/{f})" for f in c.files) or "—"
            used = c.used_for or USED_FOR.get(c.name, "")
            builds = (
                "" if build else f" {', '.join(b.capitalize() for b in BUILDS if b in c.builds)} |"
            )
            out.append(
                f"| {c.name} | {c.version} | {c.license} | {where} |{builds} {used} | {files} |"
            )
        return "\n".join(out)

    if build:
        header = (
            "| Component | Version | Licence | Bundled on | Used for | Licence text |\n"
            "| --- | --- | --- | --- | --- | --- |"
        )
    else:
        header = (
            "| Component | Version | Licence | Bundled on | Builds | Used for | Licence text |\n"
            "| --- | --- | --- | --- | --- | --- | --- |"
        )
    if build == "browser":
        intro = """The browser-mode ZIP (PDF Manager in your own web browser) also includes the
components below. Each keeps its own licence; the licence texts are in the
[`licenses/`](licenses) folder next to this file. It doesn't include the desktop window's
toolkit (pywebview and its parts) or the installer."""
    else:
        intro = """The distributed app also includes the components below: the Windows
installer (the **Desktop** build, and the Linux packages from v0.75) and the
browser-mode ZIP (the **Browser** build; its own list is in
`THIRD_PARTY_NOTICES-browser.md`). Each keeps its own licence; the licence texts are in
the [`licenses/`](licenses) folder, which is installed next to the app."""
    if build == "browser":
        notes = """**Note on the Microsoft C and C++ runtimes:** the ZIP doesn't ship them. The
Python runtime, PyMuPDF and pywin32 need Microsoft's Visual C++ runtime, which comes from the
separately installed Microsoft Visual C++ Redistributable (see below). The Universal C
Runtime is part of Windows 10 and 11."""
        not_included = _not_included(
            [
                (
                    "Your web browser (Microsoft Edge, Google Chrome, Brave, Chromium, Firefox or "
                    "another)",
                    "Its own licence",
                    "PDF Manager opens in it; never shipped.",
                ),
                *OPTIONAL_PROGRAMS,
                (VC_REDIST, "Microsoft software licence", "Required on Windows; see note."),
                SEGOE_UI,
            ],
            "Microsoft; the ZIP has no installer to check for it.",
        )
    else:
        notes = f"""**Note on the Microsoft WebView2 SDK files (Desktop build only):** pywebview
ships these Microsoft files byte-for-byte as they are in Microsoft's `Microsoft.Web.WebView2` NuGet
package {WEBVIEW2_SDK_VERSION}, which licenses them under the BSD-3-Clause-style terms in
`LICENSE.txt` (with third-party notices in `NOTICE.txt`). We found no published source
code for them. Whether the AGPL-3.0 requires it is an open question; see
[LICENSING.md](LICENSING.md).

**Note on the Microsoft C and C++ runtimes:** the Windows app doesn't ship them. The
Python runtime, PyMuPDF and pywin32 need Microsoft's Visual C++ runtime, which comes from
the separately installed Microsoft Visual C++ Redistributable (see below); the installer
checks for it. The Universal C Runtime is part of Windows 10 and 11."""
        not_included = _not_included(
            [
                *OPTIONAL_PROGRAMS,
                (
                    "Microsoft Edge WebView2 Runtime",
                    "Microsoft software licence",
                    "Part of Windows 11; not shipped.",
                ),
                (VC_REDIST, "Microsoft software licence", "Required; see note."),
                SEGOE_UI,
                (
                    "The browser that browser mode opens in",
                    "Its own licence",
                    "Browser build; never shipped.",
                ),
            ],
            "Microsoft (the installer offers the download).",
        )
    text = f"""# Third-party notices

PDF Manager's own code is released under the [MIT License](LICENSE), © 2026 Mohannad Ali.

{intro}

**PyMuPDF and MuPDF are licensed under the GNU Affero General Public License v3.0
(AGPL-3.0)**, or a commercial licence from Artifex. Because the distributed app includes
them, the app as a whole is distributed under the terms of the AGPL-3.0 (see
[LICENSING.md](LICENSING.md)). Its complete source code is available at
<https://github.com/Ali7488/pdf-manager>.

This file is generated by `scripts/collect_licenses.py` from the packages actually
bundled, and `scripts/check_licenses.py` fails CI and the Windows build when it is out of
date. It is not legal advice.

## Python packages (the app's engine{" and window" if build is None else ""})

{header}
{rows(groups["python"])}

## Inside PyMuPDF: MuPDF and the libraries and fonts it compiles in

PyMuPDF includes MuPDF, which compiles in the third-party code below. The licence
files come from the MuPDF {groups["mupdf"][0].version} source release.

{header}
{rows(groups["mupdf"])}

## Interface packages (inlined into the app's single HTML file)

{header}
{rows(groups["frontend"])}

## Also included in the built app

{header}
{rows(groups["other"])}

{notes}

## Not included (installed separately)

| Program | Licence | Notes |
| --- | --- | --- |
{not_included}

The app runs the separately installed Tesseract program for OCR. MuPDF also compiles a
copy of the Tesseract library into PyMuPDF (listed above), which PDF Manager doesn't use.
"""
    (BROWSER_NOTICES if build == "browser" else NOTICES).write_text(text, encoding="utf-8")


def main() -> int:
    if LICENSES.exists():
        shutil.rmtree(LICENSES)
    packages = runtime_python_packages()
    browser_packages = runtime_python_packages("--no-group", "desktop")
    python = python_components()
    for c in python:
        c.group = "python"
        if c.name.lower() not in browser_packages:
            c.builds = {"desktop"}  # The desktop window's toolkit.
    frontend = frontend_components()
    for c in frontend:
        c.group = "frontend"
    import pymupdf

    if pymupdf.VersionBind != packages["pymupdf"][0]:
        raise SystemExit("Run `uv sync` first: the installed PyMuPDF isn't the locked one.")
    mupdf, mupdf_source = mupdf_components(pymupdf.mupdf_version)
    webview2, webview2_hashes = webview2_component(packages["pywebview"][0])
    webview2.builds = {"desktop"}
    other = python_runtime_components() + other_components() + [webview2]
    for c in other:
        if c.name.startswith("Inno Setup"):
            c.builds = {"desktop"}  # The browser-mode ZIP has no installer.
    groups = {"python": python, "mupdf": mupdf, "frontend": frontend, "other": other}
    write_notices(groups)
    write_notices(groups, "browser")
    write_manifest(
        python + mupdf + frontend + other,
        {
            "python_windows": PYTHON_WINDOWS_VERSION,
            "pyinstaller": PYINSTALLER_VERSION,
            "inno_setup": INNO_SETUP_VERSION,
            "mupdf": pymupdf.mupdf_version,
            "webview2_sdk": {"version": WEBVIEW2_SDK_VERSION, "sha256": webview2_hashes},
            "sources": {
                "python": python_sources(packages),
                "frontend": frontend_sources(),
                "mupdf": mupdf_source,
                "python_runtime": {
                    "url": f"https://www.python.org/ftp/python/{PYTHON_WINDOWS_VERSION}/"
                    f"Python-{PYTHON_WINDOWS_VERSION}.tar.xz",
                    # Hash published on the matching Python.org release page.
                    "sha256": "6020bd10aff3bf4821be16f088ebb1591beb7b811dcd8fab1da8f7c22a7b27e7",
                },
                "pyinstaller": _pypi_sdist("pyinstaller", PYINSTALLER_VERSION),
                "python_runtime_externals": runtime_external_sources(),
            },
        },
    )
    total = len(python) + len(mupdf) + len(frontend) + len(other)
    print(f"{total} components; see {NOTICES.name} and {MANIFEST.relative_to(ROOT)}")
    unknown = [c.name for c in python + frontend + other if c.license == "UNKNOWN"]
    if unknown:
        print("WARNING: unknown licence for:", ", ".join(unknown))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
