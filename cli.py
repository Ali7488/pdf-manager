"""Command-line front end for testing PDF Manager without the window.

It calls the same service layer as the desktop app (``converter.run_action``,
``converter.check_tools``, ``converter.inspect_file``), so it exercises the real
conversion code on Windows and Linux. Results are saved with the same
never-overwrite rule as the app.

Usage (``uv run cli.py --help`` for everything)::

    uv run cli.py tools merge samples/05-slides.pptx --ocr
    uv run cli.py info samples/*.pdf
    uv run cli.py flatten samples/01-text-report.pdf --ocr --out out
    uv run cli.py merge a.pdf b.pptx --contents --out out
    uv run cli.py split samples/13-long-document.pdf --ranges "1-3, 5" --zip --out out
    uv run cli.py images photo.jpg diagram.png --separate --out out
    uv run cli.py compress big.pdf --level strong --out out

Exit codes: 0 success, 1 conversion failed (the issue is printed), 2 bad
arguments or tools missing, 130 cancelled with Ctrl+C.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

from converter import (
    Action,
    ActionData,
    ActionSettings,
    Cancelled,
    CancelToken,
    CompressLevel,
    ConversionError,
    Issue,
    ProgressEvent,
    SplitMethod,
    check_tools,
    inspect_file,
    run_action,
    safe_destination,
)

# Command names → actions. Hyphenated names read better on a command line.
ACTIONS = {
    "flatten": Action.FLATTEN,
    "flatten-merge": Action.FLATTEN_MERGE,
    "merge": Action.MERGE,
    "split": Action.SPLIT,
    "images": Action.IMAGES_TO_PDF,
    "compress": Action.COMPRESS,
}


def build_settings(args: argparse.Namespace) -> ActionSettings:
    """Turn command-line options into the job's settings (same fields the UI sends)."""
    settings = ActionSettings(
        use_ocr=args.ocr,
        contents_page=args.contents,
        combine_images=not args.separate,
        compress_level=CompressLevel(args.level),
        dpi=args.dpi,
        ocr_language=args.lang,
        ocr_page_timeout_sec=args.ocr_timeout,
        tesseract_path=args.tesseract,
    )
    if args.every:
        settings.split.method, settings.split.every_n = SplitMethod.EVERY_N, args.every
    elif args.per_page:
        settings.split.method = SplitMethod.PER_PAGE
    else:
        settings.split.method, settings.split.ranges = SplitMethod.RANGES, args.ranges or ""
    return settings


def format_issue(issue: Issue) -> str:
    """An issue as plain text: title, message, numbered steps, command and log file."""
    lines = [f"[{issue.severity.value.upper()}] {issue.code.value}: {issue.title}", issue.message]
    lines += [f"  {n}. {step}" for n, step in enumerate(issue.troubleshooting, 1)]
    if issue.command:
        lines.append(f"  Command: {issue.command}")
    if issue.details:
        lines.append("  Details: " + issue.details.strip().replace("\n", "\n           "))
    return "\n".join(lines)


def print_progress(event: ProgressEvent) -> None:
    """One progress line on stderr, overwriting the previous one in a terminal."""
    end = "\r" if sys.stderr.isatty() else "\n"
    sys.stderr.write(f"{event.fraction * 100:5.1f}%  {event.message:<70.70}{end}")
    sys.stderr.flush()


def save_outputs(outputs, folder: Path, as_zip: bool, zip_name: str) -> list[Path]:
    """Copy results out of scratch into ``folder`` without overwriting anything.

    Args:
        outputs: ``OutputFile`` list from the job.
        folder: Destination; created if missing.
        as_zip: Save everything as one zip instead of separate files.
        zip_name: Suggested zip file name.

    Returns:
        Paths written.
    """
    folder.mkdir(parents=True, exist_ok=True)
    taken: set[str] = set()
    if as_zip:
        target = safe_destination(folder, zip_name, taken)
        with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
            names: set[str] = set()
            for output in outputs:
                name = output.name
                stem, suffix, n = Path(name).stem, Path(name).suffix, 2
                while name.casefold() in names:  # Same name twice inside one zip.
                    name, n = f"{stem} ({n}){suffix}", n + 1
                names.add(name.casefold())
                archive.write(output.path, name)
        return [target]
    saved = []
    for output in outputs:
        target = safe_destination(folder, output.name, taken)
        shutil.copyfile(output.path, target)
        saved.append(target)
    return saved


