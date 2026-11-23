# Architecture

How PDF Manager is put together, how a conversion runs, and the implementation choices that aren't obvious from reading one file. Owner decisions are referenced by their IDs in [`DECISIONS.md`](DECISIONS.md); known bugs and what has or hasn't been verified are in [`ENGINEERING_REVIEW.md`](ENGINEERING_REVIEW.md).

> **Status (2026-11-23):** all layers are merged on `main`: React frontend (`frontend/`), Python API layer (`api/`), service layer (`converter/`) and Windows packaging (`packaging/`). The desktop entry point is `main.py`; the old Tkinter app was removed. Nothing has run on a real Windows 11 machine yet except the automated Windows CI tests (see `ENGINEERING_REVIEW.md`).

## Layers (F35)

```
frontend/  React + TypeScript UI ──(pywebview bridge: calls + DOM events, docs/API.md)──┐
api/       Python API layer: job state, settings, logging, saving, native dialogs  <────┘
converter/ Python service layer: pure conversion logic, no UI, no bridge
           └─ converter/platforms/  the only OS-specific code (P15)
```

- The frontend talks to Python only through the contract in [`API.md`](API.md) (`frontend/src/api/types.ts` is the TypeScript source of truth).
- The API layer converts camelCase JSON to the service layer's dataclasses and back, owns the job thread, scratch folders, settings file and logs.
- The service layer is a plain Python package that can be used and tested without any UI.

## Service layer (`converter/`)

