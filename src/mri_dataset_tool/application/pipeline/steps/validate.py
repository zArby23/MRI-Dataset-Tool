import copy
from dataclasses import replace
from typing import Any

from mri_dataset_tool.application.pipeline.step import register_step
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.processing.geometry import apply_to_series, check_modalities
from mri_dataset_tool.infrastructure.processing.validation import validate_series


@register_step("validate")
class ValidateStep:
    """Reject studies with serious integrity problems; annotate the rest (RF03).

    The volume is not changed. Each checked series gains
    ``metadata["validation"] = {"status": "ok", "findings": [codes]}``.
    """

    name = "validate"
    version = "1"

    def __init__(self, modalities: list[str] | None = None) -> None:
        check_modalities(modalities)
        self._modalities = None if modalities is None else list(modalities)

    @property
    def params(self) -> dict[str, Any]:
        return {"modalities": None if self._modalities is None else list(self._modalities)}

    def apply(self, study: MRIStudy) -> MRIStudy:
        return self.apply_with_outputs(study)[0]

    def apply_with_outputs(self, study: MRIStudy) -> tuple[MRIStudy, dict[str, Any]]:
        return apply_to_series(study, _validate, self._modalities)


def _validate(series: MRISeries) -> tuple[MRISeries, dict[str, Any]]:
    result = validate_series(series)
    # Deep copy, as replace_volume does: editing the output must not change the input.
    metadata = {**copy.deepcopy(series.metadata), "validation": {"status": "ok", "findings": list(result["findings"])}}
    return replace(series, metadata=metadata, files=list(series.files)), result
