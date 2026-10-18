from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import FileDataset
import pytest

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.dicom.reader import DICOMReader
from mri_dataset_tool.infrastructure.dicom.volume_builder import build_series_volume
from mri_dataset_tool.infrastructure.dicom.writer import DICOMWriter

AFFINE = np.array(
    [[-0.25, 0, 0, -10], [0, -0.5, 0, -20], [0, 0, 2, 5], [0, 0, 0, 1]], dtype=float
)


def _series(volume: np.ndarray | None = None, affine: np.ndarray | None = AFFINE) -> MRISeries:
    if volume is None:
        volume = np.random.default_rng(0).uniform(-50, 900, size=(4, 3, 5))
    metadata = {} if affine is None else {"affine": affine}
    return MRISeries(volume=volume, metadata=metadata)


def test_round_trip_through_reader_and_builder(tmp_path: Path) -> None:
    series = _series()
    paths = DICOMWriter().write(series, tmp_path / "out")

    assert len(paths) == 5
    study = DICOMReader().load_study(tmp_path / "out")
    assert len(study.series) == 1

    rebuilt = build_series_volume(study.series[0])
    slope = float(pydicom.dcmread(paths[0]).RescaleSlope)
    assert rebuilt.volume.shape == series.volume.shape
    assert np.abs(rebuilt.volume - series.volume).max() <= slope / 2 + 1e-6
    assert np.allclose(rebuilt.metadata["affine"], AFFINE, atol=1e-4)


def test_left_handed_affine_round_trips_as_equivalent_flipped_volume(tmp_path: Path) -> None:
    affine = AFFINE.copy()
    affine[:3, 2] *= -1  # slice axis points against cross(row, column)
    series = _series(affine=affine)
    DICOMWriter().write(series, tmp_path)

    rebuilt = build_series_volume(DICOMReader().load_study(tmp_path).series[0])
    slope = float(pydicom.dcmread(tmp_path / "slice-0001.dcm").RescaleSlope)
    assert np.abs(rebuilt.volume - series.volume[:, :, ::-1]).max() <= slope / 2 + 1e-6


def test_files_carry_no_identifiers_and_fixed_sop_attributes(tmp_path: Path) -> None:
    paths = DICOMWriter().write(_series(), tmp_path)
    ds = pydicom.dcmread(paths[0])
    for name in ("PatientName", "PatientID", "PatientBirthDate", "StudyDate"):
        assert str(ds[name].value) == ""
    assert ds.SOPClassUID == "1.2.840.10008.5.1.4.1.1.4"
    assert ds.Modality == "MR"
    assert list(ds.ImageType) == ["DERIVED", "SECONDARY"]


def test_uids_are_shared_per_series_and_unique_per_slice(tmp_path: Path) -> None:
    datasets = [pydicom.dcmread(p) for p in DICOMWriter().write(_series(), tmp_path)]
    assert len({d.SeriesInstanceUID for d in datasets}) == 1
    assert len({d.SOPInstanceUID for d in datasets}) == len(datasets)


