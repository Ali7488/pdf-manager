# PDF Manager

A lightweight, offline app for preparing PDFs and PowerPoint documents. The portable build opens in your default browser. The desktop test build uses pywebview. Both use the same React interface and Python conversion engine.

The [v0.5.0-rc.1 test build](https://github.com/Ali7488/pdf-manager/releases/tag/v0.5.0-rc.1) is available. The owner confirmed that PDF workflows passed on a Windows 11 VM. See the [v0.5.0 release notes](docs/releases/v0.5.0.md) for the planned stable release and validation scope.

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

The app reads originals and writes results to new files. Work happens in a temporary folder on your computer. The app runs without an account or cloud service.

## Install

### Windows 11 x64 portable ZIP

Download `PDF-Manager-0.5.0-browser-windows-x64.zip` from [GitHub Releases](https://github.com/Ali7488/pdf-manager/releases). Compare its PowerShell `Get-FileHash` output with the checksum in `SHA256SUMS.txt`.

1. Install the **Microsoft Visual C++ Redistributable (x64)**, version 14.44 or newer, if you don't have it (`https://aka.ms/vc14/vc_redist.x64.exe`; it needs administrator permission).
2. Unzip **`PDF-Manager-<version>-browser-windows-x64.zip`** and double-click **`PDF Manager.exe`** in the folder.
3. **Browser expectation:**
   - If your **default browser is Microsoft Edge or a Chromium-based browser** (Google Chrome, Brave, Chromium), PDF Manager opens in **its own window, with no tabs or address bar** (app mode).
   - **With any other default browser (for example Firefox), it opens as a normal tab** in that browser, at a local address (`http://127.0.0.1:...`).
   - Either way it works offline, and your files never leave your computer.
4. Closing the window leaves PDF Manager running, so it reopens quickly. Quit it from **Settings → Quit PDF Manager**. It also quits by itself after an hour without use, but never while a result is waiting to be saved.

### Windows desktop installer test build

The unsigned desktop installer is available on the [RC1 test release](https://github.com/Ali7488/pdf-manager/releases/tag/v0.5.0-rc.1). Installer acceptance and WebView2 licensing review are still open. See the [packaging guide](packaging/README.md).

### Linux (Ubuntu/Debian, Arch)

Linux packages are planned for **v0.75**. Until then, run it from source (see *Development* below).

## Testing without the window (CLI)

A command-line tool runs every function through the same engine as the app, on Windows and Linux. Use a dedicated output directory for each concurrent CLI process. With the source checked out and [uv](https://docs.astral.sh/uv/) installed:

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
         +-- LibreOffice   converts PowerPoint files (Impress), on every system
```

The interface is one self-contained HTML file loaded in the window: **no local web server** (browser mode adds a loopback-only one, [details](docs/BROWSER_MODE.md)). PowerPoint files are converted with **LibreOffice Impress**, which PDF files and images never need. For a deck that has to look exactly as it does in PowerPoint, export it to PDF in PowerPoint and add that PDF ([fidelity notes](docs/PRESENTATION_FIDELITY.md)).

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
- [Browser mode](docs/BROWSER_MODE.md): the app in your own browser. It opens in app mode with Edge or a Chromium-based browser, otherwise as a localhost tab. Also covers security and the portable ZIP.
- [Decisions](docs/DECISIONS.md): the owner's decisions.
- [Engineering review](docs/ENGINEERING_REVIEW.md): known issues, test evidence and verification gaps.
- [Portability](docs/PORTABILITY.md): Windows and Linux considerations.
- [Packaging guide](packaging/README.md): Windows build and installer details.

## Verification status

CI runs Python, frontend, browser integration, and Windows packaging checks. The owner reported passing Windows 11 VM PDF workflows on RC1. Windows presentation fidelity, OCR, and installer acceptance need separate results. Report problems via [Issues](https://github.com/Ali7488/pdf-manager/issues).

## Privacy and contributions

All document processing runs locally. Never commit real user documents, copyrighted material, credentials or personal file paths.

This project is developed with Claude Code and AI subagents under human-directed requirements and architectural decisions. Generated changes require human code review and runtime validation before the v1.0 release.

**Licence:** free and open source. The original code is [MIT](LICENSE); the distributed app includes PyMuPDF and is therefore distributed under the [GNU AGPL-3.0](LICENSE-AGPL-3.0.txt). See [LICENSING.md](LICENSING.md) for what applies to what, the complete source and build instructions, and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for every bundled component.
