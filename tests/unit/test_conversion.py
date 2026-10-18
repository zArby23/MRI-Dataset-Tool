from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from mri_dataset_tool.application.services.conversion import (
    convert_dicom_to_nifti,
    convert_nifti_to_dicom,
)
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.dicom.volume_builder import build_series_volume
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader

ROWS, COLS = 4, 3


def _write_slice(path: Path, series_uid: str, z: float, value: int, study_uid: str) -> None:
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(path, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "MR"
    ds.Rows, ds.Columns = ROWS, COLS
    ds.PixelSpacing = [0.5, 0.25]
    ds.SliceThickness = 2.0
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [10.0, 20.0, z]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.RescaleSlope, ds.RescaleIntercept = 1.0, 0.0
    ds.PixelData = np.full((ROWS, COLS), value, dtype=np.uint16).tobytes()
    ds.save_as(path, enforce_file_format=True)


def _make_input(root: Path, break_one: bool = False) -> Path:
    study = generate_uid()
    for name, base in (("s1", 10), ("s2", 50)):
        folder = root / name
        folder.mkdir(parents=True)
        uid = generate_uid()
        for k in range(3):
            z = float(2 * k)
            # One slice off the uniform spacing makes the builder reject that series.
            if break_one and name == "s2" and k == 2:
                z = 5.0
            _write_slice(folder / f"{k}.dcm", uid, z, base + k, study)
    return root


def test_two_series_become_two_niftis_with_builder_geometry(tmp_path: Path) -> None:
    src = _make_input(tmp_path / "in")
    out = tmp_path / "out"

    studies = convert_dicom_to_nifti(src, out)

    assert sorted(p.name for p in out.iterdir()) == [
        "study-001_series-001.nii.gz",
        "study-001_series-002.nii.gz",
    ]
    series = [s for st in studies for s in st.series]
    assert len(series) == 2
    for s in series:
        loaded = NIfTIReader().load_study(s.files[0]).series[0]
        np.testing.assert_allclose(loaded.metadata["affine"], s.metadata["affine"], atol=1e-4)
        assert loaded.metadata["shape"] == s.metadata["shape"] == (COLS, ROWS, 3)
        assert loaded.metadata["orientation"] == s.metadata["orientation"]
        assert s.volume is None
        assert s.metadata["provenance"]["target_format"] == "NIfTI"


def test_output_inside_input_raises_and_inputs_unchanged(tmp_path: Path) -> None:
    src = _make_input(tmp_path / "in")
    before = {p: p.read_bytes() for p in src.rglob("*.dcm")}

    with pytest.raises(ValueError):
        convert_dicom_to_nifti(src, src / "out")

    assert {p: p.read_bytes() for p in src.rglob("*.dcm")} == before
    assert not (src / "out").exists()


def test_broken_series_reported_once_and_other_converted(tmp_path: Path) -> None:
    src = _make_input(tmp_path / "in", break_one=True)
    calls: list[tuple[Path, Exception]] = []

    studies = convert_dicom_to_nifti(
        src, tmp_path / "out", on_error=lambda p, e: calls.append((p, e))
    )

    assert len(calls) == 1
    assert calls[0][0].parent.name == "s2"
    assert sum(len(s.series) for s in studies) == 1
    assert len(list((tmp_path / "out").iterdir())) == 1


def test_existing_output_is_not_overwritten(tmp_path: Path) -> None:
    src = _make_input(tmp_path / "in")
    out = tmp_path / "out"
    out.mkdir()
    (out / "study-001_series-001.nii.gz").write_bytes(b"keep")
    errors: list[Exception] = []

    studies = convert_dicom_to_nifti(src, out, on_error=lambda p, e: errors.append(e))

    assert (out / "study-001_series-001.nii.gz").read_bytes() == b"keep"
    assert len(errors) == 1 and isinstance(errors[0], FileExistsError)
    assert sum(len(s.series) for s in studies) == 1


def test_unexpected_builder_error_is_reported_and_others_convert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mri_dataset_tool.application.services import conversion

    src = _make_input(tmp_path / "in")
    real = conversion.build_series_volume

    def flaky(series):
        if series.files[0].parent.name == "s1":
            raise IndexError("boom")
        return real(series)

    monkeypatch.setattr(conversion, "build_series_volume", flaky)
    calls: list[Exception] = []

    studies = convert_dicom_to_nifti(src, tmp_path / "out", on_error=lambda p, e: calls.append(e))

    assert [type(e) for e in calls] == [IndexError]
    assert sum(len(s.series) for s in studies) == 1


def test_output_equal_to_input_raises(tmp_path: Path) -> None:
    src = _make_input(tmp_path / "in")
    with pytest.raises(ValueError):
        convert_dicom_to_nifti(src, src)


def test_failing_callback_continues_and_logs_no_uids_or_input_paths(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import pydicom

    src = _make_input(tmp_path / "in", break_one=True)
    uids = {
        str(pydicom.dcmread(p, stop_before_pixels=True)[tag].value)
        for p in src.rglob("*.dcm")
        for tag in ((0x0020, 0x000D), (0x0020, 0x000E))
    }

    def boom(path: Path, error: Exception) -> None:
        raise RuntimeError(str(path))

    with caplog.at_level("DEBUG"):
        studies = convert_dicom_to_nifti(src, tmp_path / "out", on_error=boom)

    assert sum(len(s.series) for s in studies) == 1
    assert "RuntimeError" in caplog.text
    assert str(src) not in caplog.text
    assert all(uid not in caplog.text for uid in uids)


_AFFINE = np.array([[2.0, 0, 0, -10], [0, 3.0, 0, 5], [0, 0, 4.0, 7], [0, 0, 0, 1]])


def _save_nifti(path: Path, shape: tuple = (3, 4, 5), affine: np.ndarray = _AFFINE) -> np.ndarray:
    data = np.arange(int(np.prod(shape)), dtype=np.int16).reshape(shape)
    nib.save(nib.Nifti1Image(data, affine), path)
    return data


def test_nifti_to_dicom_round_trip_volume_and_affine(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    data = _save_nifti(src / "a.nii.gz")

    studies = convert_nifti_to_dicom(src, tmp_path / "out")

    series = studies[0].series[0]
    assert series.volume is None
    assert series.metadata["provenance"]["target_format"] == "DICOM"
    assert len(series.files) == 5
    assert series.files[0].parent.name == "study-001"
    rebuilt = build_series_volume(MRISeries(files=series.files))
    np.testing.assert_array_equal(rebuilt.volume, data)
    np.testing.assert_allclose(rebuilt.metadata["affine"], _AFFINE, atol=1e-4)


def test_single_file_input(tmp_path: Path) -> None:
    _save_nifti(tmp_path / "a.nii")
    studies = convert_nifti_to_dicom(tmp_path / "a.nii", tmp_path / "out")
    assert len(studies) == 1 and (tmp_path / "out" / "study-001").is_dir()


def test_dicom_nifti_dicom_keeps_shape_and_orientation(tmp_path: Path) -> None:
    src = _make_input(tmp_path / "dcm")
    nii_dir = tmp_path / "nii"
    first = convert_dicom_to_nifti(src, nii_dir)[0].series[0]

    back = convert_nifti_to_dicom(nii_dir, tmp_path / "dcm2")[0].series[0]

    rebuilt = build_series_volume(MRISeries(files=back.files))
    assert rebuilt.metadata["shape"] == first.metadata["shape"]
    assert rebuilt.metadata["orientation"] == first.metadata["orientation"]


def test_nifti_to_dicom_rejects_output_inside_input(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    _save_nifti(src / "a.nii")
    with pytest.raises(ValueError):
        convert_nifti_to_dicom(src, src / "out")
    assert not (src / "out").exists()


def test_4d_and_unreadable_inputs_reported_and_batch_continues(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    _save_nifti(src / "a_ok.nii.gz")
    _save_nifti(src / "b_4d.nii.gz", shape=(3, 4, 5, 2))
    (src / "c_bad.nii.gz").write_bytes(b"garbage")
    _save_nifti(src / "d_ok.nii.gz")
    calls: list[tuple[Path, Exception]] = []

    studies = convert_nifti_to_dicom(src, tmp_path / "out", on_error=lambda p, e: calls.append((p, e)))

    assert sorted(p.name for p, _ in calls) == ["b_4d.nii.gz", "c_bad.nii.gz"]
    assert len(studies) == 2
    # unreadable and 4D inputs consume an index, so names are stable: a=1, b=2, c=3, d=4
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["study-001", "study-004"]


def test_single_bad_file_is_reported_then_value_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.nii"
    bad.write_bytes(b"garbage")
    calls: list[Path] = []
    with pytest.raises(ValueError, match="No valid NIfTI studies were found."):
        convert_nifti_to_dicom(bad, tmp_path / "out", on_error=lambda p, e: calls.append(p))
    assert calls == [bad]


def test_nifti_to_dicom_missing_input_raises(tmp_path: Path) -> None:
    for missing in (tmp_path / "nope.nii", tmp_path / "nope_dir"):
        with pytest.raises(FileNotFoundError):
            convert_nifti_to_dicom(missing, tmp_path / "out")


def test_nifti_to_dicom_output_equal_to_input_raises(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    _save_nifti(src / "a.nii")
    with pytest.raises(ValueError):
        convert_nifti_to_dicom(src, src)


def test_nifti_to_dicom_existing_output_reported_and_untouched(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    _save_nifti(src / "a.nii")
    _save_nifti(src / "b.nii")
    out = tmp_path / "out"
    (out / "study-001").mkdir(parents=True)
    keep = out / "study-001" / "keep.txt"
    keep.write_bytes(b"keep")
    calls: list[Exception] = []

    studies = convert_nifti_to_dicom(src, out, on_error=lambda p, e: calls.append(e))

    assert len(calls) == 1 and isinstance(calls[0], FileExistsError)
    assert len(studies) == 1
    assert [p.name for p in (out / "study-001").iterdir()] == ["keep.txt"]
    assert keep.read_bytes() == b"keep"


def test_nifti_to_dicom_failing_callback_logs_no_paths_or_uids(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    src = tmp_path / "in"
    src.mkdir()
    _save_nifti(src / "a_ok.nii")
    _save_nifti(src / "b_4d.nii", shape=(3, 4, 5, 2))
    (src / "c_bad.nii").write_bytes(b"garbage")

    def boom(path: Path, error: Exception) -> None:
        raise RuntimeError(str(path))

    with caplog.at_level("DEBUG"):
        studies = convert_nifti_to_dicom(src, tmp_path / "out", on_error=boom)

    uids = {
        str(pydicom.dcmread(p, stop_before_pixels=True)[tag].value)
        for st in studies
        for p in st.series[0].files
        for tag in ((0x0020, 0x000D), (0x0020, 0x000E))
    }
    assert len(studies) == 1 and uids
    assert "RuntimeError" in caplog.text
    assert str(src) not in caplog.text
    assert all(uid not in caplog.text for uid in uids)


def _rotation(axis: int, degrees: float) -> np.ndarray:
    c, s = np.cos(np.radians(degrees)), np.sin(np.radians(degrees))
    i, j = [k for k in range(3) if k != axis]
    rot = np.eye(3)
    rot[i, i], rot[i, j], rot[j, i], rot[j, j] = c, -s, s, c
    return rot


@pytest.mark.parametrize(
    "rotation",
    [_rotation(2, 10), _rotation(2, 10) @ _rotation(0, 15)],
    ids=["single_axis_10deg", "mixed_axes"],
)
def test_nifti_to_dicom_round_trip_with_rotated_affine(tmp_path: Path, rotation: np.ndarray) -> None:
    affine = np.eye(4)
    affine[:3, :3] = rotation @ np.diag([2.0, 3.0, 4.0])
    affine[:3, 3] = [-10, 5, 7]
    src = tmp_path / "in"
    src.mkdir()
    data = _save_nifti(src / "r.nii.gz", affine=affine)

    series = convert_nifti_to_dicom(src, tmp_path / "out")[0].series[0]

    rebuilt = build_series_volume(MRISeries(files=series.files))
    np.testing.assert_allclose(rebuilt.volume, data, atol=1e-4)
    np.testing.assert_allclose(rebuilt.metadata["affine"], affine, atol=1e-4)
