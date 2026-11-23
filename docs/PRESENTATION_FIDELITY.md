# Presentation fidelity (LibreOffice Impress)

PDF Manager converts every `.pptx` and `.ppt` with **LibreOffice Impress** (decision C17). This page records how faithful that conversion is, how it was checked, and what needs follow-up.

## When a closer match is needed

LibreOffice is not PowerPoint, and some decks will look slightly different. For a deck that has to match PowerPoint exactly:

1. Open it in **Microsoft PowerPoint**.
2. Choose **File → Export → Create PDF/XPS** (or **Save As → PDF**).
3. Add that PDF to PDF Manager instead of the presentation.

The app gives the same advice when LibreOffice is missing or a conversion fails (`SLIDE_RENDERER_MISSING`, `POWERPOINT_CONVERSION_FAILED` in `converter/core/issues.py`).

## How it is checked

`scripts/check_slide_fidelity.py` builds synthetic decks with python-pptx and converts them with the app's own `render_slides`. It then checks each PDF:

- **Slide count:** one page per visible slide.
- **Missing text:** every expected string can be extracted from its page.
- **Clipped text:** no text lies outside the page.
- **Numbers:** chart and table labels appear in their number formats.
- **Fonts:** which fonts were embedded.

`--png` also renders the pages so a person can look at them.

```bash
uv run scripts/check_slide_fidelity.py out/fidelity --png
```

| Deck | Exercises |
| --- | --- |
| `01-text.pptx` | Title slide, two-level bullets, a long paragraph that must wrap, body text that only fits with **shrink on overflow** (autofit), a table with `$1,234`, `12.5%`, `-3.1%` |
| `02-charts.pptx` | Clustered column with `0.0%` labels, line chart with `$#,##0` labels, legend and axis title, pie with percentages, scatter |
| `03-fonts.pptx` | Calibri, Segoe UI, Arial, Times New Roman, Cambria, Aptos and a font that doesn't exist; Arabic, Greek, Chinese, accented Latin |
| `04-thirty-slides-one-hidden.pptx` | 30 slides at 4:3, slide 15 hidden |
| `05-widescreen-edges.pptx` | 16:9 with text in all four corners |
| `06-text-legacy.ppt` | The text deck saved as legacy `.ppt` (made by LibreOffice) |

## Results (2026-11-23)

**Platform:** Linux (CachyOS, kernel 7.3.5), LibreOffice 26.8.3.1, commit `cdfdf69` plus the script. **Not yet run on Windows.**

| Deck | Pages | Missing or clipped text | Verdict |
| --- | --- | --- | --- |
| Text, bullets, autofit, table | 5 / 5 | none | OK |
| Charts and numerical labels | 4 / 4 | none; every label in its format | OK, with notes 3 and 4 |
| Fonts and scripts | 2 / 2 | none; Arabic shaped right to left, CJK present | OK, with note 2 |
| 30 slides, one hidden | 29 / 29 | none | OK, see note 5 |
| 16:9 edges | 1 / 1 | none | OK |
| Legacy `.ppt` | 5 / 5 | **slide 4: lines 6–14 run off the bottom of the slide** | Fails, note 1 |

I looked at the rendered pages: the `.pptx` autofit slide is shrunk correctly, and all 14 lines fit. Column, line and pie labels and the table match the requested formats.

## Fidelity issues to follow up

| # | Issue | Evidence | Follow-up |
| --- | --- | --- | --- |
| 1 | **Shrink on overflow lost in a legacy `.ppt`.** Text that fits only because PowerPoint shrinks it overflows the slide. | `06-text-legacy.ppt`, slide 4. The same slide in `.pptx` is fine. | The `.ppt` was itself written by LibreOffice, so the loss may be at save time, not when reading. Retest with a `.ppt` saved by PowerPoint. If confirmed, document "re-save old `.ppt` files as `.pptx`" or the manual PDF route. |
| 2 | **Font substitution where Office fonts are missing.** On this Linux PC, Calibri and Segoe UI became Noto Sans, Aptos became Inter, Cambria became Caladea, Arial became Liberation Sans, and Times New Roman became Liberation Serif. A missing font falls back silently. Different widths can change line breaks. | `03-fonts.pptx` embedded fonts. | Windows has Calibri, Cambria, Segoe UI, Arial and Times New Roman, so this should be smaller there; **Aptos ships only with recent Microsoft 365**. Run the script on Windows. On Linux, the metric-compatible Carlito (Calibri) and Caladea (Cambria) packages (`fonts-crosextra-carlito`, `fonts-crosextra-caladea`) keep line breaks; consider recommending them. |
| 3 | **Close data labels overlap** on the line chart ($1,234 over $1,000; $5,678 over $4,000). | `02-charts.pptx`, slide 2. | Possibly the same in PowerPoint (the points nearly coincide); compare on Windows. |
| 4 | **Scatter markers render very small.** | `02-charts.pptx`, slide 4. | Compare with PowerPoint's default marker size. |
| 5 | **Hidden slides are left out.** 30 slides with one hidden gives 29 pages. | `04-thirty-slides-one-hidden.pptx`. | PowerPoint's own Save as PDF also leaves hidden slides out by default, so this matches. Mention it in the help text if users expect every slide. |

**Not covered yet:**

- SmartArt, WordArt and 3D effects, gradients and transparency, embedded fonts, OLE objects, video and audio placeholders, slide-number and date fields;
- real-world decks (only synthetic ones may be committed, AGENTS.md);
- **LibreOffice on Windows**, which is what users will run.

Next step: run the script on a Windows 11 PC with LibreOffice installed, and compare the PNGs against PowerPoint's own PDF export of the same decks.
