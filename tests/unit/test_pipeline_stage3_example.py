"""Stage 3 closing example (E1): the YAML pipeline over a synthetic lazy NIfTI batch."""

import importlib.util
import json
import weakref
from collections.abc import Iterator
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("run_stage3_pipeline", REPO / "scripts" / "run_stage3_pipeline.py")
stage3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage3)

KEY = "k" * 40


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRI_ANON_KEY", KEY)


def _config() -> dict:
    return load_config(REPO / "config" / "stage3_example.yaml", config_dir=REPO / "config")


def _batch(root: Path) -> Path:
    """Four studies: 1 and 4 RAS 1 mm, 2 with a NaN, 3 LPS with anisotropic voxels."""
    rng = np.random.default_rng(0)
    batch = root / "input"
    batch.mkdir()
    volumes = {
        "01": (rng.uniform(10, 100, (10, 12, 8)), np.diag([1.0, 1.0, 1.0, 1.0])),
        "02": (rng.uniform(10, 100, (10, 12, 8)), np.diag([1.0, 1.0, 1.0, 1.0])),
        "03": (rng.uniform(10, 100, (6, 8, 5)), np.diag([-2.0, -1.5, 2.5, 1.0])),
        "04": (rng.uniform(10, 100, (9, 9, 9)), np.diag([1.0, 1.0, 1.0, 1.0])),
    }
    volumes["02"][0][3, 4, 5] = np.nan
    for subject, (volume, affine) in volumes.items():
        nib.save(nib.Nifti1Image(volume.astype(np.float32), affine), batch / f"sub-{subject}_ses-01_T1w.nii.gz")
    return batch


def _read_outputs(output_dir: Path) -> dict[str, nib.Nifti1Image]:
    return {path.name: nib.load(path) for path in sorted(output_dir.iterdir())}


def test_yaml_defines_the_five_steps_in_order() -> None:
    pipeline = pipeline_from_config(_config())

    assert [step.name for step in pipeline.steps] == ["validate", "anonymize", "reorient", "resample", "normalize"]


def test_stage3_pipeline_over_a_synthetic_batch(tmp_path: Path) -> None:
    batch = _batch(tmp_path)
    output_dir = tmp_path / "processed"
    output_dir.mkdir()
    config = _config()
    pipeline = pipeline_from_config(config)

    reports, errors, written = stage3.run(pipeline, batch, output_dir)

    # the NaN study fails in validate and the batch continues
    assert dict(errors) == {"ValueError": 1}
    assert [[s.status for s in r.steps] for r in reports] == [["ok"] * 5, ["failed"], ["ok"] * 5, ["ok"] * 5]
    assert reports[1].steps[0].name == "validate"
    assert written == 3

    outputs = _read_outputs(output_dir)
    assert list(outputs) == ["study-001.nii.gz", "study-003.nii.gz", "study-004.nii.gz"]
    for image in outputs.values():
        data = image.get_fdata(dtype=np.float32)
        assert nib.aff2axcodes(image.affine) == ("R", "A", "S")
        np.testing.assert_allclose(image.header.get_zooms()[:3], [1.0, 1.0, 1.0])
        assert image.get_data_dtype() == np.float32
        foreground = data[data != 0]
        assert np.all(np.isfinite(data))
        assert abs(foreground.mean()) < 1e-3 and abs(foreground.std() - 1.0) < 1e-3
    assert outputs["study-003.nii.gz"].shape == (12, 12, 13)  # ceil(6*2, 8*1.5, 5*2.5)

    # C1: anonymize redacts the sources; outputs of the steps are recorded
    text = RunManifest.from_run(config, pipeline, reports).to_json()
    assert str(batch) not in text and batch.as_posix() not in text and "sub-" not in text
    assert [r["source_path"] for r in json.loads(text)["reports"]] == [None] * 4
    steps = json.loads(text)["reports"][2]["steps"]
    assert steps[2]["outputs"] == {"series": [{"index": 0, "source": "LPS", "target": "RAS"}]}
    assert steps[3]["outputs"] == {"series": [{"index": 0, "shape": [12, 12, 13], "spacing": [1.0, 1.0, 1.0]}]}
    assert {"index", "method"} <= set(steps[4]["outputs"]["series"][0])


