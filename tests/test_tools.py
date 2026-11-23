"""Unit tests for converter.tools: registry path parsing and cancellable commands."""

from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from converter.context import CancelToken
from converter.issues import Cancelled
from converter.tools import exe_from_registry_value, run_command


@pytest.mark.parametrize(
    "value",
    [
        r"C:\Tools\tesseract.exe",
        r'"C:\Tools\tesseract.exe",0',
        r"C:\Tools\tesseract.exe,0",
        r"C:\Tools\tesseract.exe, -101",
        r'"C:\Tools\tesseract.exe"',
        r"C:\Tools",
    ],
)
def test_registry_values_resolve_to_the_exe(value):
    path = str(exe_from_registry_value(value))
    # On Linux the Windows separators stay inside one path component; only the
    # final text matters.
    assert path.replace("/", "\\").endswith(r"C:\Tools\tesseract.exe")


def test_registry_value_expands_environment_variables(monkeypatch):
    monkeypatch.setenv("PDFM_TEST_ROOT", "X")
    assert str(exe_from_registry_value("$PDFM_TEST_ROOT")).startswith("X")
    if sys.platform == "win32":  # %VAR% is only expanded by Windows path rules.
        assert str(exe_from_registry_value("%PDFM_TEST_ROOT%")).startswith("X")


SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


def test_run_command_captures_output():
    proc = run_command([sys.executable, "-c", "print('hello')"], timeout=30)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "hello"


def test_run_command_times_out_and_kills_the_program():
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_command(SLEEP, timeout=0.5)
    assert time.monotonic() - started < 10


def test_cancel_stops_a_running_program_quickly():
    token = CancelToken()
    threading.Timer(0.3, token.cancel).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_command(SLEEP, timeout=60, cancel=token)
    assert time.monotonic() - started < 10


def test_cancel_before_start_kills_immediately():
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        run_command(SLEEP, timeout=60, cancel=token)


def test_timeout_kills_child_processes_too(tmp_path):
    # A parent that starts a child which would write a file after 3 seconds.
    marker = tmp_path / "child-survived"
    child = f"import time, pathlib; time.sleep(3); pathlib.Path({str(marker)!r}).touch()"
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_command([sys.executable, "-c", parent], timeout=1)
    time.sleep(4)
    assert not marker.exists(), "child process outlived the timeout"
