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


def _json(path: Path, text: str) -> None:
    path.write_text(text)


def test_sidecar_inheritance_merges_general_to_specific(tmp_path: Path) -> None:
    from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader

    _json(tmp_path / "dataset_description.json", "{}")
    _json(tmp_path / "T1w.json", '{"A": "root", "B": "root"}')
    _json(tmp_path / "task-rest_bold.json", '{"Task": "rest"}')
    anat = tmp_path / "sub-01" / "ses-01" / "anat"
    _nifti(anat / "sub-01_ses-01_acq-x_T1w.nii.gz")
    _json(tmp_path / "sub-01" / "sub-01_T1w.json", '{"B": "sub", "C": "sub"}')
    _json(anat / "sub-01_ses-01_acq-x_T1w.json", '{"C": "own"}')
    _json(anat / "sub-01_ses-01_acq-y_T1w.json", '{"Z": 1}')  # other acq: not applicable

    expected = {"A": "root", "B": "sub", "C": "own"}
    study = BIDSReader().load_study(tmp_path / "sub-01" / "ses-01")  # root found by climbing
    assert study.series[0].metadata["sidecar"] == expected
    (batch,) = BIDSBatchReader().load_studies(tmp_path)
    assert batch.series[0].metadata["sidecar"] == expected


def test_no_root_reads_only_own_directory(tmp_path: Path) -> None:
    _json(tmp_path / "T1w.json", '{"Foreign": 1}')
    sub = tmp_path / "data"
    _nifti(sub / "sub-01_T1w.nii")
    _json(sub / "sub-01_T1w.json", '{"Own": 1}')
    study = BIDSReader().load_study(sub / "sub-01_T1w.nii")
    assert study.series[0].metadata["sidecar"] == {"Own": 1}


def test_inherited_invalid_json_reported_without_phi(tmp_path: Path, caplog) -> None:
    _json(tmp_path / "dataset_description.json", "{}")
    _json(tmp_path / "T1w.json", '{"PatientName": "secret", oops')
    _json(tmp_path / "T2w.json", '{"PatientName": "secret"}')
    _nifti(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    _nifti(tmp_path / "sub-01" / "anat" / "sub-01_T2w.nii.gz")
    errors: list[Exception] = []
    with caplog.at_level("DEBUG"):
        study = BIDSReader().load_study(tmp_path / "sub-01", on_error=lambda p, e: errors.append(e))
    assert [s.modality for s in study.series] == ["T2w"]
    assert len(errors) == 1 and errors[0].__cause__ is None and "secret" not in str(errors[0])
    assert "secret" not in caplog.text


def test_entity_order_matters(tmp_path: Path) -> None:
    _json(tmp_path / "dataset_description.json", "{}")
    _nifti(tmp_path / "sub-01" / "anat" / "sub-01_acq-x_run-1_T1w.nii.gz")
    _json(tmp_path / "run-1_acq-x_T1w.json", '{"Wrong": 1}')  # reversed order: not applicable
    _json(tmp_path / "acq-x_run-1_T1w.json", '{"Right": 1}')
    study = BIDSReader().load_study(tmp_path / "sub-01")
    assert study.series[0].metadata["sidecar"] == {"Right": 1}


def test_depth_beats_entity_count_and_entity_count_wins_within_directory(tmp_path: Path) -> None:
    _json(tmp_path / "dataset_description.json", "{}")
    anat = tmp_path / "sub-01" / "anat"
    _nifti(anat / "sub-01_T1w.nii.gz")
    _json(tmp_path / "sub-01_T1w.json", '{"K": "root", "R": "root"}')
    _json(anat / "T1w.json", '{"K": "anat-general", "D": "general"}')
    _json(anat / "sub-01_T1w.json", '{"D": "specific"}')
    study = BIDSReader().load_study(tmp_path / "sub-01")
    assert study.series[0].metadata["sidecar"] == {"K": "anat-general", "R": "root", "D": "specific"}


def test_load_study_lazy_passes_through_to_nifti_reader(tmp_path: Path) -> None:
    from mri_dataset_tool.infrastructure.processing.arrays import load_array

    path = tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz"
    _nifti(path)
    eager = BIDSReader().load_study(tmp_path / "sub-01")
    lazy = BIDSReader().load_study(tmp_path / "sub-01", lazy=True)

    assert isinstance(eager.series[0].volume, np.ndarray)
    assert not isinstance(lazy.series[0].volume, np.ndarray)
    assert lazy.series[0].metadata["bids"] == eager.series[0].metadata["bids"]
    np.testing.assert_array_equal(load_array(lazy.series[0].volume, np.float64), eager.series[0].volume)


def test_upper_case_extension_is_tolerated(tmp_path: Path) -> None:
    # BIDS requires lower-case extensions; the reader tolerates them.
    anat = tmp_path / "sub-01" / "anat"
    _nifti(anat / "sub-01_T2w.NII.GZ")
    (anat / "sub-01_T2w.json").write_text('{"EchoTime": 0.1}')
    (series,) = BIDSReader().load_study(tmp_path / "sub-01").series
    assert series.metadata["bids"]["extension"] == ".NII.GZ"
    assert series.metadata["sidecar"] == {"EchoTime": 0.1}
