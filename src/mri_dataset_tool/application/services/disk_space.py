"""Approximate free-space check for an output location (warning only, never blocking).

The output of a conversion, anonymization or pipeline run is estimated as the size of its input.
It is a rough figure: resampling to a smaller spacing (or float32 outputs of int16 inputs) can
produce much more. ``report`` and ``export-ml`` write small files and are not checked.
"""

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MARGIN = 0.10


@dataclass(frozen=True)
class DiskSpaceCheck:
    required: int
    free: int | None  # None when the free space could not be read
    insufficient: bool


def estimate_input_bytes(path: Path) -> int:
    """Total size of the regular files of *path* (a file or a tree); hidden entries are skipped as
    the batch readers do (``.git``, ``.datalad``...). A symlink to a file counts its target (git-annex
    and DataLad store each image as one); broken or unreadable links count as 0. Symlinked
    directories are not followed (``os.walk`` default), so a link cycle cannot loop."""
    if path.is_file():
        return path.stat().st_size
    total = 0
    for directory, subdirs, files in os.walk(path):
        subdirs[:] = [name for name in subdirs if not name.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            try:
                info = os.stat(os.path.join(directory, name))  # follows git-annex/DataLad file symlinks
            except OSError:  # broken or unreadable link
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def check_free_space(output_path: Path, required_bytes: int, margin: float = DEFAULT_MARGIN) -> DiskSpaceCheck:
    """Compare *required_bytes* with the free space of the drive that will hold *output_path*
    (its first existing ancestor). Insufficient when the estimate reaches ``(1 - margin)`` of the
    free space. If the free space cannot be read, nothing is reported (DEBUG log, type only)."""
    target = next((p for p in (output_path, *output_path.absolute().parents) if p.exists()), None)
    try:
        if target is None:
            raise FileNotFoundError("No existing ancestor.")
        free = shutil.disk_usage(target).free
    except OSError as error:
        logger.debug("Free disk space unavailable (%s)", type(error).__name__)
        return DiskSpaceCheck(required_bytes, None, False)
    return DiskSpaceCheck(required_bytes, free, required_bytes >= free * (1 - margin))
