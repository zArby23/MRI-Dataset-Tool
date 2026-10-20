"""Reorientation by axis permutation and flips only, without interpolation (RF07)."""

from typing import Any

import nibabel as nib
import numpy as np
from nibabel.orientations import apply_orientation, axcodes2ornt, inv_ornt_aff, io_orientation, ornt_transform

from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d

_AXIS_LABELS = (("L", "R"), ("P", "A"), ("I", "S"))


def check_target(target: Any) -> None:
    """Raise ``ValueError`` unless *target* is three axis codes, one per world axis (e.g. ``"RAS"``)."""
    if not isinstance(target, str) or len(target) != 3:
        raise ValueError("Invalid target orientation.")
    axes = [next((i for i, pair in enumerate(_AXIS_LABELS) if code in pair), None) for code in target]
    if sorted(a for a in axes if a is not None) != [0, 1, 2]:
        raise ValueError("Invalid target orientation.")


def reorient(volume: Any, affine: np.ndarray, target: str = "RAS") -> tuple[np.ndarray, np.ndarray]:
    """Return *volume* (3D or 4D, ``ndarray`` or lazy) and *affine* reoriented to *target*.

    Only permutes and flips the spatial axes, so voxel values and the world point of each
    voxel are kept; the time axis is left as is. With an oblique affine the closest
    orientation is reached and the residual obliquity stays in the affine. The dtype is
    the one ``load_array`` gives (the ``ndarray``'s own, or the proxy's on-disk/scaled one).
    """
    check_target(target)
    if len(volume.shape) not in (3, 4):
        raise ValueError("Unsupported volume dimensionality.")
    affine = np.asarray(affine, dtype=float)
    transform = ornt_transform(io_orientation(affine), axcodes2ornt(tuple(target)))
    new_affine = affine @ inv_ornt_aff(transform, volume.shape[:3])

    frames = iter_volumes_3d(volume)
    if len(volume.shape) == 3:
        return np.ascontiguousarray(apply_orientation(next(frames), transform)), new_affine

    # 4D frame by frame: peak is the output plus one input frame (RNF02)
    out: np.ndarray | None = None
    for t, frame in enumerate(frames):
        oriented = apply_orientation(frame, transform)
        if out is None:
            out = np.empty(oriented.shape + (volume.shape[3],), dtype=oriented.dtype)
        out[..., t] = oriented
    if out is None:
        raise ValueError("Volume is empty.")
    return out, new_affine


def orientation_code(affine: np.ndarray) -> str:
    return "".join(nib.aff2axcodes(affine))
