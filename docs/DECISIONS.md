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
| P14 | 2026-11-22 | **Roadmap:** v1 is a Windows product. It will then expand to Linux packages: an Ubuntu `.deb` and an Arch `PKGBUILD`. Later versions target Qt, then GNOME. Code should stay portable so these are possible. |
| P15 | 2026-11-22 | **One codebase for Windows, Ubuntu/Debian and Arch-based Linux:** a shared React/TypeScript frontend and Python conversion engine. Platform-specific functionality sits behind minimal interfaces; shared application logic has no Windows-only assumptions. Windows PowerPoint (COM) stays **optional**; **LibreOffice** is the cross-platform slide renderer. **Linux packaging is not implemented yet**; its constraints and requirements are documented in `docs/PORTABILITY.md`. Running subagents are not interrupted for this. |
| P16 | 2026-11-22 | **Documentation for a post-build review:** keep accurate, proportional docs tied to the actual code: architecture decisions, dependencies, execution flows, non-obvious choices, significant bugs, tests and CI. The owner must be able to understand, debug, modify and defend the app independently. No excessive docs, and never claim generated code was reviewed when it wasn't. |
| P17 | 2026-11-23 | **Linux now (run from source):** refactor the API layer's platform-specific code into `api/platforms/` (Windows and Linux) and make the app run from source on Linux now. Still no Linux packages. |
| P18 | 2026-11-23 | **"Qt, then GNOME" (was O9)** means pywebview **window backends**, not separate native UIs: one React UI everywhere; Qt backend first (fits KDE), then GTK/WebKitGTK (fits GNOME). |
| P19 | 2026-11-23 | **Linux Qt backend uses PySide6** (LGPL, via `pywebview[pyside6]`), not PyQt6 (GPL), so no licence is forced on PDF Manager. |
| P20 | 2026-11-23 | **Licence: MIT.** *Superseded in part by P31:* MIT covers the original source code only; the distributed app is under the AGPL-3.0 because it includes PyMuPDF. |
| P21 | 2026-11-23 | After the Linux work, continue overnight with small open items that need no new decisions (platform-aware troubleshooting text, cleaning up merged agent worktrees and branches). |
| P22 | 2026-11-23 | **Don't run the manual Windows installer build workflow** (`build-windows.yml`); the owner will trigger it. Keep CI minute use low by pushing in small batches rather than after every commit. |
| P23 | 2026-11-23 | **Public repository.** Make `Ali7488/pdf-manager` public now. Commit author emails stay as they are. The reference to the owner's private notes in `ENGINEERING_REVIEW.md` is removed. |
| P24 | 2026-11-23 | **GitHub Actions runners may be used while free** (public repo, standard runners) to build and test, including the Windows installer build, re-running and fixing as needed. Supersedes P22 for the public repo. |
| P25 | 2026-11-23 | **Release plan.** **v0.5**: Windows-only pre-release (installer built on GitHub runners), explicitly marked as a pre-release for testing, with a simple README of the features and install steps (Windows: double-click the installer). **v0.75** (also tonight): pre-release that fixes the Windows bugs found in v0.5 **and releases the Linux versions** (supersedes "no Linux packaging yet" in P15/P17). **v1.0**: full release only after the owner has manually verified the functionality, code and features. |
| P26 | 2026-11-23 | **Linux packaging (v0.75):** a bundled PyInstaller build made on GitHub's Ubuntu runner, installed to `/opt/pdf-manager`, wrapped as an Ubuntu/Debian `.deb` and an Arch `PKGBUILD` that installs the same bundle. Tesseract and LibreOffice stay separate system packages. |
| P27 | 2026-11-23 | **Arch:** a `PKGBUILD` attached to the release (and kept in the repo) that downloads the Linux bundle; installed with `makepkg -si`. Not published to the AUR. |
| P28 | 2026-11-23 | **If the Windows installer can't be made to build or start tonight:** publish v0.5 anyway with what works, stating clearly in the notes what doesn't work and what's planned for v0.75. |
| P29 | 2026-11-23 | **Version tags:** `v0.5.0` and `v0.75.0`, titled "v0.5 – pre-release for testing" and "v0.75 – pre-release for testing". |

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
| C14 | 2026-11-23 | **Untrusted presentations (audit R1):** never strip Windows Mark-of-the-Web. Presentations that came from the internet or email are rendered with **LibreOffice** (headless, macros not run), not PowerPoint automation, with a warning explaining why the slides may look slightly different. Trusted local files still use PowerPoint. |
| C15 | 2026-11-23 | **Linux logs (was O10):** `~/.local/state/pdf-manager/logs` (XDG state folder) for an installed app; when run from source during development, logs stay in the repo's `logs/` folder. Windows keeps logs next to the app (C4). |
| C16 | 2026-11-23 | **Linux "Install OCR":** show a simple popup with the exact command for the user's distribution (Ubuntu/Debian: `sudo apt install tesseract-ocr tesseract-ocr-eng`; Arch: `sudo pacman -S tesseract tesseract-data-eng`) with a Copy button, then "Search for OCR". The app never runs `sudo` itself. |
| P30 | 2026-11-23 | **Licences shipped with the app:** a copyright line at the bottom of the side pane (now "© 2026 Mohannad Ali / Free software (GNU AGPL-3.0)", per P31) and an About section in Settings; `THIRD_PARTY_NOTICES.md` and a `licenses/` folder (generated from the bundled packages by `scripts/collect_licenses.py`) installed next to the app. Because PyMuPDF is AGPL-3.0, the distributed app is under the AGPL-3.0's terms and the app points to its public source code. The owner will look into the licensing further. |
| P31 | 2026-11-23 | **AGPL-3.0 route for PyMuPDF.** The project is free, public and open source (personal use, sharing, portfolio; no paid or proprietary version). Keep PyMuPDF; don't migrate to other PDF libraries to avoid the AGPL. The distributed app is conveyed under the AGPL-3.0 with complete corresponding source, build instructions, copyright attribution, third-party notices and licence files in the installer. The original code stays MIT where compatible; the combined app is never described as MIT-only. PySide6 stays Linux-only (P19); no Qt in the Windows installer. Releases are not published without the owner's approval. |

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
| F36 | 2026-11-22 | **`converter/` is split into subfolders by responsibility** (shared core types, actions, OCR, slides, tools, PDF helpers, files, platforms) instead of one flat folder. |
| F37 | 2026-11-23 | **Automatic CI (audit R7):** on every push and pull request, run Python lint and the full tests on Linux (with Tesseract and LibreOffice installed) and on Windows, plus the frontend typecheck, lint, tests and build. Windows packaging stays a separate manual job. |
| F38 | 2026-11-23 | **Settings (was O11):** neither a contents-page default nor a page-numbering switch. The contents page stays a per-tab checkbox (off by default); page numbering stays automatic (viewer labels). |
| F39 | 2026-11-23 | **OCR language (was O12):** one language at a time, chosen in Settings (English by default). |
| F40 | 2026-11-23 | **Classic desktop look**, after 2016-era Microsoft Office software but with our own colour schemes: a band-coloured side pane with the app name (like Office's File menu), one plain page, sections marked by a heading and thin rule (no boxes), flat compact controls, almost square corners, no shadows, minimal animation. Supersedes the rounded, modern look in F7. |
| F41 | 2026-11-23 | **Few colours per scheme:** each theme defines only base colours (band, accent, paper, canvas, ink, line, alert, and text on band/accent); every other shade is derived from them. |
| F42 | 2026-11-23 | **Font:** Segoe UI (what Office used) where Windows already provides it, since it's proprietary and can't be bundled; otherwise bundled **Open Sans** (OFL), the closest freely licensed match (same designer). All text weights one step heavier (500 body, 600 emphasis). Supersedes IBM Plex Sans in F6. |
| F43 | 2026-11-23 | **Three tones per scheme, high contrast, complementary** (refines F41): base, text, accent. Dark: near-black and gold (warm white text). Light: white and gold (near-black text). Burgundy: burgundy and bright pink (white text). Green: forest green and coral (cream text). The accent is the side pane, main buttons and lines; hovers are tints of the same tones. **Buttons have soft rounded corners (6px); borders are 2px.** |
| F44 | 2026-11-23 | **Muted colours, clearly distinct neighbours** (supersedes F43's colours; soft rounded buttons and 2px borders stay). Each scheme has a **background, a foreground (side pane, panels, tiles, controls), a text colour and at most one accent** (main buttons, current item, links, focus). Dark: charcoal with gold; light: warm off-white and beige with gold; burgundy: muted burgundy with pink; green: muted forest with coral. |
| F45 | 2026-11-23 | **No eyebrow text.** No decorative subtitles or hint lines under headings, tiles or options. At most one quick instruction where it helps (Home: "Drop files here, or click Add files" / "Then choose a tool"; action pages: "Add files, choose options, then click Convert."). Each action page opens with one plain sentence (normal text, not a subtitle) on what it does and how to use it; options carry a short explanation beside them (e.g. "Use OCR: makes the text in your pages searchable and copyable"), with (?) tooltips for more detail. Status messages (such as "Not saved" or "Not used in this mode") stay. |
| F46 | 2026-11-23 | **Compact window, bigger content:** default window 1040×720 (minimum 860×600); content left-aligned beside the side pane with tighter spacing (less dead space); text and controls one step larger (body about 15px, controls 36px). |
| F47 | 2026-11-23 | **Use the horizontal space:** on wide windows, action pages show files on the left and Options/Saving on the right, and Home shows the drop area and files on the left and the tool list on the right; narrow windows fall back to one column. |

## Open questions

Add new ones here as they come up, and never assume their answers. Details and evidence for O1–O3: `docs/LICENSING_AUDIT_2026-11-23.md`.

| # | Raised | Question |
| --- | --- | --- |
| O1 | 2026-11-23 | **Microsoft binaries in the AGPL-3.0 Windows app.** The WebView2 SDK files (BSD-3-Clause-style licence, no published source) and the Visual C++ runtime (Visual Studio "Distributable Code") ship inside the app. Is that acceptable for an AGPL-3.0 distribution of PyMuPDF? Options: ask Artifex for written confirmation; get legal advice; or change the packaging (for example rely on the system Visual C++ Redistributable). Not decided; needs the owner. |
| O2 | 2026-11-23 | **Visual C++ runtime redistribution rights.** Microsoft limits redistribution of those files to licensed Visual Studio users. Does the owner hold (or want) a Visual Studio Community licence, or should the installer use Microsoft's redistributable instead of bundling the DLLs? |
| O3 | 2026-11-23 | **App icon provenance.** `PDF Manager.ico` and `assets/icon-preview.png` came with the imported baseline; the repository has no record of who made them. The owner must confirm the right to distribute them, or they should be replaced. |
