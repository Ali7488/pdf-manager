"""Shared constants and types used across the converter package."""

from __future__ import annotations

from collections.abc import Callable

DPI = 200
ALLOWED = {".pdf", ".pptx", ".ppt"}
FLATTEN = "flatten"
FLATTEN_MERGE = "flatten_merge"
MERGE = "merge"
MODES = {FLATTEN, FLATTEN_MERGE, MERGE}
Progress = Callable[[str], None]
