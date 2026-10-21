from typing import Any

from mri_dataset_tool.application.pipeline.step import register_step
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.processing.geometry import apply_to_series, check_modalities, replace_volume
from mri_dataset_tool.infrastructure.processing.memory import check_allow_insufficient_memory
from mri_dataset_tool.infrastructure.processing.normalize import check_params, normalize_volume


@register_step("normalize")
class NormalizeStep:
    """Normalize intensities to ``float32`` (RF06); geometry is kept, statistics go to outputs."""

    name = "normalize"
    version = "1"

    def __init__(
        self,
        method: str = "zscore",
        mask: str = "nonzero",
        per_volume: bool = True,
        percentiles: list[float] | None = None,
        modalities: list[str] | None = None,
        allow_insufficient_memory: bool = False,
    ) -> None:
        check_params(method, mask, per_volume, percentiles)
        check_modalities(modalities)
        check_allow_insufficient_memory(allow_insufficient_memory)
        self._allow_insufficient_memory = allow_insufficient_memory
        self._method = method
        self._mask = mask
        self._per_volume = per_volume
        self._percentiles = None if percentiles is None else [float(p) for p in percentiles]
        self._modalities = None if modalities is None else list(modalities)

    @property
    def params(self) -> dict[str, Any]:
        return {
            "method": self._method,
            "mask": self._mask,
            "per_volume": self._per_volume,
            "percentiles": None if self._percentiles is None else list(self._percentiles),
            "modalities": None if self._modalities is None else list(self._modalities),
            "allow_insufficient_memory": self._allow_insufficient_memory,
        }

    def apply(self, study: MRIStudy) -> MRIStudy:
        return self.apply_with_outputs(study)[0]

    def apply_with_outputs(self, study: MRIStudy) -> tuple[MRIStudy, dict[str, Any]]:
        return apply_to_series(study, self._normalize, self._modalities)

    def _normalize(self, series: MRISeries) -> tuple[MRISeries, dict[str, Any]]:
        volume, stats = normalize_volume(
            series.volume,
            self._method,
            self._mask,
            self._per_volume,
            self._percentiles,
            self._allow_insufficient_memory,
        )
        return replace_volume(series, volume, series.metadata["affine"]), {"method": self._method, **stats}
