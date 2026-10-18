import json
from collections.abc import Callable, Iterator
from pathlib import Path

from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.bids.entities import parse_bids_filename
from mri_dataset_tool.infrastructure.bids.reader import BIDSReader
from mri_dataset_tool.infrastructure.logging.logger import get_logger
from mri_dataset_tool.infrastructure.nifti.reader import is_nifti_file

logger = get_logger(__name__)


class BIDSBatchReader:
    """Load every subject/session of a BIDS dataset, one study at a time."""

    def __init__(self) -> None:
        self._reader = BIDSReader()

    def iter_studies(
        self,
        dataset_root: Path,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> Iterator[MRIStudy]:
        """Yield one study per subject/session, keeping only one loaded at a time (RNF02).

        Flexible mode: ``dataset_description.json`` is optional (if present it must be a
        JSON object) and loose BIDS-named NIfTI files anywhere in the tree are grouped
        by the subject/session in their names. Failures go to ``on_error`` (RF16).
        """
        if not dataset_root.exists():
            raise FileNotFoundError(f"Path doesn't exist: {dataset_root}")
        if not dataset_root.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {dataset_root}")
        description = dataset_root / "dataset_description.json"
        if description.is_file():
            try:
                valid = isinstance(json.loads(description.read_text(encoding="utf-8")), dict)
            except (json.JSONDecodeError, UnicodeDecodeError):
                valid = False
            if not valid:
                raise ValueError("Invalid dataset_description.json.")
        return self._iter_studies(dataset_root, on_error)

    def _iter_studies(
        self,
        dataset_root: Path,
        on_error: Callable[[Path, Exception], None] | None,
    ) -> Iterator[MRIStudy]:
        groups: dict[tuple[str, str], list[Path]] = {}
        errors_count = 0  # skipped files, including those that fail inside a group

        def report(file: Path, error: Exception) -> None:
            nonlocal errors_count
            errors_count += 1
            self._report(on_error, file, error)

        for file in sorted(dataset_root.rglob("*")):
            if not file.is_file() or not is_nifti_file(file):
                continue
            try:
                entities = parse_bids_filename(file.name)
            except ValueError as error:
                report(file, error)
                continue
            groups.setdefault((entities.sub, entities.ses or ""), []).append(file)

        studies_loaded = 0
        for key in sorted(groups):
            try:
                study = self._reader.load_files(groups[key], report, root=dataset_root)
            except (ValueError, OSError):
                continue  # every failed file was already reported
            studies_loaded += 1
            yield study
            del study  # don't hold it while the next group loads (peak = 1 study)

        if studies_loaded == 0:
            raise ValueError("No valid BIDS studies were found.")
        logger.info("Loaded %d BIDS studies. Errors: %d.", studies_loaded, errors_count)

    @staticmethod
    def _report(on_error, file: Path, error: Exception) -> None:
        logger.warning("Skipping BIDS file (%s)", type(error).__name__)
        if on_error is None:
            return
        try:
            on_error(file, error)
        except Exception as callback_error:
            logger.warning("on_error callback failed (%s)", type(callback_error).__name__)

    def load_studies(
        self,
        dataset_root: Path,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> list[MRIStudy]:
        """Return all studies in memory; prefer iter_studies() for large datasets."""
        return list(self.iter_studies(dataset_root, on_error))
