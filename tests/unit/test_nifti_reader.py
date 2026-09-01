from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader


def test_batch_reader_loads_nested_valid_studies_and_skips_invalid_files(
    tmp_path: Path,
) -> None:
    study_dir = tmp_path / "nested" / "study"
    study_dir.mkdir(parents=True, exist_ok=True)
    valid_1 = study_dir / "scan_a.nii.gz"
    valid_2 = tmp_path / "scan_b.nii.gz"
    invalid = tmp_path / "notes.txt"
    corrupt = study_dir / "broken.nii.gz"

    data_a = np.arange(24, dtype=np.int16).reshape(2, 3, 4)
    data_b = np.arange(12, dtype=np.int16).reshape(1, 3, 4)
    nib.save(nib.Nifti1Image(data_a, np.eye(4)), valid_1)
    nib.save(nib.Nifti1Image(data_b, np.eye(4)), valid_2)
    invalid.write_text("not a nifti")
    corrupt.write_bytes(b"not a valid nifti")

    studies = NIfTIBatchReader().load_studies(tmp_path)

    assert len(studies) == 2
    assert [study.series[0].files[0].name for study in studies] == [
        valid_1.name,
        valid_2.name,
    ]
    np.testing.assert_array_equal(studies[0].series[0].volume, data_a.astype(np.float64))
    np.testing.assert_array_equal(studies[1].series[0].volume, data_b.astype(np.float64))


def test_load_study_creates_one_series_with_volume_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "scan.nii.gz"
    data = np.arange(24, dtype=np.int16).reshape(2, 3, 4)
    affine = np.diag([1.5, 2.0, 2.5, 1.0])
    image = nib.Nifti1Image(data, affine)
    image.header["qform_code"] = 1
    image.header["sform_code"] = 1
    nib.save(image, path)

    study = NIfTIReader().load_study(path)

    assert study.study_uid is None
    assert len(study.series) == 1
    series = study.series[0]
    assert series.series_uid is None
    assert series.modality is None
    assert series.files == [path]
    assert series.volume is not None
    np.testing.assert_array_equal(series.volume, data.astype(np.float64))
    assert series.metadata["shape"] == (2, 3, 4)
    assert series.metadata["voxel_size"] == (1.5, 2.0, 2.5)
    assert series.metadata["datatype"] == "int16"
    assert series.metadata["bitpix"] == 16
    np.testing.assert_array_equal(series.metadata["affine"], affine)
    assert series.metadata["qform_code"] == 1
    assert series.metadata["sform_code"] == 1
    assert series.metadata["orientation"] == ("R", "A", "S")


def test_load_study_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        NIfTIReader().load_study(tmp_path / "missing.nii.gz")


def test_load_study_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must identify a file"):
        NIfTIReader().load_study(tmp_path)


def test_load_study_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "scan.img"
    path.touch()

    with pytest.raises(ValueError, match="Unsupported NIfTI file extension"):
        NIfTIReader().load_study(path)


def test_load_study_rejects_corrupt_nifti_file(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.nii"
    path.write_bytes(b"not a NIfTI image")

    with pytest.raises(ValueError, match="Unable to load NIfTI image"):
        NIfTIReader().load_study(path)
