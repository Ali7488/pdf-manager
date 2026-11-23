"""Download the third-party source code for a release, so it can be attached to it.

    uv run scripts/collect_sources.py build/sources --platform windows
    uv run scripts/collect_sources.py build/sources-browser --platform windows --build browser

The AGPL-3.0 (section 6) requires the complete corresponding source of the app to be
available to everyone who gets the installer. The app's own code, UI and build scripts
are archived from the exact commit being built (``git archive``; the same commit the
app's Settings > About links to, decision P37), with that commit in ``SOURCE_REVISION``.
The checkout must have no changes to tracked files. This script gathers the rest, from
the exact versions listed in ``licenses/manifest.json`` (which
``scripts/collect_licenses.py`` takes from ``uv.lock`` and ``frontend/package-lock.json``):

* each bundled Python package's source distribution (checked against uv.lock's hash),
  or its upstream source archive when it publishes none (pywin32);
* MuPDF's source release (PyMuPDF's own source distribution doesn't contain it);
* the CPython source release of the bundled interpreter;
* the PyInstaller source distribution (its bootloader is in the app's .exe);
* each interface package's npm tarball (checked against package-lock.json's integrity).

It writes ``SOURCES.md`` (what each file is and where it came from) and ``SHA256SUMS``
into the output folder. Any download or checksum failure fails the script, so a
missing source archive stops the release. The Microsoft WebView2 SDK files have no
published source; SOURCES.md says so (see docs/LICENSING_AUDIT_2026-11-23.md).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "licenses" / "manifest.json"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def app_source(out: Path) -> tuple[str, Path]:
    """Archive the app's own source at the checked-out commit.

    Returns:
        The commit and the archive (``app/pdf-manager-<commit>-source.tar.gz``).

    Raises:
        SystemExit: Not a clean Git checkout, or not the commit
            ``PDF_MANAGER_SOURCE_REVISION`` names (CI sets it to the commit it builds).
    """
    try:
        revision = _git("rev-parse", "HEAD")
        changes = _git("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"The app's source needs a Git checkout: {exc}") from exc
    if changes:
        raise SystemExit("Tracked files differ from the commit; the source wouldn't match it.")
    expected = os.environ.get("PDF_MANAGER_SOURCE_REVISION", "").strip().lower()
    if expected and expected != revision:
        raise SystemExit(f"PDF_MANAGER_SOURCE_REVISION is {expected}, the checkout {revision}.")
    folder = out / "app"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"pdf-manager-{revision}-source.tar.gz"
    _git(
        "archive",
        "--format=tar.gz",
        f"--prefix=pdf-manager-{revision}/",
        "-o",
        str(archive),
        "HEAD",
    )
    (out / "SOURCE_REVISION").write_text(revision + "\n", encoding="ascii")
    return revision, archive


def fetch(url: str, folder: Path, sha256: str = "", integrity: str = "") -> Path:
    """Download ``url`` into ``folder`` and verify the given checksum.

    Raises:
        SystemExit: The download failed or the checksum doesn't match.
    """
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if "github.com" in url and "/archive/" in url:
        repo = url.split("github.com/", 1)[1].split("/")[1]
        name = f"{repo}-{name}"
    path = folder / name
    if not path.is_file():
        print(f"  downloading {url}")
        try:
            with urllib.request.urlopen(url, timeout=600) as response:
                path.write_bytes(response.read())
        except OSError as exc:
            raise SystemExit(f"Couldn't download {url}: {exc}") from exc
    data = path.read_bytes()
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        path.unlink()
        raise SystemExit(f"SHA-256 mismatch for {url}")
    if integrity:
        algorithm, _, expected = integrity.partition("-")
        if base64.b64encode(hashlib.new(algorithm, data).digest()).decode() != expected:
            path.unlink()
            raise SystemExit(f"Integrity mismatch for {url}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--platform", choices=["windows", "linux"], required=True)
    parser.add_argument(
        "--build",
        choices=["desktop", "browser"],
        default="desktop",
        help="the desktop installer's app, or the browser-mode ZIP (a subset)",
    )
    args = parser.parse_args(argv)
    if args.platform == "linux":
        # The manifest pins the python.org Windows CPython release; the Linux build's
        # interpreter isn't settled until the Linux packages exist (v0.75). Refuse rather
        # than gather the wrong runtime's source.
        raise SystemExit(
            "No Linux build yet: its Python runtime's source isn't pinned (see LICENSING.md)."
        )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = manifest["sources"]
    shipped = {
        c["name"].lower()
        for c in manifest["components"]
        if args.build in c.get("builds", ["desktop", "browser"])
    }
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    revision, archive = app_source(out)
    print(f"App source: commit {revision}")
    rows: list[tuple[str, str, str]] = []

    def add(component: str, url: str, path: Path) -> None:
        rows.append((component, url, path.relative_to(out).as_posix()))

    for kind in ("python", "frontend", "other"):
        (out / kind).mkdir(parents=True, exist_ok=True)
    print("Python packages")
    for s in sources["python"]:
        if args.platform not in s["platforms"] or s["component"].lower() not in shipped:
            continue
        for url in s["url"].split(" and "):
            add(f"{s['component']} {s['version']}", url, fetch(url, out / "python", s["sha256"]))
    print("Interface packages")
    for s in sources["frontend"]:
        path = fetch(s["url"], out / "frontend", integrity=s["integrity"])
        add(f"{s['component']} {s['version']}", s["url"], path)
    print("MuPDF, CPython and PyInstaller")
    mupdf = sources["mupdf"]
    add(
        f"MuPDF {manifest['mupdf']}",
        mupdf["url"],
        fetch(mupdf["url"], out / "other", mupdf["sha256"]),
    )
    runtime = sources["python_runtime"]
    add(
        f"CPython {manifest['python_windows']}",
        runtime["url"],
        fetch(runtime["url"], out / "other", runtime["sha256"]),
    )
    pyinstaller = sources["pyinstaller"]
    add(
        f"PyInstaller {manifest['pyinstaller']}",
        pyinstaller["url"],
        fetch(pyinstaller["url"], out / "other", pyinstaller["sha256"]),
    )

    sums = []
    for path in sorted(
        p for p in out.rglob("*") if p.is_file() and p.name not in ("SHA256SUMS", "SOURCES.md")
    ):
        sums.append(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(out).as_posix()}"
        )
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    lines = [
        "# PDF Manager: corresponding source code",
        "",
        f"**The app's own source:** `{archive.relative_to(out).as_posix()}`, an archive of "
        f"commit `{revision}` (also in `SOURCE_REVISION`), the commit the "
        f"{'browser-mode ZIP' if args.build == 'browser' else 'app'} was built from. Its "
        "Settings > About links to the same commit: "
        f"https://github.com/Ali7488/pdf-manager/tree/{revision}",
        "",
        f"Source code of the third-party components in the {args.platform.capitalize()} "
        f"{'browser-mode ZIP' if args.build == 'browser' else 'app'}, "
        "at the exact bundled versions. Checksums: SHA256SUMS.",
        "",
        "| Component | File | Downloaded from |",
        "| --- | --- | --- |",
        *[f"| {c} | `{f}` | {u} |" for c, u, f in rows],
        "",
    ]
    lines += [
        "**Provenance note:** pywin32 b312 is fetched by its pinned upstream "
        "Git commit (2a277cb5552756c2b4d42b524dc36d25e0bb6354). "
        "The other listed Windows Python and runtime "
        "source archives use their pinned SHA-256 digests; npm archives use the "
        "lockfile integrity values. The generated SHA256SUMS records every "
        "downloaded file, but does not independently authenticate an upstream "
        "archive that has no pre-published digest.",
        "",
    ]
    if args.build == "desktop":
        lines += [
            "**Not included:** the Microsoft WebView2 SDK files inside pywebview "
            f"(Microsoft.Web.WebView2 {manifest['webview2_sdk']['version']}). Microsoft "
            "licenses them under BSD-3-Clause-style terms but publishes no source code; "
            "see LICENSING.md.",
            "",
        ]
    (out / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(rows)} source archives in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
