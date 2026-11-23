# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PDF Manager Windows app (one-folder, windowed).

Build from the repository root (``packaging/build.ps1`` does this)::

    uv run --frozen --no-dev --with "pyinstaller>=6.10,<7" pyinstaller --noconfirm --clean ^
        --distpath dist --workpath build/pyinstaller packaging/pdf-manager.spec

Output: ``dist/PDF Manager/PDF Manager.exe`` plus its ``_internal`` folder.

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

import platform
import struct
import sys
import tomllib
from pathlib import Path

from PyInstaller.compat import is_win

# SPECPATH is injected by PyInstaller: the folder that holds this spec (packaging/).
REPO = Path(SPECPATH).resolve().parent
APP_NAME = "PDF Manager"
ENTRY = REPO / "main.py"
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


_require(ENTRY, "The pywebview entry point main.py must be at the repository root.")
_require(
    FRONTEND_DIST / "index.html",
    "Build the frontend first: cd frontend; npm ci; npm run build",
)
_require(ICON, "The app icon 'PDF Manager.ico' must be at the repository root.")


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
hiddenimports = [
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "clr",
]

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
    "pptx",  # python-pptx is a test-only dependency (tests/smoke_test.py).
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
    # WebView2Loader.dll for other CPU architectures.
    if "webview/lib/runtimes/" in path and f"/runtimes/{_RID}/" not in path:
        return True
    # The old IE (mshtml) fallback only needs the interop DLL for its own bitness.
    if _RID != "win-x86" and path.endswith("webbrowserinterop.x86.dll"):
        return True
    # PyMuPDF 2.x wheels ship C headers for developers; the app never needs them.
    if "/mupdf-devel/" in f"/{path}":
        return True
    return False


a = Analysis(
    [str(ENTRY)],
    pathex=[str(REPO)],
    binaries=[],
    # Copy the whole built frontend so it lands at <_MEIPASS>/frontend/dist/.
    datas=[(str(FRONTEND_DIST), "frontend/dist")],
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
    name=APP_NAME,
)

print(f"[pdf-manager.spec] Built {APP_NAME} {VERSION} (WebView2 runtime: {_RID})", file=sys.stderr)
