"""Problems shown to the user, with plain-language troubleshooting steps.

Every error or warning the user may see is an :class:`Issue`. The wording lives
here, in one place, so the frontend only has to display it. Fatal problems are
raised as :class:`ConversionError` (which carries an Issue); non-fatal ones are
collected as warnings on the job.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"  # The job or action failed.
    WARNING = "warning"  # It worked, but something needs attention.


class IssueCode(StrEnum):
    """Stable codes; must match ``IssueCode`` in ``frontend/src/api/types.ts``."""

    OCR_MISSING = "OCR_MISSING"
    OCR_FAILED = "OCR_FAILED"
    OCR_TIMEOUT = "OCR_TIMEOUT"
    OCR_INSTALL_FAILED = "OCR_INSTALL_FAILED"
    POWERPOINT_CONVERSION_FAILED = "POWERPOINT_CONVERSION_FAILED"
    SLIDE_RENDERER_MISSING = "SLIDE_RENDERER_MISSING"
    PASSWORD_PROTECTED = "PASSWORD_PROTECTED"
    EMPTY_PDF = "EMPTY_PDF"
    UNREADABLE_FILE = "UNREADABLE_FILE"
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"
    INVALID_PAGE_RANGES = "INVALID_PAGE_RANGES"
    FLATTEN_CHECK_FAILED = "FLATTEN_CHECK_FAILED"
    MERGE_FAILED = "MERGE_FAILED"
    SAVE_FAILED = "SAVE_FAILED"
    SETTINGS_SAVE_FAILED = "SETTINGS_SAVE_FAILED"
    JOB_ALREADY_RUNNING = "JOB_ALREADY_RUNNING"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


@dataclass(frozen=True)
class Issue:
    """A problem described for a non-technical user.

    Attributes:
        code: Stable identifier the frontend can branch on.
        severity: Error (failed) or warning (worked, with a caveat).
        title: Short, plain-language headline.
        message: One or two plain sentences.
        troubleshooting: A few simple steps for the likely cause.
        details: Raw technical text for a "Show details" section, if any.
        file: Name of the input file this is about, if any.
        log_file: Log file holding the full record; filled in when logged.
        command: A command the user can copy and run themselves (e.g. a Linux
            package install), shown with a Copy button; the app never runs it.
    """

    code: IssueCode
    severity: Severity
    title: str
    message: str
    troubleshooting: tuple[str, ...] = field(default_factory=tuple)
    details: str | None = None
    file: str | None = None
    log_file: str | None = None
    command: str | None = None

    def with_log_file(self, path: str) -> Issue:
        """Return a copy pointing at the log file it was written to."""
        return replace(self, log_file=path)


class ConversionError(Exception):
    """A fatal problem that stops the job. Carries the Issue to show the user."""

    def __init__(self, issue: Issue):
        super().__init__(issue.message)
        self.issue = issue


class Cancelled(Exception):
    """Raised inside a job when the user pressed Cancel."""


# Steps shared by several issues.
_RESTART_STEP = "Close and reopen PDF Manager, then try again."
_LOGS_STEP = (
    "If it keeps happening, open the logs folder from Settings and keep the latest log file."
)


def _os_family() -> str:
    """ "windows", "linux" or "mac", for wording. Imported at call time to avoid an
    import cycle (the platform modules import this module)."""
    from .. import platforms

    return platforms.os_family()


def _on_windows() -> bool:
    """Whether to use Windows wording."""
    return _os_family() == "windows"


def _clip(text: str | None, limit: int = 4000) -> str | None:
    """Keep technical details readable; very long tool output is cut."""
    if not text:
        return None
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "\n…"


def ocr_missing() -> Issue:
    """Tesseract OCR is needed (Use OCR is ticked) but not installed."""
    return Issue(
        IssueCode.OCR_MISSING,
        Severity.ERROR,
        "Text reading (OCR) isn't installed",
        "This job uses OCR to make pages searchable, but the OCR program wasn't found.",
        (
            "Go to Settings and click Install OCR.",
            "If you installed it already, click Search for OCR in Settings.",
            "Or untick Use OCR to convert without searchable text.",
        ),
    )


def ocr_failed(file: str, page: int, details: str | None) -> Issue:
    """Tesseract exited with an error on a page."""
    return Issue(
        IssueCode.OCR_FAILED,
        Severity.ERROR,
        "Couldn't read the text on a page",
        f"OCR stopped with an error on page {page} of {file}.",
        (
            "Check the OCR language in Settings is installed (English is always available).",
            "Try a lower DPI in Settings.",
            "Reinstall OCR from Settings if the problem continues.",
            _LOGS_STEP,
        ),
        _clip(details),
        file,
    )


def ocr_timeout(file: str, page: int, seconds: int) -> Issue:
    """A single page took longer than the OCR page timeout."""
    minutes = max(1, round(seconds / 60))
    return Issue(
        IssueCode.OCR_TIMEOUT,
        Severity.ERROR,
        "Reading a page took too long",
        f"Page {page} of {file} was still being read after about {minutes} minute(s), "
        "so it was stopped.",
        (
            "Try a lower DPI in Settings; large, detailed pages are slow to read.",
            "Increase the OCR page timeout in Settings.",
            "Close other heavy programs and try again.",
        ),
        None,
        file,
    )


def ocr_install_failed(details: str | None) -> Issue:
    """The in-app OCR install (winget) didn't succeed."""
    return Issue(
        IssueCode.OCR_INSTALL_FAILED,
        Severity.ERROR,
        "OCR couldn't be installed automatically",
        "The OCR program didn't install. Your files are not affected.",
        (
            (
                "Check your internet connection and try Install OCR again.",
                "Or install Tesseract OCR from github.com/UB-Mannheim/tesseract/wiki, "
                "then click Search for OCR in Settings.",
            )
            if _on_windows()
            else (
                "Install Tesseract OCR with your system's software manager (package "
                "'tesseract-ocr' on Ubuntu/Debian, 'tesseract' on Arch).",
                "Then click Search for OCR in Settings.",
            )
        ),
        _clip(details),
    )


