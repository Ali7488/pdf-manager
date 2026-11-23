"""Shared fixtures for the API-layer tests: isolated logs and a fake pywebview window."""

from __future__ import annotations

import json
import logging
import re
import threading

import pytest

from api import logging_setup, paths


@pytest.fixture
def logs(monkeypatch, tmp_path):
    """Configure logging into a temporary logs folder and undo it afterwards.

    Yields:
        The log file path.
    """
    monkeypatch.setattr(paths, "logs_dir", lambda: tmp_path / "logs")
    root = logging.getLogger()
    level = root.level
    path = logging_setup.configure_logging()
    yield path
    for handler in logging_setup._handlers:
        root.removeHandler(handler)
        handler.close()
    logging_setup._handlers.clear()
    monkeypatch.setattr(logging_setup, "_log_file", None)
    root.setLevel(level)


class FakeEvent:
    """Stands in for a pywebview window event (``window.events.loaded``)."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeEvents:
    """Stands in for ``window.events``."""

    def __init__(self):
        self.loaded = FakeEvent()
        self.closing = FakeEvent()
        self.closed = FakeEvent()


class FakeElementEvents:
    """Stands in for ``element.events``: records DOMEventHandler subscriptions by name."""

    def __init__(self):
        self.subscriptions: dict[str, list] = {}

    def __getattr__(self, name):
        holder = self

        class _Slot:
            def __iadd__(self, handler):
                holder.subscriptions.setdefault(name, []).append(handler)
                return self

        return _Slot()

    def __setattr__(self, name, value):
        # `events.drop += handler` assigns the slot back; ignore that.
        if name == "subscriptions":
            object.__setattr__(self, name, value)


class FakeElement:
    """Stands in for ``window.dom.document``."""

    def __init__(self):
        self.events = FakeElementEvents()


class FakeDom:
    """Stands in for ``window.dom``."""

    def __init__(self):
        self.document = FakeElement()


EVENT_RE = re.compile(
    r'^window\.dispatchEvent\(new CustomEvent\("pdfmanager:(\w+)", \{detail: (.*)\}\)\);$',
    re.S,
)


class FakeWindow:
    """A pywebview window replacement: records scripts and returns canned dialog results.

    Attributes:
        scripts: Every script passed to ``evaluate_js``, in order.
        dialog_results: Queue of values returned by ``create_file_dialog``.
        dialog_calls: The arguments of each ``create_file_dialog`` call.
    """

    def __init__(self):
        self.scripts: list[str] = []
        self.dialog_results: list = []
        self.dialog_calls: list[dict] = []
        self.events = FakeEvents()
        self.dom = FakeDom()
        self._lock = threading.Lock()

    def evaluate_js(self, script):
        """Record a script instead of running it."""
        with self._lock:
            self.scripts.append(script)

    def create_file_dialog(self, dialog_type=10, directory="", allow_multiple=False, **kwargs):
        """Return the next canned dialog result."""
        self.dialog_calls.append(
            {"type": dialog_type, "directory": directory, "multiple": allow_multiple, **kwargs}
        )
        return self.dialog_results.pop(0) if self.dialog_results else None

    def events_named(self, name):
        """Decode recorded ``pdfmanager:<name>`` events.

        Args:
            name: Event name, e.g. "jobFinished".

        Returns:
            The decoded ``detail`` payloads, in order.
        """
        found = []
        with self._lock:
            scripts = list(self.scripts)
        for script in scripts:
            match = EVENT_RE.match(script)
            if match and match.group(1) == name:
                found.append(json.loads(match.group(2)))
        return found


@pytest.fixture
def window():
    """A fresh :class:`FakeWindow`."""
    return FakeWindow()
