from dataclasses import dataclass
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
from mri_dataset_tool.infrastructure.processing.reorient import check_target, orientation_code, reorient


@register_step("reorient")
@dataclass(frozen=True)
class ReorientStep:
    """Reorient each selected series to *target* (RF07); see ``docs/processing/geometry.md``.

    Outputs per series: ``source`` and ``target`` orientation codes.
    """

    target: str = "RAS"
    modalities: list[str] | None = None
    name: ClassVar[str] = "reorient"
    version: ClassVar[str] = "1"

    def __post_init__(self) -> None:
        check_target(self.target)
        check_modalities(self.modalities)
        if self.modalities is not None:
            object.__setattr__(self, "modalities", list(self.modalities))  # not shared with the caller

    @property
    def params(self) -> dict[str, Any]:
        return {"target": self.target, "modalities": None if self.modalities is None else list(self.modalities)}

    def apply_with_outputs(self, study: MRIStudy) -> tuple[MRIStudy, dict[str, Any]]:
        return apply_to_series(study, self._reorient_series, self.modalities)

    def apply(self, study: MRIStudy) -> MRIStudy:
        return self.apply_with_outputs(study)[0]

    def _reorient_series(self, series: MRISeries) -> tuple[MRISeries, dict[str, Any]]:
        validate_geometry(series)
        affine = series.metadata["affine"]
        volume, new_affine = reorient(series.volume, affine, self.target)
        result = replace_volume(series, volume, new_affine)
        return result, {"source": orientation_code(affine), "target": orientation_code(new_affine)}
