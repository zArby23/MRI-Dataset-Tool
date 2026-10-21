"""QA1 (3) and (4): invariants across steps and memory release over a larger batch.

Every order of the five built-in steps over an oblique, scaled, 4D input must keep the canonical
geometry, give the same result with an ``ndarray`` and with the lazy proxy, not mutate its
input and be reproducible from its manifest. The memory peak of a batch must not grow with the
number of studies (RNF02).
"""

import copy
import gc
import itertools
import tracemalloc
from pathlib import Path
from unittest import mock

import nibabel as nib
import numpy as np
import pytest
from nibabel.openers import ImageOpener

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.step import build_step
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader
from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d
from mri_dataset_tool.infrastructure.processing.geometry import validate_geometry

KEY = "qa-anonymization-key-0123456789abcdef"
STEPS = ["validate", "anonymize", "reorient", "resample", "normalize"]
PARAMS = {"resample": {"spacing": [2.0, 1.5, 2.0]}}


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV_VAR, KEY)


@pytest.fixture(scope="module")
def oblique_4d(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Oblique, flipped, anisotropic 4D int16 with scl_slope/inter, so eager and lazy differ in dtype."""
    affine = np.eye(4)
    affine[:3, :3] = nib.eulerangles.euler2mat(0.2, -0.1, 0.05) @ np.diag([-1.2, 0.9, 2.5])
    affine[:3, 3] = [3, -4, 5]
    data = (np.random.default_rng(1).random((9, 8, 7, 3)) * 500 + 1).astype(np.int16)
    image = nib.Nifti1Image(data, affine)
    image.header.set_slope_inter(0.7, 3)
    path = tmp_path_factory.mktemp("qa") / "x.nii.gz"
    nib.save(image, path)
    return path


def _config(order) -> dict:
    return {"pipeline": {"steps": [{"name": name, "params": PARAMS.get(name, {})} for name in order]}}


def _run(path: Path, order, lazy: bool):
    study = NIfTIReader().load_study(path, lazy=lazy)
    before = copy.deepcopy(study.series[0].metadata)
    results, errors = [], []
    pipeline = pipeline_from_config(_config(order))
    reports = pipeline.run([study], lambda s, r: results.append(s), lambda p, e: errors.append(e))
    assert errors == []
    after = study.series[0].metadata
    assert before.keys() == after.keys()
    assert all(np.array_equal(np.asarray(before[k]), np.asarray(after[k])) for k in before), "input mutated"
    return results[0].series[0], reports, pipeline


@pytest.mark.parametrize("order", list(itertools.permutations(STEPS)), ids="-".join)
def test_any_step_order_keeps_geometry_and_eager_equals_lazy(oblique_4d: Path, order) -> None:
    outputs = {}
    for lazy in (False, True):
        series, reports, _ = _run(oblique_4d, order, lazy)
        validate_geometry(series)
        metadata, volume = series.metadata, np.asarray(series.volume)
        affine = np.asarray(metadata["affine"])
        assert tuple(metadata["shape"]) == volume.shape
        assert np.allclose(metadata["voxel_size"], np.linalg.norm(affine[:3, :3], axis=0))
        assert tuple(metadata["orientation"]) == nib.aff2axcodes(affine)
        outputs[lazy] = (volume, reports)
    (eager, eager_reports), (lazy_volume, lazy_reports) = outputs[False], outputs[True]
    assert eager.dtype == lazy_volume.dtype
    assert np.allclose(eager, lazy_volume, rtol=1e-5, atol=1e-4)
    assert eager_reports == lazy_reports


def test_two_runs_are_identical_and_the_manifest_reproduces_them(oblique_4d: Path) -> None:
    first, reports, pipeline = _run(oblique_4d, STEPS, lazy=True)
    second, again, _ = _run(oblique_4d, STEPS, lazy=True)
    assert np.array_equal(np.asarray(first.volume), np.asarray(second.volume)) and reports == again

    saved = RunManifest.from_json(RunManifest.from_run(_config(STEPS), pipeline, reports).to_json())
    # outputs survive the JSON round trip (anonymize computes none)
    assert all(step.outputs for step in saved.reports[0].steps if step.name != "anonymize")
    replay = pipeline_from_manifest(saved)
    results = []
    replay_reports = replay.run([NIfTIReader().load_study(oblique_4d, lazy=True)], lambda s, r: results.append(s))
    assert RunManifest.from_run(saved.config, replay, replay_reports) == saved
    assert np.array_equal(np.asarray(results[0].series[0].volume), np.asarray(first.volume))


def test_anonymize_is_idempotent_on_a_bids_like_study(oblique_4d: Path) -> None:
    study = NIfTIReader().load_study(oblique_4d, lazy=True)
    series = study.series[0]
    series.metadata["bids"] = {"sub": "S01", "ses": "A", "suffix": "T1w", "extension": ".nii.gz", "other": {"acq": "x"}}
    series.metadata["sidecar"] = {"RepetitionTime": 2.0, "PatientName": "Doe^John"}
    study.subject_id, study.session_id, study.study_uid, series.series_uid = "S01", "A", "1.2.3", "1.2.3.4"
    step = build_step("anonymize")
    once = step.apply(study)
    twice = step.apply(once)
    assert (once.study_uid, once.subject_id, once.session_id) == (twice.study_uid, twice.subject_id, twice.session_id)
    assert once.series[0].series_uid == twice.series[0].series_uid
    assert repr(once.series[0].metadata) == repr(twice.series[0].metadata)


@pytest.mark.parametrize("name", ["validate", "anonymize"])
def test_step_output_does_not_alias_input_metadata(oblique_4d: Path, name: str) -> None:
    """QA1-05 (fixed): editing a step output in place never reaches its input."""
    study = NIfTIReader().load_study(oblique_4d, lazy=True)
    study.series[0].metadata["sidecar"] = {"RepetitionTime": 2.0}
    output = build_step(name).apply(study).series[0].metadata
    output["affine"][0, 3] += 1.0  # a later consumer editing the output in place
    output.get("sidecar", {})["RepetitionTime"] = 9.0
    assert study.series[0].metadata["affine"][0, 3] == 3.0
    assert study.series[0].metadata["sidecar"]["RepetitionTime"] == 2.0


def _peak_mib(root: Path, lazy: bool) -> float:
    gc.collect()
    tracemalloc.start()
    count = []
    try:
        pipeline_from_config(_config(STEPS)).run(
            NIfTIBatchReader().iter_studies(root, lazy=lazy), lambda s, r: count.append(r.index)
        )
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert len(count) == len(list(root.glob("*.nii.gz")))
    return peak / 2**20


@pytest.mark.parametrize("lazy", [False, True])
def test_memory_peak_does_not_grow_with_the_batch(tmp_path: Path, lazy: bool) -> None:
    data = (np.random.default_rng(0).random((64, 64, 48)) * 1000 + 1).astype(np.int16)
    small, large = tmp_path / "small", tmp_path / "large"
    small.mkdir()
    large.mkdir()
    for index in range(24):
        nib.save(nib.Nifti1Image(data, np.diag([1.2, 1.2, 1.5, 1.0])), large / f"s{index:03d}.nii.gz")
        if index < 3:
            nib.save(nib.Nifti1Image(data, np.diag([1.2, 1.2, 1.5, 1.0])), small / f"s{index:03d}.nii.gz")
    small_peak, large_peak = _peak_mib(small, lazy), _peak_mib(large, lazy)
    assert large_peak <= small_peak * 1.1 + 1.0, (small_peak, large_peak)


def test_lazy_4d_gz_is_read_with_one_open_per_pass(tmp_path: Path) -> None:
    """QA1-06 (fixed): one open per pass, not one per frame (opens are a deterministic proxy for O(T^2) time);
    the file is released with the study (renaming fails on Windows while it is open)."""
    path = tmp_path / "x.nii.gz"
    nib.save(nib.Nifti1Image(np.zeros((4, 4, 3, 10), np.int16), np.eye(4)), path)
    volume = NIfTIReader().load_study(path, lazy=True).series[0].volume
    with mock.patch.object(ImageOpener, "__init__", autospec=True, side_effect=ImageOpener.__init__) as opener:
        assert len(list(iter_volumes_3d(volume))) == 10
    assert opener.call_count <= 1
    del volume
    gc.collect()
    path.rename(tmp_path / "moved.nii.gz")
