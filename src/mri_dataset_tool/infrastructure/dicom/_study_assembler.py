from collections.abc import Iterable, Iterator
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pydicom
import pydicom.config
from pydicom.dataset import Dataset

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy

DICOM_HEADER_TAGS = [
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "Modality",
    "Rows",
    "Columns",
    "PixelSpacing",
    "SliceThickness",
    "SpacingBetweenSlices",
    "ImageOrientationPatient",
    "ImagePositionPatient",
    "RescaleSlope",
    "RescaleIntercept",
    "TemporalPositionIdentifier",
    "AcquisitionNumber",
]


@dataclass(frozen=True)
class DICOMInstanceHeader:
    """Minimum DICOM information required to build domain study models."""

    path: Path
    study_uid: str | None
    series_uid: str | None
    modality: str | None
    metadata: dict[str, Any]


@dataclass
class _SeriesAccumulator:
    modality: str | None
    metadata: dict[str, Any]
    files: list[Path] = field(default_factory=list)


_quiet_lock = threading.Lock()
_quiet_depth = 0
_quiet_previous: int | None = None


@contextmanager
def quiet_value_validation() -> Iterator[None]:
    """Skip pydicom's value validation while reading: its warnings quote the value
    (a non-conformant UID) on stderr and the ``pydicom`` logger. It only warns, so the files
    accepted or rejected are the same. Wrap the read and every element access.

    The setting is process-wide: the first thread to enter sets it and the last to leave restores it,
    so overlapping reads (nested or in other threads) never restore it early."""
    global _quiet_depth, _quiet_previous
    settings = pydicom.config.settings
    with _quiet_lock:
        if _quiet_depth == 0:
            _quiet_previous = settings.reading_validation_mode
            settings.reading_validation_mode = pydicom.config.IGNORE
        _quiet_depth += 1
    try:
        yield
    finally:
        with _quiet_lock:
            _quiet_depth -= 1
            if _quiet_depth == 0:
                settings.reading_validation_mode = _quiet_previous


def read_dicom_header(path: Path) -> DICOMInstanceHeader:
    """Read only the DICOM header elements required by the readers."""
    with quiet_value_validation():
        dataset = pydicom.dcmread(
            path,
            stop_before_pixels=True,
            specific_tags=DICOM_HEADER_TAGS,
        )
        return DICOMInstanceHeader(
            path=path,
            study_uid=_as_optional_str(dataset.get("StudyInstanceUID")),
            series_uid=_as_optional_str(dataset.get("SeriesInstanceUID")),
            modality=_as_optional_str(dataset.get("Modality")),
            metadata=extract_series_metadata(dataset),
        )


def extract_series_metadata(dataset: Dataset) -> dict[str, Any]:
    """Extract the stable, current MRISeries metadata contract."""
    return {
        "rows": dataset.get("Rows"),
        "columns": dataset.get("Columns"),
        "pixel_spacing": _as_list(dataset.get("PixelSpacing")),
        "slice_thickness": dataset.get("SliceThickness"),
        "spacing_between_slices": dataset.get("SpacingBetweenSlices"),
        "image_orientation": _as_list(dataset.get("ImageOrientationPatient")),
    }


def assemble_study(
    study_uid: str,
    headers: Iterable[DICOMInstanceHeader],
) -> MRIStudy:
    """Build a study from validated headers belonging to one study UID."""
    series_by_uid: dict[str, _SeriesAccumulator] = {}

    for header in headers:
        if header.study_uid != study_uid or header.series_uid is None:
            continue

        accumulator = series_by_uid.setdefault(
            header.series_uid,
            _SeriesAccumulator(
                modality=header.modality or "Unknown",
                metadata=header.metadata,
            ),
        )
        accumulator.files.append(header.path)

    series = [
        MRISeries(
            series_uid=series_uid,
            modality=accumulator.modality,
            files=sorted(accumulator.files),
            metadata=accumulator.metadata,
        )
        for series_uid, accumulator in sorted(series_by_uid.items())
    ]
    return MRIStudy(study_uid=study_uid, series=series)


def _as_optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _as_list(value: Any) -> Any:
    if value is None or isinstance(value, (str, bytes)):
        return value
    try:
        return list(value)
    except TypeError:
        return value
