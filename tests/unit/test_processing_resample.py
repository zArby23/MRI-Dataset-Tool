import weakref
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.processing import resample as resample_module
from mri_dataset_tool.infrastructure.processing.reorient import orientation_code, reorient
from mri_dataset_tool.infrastructure.processing.resample import (
    MAX_OUTPUT_VOXELS,
    check_interpolation,
    check_max_output_voxels,
    check_spacing,
    resample,
)

_THETA = np.deg2rad(25)
_ROTATION = np.array([[np.cos(_THETA), -np.sin(_THETA), 0], [np.sin(_THETA), np.cos(_THETA), 0], [0, 0, 1]])


def _affine(linear: np.ndarray, origin=(1.0, -2.0, 3.0)) -> np.ndarray:
    affine = np.eye(4)
    affine[:3, :3] = linear
    affine[:3, 3] = origin
    return affine


AFFINES = {
    "ras": _affine(np.diag([2.0, 2.0, 2.0])),
    "lps_anisotropic": _affine(np.diag([-1.5, -1.0, 2.0])),
    "oblique": _affine(_ROTATION @ np.diag([2.0, 1.5, 1.0])),
}


def _ramp(world: np.ndarray) -> np.ndarray:
    return 0.5 * world[0] - 0.3 * world[1] + 0.2 * world[2]


def _world(affine: np.ndarray, shape) -> np.ndarray:
    ijk = np.indices(shape).reshape(3, -1)
    return (affine @ np.vstack([ijk, np.ones(ijk.shape[1])]))[:3]


def _ramp_volume(affine: np.ndarray, shape=(24, 28, 20)) -> np.ndarray:
    return _ramp(_world(affine, shape)).reshape(shape)


def _interior(affine: np.ndarray, shape, new_affine: np.ndarray, new_shape, margin: float) -> np.ndarray:
    index = (np.linalg.inv(affine) @ np.vstack([_world(new_affine, new_shape), np.ones(int(np.prod(new_shape)))]))[:3]
    upper = np.asarray(shape)[:, None] - 1 - margin
    return np.all((index >= margin) & (index <= upper), axis=0)


@pytest.mark.parametrize("name", AFFINES)
@pytest.mark.parametrize(("spacing", "margin"), [([1.0, 1.0, 1.0], 0.0), ([0.7, 1.2, 0.9], 0.0), ([3.0, 3.0, 3.0], 3.0)])
def test_linear_ramp_is_reproduced(name: str, spacing: list[float], margin: float) -> None:
    affine = AFFINES[name]
    volume = _ramp_volume(affine)

    result, new_affine = resample(volume, affine, spacing, "linear")

    inside = _interior(affine, volume.shape, new_affine, result.shape, margin)
    assert inside.sum() > 20
    expected = _ramp(_world(new_affine, result.shape))
    np.testing.assert_allclose(result.ravel()[inside], expected[inside], atol=1e-3)


@pytest.mark.parametrize("name", AFFINES)
@pytest.mark.parametrize("spacing", [[1.0, 1.0, 1.0], [2.5, 2.5, 2.5], [0.5, 0.8, 1.3]])
def test_marked_voxel_keeps_its_world_position(name: str, spacing: list[float]) -> None:
    affine = AFFINES[name]
    volume = np.zeros((15, 15, 15))
    volume[6, 8, 7] = 1.0
    marked = (affine @ [6, 8, 7, 1])[:3]

    result, new_affine = resample(volume, affine, spacing, "linear")

    weights = result.astype(float)
    com = (np.indices(result.shape).reshape(3, -1) @ weights.ravel()) / weights.sum()
    world = (new_affine @ np.append(com, 1.0))[:3]
    assert np.all(np.abs(world - marked) <= np.asarray(spacing) / 2)


def test_same_spacing_on_ras_grid_is_equivalent() -> None:
    affine = AFFINES["ras"]
    volume = np.random.default_rng(0).random((6, 7, 8))

    result, new_affine = resample(volume, affine, [2.0, 2.0, 2.0], "linear")

    np.testing.assert_allclose(result, volume, atol=1e-6)
    np.testing.assert_allclose(new_affine, affine)
    assert result.dtype == np.float32


