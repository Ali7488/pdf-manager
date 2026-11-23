# Decisions log

Decisions made by the project owner, in their own direction (summarized, not quoted). Items marked **Open** are not yet decided and must not be assumed. Newest entries are at the bottom of each section.

## Project and process

| # | Date | Decision |
| --- | --- | --- |
| P1 | 2026-11-22 | Purpose: flatten PDFs and PowerPoints that cause compatibility problems in tablet note-taking apps, OCR them back into searchable PDFs, and merge files. |
| P2 | 2026-11-22 | Target platform: Windows (Windows 11). |
| P3 | 2026-11-22 | The tool is generic: no personal names and no use-case-specific wording anywhere. |
| P4 | 2026-11-22 | App name: **PDF Manager**. GitHub repo: `Ali7488/pdf-manager`, private. The local folder keeps its old name. |
| P5 | 2026-11-22 | The old git history was replaced with fresh, individual commits. |
| P6 | 2026-11-22 | Commit as you go: small, meaningful commits under the owner's git identity. |
| P7 | 2026-11-22 | Speaker notes are removed entirely and are not needed. |
| P8 | 2026-11-22 | The project uses **uv**. |
| P9 | 2026-11-22 | Every function has docstrings and comments describing its intended behaviour. |
| P10 | 2026-11-22 | Keep `AGENTS.md`, `CLAUDE.md`, a summarized prompts log, and this decisions log. |
| P11 | 2026-11-22 | The AI acts as a senior full-stack engineer on a Windows 11 PDF management app that prioritizes ease of use and a simple UI for everyday tasks, with low overhead. |
| P12 | 2026-11-22 | Restate the plan and list clarifications before starting work; never assume anything that wasn't stated clearly. |

## Converter (Python backend)

