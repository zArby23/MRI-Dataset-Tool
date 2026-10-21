from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.processing.normalize import check_params, normalize_volume


def _brain(shape=(6, 7, 8), seed=0) -> np.ndarray:
    """Positive values inside a box, zero background."""
    rng = np.random.default_rng(seed)
    volume = np.zeros(shape)
    volume[1:-1, 1:-1, 1:-1] = rng.uniform(10, 500, (shape[0] - 2, shape[1] - 2, shape[2] - 2))
    return volume


def _proxy(tmp_path: Path, data: np.ndarray):
    path = tmp_path / "vol.nii.gz"
    nib.save(nib.Nifti1Image(data.astype(np.float32), np.eye(4)), path)
    return nib.load(path, mmap=False).dataobj


def test_zscore_has_zero_mean_unit_std_inside_mask_and_zero_background() -> None:
    volume = _brain()
    result, stats = normalize_volume(volume)
    inside = volume != 0
    assert result.dtype == np.float32 and result.shape == volume.shape
    assert abs(result[inside].mean()) < 1e-5
    assert abs(result[inside].std() - 1) < 1e-5
    assert np.all(result[~inside] == 0)
    assert stats == {"mean": pytest.approx(volume[inside].mean()), "std": pytest.approx(volume[inside].std())}
    assert all(type(v) is float for v in stats.values())


def test_mask_none_uses_every_voxel() -> None:
    volume = _brain()
    result, _ = normalize_volume(volume, mask="none")
    assert abs(result.mean()) < 1e-5 and abs(result.std() - 1) < 1e-5


def test_minmax_maps_mask_to_unit_range() -> None:
    volume = _brain()
    result, stats = normalize_volume(volume, method="minmax")
    inside = volume != 0
    assert result[inside].min() == 0.0 and result[inside].max() == 1.0
    assert set(stats) == {"min", "max"}


def test_percentile_clips_and_rescales_with_extremes_at_0_and_1() -> None:
    volume = _brain()
    result, stats = normalize_volume(volume, method="percentile", percentiles=[5, 95])
    inside = volume != 0
    low, high = np.percentile(volume[inside], [5, 95])
    assert stats == {"low": pytest.approx(low), "high": pytest.approx(high)}
    assert result[inside].min() == 0.0 and result[inside].max() == 1.0
    assert np.all(result[inside][volume[inside] <= low] == 0.0)
    assert np.all(result[inside][volume[inside] >= high] == 1.0)


@pytest.mark.parametrize(
    ("method", "percentiles"), [("zscore", None), ("minmax", None), ("percentile", [2, 98])]
)
def test_invariant_to_scale_and_offset(method, percentiles) -> None:
    volume = _brain()
    base, _ = normalize_volume(volume, method=method, percentiles=percentiles)
    scaled, _ = normalize_volume(volume * 3.5, method=method, percentiles=percentiles)
    np.testing.assert_allclose(scaled, base, atol=1e-5)
    # offset moves the zero background, so the nonzero mask would change: use mask="none"
    base_all, _ = normalize_volume(volume, method=method, mask="none", percentiles=percentiles)
    shifted, _ = normalize_volume(volume * 2.0 + 100.0, method=method, mask="none", percentiles=percentiles)
    np.testing.assert_allclose(shifted, base_all, atol=1e-5)


@pytest.mark.parametrize("method", ["zscore", "minmax"])
def test_constant_volume_raises(method) -> None:
    with pytest.raises(ValueError, match=r"^Volume is constant within the normalization mask\.$"):
        normalize_volume(np.full((3, 3, 3), 4.0), method=method)


def test_constant_percentile_range_raises() -> None:
    volume = np.full((4, 4, 4), 2.0)
    volume[0, 0, 0] = 9.0
    with pytest.raises(ValueError, match=r"^Volume is constant within the normalization mask\.$"):
        normalize_volume(volume, method="percentile", percentiles=[10, 90])


def test_empty_mask_raises() -> None:
    with pytest.raises(ValueError, match=r"^Normalization mask is empty\.$"):
        normalize_volume(np.zeros((3, 3, 3)))


