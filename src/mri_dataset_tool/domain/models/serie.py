from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np


class VolumeLike(Protocol):
    """Array-like volume read on demand (e.g. a nibabel proxy); ``ndarray`` also fits."""

    shape: tuple[int, ...]
    dtype: np.dtype

    def __array__(self, dtype: Any = None) -> np.ndarray: ...

    def __getitem__(self, key: Any) -> np.ndarray: ...


@dataclass
class MRISeries:
    series_uid: str | None = None
    modality: str | None = None
    files: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    volume: np.ndarray | VolumeLike | None = None

    def get(
        self, 
        key: str, 
        default: Any | None = None
    ) -> Any:
        return self.metadata.get(key, default)