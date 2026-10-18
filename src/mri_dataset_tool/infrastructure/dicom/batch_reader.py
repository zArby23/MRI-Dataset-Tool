import os
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from pydicom.errors import InvalidDicomError

from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.dicom._study_assembler import (
    DICOMInstanceHeader,
    assemble_study,
    read_dicom_header,
)
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class DICOMBatchReader:
    """Load all valid DICOM studies found below a directory tree."""

    def load_studies(
        self,
        directory: Path,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> list[MRIStudy]:
        """Load all valid studies below ``directory``.

        ``on_error(path, error)`` is called once for each skipped file (RF16). If the
        callback itself raises, that is logged by type and the batch continues.
        Hidden entries (a name starting with ".", relative to ``directory``) are ignored
        silently: no ``on_error`` call and no error count.
        """
        if not directory.exists():
            raise FileNotFoundError(f"Path doesn't exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {directory}")

        headers_by_study: dict[str, list[DICOMInstanceHeader]] = defaultdict(list)
        invalid_file_count = 0
        unreadable_file_count = 0
        missing_study_uid_count = 0
        missing_series_uid_count = 0

        for path in _iter_visible_files(directory):
            if not path.is_file():
                continue

            try:
                header = read_dicom_header(path)
            except InvalidDicomError as error:
                invalid_file_count += 1
                _report(on_error, path, error)
                continue
            except (OSError, EOFError) as error:
                unreadable_file_count += 1
                _report(on_error, path, error)
                continue

            if header.study_uid is None:
                missing_study_uid_count += 1
                _report(on_error, path, ValueError("Missing StudyInstanceUID."))
                continue
            if header.series_uid is None:
                missing_series_uid_count += 1
                _report(on_error, path, ValueError("Missing SeriesInstanceUID."))
                continue

            headers_by_study[header.study_uid].append(header)

        studies = [
            assemble_study(study_uid, headers)
            for study_uid, headers in sorted(headers_by_study.items())
        ]

        if not studies:
            raise ValueError("No valid DICOM studies were found.")

        logger.info(
            "Loaded %d DICOM studies. Invalid files: %d; unreadable files: %d; "
            "missing study UID: %d; missing series UID: %d.",
            len(studies),
            invalid_file_count,
            unreadable_file_count,
            missing_study_uid_count,
            missing_series_uid_count,
        )
        return studies


def _report(
    on_error: Callable[[Path, Exception], None] | None,
    path: Path,
    error: Exception,
) -> None:
    if on_error is None:
        return
    try:
        on_error(path, error)
    except Exception as callback_error:
        logger.warning(
            "on_error callback failed (%s) while reporting %s",
            type(callback_error).__name__,
            type(error).__name__,
        )


def _iter_visible_files(directory: Path):
    """Yield candidate files below *directory*, pruning hidden subdirectories (.git, .datalad...)."""
    for root, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for name in sorted(filenames):
            if not name.startswith("."):
                yield Path(root) / name
