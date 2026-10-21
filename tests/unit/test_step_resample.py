import json
import logging
import subprocess
import sys
import weakref
from collections.abc import Iterator
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.pipeline.step import build_step
from mri_dataset_tool.application.pipeline.steps.resample import ResampleStep
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.processing.geometry import validate_geometry

LPS = np.diag([-2.0, -1.0, 3.0, 1.0])


def _series(modality: str | None = "T1w", volume=None, affine=LPS) -> MRISeries:
    volume = np.arange(4 * 6 * 2, dtype=np.int16).reshape(4, 6, 2) if volume is None else volume
    return MRISeries(
        series_uid="1.2.SECRET",
        modality=modality,
        files=[Path("sub-SECRET_T1w.nii.gz")],
        metadata={
            "shape": tuple(volume.shape),
            "voxel_size": tuple(np.linalg.norm(affine[:3, :3], axis=0)),
            "affine": affine,
            "orientation": nib.aff2axcodes(affine),
            "sidecar": {"EchoTime": 0.03},
        },
        volume=volume,
    )


def _study(*series: MRISeries) -> MRIStudy:
    return MRIStudy(study_uid="1.2.SECRET", series=list(series or [_series()]), subject_id="SECRET")


def test_step_is_registered_with_json_params_and_defaults() -> None:
    step = build_step("resample")

    assert isinstance(step, ResampleStep)
    assert step.params == {"spacing": [1.0, 1.0, 1.0], "interpolation": "linear", "modalities": None}
    assert json.loads(json.dumps(step.params)) == step.params
    custom = build_step("resample", {"spacing": [2, 2, 1], "interpolation": "nearest", "modalities": ["T1w"]})
    assert custom.params == {"spacing": [2.0, 2.0, 1.0], "interpolation": "nearest", "modalities": ["T1w"]}


