"""C4: ``process`` runs the configured pipeline through pipeline_run; counts only on the console."""

import json
import logging
from collections import namedtuple
import shutil
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.services import disk_space
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main

REPO = Path(__file__).resolve().parents[2]
KEY = "k" * 40
SECRETS = ["PATIENT01", "PATIENT02", "PATIENT03", "VISIT1", "Doe^Secret", KEY]
STEPS = """pipeline:
  steps:
    - name: validate
    - name: anonymize
    - name: reorient
    - name: resample
      params: {spacing: [2.0, 2.0, 2.0]}
    - name: normalize
report:
  path: data/output/run.json
"""


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    """Run from tmp_path with its own config/default.yaml (paths of the config are relative to the cwd)."""
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / "config" / "default.yaml", tmp_path / "config" / "default.yaml")
    (tmp_path / "config" / "run.yaml").write_text(STEPS, encoding="utf-8")
    root = logging.getLogger()
    level = root.level
    yield
    _common.configure_output()
    root.setLevel(level)


def _bids(root: Path) -> Path:
    """Three sessions with a T1w; PATIENT03 holds a NaN (validate rejects it); one sidecar carries PHI."""
    rng = np.random.default_rng(0)
    for subject in ("PATIENT01", "PATIENT02", "PATIENT03"):
        volume = rng.uniform(10, 100, (4, 5, 3)).astype(np.float32)
        if subject == "PATIENT03":
            volume[1, 1, 1] = np.nan
        anat = root / f"sub-{subject}" / "ses-VISIT1" / "anat"
        anat.mkdir(parents=True)
        nib.save(nib.Nifti1Image(volume, np.diag([1.5, 1.5, 1.5, 1.0])), anat / f"sub-{subject}_ses-VISIT1_T1w.nii.gz")
        (anat / f"sub-{subject}_ses-VISIT1_T1w.json").write_text(
            json.dumps({"RepetitionTime": 2.3, "PatientName": "Doe^Secret"}), encoding="utf-8"
        )
    return root


def _clean(text: str, tmp_path: Path) -> bool:
    return not [s for s in [*SECRETS, str(tmp_path), tmp_path.as_posix()] if s in text]


def _argv(source, fmt="bids", *extra, config="config/run.yaml", out="out", manifest="m/run.json"):
    argv = ["process", str(source), "--format", fmt, "--config", config, "--output-dir", out]
    return argv + (["--manifest-path", manifest] if manifest else []) + list(extra)


