"""Which Git revision this copy of PDF Manager was built from (decision P37).

Settings → About links to the source code of exactly the running version
(AGPL-3.0 sections 6 and 13). A version tag isn't enough: preview builds are
made from commits that have no tag, and a tag can move. So the build records
the exact commit:

* **Packaged app:** ``packaging/pdf-manager.spec`` calls :func:`write_build_info`,
  which writes ``build-info.json`` next to the bundled interface
  (``<_MEIPASS>/build-info.json``). The build stops if tracked files differ
  from that commit, so the link can't point at source the build doesn't match
  (``PDF_MANAGER_ALLOW_DIRTY=1`` allows such a build for local testing, and
  marks it ``modified``). ``PDF_MANAGER_SOURCE_REVISION`` (CI sets it to the
  commit being built) must agree with the checkout.
* **From source:** the revision is asked from Git once, at first use.

:func:`source_revision` returns ``None`` when the revision can't be known; the
page then links to the repository without claiming it is this version.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)

BUILD_INFO_FILE = "build-info.json"
GIT_TIMEOUT_SEC = 5
_SHA = re.compile(r"^[0-9a-f]{40}$")


class BuildInfoError(RuntimeError):
    """The build's revision couldn't be recorded truthfully."""


def _git(repo: Path, *args: str) -> str:
    """Run a read-only Git command in ``repo`` and return its output.

    Raises:
        OSError, subprocess.SubprocessError: Git isn't available or failed.
    """
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SEC,
        check=True,
    )
    return done.stdout.strip()


def git_revision(repo: Path) -> dict[str, Any] | None:
    """The checkout's commit and whether tracked files differ from it.

    Args:
        repo: The repository root.

    Returns:
        ``{"revision": <40-hex sha>, "modified": bool}``, or ``None`` if
        ``repo`` isn't a Git checkout (or Git isn't installed).
    """
    try:
        revision = _git(repo, "rev-parse", "HEAD")
        changes = _git(repo, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError):
        return None
    if not _SHA.match(revision):
        return None
    return {"revision": revision, "modified": bool(changes)}


def write_build_info(repo: Path, target: Path) -> dict[str, Any]:
    """Record the commit a build is made from (called by the PyInstaller spec).

    Args:
        repo: The repository root being built.
        target: The ``build-info.json`` file to write.

    Returns:
        What was written.

    Raises:
        BuildInfoError: Not a Git checkout; tracked files differ from the
            commit (unless ``PDF_MANAGER_ALLOW_DIRTY=1``); or
            ``PDF_MANAGER_SOURCE_REVISION`` names another commit.
    """
    info = git_revision(repo)
    if info is None:
        raise BuildInfoError(f"{repo} isn't a Git checkout, so the build's source is unknown.")
    expected = os.environ.get("PDF_MANAGER_SOURCE_REVISION", "").strip().lower()
    if expected and expected != info["revision"]:
        raise BuildInfoError(
            f"PDF_MANAGER_SOURCE_REVISION is {expected}, but the checkout is {info['revision']}."
        )
    if info["modified"] and os.environ.get("PDF_MANAGER_ALLOW_DIRTY") != "1":
        raise BuildInfoError(
            "Tracked files differ from the commit, so the app's source link would be wrong. "
            "Commit or stash the changes (or set PDF_MANAGER_ALLOW_DIRTY=1 for a local test build)."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def _read_bundled() -> dict[str, Any] | None:
    """The packaged app's ``build-info.json``, or ``None`` if missing or unreadable."""
    try:
        data = json.loads((paths.resource_dir() / BUILD_INFO_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("No readable %s in the app; the source revision is unknown", BUILD_INFO_FILE)
        return None
    revision = str(data.get("revision", ""))
    if not _SHA.match(revision):
        return None
    return {"revision": revision, "modified": bool(data.get("modified"))}


@functools.cache
def source_revision() -> dict[str, Any] | None:
    """The revision this running copy was built from (cached).

    Returns:
        ``{"revision", "modified"}``, or ``None`` if unknown.
    """
    info = _read_bundled() if paths.is_frozen() else git_revision(paths.app_dir())
    log.info("Source revision: %s", info or "unknown")
    return info
