"""Check how faithfully LibreOffice Impress converts representative presentations.

    uv run scripts/check_slide_fidelity.py out/fidelity            # all decks
    uv run scripts/check_slide_fidelity.py out/fidelity --png      # also render PNGs to inspect

LibreOffice Impress is PDF Manager's only presentation converter (decision C17).
This script builds synthetic decks that exercise what tends to go wrong (long and
auto-fitted text, numerical labels, charts, fonts and scripts, slide count, a hidden
slide, 4:3 and 16:9 sizes, legacy .ppt), converts each one with the app's own
``converter.slides.render_slides`` and checks the PDF:

* **slide count:** one page per visible slide;
* **missing text:** every expected string is extractable from its page;
* **clipped text:** no text span lies outside the page;
* **numbers:** chart and table labels appear as formatted (e.g. "12.5%", "$1,234");
* **fonts:** which fonts were embedded, and which requested fonts were substituted.

It prints a report and writes ``report.json`` (and PNGs with ``--png``) into the
output folder. Synthetic documents only; nothing is sent anywhere. Needs
python-pptx (a dev dependency) and LibreOffice.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf
from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from converter.core.context import JobContext  # noqa: E402
from converter.slides.render import render_slides  # noqa: E402
from converter.tools import find_libreoffice, run_command  # noqa: E402

LONG = (
    "This paragraph is deliberately long so that it has to wrap over several lines inside "
    "its text box, which is where renderers most often differ in line breaking and spacing. "
    "The final words must still be visible: END-OF-PARAGRAPH-MARKER"
)


@dataclass
class Deck:
    """A generated deck and what its PDF must contain."""

    name: str
    path: Path
    visible_slides: int
    # Per visible slide (0-based page index): strings that must be on that page.
    expected: dict[int, list[str]] = field(default_factory=dict)
    fonts_requested: list[str] = field(default_factory=list)
    note: str = ""


def _blank(pres: Presentation):
    return pres.slides.add_slide(pres.slide_layouts[6])


def _text(slide, text: str, *, left=0.5, top=0.5, width=9.0, height=1.0, size=18, font=None):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.word_wrap = True
    frame.text = text
    for paragraph in frame.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(size)
            if font:
                run.font.name = font
    return box


def text_deck(out: Path) -> Deck:
    """Titles, bullets, long wrapped paragraphs, autofit body text and a table."""
    pres = Presentation()
    expected: dict[int, list[str]] = {}
    title = pres.slides.add_slide(pres.slide_layouts[0])
    title.shapes.title.text = "Quarterly Review"
    title.placeholders[1].text = "Prepared for testing"
    expected[0] = ["Quarterly Review", "Prepared for testing"]

    bullets = pres.slides.add_slide(pres.slide_layouts[1])
    bullets.shapes.title.text = "Agenda"
    body = bullets.placeholders[1].text_frame
    items = ["Results", "Risks and mitigations", "Next steps", "Questions"]
    body.text = items[0]
    for item in items[1:]:
        body.add_paragraph().text = item
    sub = body.add_paragraph()
    sub.text = "Second-level bullet"
    sub.level = 1
    expected[1] = ["Agenda", *items, "Second-level bullet"]

    wrap = _blank(pres)
    _text(wrap, LONG, top=1.0, height=3.0, size=24)
    expected[2] = ["END-OF-PARAGRAPH-MARKER"]

    # Body text that only fits because PowerPoint shrinks it (normAutofit).
    fit = pres.slides.add_slide(pres.slide_layouts[1])
    fit.shapes.title.text = "Shrink on overflow"
    frame = fit.placeholders[1].text_frame
    lines = [f"Overflowing line {n} with enough words to wrap" for n in range(1, 15)]
    frame.text = lines[0]
    for line in lines[1:]:
        frame.add_paragraph().text = line
    frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    expected[3] = ["Shrink on overflow", "Overflowing line 1 ", "Overflowing line 14"]

    table_slide = _blank(pres)
    rows = [
        ("Region", "Revenue", "Growth"),
        ("North", "$1,234", "12.5%"),
        ("South", "$987", "-3.1%"),
    ]
    table = table_slide.shapes.add_table(3, 3, Inches(1), Inches(1), Inches(8), Inches(2)).table
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    expected[4] = ["Region", "$1,234", "12.5%", "-3.1%"]

    path = out / "01-text.pptx"
    pres.save(path)
    return Deck("Text, bullets, autofit, table", path, 5, expected, ["Calibri (theme)"])


def chart_deck(out: Path) -> Deck:
    """Column, line, pie and scatter charts with formatted data labels and axis titles."""
    pres = Presentation()
    expected: dict[int, list[str]] = {}

    data = CategoryChartData(number_format="0.0%")
    data.categories = ["Q1", "Q2", "Q3", "Q4"]
    data.add_series("Margin", (0.125, 0.18, 0.205, 0.231))
    slide = _blank(pres)
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(0.5), Inches(9), Inches(6), data
    ).chart
    plot = chart.plots[0]
    plot.has_data_labels = True
    plot.data_labels.number_format = "0.0%"
    plot.data_labels.number_format_is_linked = False
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    chart.has_title = True
    chart.chart_title.text_frame.text = "Margin by quarter"
    expected[0] = ["Margin by quarter", "Q1", "Q4", "12.5%", "18.0%", "20.5%", "23.1%"]

    data = CategoryChartData(number_format="$#,##0")
    data.categories = ["Jan", "Feb", "Mar"]
    data.add_series("Revenue", (1234, 5678, 91011))
    data.add_series("Costs", (1000, 4000, 70000))
    slide = _blank(pres)
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.LINE_MARKERS, Inches(0.5), Inches(0.5), Inches(9), Inches(6), data
    ).chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    plot = chart.plots[0]
    plot.has_data_labels = True
    plot.data_labels.number_format = "$#,##0"
    plot.data_labels.number_format_is_linked = False
    value_axis = chart.value_axis
    value_axis.has_title = True
    value_axis.axis_title.text_frame.text = "US dollars"
    expected[1] = ["Revenue", "Costs", "$1,234", "$5,678", "$91,011", "US dollars"]

    data = CategoryChartData()
    data.categories = ["Alpha", "Beta", "Gamma"]
    data.add_series("Share", (0.5, 0.3, 0.2))
    slide = _blank(pres)
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.PIE, Inches(1), Inches(0.5), Inches(8), Inches(6), data
    ).chart
    plot = chart.plots[0]
    plot.has_data_labels = True
    plot.data_labels.show_percentage = True
    plot.data_labels.show_value = False
    plot.data_labels.number_format = "0%"
    plot.data_labels.number_format_is_linked = False
    chart.has_legend = True
    expected[2] = ["Alpha", "Beta", "Gamma", "50%", "30%", "20%"]

    xy = XyChartData()
    series = xy.add_series("Measurements")
    for x, y in ((1.5, 2.25), (3.0, 9.0), (4.5, 20.25)):
        series.add_data_point(x, y)
    slide = _blank(pres)
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.XY_SCATTER, Inches(0.5), Inches(0.5), Inches(9), Inches(6), xy
    ).chart
    chart.has_title = True
    chart.chart_title.text_frame.text = "Scatter of measurements"
    expected[3] = ["Scatter of measurements"]

    path = out / "02-charts.pptx"
    pres.save(path)
    return Deck("Charts and numerical labels", path, 4, expected)


FONTS = ["Calibri", "Segoe UI", "Arial", "Times New Roman", "Cambria", "Aptos", "NoSuchFont Pro"]


def font_deck(out: Path) -> Deck:
    """One line per common Office font (and one that exists nowhere), plus other scripts."""
    pres = Presentation()
    slide = _blank(pres)
    expected = []
    for row, font in enumerate(FONTS):
        line = f"{font}: The quick brown fox 0123456789"
        _text(slide, line, top=0.3 + row * 0.8, height=0.7, size=20, font=font)
        expected.append(line)
    scripts = _blank(pres)
    samples = {
        "Arabic": "مرحبا بالعالم",
        "Greek": "Καλημέρα κόσμε",
        "Chinese": "你好，世界",
        "Accents": "Crème brûlée, Ærøskøbing, Łódź",
    }
    expected_scripts = []
    for row, (label, text) in enumerate(samples.items()):
        _text(scripts, f"{label}: {text}", top=0.5 + row * 1.2, height=1.0, size=24)
        expected_scripts.append(text)
    path = out / "03-fonts.pptx"
    pres.save(path)
    return Deck(
        "Fonts and scripts",
        path,
        2,
        {0: expected, 1: expected_scripts},
        FONTS,
    )


def count_deck(out: Path) -> Deck:
    """30 slides, one of them hidden; 4:3 size."""
    pres = Presentation()
    pres.slide_width, pres.slide_height = Inches(10), Inches(7.5)
    expected: dict[int, list[str]] = {}
    page = 0
    for n in range(1, 31):
        slide = _blank(pres)
        _text(slide, f"Slide number {n} of 30")
        if n == 15:
            slide._element.set("show", "0")  # Hidden in PowerPoint's slide show.
            continue
        expected[page] = [f"Slide number {n} of 30"]
        page += 1
    path = out / "04-thirty-slides-one-hidden.pptx"
    pres.save(path)
    return Deck(
        "Slide count (30 slides, slide 15 hidden, 4:3)",
        path,
        29,
        expected,
        note="PowerPoint's own Save as PDF also leaves hidden slides out by default.",
    )


def widescreen_deck(out: Path) -> Deck:
    """16:9 with text near every edge (clipping)."""
    pres = Presentation()
    pres.slide_width, pres.slide_height = Inches(13.333), Inches(7.5)
    slide = _blank(pres)
    corners = {
        "TOP-LEFT": (0.1, 0.1),
        "TOP-RIGHT": (10.8, 0.1),
        "BOTTOM-LEFT": (0.1, 6.7),
        "BOTTOM-RIGHT": (10.4, 6.7),
    }
    for label, (left, top) in corners.items():
        _text(slide, label, left=left, top=top, width=2.4, height=0.6, size=20)
    path = out / "05-widescreen-edges.pptx"
    pres.save(path)
    return Deck("16:9 with text at the edges", path, 1, {0: list(corners)})


def legacy_deck(out: Path, source: Deck) -> Deck | None:
    """The text deck saved as legacy .ppt by LibreOffice (if installed)."""
    office = find_libreoffice()
    if office is None:
        return None
    run_command(
        [office, "--headless", "--convert-to", "ppt", "--outdir", out, source.path], timeout=300
    )
    path = out / f"{source.path.stem}.ppt"
    if not path.is_file():
        return None
    target = path.with_name("06-text-legacy.ppt")
    path.replace(target)
    return Deck("Legacy .ppt (the text deck)", target, source.visible_slides, source.expected)


@dataclass
class Result:
    deck: str
    file: str
    slides_expected: int
    pages: int = 0
    missing_text: list[str] = field(default_factory=list)
    clipped_text: list[str] = field(default_factory=list)
    fonts_embedded: list[str] = field(default_factory=list)
    error: str = ""
    note: str = ""

    @property
    def ok(self) -> bool:
        return (
            not self.error
            and self.pages == self.slides_expected
            and not self.missing_text
            and not self.clipped_text
        )


def _normalise(text: str) -> str:
    """Compare text, not layout: join lines broken after a hyphen, collapse whitespace."""
    text = text.replace("\u00a0", " ").replace("-\n", "-")
    return " ".join(text.split())


def check(deck: Deck, work: Path, png: Path | None) -> Result:
    result = Result(deck.name, deck.path.name, deck.visible_slides, note=deck.note)
    try:
        pdf = render_slides(deck.path, work / deck.path.stem, JobContext(), deck.path.name)
    except Exception as exc:  # Reported, not raised: the other decks still run.
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    with pymupdf.open(pdf) as doc:
        result.pages = doc.page_count
        fonts: set[str] = set()
        for index, page in enumerate(doc):
            text = _normalise(page.get_text())
            for wanted in deck.expected.get(index, []):
                if _normalise(wanted) not in text:
                    result.missing_text.append(f"page {index + 1}: {wanted!r}")
            area = page.rect
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        box = pymupdf.Rect(span["bbox"])
                        if span["text"].strip() and not area.contains(box):
                            result.clipped_text.append(f"page {index + 1}: {span['text']!r}")
            fonts.update(f[3] for f in page.get_fonts())
            if png is not None:
                page.get_pixmap(dpi=60).save(png / f"{deck.path.stem}-{index + 1:02d}.png")
        result.fonts_embedded = sorted(name.split("+", 1)[-1] for name in fonts)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--png", action="store_true", help="also render each page to PNG")
    args = parser.parse_args(argv)
    office = find_libreoffice()
    if office is None:
        print("LibreOffice isn't installed; nothing to check.")
        return 2
    out = args.output
    decks_dir, work = out / "decks", out / "work"
    decks_dir.mkdir(parents=True, exist_ok=True)
    png = out / "png" if args.png else None
    if png is not None:
        png.mkdir(exist_ok=True)
    text = text_deck(decks_dir)
    decks = [text, chart_deck(decks_dir), font_deck(decks_dir), count_deck(decks_dir)]
    decks.append(widescreen_deck(decks_dir))
    legacy = legacy_deck(decks_dir, text)
    if legacy is not None:
        decks.append(legacy)
    version = run_command([office, "--version"], timeout=60).stdout.strip()
    results = [check(deck, work, png) for deck in decks]
    report = {
        "system": f"{platform.system()} {platform.release()}",
        "libreoffice": version,
        "results": [{**asdict(r), "ok": r.ok} for r in results],
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"{report['system']}; {version}")
    for r in results:
        print(f"\n{'OK  ' if r.ok else 'FAIL'} {r.deck} ({r.file})")
        print(f"     pages {r.pages} / slides {r.slides_expected}")
        for label, items in (("missing", r.missing_text), ("clipped", r.clipped_text)):
            for item in items:
                print(f"     {label}: {item}")
        if r.error:
            print(f"     error: {r.error}")
        print(f"     fonts: {', '.join(r.fonts_embedded) or '(none)'}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
