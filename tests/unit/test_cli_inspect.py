"""``inspect`` shows allow-listed metadata only; never ids, UIDs, header values or paths."""

import json
import logging
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main
from test_anonymize_dicom_tree import PLANTED, write_synthetic_series

BIDS_SECRETS = ["PATIENT01", "VISIT1", "Doe^Secret", "St Mary Hospital"]


@pytest.fixture(autouse=True)
def _reset_output():
    root = logging.getLogger()
    level = root.level
    yield
    _common.configure_output()
    root.setLevel(level)


def _nifti(path: Path, shape=(4, 4, 3)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.arange(np.prod(shape), dtype=np.int16).reshape(shape)
    nib.save(nib.Nifti1Image(data, np.diag([2.0, 2.0, 3.0, 1.0])), path)
    return path


def _bids(root: Path) -> Path:
    """One valid T1w with a sidecar carrying PHI, plus one unreadable T2w."""
    anat = root / "sub-PATIENT01" / "ses-VISIT1" / "anat"
    _nifti(anat / "sub-PATIENT01_ses-VISIT1_T1w.nii.gz")
    sidecar = {"RepetitionTime": 2.3, "PatientName": "Doe^Secret", "InstitutionName": "St Mary Hospital"}
    (anat / "sub-PATIENT01_ses-VISIT1_T1w.json").write_text(json.dumps(sidecar), encoding="utf-8")
    (anat / "sub-PATIENT01_ses-VISIT1_T2w.nii.gz").write_bytes(b"not a nifti")
    return root


def _assert_clean(text: str, secrets: list[str], tmp_path: Path) -> None:
    leaked = [secret for secret in [*secrets, str(tmp_path), tmp_path.name] if secret in text]
    assert not leaked


def test_bids_text_shows_whitelisted_metadata_and_counts_errors(tmp_path, capsys):
    assert main(["inspect", str(_bids(tmp_path / "in")), "--format", "bids"]) == 0
    out = capsys.readouterr().out
    assert "Study 1: 1 series" in out and '"RepetitionTime": 2.3' in out
    assert 'dtype: "int16"' in out and "Studies: 1" in out
    assert "Errors by type: {'ValueError': 1}" in out
    _assert_clean(out, BIDS_SECRETS, tmp_path)


def test_bids_json_is_parseable_and_clean(tmp_path, capsys):
    assert main(["inspect", str(_bids(tmp_path / "in")), "--format", "bids", "--json"]) == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    series = result["studies"][0]["series"][0]
    assert series["modality"] == "T1w" and series["sidecar"] == {"RepetitionTime": 2.3}
    assert series["shape"] == [4, 4, 3] and series["intensity"]["max"] == 47.0
    assert result["errors"] == {"ValueError": 1}
    _assert_clean(out, BIDS_SECRETS, tmp_path)


def test_verbose_logs_and_stderr_are_clean(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    assert main(["--verbose", "inspect", str(_bids(tmp_path / "in")), "--format", "bids", "--json"]) == 0
    captured = capsys.readouterr()
    for text in (captured.out, captured.err, caplog.text):
        _assert_clean(text, BIDS_SECRETS, tmp_path)


def test_bids_single_file(tmp_path, capsys):
    root = _bids(tmp_path / "in")
    file = next(root.rglob("*_T1w.nii.gz"))
    assert main(["inspect", str(file), "--format", "bids"]) == 0
    assert "Studies: 1" in capsys.readouterr().out


def test_nifti_file_and_directory(tmp_path, capsys):
    first = _nifti(tmp_path / "in" / "sub-PATIENT01_scan.nii.gz")
    _nifti(tmp_path / "in" / "b" / "other.nii", shape=(2, 2, 2))
    assert main(["inspect", str(first), "--format", "nifti"]) == 0
    assert "Studies: 1" in capsys.readouterr().out
    assert main(["inspect", str(tmp_path / "in"), "--format", "nifti", "--json"]) == 0
    out = capsys.readouterr().out
    assert len(json.loads(out)["studies"]) == 2
    _assert_clean(out, ["PATIENT01"], tmp_path)


def test_dicom_headers_only_without_phi(tmp_path, capsys):
    write_synthetic_series(tmp_path / "in" / "series")
    (tmp_path / "in" / "README").write_text("not dicom", encoding="utf-8")
    assert main(["inspect", str(tmp_path / "in"), "--format", "dicom", "--json"]) == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    series = result["studies"][0]["series"][0]
    assert series["modality"] == "MR" and series["dtype"] is None and "rows" in series
    assert sum(result["errors"].values()) == 1
    _assert_clean(out, PLANTED, tmp_path)


@pytest.mark.parametrize(
    "argv",
    [
        ["inspect", "{tmp}/missing", "--format", "nifti"],
        ["inspect", "{tmp}/file.nii.gz", "--format", "dicom"],
        ["inspect", "{tmp}/notes.txt", "--format", "nifti"],
        ["inspect", "{tmp}", "--format", "png"],
        ["inspect", "{tmp}"],
    ],
)
def test_invalid_input_exits_two(tmp_path, capsys, argv):
    _nifti(tmp_path / "file.nii.gz")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert main([arg.format(tmp=tmp_path) for arg in argv]) == 2
    _assert_clean(capsys.readouterr().out, [], tmp_path)


def test_unreadable_single_file_fails_with_type_only(tmp_path, capsys):
    bad = tmp_path / "sub-PATIENT01_T1w.nii.gz"
    bad.write_bytes(b"garbage")
    assert main(["inspect", str(bad), "--format", "nifti"]) == 1
    out = capsys.readouterr().out
    assert "Run failed: ValueError" in out
    _assert_clean(out, ["PATIENT01"], tmp_path)


def _truncated(path: Path) -> Path:
    """Loads lazily (header intact) but fails when the voxels are read."""
    _nifti(path, shape=(16, 16, 16))
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    return path


@pytest.mark.parametrize("fmt", ["nifti", "bids"])
def test_truncated_volume_is_counted_and_the_batch_continues(tmp_path, capsys, fmt):
    root = _bids(tmp_path / "in")  # its unreadable T2w is one reader error
    truncated = _truncated(root / "sub-PATIENT02" / "anat" / "sub-PATIENT02_T1w.nii.gz")
    NIfTIReader().load_study(truncated, lazy=True)  # loads: the failure comes later, in summarize_study
    assert main(["inspect", str(root), "--format", fmt]) == 0
    out = capsys.readouterr().out
    assert "Studies: 1" in out and "Errors by type: {'ValueError': 2}" in out
    _assert_clean(out, [*BIDS_SECRETS, "PATIENT02"], tmp_path)
    assert main(["inspect", str(root), "--format", fmt, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["studies"]) == 1 and result["errors"] == {"ValueError": 2}


@pytest.mark.parametrize("argv", [["inspect", "{tmp}/missing", "--format", "nifti", "--json"],
                                  ["inspect", "{tmp}/empty", "--format", "bids", "--json"]])
def test_json_errors_go_to_stderr_and_stdout_stays_empty(tmp_path, capsys, argv):
    (tmp_path / "empty").mkdir()
    assert main([arg.format(tmp=tmp_path) for arg in argv]) in (1, 2)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err and str(tmp_path) not in captured.err
