"""Per-study metadata summary (RF04, "extract" part) built only from the anonymization allow lists."""

import math
from typing import Any

import numpy as np

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.anonymization.policy import (
    FILTERED_METADATA_KEYS,
    METADATA_WHITELIST,
    SIDECAR_WHITELIST,
    filter_validation,
)
from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d

_DROP = object()


def summarize_study(study: MRIStudy) -> dict[str, Any]:
    """Return a JSON-ready, deterministic summary of *study*.

    Only allow-listed metadata keys and sidecar keys are included; UIDs, paths and
    subject/session ids never are. The intensity range is computed one 3D volume at a
    time, so a lazy volume is never fully materialized.
    """
    return {
        "series_count": len(study.series),
        "series": [_summarize_series(series) for series in study.series],
    }


def _summarize_series(series: MRISeries) -> dict[str, Any]:
    summary: dict[str, Any] = {"modality": series.modality}
    for key in sorted(METADATA_WHITELIST - FILTERED_METADATA_KEYS):
        if key in series.metadata and (value := _plain(series.metadata[key])) is not _DROP:
            summary[key] = value
    sidecar = series.metadata.get("sidecar")
    if isinstance(sidecar, dict):
        technical = {k: _scalar_or_list(sidecar[k]) for k in sorted(SIDECAR_WHITELIST) if k in sidecar}
        summary["sidecar"] = {k: v for k, v in technical.items() if v is not _DROP}
    if validation := filter_validation(series.metadata.get("validation")):
        summary["validation"] = validation
    volume = series.volume
    summary["dtype"] = None if volume is None else str(np.dtype(volume.dtype))
    summary["intensity"] = None if volume is None else _intensity(volume)
    return summary


def _intensity(volume: Any) -> dict[str, Any] | None:
    """min/max/mean/std over the finite voxels, plus how many were not finite."""
    count, mean, m2 = 0, 0.0, 0.0
    low, high = math.inf, -math.inf
    non_finite = 0
    for frame in iter_volumes_3d(volume, np.float64):
        finite = np.isfinite(frame)
        values = frame[finite]
        non_finite += int(frame.size - values.size)
        del frame, finite
        if values.size == 0:
            continue
        # Chan et al. parallel combination, as in normalize.
        n, part_mean = values.size, float(values.mean())
        delta = part_mean - mean
        total = count + n
        mean += delta * n / total
        m2 += float(((values - part_mean) ** 2).sum()) + delta**2 * count * n / total
        count = total
        low, high = min(low, float(values.min())), max(high, float(values.max()))
    if count == 0:
        return {"min": None, "max": None, "mean": None, "std": None, "non_finite_voxels": non_finite}
    return {"min": low, "max": high, "mean": mean, "std": math.sqrt(m2 / count), "non_finite_voxels": non_finite}


def _plain(value: Any) -> Any:
    """Convert to basic JSON types; anything else (paths, objects, NaN/Inf) is dropped."""
    if isinstance(value, dict):
        items = {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
        return {k: v for k, v in items.items() if v is not _DROP}
    if isinstance(value, (list, tuple, np.ndarray)):
        items = [_plain(v) for v in (value.tolist() if isinstance(value, np.ndarray) else value)]
        return _DROP if any(v is _DROP for v in items) else items
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int, float)):
        return value if _finite(value) else _DROP
    return _DROP


def _scalar_or_list(value: Any) -> Any:
    """Sidecar rule of the policy: a finite scalar or a list of them, nothing nested."""
    scalar = (str, bool, int, float)
    if isinstance(value, scalar):
        return value if _finite(value) else _DROP
    if isinstance(value, list) and all(isinstance(v, scalar) and _finite(v) for v in value):
        return list(value)
    return _DROP


def _finite(value: Any) -> bool:
    return not isinstance(value, float) or math.isfinite(value)
