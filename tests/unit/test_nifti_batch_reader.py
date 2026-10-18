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


def _mixed_dir(tmp_path: Path) -> list[Path]:
    for name in ("a.nii.gz", "b.nii.gz"):
        nib.save(nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.int16), np.eye(4)), tmp_path / name)
    bad = [tmp_path / "bad1.nii.gz", tmp_path / "bad2.nii"]
    for path in bad:
        path.write_bytes(b"garbage")
    return bad


def test_on_error_called_once_per_broken_file(tmp_path: Path) -> None:
    bad = _mixed_dir(tmp_path)
    calls: list[tuple[Path, Exception]] = []

    studies = NIfTIBatchReader().load_studies(
        tmp_path, on_error=lambda p, e: calls.append((p, e))
    )

    assert len(studies) == 2
    assert sorted(p for p, _ in calls) == sorted(bad)
    assert all(isinstance(e, ValueError) for _, e in calls)


def test_failing_callback_does_not_stop_batch_or_leak_paths(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _mixed_dir(tmp_path)

    def boom(path: Path, error: Exception) -> None:
        raise RuntimeError(str(path))

    with caplog.at_level("WARNING"):
        studies = NIfTIBatchReader().load_studies(tmp_path, on_error=boom)

    assert len(studies) == 2
    assert "RuntimeError" in caplog.text
    assert "bad1" not in caplog.text


def _tiny_nifti(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.int16), np.eye(4)), path)


def test_hidden_directories_are_ignored_silently(tmp_path: Path) -> None:
    _tiny_nifti(tmp_path / "ok.nii.gz")
    for hidden in (".git", ".datalad"):
        (tmp_path / hidden / "objects").mkdir(parents=True)
        (tmp_path / hidden / "objects" / "SHA256E-s1--abc.nii.gz").write_bytes(b"annex")
    calls: list[Path] = []

    studies = NIfTIBatchReader().load_studies(tmp_path, on_error=lambda p, e: calls.append(p))

    assert [s.series[0].files[0].name for s in studies] == ["ok.nii.gz"]
    assert calls == []


def test_only_hidden_content_means_no_studies(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x.nii.gz").write_bytes(b"annex")
    calls: list[Path] = []
    with pytest.raises(ValueError, match="No valid NIfTI studies were found."):
        NIfTIBatchReader().load_studies(tmp_path, on_error=lambda p, e: calls.append(p))
    assert calls == []


def test_root_under_hidden_directory_still_loads(tmp_path: Path) -> None:
    root = tmp_path / ".hidden_root" / "data"
    _tiny_nifti(root / "sub" / "a.nii.gz")

    studies = NIfTIBatchReader().load_studies(root)

    assert len(studies) == 1
