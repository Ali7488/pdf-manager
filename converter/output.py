"""Choosing collision-safe output filenames in the destination folder."""

from __future__ import annotations

from pathlib import Path


def safe_destination(folder: Path, proposed: str, reserved: set[str] | None = None) -> Path:
    """Pick an output path that won't overwrite anything.

    Tries ``proposed`` first, then ``name (2).pdf``, ``name (3).pdf`` and so on,
    until it finds a name that neither exists in ``folder`` nor has already
    been given to another file in the same save batch.

    Args:
        folder: Destination folder.
        proposed: Desired file name, e.g. ``"Report - Merged.pdf"``.
        reserved: Names already chosen in this batch, lower-cased. Pass the
            same set for every file in a batch; the chosen name is added to it.
            Names are compared case-insensitively, as on Windows.

    Returns:
        Full path to save to. The file itself is not created.

    Raises:
        RuntimeError: No free name was found (after 99,999 attempts).
    """
    reserved = set() if reserved is None else reserved
    requested = Path(proposed)
    for i in range(1, 100000):
        # i == 1 is the plain name; later attempts add " (i)" before the extension.
        filename = f"{requested.stem}{f' ({i})' if i > 1 else ''}{requested.suffix}"
        target = folder / filename
        if not target.exists() and filename.casefold() not in reserved:
            reserved.add(filename.casefold())
            return target
    raise RuntimeError("Could not choose a unique output filename.")
