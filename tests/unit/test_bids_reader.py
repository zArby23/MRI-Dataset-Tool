from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.bids.reader import BIDSReader


def _nifti(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.int16), np.eye(4)), path)


def test_subject_session_dir_with_sidecar(tmp_path: Path) -> None:
    anat = tmp_path / "sub-01" / "ses-01" / "anat"
    _nifti(anat / "sub-01_ses-01_T1w.nii.gz")
    (anat / "sub-01_ses-01_T1w.json").write_text('{"RepetitionTime": 2.3}')

    study = BIDSReader().load_study(tmp_path / "sub-01" / "ses-01")

    assert (study.study_uid, study.subject_id, study.session_id) == (None, "01", "01")
    (series,) = study.series
    assert series.modality == "T1w"
    assert series.metadata["bids"]["sub"] == "01"
    assert series.metadata["sidecar"] == {"RepetitionTime": 2.3}
    assert series.volume is not None


def test_loose_file_flexible_mode(tmp_path: Path) -> None:
    f = tmp_path / "sub-001_ses-01_T1w.nii"
    _nifti(f)
    study = BIDSReader().load_study(f)
    assert (study.subject_id, study.session_id) == ("001", "01")
    assert "sidecar" not in study.series[0].metadata


def test_invalid_sidecar_is_series_error_not_crash(tmp_path: Path) -> None:
    _nifti(tmp_path / "sub-01_T1w.nii.gz")
    _nifti(tmp_path / "sub-01_T2w.nii.gz")
    (tmp_path / "sub-01_T1w.json").write_text('{"PatientName": "secret", oops')
    errors: list[tuple[Path, Exception]] = []

    study = BIDSReader().load_study(tmp_path, on_error=lambda p, e: errors.append((p, e)))

    assert [s.modality for s in study.series] == ["T2w"]
    assert len(errors) == 1 and errors[0][0].name == "sub-01_T1w.nii.gz"
    assert "secret" not in str(errors[0][1]) and errors[0][1].__cause__ is None


def test_no_valid_files_and_missing_path(tmp_path: Path) -> None:
    (tmp_path / "sub-01_T1w.json").write_text("{}")
    with pytest.raises(ValueError):
        BIDSReader().load_study(tmp_path)
    with pytest.raises(FileNotFoundError):
        BIDSReader().load_study(tmp_path / "missing")


def test_mixed_subjects_reported(tmp_path: Path) -> None:
    _nifti(tmp_path / "sub-01_T1w.nii")
    _nifti(tmp_path / "sub-02_T1w.nii")
    errors: list[Path] = []
    study = BIDSReader().load_study(tmp_path, on_error=lambda p, e: errors.append(p))
    assert study.subject_id == "01" and len(errors) == 1


def test_sidecar_values_are_kept_but_never_logged(tmp_path: Path, caplog) -> None:
    _nifti(tmp_path / "sub-01_T1w.nii.gz")
    _nifti(tmp_path / "sub-01_T2w.nii.gz")
    (tmp_path / "sub-01_T1w.json").write_text('{"PatientName": "secret"}')
    (tmp_path / "sub-01_T2w.json").write_text('{"PatientName": "secret2", oops')

    with caplog.at_level("DEBUG"):
        study = BIDSReader().load_study(tmp_path)

    assert study.series[0].metadata["sidecar"] == {"PatientName": "secret"}
    assert "secret" not in caplog.text