def command_run(args: argparse.Namespace) -> int:
    """Run one action and save its outputs."""
    action = ACTIONS[args.command]
    settings = build_settings(args)
    files = [Path(f) for f in args.files]
    cancel = CancelToken()
    with tempfile.TemporaryDirectory(prefix="pdf-manager-cli-", ignore_cleanup_errors=True) as tmp:
        result: dict = {}

        def work() -> None:
            try:
                result["job"] = run_action(
                    action,
                    settings,
                    ActionData(files),
                    scratch=Path(tmp),
                    progress=None if args.quiet else print_progress,
                    cancel=cancel,
                )
            except BaseException as exc:  # Reported on the main thread below.
                result["error"] = exc

        # Run on a worker so Ctrl+C on the main thread can cancel the job cleanly.
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                worker.join(0.2)
        except KeyboardInterrupt:
            cancel.cancel()
            worker.join()
        if not args.quiet:
            sys.stderr.write("\n")

        error = result.get("error")
        if isinstance(error, Cancelled):
            print("Cancelled. Nothing was saved.")
            return 130
        if isinstance(error, ConversionError):
            print(format_issue(error.issue))
            return 1
        if error is not None:
            raise error
        job = result["job"]
        zip_name = f"{files[0].stem} - {args.command.replace('-', ' ').title()}.zip"
        saved = save_outputs(job.outputs, Path(args.out), args.zip, zip_name)

    if args.json:
        print(
            json.dumps(
                {
                    "outputs": [
                        {"name": o.name, "pages": o.page_count, "bytes": o.size_bytes}
                        for o in job.outputs
                    ],
                    "saved": [str(p) for p in saved],
                    "warnings": [w.code.value for w in job.warnings],
                },
                indent=2,
            )
        )
    else:
        for output in job.outputs:
            print(f"{output.name}: {output.page_count} page(s), {output.size_bytes:,} bytes")
        print("Saved:", *saved, sep="\n  ")
        for warning in job.warnings:
            print(format_issue(warning))
    return 0


def command_tools(args: argparse.Namespace) -> int:
    """Run the Convert modal's tool check for an action and files."""
    action = ACTIONS[args.action]
    settings = ActionSettings(use_ocr=args.ocr, tesseract_path=args.tesseract)
    check = check_tools(action, settings, ActionData([Path(f) for f in args.files]))
    for name in ("ocr", "powerpoint", "libreoffice"):
        status = getattr(check, name)
        need = "needed" if status.required else "not needed"
        found = f"found: {status.path}" if status.present else "not found"
        print(f"{name:<12} {need:<11} {found}")
    for issue in check.issues:
        print(format_issue(issue))
    print("OK: the job can start." if check.ok else "BLOCKED: fix the issues above first.")
    return 0 if check.ok else 2


def command_info(args: argparse.Namespace) -> int:
    """Describe files the way the app's file list does."""
    status = 0
    for name in args.files:
        info = inspect_file(Path(name))
        if info is None:
            print(f"{name}: not supported or not found")
            status = 2
            continue
        pages = "?" if info.page_count is None else info.page_count
        print(f"{info.name}: {info.kind.value}, {info.size_bytes:,} bytes, pages: {pages}")
    return status


def build_parser() -> argparse.ArgumentParser:
    """The command-line interface: one sub-command per action, plus ``tools`` and ``info``."""
    parser = argparse.ArgumentParser(
        prog="cli.py", description="PDF Manager from the command line (for testing)."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging to stderr.")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, action in ACTIONS.items():
        p = sub.add_parser(name, help=f"Run the {action.value} action.")
        p.add_argument("files", nargs="+", help="Input files, in order.")
        p.add_argument("--out", default="out", help="Folder to save results in (default: out).")
        p.add_argument("--ocr", action="store_true", help="Use OCR (Tesseract).")
        p.add_argument("--dpi", type=int, default=200, help="Render resolution (default 200).")
        p.add_argument("--lang", default="eng", help="OCR language code (default eng).")
        p.add_argument("--ocr-timeout", type=int, default=120, help="Seconds per OCR page.")
        p.add_argument("--tesseract", help="Path to the Tesseract executable.")
        p.add_argument("--contents", action="store_true", help="Merge: add a contents page.")
        p.add_argument("--ranges", help='Split: page ranges, e.g. "1-3, 5, 8-10".')
        p.add_argument("--every", type=int, help="Split: every N pages.")
        p.add_argument("--per-page", action="store_true", help="Split: one file per page.")
        p.add_argument("--separate", action="store_true", help="Images: one PDF per image.")
        p.add_argument(
            "--level",
            choices=[level.value for level in CompressLevel],
            default=CompressLevel.BALANCED.value,
            help="Compress level (default balanced).",
        )
        p.add_argument("--zip", action="store_true", help="Save all outputs as one zip.")
        p.add_argument("--json", action="store_true", help="Print a JSON summary.")
        p.add_argument("-q", "--quiet", action="store_true", help="No progress output.")
        p.set_defaults(handler=command_run)

    p = sub.add_parser("tools", help="Check which programs an action needs and whether present.")
    p.add_argument("action", choices=list(ACTIONS))
    p.add_argument("files", nargs="*", help="Input files (PowerPoint files need a renderer).")
    p.add_argument("--ocr", action="store_true", help="Check for OCR too.")
    p.add_argument("--tesseract", help="Path to the Tesseract executable.")
    p.set_defaults(handler=command_tools)

    p = sub.add_parser("info", help="Describe files like the app's file list.")
    p.add_argument("files", nargs="+")
    p.set_defaults(handler=command_info)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the chosen command; returns the exit code."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