@pytest.mark.parametrize("value", [np.nan, np.inf])
def test_non_finite_values_raise_instead_of_propagating(value) -> None:
    volume = _brain()
    volume[2, 2, 2] = value
    with pytest.raises(ValueError, match=r"^Volume contains non-finite values\.$"):
        normalize_volume(volume)


def test_4d_per_volume_normalizes_each_volume_separately() -> None:
    volume = np.stack([_brain(seed=0), _brain(seed=1) * 10 + 5], axis=-1)
    result, stats = normalize_volume(volume)
    assert result.shape == volume.shape and result.dtype == np.float32
    assert len(stats["volumes"]) == 2
    for t in range(2):
        inside = volume[..., t] != 0
        assert abs(result[..., t][inside].mean()) < 1e-5
        assert abs(result[..., t][inside].std() - 1) < 1e-5


def test_4d_global_uses_one_set_of_statistics() -> None:
    volume = np.stack([_brain(seed=0), _brain(seed=1) * 10 + 5], axis=-1)
    inside = volume != 0
    result, stats = normalize_volume(volume, per_volume=False)
    assert stats == {"mean": pytest.approx(volume[inside].mean()), "std": pytest.approx(volume[inside].std())}
    assert abs(result[inside].mean()) < 1e-5 and abs(result[inside].std() - 1) < 1e-5
    assert abs(result[..., 0][inside[..., 0]].mean()) > 0.1  # not per volume


@pytest.mark.parametrize(("method", "percentiles"), [("minmax", None), ("percentile", [1, 99])])
def test_4d_global_limits_match_whole_volume(method, percentiles) -> None:
    volume = np.stack([_brain(seed=0), _brain(seed=1) * 2], axis=-1)
    _, stats = normalize_volume(volume, method=method, per_volume=False, percentiles=percentiles)
    values = volume[volume != 0]
    expected = (
        [values.min(), values.max()] if method == "minmax" else np.percentile(values.astype(np.float32), percentiles)
    )
    assert list(stats.values()) == pytest.approx(list(expected), rel=1e-6)


def test_4d_global_with_one_empty_volume_still_works_but_all_empty_raises() -> None:
    volume = np.stack([_brain(), np.zeros((6, 7, 8))], axis=-1)
    result, _ = normalize_volume(volume, per_volume=False)
    assert np.all(result[..., 1] == 0)
    with pytest.raises(ValueError, match=r"^Normalization mask is empty\.$"):
        normalize_volume(volume)  # per volume: the second one is empty
    with pytest.raises(ValueError, match=r"^Normalization mask is empty\.$"):
        normalize_volume(np.zeros((2, 2, 2, 2)), per_volume=False)


@pytest.mark.parametrize("per_volume", [True, False])
@pytest.mark.parametrize(("method", "percentiles"), [("zscore", None), ("minmax", None), ("percentile", [2, 98])])
def test_lazy_and_ndarray_give_same_result(tmp_path: Path, per_volume, method, percentiles) -> None:
    data = np.stack([_brain(seed=0), _brain(seed=1)], axis=-1).astype(np.float32)
    eager = normalize_volume(data, method, "nonzero", per_volume, percentiles)
    lazy = normalize_volume(_proxy(tmp_path, data), method, "nonzero", per_volume, percentiles)
    np.testing.assert_array_equal(lazy[0], eager[0])
    assert lazy[1] == eager[1]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"method": "robust"},
        {"mask": "otsu"},
        {"per_volume": 1},
        {"method": "zscore", "percentiles": [1, 99]},
        {"method": "percentile"},
        {"method": "percentile", "percentiles": [99, 1]},
        {"method": "percentile", "percentiles": [-1, 99]},
        {"method": "percentile", "percentiles": [1, 101]},
        {"method": "percentile", "percentiles": [1]},
        {"method": "percentile", "percentiles": "1,99"},
        {"method": "percentile", "percentiles": [True, 99]},
    ],
)
def test_invalid_params_raise_fixed_value_error(kwargs) -> None:
    params = {"method": "zscore", "mask": "nonzero", "per_volume": True, "percentiles": None, **kwargs}
    with pytest.raises(ValueError):
        check_params(**params)


def test_unsupported_dimensionality_raises() -> None:
    with pytest.raises(ValueError, match=r"^Unsupported volume dimensionality\.$"):
        normalize_volume(np.ones((3, 3)))