def test_same_spacing_on_lps_grid_equals_reorientation() -> None:
    affine = AFFINES["lps_anisotropic"]
    volume = np.random.default_rng(1).random((6, 7, 8))

    result, new_affine = resample(volume, affine, [1.5, 1.0, 2.0], "cubic")
    expected, expected_affine = reorient(volume, affine)

    np.testing.assert_allclose(result, expected, atol=1e-5)
    np.testing.assert_allclose(new_affine, expected_affine)


@pytest.mark.parametrize(
    ("shape", "linear", "spacing", "expected"),
    [
        ((10, 10, 10), np.eye(3), [2.0, 2.0, 2.0], (5, 5, 5)),
        ((10, 10, 10), np.eye(3), [0.5, 0.5, 0.5], (20, 20, 20)),
        ((10, 10, 10), np.eye(3), [3.0, 3.0, 3.0], (4, 4, 4)),
        ((10, 20, 5), np.diag([1.0, 0.5, 2.0]), [1.0, 1.0, 1.0], (10, 10, 10)),
        ((3, 3, 3), np.diag([0.1, 0.1, 0.1]), [0.1, 0.1, 0.1], (3, 3, 3)),  # float error is not ceiled up
        ((10, 20, 5), np.array([[0, 0, 2.0], [-1.0, 0, 0], [0, 0.5, 0]]), [1.0, 1.0, 1.0], (10, 10, 10)),  # permuted
    ],
)
def test_physical_field_of_view_is_kept(shape, linear, spacing, expected) -> None:
    affine = _affine(linear)

    result, new_affine = resample(np.ones(shape), affine, spacing)

    assert result.shape == expected
    center = (affine @ np.append((np.asarray(shape) - 1) / 2, 1))[:3]
    np.testing.assert_allclose((new_affine @ np.append((np.asarray(expected) - 1) / 2, 1))[:3], center)
    np.testing.assert_allclose(np.diag(new_affine)[:3], spacing)
    np.testing.assert_allclose(result, 1.0, atol=1e-6)  # the edge padding covers the outer half voxel


def test_oblique_input_is_aligned_to_ras_axes() -> None:
    affine = _affine(_ROTATION @ np.diag([-1.0, -1.0, 1.0]))

    result, new_affine = resample(np.ones((8, 8, 8)), affine, [1.0, 1.0, 1.0])

    assert orientation_code(new_affine) == "RAS"
    np.testing.assert_array_equal(new_affine[:3, :3], np.eye(3))
    assert result.min() == 0.0  # corners outside the rotated field of view


@pytest.mark.parametrize("name", AFFINES)
def test_nearest_keeps_the_set_of_values(name: str) -> None:
    volume = np.random.default_rng(2).integers(1, 50, (9, 10, 11)).astype(np.int16)

    result, _ = resample(volume, AFFINES[name], [0.8, 1.7, 1.1], "nearest")

    assert result.dtype == np.float32
    assert set(np.unique(result)) <= set(np.unique(volume).astype(np.float32)) | {0.0}


def test_4d_is_resampled_frame_by_frame_and_keeps_the_time_axis(monkeypatch: pytest.MonkeyPatch) -> None:
    affine = AFFINES["oblique"]
    volume = np.stack([_ramp_volume(affine) * (t + 1) for t in range(3)], axis=-1)
    refs: list[weakref.ref] = []
    real_iter = resample_module.iter_volumes_3d

    def track(frame: np.ndarray) -> np.ndarray:
        refs.append(weakref.ref(frame))
        return frame

    def tracking_iter(source, dtype=None):
        for frame in real_iter(source, dtype):
            assert all(ref() is None for ref in refs)  # the previous frame is already released
            yield track(frame.copy())
            del frame

    monkeypatch.setattr(resample_module, "iter_volumes_3d", tracking_iter)
    result, new_affine = resample(volume, affine, [1.0, 1.0, 1.0])
    monkeypatch.undo()

    assert len(refs) == 3 and result.shape[3] == 3
    for t in range(3):
        frame, frame_affine = resample(volume[..., t], affine, [1.0, 1.0, 1.0])
        np.testing.assert_array_equal(result[..., t], frame)
        np.testing.assert_array_equal(frame_affine, new_affine)


