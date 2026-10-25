"""C2: ``convert`` in both directions; validation before creating anything; counts only."""

import logging
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main
from test_anonymize_dicom_tree import PLANTED, write_synthetic_series


@pytest.fixture(autouse=True)
def _reset_output():
    root = logging.getLogger()
    level = root.level
    yield
    _common.configure_output()
    root.setLevel(level)


def _nifti(path: Path, shape=(4, 4, 3)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.ones(shape, dtype=np.float32), np.eye(4)), path)
    return path


def _clean(text: str, secrets: list[str], tmp_path: Path) -> bool:
    return not [secret for secret in [*secrets, str(tmp_path)] if secret in text]


def test_dicom_to_nifti(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    write_synthetic_series(tmp_path / "in" / "series")
    (tmp_path / "in" / "README").write_text("not dicom", encoding="utf-8")
    out_dir = tmp_path / "out"
    assert main(["--verbose", "convert", "dicom-to-nifti", str(tmp_path / "in"), str(out_dir)]) == 0
    captured = capsys.readouterr()
    out = captured.out
    assert _clean(captured.err, PLANTED, tmp_path) and _clean(caplog.text, PLANTED, tmp_path)
    assert "Studies converted: 1  series written: 1" in out
    assert "Errors by type: {'InvalidDicomError': 1}" in out
    assert [p.name for p in out_dir.iterdir()] == ["study-001_series-001.nii.gz"]
    assert _clean(out, PLANTED, tmp_path)


def test_nifti_to_dicom_file_and_directory_with_a_4d_failure(tmp_path, capsys):
    source = _nifti(tmp_path / "in" / "sub-PATIENT01_T1w.nii.gz")
    _nifti(tmp_path / "in" / "four_d.nii.gz", shape=(4, 4, 3, 2))
    assert main(["convert", "nifti-to-dicom", str(source), str(tmp_path / "out1")]) == 0
    assert "Studies converted: 1  DICOM files written: 3" in capsys.readouterr().out
    assert main(["convert", "nifti-to-dicom", str(tmp_path / "in"), str(tmp_path / "out2")]) == 0
    out = capsys.readouterr().out
    assert "Studies converted: 1" in out and "Errors by type: {'ValueError': 1}" in out
    assert _clean(out, ["PATIENT01"], tmp_path)


@pytest.mark.parametrize(
    ("direction", "source", "output", "code"),
    [
        ("dicom-to-nifti", "missing", "out", 2),
        ("dicom-to-nifti", "in/a.nii.gz", "out", 2),  # DICOM input must be a directory
        ("nifti-to-dicom", "in/notes.txt", "out", 2),
        ("dicom-to-nifti", "in", "in/out", 2),  # output inside the input
        ("nifti-to-dicom", "in", "in", 2),  # output equal to the input
        ("nifti-to-dicom", "in", "file_out", 2),  # output is a file
        ("dicom-to-nifti", "in", "busy", 1),  # output not empty
    ],
)
def test_validation_before_creating_anything(tmp_path, capsys, direction, source, output, code):
    _nifti(tmp_path / "in" / "a.nii.gz")
    (tmp_path / "in" / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "file_out").write_text("x", encoding="utf-8")
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "previous.nii.gz").write_text("x", encoding="utf-8")
    before = sorted(tmp_path.rglob("*"))
    assert main(["convert", direction, str(tmp_path / source), str(tmp_path / output)]) == code
    assert sorted(tmp_path.rglob("*")) == before
    assert _clean(capsys.readouterr().out, [], tmp_path)


def test_no_valid_input_fails_with_type_only(tmp_path, capsys):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "README").write_text("x", encoding="utf-8")
    assert main(["convert", "dicom-to-nifti", str(tmp_path / "in"), str(tmp_path / "out")]) == 1
    assert "Run failed: ValueError" in capsys.readouterr().out


def test_discouraged_output_warns(tmp_path, capsys):
    _nifti(tmp_path / "in" / "a.nii.gz")
    assert main(["convert", "nifti-to-dicom", str(tmp_path / "in"), str(tmp_path / "out")]) == 0
    assert "WARNING: an output is on drive C: or in the temporary directory" in capsys.readouterr().out