| # | Date | Decision |
| --- | --- | --- |
| C1 | 2026-11-22 | The Python converter stays as the backend behind the new frontend. |
| C2 | 2026-11-22 | PowerPoint must not close the user's own PowerPoint or presentations (fix 1). |
| C3 | 2026-11-22 | A fatal PowerPoint error is shown in a popup. Non-fatal problems are returned as structured warnings. |
| C4 | 2026-11-22 | Errors are saved to a **logs folder next to the installed app**, and a button opens that folder in File Explorer. (Works because the app installs per user, see F17.) |
| C5 | 2026-11-22 | Add a manual **Cancel** button and an **automatic per-page OCR timeout**. Default **2 minutes per page**, adjustable in Settings. |
| C6 | 2026-11-22 | **Keep bookmarks** when merging. |
| C7 | 2026-11-22 | Add a **contents (index) page** at the start of merged output, linking to each part. It must be possible to turn it off. |
| C8 | 2026-11-22 | Renumber pages using **viewer page labels** (option a), not numbers printed on the pages. |
| C9 | 2026-11-22 | Make the flatten check strict: every page image-backed and page counts matching (fix 6). |
| C10 | 2026-11-22 | Fix the unquoted registry value case in `find_tesseract` (fix 7). |
| C11 | 2026-11-22 | The installer checks for Microsoft PowerPoint first and offers LibreOffice as an optional backup. |
| C12 | 2026-11-22 | Investigate PowerPoint conversion falling back to **LibreOffice** too often. |
| P13 | 2026-11-22 | Push small commits as you go, and use as many parallel subagents as needed. |
| C13 | 2026-11-22 | **Logging levels:** verbose logs in **development mode** (running from source, for the owner's testing). **Production** (the installed app) logs more concisely, but still keeps verbose records for errors. |

## Frontend and packaging

| # | Date | Decision |
| --- | --- | --- |
| F1 | 2026-11-22 | New frontend: **TypeScript + React**. |
| F2 | 2026-11-22 | Delivered as an **installable Windows 11 executable** that opens as a native application window, for average users. Not a browser tab or a local web server. |
| F3 | 2026-11-22 | Tooling: **Vite, React, TypeScript, npm**. |
| F4 | 2026-11-22 | Styling: **CSS Modules** in a **feature-based folder layout**: each page keeps its components, tests and stylesheets in one directory. Top-level folders: `pages/`, shared `components/`, global `styles/`. |
| F5 | 2026-11-22 | Themes: light and dark modes using the owner's usual template colours (black/white with gold accents, from `react-express-template` `client/src/styles/tokens.css`). v1 ships **four schemes: dark, light, burgundy (burgundy and pink) and green (forest green, cream and coral)**. More, such as blue, only after Windows behaviour is proven. |
| F6 | 2026-11-22 | Font: **IBM Plex Sans**, **bundled with the app** (not fetched from Google Fonts at runtime) so it works offline. No scattered italics or bold. |
| F7 | 2026-11-22 | Look: basic and user-friendly, rounded corners, smooth but uncomplicated animations. |
| F8 | 2026-11-22 | Files: drag and drop to add, drag to reorder, remove. Uploaded files persist across tabs. |
| F9 | 2026-11-22 | Modes: Flatten, Flatten + Merge, Merge, **Split** (select page ranges). v1 also adds **Images to PDF** (PNG/JPG) and **Compress PDF**. Word export is **after v1**, as an optional separate add-on install because of its extra dependency. |
| F10 | 2026-11-22 | A **"Use OCR" checkbox** with a short plain-language explanation. **Unchecked by default.** Offered in Flatten, Flatten + Merge, Merge and Split (merged or split PDFs may be image-based). OCR availability is checked by the Convert modal (F14); there is **no separate first-time check** when the box is ticked (dropped, see F33). Settings has a **"Search for OCR"** button. Installing OCR stays available in both places. |
| F11 | 2026-11-22 | Settings panel approved: DPI, OCR language, OCR page timeout, contents page on/off, page numbering, optional default save folder, plus the OCR items in F10. |
| F12 | 2026-11-22 | Results approved: save to the default folder or choose one, keep results until saved, list warnings. |
| F13 | 2026-11-22 | Warnings and errors (OCR, conversion, merging and so on) appear in a **simple popup** with basic troubleshooting steps for the likely cause. |
| F14 | 2026-11-22 | Tool check is a **modal shown when Convert is clicked**. It appears on **every Convert** and checks **only what that job needs** (no OCR check when OCR is unchecked; PowerPoint/LibreOffice only matter for PowerPoint inputs). If PowerPoint is available, a missing LibreOffice only shows as "not present" and doesn't block conversion. If a required check fails, it shows an error with likely troubleshooting steps. |
| F15 | 2026-11-22 | Navigation: a **sidebar** where **each mode is its own tab**, plus Settings. Option C: a **Home** page with the drop zone and file list and buttons leading to each mode tab, and every mode tab also accepts dropped files. The file list is shared across all tabs. |
| F16 | 2026-11-22 | The frontend is built by a parallel agent while the converter work continues. |
| F17 | 2026-11-22 | **Per-user install** (no admin rights needed). An **unsigned** installer is acceptable for v1. |
| F18 | 2026-11-22 | Shell confirmed: a **pywebview** window talking to Python directly (no local server), packaged with **PyInstaller** and an **Inno Setup** installer. |
| F19 | 2026-11-22 | The installer is a **simple install wizard**. |
| F20 | 2026-11-22 | **Tooltips:** anything that may need explaining gets a small circular **(?)** next to it that shows a simple explanation on hover. |
| F21 | 2026-11-22 | **Split** output: each page range becomes its **own file**. The user can save them as **one zip (optional)** or as individual files. |
| F22 | 2026-11-22 | **Default save folder:** set in Settings. When enabled, results save there **without asking**. Each mode page has an option to save to the default folder or not, plus a **"Change default folder"** button that goes to Settings. |
| F23 | 2026-11-22 | Drag to reorder uses **`@dnd-kit/sortable`**: smooth, intuitive animations are worth the ~15 KB. |
| F24 | 2026-11-22 | Frontend tests: **Vitest + React Testing Library**, kept in each feature folder. |
| F25 | 2026-11-22 | **Delete the Tkinter app** once the new app works. |
| F26 | 2026-11-22 | **Contents page** is available for **Merge and Flatten + Merge**, **off by default**. |
| F27 | 2026-11-22 | **First-launch theme follows Windows** light/dark. Burgundy and green are chosen manually in Settings. |
| F28 | 2026-11-22 | **Split** offers custom page ranges, **every N pages** and **one file per page**, and **accepts PowerPoint files** (rendered to PDF first). |
| F29 | 2026-11-22 | **Images to PDF:** the user chooses between one combined PDF and one PDF per image. **"Use OCR" is offered** here too. |
| F30 | 2026-11-22 | **Compress PDF** offers **levels: Light / Balanced / Strong**, each with a (?) tooltip. |
| F31 | 2026-11-22 | The **install wizard offers both** optional components: Tesseract OCR (unchecked) and LibreOffice (checked only if PowerPoint isn't found). |
| F32 | 2026-11-22 | Once a default folder is set, each mode page's **"Save to default folder" starts ticked**. |
| F33 | 2026-11-22 | **No separate first-time OCR check**; the Convert modal's check is enough. |
| F34 | 2026-11-22 | **Function-based API:** every conversion action (Flatten, Merge, Split and so on) goes through **one function** that takes an **action enum**, a **settings object** and the **data** (the files): `startJob(action, settings, data)` in the UI, `run_action(action, settings, data)` in Python. |
| F35 | 2026-11-22 | **Three separate layers:** the **frontend** (`frontend/`, React UI), the **API layer** (`api/`, the Python pywebview bridge: calls, events, job state, settings, saving) and the **service layer** (`converter/`, pure conversion logic with no UI or bridge code). |

## Open questions

None right now. Add new ones here as they come up, and never assume their answers.
