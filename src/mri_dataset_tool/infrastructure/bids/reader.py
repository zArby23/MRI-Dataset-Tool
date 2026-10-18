import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.bids.entities import BIDSEntities, parse_bids_filename
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
        files = [path] if path.is_file() else find_nifti_files(path)
        return self.load_files(
            files,
            on_error,
            root=_find_dataset_root(path),
        )

    def load_files(
        self,
        files: list[Path],
        on_error: Callable[[Path, Exception], None] | None = None,
        root: Path | None = None,
    ) -> MRIStudy:
        """Load the given NIfTI files as one study; identity comes from the first valid file.

        ``root`` is the dataset root for sidecar inheritance; without it only the
        sidecar in the image's own directory is considered.
        """
        series = []
        identity: tuple[str, str | None] | None = None
        for file in files:
            try:
                entities = parse_bids_filename(file.name)
                if identity not in (None, (entities.sub, entities.ses)):
                    raise ValueError("File belongs to a different subject/session.")
                one = self._load_series(file, entities, root)
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

    def _load_series(self, file: Path, entities: BIDSEntities, root: Path | None):
        series = self._reader.load_study(file).series[0]
        series.modality = entities.suffix
        series.metadata["bids"] = asdict(entities)
        sidecar = _inherited_sidecar(file, entities, root)
        if sidecar:
            series.metadata["sidecar"] = sidecar
        return series

    @staticmethod
    def _report(on_error, file: Path, error: Exception) -> None:
        if on_error is None:
            return
        try:
            on_error(file, error)
        except Exception as callback_error:
            logger.warning("on_error callback failed (%s)", type(callback_error).__name__)


def _find_dataset_root(path: Path) -> Path | None:
    """First ancestor (or *path* itself) holding dataset_description.json, else None."""
    start = path if path.is_dir() else path.parent
    for directory in (start, *start.parents):
        if (directory / "dataset_description.json").is_file():
            return directory
    return None


def _sidecar_entities(json_path: Path, suffix: str) -> list[tuple[str, str]] | None:
    """Entities of a candidate sidecar name, or None if it is not a valid candidate."""
    *parts, last = json_path.name.removesuffix(".json").split("_")
    if last != suffix:
        return None
    pairs = [tuple(part.partition("-")[::2]) for part in parts]
    if any(not key or not value for key, value in pairs):
        return None
    return pairs


def _is_subsequence(candidate: list[tuple[str, str]], image: list[tuple[str, str]]) -> bool:
    remaining = iter(image)
    return all(pair in remaining for pair in candidate)


def _inherited_sidecar(file: Path, entities: BIDSEntities, root: Path | None) -> dict:
    """Merge applicable JSON sidecars from general (dataset root) to specific (own directory)."""
    image = [("sub", entities.sub)]
    if entities.ses:
        image.append(("ses", entities.ses))
    image += list(entities.other.items())

    if root is not None and file.parent.is_relative_to(root):
        directories = [root]
        for part in file.parent.relative_to(root).parts:
            directories.append(directories[-1] / part)
    else:
        directories = [file.parent]  # no identifiable root: never read foreign JSON upwards

    merged: dict = {}
    for directory in directories:
        applicable = []
        for json_path in sorted(directory.glob("*.json")):
            pairs = _sidecar_entities(json_path, entities.suffix)
            if pairs is not None and _is_subsequence(pairs, image):
                applicable.append((len(pairs), json_path))
        for _, json_path in sorted(applicable):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Never chain/log the parse error: its message can quote sidecar content.
                raise ValueError("Invalid JSON sidecar.") from None
            if not isinstance(data, dict):
                raise ValueError("JSON sidecar must be an object.")
            merged.update(data)
    return merged


def find_nifti_files(directory: Path) -> list[Path]:
    """Sorted NIfTI files below *directory*, skipping hidden (dot) components relative to it."""
    return [
        f
        for f in sorted(directory.rglob("*"))
        if is_nifti_file(f)
        and f.is_file()
        and not any(part.startswith(".") for part in f.relative_to(directory).parts)
    ]
