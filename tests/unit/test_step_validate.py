import copy
import gc
import json
import logging
import weakref
from collections.abc import Iterator
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.pipeline.step import build_step
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StudyReport
from mri_dataset_tool.infrastructure.processing.validation import CONSTANT_VOLUME


def _series(volume, modality: str | None = "T1w", tmp_path: Path | None = None) -> MRISeries:
    files = [] if tmp_path is None else [tmp_path / "sub-SECRET_T1w.nii.gz"]
    return MRISeries(
        series_uid="1.2.SECRET",
        modality=modality,
        files=files,
        volume=volume,
        metadata={
            "shape": tuple(volume.shape),
            "voxel_size": (1.0, 1.0, 1.0),
            "affine": np.eye(4),
            "orientation": ("R", "A", "S"),
            "sidecar": {"PatientName": "SECRET"},
        },
    )


def _ramp(shape=(2, 3, 4)) -> np.ndarray:
    return np.arange(np.prod(shape), dtype=np.float32).reshape(shape)


def _study(*series: MRISeries) -> MRIStudy:
    return MRIStudy(study_uid="1.2.SECRET", series=list(series), subject_id="SECRET")


def test_step_is_registered_and_rebuilt_from_params() -> None:
    step = build_step("validate", {"modalities": ["T1w"]})
    assert (step.name, step.version) == ("validate", "1")
    assert step.params == {"modalities": ["T1w"]}
    assert build_step("validate", step.params).params == step.params
    assert build_step("validate").params == {"modalities": None}
    assert pipeline_from_config({"pipeline": {"steps": [{"name": "validate"}]}}).steps[0].name == "validate"


@pytest.mark.parametrize("modalities", ["T1w", [1], 3])
def test_invalid_modalities_raise(modalities) -> None:
    with pytest.raises(ValueError):
        build_step("validate", {"modalities": modalities})


def test_valid_study_only_gains_validation_metadata_and_input_is_not_mutated() -> None:
    study = _study(_series(_ramp()))
    before = copy.deepcopy(study)

    result, outputs = build_step("validate").apply_with_outputs(study)

    assert study.series[0].metadata.keys() == before.series[0].metadata.keys()
    assert "validation" not in study.series[0].metadata
    assert result is not study and result.series[0] is not study.series[0]
    out = result.series[0]
    assert out.volume is study.series[0].volume  # unchanged, not copied
    assert out.metadata.pop("validation") == {"status": "ok", "findings": []}
    assert out.metadata.keys() == before.series[0].metadata.keys()
    assert (result.study_uid, result.subject_id, out.series_uid, out.files) == (
        before.study_uid,
        before.subject_id,
        before.series[0].series_uid,
        before.series[0].files,
    )
    assert outputs == {"series": [{"index": 0, "findings": [], "volumes_checked": 1}]}
    json.dumps(outputs)


def test_apply_returns_first_item_of_apply_with_outputs() -> None:
    study = _study(_series(np.full((2, 2, 2), 3.0)))
    step = build_step("validate")
    assert step.apply(study).series[0].metadata["validation"] == {"status": "ok", "findings": [CONSTANT_VOLUME]}


def test_serious_problem_raises_fixed_message() -> None:
    volume = _ramp()
    volume[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match=r"^Volume contains non-finite values\.$"):
        build_step("validate").apply(_study(_series(volume)))


def test_series_without_volume_or_outside_modalities_are_untouched() -> None:
    no_volume = MRISeries(modality="T1w")
    bold = _series(np.full((2, 2, 2), np.nan), modality="bold")  # would fail if checked
    t1 = _series(_ramp())
    study = _study(no_volume, bold, t1)

    result, outputs = build_step("validate", {"modalities": ["T1w"]}).apply_with_outputs(study)

    assert result.series[0] is no_volume and result.series[1] is bold
    assert "validation" in result.series[2].metadata
    assert [s["index"] for s in outputs["series"]] == [2]


def test_lazy_and_ndarray_volumes_give_the_same_result(tmp_path: Path) -> None:
    data = np.arange(2 * 3 * 4 * 2, dtype=np.int16).reshape(2, 3, 4, 2)
    path = tmp_path / "vol.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), path)
    step = build_step("validate")

    lazy, lazy_outputs = step.apply_with_outputs(_study(_series(nib.load(path, mmap=False).dataobj)))
    eager, eager_outputs = step.apply_with_outputs(_study(_series(data)))

    assert lazy_outputs == eager_outputs
    assert lazy.series[0].metadata["validation"] == eager.series[0].metadata["validation"]
    assert not isinstance(lazy.series[0].volume, np.ndarray)  # validation doesn't materialize it


def test_batch_with_invalid_second_study_reports_it_and_delivers_the_others(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = _ramp()
    bad[1, 1, 1] = np.inf
    studies = [_study(_series(v, tmp_path=tmp_path)) for v in (_ramp(), bad, np.full((2, 2, 2), 1.0))]
    results: list[tuple[MRIStudy, StudyReport]] = []
    errors: list[Exception] = []

    with caplog.at_level(logging.DEBUG):
        reports = Pipeline([build_step("validate")]).run(
            studies, lambda s, r: results.append((s, r)), lambda p, e: errors.append(e)
        )

    assert [r.index for _, r in results] == [1, 3]
    assert [r.steps[0].status for r in reports] == ["ok", "failed", "ok"]
    assert reports[1].steps[0].error_type == "ValueError" and reports[1].steps[0].outputs == {}
    assert [type(e) for e in errors] == [ValueError]
    assert reports[2].steps[0].outputs == {"series": [{"index": 0, "findings": [CONSTANT_VOLUME], "volumes_checked": 1}]}
    assert "SECRET" not in caplog.text and str(tmp_path) not in caplog.text
    assert "SECRET" not in json.dumps([[rec.to_dict() for rec in r.steps] for r in reports])


def test_step_does_not_retain_studies() -> None:
    refs: list[weakref.ref] = []

    def source() -> Iterator[MRIStudy]:
        for _ in range(3):
            gc.collect()
            assert all(ref() is None for ref in refs)
            yield _study(_series(_ramp()))

    Pipeline([build_step("validate")]).run(source(), lambda s, r: refs.append(weakref.ref(s)))
    gc.collect()
    assert len(refs) == 3 and all(ref() is None for ref in refs)


def test_output_does_not_share_nested_metadata_with_input() -> None:
    study = MRIStudy(study_uid=None, series=[_series(_ramp())])
    out = build_step("validate").apply(study)
    out.series[0].metadata["affine"][0, 3] += 1
    out.series[0].metadata["sidecar"]["EchoTime"] = 1.0
    assert study.series[0].metadata["affine"][0, 3] == 0
    assert "EchoTime" not in study.series[0].metadata["sidecar"]
