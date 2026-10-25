"""``pipeline_run`` service (reading, float32 outputs, manifest checks, replay, typed failures)."""

import gc
import weakref
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.services.pipeline_run import (
    StageFailed,
    output_name,
    previous_outputs_exist,
    process_studies,
    read_studies,
    run_pipeline,
)
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.config.loader import load_config

REPO = Path(__file__).resolve().parents[2]
KEY = "k" * 40


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", KEY)


def _config(name: str) -> dict:
    return load_config(REPO / "config" / name, config_dir=REPO / "config")


def _bids(root: Path) -> Path:
    """Three participants with a T1w; sub-03 holds a NaN, so the validate step rejects it."""
    rng = np.random.default_rng(0)
    for subject in ("01", "02", "03"):
        volume = rng.uniform(10, 100, (4, 5, 3)).astype(np.float32)
        if subject == "03":
            volume[1, 1, 1] = np.nan
        path = root / f"sub-{subject}" / "anat" / f"sub-{subject}_T1w.nii.gz"
        path.parent.mkdir(parents=True)
        nib.save(nib.Nifti1Image(volume, np.diag([1.5, 1.5, 1.5, 1.0])), path)
    return root


def _run(config_name, input_format, source, tmp_path, **kwargs):
    config = _config(config_name)
    events, errors = [], []
    result = run_pipeline(
        pipeline_from_config(config), config, input_format, source, tmp_path / "out", tmp_path / "m" / "run.json",
        lambda path, error: errors.append(type(error).__name__),
        on_status=lambda stage, counts: events.append((stage, counts)), **kwargs,
    )
    return result, events, errors


def test_output_names():
    assert output_name("nifti", 2, 1, 1) == "study-002.nii.gz"
    assert output_name("nifti", 2, 1, 3) == "study-002_series-001.nii.gz"
    assert output_name("bids", 7, 1, 1) == "study-007_series-001.nii.gz"


def test_previous_outputs_exist(tmp_path):
    manifest = tmp_path / "m.json"
    assert not previous_outputs_exist(tmp_path, manifest)
    (tmp_path / "study-001.nii.gz").write_bytes(b"")
    assert previous_outputs_exist(tmp_path, manifest)
    assert previous_outputs_exist(tmp_path / "empty", tmp_path / "study-001.nii.gz")


def test_unknown_format_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsupported input format."):
        read_studies("dicom", tmp_path, None)


def test_bids_run_writes_float32_and_verifies(tmp_path):
    result, events, errors = _run("stage3_bids.yaml", "bids", _bids(tmp_path / "ds"), tmp_path)
    assert (len(result.reports), result.failed, result.files_written) == (3, 1, 2)
    assert result.no_sources and result.reproduced
    assert errors == ["ValueError"]  # the NaN study, reported once (replay errors go elsewhere)
    assert [stage for stage, _ in events] == ["process", "manifest", "verify"]
    assert events[1][1] == {"studies": 3, "files_written": 2}
    written = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert written == ["study-001_series-001.nii.gz", "study-002_series-001.nii.gz"]
    assert nib.load(tmp_path / "out" / written[0]).get_data_dtype() == np.float32


def test_nifti_run_without_verify(tmp_path):
    source = tmp_path / "in"
    source.mkdir()
    nib.save(nib.Nifti1Image(np.ones((4, 4, 3), np.float32) * 5, np.eye(4)), source / "a.nii.gz")
    nib.save(nib.Nifti1Image(np.arange(48, dtype=np.float32).reshape(4, 4, 3), np.eye(4)), source / "b.nii.gz")
    result, events, _ = _run("stage3_example.yaml", "nifti", source, tmp_path, verify=False)
    assert result.reproduced is None and "verify" not in [stage for stage, _ in events]
    assert (tmp_path / "out" / "study-002.nii.gz").is_file()


def test_missing_input_fails_at_process_without_path(tmp_path):
    missing = tmp_path / "sub-SECRET"
    with pytest.raises(StageFailed) as raised:
        _run("stage3_bids.yaml", "bids", missing, tmp_path)
    assert (raised.value.stage, raised.value.error_type) == ("process", "FileNotFoundError")
    assert str(raised.value) == "Stage failed: process." and isinstance(raised.value.__cause__, FileNotFoundError)


def test_manifest_write_failure_fails_at_manifest(tmp_path):
    source = _bids(tmp_path / "ds")
    (tmp_path / "m").write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(StageFailed) as raised:
        _run("stage3_bids.yaml", "bids", source, tmp_path)
    assert raised.value.stage == "manifest"


def test_process_studies_releases_each_study_before_the_next(tmp_path):
    alive = []

    def track(study: MRIStudy) -> MRIStudy:  # called when the next study arrives; holds no reference itself
        gc.collect()
        assert all(ref() is None for ref in alive), "a previous study is still alive"
        alive.append(weakref.ref(study))
        return study

    studies = map(track, read_studies("bids", _bids(tmp_path / "ds"), None))
    (tmp_path / "out").mkdir()
    reports, written = process_studies(
        pipeline_from_config(_config("stage3_bids.yaml")), studies, tmp_path / "out", lambda p, e: None, "bids"
    )
    assert (len(reports), written, len(alive)) == (3, 2, 3)


def test_failure_removes_the_empty_output_directory_it_created(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(StageFailed) as raised:
        _run("stage3_bids.yaml", "bids", tmp_path / "empty", tmp_path)
    assert raised.value.stage == "process" and not (tmp_path / "out").exists()


def test_failure_keeps_an_output_directory_that_already_existed(tmp_path):
    (tmp_path / "empty").mkdir()
    (tmp_path / "out").mkdir()
    with pytest.raises(StageFailed):
        _run("stage3_bids.yaml", "bids", tmp_path / "empty", tmp_path)
    assert (tmp_path / "out").is_dir()


def test_a_failed_cleanup_still_raises_stage_failed_without_the_path(tmp_path, monkeypatch):
    def locked(self):
        raise PermissionError(f"locked {self}")

    monkeypatch.setattr(Path, "rmdir", locked)
    (tmp_path / "empty").mkdir()
    with pytest.raises(StageFailed) as raised:
        _run("stage3_bids.yaml", "bids", tmp_path / "empty", tmp_path)
    assert raised.value.stage == "process" and str(tmp_path) not in str(raised.value)
    assert (tmp_path / "out").is_dir()  # left in place, the run still reports its own failure
