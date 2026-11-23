# Prompts log

A short, summarized record of each request made to the coding agent, and what came of it. These are summaries, not verbatim quotes. Newest entries are at the bottom.

## 2026-11-22

1. **Review and explain the code.** Explain every function and run a code review. → Walkthrough of the converter and UI, plus a ranked list of bugs. No code changed.
2. **Project purpose.** The tool flattens PDFs that cause compatibility problems in tablet note-taking apps, OCRs them back into searchable PDFs, and merges files. Windows is the target.
3. **Make it generic.** Remove every personal name and use-case-specific wording; it should be a general PDF tool. → Done across code, tests and docs.
4. **Rename and clean history.** Rename the app, replace the old git history with fresh, individual commits, keep the local folder name, and create the GitHub repo (private). → Done; old objects purged.
5. **Split the converter by functionality** and list the dependencies with reasons. → `converter/` package plus a dependency table in the README.
6. **Commit as you go** under the user's git identity, in small meaningful commits.
7. **Remove speaker notes** entirely. → Feature, module and runtime dependencies removed.
8. **Name the app "PDF Manager".** → Renamed everywhere.
9. **Use uv** for the project. → `pyproject.toml`, `uv.lock` and `.python-version`; the installer uses `uv sync`.
10. **Rename the GitHub repo** to match (`pdf-manager`), explain the open problems in detail, and plan a TypeScript + React frontend (drag and drop, editable settings, optional default save folder) with the Python converter as the backend.
11. **Add docstrings and comments** so the intended behaviour can be read from the code. → Every function documented; known issues flagged inline.
12. **Converter fixes and project docs** (this batch). Restate the plan and log it before starting, then discuss frontend v1, which will be built by a parallel agent while the converter work continues. Checklist:
    - [x] Add `AGENTS.md`, `CLAUDE.md` and this prompts log.
    - [x] *(service done; not yet run on Windows)* **PowerPoint quitting:** only close PowerPoint if the converter started it, so the user's open PowerPoint and presentations are never closed.
    - [x] *(service done: warning or error issue with the real PowerPoint error; the popup is the frontend's job)* **PowerPoint errors:** keep the real PowerPoint error. If conversion fails completely, show it in a popup; if LibreOffice rescued it, return it as a structured warning instead.
    - [x] *(API layer: rotating logs next to the app, `openLogsFolder`; button in Settings and issue popups; not yet run on Windows)* **Error logs:** write errors and warnings to a logs folder next to the installed app, and add a button that opens that folder in File Explorer.
    - [x] *(service done: cancel stops between pages and kills Tesseract/LibreOffice/PowerPoint we started; the button is the frontend's job)* **Cancel:** a manual Cancel button that stops a running job, including killing Tesseract or LibreOffice mid-run.
    - [x] *(done: 2 minutes per OCR page by default, 5 minutes per PowerPoint/LibreOffice export)* **Automatic timeouts:** give up on a page that takes too long to OCR (default to be chosen, likely about 2 minutes, configurable), and on a PowerPoint export that hangs.
    - [x] **Keep bookmarks** when merging (and when flattening), with one top-level bookmark per input file.
    - [x] **Contents page (can be turned off; default to be confirmed):** for merged output, add an index page at the start listing every input file with its page range and clickable links.
    - [x] **Page numbering** for merged output, using viewer page labels.
    - [x] **Stricter flatten check:** every page must be image-backed and the page count must match the input.
    - [x] **Registry path fix:** handle unquoted `tesseract.exe,0` values in `find_tesseract`.
    - [x] *(new install wizard in `packaging/`; never compiled or run on Windows yet)* **Installer:** detect Microsoft PowerPoint first; offer LibreOffice as an optional backup instead of always installing it.
    - [x] *(two likely causes addressed, neither confirmed on Windows: the Mark-of-the-Web / Protected View problem, fixed by rendering a plain copy; and the printer dialog, now timed out with troubleshooting text)* **Investigate PowerPoint falling back to LibreOffice too often:** check whether the success check is too strict, and look at the documented "Waiting for printer connection" popup during PowerPoint's PDF export.
13. **Answers and frontend v1 direction.** Logs go next to the installed app; page numbering uses viewer labels; the fallback issue is about LibreOffice. Defined the frontend: a desktop window app for Windows 11, Vite + React + TypeScript + npm, CSS Modules in feature folders, themes, IBM Plex Sans, drag-and-drop files, new Split mode (and possibly format conversion), a "Use OCR" checkbox, troubleshooting popups, a tool-check modal on Convert, and sidebar navigation. Asked for a running decisions log, a role statement in `AGENTS.md`, and a full plan plus clarifications before any work starts. Checklist:
    - [x] Create `docs/DECISIONS.md` with every owner decision so far.
    - [x] Add the senior full-stack engineer role statement to `AGENTS.md`.
    - [x] Present the full plan and open questions; wait for confirmation before starting.
14. **Answers to the frontend questions.** Per-user, unsigned installer with a simple install wizard. pywebview shell confirmed. Split saves each range as its own file, optionally zipped. v1 adds Images to PDF and Compress PDF; Word export comes later as an optional add-on. "Use OCR" is unchecked by default and also offered for Merge and Split. The tool-check modal runs on every Convert and checks only what the job needs. Navigation option C with one sidebar tab per mode. Bundle IBM Plex Sans, use dnd-kit, Vitest + React Testing Library, four colour schemes, a (?) tooltip next to anything that needs explaining, save to the default folder without asking when enabled, and delete Tkinter once the new app works. Checklist:
    - [x] Record all answers in `docs/DECISIONS.md` and list the remaining open questions.
    - [x] Get answers to the open questions (O1 to O8); recorded as F26 to F33.
    - [x] Final confirmation of the plan before starting work.
15. **Start as planned.** Write the API contract first, then build the frontend with a parallel agent in its own worktree while the converter work continues. Checklist:
    - [x] API contract (`docs/API.md` and `frontend/src/api/types.ts`).
    - [x] Launch the frontend agent.
    - [x] Converter fixes and new modes (checklist in item 12 plus Split, Images to PDF and Compress).
    - [ ] pywebview shell connecting the UI to the converter.
    - [x] *(written; untested on Windows)* Packaging: PyInstaller and the Inno Setup install wizard.
    - [ ] Delete the Tkinter app once the new app works.
16. **Function-based API.** Conversion actions share one function that takes an action enum, a settings object and the data, instead of a single bundled request object. Checklist:
    - [x] Update `frontend/src/api/types.ts` and `docs/API.md` (`startJob(action, settings, data)`, `Action` enum, `ActionSettings`, `ActionData`).
    - [x] Record the decision (F34).
    - [x] Pass the change to the frontend agent.
    - [x] Python side: `converter.run_action(action, settings, data)` with an `Action` enum.
17. **Layers and more parallel agents.** Push small commits as you go, use as many subagents as needed, and separate the frontend, API and service layers. Checklist:
    - [x] Record decisions P13 and F35.
    - [x] Define the service-layer interface (`run_action`, types, issues, cancellation).
    - [ ] Hand the API layer, the new actions and packaging to parallel agents; merge their branches.
18. **Verbose logging in development.** Error logging should be verbose in development mode; production can be more concise but still keep some verbose logs. Checklist:
    - [x] Record decision C13.
    - [x] Service layer logs verbosely at DEBUG level (commands, timings, tool output, tracebacks).
    - [ ] API layer: DEBUG level in development mode, INFO in production, with errors always logged in full.
19. **Roadmap.** Windows first, then an Ubuntu `.deb` and an Arch `PKGBUILD`, then Qt, then GNOME. Checklist:
    - [x] Record decision P14 and open questions O9 (meaning of "Qt then GNOME") and O10 (Linux log location).
    - [x] Add a "portable always" rule to `AGENTS.md`.
20. **Cross-platform architecture.** Support Windows, Ubuntu/Debian and Arch from one frontend and one Python engine; isolate platform-specific code behind minimal interfaces; keep PowerPoint COM optional with LibreOffice as the cross-platform renderer; no Linux packaging yet; no Windows-only assumptions in shared logic; document portability constraints and future Linux release requirements without interrupting the running subagents. Checklist:
    - [x] Record decision P15.
    - [x] Write `docs/PORTABILITY.md`.
    - [x] Service layer: move platform-specific code into `converter/platforms/` (Windows and POSIX modules behind one small interface), enforced by `tests/test_portability.py`.
    - [ ] API layer: after merging its branch, move Windows-specific parts (opening folders, OCR install, settings paths) behind the same kind of interface.
21. **Documentation for a post-build review.** Keep accurate, proportional documentation of architecture decisions, dependencies, execution flows, non-obvious choices, significant bugs, tests and CI, so the owner can understand, debug, modify and defend the app; never claim unreviewed code was reviewed. Checklist:
    - [x] Record decision P16 and add the rule to `AGENTS.md`.
    - [x] Write `docs/ARCHITECTURE.md` once `run_action` is implemented. (API layer and frontend sections pending their merge.)
    - [x] Update `docs/ENGINEERING_REVIEW.md` with the bugs found and their status, plus a review-status section.
22. **Split the converter into folders by responsibility.** Checklist:
    - [x] Record decision F36.
    - [x] Restructure `converter/` into subpackages (the API-layer branch's imports still need updating when it's merged).
23. **Frontend agent's contract proposals** (engineering follow-up, no new owner request). Adopted: `pickFiles("all")`, `getOcrStatus()`, a `converting_images` stage, and `discardResults` being safe to call twice. Logged as open questions for the owner: O11 (contents page / page numbering in Settings) and O12 (several OCR languages).

## 2026-11-23

24. **Add CI, and fix the post-merge audit findings** (R1–R10 in `docs/ENGINEERING_REVIEW.md`, from the owner's read-only source audit). Checklist:
    - [x] *(fixed in code; Windows acceptance pending)* R1: stop stripping Mark-of-the-Web; apply an owner-chosen policy for untrusted presentations.
    - [x] *(fixed in code; Windows acceptance pending)* R2: only kill a PowerPoint process proven to belong to this conversion.
    - [x] R3: isolate PowerPoint and LibreOffice outputs so a leftover file can't be mistaken for a result.
    - [x] R4: coordinate save, discard and shutdown in the job manager.
    - [x] R5: settings updates can't be overwritten by an older response.
    - [x] R6: a failed settings save is reported to the UI.
    - [x] R7: automatic CI for Python and frontend on push and pull requests, separate from the manual Windows packaging job.
    - [x] R8: remove the transitional import fallback in `api/service.py`.
    - [x] R9: update `ARCHITECTURE.md`, `SOURCE_INVENTORY.md` and `PORTABILITY.md` against the merged code, with real test counts.
    - [ ] R10: needs a real Windows 11 machine; can't be closed from Linux.
25. **Linux bridge: why or why not, then the pending decisions.** Explained that Linux is feasible (shared converter and UI, pywebview GTK/Qt backends, mostly Linux-aware API layer) and what's missing (a window backend, an API platform module, Linux log and OCR-install behaviour, unverified drag and drop and dialogs). Owner answered: "Qt then GNOME" means window backends, Qt first (P18); Linux logs in `~/.local/state` (C15); no contents/numbering in Settings (F38); one OCR language (F39); Linux "Install OCR" shows the command with a Copy button (C16); refactor and Linux run-from-source now (P17). Checklist:
    - [x] Record the decisions; no open questions remain.
    - [ ] Move the API layer's platform-specific code into `api/platforms/` (Windows, Linux).
    - [ ] Run from source on Linux with the Qt backend (optional dependency, logs, OCR-install command popup).
    - [ ] CI job that starts the app on Linux in a virtual display.