def test_non_empty_directory_is_refused_unless_overwrite(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x")
    with pytest.raises(FileExistsError):
        DICOMWriter().write(_series(), tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["keep.txt"]

    DICOMWriter().write(_series(), tmp_path, overwrite=True)
    assert (tmp_path / "keep.txt").exists()


@pytest.mark.parametrize(
    "series",
    [
        MRISeries(volume=None, metadata={"affine": AFFINE}),
        MRISeries(volume=np.zeros((2, 2, 2)), metadata={}),
        MRISeries(volume=np.zeros((2, 2, 2, 2)), metadata={"affine": AFFINE}),
        MRISeries(volume=np.full((2, 2, 2), np.nan), metadata={"affine": AFFINE}),
        MRISeries(volume=np.zeros((2, 2, 2)), metadata={"affine": np.diag([1, 1, 0, 1.0])}),
        MRISeries(
            volume=np.zeros((2, 2, 2)),
            metadata={"affine": np.array([[1, 1, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1.0]])},
        ),
    ],
)
def test_invalid_series_raises_and_writes_nothing(tmp_path: Path, series: MRISeries) -> None:
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        DICOMWriter().write(series, out)
    assert not out.exists()


def test_constant_volume_round_trips(tmp_path: Path) -> None:
    series = _series(volume=np.full((4, 3, 2), 7.0))
    DICOMWriter().write(series, tmp_path)
    rebuilt = build_series_volume(DICOMReader().load_study(tmp_path).series[0])
    assert np.allclose(rebuilt.volume, 7.0, atol=1e-3)


def _roundtrip_error(tmp_path: Path, volume: np.ndarray) -> tuple[float, float]:
    DICOMWriter().write(_series(volume=volume), tmp_path)
    rebuilt = build_series_volume(DICOMReader().load_study(tmp_path).series[0])
    slope = float(pydicom.dcmread(tmp_path / "slice-0001.dcm").RescaleSlope)
    return float(np.abs(rebuilt.volume - volume).max()), slope


def test_large_signed_range_error_within_half_slope(tmp_path: Path) -> None:
    volume = np.random.default_rng(1).uniform(-1e4, 1e4, size=(4, 3, 5))
    error, slope = _roundtrip_error(tmp_path, volume)
    assert error <= slope / 2 + 1e-6


def test_small_non_integer_floats(tmp_path: Path) -> None:
    volume = np.random.default_rng(2).uniform(0, 0.01, size=(4, 3, 2))
    error, slope = _roundtrip_error(tmp_path, volume)
    assert error <= slope / 2 + 1e-9


def test_single_slice(tmp_path: Path) -> None:
    error, slope = _roundtrip_error(tmp_path, np.random.default_rng(3).uniform(0, 5, (4, 3, 1)))
    assert error <= slope / 2 + 1e-6


def test_integer_volume_is_lossless(tmp_path: Path) -> None:
    volume = np.random.default_rng(4).integers(-300, 3000, size=(4, 3, 2)).astype(float)
    error, slope = _roundtrip_error(tmp_path, volume)
    assert (error, slope) == (0.0, 1.0)


def test_zero_formatted_slope_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mri_dataset_tool.infrastructure.dicom.writer.format_number_as_ds", lambda v: "0"
    )
    with pytest.raises(ValueError):
        DICOMWriter().write(_series(), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_slightly_tilted_affine_is_rejected_by_writer(tmp_path: Path) -> None:
    affine = AFFINE.copy()
    affine[0, 2] = 2 * 5e-4  # slice axis tilted by 5e-4 rad
    with pytest.raises(ValueError, match="orthogonal"):
        DICOMWriter().write(_series(affine=affine), tmp_path / "out")


def test_failure_mid_write_leaves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original, calls = FileDataset.save_as, []

    def failing(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise OSError("disk full")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileDataset, "save_as", failing)
    with pytest.raises(OSError):
        DICOMWriter().write(_series(), tmp_path / "out")
    assert list(tmp_path.iterdir()) == []


def _volume(slices: int) -> np.ndarray:
    return np.arange(12 * slices, dtype=float).reshape(4, 3, slices)


def test_overwrite_longer_previous_series_raises_and_keeps_files(tmp_path: Path) -> None:
    DICOMWriter().write(_series(volume=_volume(5)), tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        DICOMWriter().write(_series(volume=_volume(3)), tmp_path, overwrite=True)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("old,new", [(3, 3), (3, 5)])
def test_overwrite_same_or_longer_series(tmp_path: Path, old: int, new: int) -> None:
    DICOMWriter().write(_series(volume=_volume(old)), tmp_path)
    paths = DICOMWriter().write(_series(volume=_volume(new)), tmp_path, overwrite=True)
    assert len(paths) == new == len(list(tmp_path.glob("slice-*.dcm")))
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def _long_series(tilt: float) -> MRISeries:
    affine = AFFINE.copy()
    affine[0, 2] = 2 * tilt
    return _series(volume=np.zeros((2, 2, 200)), affine=affine)


def test_tilt_below_cosine_tolerance_but_above_drift_is_rejected_by_writer(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tilted"):
        DICOMWriter().write(_long_series(5e-5), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_orthogonal_200_slices_round_trip(tmp_path: Path) -> None:
    DICOMWriter().write(_long_series(0.0), tmp_path)
    rebuilt = build_series_volume(DICOMReader().load_study(tmp_path).series[0])
    assert rebuilt.volume.shape == (2, 2, 200)
    assert np.allclose(rebuilt.metadata["affine"], AFFINE, atol=1e-4)
