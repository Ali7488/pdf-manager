"""Copy the licence files a build must carry next to its app folder.

    uv run scripts/stage_licenses.py "dist/PDF Manager (browser)" --build browser

The desktop installer copies them itself (packaging/installer.iss). The
browser-mode ZIP has no installer, so its build runs this: the project's
licences, the build's own third-party notices (as THIRD_PARTY_NOTICES.md) and
the licence text of every component in ``licenses/manifest.json`` that the
build ships, and nothing else. ``scripts/check_licenses.py bundle --installed
--build <build>`` then checks the result byte for byte.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_licenses  # noqa: E402

ROOT = check_licenses.ROOT


def stage(app: Path, build: str) -> int:
    """Copy the files; returns how many licence texts were copied."""
    top = check_licenses.BROWSER_TOP_LEVEL if build == "browser" else check_licenses.TOP_LEVEL
    for source, name in top.items():
        shutil.copyfile(ROOT / source, app / name)
    shutil.rmtree(app / "licenses", ignore_errors=True)
    files = check_licenses.licence_files(check_licenses.load_manifest(), build)
    for relative in files:
        target = app / "licenses" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "licenses" / relative, target)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("app", type=Path)
    parser.add_argument("--build", choices=check_licenses.BUILDS, required=True)
    args = parser.parse_args(argv)
    count = stage(args.app, args.build)
    print(f"Copied the licences and {count} licence texts into {args.app}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
