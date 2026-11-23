# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## Role

Act as a **senior full-stack engineer** working on a PDF management application for **Windows 11**. The application prioritizes **ease of use** and a **simple UI** for everyday tasks, and must keep **low overhead** (small dependencies, low memory and disk use, fast startup).

Owner decisions are recorded in [`docs/DECISIONS.md`](docs/DECISIONS.md). Follow them, and never assume an answer to an item marked **Open**; ask instead.

## Project

**PDF Manager** is a Windows desktop tool that converts PowerPoint files (PPT/PPTX) and PDFs into **flattened, searchable PDFs**, and merges files.

- **Flatten**: render every page to an image so the PDF opens cleanly in apps that struggle with complex PDFs (for example tablet note-taking apps), then add an invisible Tesseract OCR text layer so it stays searchable.
- **Merge**: combine files in a user-chosen order, keeping the original text.
- **Flatten + Merge**: both.

The Python `converter/` package is the engine. The Tkinter `app.py` is the current UI and will be replaced by a TypeScript + React frontend, with the Python converter kept as the backend.

## Layout

- `converter/`: conversion engine. See the package docstring in `converter/__init__.py` for the job flow and module map.
- `app.py`: Tkinter dashboard (to be replaced).
- `tests/`: integration tests (need Tesseract and LibreOffice installed).
- `install_windows.ps1`, `INSTALL.bat`, `OPEN.bat`: Windows installer and launcher.
- `docs/`: engineering backlog, source inventory and the prompts log.

## Commands

```bash
uv sync                         # set up .venv (Python is pinned in .python-version)
uv run tests/smoke_test.py      # end-to-end: flatten, merge, OCR, naming, source preservation
uv run tests/test_temp_lock.py  # Windows file-lock regression
uv run app.py                   # run the current GUI
uvx ruff format --line-length 100 .
uvx ruff check --line-length 100 .
```

Use **uv** for everything (`uv add`, `uv run`, `uv sync`). Never use pip or requirements files.

## Rules

- **Generic only.** No personal names, no specific person's workflow, and no domain-specific wording (such as a particular course or subject) in code, UI text, tests, docs or commit messages. Test fixtures use neutral sample text.
- **Windows first, portable always.** v1 targets Windows 11; prefer correct Windows behaviour. Linux packages (`.deb`, Arch `PKGBUILD`) and Qt/GNOME versions come later (decision P14), so keep the service and API layers portable: guard Windows-only code (COM, registry, `os.startfile`) with platform checks and working fallbacks, and never hard-code Windows paths.
- **Originals are never modified.** Inputs are only read. All work happens in a scratch folder, and results are copied out with collision-safe names (`converter.output.safe_destination`).
- **No speaker notes.** The speaker-notes appendix was removed on purpose. Don't re-add it.
- **Documentation.** Every function gets a Google-style docstring (summary, Args, Returns, Raises). Add inline comments for non-obvious lines, and flag known issues where they occur.
- **Commits.** Make small, meaningful commits as you go, one per logical change, under the user's configured git identity. Run the tests before committing code changes, then push to `origin`.
- **Decisions log.** Record every decision the owner makes in `docs/DECISIONS.md` as soon as it is made.
- **Prompts log.** Add a short, summarized entry (not a verbatim quote) to `docs/PROMPTS_LOG.md` for each user request, and tick off its checklist as work completes.