def test_builtin_step_is_found_by_name_from_config_in_a_clean_interpreter() -> None:
    code = (
        "from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config\n"
        "pipeline = pipeline_from_config({'pipeline': {'steps': [{'name': 'resample'}]}})\n"
        "assert [step.name for step in pipeline.steps] == ['resample']\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"spacing": [0, 1, 1]}, "Spacing must be three finite positive numbers."),
        ({"spacing": 1.0}, "Spacing must be three finite positive numbers."),
        ({"interpolation": "spline"}, "Unknown interpolation."),
        ({"modalities": "T1w"}, "Modalities must be a list of strings."),
    ],
)
def test_invalid_params_are_rejected_when_building(params, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        build_step("resample", params)


def test_apply_resamples_records_outputs_and_does_not_mutate_input() -> None:
    study = _study()
    original = study.series[0].volume.copy()

    result, outputs = ResampleStep().apply_with_outputs(study)
    series = result.series[0]

    assert outputs == {"series": [{"index": 0, "shape": [8, 6, 6], "spacing": [1.0, 1.0, 1.0]}]}
    assert all(type(v) is int for v in outputs["series"][0]["shape"])
    assert all(type(v) is float for v in outputs["series"][0]["spacing"])
    assert series.metadata["shape"] == (8, 6, 6)
    np.testing.assert_allclose(series.metadata["voxel_size"], [1.0, 1.0, 1.0])
    assert series.metadata["orientation"] == ("R", "A", "S")
    assert series.metadata["sidecar"] == {"EchoTime": 0.03}
    assert series.volume.dtype == np.float32
    validate_geometry(series)
    np.testing.assert_array_equal(study.series[0].volume, original)
    assert study.series[0].metadata["shape"] == (4, 6, 2)
    np.testing.assert_array_equal(ResampleStep().apply(study).series[0].volume, series.volume)


def test_modalities_filter_and_series_without_volume_are_left_intact() -> None:
    study = _study(_series("bold"), _series("T1w"), _series(None), MRISeries(modality="T1w"))

    result, outputs = ResampleStep(modalities=["T1w"]).apply_with_outputs(study)

    assert [s["index"] for s in outputs["series"]] == [1]
    assert result.series[1].metadata["shape"] == (8, 6, 6)
    for index in (0, 2, 3):
        assert result.series[index] is study.series[index]


def test_4d_series_keeps_the_time_axis() -> None:
    volume = np.ones((4, 6, 2, 3), dtype=np.float32)

    series = ResampleStep(spacing=[2.0, 2.0, 2.0]).apply(_study(_series(volume=volume))).series[0]

    assert series.metadata["shape"] == (4, 3, 3, 3)
    np.testing.assert_allclose(series.metadata["voxel_size"], [2.0, 2.0, 2.0])
    validate_geometry(series)


def test_lazy_volume_gives_the_same_result_as_ndarray(tmp_path: Path) -> None:
    volume = np.arange(4 * 6 * 2, dtype=np.int16).reshape(4, 6, 2)
    path = tmp_path / "v.nii"
    nib.save(nib.Nifti1Image(volume, LPS), path)
    proxy = nib.load(path).dataobj

    lazy = ResampleStep().apply_with_outputs(_study(_series(volume=proxy)))
    eager = ResampleStep().apply_with_outputs(_study(_series(volume=volume)))

    np.testing.assert_array_equal(lazy[0].series[0].volume, eager[0].series[0].volume)
    assert lazy[1] == eager[1]


def test_invalid_geometry_fails_the_study_and_the_batch_continues() -> None:
    broken = _series()
    broken.metadata["affine"] = np.diag([1.0, 0.0, 1.0, 1.0])
    errors: list[str] = []
    results: list[MRIStudy] = []

    reports = Pipeline([ResampleStep()]).run(
        [_study(), _study(broken), _study()], lambda s, r: results.append(s), lambda p, e: errors.append(type(e).__name__)
    )

    assert [r.steps[0].status for r in reports] == ["ok", "failed", "ok"]
    assert errors == ["ValueError"] and len(results) == 2
    assert reports[1].steps[0].outputs == {}


def test_outputs_reach_the_manifest_and_are_reproduced() -> None:
    config = {"pipeline": {"steps": [{"name": "reorient"}, {"name": "resample", "params": {"spacing": [2, 1.5, 1]}}]}}
    pipeline = pipeline_from_config(config)
    reports = pipeline.run([_study()], lambda s, r: None)
    saved = RunManifest.from_json(RunManifest.from_run(config, pipeline, reports).to_json())

    replay = pipeline_from_manifest(saved)
    replay_reports = replay.run([_study()], lambda s, r: None)

    assert saved.reports[0].steps[1].outputs == {"series": [{"index": 0, "shape": [4, 4, 6], "spacing": [2.0, 1.5, 1.0]}]}
    assert RunManifest.from_run(saved.config, replay, replay_reports) == saved


def test_pipeline_releases_input_and_output_studies() -> None:
    refs: list[weakref.ref] = []

    def source() -> Iterator[MRIStudy]:
        for _ in range(3):
            study = _study()
            refs.append(weakref.ref(study.series[0].volume))
            yield study

    def on_result(study: MRIStudy, report) -> None:
        refs.append(weakref.ref(study.series[0].volume))

    Pipeline([ResampleStep()]).run(source(), on_result)

    assert len(refs) == 6
    assert all(ref() is None for ref in refs)


def test_logs_errors_and_outputs_have_no_phi(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    broken = _series()
    broken.metadata["affine"] = np.zeros((4, 4))
    messages: list[str] = []

    reports = Pipeline([ResampleStep()]).run([_study(), _study(broken)], lambda s, r: None, lambda p, e: messages.append(str(e)))

    assert "SECRET" not in caplog.text
    assert not any("SECRET" in m for m in messages)
    assert "SECRET" not in json.dumps([r.steps[0].outputs for r in reports])
