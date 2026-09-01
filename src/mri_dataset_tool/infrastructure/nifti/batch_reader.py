from collections.abc import Iterator
from pathlib import Path

from nibabel.filebasedimages import ImageFileError

from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.logging.logger import get_logger
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader

logger = get_logger(__name__)


class NIfTIBatchReader:
    """Load all valid NIfTI studies found below a directory tree."""

    def __init__(self) -> None:
        self._reader = NIfTIReader()

    def iter_studies(self, directory: Path) -> Iterator[MRIStudy]:
        """Yield studies one at a time to keep memory usage bounded.

        This is the streaming path recommended by RNF02 for large batches.
        """
        if not directory.exists():
            raise FileNotFoundError(f"Path doesn't exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {directory}")

        errors_count = 0
        studies_loaded = 0

        for path in sorted(directory.rglob("*")):
            if not path.is_file() or not self._is_nifti_file(path):
                continue

            try:
                study = self._reader.load_study(path)
            except (ImageFileError, OSError, EOFError, ValueError):
                errors_count += 1
                logger.warning("Skipping invalid or unreadable NIfTI file: %s", path)
                continue

            studies_loaded += 1
            yield study

        if studies_loaded == 0:
            raise ValueError("No valid NIfTI studies were found.")

        logger.info(
            "Loaded %d NIfTI studies. Errors: %d.",
            studies_loaded,
            errors_count,
        )

    def load_studies(self, directory: Path) -> list[MRIStudy]:
        """Backward-compatible API that returns all studies in memory.

        Use iter_studies() when processing large datasets to keep memory bounded.
        """
        return list(self.iter_studies(directory))

    @staticmethod
    def _is_nifti_file(path: Path) -> bool:
        return path.name.endswith(".nii") or path.name.endswith(".nii.gz")

    