# Licensing and release-readiness audit, 2026-11-23

Requested by the owner: an evidence-based review of the licensing and release work for v0.5.0, verifying the owner's findings L1–L6 and the earlier implementation (decisions P30, P31) against the repository, the dependency metadata, the bundled binaries, the licence texts and upstream documentation. Done by an AI agent (Claude); **this isn't legal advice and isn't a human review**. Where something can't be settled from the evidence, it's marked **unresolved**.

Commits from this audit: see section 8.

## 1. Verdict

**The licensing strategy is coherent.** The MIT licence for the original code is compatible with the AGPL-3.0 (FSF licence list: Expat is "compatible with the GNU GPL"). Conveying the combined app under the AGPL-3.0, PyMuPDF's open-source option, is the correct way to distribute a PyMuPDF-based program without a commercial licence. Nothing found requires changing the strategy.

**The earlier implementation was incomplete.** Six concrete gaps were found and fixed (section 3): missing MuPDF source, missing or wrong notices, an overwrite bug, a reconstructed licence file, and a Windows bundle carrying Microsoft files that nothing listed.

**One legal question can't be settled here (O1/O2):** the Windows app carries Microsoft binaries without published source (the WebView2 SDK files and the Visual C++ runtime). Whether they're acceptable in an AGPL-3.0 distribution needs Artifex's confirmation or legal advice.

**Release readiness:**
- **Private testing (trusted testers): ready.** The final Windows build in section 6 is green.
- **Public pre-release: an owner decision.** Every technical and documentation gate is met except O1–O3. The risk is mainly theoretical for a free, non-commercial project, but it isn't zero, and this audit can't make it zero.

## 2. Method and evidence types

The labels in the tables below mean:

| Label | Meaning |
| --- | --- |
| **Source** | Read the code, configuration or documents. |
| **Artifact** | Downloaded and inspected the actual files: wheels, NuGet package, MuPDF and CPython releases (byte comparisons, version resources, strings). |
| **Local** | Ran on the agent's Linux machine. |
| **CI** | GitHub Actions run, on GitHub's Linux and Windows virtual machines. |
| **Real machine** | Real Windows 11 PC. **Nothing in this audit is real-machine evidence.** |

## 3. Findings

