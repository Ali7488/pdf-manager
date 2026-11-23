# PDF Manager

A lightweight, offline desktop application for converting, preparing, and organizing PDF and PowerPoint documents. Built with **React + TypeScript** for the interface, a **Python** document-processing engine, and **pywebview** for a native desktop window.

> **Project status:** Active development. The React frontend, Python bridge, conversion engine, and Windows packaging source are merged. Automated tests have been reported passing by the development agents, but the packaged application, installer, and Microsoft PowerPoint integration **have not yet been verified on a real Windows 11 system**. This is **not a supported public release**.

## Features

| Tool | What it does | Inputs |
| --- | --- | --- |
| **Flatten** | Turns each page into a fixed image-backed PDF; optionally adds searchable OCR text. | PDF, PPT, PPTX |
| **Flatten + Merge** | Flattens several documents and combines them in the selected order. | PDF, PPT, PPTX |
| **Merge** | Combines documents while retaining existing PDF text where possible. | PDF, PPT, PPTX |
| **Split** | Extracts specified page ranges, every N pages, or individual pages. | PDF, PPT, PPTX |
| **Images to PDF** | Converts JPEG/PNG images into one combined PDF or separate PDFs. | JPG, JPEG, PNG |
| **Compress PDF** | Offers light, balanced, and strong compression. | PDF |

Additional capabilities include optional Tesseract OCR, drag-and-drop file selection and reordering, PDF bookmarks and optional contents pages, cancellation, progress updates, collision-safe output names, and clear errors with troubleshooting guidance.

**Document safety:** The application is designed to leave source documents unchanged. Conversion takes place in temporary storage, and completed results are saved as new files. This behavior has automated test coverage, but the final packaged Windows application still needs acceptance testing. Speaker-note export is intentionally **not** included.

## How it works

```text
React + TypeScript (frontend/)
         |
         | pywebview JavaScript ↔ Python API
         v
Python desktop bridge (api/)
         |
         | jobs, settings, progress, file dialogs, saving
         v
Document conversion engine (converter/)
         |
         +-- PyMuPDF       PDF processing, image rendering, merging
         +-- Tesseract     Optional offline OCR
         +-- PowerPoint    Optional Windows slide renderer (COM)
         +-- LibreOffice   Cross-platform slide renderer / fallback
```

The production frontend is bundled as a self-contained HTML asset and loaded in a desktop window. **No local web server, user account, or cloud document processing is required.** Document processing and installation of optional helpers occur locally.

## Windows installation

The intended distribution is a Windows 11 installer (Inno Setup + PyInstaller), using a normal Start-menu shortcut and an optional Desktop shortcut. It installs per user without requiring administrator access for the application itself.

**There is no verified release installer yet.** Once the first Windows CI build succeeds, test its installer artifact on a Windows 11 machine before using it with important documents.

Optional helpers:

- **Tesseract OCR** for searchable text. The app can perform non-OCR operations without it.
- **Microsoft PowerPoint or LibreOffice** for converting PPT/PPTX presentations. PowerPoint is Windows-only; LibreOffice is the fallback.
- **Microsoft Edge WebView2 Runtime** to display the Windows desktop interface. This is normally available on Windows 11.

See [Windows packaging](packaging/README.md) for build prerequisites, installer behavior, optional dependency installation, uninstall behavior, and the acceptance checklist.

## Development setup

Prerequisites: [uv](https://docs.astral.sh/uv/) for Python dependencies, Node.js and npm for the frontend, and the platform's required pywebview runtime. The repository contains `uv.lock` and `frontend/package-lock.json` for repeatable dependency resolution.

**Build the interface and launch the desktop application:**

```bash
uv sync --frozen
cd frontend
npm ci
npm run build
cd ..
uv run main.py
```

The application entry point is **`main.py`**. The earlier Tkinter frontend and its batch/PowerShell launchers have been retired from this repository.

**Run checks:**

```bash
uv run pytest
uvx ruff check --line-length 100 .
uvx ruff format --check --line-length 100 .
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

Some Python integration tests need local Tesseract or LibreOffice and may skip when those tools are absent. Linux development is possible, but Linux desktop runtime dependencies and distribution packages are not yet a supported release target.

## Building a Windows installer

On a Windows build machine with uv, Node.js/npm, and Inno Setup 6 installed:

```powershell
./packaging/build.ps1
```

The build script creates the React bundle, synchronizes locked Python dependencies, packages the desktop app with PyInstaller, and compiles an Inno Setup installer under `dist/installer/`.

A [manual GitHub Actions workflow](.github/workflows/build-windows.yml) can also build and upload a Windows installer artifact. **That workflow is not a substitute for automated PR testing or real-machine verification, and its successful execution has not yet been confirmed.**

## Repository layout

```text
api/                   Python bridge: settings, file dialogs, jobs, events, saving
converter/             UI-independent document-processing services
frontend/              React, TypeScript, Vite, CSS Modules, and frontend tests
packaging/             PyInstaller spec, PowerShell build script, Inno Setup wizard
tests/                 Python tests, including integration and regression coverage
docs/                  Architecture, API contract, decisions, engineering review
.github/workflows/     Manual Windows installer build
main.py                Desktop application entry point
PDF Manager.ico        Windows application icon
pyproject.toml         Python project/dependency metadata
uv.lock                Python dependency lockfile
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md): service, API, and UI boundaries.
- [UI ↔ Python API](docs/API.md): bridge methods, JSON models, and events.
- [Decisions](docs/DECISIONS.md): owner-approved requirements and unresolved questions.
- [Engineering review](docs/ENGINEERING_REVIEW.md): known issues, test evidence, and verification gaps.
- [Portability](docs/PORTABILITY.md): Linux compatibility considerations.
- [Packaging guide](packaging/README.md): Windows build and installation details.

## Current verification limits

The development agents reported **317 passing Python tests** and passing frontend checks after merging their work. These results have **not been independently rerun for this README update**. In particular, Windows PowerPoint COM behavior, WebView2 startup, the installer, updates/uninstalls, optional helper installation, and real-user workflows still require Windows testing.

Do not treat a successful frontend build or simulated Windows test as proof of a working packaged Windows application.

## Privacy and contributions

All document processing is designed to run locally. Never commit real user documents, copyrighted lecture slides used as fixtures, credentials, or personally identifying file paths.

This project is being developed using Claude Code and AI subagents under human-directed product requirements and architectural decisions. Generated changes require human code review and runtime validation before release. Contributions and engineering outcomes should be represented accurately.

**License:** Not yet selected; the repository remains private. Do not assume permission to redistribute code or binaries until licensing is finalized.
