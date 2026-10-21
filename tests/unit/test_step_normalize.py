import copy
import gc
import json
import logging
import weakref
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np
import psutil
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.pipeline.step import build_step
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy

_AFFINE = np.array([[0.0, 0.0, 2.0, 1.0], [-1.5, 0.0, 0.0, 2.0], [0.0, 1.0, 0.0, 3.0], [0.0, 0.0, 0.0, 1.0]])


def _volume(shape=(4, 5, 6), seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    volume = np.zeros(shape, dtype=np.int16)
    volume[1:-1, 1:-1, 1:-1] = rng.integers(10, 500, tuple(n - 2 for n in shape[:3]) + shape[3:])
    return volume


def _series(volume, modality: str | None = "T1w", tmp_path: Path | None = None) -> MRISeries:
    files = [] if tmp_path is None else [tmp_path / "sub-SECRET_T1w.nii.gz"]
    return MRISeries(
        series_uid="1.2.SECRET",
        modality=modality,
        files=files,
        volume=volume,
        metadata={
            "shape": tuple(volume.shape),
            "voxel_size": (1.5, 1.0, 2.0),
            "affine": _AFFINE,
            "orientation": ("P", "S", "R"),
            "datatype": "int16",
            "sidecar": {"PatientName": "SECRET"},
        },
    )


def _study(*series: MRISeries) -> MRIStudy:
    return MRIStudy(study_uid="1.2.SECRET", series=list(series), subject_id="SECRET")


def test_defaults_and_params_round_trip() -> None:
    step = build_step("normalize")
    assert (step.name, step.version) == ("normalize", "1")
    assert step.params == {"method": "zscore", "mask": "nonzero", "per_volume": True, "percentiles": None, "modalities": None, "allow_insufficient_memory": False}
    custom = build_step("normalize", {"method": "percentile", "percentiles": [1, 99], "modalities": ["T1w"]})
    assert custom.params["percentiles"] == [1.0, 99.0]
    assert build_step("normalize", custom.params).params == custom.params
    json.dumps(custom.params)
    assert pipeline_from_config({"pipeline": {"steps": [{"name": "normalize"}]}}).steps[0].name == "normalize"


@pytest.mark.parametrize(
    "params",
    [{"method": "x"}, {"percentiles": [1, 99]}, {"modalities": "T1w"}, {"allow_insufficient_memory": 1}],
)
def test_invalid_params_raise(params) -> None:
    with pytest.raises(ValueError):
        build_step("normalize", params)


def test_geometry_is_kept_dtype_becomes_float32_and_input_is_not_mutated() -> None:
    study = _study(_series(_volume()))
    before = copy.deepcopy(study)

    result, outputs = build_step("normalize").apply_with_outputs(study)

    np.testing.assert_array_equal(study.series[0].volume, before.series[0].volume)
    assert study.series[0].volume.dtype == np.int16
    out = result.series[0]
    assert out.volume.dtype == np.float32
    assert out.metadata["shape"] == before.series[0].metadata["shape"]
    np.testing.assert_array_equal(out.metadata["affine"], _AFFINE)
    assert out.metadata["orientation"] == ("P", "S", "R")
    assert out.metadata["voxel_size"] == pytest.approx((1.5, 1.0, 2.0))
    assert out.metadata["sidecar"] == before.series[0].metadata["sidecar"]
    assert (out.series_uid, result.subject_id) == ("1.2.SECRET", "SECRET")
    assert outputs["series"][0]["index"] == 0 and outputs["series"][0]["method"] == "zscore"
    assert set(outputs["series"][0]) == {"index", "method", "mean", "std"}
    assert all(type(v) is float for k, v in outputs["series"][0].items() if k in ("mean", "std"))
    json.dumps(outputs)


def test_4d_per_volume_outputs_list_one_entry_per_volume() -> None:
    _, outputs = build_step("normalize").apply_with_outputs(_study(_series(_volume((4, 5, 6, 3)))))
    entry = outputs["series"][0]
    assert set(entry) == {"index", "method", "volumes"} and len(entry["volumes"]) == 3
    _, global_outputs = build_step("normalize", {"per_volume": False}).apply_with_outputs(
        _study(_series(_volume((4, 5, 6, 3))))
    )
    assert set(global_outputs["series"][0]) == {"index", "method", "mean", "std"}


def test_series_without_volume_or_outside_modalities_are_untouched() -> None:
    no_volume = MRISeries(modality="T1w")
    bold = _series(np.zeros((3, 3, 3)), modality="bold")  # empty mask: would fail if selected
    t1 = _series(_volume())
    result, outputs = build_step("normalize", {"modalities": ["T1w"]}).apply_with_outputs(_study(no_volume, bold, t1))
    assert result.series[0] is no_volume and result.series[1] is bold
    assert result.series[2].volume.dtype == np.float32
    assert [s["index"] for s in outputs["series"]] == [2]


def test_lazy_and_ndarray_volumes_give_the_same_result(tmp_path: Path) -> None:
    data = _volume((4, 5, 6, 2))
    path = tmp_path / "vol.nii.gz"
    nib.save(nib.Nifti1Image(data, _AFFINE), path)
    step = build_step("normalize")
    lazy, lazy_outputs = step.apply_with_outputs(_study(_series(nib.load(path, mmap=False).dataobj)))
    eager, eager_outputs = step.apply_with_outputs(_study(_series(data)))
    np.testing.assert_array_equal(lazy.series[0].volume, eager.series[0].volume)
    assert lazy_outputs == eager_outputs


def test_outputs_are_reproduced_from_the_manifest(tmp_path: Path) -> None:
    config = {"pipeline": {"steps": [{"name": "normalize", "params": {"method": "minmax"}}]}}

    def run(pipeline: Pipeline):
        volumes = []
        reports = pipeline.run(
            [_study(_series(_volume(seed=s))) for s in (0, 1)], lambda s, r: volumes.append(s.series[0].volume)
        )
        return volumes, reports

    pipeline = pipeline_from_config(config)
    volumes, reports = run(pipeline)
    manifest = RunManifest.from_json(RunManifest.from_run(config, pipeline, reports).to_json())

    rebuilt = pipeline_from_manifest(manifest)
    again, again_reports = run(rebuilt)
    assert RunManifest.from_run(config, rebuilt, again_reports) == manifest
    assert [r.steps[0].outputs for r in again_reports] == [r.steps[0].outputs for r in reports]
    for got, expected in zip(again, volumes, strict=True):
        np.testing.assert_array_equal(got, expected)


def test_constant_study_fails_and_the_batch_continues(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    studies = [_study(_series(v, tmp_path=tmp_path)) for v in (_volume(), np.full((3, 3, 3), 7), _volume(seed=2))]
    delivered: list[int] = []
    errors: list[Exception] = []
    with caplog.at_level(logging.DEBUG):
        reports = Pipeline([build_step("normalize")]).run(
            studies, lambda s, r: delivered.append(r.index), lambda p, e: errors.append(e)
        )
    assert delivered == [1, 3]
    assert [r.steps[0].status for r in reports] == ["ok", "failed", "ok"]
    assert reports[1].steps[0].outputs == {} and [type(e) for e in errors] == [ValueError]
    assert "SECRET" not in caplog.text and str(tmp_path) not in caplog.text
    assert "SECRET" not in json.dumps([[rec.to_dict() for rec in r.steps] for r in reports])


def test_step_does_not_retain_studies() -> None:
    refs: list[weakref.ref] = []

    def source() -> Iterator[MRIStudy]:
        for seed in range(3):
            gc.collect()
            assert all(ref() is None for ref in refs)
            study = _study(_series(_volume(seed=seed)))
            refs.append(weakref.ref(study))
            yield study
            del study

    Pipeline([build_step("normalize")]).run(source(), lambda s, r: refs.append(weakref.ref(s)))
    gc.collect()
    assert len(refs) == 6 and all(ref() is None for ref in refs)


def test_manifest_without_allow_insufficient_memory_rebuilds_with_the_default() -> None:
    old_params = {"method": "zscore", "mask": "nonzero", "per_volume": True, "percentiles": None, "modalities": None}
    step = build_step("normalize", old_params)
    assert step.version == "1" and step.params["allow_insufficient_memory"] is False


def test_insufficient_memory_fails_only_that_study_unless_allowed(monkeypatch) -> None:
    # The estimate grows with the volume: 4 KiB is enough for a tiny study, not for a larger one.
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=4096))
    studies = [_study(_series(_volume(shape))) for shape in ((20, 20, 20), (4, 4, 4), (20, 20, 20))]
    errors: list[str] = []

    refused = Pipeline([build_step("normalize")]).run(studies, lambda s, r: None, lambda p, e: errors.append(str(e)))
    allowed = pipeline_from_config(
        {"pipeline": {"steps": [{"name": "normalize", "params": {"allow_insufficient_memory": True}}]}}
    ).run([_study(_series(_volume((20, 20, 20))))], lambda s, r: None)

    assert [r.steps[0].status for r in refused] == ["failed", "ok", "failed"]
    assert errors == ["Insufficient available memory for the normalized volume."] * 2
    assert allowed[0].steps[0].status == "ok"
