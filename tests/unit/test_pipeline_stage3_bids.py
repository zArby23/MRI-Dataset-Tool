"""QA2-cfg: config/stage3_bids.yaml over a tiny lazy BIDS batch (anatomy at 1 mm, dwi at 2 mm)."""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.config.loader import load_config

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRI_ANON_KEY", "k" * 40)


def _config() -> dict:
    return load_config(REPO / "config" / "stage3_bids.yaml", config_dir=REPO / "config")


def _dataset(root: Path) -> Path:
    """One session: LPS 1.5 mm T1w (3D), 1 mm dwi (4D, 3 volumes) and a FLAIR that no list includes."""
    rng = np.random.default_rng(0)
    session = root / "ds" / "sub-01" / "ses-01"
    images = {
        "anat/sub-01_ses-01_T1w.nii.gz": (rng.uniform(10, 100, (6, 8, 5)), np.diag([-1.5, -1.5, 1.5, 1.0])),
        "dwi/sub-01_ses-01_dwi.nii.gz": (rng.uniform(10, 100, (8, 6, 4, 3)), np.diag([1.0, 1.0, 1.0, 1.0])),
        "anat/sub-01_ses-01_FLAIR.nii.gz": (rng.uniform(10, 100, (5, 5, 5)), np.diag([1.5, 1.5, 1.5, 1.0])),
    }
    for name, (volume, affine) in images.items():
        (session / name).parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(volume.astype(np.float32), affine), session / name)
    return root / "ds"


def _run(pipeline, dataset: Path) -> tuple[list[MRIStudy], list]:
    results: list[MRIStudy] = []
    reports = pipeline.run(BIDSBatchReader().iter_studies(dataset, lazy=True), lambda s, r: results.append(s))
    return results, reports


def _assert_normalized(volume: np.ndarray) -> None:
    for frame in np.moveaxis(volume.reshape(volume.shape[:3] + (-1,)), -1, 0):
        foreground = frame[frame != 0]
        assert abs(foreground.mean()) < 1e-3 and abs(foreground.std() - 1.0) < 1e-3


def test_yaml_resamples_anatomy_and_dwi_separately() -> None:
    steps = _config()["pipeline"]["steps"]

    assert [s["name"] for s in steps] == ["validate", "anonymize", "reorient", "resample", "resample", "normalize"]
    assert steps[3]["params"]["modalities"] == ["T1w", "T2w", "magnitude1", "magnitude2", "phasediff"]
    assert steps[4]["params"] == {"spacing": [2.0, 2.0, 2.0], "interpolation": "linear", "modalities": ["dwi"]}
    assert "modalities" not in steps[5].get("params", {})
    assert _config()["report"]["path"] == "data/output/stage3_bids_run_manifest.json"


def test_anatomy_at_1_mm_dwi_at_2_mm_unlisted_modality_untouched(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    config = _config()
    pipeline = pipeline_from_config(config)

    results, reports = _run(pipeline, dataset)

    assert [[s.status for s in r.steps] for r in reports] == [["ok"] * 6]
    series = {s.modality: s for s in results[0].series}
    assert set(series) == {"T1w", "dwi", "FLAIR"}
    t1, dwi, flair = series["T1w"], series["dwi"], series["FLAIR"]
    assert t1.metadata["shape"] == (9, 12, 8)  # ceil(6*1.5, 8*1.5, 5*1.5)
    np.testing.assert_allclose(t1.metadata["voxel_size"], [1.0, 1.0, 1.0])
    assert dwi.metadata["shape"] == (4, 3, 2, 3)
    np.testing.assert_allclose(dwi.metadata["voxel_size"], [2.0, 2.0, 2.0])
    np.testing.assert_allclose(flair.metadata["voxel_size"], [1.5, 1.5, 1.5])  # in neither list: not resampled
    for s in (t1, dwi, flair):
        assert s.metadata["orientation"] == ("R", "A", "S")
        _assert_normalized(np.asarray(s.volume))

    text = RunManifest.from_run(config, pipeline, reports).to_json()
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text and "sub-" not in text
    steps = json.loads(text)["reports"][0]["steps"]
    assert [entry["index"] for entry in steps[3]["outputs"]["series"]] == [
        i for i, s in enumerate(results[0].series) if s.modality == "T1w"
    ]
    assert [entry["spacing"] for entry in steps[4]["outputs"]["series"]] == [[2.0, 2.0, 2.0]]


def test_manifest_reproduces_the_same_volumes(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    config = _config()
    pipeline = pipeline_from_config(config)
    first, reports = _run(pipeline, dataset)
    saved = RunManifest.from_json(RunManifest.from_run(config, pipeline, reports).to_json())

    replay = pipeline_from_manifest(saved)
    again, replay_reports = _run(replay, dataset)

    assert RunManifest.from_run(saved.config, replay, replay_reports) == saved
    for a, b in zip(first[0].series, again[0].series, strict=True):
        np.testing.assert_array_equal(a.volume, b.volume)
        np.testing.assert_array_equal(a.metadata["affine"], b.metadata["affine"])
