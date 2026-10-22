"""Write processed studies as a BIDS dataset (RF10, RF13, RF15), one study at a time (RNF02).

Layout and names come from ``bids_layout``. Each image is a ``float32`` NIfTI with the canonical
affine plus a JSON sidecar holding only ``SIDECAR_WHITELIST`` keys. Ids come from
``subject_id``/``session_id``, never from paths; ``series.files`` is never read. Nothing is
overwritten and every file is written atomically. Messages and logs: fixed text, types and counts.
"""

import json
import math
import os
from collections import Counter
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.anonymization.policy import POLICY_VERSION, SIDECAR_WHITELIST
from mri_dataset_tool.infrastructure.dataset.bids_layout import SUFFIX_DATATYPES, bids_path, validate_label
from mri_dataset_tool.infrastructure.logging.logger import get_logger
from mri_dataset_tool.infrastructure.nifti.writer import NIfTIWriter
from mri_dataset_tool.infrastructure.processing.arrays import load_array
from mri_dataset_tool.infrastructure.processing.geometry import validate_geometry

logger = get_logger(__name__)

BIDS_VERSION = "1.9.0"
TOOL_NAME = "MRI-Dataset-Tool"
DATASET_NAME = "MRI-Dataset-Tool export"

_SCALARS = (str, int, float, bool)


class BIDSDatasetWriter:
    """Use ``add_study`` once per study (e.g. as the pipeline's ``on_result``), then ``finalize`` once."""

    def __init__(self, root: Path) -> None:
        """Create *root* (and missing parents); an existing *root* → ``FileExistsError``."""
        try:
            root.mkdir(parents=True)
        except FileExistsError:
            raise FileExistsError("Dataset directory already exists.") from None
        except OSError:
            raise OSError("Dataset directory could not be created.") from None  # the cause quotes the path
        self.root = root
        self._nifti = NIfTIWriter()
        # subject -> sessions written (None = no session level); the only state kept between studies
        self._sessions: dict[str, set[str | None]] = {}

    @property
    def participants(self) -> list[str]:
        """Subject labels with at least one written series, sorted."""
        return sorted(self._sessions)

    def add_study(
        self, study: MRIStudy, on_error: Callable[[Path, Exception], None] | None = None
    ) -> list[Path]:
        """Write every series of *study*; returns the written NIfTI paths.

        A study without a valid subject id, with an invalid session id, already written, or
        mixing session/no-session for a subject raises a fixed ``ValueError`` and writes nothing.
        A series that cannot be written (unsupported suffix, invalid geometry, unreadable volume,
        existing output) goes to ``on_error(<study folder relative to the root>, error)`` and the
        rest of the study is written. When a suffix repeats in the study, its series get
        ``run-1..n`` in ``study.series`` order. The volume of each series is released after writing.
        """
        if study.subject_id is None:
            raise ValueError("Study has no subject id.")
        subject = validate_label(study.subject_id)
        session = None if study.session_id is None else validate_label(study.session_id)
        sessions = self._sessions.get(subject, set())
        if session in sessions:
            raise ValueError("Study subject/session was already written.")
        if sessions and (session is None) != (None in sessions):
            raise ValueError("Study session layout is inconsistent for its subject.")

        folder = Path(f"sub-{subject}") if session is None else Path(f"sub-{subject}", f"ses-{session}")
        repeated = Counter(series.modality for series in study.series if series.modality in SUFFIX_DATATYPES)
        runs: Counter[str] = Counter()
        written: list[Path] = []
        failed = 0
        for series in study.series:
            run = None
            if series.modality in SUFFIX_DATATYPES and repeated[series.modality] > 1:
                runs[series.modality] += 1
                run = runs[series.modality]
            try:
                written.append(self._write_series(series, subject, session, run))
            except Exception as error:
                failed += 1
                self._report(on_error, folder, error)

        if written:
            self._sessions.setdefault(subject, set()).add(session)
        logger.info("Wrote %d series of a study. Errors: %d.", len(written), failed)
        return written

    def finalize(self, manifest_json: str | None = None) -> list[Path]:
        """Write ``dataset_description.json``, ``participants.tsv``/``.json``, ``README`` and,
        with *manifest_json* (the run manifest as JSON text), ``code/run_manifest.json``.

        The anonymization policy is declared only if the manifest records an ``anonymize`` step.
        Existing files → ``FileExistsError``; invalid manifest JSON → ``ValueError``.
        """
        anonymized = False
        if manifest_json is not None:
            try:
                manifest = json.loads(manifest_json)
                anonymized = any(step["name"] == "anonymize" for step in manifest["steps"])
                # the dataset never carries input paths (RNF07)
                has_paths = any(report.get("source_path") is not None for report in manifest["reports"])
            except (ValueError, KeyError, TypeError, AttributeError):
                raise ValueError("Invalid run manifest.") from None  # the cause quotes content
            if has_paths:
                raise ValueError("Run manifest must not contain source paths.")

        generated_by: dict[str, Any] = {"Name": TOOL_NAME, "Version": _tool_version()}
        if anonymized:
            generated_by["Description"] = f"Anonymization policy {POLICY_VERSION}"
        description = {
            "Name": DATASET_NAME,
            "BIDSVersion": BIDS_VERSION,
            "DatasetType": "raw",
            "GeneratedBy": [generated_by],
        }
        participants = self.participants
        files: dict[Path, bytes] = {
            self.root / "dataset_description.json": _json_bytes(description),
            self.root / "participants.tsv": "".join(
                f"{line}\n" for line in ["participant_id", *(f"sub-{p}" for p in participants)]
            ).encode("utf-8"),
            self.root / "participants.json": _json_bytes(
                {"participant_id": {"Description": "Pseudonymized participant identifier."}}
            ),
            self.root / "README": _readme(anonymized).encode("utf-8"),
        }
        if manifest_json is not None:
            files[self.root / "code" / "run_manifest.json"] = manifest_json.encode("utf-8")
        if any(path.exists() for path in files):
            raise FileExistsError("Dataset file already exists.")
        try:
            if manifest_json is not None:
                (self.root / "code").mkdir(exist_ok=True)
            write_all(files)
        except BaseException:
            self._remove_empty_dirs(self.root / "code")
            raise
        logger.info("Finalized dataset with %d participants.", len(participants))
        return list(files)

    def _write_series(self, series: MRISeries, subject: str, session: str | None, run: int | None) -> Path:
        image_rel = bids_path(subject, session, series.modality, ".nii.gz", run)
        image, sidecar = self.root / image_rel, self.root / bids_path(subject, session, series.modality, ".json", run)
        if image.exists() or sidecar.exists():
            raise FileExistsError("Dataset file already exists.")
        validate_geometry(series)
        if len(series.volume.shape) not in (3, 4):
            raise ValueError("Unsupported volume dimensionality.")
        sidecar_data = _json_bytes(_filter_sidecar(series.get("sidecar")))  # encoded before writing anything

        image.parent.mkdir(parents=True, exist_ok=True)
        image_written = False
        try:
            try:
                with np.errstate(over="raise"):
                    volume = load_array(series.volume, np.float32)
            except FloatingPointError:
                raise ValueError("Volume values exceed the float32 range.") from None
            output = MRISeries(volume=volume, metadata={"affine": series.get("affine")})
            del volume
            self._nifti.write(output, image)
            image_written = True
            del output  # one volume alive at a time
            _write_bytes(sidecar, sidecar_data)
        except BaseException:
            if image_written:
                image.unlink(missing_ok=True)  # never leave an image without its sidecar
            self._remove_empty_dirs(image.parent)
            raise
        return image

    def _remove_empty_dirs(self, directory: Path) -> None:
        """Remove *directory* and its parents up to (not including) the root while they are empty."""
        while directory != self.root:
            try:
                directory.rmdir()
            except OSError:
                return  # not empty
            directory = directory.parent

    @staticmethod
    def _report(on_error, folder: Path, error: Exception) -> None:
        logger.warning("Skipping series (%s)", type(error).__name__)
        if on_error is None:
            return
        try:
            on_error(folder, error)
        except Exception as callback_error:
            logger.warning("on_error callback failed (%s)", type(callback_error).__name__)


