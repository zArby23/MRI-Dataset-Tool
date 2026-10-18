from dataclasses import replace
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
from pydicom.dataset import Dataset

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# LPS (DICOM) <-> RAS+ (NIfTI) is the same sign flip of the x and y axes in both directions.
_FLIP_XY = np.diag([-1.0, -1.0, 1.0, 1.0])
_SPACING_TOLERANCE = 1e-2  # relative to the mean slice spacing
IN_PLANE_TOLERANCE_MM = 1e-3  # max in-plane drift of slice origins (shared with the writer)


def lps_to_ras(affine: np.ndarray) -> np.ndarray:
    """Convert a 4x4 voxel->world affine from LPS to RAS+."""
    return _FLIP_XY @ affine


def ras_to_lps(affine: np.ndarray) -> np.ndarray:
    """Convert a 4x4 voxel->world affine from RAS+ to LPS."""
    return _FLIP_XY @ affine


def build_series_volume(series: MRISeries) -> MRISeries:
    """Load pixels of a single-frame MR series into a 3D or 4D RAS+ volume.

    Returns a new series; the input is not modified. Errors never include header values.
    """
    if not series.files:
        raise ValueError("The series has no files.")

    datasets = [_read_slice(path) for path in series.files]
    first = datasets[0]
    row_dir, col_dir, pixel_spacing = _check_geometry(datasets)
    normal = np.cross(row_dir, col_dir)

    positions = [
        float(np.dot(np.asarray(d.ImagePositionPatient, dtype=float), normal))
        for d in datasets
    ]
    offsets = np.array(
        [np.asarray(d.ImagePositionPatient, dtype=float) - pos * normal
         for d, pos in zip(datasets, positions)]
    )
    if np.abs(offsets - offsets[0]).max() > IN_PLANE_TOLERANCE_MM:
        raise ValueError("Slices are shifted in-plane or tilted (gantry tilt is not supported).")
    frames = _group_by_time(datasets, positions)
    slice_count = len(frames[0])
    reference_positions = [p for p, _ in frames[0]]
    for frame in frames:
        frame_positions = [p for p, _ in frame]
        if len(frame_positions) != slice_count or not np.allclose(
            frame_positions, reference_positions, atol=1e-3
        ):
            raise ValueError("Time points do not share the same slice positions.")

    slice_spacing = _slice_spacing(reference_positions, first)
    origin = np.asarray(frames[0][0][1].ImagePositionPatient, dtype=float)

    volume = np.stack(
        [np.stack([_pixels(d) for _, d in frame], axis=-1) for frame in frames],
        axis=-1,
    )  # (rows, cols, slices, time)
    volume = volume.transpose(1, 0, 2, 3)  # NIfTI index order: (i=column, j=row, k, t)
    if volume.shape[3] == 1:
        volume = volume[..., 0]

    affine_lps = np.eye(4)
    affine_lps[:3, 0] = row_dir * pixel_spacing[1]  # step along increasing column index
    affine_lps[:3, 1] = col_dir * pixel_spacing[0]  # step along increasing row index
    affine_lps[:3, 2] = normal * slice_spacing
    affine_lps[:3, 3] = origin
    affine = lps_to_ras(affine_lps)

    metadata = dict(series.metadata)
    metadata.update(
        shape=tuple(int(n) for n in volume.shape),
        voxel_size=(pixel_spacing[1], pixel_spacing[0], slice_spacing),
        affine=affine,
        orientation=nib.aff2axcodes(affine),
    )
    logger.info("Built DICOM volume with shape %s", metadata["shape"])
    return replace(series, volume=volume, metadata=metadata)


def _read_slice(path: Path) -> Dataset:
    try:
        dataset = pydicom.dcmread(path)
    except (pydicom.errors.InvalidDicomError, OSError, EOFError) as error:
        raise ValueError("A series file could not be read as DICOM.") from error

    if int(dataset.get("NumberOfFrames", 1) or 1) > 1:
        raise ValueError("Multi-frame DICOM is not supported.")
    if "MOSAIC" in [str(t).upper() for t in dataset.get("ImageType", [])]:
        raise ValueError("Siemens mosaic DICOM is not supported.")
    if int(dataset.get("SamplesPerPixel", 1)) > 1:
        raise ValueError("Multi-sample (e.g. RGB) DICOM is not supported.")
    for tag in ("Rows", "Columns", "PixelSpacing", "ImageOrientationPatient",
                "ImagePositionPatient", "PixelData"):
        if tag not in dataset:
            raise ValueError(f"A series file is missing required element {tag}.")
    return dataset


def _check_geometry(
    datasets: list[Dataset],
) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    first = datasets[0]
    for d in datasets[1:]:
        if (d.Rows, d.Columns) != (first.Rows, first.Columns):
            raise ValueError("Slices have inconsistent Rows/Columns.")
        if not np.allclose(d.ImageOrientationPatient, first.ImageOrientationPatient, atol=1e-4):
            raise ValueError("Slices have inconsistent ImageOrientationPatient.")
        if not np.allclose(d.PixelSpacing, first.PixelSpacing, atol=1e-4):
            raise ValueError("Slices have inconsistent PixelSpacing.")

    iop = np.asarray(first.ImageOrientationPatient, dtype=float)
    spacing = tuple(float(s) for s in first.PixelSpacing)
    return iop[:3], iop[3:], (spacing[0], spacing[1])


def _group_by_time(
    datasets: list[Dataset], positions: list[float]
) -> list[list[tuple[float, Dataset]]]:
    """Group slices into time points and sort each group along the slice normal."""
    groups: dict[int, list[tuple[float, Dataset]]] = {}
    for position, dataset in zip(positions, datasets):
        key = dataset.get("TemporalPositionIdentifier", dataset.get("AcquisitionNumber", 0))
        groups.setdefault(int(key or 0), []).append((position, dataset))
    return [sorted(groups[key], key=lambda item: item[0]) for key in sorted(groups)]


def _slice_spacing(positions: list[float], first: Dataset) -> float:
    if len(positions) == 1:
        thickness = first.get("SliceThickness")
        if thickness is None:
            raise ValueError("Cannot determine slice spacing of a single slice.")
        return float(thickness)

    steps = np.diff(positions)
    mean = float(steps.mean())
    if mean <= 1e-6 or np.abs(steps - mean).max() > _SPACING_TOLERANCE * mean:
        raise ValueError("Slice spacing is not uniform or slices share a position.")
    return mean


def _pixels(dataset: Dataset) -> np.ndarray:
    slope = float(dataset.get("RescaleSlope", 1.0))
    intercept = float(dataset.get("RescaleIntercept", 0.0))
    try:
        array = dataset.pixel_array
    except (RuntimeError, NotImplementedError, ValueError) as error:
        raise ValueError("Pixel data of a series file could not be decoded.") from error
    return array.astype(np.float64) * slope + intercept
