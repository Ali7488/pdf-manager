"""Input files (``info``: describing them for the file list) and output file names
(``naming``: never overwrite when saving)."""

from .info import FileInfo, FileKind, file_kind, inspect_file
from .naming import safe_destination

__all__ = ["FileInfo", "FileKind", "file_kind", "inspect_file", "safe_destination"]
