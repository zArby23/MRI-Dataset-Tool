from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.dicom.volume_builder import (
    build_series_volume,
    lps_to_ras,
    ras_to_lps,
)

ROWS, COLS = 4, 3


def _write_slice(path: Path, z: float, value: int, **overrides) -> Path:
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(path, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.Modality = "MR"
    ds.Rows, ds.Columns = ROWS, COLS
    ds.PixelSpacing = [0.5, 0.25]  # row spacing, column spacing
    ds.SliceThickness = 2.0
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [10.0, 20.0, z]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.RescaleSlope = 2.0
    ds.RescaleIntercept = -1.0
    for key, val in overrides.items():
        setattr(ds, key, val)
    ds.PixelData = np.full((ROWS, COLS), value, dtype=np.uint16).tobytes()
    ds.save_as(path, enforce_file_format=True)
    return path


def _series(files: list[Path]) -> MRISeries:
    return MRISeries(series_uid="s", modality="MR", files=files, metadata={"rows": ROWS})


def test_3d_volume_sorted_by_position_with_expected_ras_affine(tmp_path: Path) -> None:
    # Files named in an order unrelated to their position.
    zs = {"c.dcm": 4.0, "a.dcm": 6.0, "d.dcm": 0.0, "b.dcm": 2.0}
    files = [_write_slice(tmp_path / n, z, int(z)) for n, z in zs.items()]

    out = build_series_volume(_series(files))

    assert out.volume.shape == (COLS, ROWS, 4)
    assert [out.volume[0, 0, k] for k in range(4)] == [-1.0, 3.0, 7.0, 11.0]  # 2*z - 1
    expected = np.array(
        [[-0.25, 0, 0, -10], [0, -0.5, 0, -20], [0, 0, 2, 0], [0, 0, 0, 1]]
    )
    assert np.allclose(out.metadata["affine"], expected, atol=1e-4)
    assert out.metadata["shape"] == (COLS, ROWS, 4)
    assert out.metadata["voxel_size"] == (0.25, 0.5, 2.0)
    assert out.metadata["orientation"] == ("L", "P", "S")
    assert out.metadata["rows"] == ROWS  # existing keys preserved


def test_4d_volume_groups_by_acquisition_number(tmp_path: Path) -> None:
    files = [
        _write_slice(tmp_path / f"t{t}z{z}.dcm", float(z * 2), 10 * t + z, AcquisitionNumber=t)
        for t in (2, 1) for z in (1, 0)
    ]

    out = build_series_volume(_series(files))

    assert out.volume.shape == (COLS, ROWS, 2, 2)
    assert out.metadata["shape"] == (COLS, ROWS, 2, 2)
    # time index follows ascending AcquisitionNumber, slice index ascending position
    assert out.volume[0, 0, 1, 1] == 2 * 21 - 1


def test_single_slice_uses_slice_thickness(tmp_path: Path) -> None:
    out = build_series_volume(_series([_write_slice(tmp_path / "a.dcm", 0.0, 1)]))
    assert out.volume.shape == (COLS, ROWS, 1)
    assert out.metadata["voxel_size"][2] == 2.0


def test_lps_ras_helpers_are_inverse() -> None:
    affine = np.arange(16, dtype=float).reshape(4, 4)
    assert np.allclose(ras_to_lps(lps_to_ras(affine)), affine)


@pytest.mark.parametrize(
    "bad",
    [
        {"ImageOrientationPatient": [0, 1, 0, 1, 0, 0]},
        {"Rows": ROWS + 1},
        {"PixelSpacing": [1.0, 1.0]},
        {"NumberOfFrames": 3},
        {"ImageType": ["ORIGINAL", "MOSAIC"]},
    ],
)
def test_inconsistent_or_unsupported_slice_raises(tmp_path: Path, bad: dict) -> None:
    good = _write_slice(tmp_path / "a.dcm", 0.0, 1)
    other = _write_slice(tmp_path / "b.dcm", 2.0, 1, **bad)
    if "Rows" in bad:  # keep pixel buffer consistent with the declared size
        other_ds = pydicom.dcmread(other)
        other_ds.PixelData = np.zeros((ROWS + 1, COLS), dtype=np.uint16).tobytes()
        other_ds.save_as(other, enforce_file_format=True)
    with pytest.raises(ValueError):
        build_series_volume(_series([good, other]))


def test_missing_position_raises(tmp_path: Path) -> None:
    good = _write_slice(tmp_path / "a.dcm", 0.0, 1)
    other = _write_slice(tmp_path / "b.dcm", 2.0, 1)
    ds = pydicom.dcmread(other)
    del ds.ImagePositionPatient
    ds.save_as(other, enforce_file_format=True)
    with pytest.raises(ValueError):
        build_series_volume(_series([good, other]))


def test_non_uniform_spacing_raises_without_values(tmp_path: Path) -> None:
    files = [_write_slice(tmp_path / f"{i}.dcm", z, 1) for i, z in enumerate((0.0, 2.0, 7.0))]
    with pytest.raises(ValueError) as info:
        build_series_volume(_series(files))
    assert str(info.value) == "Slice spacing is not uniform or slices share a position."


def test_repeated_positions_without_time_key_raises(tmp_path: Path) -> None:
    files = [_write_slice(tmp_path / f"{i}.dcm", 0.0, 1) for i in range(2)]
    with pytest.raises(ValueError, match="share a position"):
        build_series_volume(_series(files))


def test_time_points_with_different_slice_counts_raise(tmp_path: Path) -> None:
    files = [
        _write_slice(tmp_path / "a.dcm", 0.0, 1, AcquisitionNumber=1),
        _write_slice(tmp_path / "b.dcm", 2.0, 1, AcquisitionNumber=1),
        _write_slice(tmp_path / "c.dcm", 0.0, 1, AcquisitionNumber=2),
    ]
    with pytest.raises(ValueError, match="Time points"):
        build_series_volume(_series(files))


def test_time_points_with_different_positions_raise(tmp_path: Path) -> None:
    files = [
        _write_slice(tmp_path / "a.dcm", 0.0, 1, AcquisitionNumber=1),
        _write_slice(tmp_path / "b.dcm", 2.0, 1, AcquisitionNumber=2),
    ]
    with pytest.raises(ValueError, match="Time points"):
        build_series_volume(_series(files))


def test_non_dicom_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.dcm"
    bad.write_bytes(b"not dicom")
    with pytest.raises(ValueError, match="could not be read"):
        build_series_volume(_series([bad]))


def test_truncated_pixel_data_raises(tmp_path: Path) -> None:
    path = _write_slice(tmp_path / "a.dcm", 0.0, 1)
    ds = pydicom.dcmread(path)
    ds.PixelData = ds.PixelData[:-2]
    ds.save_as(path, enforce_file_format=True)
    with pytest.raises(ValueError, match="could not be decoded"):
        build_series_volume(_series([path]))


def test_rgb_raises(tmp_path: Path) -> None:
    path = _write_slice(tmp_path / "a.dcm", 0.0, 1, SamplesPerPixel=3)
    with pytest.raises(ValueError, match="Multi-sample"):
        build_series_volume(_series([path]))


def test_in_plane_shift_raises(tmp_path: Path) -> None:
    a = _write_slice(tmp_path / "a.dcm", 0.0, 1)
    b = _write_slice(tmp_path / "b.dcm", 2.0, 1, ImagePositionPatient=[15.0, 20.0, 2.0])
    with pytest.raises(ValueError, match="gantry tilt"):
        build_series_volume(_series([a, b]))