def test_reproducing_from_the_manifest_gives_the_same_volumes_and_outputs(tmp_path: Path) -> None:
    batch = _batch(tmp_path)
    first_dir, replay_dir = tmp_path / "first", tmp_path / "replay"
    first_dir.mkdir()
    replay_dir.mkdir()
    config = _config()
    pipeline = pipeline_from_config(config)
    reports, _, _ = stage3.run(pipeline, batch, first_dir)
    manifest = RunManifest.from_run(config, pipeline, reports)
    manifest_path = tmp_path / "manifest.json"
    manifest.write(manifest_path)

    saved = RunManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    replay = pipeline_from_manifest(saved)
    replay_reports, _, _ = stage3.run(replay, batch, replay_dir)

    assert RunManifest.from_run(saved.config, replay, replay_reports) == saved == manifest
    first, again = _read_outputs(first_dir), _read_outputs(replay_dir)
    assert list(first) == list(again)
    for name in first:
        np.testing.assert_array_equal(first[name].get_fdata(), again[name].get_fdata())
        np.testing.assert_array_equal(first[name].affine, again[name].affine)


def test_existing_outputs_are_not_overwritten(tmp_path: Path) -> None:
    batch = _batch(tmp_path)
    output_dir = tmp_path / "processed"
    output_dir.mkdir()
    (output_dir / "study-001.nii.gz").write_bytes(b"previous")

    _, errors, written = stage3.run(pipeline_from_config(_config()), batch, output_dir)

    assert (output_dir / "study-001.nii.gz").read_bytes() == b"previous"
    assert dict(errors) == {"ValueError": 1, "FileExistsError": 1}
    assert written == 2


def test_no_yielded_study_is_retained_across_the_five_steps(tmp_path: Path) -> None:
    batch = _batch(tmp_path)
    refs: list[weakref.ref] = []

    def source() -> Iterator[MRIStudy]:
        for study in NIfTIBatchReader().iter_studies(batch, lazy=True):
            refs.append(weakref.ref(study))
            yield study
            del study

    def on_result(study: MRIStudy, report) -> None:
        refs.append(weakref.ref(study))
        refs.append(weakref.ref(study.series[0].volume))

    pipeline_from_config(_config()).run(source(), on_result, lambda p, e: None)

    assert len(refs) == 4 + 3 * 2
    assert all(ref() is None for ref in refs)


def test_main_without_key_stops_before_creating_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MRI_ANON_KEY")
    monkeypatch.setattr(stage3, "REPO", tmp_path)
    monkeypatch.setattr(stage3, "OUTPUT_DIR", tmp_path / "processed")

    assert stage3.main() == 2

    assert capsys.readouterr().out == "MRI_ANON_KEY is not set or is shorter than 32 characters; nothing was run.\n"
    assert list(tmp_path.iterdir()) == []


def test_main_end_to_end_prints_no_paths_and_refuses_a_second_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil

    batch = _batch(tmp_path)
    shutil.copytree(REPO / "config", tmp_path / "config")
    monkeypatch.setattr(stage3, "REPO", tmp_path)
    monkeypatch.setattr(stage3, "CONFIG_PATH", tmp_path / "config" / "stage3_example.yaml")
    monkeypatch.setattr(stage3, "INPUT_DIR", batch)
    monkeypatch.setattr(stage3, "OUTPUT_DIR", tmp_path / "data" / "processed")

    assert stage3.main() == 0
    out = capsys.readouterr().out

    assert "Studies: 4  ok: 3  failed in a step: 1  files written: 3" in out
    assert "Errors by type: {'ValueError': 1}" in out
    assert "Manifest without source paths: True  reproduced from manifest: True" in out
    assert "sub-" not in out and str(tmp_path) not in out and KEY not in out
    manifest = (tmp_path / "data" / "output" / "stage3_run_manifest.json").read_text(encoding="utf-8")
    assert KEY not in manifest

    assert stage3.main() == 1  # nothing is overwritten
    assert "remove them first" in capsys.readouterr().out


def test_main_with_missing_input_directory_prints_a_fixed_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(stage3, "REPO", tmp_path)
    monkeypatch.setattr(stage3, "INPUT_DIR", tmp_path / "data" / "raw" / "nifti_test_studies")
    monkeypatch.setattr(stage3, "OUTPUT_DIR", tmp_path / "data" / "processed")

    assert stage3.main() == 2

    captured = capsys.readouterr()
    assert captured.out == "Input directory not found: data/raw/nifti_test_studies\n"
    assert captured.err == "" and str(tmp_path) not in captured.out
    assert list(tmp_path.iterdir()) == []