| # | Finding (as raised) | Verdict | Evidence | Resolution | Remaining risk |
| --- | --- | --- | --- | --- | --- |
| L1 | Proprietary WebView2 SDK DLLs in an AGPL work; System Libraries unproven. | **Partially correct.** The DLLs are bundled, and the preinstalled Runtime doesn't settle it. But they aren't under a restrictive EULA: Microsoft's NuGet `LICENSE.txt` for 1.0.3856.49 is a BSD-3-Clause-style licence, which is GPL-compatible. The open question is source availability, not licence conflict. | Artifact: pywebview 6.2.1's three DLLs (five files) are byte-identical to `Microsoft.Web.WebView2` 1.0.3856.49 (`cmp`; version resources 1.0.3856.49). The NuGet package carries `LICENSE.txt` (BSD-style) and `NOTICE.txt` (ANTLR/StringTemplate notices). Microsoft Learn says managed apps must ship these files. No published source found. | Licence and NOTICE now shipped. The collector re-verifies byte-identity and the build fails if the DLLs change. | **Unresolved (O1).** §1 "System Libraries" requires being "included in the normal form of packaging a Major Component"; the SDK DLLs come with the SDK, not with Windows. |
| L1+ | (new) Microsoft C++ runtime and other Microsoft files in the bundle. | **Confirmed, new.** The real Windows build contained `vcruntime140*.dll`, `MSVCP140.dll`, 45 UCRT files (`ucrtbase.dll`, `api-ms-win-*.dll`) and `mfc140u.dll`, none of them listed. | CI: run 45200592420 (bundle check output). The GNU FAQ (WindowsRuntimeAndGPL) says the VC++ runtime is a System Library, but "if you distribute the DLLs with the program, they won't be eligible for this exception anymore". Microsoft's VS 2022 redistribution page limits redistribution of the runtime files "to licensed Visual Studio users". Microsoft's UCRT page says Windows 10/11 always use the system UCRT, even when an app ships its own. | UCRT and MFC excluded from the bundle (unused; the check fails if they return). The VC++ runtime is listed with a factual notice. | **Unresolved (O1, O2)** for the VC++ runtime. |
| L2 | Corresponding Source not demonstrated; PyPI pointers may not suffice. | **Confirmed, and worse than stated.** `LICENSING.md` promised the PyMuPDF sdist, but that sdist doesn't contain MuPDF (its `setup.py` downloads `mupdf-1.28.2-source.tar.gz` at build time). The Python patch version and Inno Setup weren't pinned. | Artifact: sdist listing; `setup.py` lines 8–23, 318. CI: the Windows runner used CPython 3.13.17 from its tool cache, with no pin. | `scripts/collect_sources.py` gathers every bundled package's source plus MuPDF, CPython and PyInstaller, checked against `uv.lock` and `package-lock.json` hashes. It runs as the `sources` job in `build-windows.yml`. Python pinned to 3.13.17 (`setup-python`, `UV_PYTHON`); Inno Setup pinned to 6.7.1. | Local: 22 archives (187 MB), all checksums OK. CI: `sources` job green (runs 45200592420 onward). Attaching to the release is a release step (P31). §6(d) allows a third-party server for source, but the distributor must keep it available, so the release attachment is the safe route. |
| L3 | Licence inventory incomplete; no BOM check; `licenses/frontend` not verified at install. | **Confirmed.** | Source, Artifact, CI. Problems found: (a) the Windows app shipped the *Linux* Python licence (277 lines; python.org's Windows `LICENSE.txt` is 645 lines, with the bundled libraries and the Microsoft Distributable Code terms); (b) MuPDF's 20 compiled-in libraries and fonts had no notices; (c) pywin32's ten licence files overwrote each other by name (only four kept); (d) the Feather licence was the SPDX template with a guessed year; (e) the Inno Setup uninstaller and the VC++ runtime weren't listed; (f) no check tied any of this to the bundle. | (a)–(e) fixed in `scripts/collect_licenses.py` (55 components; `licenses/manifest.json`). `check_licenses.py repo` runs in the test suite and fails on stale versions, new or removed dependencies, missing files, incomplete copyleft texts, missing installer entries and MIT-only wording. `check_licenses.py bundle` runs in `build.ps1` and after the silent install. Every native file must map to a component, WebView2 hashes must match, the Python version and licence must match, and with `--installed` every licence file must be byte-identical to the repo's and none stale. The installer now deletes old licence files on upgrade. | The classification table covers today's bundle and fails closed on anything new. |
| L4 | Linux PySide6/Qt obligations; Qt WebEngine/Chromium notices. | **Confirmed (future gate, v0.75).** | Artifact (local venv): the PySide6 6.12.0 wheels ship **no licence files at all**, and bundle FFmpeg, ICU and Qt WebEngine (Chromium). Qt's LGPL page requires Qt's complete source (even unmodified), the ability to relink or replace, the LGPL text, and notes some Qt parts are GPL-only. | Qt and PySide6 source URLs recorded in the manifest. LGPL and GPL texts shipped for each PySide6 package. | Before v0.75: collect only the Qt modules used; ship Qt's and Chromium's third-party notices; attach the Qt source. GPL-3.0-only Qt modules are AGPL-compatible (AGPL §13) but should be avoided. Not inspected: an actual Linux bundle (none exists). |
| L5 | Documentation drift. | **Partially correct.** `pyproject.toml` `license = "MIT"` is correct for the source. P20 and P30 were stale. `packaging/README.md` still said the repo was private. `ENGINEERING_REVIEW.md`'s status block was outdated. The README told people to download a release that doesn't exist. The release notes' runner evidence did exist (run 45162114777) but didn't say it was a virtual machine. Also found: Settings → About said "open-source components" while bundling proprietary Microsoft files. | Source. | All corrected. SHA-256 integrity steps added to the README and release notes. The repo check fails if README, LICENSING or the release notes describe the app as MIT or omit the AGPL-3.0. | GitHub's sidebar shows "MIT" (detected from `LICENSE`). Explained in `LICENSING.md`; accepted as accurate for the source. |
| L6 | Asset provenance (icon, preview, fonts, icons). | **Partially correct.** | Source and Artifact. `PDF Manager.ico` and `assets/icon-preview.png` arrived with the imported baseline (commits `7293ad4`, `e4baa64`), with no record of their author. Open Sans comes from `@fontsource-variable/open-sans` 5.3.0 (OFL-1.1 with the Open Sans Project Authors' copyright; the FSF lists the OFL as a free licence for fonts). Segoe UI is only named in the CSS font stack, never bundled. The settings gear path is Feather's `settings.svg` with its numbers rounded; the other icons are simple original geometry. | Feather's real licence (v4.29.2) now shipped and the derived icon named. | **Unresolved (O3):** the owner must confirm the icon's provenance. |

### Other questions in the request

| Question | Result |
| --- | --- |
| MIT/AGPL compatibility | Compatible. The combination is correctly presented: MIT for the source files, AGPL-3.0 for the distributed app (`LICENSING.md`, About, README, notices). |
| PyMuPDF/MuPDF terms | PyMuPDF metadata: "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License". MuPDF headers: AGPL "version 3 … or any later version". MuPDF also compiles in AGPL-licensed jbig2dec and extract. Obligations (§4–6, §5d notices) are implemented. §13 (network use) doesn't apply: the app runs locally. |
| Python runtime, PyInstaller | Python licence: "compatible with the GNU GPL" (FSF). PyInstaller's bootloader is GPL-2.0-or-later with the Bootloader Exception (its `COPYING.txt`, line 16), which allows any licence for the bundled app. |
| Frontend | react, react-dom, scheduler, @dnd-kit/* (MIT), tslib (0BSD), Open Sans (OFL-1.1). All inlined into one HTML file. No conflict. |
| Libraries inside MuPDF | Licences read from each file: MIT (Brotli, lcms2, HarfBuzz "Old MIT"), BSD-2/3 (cmark-gfm, Leptonica, OpenJPEG, Zint backend), Apache-2.0 (Tesseract, ZXing-C++, Gumbo, Droid), FTL or GPL-2.0+ (FreeType), IJG (libjpeg), ISC (MuJS), Zlib, OFL-1.1 (Noto, Source Han, Charis SIL), AGPL-3.0 (extract, jbig2dec). FSF lists these as GPLv3-compatible (Apache-2.0, FTL and IJG included). curl and freeglut are viewer-only in MuPDF's build and show no trace in the Windows DLL, so they're left out. |
| Inno Setup | Licence: "use this software for any purpose, including commercial applications" with notice conditions. The compiler's "Non-commercial use only" banner reflects jrsoftware's request that *commercial* users buy a licence, which "is not strictly required". It doesn't apply to this project. The uninstaller (`unins000.exe`) is now listed with the licence. |
| Overlooked conflicts | None found among the open-source components. The Microsoft binaries (O1/O2) are the only unresolved point. pywebview's `WebBrowserInterop.*.dll` (legacy MSHTML backend, part of pywebview's BSD-3 package) wasn't traced to source in pywebview's current repository. It loads only when WebView2 is missing; a candidate for exclusion, but that needs a Windows test. |

## 4. Changes made

| Commit | Files | Why |
| --- | --- | --- |
| `6e39fe8` | `scripts/collect_sources.py` | Gather the complete third-party source for a release (L2). |
| `fef199f` | `scripts/collect_licenses.py`, `licenses/**`, `THIRD_PARTY_NOTICES.md` | MuPDF libraries, WebView2 licence and NOTICE (byte-verified), Windows Python licence plus CPython notices, pywin32 overwrite fix, manifest (L1, L3). |
| `094b608` | `scripts/check_licenses.py`, `tests/test_licensing.py`, `packaging/build.ps1`, `packaging/installer.iss`, `.github/workflows/build-windows.yml` | Automated repo, bundle and installed checks; Python pin; upgrade cleanup; source job (L2, L3). |
| `277beed` | `packaging/pdf-manager.spec`, checks, notices | Exclude the UCRT and MFC; list the VC++ runtime (L1+). |
| `fb67879` | collector, `licenses/other/feather-icons/LICENSE` | Real Feather licence (L3, L6). |
| `6a5af8d` | collector, checks, tests, workflow | Inno Setup listed and pinned to 6.7.1. |
| `fcd8531` | `scripts/check_licenses.py`, tests | Fix the Inno Setup classification bug; whole-app test. |
| *(docs commit)* | `LICENSING.md`, `README.md`, `docs/releases/v0.5.0.md`, `packaging/README.md`, `docs/DECISIONS.md`, `docs/ENGINEERING_REVIEW.md`, `pyproject.toml`, `SettingsPage.tsx`, this file | Documentation corrections (L5) and open questions O1–O3. |

The licensing strategy (P31) wasn't changed.

## 5. Tests and checks run

| Check | Where | Result |
| --- | --- | --- |
| `uv run pytest` | Local (Linux) | 483 passed, 5 skipped (Windows-only NTFS tests), including 34 in `tests/test_licensing.py`. |
| `uvx ruff check …` and `ruff format --check` | Local | Clean. |
| `npm run lint`, `typecheck`, `test`, `build` | Local | Clean; 95 tests passed; build 459.5 kB. |
| `scripts/check_licenses.py repo` | Local, and in CI via pytest | Passed. |
| `scripts/collect_sources.py --platform windows` | Local; CI `sources` job | 22 archives, all checksums verified; CI job green. |
| Windows build plus bundle check plus installed check plus smoke test | CI (`build-windows.yml`) | Runs 45200592420, 45201312558 and 45201750417 **failed, correctly**: each time the new checks found a real gap (UCRT, MFC and C++ runtime files; then the uninstaller; then the checker's own bug). Each gap was fixed. Run 45202300026 **passed** (section 6). |
| Negative tests | Local | Each check is shown to fail on the defect it targets: new or bumped dependency, unknown DLL, changed WebView2 file, Qt in the Windows app, UCRT or MFC present, unlisted package, tampered, missing or stale installed licence files, bad checksum. The whole-app test was confirmed to fail without the Inno Setup fix. |

Not tested: anything on a real Windows 11 PC; the Linux bundle (doesn't exist yet); legal sufficiency.

## 6. Final Windows run

[Run 45202300026](https://github.com/Ali7488/pdf-manager/actions/runs/45202300026) on commit `fcd8531` (CI, GitHub Windows virtual machine; **not** a real PC):

- Build used CPython 3.13.17 (pinned) and Inno Setup 6.7.1 (pinned); installer `PDF-Manager-Setup-0.5.0.exe`, 26.4 MB.
- `check_licenses.py repo`: passed. `bundle` on `dist\PDF Manager`: passed. 49 native files, all mapped: Python runtime 22, pywin32 9, WebView2 5, VC++ runtime 3, PyMuPDF 3, clr-loader 2, pywebview 2, cffi 1, pythonnet 1, bootloader 1.
- Silent install, then `bundle --installed`: passed. The installed licence files are byte-identical to the repository's; the uninstaller is listed.
- Smoke test of the installed app, with the UCRT and MFC files no longer bundled: `SMOKE TEST PASSED` (window opened, UI rendered, bridge answered).
- `sources` job: 22 source archives, checksums verified, uploaded as the `PDF-Manager-third-party-sources` artifact.

## 7. Remaining blockers and decisions

**Legal (owner):**
- **O1.** Microsoft binaries (WebView2 SDK, VC++ runtime) in the AGPL-3.0 app. Options:
  1. Ask Artifex (PyMuPDF's licensor) for written confirmation that shipping them is acceptable. This is the most direct route.
  2. Get legal advice.
  3. Reduce the exposure technically: rely on the system VC++ Redistributable (installer prerequisite) instead of bundling it. There's no comparable option for the WebView2 SDK DLLs short of replacing pywebview's Windows backend.
- **O2.** VC++ runtime redistribution is limited to licensed Visual Studio users. Either the owner holds a Visual Studio Community licence (free for individual and open-source use, under its own terms, which the owner should read), or the installer uses Microsoft's redistributable.

**Ownership (owner):**
- **O3.** Confirm the app icon and preview image may be distributed, or replace them.

**Technical (before v0.75):**
- Linux licence work (L4).
- Decide on pywebview's MSHTML interop DLLs (Windows test needed).

**Release process:**
- Tag the commit `v0.5.0` and build from the tag.
- Attach the installer, `SHA256SUMS.txt` and the source bundle.
- Publish only on the owner's approval (P31).
- Real Windows 11 acceptance (R10) remains open.

## 8. Commits

`6ae3153` (request log), `6e39fe8`, `fef199f`, `094b608`, `277beed`, `fb67879`, `6a5af8d`, `fcd8531`, and the documentation commit that adds this file.
