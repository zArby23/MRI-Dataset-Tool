"""Single access point to ``MRISeries.volume``, whether an ``ndarray`` or a lazy proxy."""

import zlib
from collections.abc import Iterator
from typing import Any

import numpy as np

# Raised by nibabel/gzip when a lazy volume's file is truncated or corrupt.
_READ_ERRORS = (OSError, EOFError, zlib.error)


def _check_dtype(dtype: Any) -> np.dtype | None:
    if dtype is None:
        return None
    try:
        resolved = np.dtype(dtype)
    except TypeError:
        raise ValueError("Invalid volume dtype.") from None
    if resolved.kind not in "iuf":
        raise ValueError("Invalid volume dtype.")
    return resolved


def load_array(volume: Any, dtype: Any = None) -> np.ndarray:
    """Materialize *volume* as an ``ndarray``; an ``ndarray`` already in *dtype* is not copied.

    With a nibabel proxy and ``dtype=None`` the result keeps the on-disk dtype (or
    float when the header scales intensities).
    """
    resolved = _check_dtype(dtype)
    try:
        return np.asarray(volume, dtype=resolved)
    except _READ_ERRORS as error:
        raise ValueError("Unable to read volume data.") from error


def iter_volumes_3d(volume: Any, dtype: Any = None) -> Iterator[np.ndarray]:
    """Yield one 3D volume at a time: the volume itself if 3D, each ``[..., t]`` if 4D."""
    resolved = _check_dtype(dtype)
    ndim = len(volume.shape)
    if ndim not in (3, 4):
        raise ValueError("Unsupported volume dimensionality.")
    if ndim == 3:
        yield load_array(volume, resolved)
        return
    for t in range(volume.shape[3]):
        try:
            frame = volume[..., t]
        except _READ_ERRORS as error:
            raise ValueError("Unable to read volume data.") from error
        yield load_array(frame, resolved)
