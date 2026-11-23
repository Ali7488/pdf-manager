"""Loading, validating and saving the user's settings.

Settings are kept as the contract's camelCase ``Settings`` object (see
``frontend/src/api/types.ts``) in a small JSON file at
:func:`api.paths.settings_path`. A missing or damaged file never stops the
app: defaults are used and the problem is logged. Each field is validated on
its own, so one bad value only resets that field.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from converter.common import DPI, OCR_LANGUAGE, OCR_PAGE_TIMEOUT_SEC

log = logging.getLogger(__name__)

THEMES = ("system", "light", "dark", "burgundy", "green")
DPI_RANGE = (72, 600)  # Below 72 OCR is unreliable; above 600 files get huge and slow.
OCR_TIMEOUT_RANGE = (10, 3600)  # Seconds per page: 10 s to 1 hour.
# Tesseract language codes such as "eng", "chi_sim" or "eng+deu".
_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*$")

DEFAULTS: dict[str, Any] = {
    "theme": "system",  # Follows the Windows light/dark setting (decision F27).
    "defaultSaveFolder": None,
    "dpi": DPI,
    "ocrLanguage": OCR_LANGUAGE,
    "ocrPageTimeoutSec": OCR_PAGE_TIMEOUT_SEC,  # Decision C5: 2 minutes per page.
    "tesseractPath": None,
}


class InvalidSetting(ValueError):
    """A settings value has the wrong type or is out of range."""


def _int_in(value: Any, low: int, high: int) -> int:
    """Accept a whole number within ``[low, high]``.

    Args:
        value: Candidate value from JSON (JavaScript numbers may arrive as floats).
        low: Smallest allowed value.
        high: Largest allowed value.

    Returns:
        The value as an int.

    Raises:
        InvalidSetting: Not a whole number, or out of range.
    """
    # bool is a subclass of int in Python; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidSetting(f"expected a whole number, got {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise InvalidSetting(f"expected a whole number, got {value!r}")
    number = int(value)
    if not low <= number <= high:
        raise InvalidSetting(f"{number} is outside {low}..{high}")
    return number


def _theme(value: Any) -> str:
    """Validate ``theme``. Raises InvalidSetting if it isn't a known scheme."""
    if value not in THEMES:
        raise InvalidSetting(f"unknown theme {value!r}")
    return value


def _optional_path(value: Any) -> str | None:
    """Validate an optional path (``defaultSaveFolder``, ``tesseractPath``).

    Empty strings are stored as ``None`` (not set). Raises InvalidSetting for
    non-strings.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidSetting(f"expected a path or null, got {value!r}")
    return value.strip() or None


def _language(value: Any) -> str:
    """Validate ``ocrLanguage``. Raises InvalidSetting for malformed codes."""
    if not isinstance(value, str) or not _LANGUAGE_RE.match(value.strip()):
        raise InvalidSetting(f"invalid OCR language {value!r}")
    return value.strip()


# One validator per field. Each returns the cleaned value or raises InvalidSetting.
VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "theme": _theme,
    "defaultSaveFolder": _optional_path,
    "dpi": lambda value: _int_in(value, *DPI_RANGE),
    "ocrLanguage": _language,
    "ocrPageTimeoutSec": lambda value: _int_in(value, *OCR_TIMEOUT_RANGE),
    "tesseractPath": _optional_path,
}


def validate_patch(patch: Any) -> tuple[dict[str, Any], list[str]]:
    """Split a (partial) settings object into valid values and problems.

    Args:
        patch: Object from the UI or from the settings file.

    Returns:
        ``(valid, problems)``: the cleaned values that passed, and one
        message per unknown key or invalid value (those are left out).
    """
    if not isinstance(patch, dict):
        return {}, [f"settings must be an object, got {type(patch).__name__}"]
    valid: dict[str, Any] = {}
    problems: list[str] = []
    for key, value in patch.items():
        validator = VALIDATORS.get(key)
        if validator is None:
            problems.append(f"unknown setting {key!r}")
            continue
        try:
            valid[key] = validator(value)
        except InvalidSetting as exc:
            problems.append(f"{key}: {exc}")
    return valid, problems


class SettingsStore:
    """The user's settings, in memory and on disk. Thread-safe.

    Args:
        path: The settings file. Its folder is created on the first save.
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._values: dict[str, Any] = copy.deepcopy(DEFAULTS)

    @property
    def path(self) -> Path:
        """The settings file."""
        return self._path

    def load(self) -> dict[str, Any]:
        """Read the settings file, falling back to defaults for anything unusable.

        A missing file is normal on first launch. A damaged file, or invalid
        values in it, are logged and replaced by defaults; the file itself is
        only rewritten on the next save.

        Returns:
            A copy of the full settings.
        """
        values = copy.deepcopy(DEFAULTS)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            log.info("No settings file yet at %s; using defaults", self._path)
            raw = {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("Settings file %s is unreadable, using defaults: %s", self._path, exc)
            raw = {}
        valid, problems = validate_patch(raw)
        for problem in problems:
            log.warning("Ignoring saved setting (%s): %s", self._path, problem)
        values.update(valid)
        with self._lock:
            self._values = values
        log.debug("Settings loaded: %s", values)
        return self.get()

    def get(self) -> dict[str, Any]:
        """Return a copy of the current settings (the contract's ``Settings``)."""
        with self._lock:
            return copy.deepcopy(self._values)

    def update(self, patch: Any) -> dict[str, Any]:
        """Merge a partial settings object, persist it and return the full settings.

        Invalid or unknown fields are skipped and logged; the rest is applied.
        If the file can't be written, the new values still apply for this
        session and the failure is logged.

        Args:
            patch: Partial ``Settings`` from the UI (camelCase keys).

        Returns:
            A copy of the full settings after the update.
        """
        valid, problems = validate_patch(patch)
        for problem in problems:
            log.warning("Ignoring setting from the UI: %s", problem)
        with self._lock:
            self._values.update(valid)
            snapshot = copy.deepcopy(self._values)
            try:
                self._write(snapshot)
            except OSError:
                log.exception("Couldn't save settings to %s", self._path)
        return snapshot

    def _write(self, values: dict[str, Any]) -> None:
        """Write the settings atomically: a temp file in the same folder, then replace.

        A crash or power cut mid-write leaves either the old file or the new
        one, never a half-written file.

        Args:
            values: Full settings to write.

        Raises:
            OSError: The folder or file couldn't be written.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=".settings-", suffix=".tmp", dir=self._path.parent
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(values, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            # Known issue: on Windows, replace can briefly fail if antivirus or
            # a backup tool has the file open; the error is logged by the caller.
            os.replace(temp_name, self._path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
