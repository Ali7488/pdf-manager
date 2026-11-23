"""The single entry point for every conversion: ``run_action(action, settings, data)``.

Execution flow for one job (decision F34):

1. **Validate**: every input exists and is accepted by the action; if "Use
   OCR" is on, Tesseract must be installed (checked before any slow work).
2. **Prepare** each input as a PDF: PDFs are used as they are (only read);
   PowerPoint files are rendered (``powerpoint.render_slides``). Each input
   gets its own scratch sub-folder ``item_NNN``.
3. **Act**: flatten, merge, split, convert images or compress.
4. **Return** the outputs (still in scratch) and any warnings. The API layer
   copies outputs to the user's folder when they choose to save.

Nothing here touches the user's original files or output folder.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz

from ..core.context import CancelToken, JobContext
from ..core.issues import (
    ConversionError,
    empty_pdf,
    password_protected,
    unreadable_file,
    unsupported_file,
)
from ..core.types import (
    ACCEPTS,
    POWERPOINT_EXTENSIONS,
    Action,
    ActionData,
    ActionSettings,
    JobResult,
    OutputFile,
    Progress,
    Stage,
)
from ..ocr import add_text_layer, require_ocr
from ..slides import render_slides
from .compress import compress_pdf
from .flatten import flatten_pdf
from .images import images_to_pdf
from .merge import Part, merge_documents
from .split import split_pdf

log = logging.getLogger(__name__)


def run_action(
    action: Action,
    settings: ActionSettings,
    data: ActionData,
    *,
    scratch: Path,
    progress: Progress | None = None,
    cancel: CancelToken | None = None,
) -> JobResult:
    """Run one conversion job.

    Args:
        action: What to do.
        settings: How to do it; each action reads only the fields it needs.
        data: The input files, in the user's order.
        scratch: Empty working folder; outputs are left in it.
        progress: Receives :class:`~converter.common.ProgressEvent` updates.
        cancel: Lets the caller stop the job.

    Returns:
        The outputs (in ``scratch``) and any non-fatal warnings.

    Raises:
        ConversionError: A fatal, user-explainable problem (``.issue``).
        Cancelled: The job was cancelled.
        Exception: Anything else is a bug; the caller reports it as unexpected.
    """
    action = Action(action)
    ctx = JobContext(settings=settings, cancel=cancel or CancelToken())
    if progress is not None:
        ctx.progress = progress
    files = [Path(f) for f in data.files]
    log.info("Starting %s on %d file(s)", action.value, len(files))
    log.debug("Settings: %s", settings)

    _validate_inputs(action, files)
    scratch.mkdir(parents=True, exist_ok=True)
    if settings.use_ocr and action is not Action.COMPRESS:
        require_ocr(ctx)  # Fail fast, before any slow rendering.

    handler = {
        Action.FLATTEN: _flatten,
        Action.FLATTEN_MERGE: _flatten_merge,
        Action.MERGE: _merge,
        Action.SPLIT: _split,
        Action.IMAGES_TO_PDF: _images,
        Action.COMPRESS: _compress,
    }[action]
    outputs = handler(files, scratch, ctx)
    ctx.report(Stage.FINISHING, "Done", within_file=1.0)
    log.info(
        "Finished %s: %d output(s), %d warning(s)", action.value, len(outputs), len(ctx.warnings)
    )
    return JobResult(outputs, list(ctx.warnings))


# --- Steps shared by several actions ---------------------------------------------------


def _validate_inputs(action: Action, files: list[Path]) -> None:
    """Every input must exist and be a type this action accepts."""
    if not files:
        raise ConversionError(unsupported_file("(no files)"))
    for path in files:
        if path.suffix.lower() not in ACCEPTS[action]:
            raise ConversionError(unsupported_file(path.name))
        if not path.is_file():
            raise ConversionError(unreadable_file(path.name, f"File not found: {path}"))


def check_pdf(path: Path, label: str) -> int:
    """Reject PDFs that can't be processed; return the page count.

    Raises:
        ConversionError: Unreadable, password-protected or empty.
    """
    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise ConversionError(unreadable_file(label, str(exc))) from exc
    with doc:
        if doc.needs_pass:
            raise ConversionError(password_protected(label))
        if len(doc) == 0:
            raise ConversionError(empty_pdf(label))
        return len(doc)


def prepare_pdf(source: Path, work: Path, ctx: JobContext) -> Path:
    """Get a PDF version of one input: PDFs as they are, PowerPoints rendered into ``work``."""
    ctx.report(Stage.PREPARING, f"Opening {source.name}")
    pdf = source
    if source.suffix.lower() in POWERPOINT_EXTENSIONS:
        pdf = render_slides(source, work, ctx, source.name)
    check_pdf(pdf, source.name)
    return pdf


def _with_ocr(pdf: Path, work: Path, ctx: JobContext, label: str) -> Path:
    """If "Use OCR" is on, return a copy with a searchable text layer; else ``pdf``."""
    if not ctx.settings.use_ocr:
        return pdf
    searchable = work / "searchable.pdf"
    add_text_layer(pdf, searchable, work / "ocr", ctx, label)
    return searchable


def _output(name: str, path: Path) -> OutputFile:
    """Describe a finished output file."""
    with fitz.open(str(path)) as doc:
        pages = len(doc)
    return OutputFile(name, path, pages, path.stat().st_size)


def _merged_name(files: list[Path], suffix: str) -> str:
    """'<first> - <suffix>.pdf' or '<first> + N more - <suffix>.pdf'."""
    first = files[0].stem
    prefix = f"{first} + {len(files) - 1} more" if len(files) > 1 else first
    return f"{prefix} - {suffix}.pdf"


def _flatten_label(ctx: JobContext) -> str:
    return "Flattened Searchable" if ctx.settings.use_ocr else "Flattened"


def _flatten_each(files: list[Path], scratch: Path, ctx: JobContext) -> list[Path]:
    """Prepare and flatten every input; return the flattened PDFs in order."""
    flattened = []
    for index, source in enumerate(files, 1):
        ctx.file_index = index
        work = scratch / f"item_{index:03d}"
        pdf = prepare_pdf(source, work, ctx)
        target = work / "flattened.pdf"
        flatten_pdf(pdf, target, work / "pages", ctx, source.name)
        flattened.append(target)
    return flattened


# --- One handler per action --------------------------------------------------------


def _flatten(files: list[Path], scratch: Path, ctx: JobContext) -> list[OutputFile]:
    ctx.begin_phase(0.0, 1.0, len(files))
    flattened = _flatten_each(files, scratch, ctx)
    label = _flatten_label(ctx)
    return [_output(f"{src.stem} - {label}.pdf", out) for src, out in zip(files, flattened)]


def _flatten_merge(files: list[Path], scratch: Path, ctx: JobContext) -> list[OutputFile]:
    ctx.begin_phase(0.0, 0.9, len(files))
    flattened = _flatten_each(files, scratch, ctx)
    ctx.begin_phase(0.9, 0.1, len(files))
    target = scratch / "merged.pdf"
    parts = [Part(src.stem, pdf) for src, pdf in zip(files, flattened)]
    merge_documents(parts, target, ctx, contents_page=ctx.settings.contents_page)
    return [_output(_merged_name(files, f"{_flatten_label(ctx)} Merged"), target)]


def _merge(files: list[Path], scratch: Path, ctx: JobContext) -> list[OutputFile]:
    ctx.begin_phase(0.0, 0.8 if ctx.settings.use_ocr else 0.5, len(files))
    parts = []
    for index, source in enumerate(files, 1):
        ctx.file_index = index
        work = scratch / f"item_{index:03d}"
        pdf = _with_ocr(prepare_pdf(source, work, ctx), work, ctx, source.name)
        parts.append(Part(source.stem, pdf))
    done = ctx.phase_start + ctx.phase_span
    ctx.begin_phase(done, 1.0 - done, len(files))
    target = scratch / "merged.pdf"
    merge_documents(parts, target, ctx, contents_page=ctx.settings.contents_page)
    return [_output(_merged_name(files, "Merged"), target)]


def _split(files: list[Path], scratch: Path, ctx: JobContext) -> list[OutputFile]:
    ctx.begin_phase(0.0, 1.0, len(files))
    outputs = []
    for index, source in enumerate(files, 1):
        ctx.file_index = index
        work = scratch / f"item_{index:03d}"
        pdf = _with_ocr(prepare_pdf(source, work, ctx), work, ctx, source.name)
        outputs += split_pdf(pdf, work / "parts", source.stem, ctx.settings.split, ctx)
    return outputs


def _images(files: list[Path], scratch: Path, ctx: JobContext) -> list[OutputFile]:
    ctx.begin_phase(0.0, 0.5 if ctx.settings.use_ocr else 1.0, len(files))
    outputs = images_to_pdf(files, scratch / "images", ctx.settings.combine_images, ctx)
    if not ctx.settings.use_ocr:
        return outputs
    ctx.begin_phase(0.5, 0.5, len(outputs))
    searchable = []
    for index, output in enumerate(outputs, 1):
        ctx.file_index = index
        work = scratch / f"ocr_{index:03d}"
        target = work / output.path.name
        add_text_layer(output.path, target, work / "pages", ctx, output.name)
        searchable.append(_output(output.name, target))
    return searchable


def _compress(files: list[Path], scratch: Path, ctx: JobContext) -> list[OutputFile]:
    ctx.begin_phase(0.0, 1.0, len(files))
    outputs = []
    for index, source in enumerate(files, 1):
        ctx.file_index = index
        check_pdf(source, source.name)
        target = scratch / f"item_{index:03d}" / "compressed.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        compress_pdf(source, target, ctx.settings.compress_level, ctx)
        outputs.append(_output(f"{source.stem} - Compressed.pdf", target))
    return outputs
