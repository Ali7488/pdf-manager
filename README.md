# SlideStitch

A lightweight desktop tool for converting PowerPoint presentations and PDFs into flattened, searchable documents, with OCR and merging. It targets Windows.

Flattening renders every page to an image, so the result opens cleanly in apps that struggle with complex PDFs (for example note-taking apps on tablets). Tesseract OCR then adds an invisible text layer, so the flattened PDF is still searchable and selectable.

Built with Python/Tkinter, PyMuPDF, Tesseract OCR, ReportLab and python-pptx, plus Microsoft PowerPoint or LibreOffice for slide rendering.

**Status: working baseline (v1.1.1) under engineering review. Not yet a public release.**

## Modes

- **Flatten**: each file becomes its own image-backed, OCR-searchable PDF.
- **Flatten + Merge**: flatten and OCR every file, then combine them in the chosen order.
- **Merge**: combine PDFs and rendered PowerPoints without rasterizing, keeping the original text.

Input files are never modified. Outputs are built in a temporary folder and saved with collision-safe filenames. PowerPoint speaker notes are appended automatically, which is a known content-quality risk when presentations contain stale or unrelated notes.

## Windows

Run `INSTALL.bat` once (it creates a virtual environment and installs Tesseract and LibreOffice through `winget` if they are missing), then start the app with `OPEN.bat`. Review the installer before distributing it publicly.

## Development (Linux)

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# Tesseract (English) and LibreOffice must be installed for the integration tests.
.venv/bin/python tests/smoke_test.py
.venv/bin/python tests/test_temp_lock.py
.venv/bin/python app.py
```

## Dependencies

Python packages (`requirements.txt`):

| Package | Used in | Why |
| --- | --- | --- |
| PyMuPDF (`fitz`) | `flatten.py`, `merge.py`, `pipeline.py` | Opens and validates PDFs, renders pages to images, stamps OCR pages into the output, merges documents. |
| python-pptx | `notes.py` | Reads speaker notes from PPTX files. |
| ReportLab | `notes.py` | Typesets the speaker-notes appendix as a PDF. |
| pywin32 (Windows only) | `powerpoint.py` | Drives Microsoft PowerPoint through COM to export slides as PDF. |

External programs:

| Program | Required for | Why |
| --- | --- | --- |
| Tesseract OCR (English) | Flatten, Flatten + Merge | Turns each page image back into searchable text. |
| Microsoft PowerPoint | PowerPoint inputs (preferred) | Gives the most faithful slide rendering on Windows. |
| LibreOffice | PowerPoint inputs (fallback), notes from `.ppt` | Converts slides to PDF when PowerPoint isn't available, and converts old `.ppt` files to `.pptx` so their notes can be read. |
| winget | Optional | Lets the app and installer install Tesseract automatically. |

The GUI uses only the standard library (Tkinter).

## Layout

- `app.py`: Tkinter dashboard and local settings.
- `converter/`: the conversion engine, split by responsibility. `from converter import ...` exposes the public API.
  - `common.py`: shared constants (modes, supported extensions, DPI) and the progress-callback type.
  - `tools.py`: finding Tesseract and LibreOffice, and running external programs without a console window.
  - `powerpoint.py`: rendering PPT/PPTX to PDF with Microsoft PowerPoint, falling back to LibreOffice.
  - `notes.py`: extracting speaker notes and building the notes appendix PDF.
  - `flatten.py`: rasterizing pages and adding the OCR text layer.
  - `merge.py`: combining PDFs in order.
  - `pipeline.py`: preparing and validating each input, then running the chosen mode.
  - `output.py`: collision-safe output filenames.
- `SlideStitch.ico`: application icon (`app.py` loads it from the repository root).
- `assets/`: preview images (not needed at runtime).
- `tests/`: integration test and Windows file-lock regression test.
- `docs/`: import provenance and review checklist.

## Privacy

Everything is processed locally. Do not commit real user documents, private data or third-party sample files.

## Known issues

See [`docs/ENGINEERING_REVIEW.md`](docs/ENGINEERING_REVIEW.md).
