"""scripts/memory_check_nifti_batch.py: directory argument and a console without paths."""

import importlib.util
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("memory_check_nifti_batch", REPO / "scripts" / "memory_check_nifti_batch.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def _batch(root: Path) -> Path:
    batch = root / "batch"
    batch.mkdir()
    for subject in ("01", "02"):
        nib.save(nib.Nifti1Image(np.ones((4, 4, 4), np.float32), np.eye(4)), batch / f"sub-{subject}_T1w.nii.gz")
    return batch


@pytest.mark.parametrize("lazy", [[], ["--lazy"]])
def test_directory_argument_prints_only_counts_and_rss(lazy: list[str], tmp_path: Path, capsys) -> None:
    batch = _batch(tmp_path)

    assert script.main([str(batch), *lazy]) == 0

    out = capsys.readouterr().out
    assert f"Lazy loading: {bool(lazy)}" in out and "files processed: 2" in out
    assert "sub-" not in out and str(tmp_path) not in out and tmp_path.as_posix() not in out


def test_missing_directory_prints_a_fixed_message(tmp_path: Path, capsys) -> None:
    assert script.main([str(tmp_path / "sub-99")]) == 2
    assert capsys.readouterr().out == "NIfTI batch directory not found.\n"


def test_default_is_the_repository_test_batch() -> None:
    assert script.DEFAULT_BATCH_DIR == REPO / "data" / "raw" / "nifti_test_studies"


def test_reader_failure_prints_only_the_type(monkeypatch, tmp_path: Path, capsys) -> None:
    batch = _batch(tmp_path)

    def fail(*args, **kwargs):
        raise OSError(f"cannot read {batch / 'sub-01_T1w.nii.gz'}")

    monkeypatch.setattr(script.NIfTIBatchReader, "iter_studies", fail)

    assert script.main([str(batch)]) == 1
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "Run failed: OSError" and "sub-" not in out and str(tmp_path) not in out
