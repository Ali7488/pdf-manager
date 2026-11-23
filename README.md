# PDF Manager

A lightweight, offline desktop application for converting, preparing and organizing PDF and PowerPoint documents. The interface is **React + TypeScript**, the document engine is **Python**, and **pywebview** gives it a native desktop window.

> **⚠️ Pre-release for testing (v0.5).** This version is for testing only. The installer is **unsigned** and has **not yet been verified on a real Windows 11 PC**. Don't use it as your only copy of important documents. The full v1.0 release will follow after manual verification of the functions, code and features.

## What it does

| Tool | What it does | Inputs |
| --- | --- | --- |
| **Flatten** | Turns every page into a single image, so PDFs open reliably in apps that struggle with complex PDFs (for example tablet note-taking apps). Optional OCR makes the pages searchable again. | PDF, PPT, PPTX |
| **Flatten + Merge** | Flattens several documents and combines them in the order you choose. | PDF, PPT, PPTX |
| **Merge** | Combines documents, keeping their text, links and bookmarks. Optional clickable contents page. | PDF, PPT, PPTX |
| **Split** | Splits by page ranges (e.g. `1-3, 5, 8-10`), every N pages, or one file per page. Save as files or one zip. | PDF, PPT, PPTX |
| **Images to PDF** | Turns photos and images into one combined PDF or one PDF per image (photos stay upright). | JPG, PNG |
| **Compress** | Makes PDFs smaller: Light, Balanced or Strong. | PDF |

Also: drag and drop, drag to reorder, optional **OCR** (Tesseract) on every tool except Compress, progress and Cancel, an optional default save folder, four colour themes, and plain-language error messages with troubleshooting steps.

**Your files are safe:** originals are only read, never changed. Work happens in a temporary folder and results are saved as new files; existing files are never overwritten. Everything runs on your computer: no account, no cloud.

## Install

### Windows 11

1. Open the [Releases page](https://github.com/Ali7488/pdf-manager/releases) and download **`PDF-Manager-Setup-<version>.exe`** from the latest pre-release.
2. **Double-click it.** Because the installer isn't signed yet, Windows SmartScreen may say "Windows protected your PC": click **More info → Run anyway**.
3. Follow the short wizard. It installs for your user only (no administrator rights needed) and can optionally install:
   - **Tesseract OCR**, to make pages searchable (Windows may ask for permission);
   - **LibreOffice**, only needed if Microsoft PowerPoint isn't installed.
4. Start **PDF Manager** from the Start menu or the desktop icon.

You can install OCR later from the app's **Settings**. Logs are written to a `logs` folder next to the installed app (open it from Settings); settings are in `%LOCALAPPDATA%\PDFManager`.

### Linux (Ubuntu/Debian, Arch)

Linux packages are planned for **v0.75**. Until then, run it from source (see *Development* below).

## Testing without the window (CLI)

A command-line tool runs every function through the same engine as the app, on Windows and Linux. With the source checked out and [uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync
uv run scripts/make_samples.py          # creates test documents for every function in ./samples
uv run cli.py tools flatten samples/05-slides.pptx --ocr   # which helper programs a job needs
uv run cli.py flatten samples/01-text-report.pdf --ocr --out out
uv run cli.py merge samples/01-text-report.pdf samples/05-slides.pptx --contents --out out
uv run cli.py split samples/13-long-document.pdf --ranges "1-3, 5" --zip --out out
uv run cli.py images samples/07-photo-portrait.jpg samples/08-diagram.png --separate --out out
uv run cli.py compress samples/09-image-heavy.pdf --level strong --out out
uv run cli.py --help
```

`samples/README.txt` explains what each test document is for, including the expected error cases (a password-protected and a damaged PDF).

## How it works

```text
React + TypeScript (frontend/)
         |
         | pywebview JavaScript ↔ Python calls and events (docs/API.md)
         v
Python desktop bridge (api/)       jobs, settings, progress, file dialogs, saving, logs
         |
         v
Document engine (converter/)       one entry point: run_action(action, settings, data)
         +-- PyMuPDF       PDF processing, rendering, merging, splitting, compressing
         +-- Tesseract     optional offline OCR
         +-- PowerPoint    optional Windows slide renderer (COM)
         +-- LibreOffice   cross-platform slide renderer and fallback
```

The interface is one self-contained HTML file loaded in the window: **no local web server**. Presentations downloaded from the internet or email are converted with LibreOffice rather than opened by PowerPoint automation, to keep your computer safe.

## Development

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 24 and npm. On Linux, pywebview uses Qt (PySide6).

```bash
uv sync --frozen
cd frontend && npm ci && npm run build && cd ..
uv run main.py
```

Checks (CI runs the same tests; it lints `api`, `converter`, `tests` and `main.py`):

```bash
uv run pytest
uvx ruff check --select F,E9,I,E501 --line-length 100 api converter tests main.py cli.py scripts
uvx ruff format --check --line-length 100 api converter tests main.py cli.py scripts
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```

Tests that need Tesseract or LibreOffice skip when those aren't installed.

**CI:** every push runs Python tests on Linux (with Tesseract and LibreOffice) and Windows, plus the frontend checks ([`ci.yml`](.github/workflows/ci.yml)). The Windows installer is built by [`build-windows.yml`](.github/workflows/build-windows.yml); see the [packaging guide](packaging/README.md).

## Repository layout

```text
api/                   Python bridge: settings, file dialogs, jobs, events, saving, logs
converter/             UI-independent document engine (folders by responsibility)
frontend/              React, TypeScript, Vite, CSS Modules and frontend tests
packaging/             PyInstaller spec, PowerShell build script, Inno Setup wizard
scripts/               Test-document generator
tests/                 Python tests (unit, end-to-end, regression)
docs/                  Architecture, API contract, decisions, engineering review
cli.py                 Command-line front end for testing
main.py                Desktop application entry point
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md): layers, execution flows, non-obvious choices, tests and CI.
- [UI ↔ Python API](docs/API.md): bridge methods, JSON models and events.
- [Decisions](docs/DECISIONS.md): the owner's decisions.
- [Engineering review](docs/ENGINEERING_REVIEW.md): known issues, test evidence and verification gaps.
- [Portability](docs/PORTABILITY.md): Windows and Linux considerations.
- [Packaging guide](packaging/README.md): Windows build and installer details.

## Verification status

The Python suite (449 tests on Linux; on Windows CI, tests needing OCR or LibreOffice skip) and the frontend suite (95 tests) pass in CI. The packaged app, the installer, Microsoft PowerPoint automation and real-user workflows **still need testing on a real Windows 11 PC**; that's what this pre-release is for. Report problems via [Issues](https://github.com/Ali7488/pdf-manager/issues).

## Privacy and contributions

All document processing runs locally. Never commit real user documents, copyrighted material, credentials or personal file paths.

This project is developed with Claude Code and AI subagents under human-directed requirements and architectural decisions. Generated changes require human code review and runtime validation before the v1.0 release.

**Licence:** free and open source. The original code is [MIT](LICENSE); the distributed app includes PyMuPDF and is therefore distributed under the [GNU AGPL-3.0](LICENSE-AGPL-3.0.txt). See [LICENSING.md](LICENSING.md) for what applies to what, the complete source and build instructions, and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for every bundled component.
