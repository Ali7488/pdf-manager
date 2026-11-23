# Engineering review: bugs, status and what has been verified

Significant bugs found since the v1.1.1 baseline was imported, their status, and the open work. "Fixed" means fixed in code and covered by automated tests **on Linux**; anything that depends on Windows is marked as unverified until it has run there.

## Review status (read this first)

- **No human has reviewed the generated code yet.** All code since the import was written by AI agents. The lead agent read the agent-written modules (Split, Images to PDF, Compress, packaging) briefly and ran their tests; that is not a line-by-line review.
- **Automated checks:** the pytest suite (`uv run pytest`, 163 tests at the time of writing) and `ruff` lint/format, run on Linux (CachyOS) with Tesseract 5.5.4, LibreOffice and PyMuPDF 1.28.2.
- **Never run on Windows yet:** Microsoft PowerPoint automation (COM), registry lookups, `taskkill`, the PyInstaller build, the Inno Setup wizard, the GitHub build workflow, pywebview/WebView2. Their tests use fakes or don't exist.
- **Not yet merged:** the API layer (`api/`) and the React frontend (`frontend/`).

## Bugs and their status

| # | Bug (where it was) | Status |
| --- | --- | --- |
| 1 | Converting a presentation could **close the user's own open PowerPoint** (`app.Quit()` on the shared instance). | Fixed: quits or kills PowerPoint only if the converter started it (`platforms/windows_powerpoint.py`). Logic tested with fakes; **unverified on Windows**. |
| 2 | **PowerPoint errors were swallowed**; users saw a misleading "requires PowerPoint or LibreOffice" message. | Fixed: a fallback produces a `POWERPOINT_FALLBACK` warning carrying the real error; if both renderers fail, the issue includes both errors. |
| 3 | PowerPoint **fell back to LibreOffice too often**. | Two likely causes addressed, **neither confirmed on Windows**: (a) downloaded files open in Protected View, so the converter now renders a plain copy without the Mark-of-the-Web; (b) the documented "Waiting for printer connection" dialog, which now times out after 5 minutes with troubleshooting steps. Confirm with real files on Windows. |
| 4 | **No cancel, and jobs could hang** (no PowerPoint timeout; 5 min per OCR page). | Fixed in the service layer: cancel token checked between pages and files; running programs are killed (whole process tree); timeouts for OCR pages (2 min default, a setting), PowerPoint and LibreOffice (5 min). The Cancel button is the frontend's job. |
| 5 | **DPI setting never reached flattening**; OCR language fixed to English. | Fixed: settings flow through `ActionSettings` into every step. |
| 6 | **Merging dropped bookmarks.** | Fixed: nested per-file bookmarks; optional contents page; page labels. |
| 7 | **Weak flatten check** (passed if any one page had an image). | Fixed: page count must match and every page must be image-backed. |
| 8 | **Registry path parsing** broke on unquoted `tesseract.exe,0`. | Fixed and unit-tested (`exe_from_registry_value`); the registry reading itself is unverified on Windows. |
| 9 | **Installer always installed LibreOffice**, even with Office present. | Replaced by the new install wizard (`packaging/installer.iss`), which detects PowerPoint and offers LibreOffice as an optional backup. **Never compiled or run.** |
| 10 | **Cancelling the save dialog discarded all results.** | Designed out in the API contract (results kept until saved or discarded); depends on the API layer, not merged yet. |
| 11 | Tkinter UI: event polling could stop permanently after an error; no visible keyboard focus. | Not fixed; the Tkinter app will be deleted once the new app works (F25). The frontend brief requires real buttons and visible focus rings. |
| 12 | Speaker-notes appendix: non-Latin text rendered as missing glyphs, soft line breaks lost, unrelated template notes included. | Removed with the feature (P7). |
| 13 | WinError 32 when deleting temporary OCR files on Windows (baseline bug). | Fixed in the baseline; kept by design and by the simulated regression test. Real Windows antivirus/Explorer behaviour is unverified. |

Found during implementation:

- `fitz.image_profile` raises a `TypeError` in PyMuPDF 1.28.2; it isn't used.
- `import fitz` prints a deprecation notice in PyMuPDF 1.28. Open cleanup: switch to `import pymupdf`.

## Open work

1. Merge and review the API layer and the frontend; fill in their sections of `ARCHITECTURE.md`.
2. Run everything on a real Windows 11 machine: PowerPoint conversion (including a downloaded file and a machine with an offline default printer), cancel and timeouts, the installer wizard (with and without PowerPoint, with and without winget, as a non-admin user), the packaged app (WebView2, no console window), upgrade and uninstall.
3. Delete the Tkinter app and the old Windows scripts (`app.py`, `INSTALL.bat`, `OPEN.bat`, `install_windows.ps1`) once the new app works (F25).
4. Make Windows-specific troubleshooting text platform-aware before any Linux release (see `PORTABILITY.md`).
5. Add automated test runs in CI (none exist yet).
6. Public release items: licence, versioning, signed installer (unsigned is accepted for v1, F17).

Historical originals of the imported baseline are in `.migration/` locally (Git-ignored).
