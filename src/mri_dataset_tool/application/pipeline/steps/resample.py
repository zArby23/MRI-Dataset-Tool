from dataclasses import dataclass, field
from typing import Any, ClassVar

from mri_dataset_tool.application.pipeline.step import register_step
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.processing.geometry import (
    apply_to_series,
    check_modalities,
    replace_volume,
    validate_geometry,
)
from mri_dataset_tool.infrastructure.processing.memory import check_allow_insufficient_memory
from mri_dataset_tool.infrastructure.processing.resample import (
    MAX_OUTPUT_VOXELS,
    check_interpolation,
    check_max_output_voxels,
    check_spacing,
    resample,
)


@register_step("resample")
@dataclass(frozen=True)
class ResampleStep:
    """Resample each selected series to *spacing* mm (RF08); see ``docs/processing/geometry.md``.

    Outputs per series: resulting ``shape`` and ``spacing``.
    """

    spacing: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    interpolation: str = "linear"
    modalities: list[str] | None = None
    max_output_voxels: int = MAX_OUTPUT_VOXELS
    allow_insufficient_memory: bool = False
    name: ClassVar[str] = "resample"
    version: ClassVar[str] = "1"

    def __post_init__(self) -> None:
        check_spacing(self.spacing)
        check_interpolation(self.interpolation)
        check_modalities(self.modalities)
        check_max_output_voxels(self.max_output_voxels)
        check_allow_insufficient_memory(self.allow_insufficient_memory)
        object.__setattr__(self, "spacing", [float(s) for s in self.spacing])  # JSON floats, not shared with the caller
        if self.modalities is not None:
            object.__setattr__(self, "modalities", list(self.modalities))

    @property
    def params(self) -> dict[str, Any]:
        return {
            "spacing": list(self.spacing),
            "interpolation": self.interpolation,
            "modalities": None if self.modalities is None else list(self.modalities),
            "max_output_voxels": self.max_output_voxels,
            "allow_insufficient_memory": self.allow_insufficient_memory,
        }

    def apply_with_outputs(self, study: MRIStudy) -> tuple[MRIStudy, dict[str, Any]]:
        return apply_to_series(study, self._resample_series, self.modalities)

    def apply(self, study: MRIStudy) -> MRIStudy:
        return self.apply_with_outputs(study)[0]

    def _resample_series(self, series: MRISeries) -> tuple[MRISeries, dict[str, Any]]:
        validate_geometry(series)
        volume, affine = resample(
            series.volume,
            series.metadata["affine"],
            self.spacing,
            self.interpolation,
            self.max_output_voxels,
            self.allow_insufficient_memory,
        )
        result = replace_volume(series, volume, affine)
        return result, {"shape": list(result.metadata["shape"]), "spacing": list(result.metadata["voxel_size"])}
