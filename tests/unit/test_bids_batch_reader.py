from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader


def _nifti(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.int16), np.eye(4)), path)


def _dataset(root: Path) -> None:
    (root / "dataset_description.json").write_text('{"Name": "x", "BIDSVersion": "1.9.0"}')
    _nifti(root / "sub-02" / "anat" / "sub-02_T1w.nii.gz")
    _nifti(root / "sub-01" / "ses-02" / "anat" / "sub-01_ses-02_T1w.nii.gz")
    _nifti(root / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_T1w.nii.gz")
    _nifti(root / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_T2w.nii.gz")


def test_three_studies_in_deterministic_order(tmp_path: Path) -> None:
    _dataset(tmp_path)
    studies = BIDSBatchReader().load_studies(tmp_path)
    assert [(s.subject_id, s.session_id) for s in studies] == [
        ("01", "01"),
        ("01", "02"),
        ("02", None),
    ]
    assert len(studies[0].series) == 2


def test_flexible_mode_without_description_and_loose_files(tmp_path: Path) -> None:
    _nifti(tmp_path / "sub-001_ses-01_T1w.nii.gz")
    _nifti(tmp_path / "sub-002_T1w.nii")
    studies = BIDSBatchReader().load_studies(tmp_path)
    assert [s.subject_id for s in studies] == ["001", "002"]


def test_broken_subject_is_reported_and_others_load(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / "sub-03").mkdir()
    (tmp_path / "sub-03" / "sub-03_T1w.nii.gz").write_bytes(b"garbage")
    (tmp_path / "sub-04_bad_name.nii").write_bytes(b"")  # unparseable name
    errors: list[Path] = []
    studies = BIDSBatchReader().load_studies(tmp_path, on_error=lambda p, e: errors.append(p))
    assert len(studies) == 3
    assert sorted(p.name for p in errors) == ["sub-03_T1w.nii.gz", "sub-04_bad_name.nii"]


def test_streaming_is_lazy(tmp_path: Path, monkeypatch) -> None:
    _dataset(tmp_path)
    reader = BIDSBatchReader()
    calls = []
    original = reader._reader.load_files

    def counting(files, on_error=None, **kwargs):
        calls.append(files)
        return original(files, on_error, **kwargs)

    monkeypatch.setattr(reader._reader, "load_files", counting)
    it = reader.iter_studies(tmp_path)
    assert calls == []
    assert next(it).session_id == "01"
    assert len(calls) == 1
    assert next(it).session_id == "02"
    assert len(calls) == 2


def test_validation(tmp_path: Path) -> None:
    reader = BIDSBatchReader()
    with pytest.raises(FileNotFoundError):
        reader.iter_studies(tmp_path / "missing")
    f = tmp_path / "f.txt"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        reader.iter_studies(f)
    with pytest.raises(ValueError, match="No valid"):
        reader.load_studies(tmp_path)
    (tmp_path / "dataset_description.json").write_text('{"PatientName": "secret", oops')
    with pytest.raises(ValueError) as exc:
        reader.iter_studies(tmp_path)
    assert "secret" not in str(exc.value)


def test_hidden_directories_are_ignored_silently(tmp_path: Path) -> None:
    from mri_dataset_tool.infrastructure.bids.reader import BIDSReader

    _dataset(tmp_path)
    for hidden in (".git/objects", ".datalad"):
        (tmp_path / hidden).mkdir(parents=True)
        (tmp_path / hidden / "SHA256E-s1--abc.nii.gz").write_bytes(b"annex")
        (tmp_path / hidden / "sub-09_T1w.nii.gz").write_bytes(b"fake")
    errors: list[Path] = []
    studies = BIDSBatchReader().load_studies(tmp_path, on_error=lambda p, e: errors.append(p))
    assert len(studies) == 3 and errors == []
    study = BIDSReader().load_study(tmp_path / "sub-02", on_error=lambda p, e: errors.append(p))
    assert errors == [] and study.subject_id == "02"


def test_root_under_hidden_directory_still_loads(tmp_path: Path) -> None:
    root = tmp_path / ".hidden" / "ds"
    root.mkdir(parents=True)
    _dataset(root)
    assert len(BIDSBatchReader().load_studies(root)) == 3
