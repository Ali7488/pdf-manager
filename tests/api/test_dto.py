"""Tests for api.dto: camelCase JSON <-> service-layer dataclasses."""

import dataclasses
import json
from pathlib import Path

import pytest

from api import dto
from api.service import (
    Action,
    CompressLevel,
    ConversionError,
    FileInfo,
    FileKind,
    IssueCode,
    OutputFile,
    ProgressEvent,
    SplitMethod,
    Stage,
    ToolCheck,
    ToolStatus,
    ocr_missing,
)
from api.settings_store import DEFAULTS

FRONTEND_SETTINGS = {
    "useOcr": True,
    "contentsPage": True,
    "split": {"method": "every_n", "ranges": "1-3, 5", "everyN": 4},
    "combineImages": False,
    "compressLevel": "strong",
}


def expect_invalid(call, *args):
    """Assert a call raises ConversionError with an UNEXPECTED_ERROR issue; return its details."""
    with pytest.raises(ConversionError) as info:
        call(*args)
    assert info.value.issue.code == IssueCode.UNEXPECTED_ERROR
    return info.value.issue.details


def test_action_settings_from_json_merges_saved_settings():
    """Per-job options and saved settings combine into one ActionSettings."""
    saved = dict(DEFAULTS, dpi=300, ocrLanguage="eng+deu", tesseractPath="C:\\t\\tesseract.exe")
    settings = dto.action_settings_from_json(FRONTEND_SETTINGS, saved)
    assert settings.use_ocr and settings.contents_page
    assert settings.split.method is SplitMethod.EVERY_N
    assert settings.split.ranges == "1-3, 5"
    assert settings.split.every_n == 4
    assert settings.combine_images is False
    assert settings.compress_level is CompressLevel.STRONG
    assert settings.dpi == 300
    assert settings.ocr_language == "eng+deu"
    assert settings.ocr_page_timeout_sec == 120
    assert settings.tesseract_path == "C:\\t\\tesseract.exe"


def test_action_settings_round_trip():
    """The per-job part converts back to the same frontend object."""
    settings = dto.action_settings_from_json(FRONTEND_SETTINGS, DEFAULTS)
    assert dto.action_settings_to_json(settings) == FRONTEND_SETTINGS


def test_missing_fields_use_defaults():
    """An empty settings object gives the service defaults (OCR off)."""
    settings = dto.action_settings_from_json({}, DEFAULTS)
    assert settings.use_ocr is False
    assert settings.split.method is SplitMethod.RANGES
    assert settings.compress_level is CompressLevel.BALANCED


def test_every_n_accepts_whole_float():
    """JavaScript may send 2 as 2.0."""
    value = dict(FRONTEND_SETTINGS, split={"method": "every_n", "ranges": "", "everyN": 2.0})
    assert dto.action_settings_from_json(value, DEFAULTS).split.every_n == 2


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"compressLevel": "extreme"}, "settings.compressLevel"),
        ({"split": {"method": "halves"}}, "settings.split.method"),
        ({"split": {"everyN": 0}}, "everyN"),
        ({"split": {"everyN": True}}, "everyN"),
        ({"split": {"ranges": 5}}, "ranges"),
        ({"split": "all"}, "settings.split"),
        ({"useOcr": "yes"}, "settings.useOcr"),
    ],
)
def test_invalid_action_settings(change, needle):
    """Invalid values become an UNEXPECTED_ERROR issue naming the field."""
    details = expect_invalid(dto.action_settings_from_json, dict(FRONTEND_SETTINGS, **change), {})
    assert needle in details


def test_settings_must_be_object():
    """A non-object settings argument is rejected."""
    assert "settings must be an object" in expect_invalid(
        dto.action_settings_from_json, None, DEFAULTS
    )


def test_parse_action():
    """Actions are parsed into the enum; unknown ones are rejected."""
    assert dto.parse_action("images_to_pdf") is Action.IMAGES_TO_PDF
    assert "action must be one of" in expect_invalid(dto.parse_action, "rotate")
    expect_invalid(dto.parse_action, None)


def test_action_data():
    """data.files becomes a list of Paths in the same order."""
    data = dto.action_data_from_json({"files": ["C:\\b.pdf", "C:\\a.pdf"]})
    assert data.files == [Path("C:\\b.pdf"), Path("C:\\a.pdf")]
    expect_invalid(dto.action_data_from_json, {"files": "C:\\a.pdf"})
    expect_invalid(dto.action_data_from_json, {"files": [1]})
    expect_invalid(dto.action_data_from_json, {})


def test_parse_save_options():
    """SaveOptions: folder or null, and asZip."""
    assert dto.parse_save_options({"folder": None, "asZip": False}) == (None, False)
    assert dto.parse_save_options({"folder": "/out", "asZip": True}) == (Path("/out"), True)
    expect_invalid(dto.parse_save_options, {"folder": 3, "asZip": False})
    expect_invalid(dto.parse_save_options, {"folder": None, "asZip": "yes"})


