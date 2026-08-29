from pathlib import Path

import pytest
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from mri_dataset_tool.infrastructure.dicom import _study_assembler
from mri_dataset_tool.infrastructure.dicom.batch_reader import DICOMBatchReader
from mri_dataset_tool.infrastructure.dicom.reader import DICOMReader


def _write_dicom_instance(
    path: Path,
    study_uid: str | None,
    series_uid: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    dataset = FileDataset(path, {}, file_meta=file_meta, preamble=b"\0" * 128)
    if study_uid is not None:
        dataset.StudyInstanceUID = study_uid
    if series_uid is not None:
        dataset.SeriesInstanceUID = series_uid
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.Modality = "MR"
    dataset.Rows = 64
    dataset.Columns = 32
    dataset.PixelSpacing = [0.8, 0.8]
    dataset.SliceThickness = 1.2
    dataset.SpacingBetweenSlices = 1.5
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.save_as(path, enforce_file_format=True)


def test_load_studies_groups_nested_files_deterministically_and_skips_failures(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first_study_uid = "1.2.3"
    second_study_uid = "1.2.4"
    first_series_uid = "1.2.3.1"
    second_series_uid = "1.2.3.2"
    second_study_series_uid = "1.2.4.1"

    nested = tmp_path / "deep" / "nested"
    _write_dicom_instance(nested / "z.dcm", first_study_uid, second_series_uid)
    _write_dicom_instance(nested / "a.dcm", first_study_uid, second_series_uid)
    _write_dicom_instance(tmp_path / "first.dcm", first_study_uid, first_series_uid)
    _write_dicom_instance(
        tmp_path / "another" / "study.dcm",
        second_study_uid,
        second_study_series_uid,
    )
    _write_dicom_instance(tmp_path / "missing-study.dcm", None, first_series_uid)
    _write_dicom_instance(tmp_path / "missing-series.dcm", first_study_uid, None)
    private_file = tmp_path / "patient-name-private.bin"
    private_file.write_text("not a DICOM file")

    studies = DICOMBatchReader().load_studies(tmp_path)

    assert [study.study_uid for study in studies] == [
        first_study_uid,
        second_study_uid,
    ]
    first_study = studies[0]
    assert [series.series_uid for series in first_study.series] == [
        first_series_uid,
        second_series_uid,
    ]
    second_series = first_study.series[1]
    assert second_series.files == [nested / "a.dcm", nested / "z.dcm"]
    assert second_series.volume is None
    assert second_series.metadata == {
        "rows": 64,
        "columns": 32,
        "pixel_spacing": [0.8, 0.8],
        "slice_thickness": 1.2,
        "spacing_between_slices": 1.5,
        "image_orientation": [1, 0, 0, 0, 1, 0],
    }
    assert "patient-name-private.bin" not in caplog.text


def test_readers_request_only_the_required_header_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_uid = generate_uid()
    series_uid = generate_uid()
    path = tmp_path / "instance.dcm"
    _write_dicom_instance(path, study_uid, series_uid)
    original_dcmread = _study_assembler.pydicom.dcmread
    calls: list[dict[str, object]] = []

    def spy_dcmread(*args: object, **kwargs: object) -> FileDataset:
        calls.append(kwargs)
        return original_dcmread(*args, **kwargs)

    monkeypatch.setattr(_study_assembler.pydicom, "dcmread", spy_dcmread)

    DICOMReader().load_study(tmp_path)
    DICOMBatchReader().load_studies(tmp_path)

    assert len(calls) == 2
    for kwargs in calls:
        assert kwargs["stop_before_pixels"] is True
        assert kwargs["specific_tags"] == _study_assembler.DICOM_HEADER_TAGS


def test_batch_reader_validates_paths_and_requires_a_valid_study(
    tmp_path: Path,
) -> None:
    reader = DICOMBatchReader()
    missing_path = tmp_path / "missing"
    non_directory = tmp_path / "input.dcm"
    non_directory.touch()
    empty_directory = tmp_path / "empty"
    empty_directory.mkdir()

    with pytest.raises(FileNotFoundError):
        reader.load_studies(missing_path)
    with pytest.raises(NotADirectoryError):
        reader.load_studies(non_directory)
    with pytest.raises(ValueError, match="No valid DICOM studies"):
        reader.load_studies(empty_directory)