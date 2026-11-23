"""Shared constants and types used across the converter package."""

from __future__ import annotations

from collections.abc import Callable

# Resolution used when rendering each page to an image for flattening.
# Higher values give sharper pages and better OCR, but larger files and slower runs.
DPI = 200

# File extensions the converter accepts as input (compared lower-case).
ALLOWED = {".pdf", ".pptx", ".ppt"}

# Conversion modes:
#   FLATTEN        - one flattened, OCR-searchable PDF per input file.
#   FLATTEN_MERGE  - flatten every input, then merge them into a single PDF.
#   MERGE          - merge inputs as they are, keeping their original text layer.
FLATTEN = "flatten"
FLATTEN_MERGE = "flatten_merge"
MERGE = "merge"
MODES = {FLATTEN, FLATTEN_MERGE, MERGE}

# Progress callback: receives a short human-readable status message.
# The GUI passes a function that forwards these messages to the status line.
Progress = Callable[[str], None]