| Folder | Responsibility |
| --- | --- |
| `core/` | `types.py`: `Action` enum, `ActionSettings`, `ActionData`, `ProgressEvent`, `OutputFile`, `JobResult`, accepted file types. `issues.py`: `Issue` (user-facing error/warning with troubleshooting steps), `ConversionError`, `Cancelled`. `context.py`: `CancelToken`, `JobContext` (settings, cancel, progress, warnings). |
| `actions/` | `run.py`: `run_action`, the single entry point (F34). One module per action: `flatten`, `merge`, `split`, `images`, `compress`. |
| `ocr/` | Tesseract: page rendering, page OCR, and the text-layer-only mode. |
| `slides/` | PowerPoint files to PDF: optional Microsoft PowerPoint, LibreOffice fallback. |
| `tools/` | `process.py` (run a program with timeout/cancel), `locate.py` (find Tesseract, LibreOffice, PowerPoint), `check.py` (the Convert modal's tool check). |
| `pdf/` | Bookmark helpers. |
| `files/` | `info.py` (describe inputs for the file list), `naming.py` (`safe_destination`: never overwrite). |
| `platforms/` | `windows.py`, `posix.py`, `windows_powerpoint.py`, selected once in `__init__.py`. |

### Execution flow of one job

`run_action(action, settings, data, scratch=, progress=, cancel=)` in `actions/run.py`:

1. **Validate**: at least one file; each exists and is accepted by the action (`core/types.py: ACCEPTS`). If `use_ocr` is on (any action but Compress), Tesseract must be found **before** any slow work.
2. **Prepare** each input as a PDF in its own `scratch/item_NNN/`: PDFs are only read; PPT/PPTX go through `slides.render_slides`. Each prepared PDF is checked (unreadable, password-protected, empty → `ConversionError`).
3. **Act** (per action):

| Action | Steps | Output name |
| --- | --- | --- |
| Flatten | prepare → `flatten_pdf` (render each page; OCR it if `use_ocr`) | `<name> - Flattened[ Searchable].pdf` per input |
| Flatten + Merge | flatten each → `merge_documents` | `<first> + N more - Flattened[ Searchable] Merged.pdf` |
| Merge | prepare (+ OCR text layer if `use_ocr`) → `merge_documents` | `<first> + N more - Merged.pdf` |
| Split | prepare (+ OCR text layer) → `split_pdf` | `<name> - pages a-b.pdf` / `- page a.pdf` |
| Images to PDF | `images_to_pdf` (+ OCR text layer per output) | `<first> + N more - Images.pdf` or `<image>.pdf` |
| Compress | check → `compress_pdf` | `<name> - Compressed.pdf` |

4. **Return** `JobResult(outputs, warnings)`. Outputs stay in scratch; the API layer copies them out with `safe_destination` when the user saves (results are never lost if the folder picker is cancelled, F12).

Errors: fatal problems raise `ConversionError(issue)`; a user cancel raises `Cancelled`; anything else is a bug and the caller reports it as `UNEXPECTED_ERROR` with the traceback.

### Cross-cutting mechanisms

- **Cancellation and timeouts (C5).** `JobContext.check_cancel()` is called between pages and files. External programs run through `tools.process.run_command`, which registers the process on the `CancelToken` so Cancel kills it immediately, and kills the whole process tree on timeout. Defaults: 120 s per OCR page (setting), 300 s per PowerPoint or LibreOffice export.
- **Progress.** Steps call `ctx.report(stage, message, page, page_count)`. Within a *phase* each input gets an equal share; multi-phase actions (flatten then merge, OCR then merge) call `ctx.begin_phase(start, span, count)` so the bar never moves backwards (tested).
- **Warnings vs errors.** A warning (e.g. `POWERPOINT_FALLBACK`) is collected with `ctx.warn()` and returned with the results; an error stops the job. All wording, including troubleshooting steps, lives in `core/issues.py`.
- **Logging (C13).** Modules log with `logging.getLogger(__name__)`; `run_command` logs every command, its duration, exit code and output at DEBUG. The API layer chooses the level (DEBUG in development, INFO in production; errors always in full).
- **Originals are never modified.** Inputs are opened read-only; PowerPoint files are rendered from a scratch copy; tests compare input hashes before and after.

## API layer (`api/`)

Started by `main.py` → `api.app.main()`, which configures logging, creates the pywebview window and exposes `api.bridge.Api` to the page as `window.pywebview.api`.

| Module | Responsibility |
| --- | --- |
| `app.py` | Window creation (1200×800, min 960×640), choosing what to load (the built `frontend/dist/index.html` as a `file://` URL; in dev mode an `http(s)` URL from `PDF_MANAGER_UI_URL`), a fallback page if the UI is missing, clean shutdown. |
| `bridge.py` | `Api`: exactly the contract's methods (`docs/API.md`). Every public method catches errors and returns contract-shaped results with an `Issue`, so nothing raises into JavaScript. Events go to the page by dispatching `pdfmanager:<name>` DOM events. Also native pickers, OCR search/install (winget), opening folders, and drag-and-drop paths. |
| `jobs.py` | `JobManager`: one job at a time on a worker thread calling `converter.run_action`; throttled progress (≤ 1 event / 100 ms, final event always delivered); one state per job (running → ready → saving → gone) so save, discard and shutdown never race (audit R4); saving copies in chunks with exclusive-create (never overwrites), optional zip. |
| `settings_store.py` | Persisted settings (`%LOCALAPPDATA%\PDFManager\settings.json` on Windows, XDG elsewhere): validated fields, atomic writes, updates applied first-come-first-served; a failed write returns the in-memory settings plus a `SETTINGS_SAVE_FAILED` issue (audit R6). |
| `dto.py` | camelCase JSON ↔ service dataclasses; invalid UI input becomes an `UNEXPECTED_ERROR` issue. |
| `logging_setup.py` | Rotating log files (2 MB × 5) next to the installed app (C4), DEBUG in dev mode and INFO in production (C13); `log_issue` records every issue shown to the user. |
| `paths.py` | App, bundled-resource, logs and settings locations in source vs frozen (PyInstaller) mode. |
| `service.py` | The single import seam from the API layer into `converter/`. |

**Drag and drop:** a web page can't see real file paths, so Python subscribes to the document's `drop` event (pywebview `DOMEventHandler`), reads `pywebviewFullPath` for each file, describes it with `converter.inspect_file` and sends a `filesAdded` event.

**Platform note:** the API layer's Windows-specific behaviour (winget, `os.startfile`, picker filters) is currently gated by `paths.on_windows()` checks inside `bridge.py`, not isolated in one platform module as P15 asks. Tracked in `ENGINEERING_REVIEW.md`.

## Frontend (`frontend/`)

Vite + React + TypeScript, CSS Modules, feature folders (`pages/`, `components/`, `styles/`), Vitest + React Testing Library tests next to the code. No router or state library: the sidebar tab is app state.

- `src/api/`: `types.ts` (the contract), `bridge.ts` (pywebview calls and `pdfmanager:*` events), `mock.ts` (an in-memory backend for `npm run dev` and tests; excluded from production builds), `client.ts` (picks one).
- `src/state/`: app state (reducer + context). Settings changes apply on screen immediately; saves are queued one at a time, with pending changes merged, so a late reply can never undo a newer choice (audit R5). A failed save shows a "Not saved" warning in Settings (R6).
- `src/pages/`: Home (drop zone, shared file list, action buttons), one `ActionPage` per action, Settings.
- `src/components/`: shared pieces (file list with dnd-kit reordering, `InfoTip` (?) tooltips, the Convert modal's issue view, buttons, modal, progress).
- **Build:** `npm run build` produces **one self-contained `dist/index.html`** (JS, CSS and IBM Plex fonts inlined, via `vite-plugin-singlefile`). WebView2 blocks module scripts and fonts loaded over `file://`, and the app has no local server (F18), so nothing may be fetched at runtime.
- **Themes:** CSS custom properties per theme (`data-theme` on `<html>`): system (follows Windows), light, dark, burgundy, green. A tiny inline script picks light/dark before first paint.

## Non-obvious implementation choices

| Where | Choice | Why |
| --- | --- | --- |
| `slides/render.py`, `platforms/` | The scratch copy **keeps** the Windows Mark-of-the-Web. Downloaded presentations are rendered by LibreOffice, never automated with PowerPoint, with an `UNTRUSTED_PRESENTATION` warning (C14, audit R1). | Stripping the marker (an earlier version did) bypasses Office's Protected View trust signal. Files from the internet open in Protected View, which hidden automation can't use anyway. |
| `slides/render.py` | PowerPoint and LibreOffice write into separate, freshly emptied folders (audit R3). | A partial file from a failed PowerPoint export must never be accepted as LibreOffice's result. LibreOffice can exit 0 without writing anything. |
| `platforms/windows_powerpoint.py` | Export on a helper thread; quit or kill PowerPoint **only if the converter can prove it started that process**: PowerPoint wasn't running, exactly one new `POWERPNT.EXE` appeared, and it is the automation window's process (`owned_pid`, audit R2). Any doubt: never kill or quit. | PowerPoint is single-instance, so the converter may attach to the user's open PowerPoint. The thread allows a timeout when PowerPoint hangs (e.g. "Waiting for printer connection"). |
| `slides/render.py` | LibreOffice runs with a throwaway profile; success also requires a non-empty output file. | With the user's LibreOffice open, the command would otherwise hand off and do nothing; LibreOffice often exits 0 on failure. |
| `tools/process.py`, `platforms/` | Kill the whole process tree (`taskkill /T`, or a process group on Linux). | `soffice` starts `soffice.bin`; killing only the parent leaves the real worker running. |
| `actions/flatten.py` | Page images and OCR files stay in scratch until the job ends. | Deleting them immediately caused WinError 32 on Windows (file still held by a renderer or virus scanner). Regression test: `tests/test_temp_lock.py`. |
| `ocr/tesseract.py` | Non-flatten OCR uses Tesseract's `textonly_pdf=1` and overlays the invisible text onto the **original** page; only pages with no extractable text are OCR'd; rotation is undone when overlaying. | Keeps the page exactly as it looked. Limitation: a page that is mostly a scanned image but has a little real text (e.g. a typed page number) is not OCR'd. |
| `actions/merge.py` | Contents pages are inserted first, then drawn, with `insert_htmlbox`. | Links can target final page indexes (inserting pages doesn't break existing links, which point at page objects). HTML boxes fall back to fonts that cover Arabic, Greek, CJK, so file names in any language render. |
| `actions/merge.py` | Page labels: contents `i, ii…`, content `1…N` (C8). | Viewer numbering without printing anything on pages. |
| `pdf/bookmarks.py` | Repair bookmark lists (levels, page ranges) before setting them; never fail the job over bookmarks. | Real-world outlines are often slightly invalid and PyMuPDF rejects them. |
| `actions/merge.py` | Each input's own bookmarks are nested under a top-level bookmark for that input. | C6. Note: LibreOffice adds a "Slide N" bookmark per slide, so rendered decks contribute one bookmark per slide. |
| `actions/images.py` | Page size from the image's DPI (96 if missing), longest side capped at 842 pt (A4); EXIF orientation applied by PyMuPDF's own image-to-PDF conversion; JPEG data embedded unchanged. | Avoids giant pages from phone photos. Page sizing was an engineering choice (not owner-specified). |
| `actions/compress.py` | Balanced: images above 200 DPI → 150 DPI, JPEG q75. Strong: above 120 → 96 DPI, q50. Light: lossless clean-up only. Never returns a bigger file. Uses PyMuPDF's low-level `mupdf.PdfImageRewriterOptions`. | Exact target resolutions need bicubic subsampling options the simple `rewrite_images` arguments don't offer. The low-level API is more likely to change between PyMuPDF versions (tests would catch it). |
| `actions/split.py` | Ranges accept spaces and en/em dashes; overlapping ranges allowed; each part keeps in-range bookmarks with shifted pages and drops links to pages outside it. | Friendly input; valid output files. |

## Dependencies

Runtime: **PyMuPDF** (all PDF work), **pywin32** (Windows only, optional PowerPoint). External programs: **Tesseract** (OCR, optional), **LibreOffice** (slides; required on Linux, backup on Windows), **Microsoft PowerPoint** (optional, Windows). The API layer uses **pywebview** (the window and the JS bridge; Edge WebView2 on Windows). The frontend's runtime dependencies are React and dnd-kit; the font is bundled. Details and per-platform package names: [`../README.md`](../README.md), [`PORTABILITY.md`](PORTABILITY.md). Python ≥ 3.11 (uses `StrEnum`); pinned to 3.13.

Known dependency notes: the code imports `pymupdf` (the old `fitz` name is deprecated in 1.28); `pymupdf.image_profile` raises a `TypeError` in the installed 1.28.2, so it isn't used.

## Tests

Python: `uv run pytest` (on 2026-11-23, Linux: **355 passed, 5 skipped**; the skipped ones are Windows-only NTFS tests). Tests needing Tesseract or LibreOffice skip when those aren't installed. Frontend: `npm test` in `frontend/` (**83 passed**).

| Where | Covers |
| --- | --- |
| `tests/test_end_to_end.py` | Every action through `run_action`: naming, page counts, OCR on/off, contents page, order, monotonic progress, cancel, missing OCR, wrong file types, inputs unchanged. |
| `tests/test_flatten.py`, `test_merge.py`, `test_split.py`, `test_images.py`, `test_compress.py`, `test_ocr.py` | Each action and the OCR text layer in detail. |
| `tests/test_powerpoint.py` | Renderer order and fallback with a **fake** PowerPoint; untrusted-file routing (R1); the partial-output scenario (R3, fails on the old code); proven process ownership (R2); the COM helper thread's timeout/cancel rules. Real PowerPoint is never exercised. |
| `tests/test_provenance.py` | Mark-of-the-Web parsing; on Windows (CI), real NTFS zone streams and that copies keep them. |
| `tests/test_tools.py`, `test_portability.py`, `test_temp_lock.py` | Running/killing external programs; no OS checks in shared service code; the WinError 32 regression. |
| `tests/api/` | Paths, logging, settings store (including failed writes, R6), DTOs, job manager (including deterministic save/discard/shutdown races, R4), bridge contract (method names and argument lists), app entry, the import seam (R8). No real window is opened. |
| `frontend/src/**/*.test.ts(x)` | Bridge mapping, mock, file list, action options and defaults, Split validation, Convert modal flow, settings save ordering (R5) and failure display (R6), tooltips. |

## CI

- **`.github/workflows/ci.yml`** (every push and pull request, decision F37): Python lint, format check and tests on **Linux** (with Tesseract and LibreOffice installed) and on **Windows** (without them, so OCR/slide tests skip there); frontend typecheck, lint, tests and the single-file build check. A newer push cancels an older run on the same branch.
- **`.github/workflows/build-windows.yml`**: builds the Windows installer (PyInstaller + Inno Setup). **Manual trigger only.** Not run yet.