def test_lazy_proxy_gives_the_same_result_as_ndarray(tmp_path: Path) -> None:
    affine = AFFINES["lps_anisotropic"]
    volume = np.stack([np.arange(6 * 7 * 8, dtype=np.int16).reshape(6, 7, 8) + t for t in range(2)], axis=-1)
    path = tmp_path / "v.nii.gz"
    nib.save(nib.Nifti1Image(volume, affine), path)
    proxy = nib.load(path).dataobj
    assert isinstance(proxy, nib.arrayproxy.ArrayProxy)

    from_proxy, proxy_affine = resample(proxy, affine, [1.0, 1.0, 1.0])
    from_array, array_affine = resample(volume, affine, [1.0, 1.0, 1.0])

    np.testing.assert_array_equal(from_proxy, from_array)
    np.testing.assert_array_equal(proxy_affine, array_affine)


@pytest.mark.parametrize(
    "spacing",
    [[0, 1, 1], [-1.0, 1, 1], [float("nan"), 1, 1], [float("inf"), 1, 1], [1, 1], [1, 1, 1, 1], "1", 1.0, None, [True, 1, 1], ["1", 1, 1]],
)
def test_invalid_spacing_is_rejected_with_fixed_message(spacing) -> None:
    with pytest.raises(ValueError, match="^Spacing must be three finite positive numbers.$"):
        check_spacing(spacing)
    with pytest.raises(ValueError, match="^Spacing must be three finite positive numbers.$"):
        resample(np.zeros((2, 2, 2)), np.eye(4), spacing)


@pytest.mark.parametrize("interpolation", ["bspline", "Linear", None, 1])
def test_unknown_interpolation_is_rejected(interpolation) -> None:
    with pytest.raises(ValueError, match="^Unknown interpolation.$"):
        check_interpolation(interpolation)
    with pytest.raises(ValueError, match="^Unknown interpolation.$"):
        resample(np.zeros((2, 2, 2)), np.eye(4), [1, 1, 1], interpolation)


def test_output_larger_than_the_limit_is_rejected_before_allocating() -> None:
    assert MAX_OUTPUT_VOXELS == 2**32
    with pytest.raises(ValueError, match="^Resampled volume would be too large.$"):
        resample(np.zeros((100, 100, 100)), np.eye(4), [0.06, 0.06, 0.06])  # ~4.6e9 voxels
    with pytest.raises(ValueError, match="^Resampled volume would be too large.$"):
        resample(np.zeros((4, 4, 4, 2)), np.eye(4), [1, 1, 1], max_output_voxels=4 * 4 * 4 * 2 - 1)


class _PassedSizeCheck(Exception):
    pass


def test_real_4d_diffusion_size_passes_the_default_limit(monkeypatch) -> None:
    # QA1-07: 144x144x78x140 at 1.8 mm resampled to 1 mm gives 260x260x141x140 ~ 1.33e9 voxels > 2**28.
    # Stop right after the size check so CI never allocates the output.
    def stop(volume, dtype):
        raise _PassedSizeCheck

    monkeypatch.setattr(resample_module, "iter_volumes_3d", stop)
    volume = np.broadcast_to(np.float32(0), (144, 144, 78, 140))  # no memory behind it
    affine = np.diag([1.8, 1.8, 1.8, 1.0])
    with pytest.raises(_PassedSizeCheck):
        resample(volume, affine, [1, 1, 1])
    with pytest.raises(ValueError, match="^Resampled volume would be too large.$"):
        resample(volume, affine, [1, 1, 1], max_output_voxels=2**28)
    assert resample_module.target_grid(volume.shape, affine, [1, 1, 1])[0] == (260, 260, 141)


def test_limit_equal_to_the_output_size_is_accepted() -> None:
    out, _ = resample(np.ones((4, 4, 4, 2)), np.eye(4), [1, 1, 1], max_output_voxels=4 * 4 * 4 * 2)
    assert out.shape == (4, 4, 4, 2)


@pytest.mark.parametrize("limit", [0, -1, 1.5, 2.0**32, True, "4294967296", None])
def test_invalid_max_output_voxels_is_rejected_with_fixed_message(limit) -> None:
    with pytest.raises(ValueError, match="^Max output voxels must be a positive integer.$"):
        check_max_output_voxels(limit)
    with pytest.raises(ValueError, match="^Max output voxels must be a positive integer.$"):
        resample(np.zeros((2, 2, 2)), np.eye(4), [1, 1, 1], max_output_voxels=limit)


@pytest.mark.parametrize("shape", [(3, 4), (2, 2, 2, 2, 2)])
def test_unsupported_dimensionality_is_rejected(shape) -> None:
    with pytest.raises(ValueError, match="^Unsupported volume dimensionality.$"):
        resample(np.zeros(shape), np.eye(4), [1, 1, 1])
