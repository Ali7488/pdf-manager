# AGENTS.md

Engineering instructions for people and AI coding agents working on **PDF Manager**.

## Product and authority

Build a clear, low-overhead, **offline Windows 11 desktop application** for everyday PDF and PowerPoint processing. The product is intended for nontechnical users: installation, file selection, conversion, saving and troubleshooting must not require a terminal.

Read [`docs/DECISIONS.md`](docs/DECISIONS.md) before making behavior or design changes. Owner decisions there take precedence. Items marked **Open** need a decision and must not be silently resolved.

The repository currently contains a shared React + TypeScript frontend, a pywebview-backed Python API layer, and a UI-independent document conversion engine. The **supported development entry point is `main.py`**, not the retired Tkinter `app.py`.

## Architecture and files

- `frontend/`: React, TypeScript, Vite, CSS Modules, UI state and Vitest/Testing Library tests. The production build is a self-contained HTML asset for a pywebview window.
- `api/`: desktop window, Python↔JavaScript contract, settings, file handling, background jobs, progress and results.
- `converter/`: pure document processing and platform adapters; no UI-specific behavior.
- `main.py`: pywebview desktop entry point.
- `packaging/`: Windows PyInstaller build and Inno Setup wizard.
- `tests/`: Python unit, integration, portability and regression checks.
- `docs/`: API contract, decisions, architecture, engineering review, portability and prompts log.

## Development commands

From the repository root:

```bash
uv sync --frozen
cd frontend && npm ci && npm run build && cd ..
uv run main.py
```

Checks:

```bash
uv run pytest
uvx ruff check --select F,E9,I,E501 --line-length 100 api converter tests main.py cli.py scripts
uvx ruff format --check --line-length 100 api converter tests main.py cli.py scripts
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

Some Python tests require installed Tesseract or LibreOffice; report skips instead of counting them as passes. Do not claim Windows test success from Linux mocks. The GitHub Windows build is currently a manually triggered packaging workflow, **not** a complete PR CI pipeline.

For the Windows installer, see `packaging/README.md` and `packaging/build.ps1`.

## Engineering rules

- **Never modify originals.** Work in scratch space, validate outputs and save collision-safe new files.
- **No real user documents or identifying data.** Synthetic fixtures only; local processing only unless expressly approved otherwise.
- **No speaker notes.** Removed intentionally.
- **Keep platform-specific code isolated.** Windows PowerPoint COM is optional, LibreOffice is the cross-platform renderer. Linux packages come later; don't compromise Windows v1.
- **No unnecessary infrastructure.** No database, Docker runtime, web server, telemetry, accounts or new abstraction layers without a demonstrated requirement.
- **Accessible UI.** Plain-language controls, visible focus, readable contrast, friendly actionable error messages, minimal installation friction.
- **Coordinate subagents.** Check current working tree and integration contracts before parallel edits. Use focused commits and tests; do not silently change owner decisions.
- **Documentation is evidence.** Record architecture, tradeoffs, known issues, verifiable commands/results and Windows validation gaps accurately. Do not claim agent-written code has undergone human review unless that happened.
- **Function documentation.** Provide Google-style docstrings and comments for meaningful non-obvious behavior without filling code with redundant narration.
- **Git safety.** Before making changes, check `git status`; avoid overwriting uncommitted human/agent work. Keep commits small and meaningful. Do not publish installers, merge unrelated changes or declare release readiness without owner approval.
- **Prompt/decision records.** Summarize requests in `docs/PROMPTS_LOG.md`, and record newly approved design decisions in `docs/DECISIONS.md`. Respect the existing prompts log rather than duplicating entries.

## Current quality gate

The repo contains a React frontend, API layer, conversion engine and Windows installer source. **Real Windows runtime and installer testing remains outstanding**, including PowerPoint automation, WebView2, optional component installation, upgrades and uninstall. Report the exact tests actually executed, on which platform, and their result.
