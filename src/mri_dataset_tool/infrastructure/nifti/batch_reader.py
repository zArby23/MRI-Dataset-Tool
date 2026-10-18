from collections.abc import Callable, Iterator
from pathlib import Path

from nibabel.filebasedimages import ImageFileError

from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.logging.logger import get_logger
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader, is_nifti_file

logger = get_logger(__name__)


class NIfTIBatchReader:
    """Load all valid NIfTI studies found below a directory tree."""

    def __init__(self) -> None:
        self._reader = NIfTIReader()

    def iter_studies(
        self,
        directory: Path,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> Iterator[MRIStudy]:
        """Yield studies one at a time to keep memory usage bounded.

        This is the streaming path recommended by RNF02 for large batches.
        ``on_error(path, error)`` is called for each skipped file (RF16). If the
        callback itself raises, that is logged by type and the batch continues.
        """
        # Validate eagerly: a generator function would defer this to the first next().
        if not directory.exists():
            raise FileNotFoundError(f"Path doesn't exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {directory}")
        return self._iter_studies(directory, on_error)

    def _iter_studies(
        self,
        directory: Path,
        on_error: Callable[[Path, Exception], None] | None,
    ) -> Iterator[MRIStudy]:
        errors_count = 0
        studies_loaded = 0

        for path in sorted(directory.rglob("*")):
            if not path.is_file() or not is_nifti_file(path):
                continue
            # Hidden components (.git, .datalad...) are skipped silently; only those
            # below the given root count, so the root itself may live under a hidden dir.
            if any(part.startswith(".") for part in path.relative_to(directory).parts):
                continue

            try:
                study = self._reader.load_study(path)
            except (ImageFileError, OSError, EOFError, ValueError) as error:
                errors_count += 1
                logger.warning(
                    "Skipping invalid or unreadable NIfTI file (%s)",
                    type(error).__name__,
                )
                if on_error is not None:
                    try:
                        on_error(path, error)
                    except Exception as callback_error:
                        logger.warning(
                            "on_error callback failed (%s) while reporting %s",
                            type(callback_error).__name__,
                            type(error).__name__,
                        )
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

    def load_studies(
        self,
        directory: Path,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> list[MRIStudy]:
        """Backward-compatible API that returns all studies in memory.

        Use iter_studies() when processing large datasets to keep memory bounded.
        """
        return list(self.iter_studies(directory, on_error))
