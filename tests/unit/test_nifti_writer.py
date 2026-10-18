from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader
from mri_dataset_tool.infrastructure.nifti.writer import NIfTIWriter

AFFINE = np.array(
    [[2.0, 0, 0, -10], [0, 3.0, 0, 5], [0, 0, 4.0, 7], [0, 0, 0, 1]]
)


def _series() -> MRISeries:
    volume = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    return MRISeries(volume=volume, metadata={"affine": AFFINE})


@pytest.mark.parametrize("name", ["out.nii", "out.nii.gz"])
def test_round_trip_preserves_volume_and_geometry(tmp_path: Path, name: str) -> None:
    series = _series()
    path = NIfTIWriter().write(series, tmp_path / name)

    loaded = NIfTIReader().load_study(path).series[0]

    np.testing.assert_array_equal(loaded.volume, series.volume)
    np.testing.assert_allclose(loaded.metadata["affine"], AFFINE)
    np.testing.assert_allclose(loaded.metadata["voxel_size"], (2.0, 3.0, 4.0))
    assert loaded.metadata["orientation"] == ("R", "A", "S")
    assert loaded.metadata["qform_code"] == 1
    assert loaded.metadata["sform_code"] == 1


def test_rejects_other_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        NIfTIWriter().write(_series(), tmp_path / "out.mgz")


def test_series_without_volume_or_affine_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        NIfTIWriter().write(MRISeries(metadata={"affine": AFFINE}), tmp_path / "a.nii")
    with pytest.raises(ValueError):
        NIfTIWriter().write(MRISeries(volume=np.zeros((2, 2, 2))), tmp_path / "b.nii")


def test_existing_file_not_overwritten_unless_requested(tmp_path: Path) -> None:
    path = tmp_path / "out.nii.gz"
    path.write_bytes(b"keep")

    with pytest.raises(FileExistsError):
        NIfTIWriter().write(_series(), path)
    assert path.read_bytes() == b"keep"

    NIfTIWriter().write(_series(), path, overwrite=True)
    assert NIfTIReader().load_study(path).series[0].volume.shape == (2, 3, 4)


def test_missing_parent_directory_is_not_created(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        NIfTIWriter().write(_series(), tmp_path / "sub" / "out.nii")
    assert not (tmp_path / "sub").exists()


def test_failed_save_keeps_original_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "out.nii.gz"
    path.write_bytes(b"original")

    def failing_save(image: object, target: Path) -> None:
        Path(target).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr("nibabel.save", failing_save)
    with pytest.raises(OSError):
        NIfTIWriter().write(_series(), path, overwrite=True)

    assert path.read_bytes() == b"original"
    assert [p.name for p in tmp_path.iterdir()] == ["out.nii.gz"]


def test_failed_save_without_overwrite_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_save(image: object, target: Path) -> None:
        Path(target).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr("nibabel.save", failing_save)
    with pytest.raises(OSError):
        NIfTIWriter().write(_series(), tmp_path / "out.nii")

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "affine",
    [
        # oblique/rotated 30 degrees about z, with translation
        [[1.732, -1.0, 0, 3], [1.0, 1.732, 0, -4], [0, 0, 2.0, 5], [0, 0, 0, 1]],
        # negative determinant (flipped x)
        [[-2.0, 0, 0, 10], [0, 3.0, 0, 5], [0, 0, 4.0, 7], [0, 0, 0, 1]],
        # RAS with negative diagonals
        [[-1.0, 0, 0, 90], [0, -1.0, 0, 126], [0, 0, -1.0, 72], [0, 0, 0, 1]],
    ],
)
def test_round_trip_geometry(tmp_path: Path, affine: list) -> None:
    affine = np.array(affine, dtype=float)
    series = MRISeries(volume=np.ones((3, 4, 5), dtype=np.float32), metadata={"affine": affine})

    loaded = NIfTIReader().load_study(NIfTIWriter().write(series, tmp_path / "g.nii.gz")).series[0]

    np.testing.assert_allclose(loaded.metadata["affine"], affine, atol=1e-4)
    assert loaded.metadata["orientation"] == tuple(nib.aff2axcodes(affine))
    np.testing.assert_allclose(loaded.metadata["voxel_size"], np.linalg.norm(affine[:3, :3], axis=0), atol=1e-4)


def test_round_trip_4d_volume(tmp_path: Path) -> None:
    volume = np.arange(2 * 3 * 4 * 5, dtype=np.float32).reshape(2, 3, 4, 5)
    series = MRISeries(volume=volume, metadata={"affine": AFFINE})

    loaded = NIfTIReader().load_study(NIfTIWriter().write(series, tmp_path / "d.nii")).series[0]

    assert loaded.metadata["shape"] == (2, 3, 4, 5)
    np.testing.assert_array_equal(loaded.volume, volume)
    assert len(loaded.metadata["voxel_size"]) == 3


@pytest.mark.parametrize("dtype", [bool, object])
def test_unsupported_dtype_raises_generic_value_error(tmp_path: Path, dtype: type) -> None:
    series = MRISeries(volume=np.zeros((2, 2, 2), dtype=dtype), metadata={"affine": AFFINE})
    with pytest.raises(ValueError):
        NIfTIWriter().write(series, tmp_path / "x.nii")
    assert list(tmp_path.iterdir()) == []
