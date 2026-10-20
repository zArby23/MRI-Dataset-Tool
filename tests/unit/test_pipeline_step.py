import ast
import json
from dataclasses import dataclass, replace
from typing import Any, ClassVar

import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.step import (
    STEP_REGISTRY,
    ProcessingStep,
    build_step,
    register_step,
)
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models import transformation
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StepRecord, StudyReport


@register_step("test.scale")
@dataclass(frozen=True)
class ScaleStep:
    factor: float = 1.0
    name: ClassVar[str] = "test.scale"
    version: ClassVar[str] = "1"

    @property
    def params(self) -> dict[str, Any]:
        return {"factor": self.factor}

    def apply(self, study: MRIStudy) -> MRIStudy:
        return replace(
            study,
            series=[replace(s, volume=s.volume * self.factor) for s in study.series],
        )


def _study() -> MRIStudy:
    series = MRISeries(volume=np.ones((2, 2, 2)), metadata={"shape": (2, 2, 2)})
    return MRIStudy(study_uid=None, series=[series])


def test_step_does_not_mutate_input_and_returns_new_study() -> None:
    study = _study()
    original_volume = study.series[0].volume.copy()
    step: ProcessingStep = ScaleStep(factor=3.0)

    result = step.apply(study)

    assert result is not study
    assert result.series[0] is not study.series[0]
    np.testing.assert_array_equal(study.series[0].volume, original_volume)
    np.testing.assert_array_equal(result.series[0].volume, original_volume * 3.0)


def test_build_step_rebuilds_registered_step() -> None:
    step = ScaleStep(factor=2.0)

    rebuilt = build_step(step.name, step.params)

    assert STEP_REGISTRY["test.scale"] is ScaleStep
    assert rebuilt == step
    assert (rebuilt.name, rebuilt.version, rebuilt.params) == ("test.scale", "1", {"factor": 2.0})


def test_build_step_without_params_uses_defaults() -> None:
    assert build_step("test.scale") == ScaleStep()


def test_build_step_unknown_name_raises_without_echoing_it() -> None:
    with pytest.raises(ValueError, match="Unknown processing step") as info:
        build_step("secret-name")
    assert "secret-name" not in str(info.value)


@register_step("test.required")
def _required_step(factor: float) -> ProcessingStep:
    return ScaleStep(factor=factor)


@register_step("test.broken")
def _broken_step() -> ProcessingStep:
    raise TypeError("internal factory bug")


@pytest.mark.parametrize(
    ("name", "params"),
    [("test.scale", {"bogus": 1}), ("test.required", {})],
)
def test_build_step_unknown_or_missing_params_raise_value_error(name: str, params: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="Invalid parameters") as info:
        build_step(name, params)
    assert isinstance(info.value.__cause__, TypeError)


def test_build_step_propagates_internal_type_error() -> None:
    with pytest.raises(TypeError, match="internal factory bug"):
        build_step("test.broken")


def test_register_step_rejects_duplicate_name() -> None:
    with pytest.raises(ValueError, match="already registered"):
        register_step("test.scale")(ScaleStep)
    assert STEP_REGISTRY["test.scale"] is ScaleStep


def _report() -> StudyReport:
    return StudyReport(
        index=2,
        source_path="input/sub-01_T1w.nii.gz",
        steps=[
            StepRecord("test.scale", "1", {"factor": 2.0, "axes": [0, 1]}, "ok"),
            StepRecord("test.other", "3", {}, "failed", error_type="ValueError"),
        ],
    )


def test_step_record_round_trips_through_json() -> None:
    record = _report().steps[1]

    data = json.loads(json.dumps(record.to_dict()))

    assert data == {
        "name": "test.other",
        "version": "3",
        "params": {},
        "status": "failed",
        "error_type": "ValueError",
    }
    assert StepRecord.from_dict(data) == record


def test_study_report_round_trips_through_json_with_step_instances() -> None:
    report = _report()

    rebuilt = StudyReport.from_dict(json.loads(json.dumps(report.to_dict())))

    assert rebuilt == report
    assert all(isinstance(step, StepRecord) for step in rebuilt.steps)


def test_study_report_without_source_path_round_trips() -> None:
    report = StudyReport(index=1, source_path=None, steps=[])
    assert StudyReport.from_dict(json.loads(json.dumps(report.to_dict()))) == report


@pytest.mark.parametrize(
    ("status", "error_type"),
    [("skipped", None), ("ok", "ValueError"), ("failed", None)],
)
def test_step_record_rejects_invalid_status_or_error_type(status: str, error_type: str | None) -> None:
    with pytest.raises(ValueError, match="Step"):
        StepRecord("test.scale", "1", {}, status, error_type)  # type: ignore[arg-type]


def test_study_report_from_dict_validates_steps() -> None:
    data = _report().to_dict()
    data["steps"][0]["status"] = "skipped"
    with pytest.raises(ValueError, match="Step status"):
        StudyReport.from_dict(data)


def test_transformation_module_imports_no_format_or_array_libraries() -> None:
    tree = ast.parse(open(transformation.__file__, encoding="utf-8").read())
    imported = {
        alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported.isdisjoint({"numpy", "pydicom", "nibabel"})
