from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.processing.reorient import check_target, orientation_code, reorient

_THETA = np.deg2rad(20)

# name -> (affine, orientation code)
AFFINES = {
    "LPS": (np.diag([-1.0, -1.0, 1.0, 1.0]), "LPS"),
    "RPI": (np.array([[2.0, 0, 0, -3], [0, -1.5, 0, 4], [0, 0, -3.0, 5], [0, 0, 0, 1]]), "RPI"),
    "ASL": (np.array([[0, 0, -1.0, 7], [1.0, 0, 0, -2], [0, 2.0, 0, 1], [0, 0, 0, 1]]), "ASL"),
    "permuted": (np.array([[0, 0.5, 0, 1], [0, 0, -2.5, 0], [-1.25, 0, 0, 3], [0, 0, 0, 1]]), "IRP"),
}


def _volume(shape=(3, 4, 5), dtype=np.float64) -> np.ndarray:
    # distinct values identify each voxel after the axes move
    return np.random.default_rng(0).permutation(np.prod(shape)).reshape(shape).astype(dtype)


def _world_by_value(volume: np.ndarray, affine: np.ndarray) -> dict[float, tuple[float, ...]]:
    ijk = np.indices(volume.shape[:3]).reshape(3, -1)
    world = (affine @ np.vstack([ijk, np.ones(ijk.shape[1])]))[:3].T
    return {float(v): tuple(np.round(w, 9)) for v, w in zip(volume[..., 0].ravel() if volume.ndim == 4 else volume.ravel(), world)}


@pytest.mark.parametrize("name", AFFINES)
def test_reorients_to_ras_keeping_values_and_world_points(name: str) -> None:
    affine, code = AFFINES[name]
    volume = _volume()
    assert orientation_code(affine) == code

    result, new_affine = reorient(volume, affine)

    assert orientation_code(new_affine) == "RAS"
    np.testing.assert_array_equal(np.sort(result, axis=None), np.sort(volume, axis=None))
    assert _world_by_value(result, new_affine) == _world_by_value(volume, affine)
    np.testing.assert_allclose(sorted(np.linalg.norm(new_affine[:3, :3], axis=0)), sorted(np.linalg.norm(affine[:3, :3], axis=0)))


def test_4d_keeps_the_time_axis() -> None:
    affine = AFFINES["ASL"][0]
    volume = np.stack([_volume() + 1000 * t for t in range(3)], axis=-1)

    result, new_affine = reorient(volume, affine)

    assert result.shape[3] == 3
    for t in range(3):
        frame, frame_affine = reorient(volume[..., t], affine)
        np.testing.assert_array_equal(result[..., t], frame)
        np.testing.assert_array_equal(frame_affine, new_affine)
    assert _world_by_value(result, new_affine) == _world_by_value(volume, affine)


def test_already_in_target_returns_the_same_volume_and_twice_equals_once() -> None:
    volume = _volume()
    affine = np.diag([1.0, 2.0, 3.0, 1.0])

    same, same_affine = reorient(volume, affine)
    once, once_affine = reorient(volume, AFFINES["LPS"][0])
    twice, twice_affine = reorient(once, once_affine)

    np.testing.assert_array_equal(same, volume)
    np.testing.assert_array_equal(same_affine, affine)
    np.testing.assert_array_equal(twice, once)
    np.testing.assert_array_equal(twice_affine, once_affine)


def test_other_targets_are_reached() -> None:
    result, new_affine = reorient(_volume(), np.eye(4), "LPI")

    assert orientation_code(new_affine) == "LPI"
    assert _world_by_value(result, new_affine) == _world_by_value(_volume(), np.eye(4))


def test_oblique_affine_reaches_the_closest_orientation_and_keeps_residual_obliquity() -> None:
    rotation = np.array([[np.cos(_THETA), -np.sin(_THETA), 0], [np.sin(_THETA), np.cos(_THETA), 0], [0, 0, 1]])
    affine = np.eye(4)
    affine[:3, :3] = rotation @ np.diag([-1.0, -1.0, 1.0])  # oblique LPS
    volume = _volume()

    result, new_affine = reorient(volume, affine)

    assert orientation_code(new_affine) == "RAS"
    assert not np.allclose(new_affine[:3, :3], np.diag(np.diag(new_affine[:3, :3])))  # still oblique
    assert _world_by_value(result, new_affine) == _world_by_value(volume, affine)


@pytest.mark.parametrize("dtype", [np.int16, np.uint8, np.float32])
def test_dtype_is_kept(dtype) -> None:
    result, _ = reorient(_volume(dtype=dtype), AFFINES["RPI"][0])

    assert result.dtype == dtype


def test_lazy_proxy_gives_the_same_result_as_ndarray(tmp_path: Path) -> None:
    affine = AFFINES["ASL"][0]
    volume = np.stack([_volume(dtype=np.int16) + t for t in range(2)], axis=-1)
    path = tmp_path / "v.nii.gz"
    nib.save(nib.Nifti1Image(volume, affine), path)
    proxy = nib.load(path).dataobj
    assert isinstance(proxy, nib.arrayproxy.ArrayProxy)

    from_proxy, proxy_affine = reorient(proxy, affine)
    from_array, array_affine = reorient(volume, affine)

    np.testing.assert_array_equal(from_proxy, from_array)
    np.testing.assert_array_equal(proxy_affine, array_affine)
    assert from_proxy.dtype == np.int16


@pytest.mark.parametrize("target", ["RAX", "RRS", "ras", "RA", "RASI", 3, None, ["R", "A", "S"]])
def test_invalid_target_is_rejected_with_fixed_message(target) -> None:
    with pytest.raises(ValueError, match="^Invalid target orientation.$"):
        check_target(target)
    with pytest.raises(ValueError, match="^Invalid target orientation.$"):
        reorient(_volume(), np.eye(4), target)


@pytest.mark.parametrize("shape", [(3, 4), (2, 2, 2, 2, 2)])
def test_unsupported_dimensionality_is_rejected(shape) -> None:
    with pytest.raises(ValueError, match="^Unsupported volume dimensionality.$"):
        reorient(np.zeros(shape), np.eye(4))
