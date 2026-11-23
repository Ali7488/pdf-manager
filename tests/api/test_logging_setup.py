"""Tests for api.logging_setup: levels, the log file and issue logging."""

import logging
import sys

from api import logging_setup, paths
from converter.issues import powerpoint_fallback, unexpected_error


def test_dev_mode_from_source(monkeypatch):
    """Running from source is development mode."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert logging_setup.dev_mode()


def test_production_unless_debug_env(monkeypatch):
    """The installed app is production, unless PDF_MANAGER_DEBUG=1."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("PDF_MANAGER_DEBUG", raising=False)
    assert not logging_setup.dev_mode()
    monkeypatch.setenv("PDF_MANAGER_DEBUG", "1")
    assert logging_setup.dev_mode()


def test_dev_level_is_debug(logs):
    """Development mode logs at DEBUG level and writes the start record."""
    assert logging.getLogger().level == logging.DEBUG
    assert logs.name == "pdf-manager.log"
    text = logs.read_text(encoding="utf-8")
    assert "starting (development mode" in text
    assert "settings:" in text


def test_production_level_is_info(monkeypatch, tmp_path, logs):
    """Production logs at INFO; DEBUG records are dropped but errors are kept."""
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.delenv("PDF_MANAGER_DEBUG", raising=False)
    path = logging_setup.configure_logging()
    assert logging.getLogger().level == logging.INFO
    logging.getLogger("converter.tools").debug("verbose tool output")
    logging.getLogger("converter.tools").error("tool failed")
    text = path.read_text(encoding="utf-8")
    assert "production mode" in text
    assert "verbose tool output" not in text
    assert "tool failed" in text


def test_reconfigure_does_not_duplicate_handlers(logs):
    """Calling configure_logging twice replaces its handlers instead of adding more."""
    before = len(logging.getLogger().handlers)
    logging_setup.configure_logging()
    assert len(logging.getLogger().handlers) == before


def test_unwritable_logs_folder_falls_back(monkeypatch, tmp_path, logs):
    """If the logs folder can't be created, a temp folder is used instead."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    monkeypatch.setattr(paths, "logs_dir", lambda: blocker / "logs")
    monkeypatch.setattr(logging_setup.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    path = logging_setup.configure_logging()
    assert path == tmp_path / "tmp" / "pdf-manager-logs" / "pdf-manager.log"
    assert "not writable" in path.read_text(encoding="utf-8")


def test_log_issue_writes_details_and_traceback(logs):
    """log_issue records code, title, message, details and traceback, and sets logFile."""
    try:
        raise RuntimeError("boom inside the job")
    except RuntimeError as exc:
        issue = logging_setup.log_issue(unexpected_error("raw tool output"), exc)
    assert issue.log_file == str(logs)
    text = logs.read_text(encoding="utf-8")
    assert "ERROR" in text
    assert "Issue UNEXPECTED_ERROR: Something went wrong" in text
    assert "raw tool output" in text
    assert "Traceback" in text and "boom inside the job" in text


def test_log_issue_warning_level_and_file(logs):
    """Warnings are logged at WARNING level, with the file they are about."""
    issue = logging_setup.log_issue(powerpoint_fallback("Slides.pptx", None))
    text = logs.read_text(encoding="utf-8")
    assert "WARNING" in text and "File: Slides.pptx" in text
    assert issue.log_file == str(logs)


def test_log_issue_before_configuration(monkeypatch):
    """Without configured logging the issue is returned unchanged."""
    monkeypatch.setattr(logging_setup, "_log_file", None)
    issue = unexpected_error(None)
    assert logging_setup.log_issue(issue) is issue