def _powerpoint_pdf_step() -> str:
    """The manual route for decks that need a closer visual match (decision C17)."""
    if _os_family() == "linux":  # No Microsoft PowerPoint here.
        return (
            "If the slides need to look exactly as they do in PowerPoint, export them as a PDF "
            "from PowerPoint on a computer that has it, and add that PDF instead."
        )
    return (
        "If you have Microsoft PowerPoint and need the slides to look exactly as they do there, "
        "open the presentation in PowerPoint, save or export it as a PDF, and add that PDF instead."
    )


def _install_libreoffice_step() -> str:
    """How to install LibreOffice Impress on this platform."""
    if _on_windows():
        return (
            "Install the free LibreOffice from libreoffice.org (its Impress part converts "
            "presentations), then try again."
        )
    if _os_family() == "mac":
        return "Install the free LibreOffice from libreoffice.org, then try again."
    return (
        "Install LibreOffice Impress with your system's software manager (package "
        "'libreoffice-impress' on Ubuntu/Debian, 'libreoffice-fresh' on Arch), then try again."
    )


def powerpoint_failed(file: str, details: str | None) -> Issue:
    """LibreOffice Impress couldn't convert a presentation to PDF."""
    return Issue(
        IssueCode.POWERPOINT_CONVERSION_FAILED,
        Severity.ERROR,
        "Couldn't convert the slides",
        f"LibreOffice couldn't turn {file} into a PDF.",
        (
            "Check that the presentation isn't damaged or password-protected: open it in "
            "LibreOffice Impress.",
            _powerpoint_pdf_step(),
            _LOGS_STEP,
        ),
        _clip(details),
        file,
    )


def slide_renderer_missing() -> Issue:
    """PowerPoint files were added, but LibreOffice Impress (which converts them) is missing."""
    return Issue(
        IssueCode.SLIDE_RENDERER_MISSING,
        Severity.ERROR,
        "LibreOffice is needed for PowerPoint files",
        "PDF Manager converts PowerPoint files (.pptx and .ppt) with the free LibreOffice "
        "Impress, which wasn't found. PDF files and images work without it.",
        (_install_libreoffice_step(), _powerpoint_pdf_step()),
    )


