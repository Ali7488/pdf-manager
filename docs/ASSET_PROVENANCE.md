# Application image assets: provenance

**Reviewed:** 2026-11-23  
**Scope:** `PDF Manager.ico` and `assets/icon-preview.png`, not third-party UI icons or fonts.

## Origin and chain of custody

- The original burgundy desktop application artwork was supplied for the **Lecture PDF Maker** project in the November 22, 2026 desktop icon setup package. The owner recognizes this as the custom artwork prepared for the application, rather than an externally purchased or downloaded icon.
- The original icon was introduced into the repository as `SlideStitch.ico` in commit [7293ad4](https://github.com/Ali7488/pdf-manager/commit/7293ad4c726dd6154b45f6086700a2ac49ca5f1f).
- It was renamed to `PDF Manager.ico` in [46ac20c](https://github.com/Ali7488/pdf-manager/commit/46ac20c2804b97cd4defe7ff94c81bb9735d0127). **Git blob `f3f2366115fd781f50ff467dcabad88cc376924c` is identical before and after the rename**, so no different artwork was substituted.
- The preview file `assets/icon-preview.png` entered the repository in [e4baa64](https://github.com/Ali7488/pdf-manager/commit/e4baa6448eebdd80bc28eeee0724df3e6a998162), in the original application documentation package; its Git blob is `01120893e78be5db1107f1cc1c4eba030c7f8f85`. It was not modified by the rebranding commit.

## Redistribution assessment

The ICO has a project-specific creation history, corroborated by the original icon-setup deliverable and unchanged repository bytes. No separate third-party icon package, stock-media source, or restricted branding was identified in the available project records. A **missing external icon license** is therefore not an established defect. The owner can continue to distribute this custom icon under the project's chosen terms, subject to ordinary third-party rights.

The PNG has the same project-package provenance but has **not been independently inspected or pixel-compared** to the ICO in this review. A confirmed visual match to the original custom artwork would close its remaining narrow provenance question. Do not invent a distinct author, outside license, or an external source to fill a missing record.

These are separate from the **Feather-derived settings glyph** (`licenses/other/feather-icons/LICENSE`) and the **Open Sans** font (OFL license), whose third-party notices are already tracked in `THIRD_PARTY_NOTICES.md`.

## Status

- `PDF Manager.ico`: **origin traced; no identified external license missing**.
- `assets/icon-preview.png`: **package origin traced, visual/content match not independently confirmed**.
- Microsoft WebView2 SDK, Visual C++ redistribution, and future Qt licensing questions are unaffected by this asset review.
