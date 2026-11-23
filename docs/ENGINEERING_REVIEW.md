# Engineering review: bugs, status and what has been verified

Significant bugs found since the v1.1.1 baseline was imported, their status, and the open work. "Fixed" means fixed in code and covered by automated tests **on Linux**; anything that depends on Windows is marked as unverified until it has run there.

## Review status (read this first)

Current as of **2026-11-23**:

- **Human review:** none of the generated code has had a complete line-by-line human review. A targeted read-only source risk audit (R1–R10, below) and an AI-agent licensing audit (`docs/LICENSING_AUDIT_2026-11-23.md`) have been done. Neither is a release sign-off.
- **Automated checks (CI):** `.github/workflows/ci.yml` runs on every push: Python on Linux (with Tesseract and LibreOffice) and on Windows, the frontend checks, and a Linux start-up check. The licence inventory check (`tests/test_licensing.py`) is part of the Python suite. Latest local run: Python 483 passed, 5 skipped; frontend 95 passed.
- **Windows build (CI, manual trigger):** `build-windows.yml` builds the installer, checks the bundle against the licence notices, installs it silently, checks the installed licence files, and starts the installed app in smoke-test mode. Last green run: [45202300026](https://github.com/Ali7488/pdf-manager/actions/runs/45202300026) (commit `fcd8531`). That's a GitHub virtual machine, **not a real Windows 11 PC**.
- **Not verified on a real Windows 11 machine (R10):** PowerPoint automation (COM), native dialogs, drag and drop, the wizard's optional installs, upgrade and uninstall.
- **Licensing:** the strategy (P31) is coherent. Open questions O1–O3 in `docs/DECISIONS.md` need the owner. Branch `fix/windows-vc-runtime` (P32, pending review) stops bundling the Visual C++ runtime. The installer checks for Microsoft's separately installed redistributable instead. The missing-runtime path has only been simulated on the runner; it still needs a test on a clean Windows PC.

Historical counts from earlier snapshots (163 and 317 tests, the pre-CI state) are kept in the fix log below for the record only.

## Bugs and their status

| # | Bug (where it was) | Status |
| --- | --- | --- |
| 1 | Converting a presentation could **close the user's own open PowerPoint** (`app.Quit()` on the shared instance). | Fixed: quits or kills PowerPoint only if the converter started it (`platforms/windows_powerpoint.py`). Logic tested with fakes; **unverified on Windows**. |
| 2 | **PowerPoint errors were swallowed**; users saw a misleading "requires PowerPoint or LibreOffice" message. | Fixed: a fallback produces a `POWERPOINT_FALLBACK` warning carrying the real error; if both renderers fail, the issue includes both errors. |
| 3 | PowerPoint **fell back to LibreOffice too often**. | Two likely causes, **neither confirmed on Windows**: (a) downloaded files carry the Mark-of-the-Web and open in Protected View, which hidden automation can't use; the provenance is **kept** and such files are rendered by LibreOffice on purpose (decision C14, audit R1); (b) the documented "Waiting for printer connection" dialog, which now times out after 5 minutes with troubleshooting steps. Confirm with real files on Windows. |
| 4 | **No cancel, and jobs could hang** (no PowerPoint timeout; 5 min per OCR page). | Fixed in the service layer: cancel token checked between pages and files; running programs are killed (whole process tree); timeouts for OCR pages (2 min default, a setting), PowerPoint and LibreOffice (5 min). The Cancel button is the frontend's job. |
| 5 | **DPI setting never reached flattening**; OCR language fixed to English. | Fixed: settings flow through `ActionSettings` into every step. |
| 6 | **Merging dropped bookmarks.** | Fixed: nested per-file bookmarks; optional contents page; page labels. |
| 7 | **Weak flatten check** (passed if any one page had an image). | Fixed: page count must match and every page must be image-backed. |
| 8 | **Registry path parsing** broke on unquoted `tesseract.exe,0`. | Fixed and unit-tested (`exe_from_registry_value`); the registry reading itself is unverified on Windows. |
| 9 | **Installer always installed LibreOffice**, even with Office present. | Replaced by the new install wizard (`packaging/installer.iss`), which detects PowerPoint and offers LibreOffice as an optional backup. **Never compiled or run.** |
| 10 | **Cancelling the save dialog discarded all results.** | Addressed in the merged API implementation: a cancelled folder picker keeps scratch results available for later saving. Tests exist; Windows GUI behavior remains unverified. |
| 11 | Tkinter UI: event polling could stop permanently after an error; no visible keyboard focus. | Legacy UI retired from the repository (owner retains local backup). The React replacement uses native buttons and focus styling; end-user accessibility and keyboard flow still need acceptance testing. |
| 12 | Speaker-notes appendix: non-Latin text rendered as missing glyphs, soft line breaks lost, unrelated template notes included. | Removed with the feature (P7). |
| 13 | WinError 32 when deleting temporary OCR files on Windows (baseline bug). | Fixed in the baseline; kept by design and by the simulated regression test. Real Windows antivirus/Explorer behaviour is unverified. |

Found during implementation:

- `pymupdf.image_profile` raises a `TypeError` in PyMuPDF 1.28.2; it isn't used.
- `import fitz` is deprecated in PyMuPDF 1.28; the code now imports `pymupdf` (done).

## Open issues from post-merge source risk audit (2026-11-22)

These are **source-review findings**, not necessarily reproduced defects. Priority reflects potential user impact; a fix is complete only once its regression test and relevant runtime checks pass. IDs are stable for PRs and follow-up audits.

| ID | Priority | Status | Issue and evidence | Required resolution / acceptance test |
| --- | --- | --- | --- | --- |
| **R1** | **P1: security** | Fixed in code, Windows verification pending (C14): provenance kept; untrusted files routed to LibreOffice; NTFS stream tests pass on Windows CI. Not yet tried with real downloaded files and Office. | **Downloaded PowerPoint trust metadata is stripped.** `converter/slides/render.py:14–19, 52–62, 146–155` copies only document bytes, intentionally removing Windows Mark-of-the-Web before COM opens it. That can bypass Office's Protected View trust signal. | Preserve/trust-assess source provenance, select a safer fallback for untrusted documents or require explicit user approval; add tests with real downloaded/MOTW-tagged presentations on Windows. Do **not** silently remove provenance just to make COM render. |
| **R2** | **P1: user-data safety** | Fixed in code, Windows verification pending: `owned_pid` proof rule; tested with fakes only, never with real Office. | **PowerPoint process ownership is uncertain.** `converter/platforms/windows_powerpoint.py:75–82, 129–139` infers whether an instance was running from `GetActiveObject`, then may `taskkill /F /T` a PID after a timeout. Existing tests simulate PIDs; they do not prove ownership with real Office/COM. | Require reliable proof a process belongs to this conversion before killing it. Test with a user PowerPoint session open and edited/unsaved presentations, timeouts and cancellation. Do not terminate a process if ownership is uncertain. |
| **R3** | **P1: output integrity** | Fixed: isolated renderer folders; regression test fails on the old code and passes now. | **PowerPoint and LibreOffice fallback share an output filename.** `converter/slides/render.py:148, 155–169` and `libreoffice_convert():118–126` can accept a non-empty artifact left by a failed PowerPoint export as the LibreOffice result. | Isolate renderer outputs or delete/validate leftovers before fallback; test partial PowerPoint output followed by failed LibreOffice output. Verify final PDF matches intended slide count/content. |
| **R4** | **P2: data integrity** | Fixed: one state per job; deterministic threaded tests (save+discard, save+shutdown, discard+discard). | **Save and discard use separate synchronization.** `api/jobs.py:192–194, 362–452` serializes saves but not discards; concurrent bridge calls may remove scratch files while they're being copied. Frontend blocks the normal Discard button during save, but backend invariant is not enforced. | Coordinate save/discard/shutdown state; add deterministic threaded save+discard and save+shutdown tests proving no partial/corrupted user outputs. |
| **R5** | **P2: UI consistency** | Fixed: serialized, coalesced settings saves; inverted-response tests (which fail on the old provider). | **Settings requests may complete out of order.** `frontend/src/state/AppProvider.tsx:67–73` replaces local state with the full returned snapshot from each asynchronous save. A late response from an older edit can overwrite the visible result of a newer edit. | Serialize settings updates or add revision sequencing; simulate inverted response order and assert latest user choice stays visible and persisted. |
| **R6** | **P2: user-facing reliability** | Fixed: `saveSettings` returns `{ settings, issue }`; Settings shows a "Not saved" warning; tests for read-only, unwritable and disk-full cases. | **Failed settings persistence is silent.** `api/settings_store.py:186–209` catches disk write errors but returns in-memory settings as though saved, despite UI claiming immediate persistence. | Surface save failure to the UI (or unmistakable unsaved state) and test read-only/missing/full destination behavior and restart persistence. |
| **R7** | **P2: quality gate** | Fixed: `.github/workflows/ci.yml`; first green run linked in the fix log below. | **No automatic test CI is configured.** Existing `.github/workflows/build-windows.yml` is manual packaging only; agent-reported 317 Python passes have not been independently rerun in this audit. | Add PR/push jobs running Python lint/tests and frontend lint/typecheck/test/build, including Windows-appropriate checks; retain distinct Windows packaging job. Verify run links and configure required checks once stable. |
| **R8** | **P3: cleanup** | Fixed: fallback removed; a test checks `api/service.py` has no `try`. | **Transitional legacy-layout fallback** remains in `api/service.py`, catching `ImportError` broadly and potentially masking a broken new-layout import. | Remove fallback after confirming the new `converter/` imports and running backend/bridge tests. |
| **R9** | **P3: docs** | Fixed for this snapshot: ARCHITECTURE, PORTABILITY and SOURCE_INVENTORY updated with measured counts (see fix log). | **Stale docs.** `docs/ARCHITECTURE.md` says frontend/API unmerged; previous edition of this review cited 163 tests and unmerged layers. README and agent instructions were updated. | Update architecture flow, frontend/API sections and source inventory against the actual merged code. Capture exact current test counts/results with platform/commit reference. |
| **R10** | **P1: release blocker** | Open, Windows verification required. Partly covered on a GitHub Windows VM: the installer builds, installs silently and the app starts (run 45202300026). | **Real Windows application and installer are unverified.** WebView2, native dialogs/drag/drop, COM, OCR, installing optional dependencies, startup, upgrade and uninstall cannot be certified by Linux/frontend checks. | Run Windows build; install as standard user; launch packaged UI; exercise all six actions with synthetic samples; test OCR on/off, COM/LibreOffice fallback, cancellation, saving, settings restart, upgrade/uninstall. Record exact outcomes and logs. |

### Fix log (2026-11-23)

Implementation of the fixes above, by AI agents (not a human review). Evidence:

- **CI run** [45126075718](https://github.com/Ali7488/pdf-manager/actions/runs/45126075718) on commit `454ed5d`: Python on Linux **355 passed, 5 skipped** (the 5 are Windows-only NTFS tests); Python on Windows **346 passed, 14 skipped** (tests needing Tesseract or LibreOffice skip there; the NTFS provenance tests ran and passed); frontend **83 passed**, typecheck, lint and single-file build OK.
- The first CI run (45125511288) failed on Windows: two API tests assumed POSIX paths. The tests were fixed (`ce4f73f`); the code was correct.
- **R1–R3** remain open for Windows acceptance as the audit requires: they were never exercised with real Microsoft Office, real downloaded files or a hung PowerPoint.
- **New gap found while documenting:** the API layer's Windows-specific code was gated inside `api/bridge.py` instead of one platform module, contrary to P15. **Fixed** the same day: it now lives in `api/platforms/`.

**Do not close R1–R3 based only on mock tests.** Do not mark R10 resolved on a successful compiler build alone. The aim is a reliable Windows application for a nontechnical person, not a reassuring collection of green checkmarks.

### Priority order

1. **P1:** Address R1–R3 in code and tests before running the new installer with important documents; complete R10 before release to the actual end user.
2. **P2:** Repair R4–R6 and implement R7; verify behavior across UI and API rather than only testing a single function.
3. **P3:** Resolve R8–R9 while updating documentation and recording verified outcomes.


## Open work

1. Resolve P1 audit issues **R1–R3** and verify a real Windows 11 build and installed application (**R10**), including downloaded-file provenance, COM ownership, renderer fallback, cancel/timeout behavior, WebView2, OCR, native file dialogs, installation, upgrade and uninstall.
2. Fix concurrency/persistence issues **R4–R6** and add regression tests.
3. Implement automated Python/frontend pull-request CI **R7** and record actual run results, not just agent-reported test counts.
4. Remove transitional import fallback **R8** and update `docs/ARCHITECTURE.md`, `docs/SOURCE_INVENTORY.md` and any obsolete references in `docs/PORTABILITY.md` (**R9**).
5. ~~Make Windows-specific troubleshooting text platform-aware.~~ Done 2026-11-23 for the service layer's messages (`os_family()`, tested); the API layer's Linux OCR-install message is being added with the Linux work.
6. Public release requirements: licence chosen (P31) and third-party licences validated with automated checks (`docs/LICENSING_AUDIT_2026-11-23.md`); open questions O1–O3 remain. Decide whether and when to sign the installer (unsigned accepted for initial private testing, F17).
7. Complete a line-by-line human code ownership review and actual-user acceptance before resume/release claims.

Historical originals of the imported baseline are in `.migration/` locally (Git-ignored).