def password_protected(file: str) -> Issue:
    return Issue(
        IssueCode.PASSWORD_PROTECTED,
        Severity.ERROR,
        "This PDF is password-protected",
        f"{file} needs a password to open, so it can't be converted.",
        (
            "Open it in a PDF reader with the password and save an unprotected copy.",
            "Then add the unprotected copy instead.",
        ),
        None,
        file,
    )


def empty_pdf(file: str) -> Issue:
    return Issue(
        IssueCode.EMPTY_PDF,
        Severity.ERROR,
        "This PDF has no pages",
        f"{file} doesn't contain any pages.",
        ("Remove it from the list, or check you picked the right file.",),
        None,
        file,
    )


def unreadable_file(file: str, details: str | None) -> Issue:
    return Issue(
        IssueCode.UNREADABLE_FILE,
        Severity.ERROR,
        "Couldn't open a file",
        f"{file} couldn't be read. It may be damaged, moved or still downloading.",
        (
            "Check the file opens in its usual program.",
            "If it's in OneDrive or another cloud folder, make sure it's fully downloaded.",
            "Remove it from the list and add it again.",
        ),
        _clip(details),
        file,
    )


def unsupported_file(file: str) -> Issue:
    return Issue(
        IssueCode.UNSUPPORTED_FILE,
        Severity.ERROR,
        "This file type isn't supported here",
        f"{file} can't be used for this action.",
        ("Remove it from the list, or use a tab that accepts this file type.",),
        None,
        file,
    )


def invalid_page_ranges(file: str | None, reason: str) -> Issue:
    return Issue(
        IssueCode.INVALID_PAGE_RANGES,
        Severity.ERROR,
        "The page ranges need fixing",
        reason,
        (
            "Use page numbers and dashes separated by commas, for example: 1-3, 5, 8-10.",
            "Make sure every page number exists in the document.",
        ),
        None,
        file,
    )


def flatten_check_failed(file: str, details: str) -> Issue:
    return Issue(
        IssueCode.FLATTEN_CHECK_FAILED,
        Severity.ERROR,
        "Flattening didn't finish correctly",
        f"The flattened copy of {file} didn't pass the final check, so it wasn't kept.",
        ("Try again.", "Try a lower DPI in Settings.", _LOGS_STEP),
        details,
        file,
    )


def merge_failed(details: str | None) -> Issue:
    return Issue(
        IssueCode.MERGE_FAILED,
        Severity.ERROR,
        "Couldn't combine the files",
        "The files couldn't be merged into one PDF.",
        ("Try merging fewer files at once to find the one causing trouble.", _LOGS_STEP),
        _clip(details),
    )


def save_failed(details: str | None) -> Issue:
    return Issue(
        IssueCode.SAVE_FAILED,
        Severity.ERROR,
        "Couldn't save the results",
        "The finished files couldn't be written to the chosen folder. Nothing in that "
        "folder was overwritten.",
        (
            "If the Save button is still there, try again with a different folder, such as "
            "Documents or Desktop. Otherwise, convert the files again.",
            "Check the drive isn't full and the folder isn't read-only.",
            "Close the file if it's open in another program.",
        ),
        _clip(details),
    )


def settings_save_failed(details: str | None) -> Issue:
    """Settings couldn't be written to disk; they still apply until the app closes."""
    return Issue(
        IssueCode.SETTINGS_SAVE_FAILED,
        Severity.WARNING,
        "Your settings couldn't be saved",
        "The change works for now, but it will be lost when PDF Manager closes.",
        (
            "Check the drive isn't full.",
            "Make sure your user folder (AppData) isn't read-only or blocked by security software."
            if _on_windows()
            else "Make sure your settings folder (~/.config/pdf-manager) isn't read-only.",
            _LOGS_STEP,
        ),
        _clip(details),
    )


def job_already_running() -> Issue:
    return Issue(
        IssueCode.JOB_ALREADY_RUNNING,
        Severity.ERROR,
        "Another conversion is still running",
        "Only one conversion can run at a time.",
        ("Wait for it to finish, or cancel it, then try again.",),
    )


def unexpected_error(details: str | None) -> Issue:
    return Issue(
        IssueCode.UNEXPECTED_ERROR,
        Severity.ERROR,
        "Something went wrong",
        "An unexpected problem stopped the conversion. Your original files were not changed.",
        (_RESTART_STEP, _LOGS_STEP),
        _clip(details),
    )
