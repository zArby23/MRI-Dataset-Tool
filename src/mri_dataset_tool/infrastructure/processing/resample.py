"""Resampling to a fixed spacing on an RAS-aligned grid (RF08)."""

import math
from typing import Any

import numpy as np
from nibabel.orientations import io_orientation
from scipy import ndimage

from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d

INTERPOLATION_ORDERS = {"nearest": 0, "linear": 1, "cubic": 3}

# Default safety net (2**32 float32 voxels = 16 GiB, the time axis included): a tiny spacing must
# not ask for an impossible output; real 4D diffusion at 1 mm (~1.3e9 voxels) fits under it
MAX_OUTPUT_VOXELS = 2**32

# shape * voxel / spacing is ceiled; this absorbs float error (3 * 0.1 / 0.1 = 3.0000000000000004)
_CEIL_TOLERANCE = 1e-6


def check_spacing(spacing: Any) -> None:
    """Raise ``ValueError`` unless *spacing* is three finite positive numbers (mm)."""
    if not isinstance(spacing, (list, tuple)) or len(spacing) != 3:
        raise ValueError("Spacing must be three finite positive numbers.")
    for value in spacing:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("Spacing must be three finite positive numbers.")


def check_max_output_voxels(max_output_voxels: Any) -> None:
    if isinstance(max_output_voxels, bool) or not isinstance(max_output_voxels, int) or max_output_voxels <= 0:
        raise ValueError("Max output voxels must be a positive integer.")


def check_interpolation(interpolation: Any) -> None:
    if interpolation not in INTERPOLATION_ORDERS:
        raise ValueError("Unknown interpolation.")


def target_grid(shape: tuple[int, ...], affine: np.ndarray, spacing: Any) -> tuple[tuple[int, int, int], np.ndarray]:
    """Return the spatial shape and affine of the RAS-aligned output grid.

    Each world axis takes the physical extent (``shape * voxel``) of the input axis closest
    to it, so ``shape_new = ceil(shape * voxel_old / spacing)``; the grid is centered on the
    center of the input field of view. Voxel centers sit at integer indices.
    """
    affine = np.asarray(affine, dtype=float)
    spacing = np.asarray(spacing, dtype=float)
    voxel = np.linalg.norm(affine[:3, :3], axis=0)
    extents = np.empty(3)
    for axis, (world_axis, _) in enumerate(io_orientation(affine)):
        extents[int(world_axis)] = shape[axis] * voxel[axis]
    new_shape = tuple(max(1, math.ceil(e / s - _CEIL_TOLERANCE)) for e, s in zip(extents, spacing))
    center = (affine @ np.append((np.asarray(shape[:3]) - 1) / 2, 1.0))[:3]
    new_affine = np.diag(np.append(spacing, 1.0))
    new_affine[:3, 3] = center - spacing * (np.asarray(new_shape) - 1) / 2
    return new_shape, new_affine


def resample(
    volume: Any,
    affine: np.ndarray,
    spacing: Any = (1.0, 1.0, 1.0),
    interpolation: str = "linear",
    max_output_voxels: int = MAX_OUTPUT_VOXELS,
) -> tuple[np.ndarray, np.ndarray]:
    """Resample *volume* (3D or 4D, ``ndarray`` or lazy) to *spacing* on an RAS-aligned grid.

    Returns a ``float32`` volume and its affine. Oblique input is interpolated onto axis-aligned
    axes, so the output orientation is RAS. Before reducing resolution along an axis the input
    is smoothed with a Gaussian (``sigma = (factor - 1) / 2`` voxels; not with ``nearest``).
    The input is edge-padded by one voxel so the field of view's outer half voxel takes the
    edge value; output points beyond it are 0. 4D is processed one 3D volume at a time and the
    time axis is left as is. An output of more than *max_output_voxels* voxels (time axis
    included) is rejected before allocating.
    """
    check_spacing(spacing)
    check_interpolation(interpolation)
    check_max_output_voxels(max_output_voxels)
    if len(volume.shape) not in (3, 4):
        raise ValueError("Unsupported volume dimensionality.")
    affine = np.asarray(affine, dtype=float)
    shape = tuple(int(n) for n in volume.shape)
    new_shape, new_affine = target_grid(shape, affine, spacing)
    out_shape = new_shape + shape[3:]
    if math.prod(out_shape) > max_output_voxels:
        raise ValueError("Resampled volume would be too large.")

    mapping = np.linalg.inv(affine) @ new_affine  # output index -> input index
    order = INTERPOLATION_ORDERS[interpolation]
    sigma = [0.0, 0.0, 0.0]
    if order > 0:
        voxel = np.linalg.norm(affine[:3, :3], axis=0)
        for axis, (world_axis, _) in enumerate(io_orientation(affine)):
            factor = float(spacing[int(world_axis)]) / voxel[axis]
            sigma[axis] = max(0.0, (factor - 1) / 2)

    frames = iter_volumes_3d(volume, np.float32)
    out = np.empty(out_shape, dtype=np.float32)
    t = 0  # no enumerate(): its cached tuple would keep the previous frame alive
    for frame in frames:
        if any(sigma):
            frame = ndimage.gaussian_filter(frame, sigma, mode="nearest")
        frame = np.pad(frame, 1, mode="edge")
        target = out if len(shape) == 3 else out[..., t]
        target[...] = ndimage.affine_transform(
            frame, mapping[:3, :3], offset=mapping[:3, 3] + 1, output_shape=new_shape, order=order, mode="constant", cval=0.0
        )
        del frame, target  # release this frame before reading the next (RNF02)
        t += 1
    return out, new_affine
