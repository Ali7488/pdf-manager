# Engineering review backlog (imported v1.1.1)

These are **issues to investigate**, not claims that fixes are already complete.

1. **Notes contamination:** resolved by removing the speaker-notes feature. Only slides are converted.
2. **PowerPoint automation:** on Windows `powerpoint_to_pdf()` prefers PowerPoint COM and may trigger an unavailable printer dialog. Review explicit fallback/engine selection and cleanup after failure.
3. **File-lock testing:** regression test simulates WinError 32 from `Path.unlink`; verify real Windows AV/PowerPoint/Explorer interactions and scratch cleanup with acceptance fixtures.
4. **Installer quality:** v1.0 `install_windows.ps1` may install LibreOffice even if Microsoft Office exists; VBScript updaters are legacy and **not part of the active public release**.
5. **Rebranding:** done. The app is SlideStitch, with settings stored in `%LOCALAPPDATA%\SlideStitch`.
6. **Error boundaries:** review threading, GUI events, subprocess cancellation/timeouts, structured warnings vs exception popups.
7. **Testing depth:** add corrupt PDFs, locked files, password protected PDFs, output collision, cancellation, image-only scans, order preservation, large page counts, and QA for scientific notation and non-Latin text.
8. **Public release:** pick license, replace private example language with synthetic examples, CI, packaging and binaries, versioning and source integrity.

**Apart from rebranding, code formatting and splitting `converter.py` into the `converter/` package, the v1.1.1 app/converter logic is unchanged from the baseline.** Historical originals are in `.migration/` locally but are Git-ignored to keep the first tracked tree clean.
