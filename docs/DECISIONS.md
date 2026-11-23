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
| P32 | 2026-11-23 | **Visual C++ runtime: a separately installed prerequisite, not bundled** (owner request; branch `fix/windows-vc-runtime`, pending review). The Windows app ships none of Microsoft's Visual C++ runtime DLLs. It uses the system-wide Microsoft Visual C++ Redistributable (x64), version 14.44 or newer (the newest MSVC toolset among the bundled binaries). The installer checks the DLLs' file versions in System32. When they're missing it explains why, says installing them needs administrator permission, and offers Microsoft's download page. It continues either way and hides **Launch** until the runtime is there. It never downloads, bundles or runs `vc_redist.x64.exe` itself. The build excludes the DLLs, and `scripts/check_licenses.py` fails if one comes back or if the installer stops covering what the binaries import. This is Microsoft's recommended central deployment. Distributing no Microsoft runtime file avoids Visual Studio's redistribution limits. It also matches the GNU FAQ's condition for treating the runtime as a System Library (not distributed with the program). WebView2 and PyMuPDF are unchanged. |
| P33 | 2026-11-23 | **Browser mode, next to the desktop window** (owner request; branch `migration/local-browser-mode`, pending review; docs/BROWSER_MODE.md). The same interface and workflow run in the user's own default browser, served by a loopback-only HTTP API on `127.0.0.1`. **App mode** (its own window, no tabs) is used when the default browser is Edge, Chrome, Brave or Chromium. **Any other default (Firefox included) gets a normal localhost tab**, documented as such. No browser is installed, forced or substituted. Boundary: an explicit operation list; opaque file, folder and download IDs instead of host paths; a single-use launch link and session cookie; exact Host/Origin; polling instead of an event stream; no heartbeats or browser-process tracking. **Files and saving:** drag and drop and the browser's file chooser upload working copies, which are marked as downloaded, so presentations dropped in use LibreOffice (C14 unchanged). Native pickers are used where available, with browser downloads as the save fallback. The desktop window, PyMuPDF and the AGPL route (P31) stay. Ships as a portable Windows ZIP with its own licence inventory; the browser itself is never shipped. |
