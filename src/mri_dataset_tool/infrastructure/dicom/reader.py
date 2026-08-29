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


class DICOMReader:
    """Load one DICOM study from the direct files of a directory."""

    def load_study(self, directory: Path) -> MRIStudy:
        if not directory.exists():
            raise FileNotFoundError(f"Path doesn't exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {directory}")

        headers: list[DICOMInstanceHeader] = []
        invalid_file_count = 0
        unreadable_file_count = 0

        for path in directory.iterdir():
            if not path.is_file():
                continue
            try:
                headers.append(read_dicom_header(path))
            except InvalidDicomError:
                invalid_file_count += 1
            except (OSError, EOFError):
                unreadable_file_count += 1

        if not headers:
            raise ValueError(f"No DICOM files were found in directory: {directory}")

        headers_with_study_uid = [
            header for header in headers if header.study_uid is not None
        ]
        study_uids = {header.study_uid for header in headers_with_study_uid}
        if not study_uids:
            raise ValueError("No DICOM files with StudyInstanceUID were found.")
        if len(study_uids) > 1:
            raise ValueError(f"Multiple studies found in directory: {directory}")

        study_uid = study_uids.pop()
        valid_headers = [
            header
            for header in headers_with_study_uid
            if header.series_uid is not None
        ]
        if not valid_headers:
            raise ValueError("No valid DICOM series found.")

        study = assemble_study(study_uid, valid_headers)
        logger.info(
            "Loaded one DICOM study with %d series. Invalid files: %d; "
            "unreadable files: %d; missing study or series UID: %d.",
            len(study.series),
            invalid_file_count,
            unreadable_file_count,
            len(headers) - len(valid_headers),
        )
        return study