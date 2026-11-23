# Portability

PDF Manager ships first on **Windows 11** (v1). The same code base must later support **Ubuntu/Debian** and **Arch-based** Linux distributions (decisions P14, P15). There is one shared React/TypeScript frontend and one shared Python conversion engine; only small, isolated pieces differ per platform.

**Linux packaging is not implemented yet.** This document records the constraints that keep it possible, and what a Linux release will need.

## Layers and where platform code may live

| Layer | Folder | Platform-specific code |
| --- | --- | --- |
| Frontend | `frontend/` | None. The UI never assumes an OS; it gets paths, platform name and capabilities from the API. |
| API layer | `api/` | Only behind a small platform module (opening a folder, installing OCR, settings/log locations). |
| Service layer | `converter/` | Only in `converter/platforms/` (`windows.py`, `posix.py`), selected once at import time. |

## Rules for shared code

1. **No platform checks in shared logic.** `os.name`, `sys.platform`, `winreg`, COM (`win32com`, `pythoncom`), `os.startfile`, `taskkill` and `CREATE_NO_WINDOW` belong only in the platform modules. Shared code calls the platform interface.
2. **Optional, never required, Windows features.** Microsoft PowerPoint (COM) is an optional, higher-fidelity slide renderer on Windows. **LibreOffice is the cross-platform renderer** and must always work as the fallback. No feature may depend on PowerPoint.
3. **Paths:** use `pathlib`; never hard-code drive letters, `\` separators, `Program Files` or `%LOCALAPPDATA%` outside platform modules. Remember Linux file names are case-sensitive.
4. **External tools are found, not assumed:** Tesseract and LibreOffice are located through the platform interface (PATH first, then platform-specific places).
5. **User-facing text:** wording that names a platform-specific fix (for example "Microsoft Print to PDF" or a Windows download page) must become platform-aware before a Linux release (see "Known Windows-specific spots").
6. **Tests:** platform-independent tests run on Linux in development. Windows-only behaviour is isolated so it can be faked in tests and verified on a real Windows 11 machine.

## Platform interface (service layer)

`converter/platforms/` exposes one small set of functions, implemented once per platform:

| Function | Windows | Linux (POSIX) |
| --- | --- | --- |
| `popen_options()` | Hide the console window (`CREATE_NO_WINDOW`). | Start in a new session so the whole process group can be stopped. |
| `kill_process_tree(process)` | `taskkill /F /T`. | `killpg(SIGKILL)` on the process group. |
| `tesseract_candidates()` | Program Files / LocalAppData folders and installer registry entries. | None beyond `PATH` (packages install to `/usr/bin`). |
| `libreoffice_candidates()` | Program Files / LocalAppData folders. | None beyond `PATH` (`soffice`, `libreoffice`). |
| `powerpoint_installed()` / `powerpoint_path()` | Registry checks for PowerPoint's automation class and executable. | Always `False` / `None`. |
| `is_untrusted(path)` / `copy_with_provenance(src, dst)` | Read the Mark-of-the-Web zone; copy a file with its `Zone.Identifier` stream (never strip it, audit R1). | Always `False`; plain copy. |
| `export_slides_with_powerpoint` | The optional COM-based renderer (`windows_powerpoint.py`). | `None`: LibreOffice renders slides. |

The service layer's public functions (`find_tesseract`, `find_libreoffice`, `run_command`, `powerpoint_installed` and so on in `converter/tools/`) stay the same on every platform.

## External programs per platform

| Program | Windows | Ubuntu/Debian | Arch-based |
| --- | --- | --- | --- |
| Tesseract OCR + English data | UB-Mannheim build (installer wizard or in-app via winget) | `tesseract-ocr`, `tesseract-ocr-eng` | `tesseract`, `tesseract-data-eng` |
| LibreOffice (slides) | Optional backup (installer wizard offers it) | `libreoffice-impress` | `libreoffice-fresh` or `libreoffice-still` |
| Microsoft PowerPoint | Optional, preferred when present | Not available | Not available |
| Web view for the window | Edge WebView2 (built into Windows 11) | WebKitGTK via PyGObject, or Qt WebEngine | Same as Debian |

## Future Linux release requirements

To be done in a later release; not implemented now.

- **Packages:** an Ubuntu/Debian `.deb` and an Arch `PKGBUILD`.
- **Python strategy:** decide between bundling the app with its own Python environment (as on Windows, which avoids distro version differences, especially for PyMuPDF) and depending on distro Python packages. To decide later.
- **Dependencies to declare:** Tesseract and English data, LibreOffice Impress (optional or recommended), a pywebview backend (GTK: PyGObject + WebKitGTK; or Qt: PyQt6 + Qt WebEngine), with the exact package names per distribution (see the table above).
- **Desktop integration:** a `.desktop` launcher, icons in PNG/SVG sizes (only a Windows `.ico` exists today), optional AppStream metadata.
- **Locations (XDG):** settings in `$XDG_CONFIG_HOME/pdf-manager/`. Logs go to `$XDG_STATE_HOME/pdf-manager/logs` (default `~/.local/state/pdf-manager/logs`, decision C15), because a packaged install lives in a read-only system folder; from source they stay in the repo's `logs/`. Scratch files in the system temp folder.
- **Opening folders:** `xdg-open`.
- **Installing OCR from the app:** Windows uses winget. On Linux the app never runs `sudo`; "Install OCR" shows the exact command for the user's distribution with a Copy button (decision C16).
- **Qt and GNOME** (P14, P18) mean pywebview window backends for the same React UI: Qt first (`pywebview[qt]`), then GTK/WebKitGTK. Running from source on Linux is being added now (P17); packages come later.
- **CI:** build and test on Linux runners once packaging exists.

## Known Windows-specific spots to address

| Where | What | Plan |
| --- | --- | --- |
| `converter/core/issues.py` | Troubleshooting text mentions Windows-only fixes (default printer, Windows download page) | Make platform-aware before the Linux release. |
| `api/bridge.py`, `api/paths.py` | Opening folders (`os.startfile` / `xdg-open`), OCR install via winget, picker filters and the settings path are gated by `paths.on_windows()` checks inside these modules | Move behind one API-layer platform module (P15); tracked in `ENGINEERING_REVIEW.md`. |
| `packaging/` | Windows installer (PyInstaller + Inno Setup) | Windows only by design; Linux packaging is separate future work. |
