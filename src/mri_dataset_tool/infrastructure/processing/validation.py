"""Volume integrity checks (RF03): serious problems raise, the rest are reported as finding codes."""

import math
from typing import Any

import numpy as np

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d
from mri_dataset_tool.infrastructure.processing.geometry import validate_geometry

# Non-serious finding codes (Q6): the study passes and they are recorded.
CONSTANT_VOLUME = "CONSTANT_VOLUME"
SINGLE_VOLUME_4D = "SINGLE_VOLUME_4D"


def validate_series(series: MRISeries) -> dict[str, Any]:
    """Check *series* and return ``{"findings": [codes], "volumes_checked": n}``.

    Serious problems raise ``ValueError`` with a fixed message: missing or incoherent
    geometry, empty volume, null or non-finite voxel size, NaN/Inf values. A lazy volume
    is read one 3D volume at a time; NaN/Inf can't occur when the on-disk dtype is integer.
    """
    validate_geometry(series)
    volume = series.volume
    if 0 in volume.shape:
        raise ValueError("Volume is empty.")
    _check_voxel_size(series.metadata.get("voxel_size"))

    check_finite = np.dtype(volume.dtype).kind == "f"
    low, high = math.inf, -math.inf
    volumes_checked = 0
    # float64 per 3D volume: exact for every NIfTI dtype and for scaled integer data.
    for frame in iter_volumes_3d(volume, np.float64):
        if check_finite and not np.isfinite(frame).all():
            raise ValueError("Volume contains non-finite values.")
        low, high = min(low, float(frame.min())), max(high, float(frame.max()))
        volumes_checked += 1
        del frame

    findings = []
    if low == high:
        findings.append(CONSTANT_VOLUME)
    if len(volume.shape) == 4 and volume.shape[3] == 1:
        findings.append(SINGLE_VOLUME_4D)
    return {"findings": findings, "volumes_checked": volumes_checked}


def _check_voxel_size(raw: Any) -> None:
    try:
        voxel_size = np.asarray(raw, dtype=float)
    except (TypeError, ValueError):
        raise ValueError("Voxel size must be three positive finite numbers.") from None
    if voxel_size.shape != (3,) or not np.all(np.isfinite(voxel_size)) or np.any(voxel_size <= 0):
        raise ValueError("Voxel size must be three positive finite numbers.")
