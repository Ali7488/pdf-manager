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
| C4 | 2026-11-22 | Errors are saved to a **logs folder next to the installed app**, and a button opens that folder in File Explorer. |
| C5 | 2026-11-22 | Add a manual **Cancel** button and an **automatic per-page OCR timeout**. The owner left the timeout value to engineering judgment ("5 minutes or whatever is reasonable"). |
| C6 | 2026-11-22 | **Keep bookmarks** when merging. |
| C7 | 2026-11-22 | Add a **contents (index) page** at the start of merged output, linking to each part. It must be possible to turn it off. |
| C8 | 2026-11-22 | Renumber pages using **viewer page labels** (option a), not numbers printed on the pages. |
| C9 | 2026-11-22 | Make the flatten check strict: every page image-backed and page counts matching (fix 6). |
| C10 | 2026-11-22 | Fix the unquoted registry value case in `find_tesseract` (fix 7). |
| C11 | 2026-11-22 | The installer checks for Microsoft PowerPoint first and offers LibreOffice as an optional backup. |
| C12 | 2026-11-22 | Investigate PowerPoint conversion falling back to **LibreOffice** too often. |

## Frontend and packaging

| # | Date | Decision |
| --- | --- | --- |
| F1 | 2026-11-22 | New frontend: **TypeScript + React**. |
| F2 | 2026-11-22 | Delivered as an **installable Windows 11 executable** that opens as a native application window, for average users. Not a browser tab or a local web server. |
| F3 | 2026-11-22 | Tooling: **Vite, React, TypeScript, npm**. |
| F4 | 2026-11-22 | Styling: **CSS Modules** in a **feature-based folder layout**: each page keeps its components, tests and stylesheets in one directory. Top-level folders: `pages/`, shared `components/`, global `styles/`. |
| F5 | 2026-11-22 | Themes: light and dark modes using the owner's usual template colours (black/white with gold accents, from `react-express-template` `client/src/styles/tokens.css`). Extra colourways were suggested (burgundy and pink; forest green, cream and coral; perhaps blue). **Open:** which of these ship. |
| F6 | 2026-11-22 | Font: **IBM Plex Sans**, imported from Google Fonts. No scattered italics or bold. |
| F7 | 2026-11-22 | Look: basic and user-friendly, rounded corners, smooth but uncomplicated animations. |
| F8 | 2026-11-22 | Files: drag and drop to add, drag to reorder, remove. Uploaded files persist across tabs. |
| F9 | 2026-11-22 | Modes: Flatten, Flatten + Merge, Merge, **Split** (select page ranges). Converting PDFs to other file types was suggested ("perhaps"). **Open:** whether to include it and which formats. |
| F10 | 2026-11-22 | A **"Use OCR" checkbox** with a short plain-language explanation. The first time, the Convert button is greyed out while the app checks that OCR is installed. Afterwards, assume it's present. Settings has a **"Search for OCR"** button. Installing OCR stays available in both places. |
| F11 | 2026-11-22 | Settings panel approved: DPI, OCR language, OCR page timeout, contents page on/off, page numbering, optional default save folder, plus the OCR items in F10. |
| F12 | 2026-11-22 | Results approved: save to the default folder or choose one, keep results until saved, list warnings. |
| F13 | 2026-11-22 | Warnings and errors (OCR, conversion, merging and so on) appear in a **simple popup** with basic troubleshooting steps for the likely cause. |
| F14 | 2026-11-22 | Tool check is a **modal shown when Convert is clicked**. It checks OCR, PowerPoint and LibreOffice. If PowerPoint is available, a missing LibreOffice only shows as "not present" and doesn't block conversion. |
| F15 | 2026-11-22 | Navigation: a **sidebar with tabs** (Convert, Settings, possibly one tab per mode). **Open:** home page with upload plus buttons that lead to mode tabs, or upload directly in each tab. |
| F16 | 2026-11-22 | The frontend is built by a parallel agent while the converter work continues. |
