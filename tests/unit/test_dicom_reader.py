from pathlib import Path

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from mri_dataset_tool.infrastructure.dicom.reader import DICOMReader


def _write_dicom_instance(
    path: Path,
    study_uid: str,
    series_uid: str,
) -> None:
    """Create the minimum metadata required by DICOMReader for one instance."""
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    dataset = FileDataset(path, {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.StudyInstanceUID = study_uid
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


def test_load_study_groups_dicom_instances_and_extracts_series_metadata(
    tmp_path: Path,
) -> None:
    study_uid = generate_uid()
    series_uid = generate_uid()
    first_instance = tmp_path / "instance-0001.dcm"
    second_instance = tmp_path / "instance-0002.dcm"
    _write_dicom_instance(first_instance, study_uid, series_uid)
    _write_dicom_instance(second_instance, study_uid, series_uid)

    study = DICOMReader().load_study(tmp_path)

    assert study.study_uid == study_uid
    assert len(study.series) == 1
    series = study.series[0]
    assert series.series_uid == series_uid
    assert series.modality == "MR"
    assert set(series.files) == {first_instance, second_instance}
    assert series.volume is None
    assert series.metadata == {
        "rows": 64,
        "columns": 32,
        "pixel_spacing": [0.8, 0.8],
        "slice_thickness": 1.2,
        "spacing_between_slices": 1.5,
        "image_orientation": [1, 0, 0, 0, 1, 0],
    }
