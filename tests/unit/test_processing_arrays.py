import gc
import weakref
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d, load_array


def _proxy(tmp_path: Path, data: np.ndarray, name: str = "vol.nii.gz", slope: float = 1.0):
    image = nib.Nifti1Image(data, np.eye(4))
    image.header.set_slope_inter(slope, 0.0)
    path = tmp_path / name
    nib.save(image, path)
    return nib.load(path, mmap=False).dataobj, path


class _CountingVolume:
    """Minimal VolumeLike that records every data access."""

    def __init__(self, data: np.ndarray) -> None:
        self._data = data
        self.shape = data.shape
        self.dtype = data.dtype
        self.reads: list[object] = []

    def __array__(self, dtype=None, copy=None):
        self.reads.append("all")
        return np.asarray(self._data, dtype=dtype)

    def __getitem__(self, key):
        self.reads.append(key)
        return self._data[key]


def test_load_array_returns_same_ndarray_without_copy() -> None:
    data = np.zeros((2, 3, 4), dtype=np.float32)
    assert load_array(data) is data
    assert load_array(data, np.float32) is data


def test_load_array_converts_dtype() -> None:
    data = np.arange(24, dtype=np.int16).reshape(2, 3, 4)
    result = load_array(data, np.float32)
    assert result.dtype == np.float32
    np.testing.assert_array_equal(result, data)


def test_load_array_proxy_matches_eager_get_fdata(tmp_path: Path) -> None:
    data = np.arange(60, dtype=np.int16).reshape(3, 4, 5)
    proxy, path = _proxy(tmp_path, data, slope=2.0)
    eager = nib.load(path).get_fdata()
    result = load_array(proxy, np.float64)
    assert result.dtype == np.float64
    np.testing.assert_array_equal(result, eager)
    np.testing.assert_array_equal(eager, data * 2.0)


def test_load_array_proxy_default_dtype_is_on_disk_dtype(tmp_path: Path) -> None:
    proxy, _ = _proxy(tmp_path, np.ones((2, 2, 2), dtype=np.int16))
    assert proxy.dtype == np.int16
    assert load_array(proxy).dtype == np.int16


def test_no_data_is_read_until_load_array() -> None:
    volume = _CountingVolume(np.ones((2, 2, 2)))
    assert volume.reads == []
    load_array(volume)
    assert volume.reads == ["all"]


@pytest.mark.parametrize("dtype", [bool, np.complex64, object, "not-a-dtype", np.str_])
def test_invalid_dtype_raises_fixed_value_error(dtype) -> None:
    with pytest.raises(ValueError, match=r"^Invalid volume dtype\.$"):
        load_array(np.zeros((2, 2, 2)), dtype)
    with pytest.raises(ValueError, match=r"^Invalid volume dtype\.$"):
        list(iter_volumes_3d(np.zeros((2, 2, 2)), dtype))


def test_truncated_proxy_raises_fixed_value_error_on_materialize(tmp_path: Path) -> None:
    proxy, path = _proxy(tmp_path, np.arange(4096, dtype=np.int16).reshape(16, 16, 16))
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(ValueError, match=r"^Unable to read volume data\.$") as info:
        load_array(proxy)
    assert str(path) not in str(info.value)


def test_truncated_4d_proxy_raises_fixed_value_error_while_iterating(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    proxy, path = _proxy(tmp_path, rng.integers(0, 1000, (16, 16, 16, 4), dtype=np.int16))
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(ValueError, match=r"^Unable to read volume data\.$"):
        list(iter_volumes_3d(proxy))


def test_iter_volumes_3d_yields_single_volume_for_3d() -> None:
    data = np.ones((2, 3, 4))
    volumes = list(iter_volumes_3d(data))
    assert len(volumes) == 1
    assert volumes[0] is data


def test_iter_volumes_3d_yields_each_4d_frame_lazily() -> None:
    data = np.arange(2 * 3 * 4 * 5, dtype=np.float32).reshape(2, 3, 4, 5)
    volume = _CountingVolume(data)
    frames = iter_volumes_3d(volume, np.float32)
    first = next(frames)
    np.testing.assert_array_equal(first, data[..., 0])
    assert volume.reads == [(Ellipsis, 0)]  # only the first frame was read
    rest = list(frames)
    assert len(rest) == 4
    np.testing.assert_array_equal(rest[-1], data[..., 4])
    assert "all" not in volume.reads


def test_iter_volumes_3d_proxy_matches_ndarray(tmp_path: Path) -> None:
    data = np.arange(3 * 4 * 5 * 2, dtype=np.int16).reshape(3, 4, 5, 2)
    proxy, _ = _proxy(tmp_path, data)
    for lazy, eager in zip(iter_volumes_3d(proxy, np.float32), iter_volumes_3d(data, np.float32), strict=True):
        assert lazy.dtype == np.float32
        assert lazy.shape == (3, 4, 5)
        np.testing.assert_array_equal(lazy, eager)


def test_iter_volumes_3d_does_not_retain_previous_frames() -> None:
    data = np.ones((2, 2, 2, 3))
    refs = []
    for frame in iter_volumes_3d(data, np.float32):  # float32 forces a new array per frame
        refs.append(weakref.ref(frame))
        del frame
        gc.collect()
        assert all(ref() is None for ref in refs)


@pytest.mark.parametrize("shape", [(4,), (2, 3), (1, 1, 1, 1, 2)])
def test_iter_volumes_3d_rejects_unsupported_dimensionality(shape) -> None:
    with pytest.raises(ValueError, match=r"^Unsupported volume dimensionality\.$"):
        list(iter_volumes_3d(np.zeros(shape)))


def test_proxy_keeps_no_file_open(tmp_path: Path) -> None:
    proxy, path = _proxy(tmp_path, np.ones((2, 2, 2), dtype=np.int16), name="vol.nii")
    load_array(proxy)
    path.unlink()  # fails on Windows if the file stayed open or memory-mapped
    assert not path.exists()