def test_bids_with_verify_is_reproduced_and_clean(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    assert main(["--verbose", *_argv(_bids(tmp_path / "ds"), "bids", "--verify")]) == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "Processing studies..." in out and "Verifying: running again" in out
    assert "Studies: 3  ok: 2  failed in a step: 1  files written: 2" in out
    assert "Errors by type: {'ValueError': 1}" in out and "Replay errors by type: {'ValueError': 1}" in out
    assert "Manifest without source paths: yes" in out and "Reproduced from manifest: yes" in out
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["study-001_series-001.nii.gz", "study-002_series-001.nii.gz"]
    manifest = (tmp_path / "m" / "run.json").read_text(encoding="utf-8")
    for text in (out, captured.err, caplog.text, manifest):
        assert _clean(text, tmp_path)
    assert "sub-" not in manifest


def test_nifti_without_verify_uses_the_config_manifest_path(tmp_path, capsys):
    source = tmp_path / "in"
    source.mkdir()
    nib.save(nib.Nifti1Image(np.arange(60, dtype=np.float32).reshape(4, 5, 3), np.eye(4)), source / "sub-PATIENT01.nii.gz")
    assert main(_argv(source, "nifti", manifest=None)) == 0
    out = capsys.readouterr().out
    assert "Reproduced from manifest: not checked (use --verify)" in out and "Verifying" not in out
    assert (tmp_path / "data" / "output" / "run.json").is_file() and (tmp_path / "out" / "study-001.nii.gz").is_file()
    assert _clean(out, tmp_path)


def test_quiet_hides_stage_lines(tmp_path, capsys):
    assert main(["--quiet", *_argv(_bids(tmp_path / "ds"))]) == 0
    out = capsys.readouterr().out
    assert "Processing studies..." not in out and "Studies: 3" in out


def test_dicom_points_to_convert(tmp_path, capsys):
    assert main(_argv(_bids(tmp_path / "ds"), "dicom")) == 2
    assert "convert dicom-to-nifti" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"source": "missing"}, "Input directory not found."),
        ({"config": "config/none.yaml"}, "Config file not found."),
        ({"config": "config/bad.yaml"}, "Invalid config: ValueError"),
        ({"config": "config/unknown_step.yaml"}, "Invalid config: ValueError"),
        ({"out": "ds/out"}, "Outputs must not be inside the input directory."),
        ({"manifest": "ds/m.json"}, "Outputs must not be inside the input directory."),
        ({"out": "a_file"}, "Output path is not a directory."),
    ],
)
def test_invalid_arguments_exit_two_before_creating_anything(tmp_path, capsys, change, message):
    _bids(tmp_path / "ds")
    (tmp_path / "config" / "bad.yaml").write_text("pipeline: [unclosed", encoding="utf-8")
    (tmp_path / "config" / "unknown_step.yaml").write_text("pipeline:\n  steps:\n    - name: nope\n", encoding="utf-8")
    (tmp_path / "a_file").write_text("x", encoding="utf-8")
    before = sorted(tmp_path.rglob("*"))
    kwargs = {k: v for k, v in change.items() if k != "source"}
    assert main(_argv(tmp_path / change.get("source", "ds"), "bids", **kwargs)) == 2
    out = capsys.readouterr().out
    assert message in out and _clean(out, tmp_path)
    assert sorted(tmp_path.rglob("*")) == before


def test_key_is_required_only_with_the_anonymize_step(tmp_path, monkeypatch, capsys):
    source = _bids(tmp_path / "ds")
    monkeypatch.delenv("MRI_ANON_KEY")
    assert main(_argv(source)) == 2
    assert "MRI_ANON_KEY is not set" in capsys.readouterr().out and not (tmp_path / "out").exists()
    (tmp_path / "config" / "plain.yaml").write_text("pipeline:\n  steps:\n    - name: reorient\n", encoding="utf-8")
    assert main(_argv(source, config="config/plain.yaml")) == 0
    assert "Manifest without source paths: no (no anonymize step" in capsys.readouterr().out


def test_previous_outputs_exit_one(tmp_path, capsys):
    source = _bids(tmp_path / "ds")
    assert main(_argv(source)) == 0
    before = sorted(tmp_path.rglob("*"))
    assert main(_argv(source, manifest="m/other.json")) == 1  # study-*.nii.gz already in out/
    assert main(_argv(source, out="out2")) == 1  # the manifest already exists
    assert "Outputs of a previous run exist" in capsys.readouterr().out
    assert sorted(tmp_path.rglob("*")) == before


def test_failed_stage_exits_one_with_type_only(tmp_path, capsys):
    (tmp_path / "m").write_text("a file where the manifest directory should be", encoding="utf-8")
    assert main(_argv(_bids(tmp_path / "ds"))) == 1
    out = capsys.readouterr().out
    assert "Run failed at manifest: " in out and _clean(out, tmp_path)


@pytest.mark.parametrize(("free", "warned"), [(10, True), (10**15, False)])
def test_low_disk_space_warns_without_changing_the_exit_code(tmp_path, monkeypatch, capsys, free, warned):
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(disk_space.shutil, "disk_usage", lambda path: usage(free, 0, free))
    assert main(_argv(_bids(tmp_path / "ds"))) == 0
    out = capsys.readouterr().out
    assert ("WARNING INSUFFICIENT_DISK_SPACE" in out) == warned
    assert "drive C:" not in out
    assert _clean(out, tmp_path)


def test_empty_input_fails_without_leaving_the_output_directory(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert main(_argv(tmp_path / "empty")) == 1
    assert "Run failed at process: ValueError" in capsys.readouterr().out
    assert not (tmp_path / "out").exists() and not (tmp_path / "m").exists()
