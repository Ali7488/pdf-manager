# PDF Manager

A lightweight desktop tool for converting PowerPoint presentations and PDFs into flattened, searchable documents, with OCR and merging. It targets Windows.

Flattening renders every page to an image, so the result opens cleanly in apps that struggle with complex PDFs (for example note-taking apps on tablets). Tesseract OCR then adds an invisible text layer, so the flattened PDF is still searchable and selectable.

Built with Python/Tkinter, PyMuPDF and Tesseract OCR, plus Microsoft PowerPoint or LibreOffice for slide rendering.

**Status: working baseline (v1.1.1) under engineering review. Not yet a public release.**

## Modes

- **Flatten**: each file becomes its own image-backed, OCR-searchable PDF.
- **Flatten + Merge**: flatten and OCR every file, then combine them in the chosen order.
- **Merge**: combine PDFs and rendered PowerPoints without rasterizing, keeping the original text.

Input files are never modified. Outputs are built in a temporary folder and saved with collision-safe filenames. Only the slides are converted; PowerPoint speaker notes are not included.

## Windows

Run `INSTALL.bat` once (it installs [uv](https://docs.astral.sh/uv/) if needed, uses it to set up Python and the dependencies in `.venv`, and installs Tesseract and LibreOffice through `winget` if they are missing), then start the app with `OPEN.bat`. Review the installer before distributing it publicly.

## Development

```bash
uv sync          # creates .venv with the pinned Python and all dependencies
uv run pytest    # all tests; ones needing Tesseract or LibreOffice skip if those are missing
uv run app.py    # the old Tkinter UI, until the new desktop app replaces it
```

## Dependencies

Python packages (`pyproject.toml`, locked in `uv.lock`):

| Package | Used in | Why |
| --- | --- | --- |
| PyMuPDF (`pymupdf`) | `converter/actions/`, `converter/ocr/`, `converter/pdf/` | All PDF work: opening and validating, rendering pages to images, placing OCR text, merging, splitting, image conversion, compression, bookmarks, links and page labels. |
| pywin32 (Windows only) | `converter/platforms/windows_powerpoint.py` | Optional: drives Microsoft PowerPoint through COM to export slides as PDF. |

External programs:

| Program | Required for | Why |
| --- | --- | --- |
| Tesseract OCR (English) | Any action with "Use OCR" ticked | Reads the text in page images so it can be searched and copied. |
| Microsoft PowerPoint | PowerPoint inputs (preferred) | Gives the most faithful slide rendering on Windows. |
| LibreOffice | PowerPoint inputs (fallback) | Converts slides to PDF when PowerPoint isn't available. |
| winget | Optional | Lets the app and installer install Tesseract automatically. |

The GUI uses only the standard library (Tkinter).

Development only (the `dev` dependency group): pytest, and python-pptx (the tests use it to build a sample PPTX file).

## Layout

- `app.py`: Tkinter dashboard and local settings.
- `converter/`: the conversion engine (service layer), in folders by responsibility. `from converter import ...` is the public API; `run_action(action, settings, data)` is the single entry point.
  - `core/`: shared types (`types.py`), user-facing issues with troubleshooting steps (`issues.py`), per-job cancel/progress/warnings (`context.py`).
  - `actions/`: `run.py` (the entry point) plus one module per action: flatten, merge, split, images, compress.
  - `ocr/`: Tesseract OCR, including the text-layer-only mode.
  - `slides/`: PowerPoint files to PDF (PowerPoint optional, LibreOffice fallback).
  - `tools/`: running external programs (`process.py`), finding them (`locate.py`), the Convert tool check (`check.py`).
  - `pdf/`: bookmark helpers. `files/`: describing inputs and choosing safe output names.
  - `platforms/`: everything OS-specific (Windows, POSIX, the optional PowerPoint renderer).
- `frontend/`: React UI (in progress). `api/`: the Python bridge between them (in progress).
- `packaging/`: Windows build (PyInstaller), install wizard (Inno Setup), build script.
- `PDF Manager.ico`: application icon (`app.py` loads it from the repository root).
- `assets/`: preview images (not needed at runtime).
- `tests/`: pytest suite (unit, end-to-end and the Windows file-lock regression).
- `docs/`: decisions, prompts log, API contract, portability, engineering review, source inventory.

## Privacy

Everything is processed locally. Do not commit real user documents, private data or third-party sample files.

## Known issues

See [`docs/ENGINEERING_REVIEW.md`](docs/ENGINEERING_REVIEW.md).
