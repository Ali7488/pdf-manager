"""Choosing collision-safe output filenames in the destination folder."""

from __future__ import annotations

from pathlib import Path


def safe_destination(folder: Path, proposed: str, reserved: set[str] | None = None) -> Path:
    """Never overwrite existing files or collide with another result in this batch."""
    reserved = set() if reserved is None else reserved
    requested = Path(proposed)
    for i in range(1, 100000):
        filename = f"{requested.stem}{f' ({i})' if i > 1 else ''}{requested.suffix}"
        target = folder / filename
        if not target.exists() and filename.casefold() not in reserved:
            reserved.add(filename.casefold())
            return target
    raise RuntimeError("Could not choose a unique output filename.")
