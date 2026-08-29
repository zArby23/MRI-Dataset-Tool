from collections import defaultdict
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

    def load_studies(self, directory: Path) -> list[MRIStudy]:
        if not directory.exists():
            raise FileNotFoundError(f"Path doesn't exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {directory}")

        headers_by_study: dict[str, list[DICOMInstanceHeader]] = defaultdict(list)
        invalid_file_count = 0
        unreadable_file_count = 0
        missing_study_uid_count = 0
        missing_series_uid_count = 0

        for path in directory.rglob("*"):
            if not path.is_file():
                continue

            try:
                header = read_dicom_header(path)
            except InvalidDicomError:
                invalid_file_count += 1
                continue
            except (OSError, EOFError):
                unreadable_file_count += 1
                continue

            if header.study_uid is None:
                missing_study_uid_count += 1
                continue
            if header.series_uid is None:
                missing_series_uid_count += 1
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
