from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MRISeries:
    series_uid: str
    modality: str
    files: list[Path]
    
    metadata: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)