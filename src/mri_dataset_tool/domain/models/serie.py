from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class MRISeries:
    series_uid: str | None = None
    modality: str | None = None
    files: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    volume: np.ndarray | None = None

    def get(
        self, 
        key: str, 
        default: Any | None = None
    ) -> Any:
        return self.metadata.get(key, default)