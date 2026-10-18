from pathlib import Path

import numpy as np
import pytest
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from mri_dataset_tool.application.services.conversion import convert_dicom_to_nifti
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
