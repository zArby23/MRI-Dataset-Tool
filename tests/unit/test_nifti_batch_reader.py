from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader


def _truncated_gz(tmp_path: Path, name: str = "truncated.nii.gz") -> Path:
    good = tmp_path / "good_src.nii.gz"
    nib.save(nib.Nifti1Image(np.arange(4096, dtype=np.int16).reshape(16, 16, 16), np.eye(4)), good)
    raw = good.read_bytes()
    good.unlink()
    path = tmp_path / name
    path.write_bytes(raw[: len(raw) // 2])
    return path


def test_iter_studies_missing_path_raises_on_call_without_next(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        NIfTIBatchReader().iter_studies(tmp_path / "missing")


def test_iter_studies_file_path_raises_on_call_without_next(tmp_path: Path) -> None:
    file_path = tmp_path / "scan.nii"
    file_path.write_bytes(b"")
    with pytest.raises(NotADirectoryError):
        NIfTIBatchReader().iter_studies(file_path)


def test_empty_directory_raises_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No valid NIfTI studies were found."):
        NIfTIBatchReader().load_studies(tmp_path)


def test_load_study_truncated_gzip_raises_value_error_with_cause(tmp_path: Path) -> None:
    path = _truncated_gz(tmp_path)
    with pytest.raises(ValueError) as exc_info:
        NIfTIReader().load_study(path)
    assert exc_info.value.__cause__ is not None


def test_batch_skips_truncated_gzip(tmp_path: Path) -> None:
    _truncated_gz(tmp_path)
    valid = tmp_path / "ok.nii.gz"
    nib.save(nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.int16), np.eye(4)), valid)

    studies = NIfTIBatchReader().load_studies(tmp_path)

    assert [s.series[0].files[0].name for s in studies] == [valid.name]
