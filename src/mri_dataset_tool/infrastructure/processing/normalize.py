"""Intensity normalization (RF06): zscore, minmax and percentile, over an optional foreground mask."""

from typing import Any

import numpy as np

from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d

METHODS = ("zscore", "minmax", "percentile")
MASKS = ("nonzero", "none")


def check_params(method: str, mask: str, per_volume: bool, percentiles: Any) -> None:
    """Raise ``ValueError`` with a fixed message unless the parameters are coherent."""
    if method not in METHODS:
        raise ValueError("Unknown normalization method.")
    if mask not in MASKS:
        raise ValueError("Unknown normalization mask.")
    if not isinstance(per_volume, bool):
        raise ValueError("per_volume must be a boolean.")
    if method != "percentile":
        if percentiles is not None:
            raise ValueError("Percentiles are only used by the percentile method.")
        return
    if (
        not isinstance(percentiles, (list, tuple))
        or len(percentiles) != 2
        or not all(isinstance(p, (int, float)) and not isinstance(p, bool) for p in percentiles)
        or not 0 <= percentiles[0] < percentiles[1] <= 100
    ):
        raise ValueError("Percentiles must be [low, high] with 0 <= low < high <= 100.")


def normalize_volume(
    volume: Any,
    method: str = "zscore",
    mask: str = "nonzero",
    per_volume: bool = True,
    percentiles: Any = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return the normalized ``float32`` volume and the statistics used.

    Statistics come from the voxels in the mask (``nonzero``: input != 0); voxels outside
    the mask stay 0. A 4D volume is processed one 3D volume at a time: with *per_volume*
    each gets its own statistics (``{"volumes": [...]}``), otherwise one global set.
    Empty mask, constant data or NaN/Inf raise ``ValueError`` with a fixed message.
    """
    check_params(method, mask, per_volume, percentiles)
    four_d = len(volume.shape) == 4
    if not four_d:
        (frame,) = iter_volumes_3d(volume, np.float64)
        selected = _mask(frame, mask)
        stats = _stats(frame[selected], method, percentiles)
        return _transform(frame, selected, stats, method), stats

    output = np.empty(volume.shape, dtype=np.float32)
    if per_volume:
        volumes = []
        for t, frame in enumerate(iter_volumes_3d(volume, np.float64)):
            selected = _mask(frame, mask)
            stats = _stats(frame[selected], method, percentiles)
            output[..., t] = _transform(frame, selected, stats, method)
            volumes.append(stats)
        return output, {"volumes": volumes}

    stats = _global_stats(volume, mask, method, percentiles)
    for t, frame in enumerate(iter_volumes_3d(volume, np.float64)):
        output[..., t] = _transform(frame, _mask(frame, mask), stats, method)
    return output, stats


def _mask(frame: np.ndarray, mask: str) -> np.ndarray:
    return frame != 0 if mask == "nonzero" else np.ones(frame.shape, dtype=bool)


def _check_values(values: np.ndarray) -> None:
    if not np.isfinite(values).all():
        raise ValueError("Volume contains non-finite values.")


def _stats(values: np.ndarray, method: str, percentiles: Any) -> dict[str, float]:
    if values.size == 0:
        raise ValueError("Normalization mask is empty.")
    _check_values(values)
    if method == "zscore":
        stats = {"mean": float(values.mean()), "std": float(values.std())}
    elif method == "minmax":
        stats = {"min": float(values.min()), "max": float(values.max())}
    else:
        low, high = np.percentile(values, percentiles)
        stats = {"low": float(low), "high": float(high)}
    _check_not_constant(stats, method)
    return stats


def _global_stats(volume: Any, mask: str, method: str, percentiles: Any) -> dict[str, float]:
    """First pass over a 4D volume: combine per-volume statistics without holding all of it."""
    count, mean, m2 = 0, 0.0, 0.0
    low, high = np.inf, -np.inf
    parts: list[np.ndarray] = []
    for frame in iter_volumes_3d(volume, np.float64):
        values = frame[_mask(frame, mask)]
        del frame
        if values.size == 0:
            continue
        _check_values(values)
        if method == "zscore":
            # Chan et al. parallel combination of mean and sum of squared deviations.
            n, part_mean = values.size, float(values.mean())
            delta = part_mean - mean
            total = count + n
            mean += delta * n / total
            m2 += float(((values - part_mean) ** 2).sum()) + delta**2 * count * n / total
            count = total
        elif method == "minmax":
            low, high = min(low, float(values.min())), max(high, float(values.max()))
            count += values.size
        else:
            # shortcut: keeps every masked value as float32 (~the 4D volume in float32); upgrade to a histogram if memory bites.
            parts.append(values.astype(np.float32))
            count += values.size
    if count == 0:
        raise ValueError("Normalization mask is empty.")
    if method == "zscore":
        stats = {"mean": mean, "std": float(np.sqrt(m2 / count))}
    elif method == "minmax":
        stats = {"min": low, "max": high}
    else:
        p_low, p_high = np.percentile(np.concatenate(parts), percentiles)
        stats = {"low": float(p_low), "high": float(p_high)}
    _check_not_constant(stats, method)
    return stats


def _check_not_constant(stats: dict[str, float], method: str) -> None:
    spread = stats["std"] if method == "zscore" else stats[_HIGH[method]] - stats[_LOW[method]]
    if not spread > 0:
        raise ValueError("Volume is constant within the normalization mask.")


_LOW = {"minmax": "min", "percentile": "low"}
_HIGH = {"minmax": "max", "percentile": "high"}


def _transform(frame: np.ndarray, selected: np.ndarray, stats: dict[str, float], method: str) -> np.ndarray:
    if method == "zscore":
        result = (frame - stats["mean"]) / stats["std"]
    else:
        low, high = stats[_LOW[method]], stats[_HIGH[method]]
        result = (np.clip(frame, low, high) - low) / (high - low)
    result[~selected] = 0.0
    return result.astype(np.float32)
