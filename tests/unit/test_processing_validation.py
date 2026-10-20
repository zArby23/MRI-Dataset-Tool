from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.processing.validation import (
    CONSTANT_VOLUME,
    SINGLE_VOLUME_4D,
    validate_series,
)


def _series(volume, affine=None, **metadata) -> MRISeries:
    affine = np.eye(4) if affine is None else affine
    base = {"shape": tuple(volume.shape), "voxel_size": (1.0, 1.0, 1.0), "affine": affine}
    return MRISeries(volume=volume, metadata={**base, **metadata})


def _ramp(shape=(3, 4, 5)) -> np.ndarray:
    return np.arange(np.prod(shape), dtype=np.float32).reshape(shape)


def _lazy(tmp_path: Path, data: np.ndarray) -> MRISeries:
    path = tmp_path / "vol.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), path)
    return _series(nib.load(path, mmap=False).dataobj)


def test_valid_volume_has_no_findings() -> None:
    assert validate_series(_series(_ramp())) == {"findings": [], "volumes_checked": 1}


def test_valid_4d_volume_is_checked_volume_by_volume() -> None:
    assert validate_series(_series(_ramp((2, 3, 4, 3)))) == {"findings": [], "volumes_checked": 3}


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_non_finite_values_are_rejected(value) -> None:
    volume = _ramp()
    volume[1, 2, 3] = value
    with pytest.raises(ValueError, match=r"^Volume contains non-finite values\.$"):
        validate_series(_series(volume))


def test_non_finite_value_in_a_later_4d_volume_is_rejected() -> None:
    volume = _ramp((2, 2, 2, 3))
    volume[0, 0, 0, 2] = np.nan
    with pytest.raises(ValueError, match=r"^Volume contains non-finite values\.$"):
        validate_series(_series(volume))


def test_empty_volume_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"^Volume is empty\.$"):
        validate_series(_series(np.zeros((0, 4, 5))))


def test_incoherent_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"^Series shape does not match its volume\.$"):
        validate_series(_series(_ramp(), shape=(9, 9, 9)))


@pytest.mark.parametrize(
    "affine",
    [np.zeros((4, 4)), np.diag([1.0, 1.0, np.nan, 1.0]), np.diag([1.0, 0.0, 1.0, 1.0]), np.eye(3)],
)
def test_degenerate_or_non_finite_affine_is_rejected(affine) -> None:
    with pytest.raises(ValueError, match=r"^Affine must"):
        validate_series(_series(_ramp(), affine=affine))


@pytest.mark.parametrize("voxel_size", [(1.0, 0.0, 1.0), (1.0, -1.0, 1.0), (1.0, np.nan, 1.0), (1.0, 1.0), None, "x"])
def test_null_or_non_finite_voxel_size_is_rejected(voxel_size) -> None:
    with pytest.raises(ValueError, match=r"^Voxel size must be three positive finite numbers\.$"):
        validate_series(_series(_ramp(), voxel_size=voxel_size))


def test_unsupported_dimensionality_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"^Unsupported volume dimensionality\.$"):
        validate_series(_series(np.ones((2, 2))))


def test_constant_volume_is_a_finding_not_an_error() -> None:
    assert validate_series(_series(np.full((2, 3, 4), 7.0)))["findings"] == [CONSTANT_VOLUME]


def test_constant_check_spans_all_4d_volumes() -> None:
    volume = np.zeros((2, 2, 2, 2))
    volume[..., 1] = 1.0  # each volume is constant, the whole series is not
    assert validate_series(_series(volume))["findings"] == []


def test_4d_with_single_volume_is_a_finding() -> None:
    result = validate_series(_series(_ramp((2, 3, 4, 1))))
    assert result == {"findings": [SINGLE_VOLUME_4D], "volumes_checked": 1}


def test_lazy_volume_gives_same_result_as_ndarray(tmp_path: Path) -> None:
    data = np.arange(2 * 3 * 4 * 2, dtype=np.int16).reshape(2, 3, 4, 2)
    assert validate_series(_lazy(tmp_path, data)) == validate_series(_series(data))


def test_lazy_float_volume_with_nan_is_rejected(tmp_path: Path) -> None:
    data = _ramp()
    data[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match=r"^Volume contains non-finite values\.$"):
        validate_series(_lazy(tmp_path, data))


class _IntegerOnDisk:
    """VolumeLike whose on-disk dtype is integer: the NaN/Inf check must be skipped."""

    dtype = np.dtype(np.int16)

    def __init__(self, data: np.ndarray) -> None:
        self._data = data
        self.shape = data.shape

    def __array__(self, dtype=None, copy=None):
        return np.asarray(self._data, dtype=dtype)

    def __getitem__(self, key):
        return self._data[key]


def test_integer_on_disk_dtype_skips_finite_check() -> None:
    data = _ramp().astype(np.float64)
    data[0, 0, 0] = np.nan  # impossible in a real integer file; proves the check is skipped
    assert validate_series(_series(_IntegerOnDisk(data)))["volumes_checked"] == 1


def test_truncated_lazy_volume_fails_with_fixed_message(tmp_path: Path) -> None:
    path = tmp_path / "vol.nii.gz"
    nib.save(nib.Nifti1Image(np.arange(4096, dtype=np.int16).reshape(16, 16, 16), np.eye(4)), path)
    series = _series(nib.load(path, mmap=False).dataobj)
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(ValueError, match=r"^Unable to read volume data\.$"):
        validate_series(series)


def test_messages_contain_no_values() -> None:
    volume = _ramp()
    volume[0, 0, 0] = np.nan
    with pytest.raises(ValueError) as info:
        validate_series(_series(volume, voxel_size=(123.456, 1.0, 1.0)))
    assert "123" not in str(info.value)
