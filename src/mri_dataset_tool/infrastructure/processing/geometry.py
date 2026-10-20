import copy
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

import nibabel as nib
import numpy as np

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy


def replace_volume(series: MRISeries, volume: Any, affine: np.ndarray) -> MRISeries:
    """Return a new series holding *volume* with the canonical geometry recomputed.

    The only place processing writes ``shape``, ``voxel_size``, ``affine`` and
    ``orientation``: voxel size comes from the affine columns and orientation from
    ``nib.aff2axcodes``. The rest of ``metadata`` (deep-copied, so nested dicts such as
    ``bids``, ``sidecar`` or ``provenance`` are not shared with the input) and ``files``
    is kept.
    """
    affine = _as_affine(affine)
    metadata = {
        **copy.deepcopy({k: v for k, v in series.metadata.items() if k not in _GEOMETRY_KEYS}),
        "shape": tuple(int(n) for n in volume.shape),
        "voxel_size": tuple(float(v) for v in np.linalg.norm(affine[:3, :3], axis=0)),
        "affine": affine,
        "orientation": nib.aff2axcodes(affine),
    }
    return replace(series, volume=volume, metadata=metadata, files=list(series.files))


def validate_geometry(series: MRISeries) -> None:
    """Raise ``ValueError`` unless *series* has a volume and a coherent canonical geometry."""
    if series.volume is None:
        raise ValueError("Series has no volume.")
    if "affine" not in series.metadata:
        raise ValueError("Series has no affine.")
    _as_affine(series.metadata["affine"])
    try:
        shape = tuple(series.metadata.get("shape", ()))
    except TypeError:
        shape = None
    if shape != tuple(series.volume.shape):
        raise ValueError("Series shape does not match its volume.")


def check_modalities(modalities: Sequence[str] | None) -> None:
    """Raise ``ValueError`` unless *modalities* is ``None`` or a list of strings (``params.modalities``)."""
    if modalities is None:
        return
    if isinstance(modalities, str) or not isinstance(modalities, (list, tuple)):
        raise ValueError("Modalities must be a list of strings.")
    if not all(isinstance(m, str) for m in modalities):
        raise ValueError("Modalities must be a list of strings.")


def apply_to_series(
    study: MRIStudy,
    transform: Callable[[MRISeries], tuple[MRISeries, dict[str, Any]]],
    modalities: Sequence[str] | None = None,
) -> tuple[MRIStudy, dict[str, Any]]:
    """Apply *transform* to the selected series (Q12); return the new study and its outputs.

    Selected: series with a volume and, when *modalities* is given, a ``modality`` in it
    (``modality=None`` is then left out; ``[]`` selects nothing). The other series are kept
    as they are. *transform* returns the new series and its computed values; the outputs
    follow the ``StepRecord.outputs`` convention ``{"series": [{"index": i, ...}]}``, with
    ``i`` the position in ``study.series``, for the transformed series only.
    """
    check_modalities(modalities)
    series_list: list[MRISeries] = []
    outputs: list[dict[str, Any]] = []
    for index, series in enumerate(study.series):
        if series.volume is not None and (modalities is None or series.modality in modalities):
            series, values = transform(series)
            outputs.append({"index": index, **values})
        series_list.append(series)
    return replace(study, series=series_list), {"series": outputs}


_GEOMETRY_KEYS = ("shape", "voxel_size", "affine", "orientation")


def _as_affine(raw: Any) -> np.ndarray:
    try:
        affine = np.array(raw, dtype=float)
    except (TypeError, ValueError):
        raise ValueError("Affine must be a 4x4 matrix.") from None  # the cause quotes the value
    if affine.shape != (4, 4):
        raise ValueError("Affine must be a 4x4 matrix.")
    if not np.all(np.isfinite(affine)):
        raise ValueError("Affine must be finite.")
    if not np.array_equal(affine[3], [0.0, 0.0, 0.0, 1.0]):
        raise ValueError("Affine must have [0, 0, 0, 1] as its last row.")
    if np.linalg.matrix_rank(affine) < 4:
        raise ValueError("Affine must be invertible.")
    return affine
