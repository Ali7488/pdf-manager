"""Browser mode's per-launch state.

The page never sees or sends a host path it could choose itself. Files the
user picks or uploads, folders the user picks, and results prepared for
download are known to the page only by opaque IDs issued here; folder paths
the page shows (the default save folder, where results were saved, the logs
and licences folders) may only be sent back if this session issued them.

The session also keeps the latest status of each job and of an OCR install,
fed by :class:`api.workflow.Workflow`'s events, so the page can poll it and
a quick finish or a page refresh never loses the result.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import dto, service

log = logging.getLogger(__name__)

FILE_PREFIX = "f-"
FOLDER_PREFIX = "d-"
DOWNLOAD_PREFIX = "x-"
# What the page may do with a folder it names.
OPEN = "open"
SAVE = "save"
# Statuses kept for jobs the page hasn't discarded yet (older ones are dropped).
MAX_JOB_STATUSES = 20
CHUNK = 1024 * 1024
# Characters that can't be in a file name on Windows (and "/" anywhere).
_UNSAFE_NAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


class UploadError(Exception):
    """An upload was refused or didn't arrive complete (the reason is for the log)."""


def safe_upload_name(name: str) -> str:
    """The file name an upload is stored under: no folders, no unsafe characters.

    Args:
        name: The browser's ``File.name``.

    Raises:
        UploadError: Nothing usable is left (for example ``".."``).
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_NAME.sub("_", base).strip().strip(".")
    if not cleaned or cleaned in {".", ".."}:
        raise UploadError(f"Unusable file name: {name!r}")
    return cleaned[:200]


def _key(path: Path) -> str:
    """Comparison key for a path (case-insensitive on Windows, as Explorer is)."""
    return os.path.normcase(str(path))


class Session:
    """IDs, staged uploads and polled status for one run of browser mode.

    Thread-safe: the server calls it from one thread per request.

    Args:
        staging_parent: Where the private staging folder is created (default:
            the system temp folder).
    """

    def __init__(self, staging_parent: Path | None = None):
        self._lock = threading.Lock()
        self._files: dict[str, Path] = {}
        self._file_ids: dict[str, str] = {}
        self._folders: dict[str, Path] = {}
        self._folder_ids: dict[str, str] = {}
        # Folders the page may name, and what for: OPEN (show in the file
        # manager) and/or SAVE (save results into).
        self._known_folders: dict[str, set[str]] = {}
        self._downloads: dict[str, tuple[Path, str]] = {}
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._started: dict[str, dict[str, Any]] = {}  # requestId -> start result.
        self._ocr: dict[str, Any] = {"running": False, "messages": [], "finished": None}
        # mkdtemp makes the folder readable by this user only.
        self.staging = Path(tempfile.mkdtemp(prefix="pdf-manager-uploads-", dir=staging_parent))

    def close(self) -> None:
        """Delete the staged uploads and download copies. Never raises."""
        shutil.rmtree(self.staging, ignore_errors=True)

    # ----- Files -----

    def file_id(self, path: Path) -> str:
        """The page's ID for a file (the same file always gets the same ID)."""
        with self._lock:
            key = _key(path)
            if key not in self._file_ids:
                file_id = FILE_PREFIX + secrets.token_urlsafe(12)
                self._file_ids[key] = file_id
                self._files[file_id] = path
            return self._file_ids[key]

    def for_page(self, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """``InputFile`` objects with their ``path`` replaced by the file's ID."""
        return [{**f, "path": self.file_id(Path(f["path"]))} for f in files]

    def resolve_files(self, ids: Any) -> list[str]:
        """The host paths of the IDs the page sent, in the same order.

        Raises:
            ConversionError: Not a list of IDs this session issued.
        """
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise dto.invalid_request("files must be a list of file IDs")
        with self._lock:
            unknown = [i for i in ids if i not in self._files]
            if unknown:
                raise dto.invalid_request(f"{len(unknown)} unknown file ID(s)")
            return [str(self._files[i]) for i in ids]

    def add_upload(
        self,
        name: str,
        size: int,
        read: Callable[[int], bytes],
        describe: Callable[[list[Path]], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Stage one uploaded file under its own new UUID and publish its ID.

        Every upload gets a fresh, server-generated UUID (decision P34). The
        UUID names its private folder (``uploads/<uuid>/<name>``) and is its
        ID (``f-<uuid>``), so two uploads never share storage or an ID, even
        for the same file sent twice or for different files with the same
        name, size and date. The original name is kept for display and output
        naming. The body is written to a hidden partial file, renamed into
        place and checked with ``describe``; only then is the ID published.
        Any failure removes the upload's folder, so a retry is a fresh upload.
        Renderer choice doesn't depend on where the file came from (decision
        C17), so no provenance marker is added.

        Args:
            name: The browser's file name.
            size: Its size in bytes (the request's Content-Length).
            read: Reads up to ``n`` more bytes of the body.
            describe: Turns the staged path into ``InputFile`` objects (an
                empty list if the file isn't usable).

        Returns:
            ``InputFile`` objects (one, or none if unusable) with the new ID as ``path``.

        Raises:
            UploadError: Unsupported type, or the body didn't arrive complete.
        """
        safe = safe_upload_name(name)
        if service.file_kind(Path(safe)) is None:
            raise UploadError(f"Unsupported file type: {Path(safe).suffix or '(none)'}")
        upload_id = uuid.uuid4().hex
        uploads = self.staging / "uploads"
        uploads.mkdir(exist_ok=True)
        folder = uploads / upload_id
        folder.mkdir()  # A new UUID: never an existing folder.
        try:
            target = folder / safe
            partial = folder / ".upload.part"
            remaining = size
            with open(partial, "xb") as out:
                while remaining > 0:
                    chunk = read(min(CHUNK, remaining))
                    if not chunk:
                        raise UploadError("The upload ended early")
                    out.write(chunk)
                    remaining -= len(chunk)
            os.replace(partial, target)
            files = describe([target])
            if len(files) != 1:
                log.info("Upload %s isn't a usable file", upload_id)
                shutil.rmtree(folder, ignore_errors=True)
                return []
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        file_id = FILE_PREFIX + upload_id
        with self._lock:
            self._files[file_id] = target
        return [{**files[0], "path": file_id}]

    # ----- Folders -----

    def know_folder(self, folder: Path | str | None, *uses: str) -> None:
        """Let the page name this folder from now on, for the given uses (OPEN, SAVE)."""
        if folder:
            with self._lock:
                self._known_folders.setdefault(_key(Path(folder)), set()).update(uses)

    def folder_id(self, folder: Path) -> str:
        """The page's ID for a folder the user picked (it may open and save to it)."""
        self.know_folder(folder, OPEN, SAVE)
        with self._lock:
            key = _key(folder)
            if key not in self._folder_ids:
                folder_id = FOLDER_PREFIX + secrets.token_urlsafe(12)
                self._folder_ids[key] = folder_id
                self._folders[folder_id] = folder
            return self._folder_ids[key]

    def resolve_folder(self, value: Any, use: str) -> Path | None:
        """A folder the page may use for ``use``: picked (by ID), or shown to it for that use.

        Args:
            value: A folder ID, or a folder path this session showed the page.
            use: OPEN or SAVE.

        Returns:
            The folder, or ``None`` if the page may not use it that way.
        """
        if not isinstance(value, str) or not value:
            return None
        with self._lock:
            if value in self._folders:
                return self._folders[value]
            if use in self._known_folders.get(_key(Path(value)), set()):
                return Path(value)
        return None

    # ----- Downloads -----

    def download_folder(self) -> Path:
        """A new private folder to copy results into for downloading."""
        folder = self.staging / "downloads" / secrets.token_hex(8)
        folder.mkdir(parents=True)
        return folder

    def add_download(self, path: Path) -> dict[str, Any]:
        """Offer a prepared file for one download. Returns ``{id, name, sizeBytes}``."""
        download_id = DOWNLOAD_PREFIX + secrets.token_urlsafe(12)
        with self._lock:
            self._downloads[download_id] = (path, path.name)
        return {"id": download_id, "name": path.name, "sizeBytes": path.stat().st_size}

    def take_download(self, download_id: str) -> tuple[Path, str] | None:
        """Claim a prepared download (each can be fetched once)."""
        with self._lock:
            return self._downloads.pop(download_id, None)

    # ----- Status the page polls -----

    def record(self, name: str, payload: Any) -> None:
        """Keep an event from the workflow (its ``emit`` callback). Never raises."""
        try:
            with self._lock:
                if name in ("jobProgress", "jobFinished"):
                    job = self._jobs.setdefault(
                        payload["jobId"], {"progress": None, "finished": None}
                    )
                    job["progress" if name == "jobProgress" else "finished"] = payload
                    self._jobs.move_to_end(payload["jobId"])
                    while len(self._jobs) > MAX_JOB_STATUSES:
                        self._jobs.popitem(last=False)
                elif name == "ocrInstallProgress":
                    self._ocr = {**self._ocr, "running": True}
                    self._ocr["messages"] = [*self._ocr["messages"], payload["message"]]
                elif name == "ocrInstallFinished":
                    self._ocr = {**self._ocr, "running": False, "finished": payload}
                else:
                    log.debug("Browser mode ignores event %s", name)
        except Exception:
            log.exception("Couldn't record event %s", name)

    def job_started(self, request_id: str, action: str, result: dict[str, Any]) -> None:
        """Remember a start request's result, so a retried request gets the same job."""
        with self._lock:
            self._started[request_id] = result
            job_id = result.get("jobId")
            if job_id:
                job = self._jobs.setdefault(job_id, {"progress": None, "finished": None})
                job["action"] = action

    def started(self, request_id: str) -> dict[str, Any] | None:
        """The result of an earlier start request with this ID, if any."""
        with self._lock:
            return self._started.get(request_id)

    def job_saved(self, job_id: str, outcome: dict[str, Any], as_zip: bool) -> None:
        """Remember how a job's results were saved, for a page that is reloaded (P36).

        Args:
            job_id: The job.
            outcome: Its ``SaveOutcome`` (saved to a folder, or ``downloaded``).
            as_zip: Whether they were saved as one zip (so Download again does the same).
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["saved"] = outcome
                job["savedAsZip"] = as_zip

    def _status(self, job_id: str, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "jobId": job_id,
            "progress": job["progress"],
            "finished": job["finished"],
            "saved": job.get("saved"),
            "savedAsZip": bool(job.get("savedAsZip")),
        }

    def job_status(self, job_id: str) -> dict[str, Any] | None:
        """``{jobId, progress, finished, saved, savedAsZip}`` of a job this session started."""
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else self._status(job_id, job)

    def latest_job(self) -> dict[str, Any] | None:
        """The newest job not yet discarded, for a page that was refreshed.

        It includes how its results were saved (``saved``), so a job already
        saved to a folder comes back as saved, never with a Save button whose
        results are gone, and a downloaded one keeps Download again (P36).
        """
        with self._lock:
            if not self._jobs:
                return None
            job_id, job = next(reversed(self._jobs.items()))
            return {**self._status(job_id, job), "action": job.get("action")}

    def forget_job(self, job_id: str) -> None:
        """Drop a job's status once its results are discarded."""
        with self._lock:
            self._jobs.pop(job_id, None)

    def ocr_install_started(self) -> None:
        """An install was requested: clear the previous one's status."""
        with self._lock:
            self._ocr = {"running": True, "messages": [], "finished": None}

    def ocr_install_status(self) -> dict[str, Any]:
        """``{running, messages, finished}`` of the latest OCR install."""
        with self._lock:
            return {**self._ocr, "messages": list(self._ocr["messages"])}
