import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.bids.entities import parse_bids_filename
from mri_dataset_tool.infrastructure.logging.logger import get_logger
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader, is_nifti_file

logger = get_logger(__name__)


class BIDSReader:
    """Load the NIfTI images of one BIDS subject/session as a single study."""

    def __init__(self) -> None:
        self._reader = NIfTIReader()

    def load_study(
        self,
        path: Path,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> MRIStudy:
        """Load a subject/session directory, or one loose BIDS-named NIfTI file.

        Flexible mode: no ``sub-*/ses-*/<datatype>/`` tree or ``dataset_description.json``
        is required; subject and session come from the file names. A file that fails
        (bad name, bad image, bad sidecar) is reported via ``on_error`` and skipped.
        """
        if not path.exists():
            raise FileNotFoundError(f"Path doesn't exist: {path}")
        files = [path] if path.is_file() else sorted(path.rglob("*"))
        # Names are only inspected here; the caller may pass a mixed tree.
        return self.load_files(
            [f for f in files if f.is_file() and is_nifti_file(f)], on_error
        )

    def load_files(
        self,
        files: list[Path],
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> MRIStudy:
        """Load the given NIfTI files as one study; identity comes from the first valid file."""
        series = []
        identity: tuple[str, str | None] | None = None
        for file in files:
            try:
                entities = parse_bids_filename(file.name)
                if identity not in (None, (entities.sub, entities.ses)):
                    raise ValueError("File belongs to a different subject/session.")
                one = self._load_series(file, entities)
            except (ValueError, OSError) as error:
                logger.warning("Skipping BIDS file (%s)", type(error).__name__)
                self._report(on_error, file, error)
                continue
            identity = (entities.sub, entities.ses)
            series.append(one)

        if identity is None:
            raise ValueError("No valid BIDS NIfTI files were found.")
        logger.info("Loaded BIDS study with %d series", len(series))
        return MRIStudy(
            study_uid=None,
            series=series,
            subject_id=identity[0],
            session_id=identity[1],
        )

    def _load_series(self, file: Path, entities):
        series = self._reader.load_study(file).series[0]
        series.modality = entities.suffix
        series.metadata["bids"] = asdict(entities)
        # shortcut: same-name sidecar only, no BIDS inheritance (open question 5), decide with the human.
        sidecar = file.parent / (file.name.removesuffix(".gz").removesuffix(".nii") + ".json")
        if sidecar.is_file():
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Never chain/log the parse error: its message can quote sidecar content.
                raise ValueError("Invalid JSON sidecar.") from None
            if not isinstance(data, dict):
                raise ValueError("JSON sidecar must be an object.")
            series.metadata["sidecar"] = data
        return series

    @staticmethod
    def _report(on_error, file: Path, error: Exception) -> None:
        if on_error is None:
            return
        try:
            on_error(file, error)
        except Exception as callback_error:
            logger.warning("on_error callback failed (%s)", type(callback_error).__name__)
