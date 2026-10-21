"""QA2-cfg: config/stage3_bids.yaml over a tiny lazy BIDS batch (anatomy at 1 mm, dwi at 2 mm)."""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.config.loader import load_config

REPO = Path(__file__).resolve().parents[2]
KEY = "k" * 40


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRI_ANON_KEY", KEY)


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


# --- scripts/run_stage3_bids_pipeline.py (QA2-script) ---

_spec = importlib.util.spec_from_file_location("run_stage3_bids_pipeline", REPO / "scripts" / "run_stage3_bids_pipeline.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def _dataset_with_a_failing_study(root: Path) -> Path:
    dataset = _dataset(root)
    broken = np.ones((4, 4, 4), dtype=np.float32)
    broken[1, 1, 1] = np.nan
    (dataset / "sub-02" / "anat").mkdir(parents=True)
    nib.save(nib.Nifti1Image(broken, np.eye(4)), dataset / "sub-02" / "anat" / "sub-02_T1w.nii.gz")
    return dataset


def test_script_writes_series_and_a_clean_reproducible_manifest(tmp_path: Path, capsys) -> None:
    dataset = _dataset_with_a_failing_study(tmp_path)
    output_dir, manifest_path = tmp_path / "out", tmp_path / "manifest" / "run.json"
    args = [str(dataset), "--output-dir", str(output_dir), "--manifest-path", str(manifest_path)]

    assert script.main(args) == 0
    out = capsys.readouterr().out

    assert sorted(p.name for p in output_dir.iterdir()) == [f"study-001_series-00{i}.nii.gz" for i in (1, 2, 3)]
    assert all(nib.load(p).get_data_dtype() == np.float32 for p in output_dir.iterdir())
    assert "Studies: 2  ok: 1  failed in a step: 1  files written: 3" in out
    assert "Errors by type: {'ValueError': 1}" in out  # the NaN study; FLAIR outside both lists is not an error
    assert "Manifest without source paths: True  reproduced from manifest: True" in out
    assert "WARNING: an output is on drive C: or in the temporary directory" in out  # tmp_path is in the temp dir
    assert "sub-" not in out and str(tmp_path) not in out and KEY not in out
    text = manifest_path.read_text(encoding="utf-8")
    assert "sub-" not in text and str(tmp_path) not in text and tmp_path.as_posix() not in text and KEY not in text

    assert script.main(args) == 1  # nothing is overwritten
    assert "remove them first" in capsys.readouterr().out


def test_script_without_key_stops_before_creating_anything(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.delenv("MRI_ANON_KEY")
    dataset = _dataset(tmp_path)

    code = script.main([str(dataset), "--output-dir", str(tmp_path / "out"), "--manifest-path", str(tmp_path / "m.json")])

    assert code == 2
    assert capsys.readouterr().out == "MRI_ANON_KEY is not set or is shorter than 32 characters; nothing was run.\n"
    assert not (tmp_path / "out").exists() and not (tmp_path / "m.json").exists()


@pytest.mark.parametrize("missing", ["--output-dir", "--manifest-path"])
def test_script_requires_output_dir_and_manifest_path(missing: str, tmp_path: Path, capsys) -> None:
    args = {"--output-dir": str(tmp_path / "out"), "--manifest-path": str(tmp_path / "m.json")}
    del args[missing]

    with pytest.raises(SystemExit) as exit_info:
        script.main([str(tmp_path), *[x for pair in args.items() for x in pair]])

    assert exit_info.value.code == 2
    assert f"the following arguments are required: {missing}" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_script_with_missing_dataset_prints_a_fixed_message(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "sub-99"

    code = script.main([str(missing), "--output-dir", str(tmp_path / "out"), "--manifest-path", str(tmp_path / "m.json")])

    assert code == 2
    assert capsys.readouterr().out == "Dataset directory not found.\n"


def test_discouraged_location() -> None:
    assert script.is_discouraged_location(Path(tempfile.gettempdir()) / "x")
    assert script.is_discouraged_location(Path("C:/data/out")) == (sys.platform == "win32")


def _raise_oserror_naming(path: Path):
    def fail(*args, **kwargs):
        raise OSError(f"cannot read {path}")

    return fail


@pytest.mark.parametrize("target", ["reader", "manifest_write"])
def test_script_run_failure_prints_only_the_type(target: str, monkeypatch, tmp_path: Path, capsys) -> None:
    dataset = _dataset(tmp_path)
    secret = dataset / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_T1w.nii.gz"
    if target == "reader":
        monkeypatch.setattr(script.BIDSBatchReader, "iter_studies", _raise_oserror_naming(secret))
    else:
        monkeypatch.setattr(script.RunManifest, "write", _raise_oserror_naming(secret))

    code = script.main([str(dataset), "--output-dir", str(tmp_path / "out"), "--manifest-path", str(tmp_path / "m.json")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.splitlines()[-1] == "Run failed: OSError"
    console = captured.out + captured.err
    assert "sub-" not in console and str(tmp_path) not in console and tmp_path.as_posix() not in console
