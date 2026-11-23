# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PDF Manager Windows app (one-folder, windowed).

Build from the repository root (``packaging/build.ps1`` does this)::

    uv run --frozen --no-dev --with "pyinstaller>=6.10,<7" pyinstaller --noconfirm --clean ^
        --distpath dist --workpath build/pyinstaller packaging/pdf-manager.spec

Output: ``dist/PDF Manager/PDF Manager.exe`` plus its ``_internal`` folder.

With ``PDF_MANAGER_BUILD=browser`` (``packaging/build-browser.ps1``) it builds the
browser-mode app instead: ``dist/PDF Manager (browser)/``, started by
``packaging/browser_main.py``, from an environment without the desktop group, and
with the window toolkit excluded (pywebview, pythonnet, Qt). Everything else is
shared, so both builds bundle the same engine the same way.

Runtime layout (what the API layer relies on):

* ``Path(sys._MEIPASS) / "frontend" / "dist" / "index.html"``: the built React app.
  In a one-folder build ``sys._MEIPASS`` is the ``_internal`` folder next to the exe.
* ``Path(sys.executable).parent``: the install folder (``PDF Manager.exe`` lives there).
  The ``logs`` folder belongs here (decision C4), not under ``_internal``.

pywebview, pythonnet, clr_loader, PyMuPDF and pywin32 all ship (or have in
pyinstaller-hooks-contrib) PyInstaller hooks that collect their DLLs and data files,
so this spec only adds what the hooks can't know: the frontend, the backend choice,
the exclusions and the Windows version resource.
"""

import os
import platform
import re
import struct
import sys
import tomllib
from pathlib import Path

from PyInstaller.compat import is_win

# SPECPATH is injected by PyInstaller: the folder that holds this spec (packaging/).
REPO = Path(SPECPATH).resolve().parent
APP_NAME = "PDF Manager"
BUILD = os.environ.get("PDF_MANAGER_BUILD", "desktop")
if BUILD not in ("desktop", "browser"):
    raise SystemExit(f"[pdf-manager.spec] PDF_MANAGER_BUILD must be desktop or browser, not {BUILD}")
BROWSER = BUILD == "browser"
ENTRY = REPO / ("packaging/browser_main.py" if BROWSER else "main.py")
DIST_NAME = f"{APP_NAME} (browser)" if BROWSER else APP_NAME
FRONTEND_DIST = REPO / "frontend" / "dist"
ICON = REPO / "PDF Manager.ico"


def _require(path: Path, hint: str) -> None:
    """Stop the build with a readable message when an input is missing.

    Args:
        path: File or folder that must exist.
        hint: What to do about it, shown to whoever runs the build.

    Raises:
        SystemExit: ``path`` doesn't exist.
    """
    if not path.exists():
        raise SystemExit(f"[pdf-manager.spec] Missing {path}. {hint}")


_require(ENTRY, "The entry script (main.py, or packaging/browser_main.py) is missing.")
_require(
    FRONTEND_DIST / "index.html",
    "Build the frontend first: cd frontend; npm ci; npm run build",
)
_require(ICON, "The app icon 'PDF Manager.ico' must be at the repository root.")

# The exact commit this build is made from, for Settings > About's source link
# (decision P37). Stops the build if tracked files differ from that commit.
sys.path.insert(0, str(REPO))
from api.build_info import BUILD_INFO_FILE, BuildInfoError, write_build_info  # noqa: E402

BUILD_INFO = REPO / "build" / f"build-info-{BUILD}" / BUILD_INFO_FILE
try:
    _build_info = write_build_info(REPO, BUILD_INFO)
except BuildInfoError as exc:
    raise SystemExit(f"[pdf-manager.spec] {exc}")
print(f"[pdf-manager.spec] Source revision {_build_info['revision']}"
      f"{' (modified)' if _build_info['modified'] else ''}")


def _read_version() -> str:
    """Read the app version from ``pyproject.toml``.

    Returns:
        The ``[project] version`` string, for example ``"1.1.1"``.
    """
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    """Turn ``"1.2.3"`` into the four numbers a Windows version resource needs.

    Non-numeric suffixes (``"1.2.3rc1"``) are dropped; missing parts become 0.

    Args:
        version: Version string from ``pyproject.toml``.

    Returns:
        ``(major, minor, patch, 0)``-style tuple of four ints.
    """
    parts = []
    for piece in version.split(".")[:4]:
        digits = "".join(ch for ch in piece if ch.isdigit()) or "0"
        parts.append(int(digits))
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


VERSION = _read_version()


def _windows_version_info(version: str):
    """Build the Windows "Details" tab info (name, version) for the exe.

    Args:
        version: Version string from ``pyproject.toml``.

    Returns:
        A ``VSVersionInfo`` object, or ``None`` when not building on Windows.
    """
    if not is_win:
        return None
    # Imported here because the module needs pywin32/pefile, which only matter on Windows.
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = _version_tuple(version)
    strings = [
        StringStruct("CompanyName", APP_NAME),
        StringStruct("FileDescription", APP_NAME),
        StringStruct("FileVersion", version),
        StringStruct("InternalName", APP_NAME),
        StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
        StringStruct("ProductName", APP_NAME),
        StringStruct("ProductVersion", version),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            # 040904B0 = US English, Unicode code page.
            StringFileInfo([StringTable("040904B0", strings)]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


# pywebview picks its GUI backend at runtime. On Windows that is WinForms with the
# Edge WebView2 (Chromium) renderer, both driven through pythonnet ("clr").
hiddenimports = (
    []
    if BROWSER
    else ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"]
)

# Keep the bundle small (low overhead): no Tk, no test frameworks, and none of
# pywebview's non-Windows backends (they would pull in Qt/GTK if installed).
excludes = [
    "tkinter",
    "_tkinter",
    "turtle",
    "turtledemo",
    "idlelib",
    "unittest",
    "test",
    "tests",
    "pytest",
    "_pytest",
    "pptx",  # python-pptx is a test-only dependency (tests, scripts/make_samples.py).
    "pydoc_data",
    "ensurepip",
    "webview.platforms.qt",
    "webview.platforms.gtk",
    "webview.platforms.cocoa",
    "webview.platforms.android",
    "webview.platforms.cef",
    "qtpy",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "gi",
    "cefpython3",
    "jnius",
]
if BROWSER:
    # The window toolkit: not installed in the browser build's environment, and kept
    # out even if it is (scripts/check_licenses.py --build browser checks the result).
    excludes += ["webview", "clr", "clr_loader", "pythonnet", "proxy_tools", "bottle"]


def _webview_runtime_id() -> str:
    """Return the .NET runtime id matching the Python that runs the build.

    The bundled exe has the same architecture as that Python, so only its
    ``WebView2Loader.dll`` is needed.

    Returns:
        ``"win-x64"``, ``"win-arm64"`` or ``"win-x86"``.
    """
    if struct.calcsize("P") == 4:
        return "win-x86"
    return "win-arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "win-x64"


_RID = _webview_runtime_id()
# The same pattern as VC_RUNTIME_DLL in scripts/check_licenses.py.
_VC_RUNTIME_DLL = re.compile(r"(vcruntime|msvcp|concrt|vccorlib|vcomp|vcamp|mfcm?)14\d\w*\.dll$")


def _unneeded(dest: str) -> bool:
    """Decide whether a collected file can be left out of the bundle.

    Args:
        dest: Destination path of the file inside the bundle.

    Returns:
        True for files this Windows build never uses.
    """
    path = dest.replace("\\", "/").lower()
    if path.endswith("pywebview-android.jar"):
        return True
    # Keep every WebView2Loader.dll runtime folder (win-x64, win-x86, win-arm64):
    # pywebview's EdgeChromium backend looks them all up at import time and raises
    # "Cannot find win-arm64" if one is missing (found by the installed-app smoke
    # test on the Windows runner). They're small.
    # PyMuPDF 2.x wheels ship C headers for developers; the app never needs them.
    if "/mupdf-devel/" in f"/{path}":
        return True
    name = path.rsplit("/", 1)[-1]
    # The Universal C Runtime is part of Windows 10 and 11 (the installer's minimum),
    # and Windows always uses its own copy even when an app ships one, so the copies
    # PyInstaller picks up from the build machine are never used. Leaving them out also
    # keeps Microsoft binaries the app doesn't need out of the AGPL-3.0 distribution.
    if name == "ucrtbase.dll" or (name.startswith("api-ms-win-") and name.endswith(".dll")):
        return True
    # The Microsoft Visual C++ runtime (vcruntime140*.dll, msvcp140*.dll, MFC and the
    # rest of the v14 Redistributable's DLLs) isn't bundled, wherever PyInstaller finds
    # it (decision P32). The app uses the separately installed Microsoft Visual C++
    # Redistributable (x64), which the installer checks for: that is Microsoft's
    # recommended central deployment, keeps Microsoft's runtime serviced by Windows
    # Update, and keeps it outside the AGPL-3.0 distribution, where the GNU FAQ treats it
    # as a System Library only while it isn't shipped with the program. MFC is needed only
    # by pywin32's Pythonwin GUI (win32ui), which the app never imports.
    # scripts/check_licenses.py fails the build if any of them is bundled again.
    if _VC_RUNTIME_DLL.match(name):
        return True
    return False


a = Analysis(
    [str(ENTRY)],
    pathex=[str(REPO)],  # Lets browser_main.py import the api package.
    binaries=[],
    # Copy the whole built frontend so it lands at <_MEIPASS>/frontend/dist/, and the
    # build's source revision at <_MEIPASS>/build-info.json.
    datas=[(str(FRONTEND_DIST), "frontend/dist"), (str(BUILD_INFO), ".")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

a.datas = [entry for entry in a.datas if not _unneeded(entry[0])]
a.binaries = [entry for entry in a.binaries if not _unneeded(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # One-folder build: DLLs go next to the exe, not inside it.
    name=APP_NAME,
    icon=str(ICON),
    version=_windows_version_info(VERSION),
    console=False,  # Windowed app: no console window behind the UI.
    disable_windowed_traceback=False,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is off: it often trips antivirus heuristics and can break .NET DLLs.
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=DIST_NAME,
)

print(f"[pdf-manager.spec] Built {DIST_NAME} {VERSION} (WebView2 runtime: {_RID})", file=sys.stderr)