def test_parse_job_id():
    """Job ids must be non-empty strings."""
    assert dto.parse_job_id("abc") == "abc"
    expect_invalid(dto.parse_job_id, "")
    expect_invalid(dto.parse_job_id, 5)


def test_issue_to_json():
    """Issues use camelCase keys and a troubleshooting list."""
    issue = ocr_missing().with_log_file("/logs/pdf-manager.log")
    result = dto.issue_to_json(issue)
    assert result == {
        "code": "OCR_MISSING",
        "severity": "error",
        "title": issue.title,
        "message": issue.message,
        "troubleshooting": list(issue.troubleshooting),
        "details": None,
        "logFile": "/logs/pdf-manager.log",
        "command": None,
        "file": None,
    }
    assert isinstance(result["troubleshooting"], list)
    json.dumps(result)  # Must be JSON-serializable.


def test_issue_to_json_sends_command():
    """An issue's copyable command is sent as ``command`` (decision C16)."""
    issue = dataclasses.replace(ocr_missing(), command="sudo apt install tesseract-ocr")
    assert dto.issue_to_json(issue)["command"] == "sudo apt install tesseract-ocr"


def test_every_issue_in_results_carries_command():
    """Issues nested in other results have the ``command`` key too (null when absent)."""
    issue = ocr_missing()
    check = ToolCheck(
        ok=False,
        ocr=ToolStatus(True, False, None),
        libreoffice=ToolStatus(False, False, None),
        issues=[issue],
    )
    nested = [
        dto.tool_check_to_json(check)["issues"][0],
        dto.save_settings_json(dict(DEFAULTS), issue)["issue"],
        dto.save_outcome_json(issue=issue)["issue"],
        dto.failed_tool_check_json(issue)["issues"][0],
    ]
    assert all("command" in value and value["command"] is None for value in nested)


def test_input_file_to_json():
    """FileInfo becomes the contract's InputFile."""
    info = FileInfo(Path("/docs/Report.pdf"), "Report.pdf", FileKind.PDF, 1234, 7)
    assert dto.input_file_to_json(info) == {
        "path": str(Path("/docs/Report.pdf")),
        "name": "Report.pdf",
        "kind": "pdf",
        "sizeBytes": 1234,
        "pageCount": 7,
    }


def test_progress_to_json_adds_job_id_and_clamps():
    """ProgressEvent becomes JobProgress with the job id; fraction is clamped."""
    event = ProgressEvent(Stage.OCR, 2, 3, 4, 10, 1.2, "Reading text: page 4 of 10")
    assert dto.progress_to_json("job1", event) == {
        "jobId": "job1",
        "stage": "ocr",
        "fileIndex": 2,
        "fileCount": 3,
        "page": 4,
        "pageCount": 10,
        "fraction": 1.0,
        "message": "Reading text: page 4 of 10",
    }


def test_progress_nan_fraction_becomes_zero():
    """A NaN fraction (not valid JSON) is sent as 0."""
    event = ProgressEvent(Stage.OCR, 1, 1, None, None, float("nan"), "Working")
    assert dto.progress_to_json("job1", event)["fraction"] == 0.0


def test_output_to_json_hides_scratch_path():
    """Outputs don't reveal the scratch path."""
    output = OutputFile("Report - Flattened.pdf", Path("/tmp/x.pdf"), 3, 999)
    assert dto.output_to_json(output) == {
        "name": "Report - Flattened.pdf",
        "sizeBytes": 999,
        "pageCount": 3,
    }


def test_tool_check_to_json():
    """ToolCheck becomes ToolCheckResult with string paths."""
    check = ToolCheck(
        False,
        ToolStatus(True, False, None),
        ToolStatus(True, True, Path("/apps/soffice")),
        [ocr_missing()],
    )
    result = dto.tool_check_to_json(check)
    assert result["ok"] is False
    assert result["ocr"] == {"required": True, "present": False, "path": None}
    assert result["libreoffice"]["path"] == str(Path("/apps/soffice"))
    assert "powerpoint" not in result
    assert [i["code"] for i in result["issues"]] == ["OCR_MISSING"]
    json.dumps(result)


def test_job_finished_json_only_sends_outputs_on_success():
    """Outputs are empty unless the job succeeded."""
    output = OutputFile("a.pdf", Path("/tmp/a.pdf"), 1, 10)
    assert dto.job_finished_json("j", "succeeded", [output], [], None)["outputs"] == [
        {"name": "a.pdf", "sizeBytes": 10, "pageCount": 1}
    ]
    failed = dto.job_finished_json("j", "failed", [output], [], ocr_missing())
    assert failed["outputs"] == [] and failed["error"]["code"] == "OCR_MISSING"


def test_save_outcome_json():
    """SaveOutcome uses string paths."""
    outcome = dto.save_outcome_json(saved=[Path("/out/a.pdf")], folder=Path("/out"))
    assert outcome == {
        "cancelled": False,
        "savedPaths": [str(Path("/out/a.pdf"))],
        "folder": str(Path("/out")),
        "issue": None,
    }