def _filter_sidecar(sidecar: Any) -> dict[str, Any]:
    if not isinstance(sidecar, dict):
        return {}
    return {key: value for key, value in sidecar.items() if key in SIDECAR_WHITELIST and _is_plain(value)}


def _is_plain(value: Any) -> bool:
    if isinstance(value, list):
        return all(_is_plain_scalar(item) for item in value)
    return _is_plain_scalar(value)


def _is_plain_scalar(value: Any) -> bool:
    return isinstance(value, _SCALARS) and not (isinstance(value, float) and not math.isfinite(value))


def _json_bytes(data: dict[str, Any]) -> bytes:
    try:
        return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Dataset file content is invalid.") from None  # the cause quotes the text


def _readme(anonymized: bool) -> str:
    privacy = (
        f"Identifiers were pseudonymized and metadata filtered with anonymization policy {POLICY_VERSION}.\n"
        if anonymized
        else "No anonymization step was recorded for this export.\n"
    )
    return (
        f"# {DATASET_NAME}\n\n"
        f"Processed MRI dataset generated by {TOOL_NAME}. Images are float32 NIfTI after the\n"
        "processing steps recorded in code/run_manifest.json (when present).\n"
        + privacy
    )


def _tool_version() -> str:
    try:
        return version("mri-dataset-tool")
    except PackageNotFoundError:
        return "unknown"


def write_all(files: dict[Path, bytes]) -> list[Path]:
    """Write every file or none: an existing one → ``FileExistsError`` before writing; on any
    failure the files already written are removed, so the call can be retried."""
    if any(path.exists() for path in files):
        raise FileExistsError("Dataset file already exists.")
    written: list[Path] = []
    try:
        for path, data in files.items():
            _write_bytes(path, data)
            written.append(path)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return written


def _write_bytes(path: Path, data: bytes) -> None:
    """Atomic write (temporary file + ``os.replace``); an existing *path* is never replaced."""
    if path.exists():
        raise FileExistsError("Dataset file already exists.")
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException as error:
        tmp.unlink(missing_ok=True)
        if isinstance(error, OSError):
            raise OSError("Dataset file could not be written.") from None  # the cause quotes the path
        raise
