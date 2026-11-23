# Architecture

How PDF Manager is put together, how a conversion runs, and the implementation choices that aren't obvious from reading one file. Owner decisions are referenced by their IDs in [`DECISIONS.md`](DECISIONS.md); known bugs and what has or hasn't been verified are in [`ENGINEERING_REVIEW.md`](ENGINEERING_REVIEW.md).

> **Status:** the service layer (`converter/`) and the Windows packaging scripts are merged. The API layer (`api/`) and the React frontend (`frontend/`) are still being built; their sections below will be filled in when they are merged.

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

## Non-obvious implementation choices

| Where | Choice | Why |
| --- | --- | --- |
| `slides/render.py` | Render PowerPoint files from a plain byte copy in scratch. | Downloaded files carry the Windows Mark-of-the-Web; PowerPoint opens them in Protected View, which hidden automation can't use. A likely cause of the reported "falls back to LibreOffice too often" (unconfirmed on Windows). |
| `platforms/windows_powerpoint.py` | Export on a helper thread; quit or kill PowerPoint **only if the converter started it** (C2). | PowerPoint is single-instance, so the converter may attach to the user's open PowerPoint. The thread allows a timeout when PowerPoint hangs (e.g. "Waiting for printer connection"). |
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

Runtime: **PyMuPDF** (all PDF work), **pywin32** (Windows only, optional PowerPoint). External programs: **Tesseract** (OCR, optional), **LibreOffice** (slides; required on Linux, backup on Windows), **Microsoft PowerPoint** (optional, Windows). The API layer will add **pywebview**. Details and per-platform package names: [`../README.md`](../README.md), [`PORTABILITY.md`](PORTABILITY.md). Python ≥ 3.11 (uses `StrEnum`); pinned to 3.13.

Known dependency notes: `import fitz` prints a deprecation notice in PyMuPDF 1.28 (switching to `import pymupdf` is an open cleanup); `fitz.image_profile` raises a `TypeError` in the installed 1.28.2, so it isn't used.

## Tests

`uv run pytest` runs everything in `tests/`. Tests needing Tesseract or LibreOffice are skipped when those aren't installed.

| File | Covers |
| --- | --- |
| `test_end_to_end.py` | Every action through `run_action`: naming, page counts, OCR on/off, contents page, order, monotonic progress, cancel, missing OCR, wrong file types, inputs unchanged. |
| `test_flatten.py`, `test_merge.py`, `test_split.py`, `test_images.py`, `test_compress.py`, `test_ocr.py` | Each action and the OCR text layer in detail (bookmarks, labels, links, EXIF, levels, rotated pages, password-protected files). |
| `test_powerpoint.py` | Renderer order and fallback warnings with a **fake** PowerPoint; the COM helper thread's timeout/cancel/kill rules with a fake export. Real PowerPoint is never exercised. |
| `test_tools.py` | Registry path parsing, `run_command` output, timeout, cancel and child-process killing. |
| `test_portability.py` | Fails if shared service code contains OS checks or Windows-only APIs outside `converter/platforms/`. |
| `test_temp_lock.py` | WinError 32 regression (simulated). |

All tests run on Linux only so far.

## CI

- `.github/workflows/build-windows.yml`: builds the Windows installer on `windows-latest`. **Manual trigger only** (`workflow_dispatch`) to avoid spending Actions minutes on a private repo. Not run yet; it can't succeed until `api/`, `main.py` and the frontend are merged.
- There is **no automated test run in CI** yet; tests are run locally.
