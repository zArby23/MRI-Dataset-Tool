"""A2: anonymize_dicom_tree over synthetic, realistic DICOM, with a recursive audit of the output.

The fixture tests first check that the input really carries every identifier the audit must
not find in the output.
"""

import json
import logging
import re
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset
from pydicom.sequence import Sequence
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian

from mri_dataset_tool.application.services.anonymize import REPORT_NAME, anonymize_dicom_tree
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.anonymization.dicom import generalize_age, generalize_date, generalize_datetime
from mri_dataset_tool.infrastructure.anonymization.policy import DICOM_ACTIONS, POLICY_VERSION, Action
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR
from mri_dataset_tool.infrastructure.anonymization.report import AnonymizationReport, tag_label
from mri_dataset_tool.infrastructure.dicom.volume_builder import build_series_volume

KEY = "test-anonymization-key-0123456789abcdef"
OTHER_KEY = "other-anonymization-key-0123456789abcdef"
# Written by pydicom itself when saving with enforce_file_format=True (its own values).
PYDICOM_FILE_META = {
    "FileMetaInformationGroupLength", "FileMetaInformationVersion", "ImplementationClassUID", "ImplementationVersionName",
}
OUTPUT_NAME = re.compile(r"study-[0-9a-f]{16}/series-[0-9a-f]{16}/[0-9a-f]{16}\.dcm")

ROWS, COLS = 4, 3
MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"
STUDY_UID = "1.2.826.0.1.3680043.8.498.10001"
SERIES_UID = "1.2.826.0.1.3680043.8.498.10001.1"
FRAME_UID = "1.2.826.0.1.3680043.8.498.10001.9"
REFERENCED_UID = "1.2.826.0.1.3680043.8.498.20002.5"

# Values that must not survive anonymization at any level (original SOP instance UIDs are added
# per file by sop_uid). Dates avoid MMDD = 0101 so that the generalized YYYY0101 cannot match.
PLANTED = [
    STUDY_UID, SERIES_UID, FRAME_UID, REFERENCED_UID,
    "Doe^John", "PAT12345", "OTHER-777", "19700512", "20240115", "20240115103215", "103215",
    "1 Main St, Springfield", "ACC-998877", "STUDY-42", "Smith^Anna", "Brown^Bob", "Op^Carl",
    "General Hospital", "Radiology Wing", "MRI-STATION-3", "SN-4471", "Brain John tumour",
    "JD_protocol_v2", "John Doe follow-up", "REQ-5566", "PRIV-SECRET-ID", "PRIV-NESTED-PAT",
]


def sop_uid(index: int) -> str:
    return f"1.2.826.0.1.3680043.8.498.10001.1.{index + 1}"


def write_synthetic_series(directory: Path, n_slices: int = 3, **overrides) -> list[Path]:
    """Write one realistic MR series: full patient/study headers, staff, institution, free text,
    a private block and nested sequences carrying identifiers. Returns the files written."""
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    for index in range(n_slices):
        path = directory / f"IMG{index:04d}.dcm"
        file_meta = Dataset()
        file_meta.MediaStorageSOPClassUID = MR_IMAGE_STORAGE
        file_meta.MediaStorageSOPInstanceUID = sop_uid(index)
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(path, {}, file_meta=file_meta, preamble=b"\0" * 128)
        ds.SpecificCharacterSet = "ISO_IR 100"
        ds.SOPClassUID, ds.SOPInstanceUID = MR_IMAGE_STORAGE, sop_uid(index)
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = STUDY_UID, SERIES_UID, FRAME_UID
        # Patient.
        ds.PatientName, ds.PatientID, ds.OtherPatientIDs = "Doe^John", "PAT12345", "OTHER-777"
        ds.PatientBirthDate, ds.PatientSex, ds.PatientAge = "19700512", "M", "053Y"
        ds.PatientAddress, ds.PatientWeight, ds.PatientSize = "1 Main St, Springfield", "81.5", "1.78"
        # Study, series, staff and institution.
        ds.StudyDate = ds.SeriesDate = ds.AcquisitionDate = ds.ContentDate = "20240115"
        ds.StudyTime = ds.SeriesTime = ds.AcquisitionTime = ds.ContentTime = "103215"
        ds.AcquisitionDateTime = "20240115103215"
        ds.AccessionNumber, ds.StudyID = "ACC-998877", "STUDY-42"
        ds.ReferringPhysicianName, ds.PerformingPhysicianName, ds.OperatorsName = "Smith^Anna", "Brown^Bob", "Op^Carl"
        ds.InstitutionName, ds.InstitutionalDepartmentName = "General Hospital", "Radiology Wing"
        ds.StationName, ds.DeviceSerialNumber = "MRI-STATION-3", "SN-4471"
        # Free text.
        ds.StudyDescription = ds.SeriesDescription = "Brain John tumour"
        ds.ProtocolName, ds.ImageComments = "JD_protocol_v2", "John Doe follow-up"
        # Technical acquisition parameters (kept by the policy).
        ds.Modality, ds.ImageType = "MR", ["ORIGINAL", "PRIMARY", "M"]
        ds.Manufacturer, ds.ManufacturerModelName, ds.MagneticFieldStrength = "Siemens", "Prisma", "3"
        ds.ScanningSequence, ds.SequenceVariant, ds.MRAcquisitionType = "GR", "SP", "3D"
        ds.RepetitionTime, ds.EchoTime, ds.FlipAngle = "2300", "2.98", "9"
        ds.SeriesNumber, ds.InstanceNumber, ds.PatientPosition = 3, index + 1, "HFS"
        # Image geometry and pixels.
        ds.Rows, ds.Columns = ROWS, COLS
        ds.PixelSpacing, ds.SliceThickness = [0.5, 0.25], 2.0
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [10.0, 20.0, 2.0 * index]
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit, ds.PixelRepresentation = 15, 0
        ds.RescaleSlope, ds.RescaleIntercept = 2.0, -1.0
        # Nested sequences with identifiers, two levels deep.
        referenced = Dataset()
        referenced.ReferencedSOPClassUID, referenced.ReferencedSOPInstanceUID = MR_IMAGE_STORAGE, REFERENCED_UID
        ds.ReferencedImageSequence = Sequence([referenced])
        code = Dataset()
        code.CodeValue, code.CodeMeaning = "REQ-5566", "Brain John tumour"
        request = Dataset()
        request.RequestedProcedureID, request.ScheduledProcedureStepID = "REQ-5566", "REQ-5566"
        request.ReasonForRequestedProcedureCodeSequence = Sequence([code])
        ds.RequestAttributesSequence = Sequence([request])
        # Private block, including a private sequence.
        block = ds.private_block(0x0009, "ACME_PRIVATE", create=True)
        block.add_new(0x01, "LO", "PRIV-SECRET-ID")
        nested = Dataset()
        nested.PatientID = "PRIV-NESTED-PAT"
        block.add_new(0x02, "SQ", Sequence([nested]))
        for key, value in overrides.items():
            setattr(ds, key, value)
        ds.PixelData = np.full((ROWS, COLS), index + 1, dtype=np.uint16).tobytes()
        ds.save_as(path, enforce_file_format=True)
        files.append(path)
    return files


def dicom_strings(path: Path) -> list[str]:
    """Every text value of a file at every level (file meta, sequences, private elements)."""
    ds = pydicom.dcmread(path)
    elements = [*ds.file_meta.iterall(), *ds.iterall()]
    return [str(element.value) for element in elements if element.tag != Tag("PixelData") and element.VR != "SQ"]


def leaked(paths: list[Path], planted: list[str]) -> set[str]:
    texts = [text for path in paths for text in dicom_strings(path)]
    return {value for value in planted if any(value in text for text in texts)}


def test_synthetic_series_carries_every_planted_identifier(tmp_path):
    files = write_synthetic_series(tmp_path / "in")
    planted = PLANTED + [sop_uid(i) for i in range(len(files))]
    assert leaked(files, planted) == set(planted)


def test_synthetic_series_has_private_and_nested_elements(tmp_path):
    ds = pydicom.dcmread(write_synthetic_series(tmp_path / "in", n_slices=1)[0])
    assert any(element.tag.is_private for element in ds.iterall())
    request = ds.RequestAttributesSequence[0]
    assert request.ReasonForRequestedProcedureCodeSequence[0].CodeValue == "REQ-5566"


def test_synthetic_series_rebuilds_as_a_volume(tmp_path):
    files = write_synthetic_series(tmp_path / "in")
    built = build_series_volume(MRISeries(series_uid=SERIES_UID, modality="MR", files=files))
    assert built.volume.shape == (COLS, ROWS, 3)
    assert [built.volume[0, 0, k] for k in range(3)] == [1.0, 3.0, 5.0]  # 2 * value - 1


def test_report_counts_actions_per_tag_without_values():
    report = AnonymizationReport()
    report.record(Tag("PatientName"), Action.EMPTIED)
    report.record(Tag("PatientName"), Action.EMPTIED)
    report.record(Tag(0x0009, 0x1001), Action.REMOVED)
    report.files_written = 2
    data = json.loads(report.to_json())
    assert data == {
        "policy_version": POLICY_VERSION,
        "files_written": 2,
        "files_failed": 0,
        "actions": {"0009,1001": {"removed": 1}, "PatientName": {"emptied": 2}},
    }
    assert tag_label(Tag("StudyInstanceUID")) == "StudyInstanceUID"


# --- anonymize_dicom_tree ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(KEY_ENV_VAR, KEY)


def _planted(n_slices: int = 3) -> list[str]:
    return PLANTED + [sop_uid(i) for i in range(n_slices)]


def _run(input_dir: Path, output_dir: Path, errors: list | None = None) -> AnonymizationReport:
    errors = [] if errors is None else errors
    return anonymize_dicom_tree(input_dir, output_dir, lambda path, error: errors.append((path, error)))


def _outputs(output_dir: Path) -> list[Path]:
    return sorted(output_dir.rglob("*.dcm"))


def _anonymized(tmp_path: Path, n_slices: int = 3) -> tuple[list[Path], list[Path], AnonymizationReport]:
    inputs = write_synthetic_series(tmp_path / "in", n_slices)
    errors: list = []
    report = _run(tmp_path / "in", tmp_path / "out", errors)
    assert errors == []
    return inputs, _outputs(tmp_path / "out"), report


def test_no_planted_value_survives_at_any_level(tmp_path):
    _, outputs, report = _anonymized(tmp_path)
    assert len(outputs) == 3 and report.files_written == 3 and report.files_failed == 0
    assert leaked(outputs, _planted()) == set()
    names = [path.relative_to(tmp_path / "out").as_posix() for path in outputs]
    assert all(OUTPUT_NAME.fullmatch(name) for name in names)
    assert not [value for value in _planted() for name in names if value in name]


def test_no_planted_value_survives_in_the_raw_bytes_preamble_included(tmp_path):
    preamble_value = "Doe^John-PREAMBLE"
    preamble = preamble_value.encode("ascii").ljust(128, b"\0")
    inputs = write_synthetic_series(tmp_path / "in", preamble=preamble)
    assert all(path.read_bytes()[:128] == preamble for path in inputs)
    _run(tmp_path / "in", tmp_path / "out")
    outputs = _outputs(tmp_path / "out")
    assert len(outputs) == 3
    planted = [value.encode("latin-1") for value in [*_planted(), preamble_value]]
    assert not [value for value in planted for path in outputs if value in path.read_bytes()]
    assert all(path.read_bytes()[:128] == b"\0" * 128 for path in outputs)


def test_only_policy_elements_remain_at_every_level(tmp_path):
    _, outputs, _ = _anonymized(tmp_path)
    for path in outputs:
        ds = pydicom.dcmread(path)
        for element in [*ds.file_meta.iterall(), *ds.iterall()]:
            assert not element.tag.is_private and element.VR != "SQ"
            assert element.keyword in DICOM_ACTIONS or element.keyword in PYDICOM_FILE_META, element.keyword


def test_dates_age_sex_and_free_text_follow_the_policy(tmp_path):
    _, outputs, _ = _anonymized(tmp_path, n_slices=1)
    ds = pydicom.dcmread(outputs[0])
    assert ds.StudyDate == ds.SeriesDate == ds.AcquisitionDate == ds.ContentDate == "20240101"
    assert ds.AcquisitionDateTime == "2024"
    assert ds.PatientBirthDate == "" and ds.PatientName == "" and ds.StudyTime == ""
    assert ds.ReferringPhysicianName == "" and ds.AccessionNumber == "" and ds.StudyID == ""
    assert ds.PatientAge == "050Y" and ds.PatientSex == "M"
    assert re.fullmatch(r"[0-9a-f]{16}", ds.PatientID)
    assert ds.PatientIdentityRemoved == "YES" and POLICY_VERSION in ds.DeidentificationMethod
    for keyword in ("SeriesTime", "AcquisitionTime", "SeriesDescription", "StudyDescription", "ProtocolName",
                    "ImageComments", "InstitutionName", "OtherPatientIDs", "PatientAddress", "PatientWeight",
                    "ReferencedImageSequence", "RequestAttributesSequence"):
        assert keyword not in ds, keyword
    assert ds.RepetitionTime == 2300 and ds.Manufacturer == "Siemens"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("047Y", "040Y"), ("053Y", "050Y"), ("009Y", "000Y"), ("089Y", "080Y"), ("090Y", "090Y"),
     ("104Y", "090Y"), ("006M", "000Y"), ("030M", "000Y"), ("150M", "010Y"), ("030W", "000Y"),
     ("200D", "000Y"), ("47Y", ""), ("abcY", ""), ("", "")],
)
def test_generalize_age(value, expected):
    assert generalize_age(value) == expected


def test_generalize_dates():
    assert generalize_date("20240115") == "20240101"
    assert generalize_date("") == "" and generalize_date("2024") == "20240101" and generalize_date("ab") == ""
    assert generalize_datetime("20240115103215.000+0100") == "2024" and generalize_datetime("x") == ""


def test_series_stays_consistent_and_rebuilds_the_same_volume(tmp_path):
    inputs, outputs, _ = _anonymized(tmp_path)
    datasets = [pydicom.dcmread(path) for path in outputs]
    assert len({ds.StudyInstanceUID for ds in datasets}) == 1
    assert len({ds.SeriesInstanceUID for ds in datasets}) == 1
    assert len({ds.FrameOfReferenceUID for ds in datasets}) == 1
    assert len({ds.SOPInstanceUID for ds in datasets}) == 3
    assert all(ds.file_meta.MediaStorageSOPInstanceUID == ds.SOPInstanceUID for ds in datasets)
    assert datasets[0].StudyInstanceUID.startswith("2.25.") and datasets[0].StudyInstanceUID != STUDY_UID

    original = build_series_volume(MRISeries(series_uid=SERIES_UID, modality="MR", files=inputs))
    rebuilt = build_series_volume(MRISeries(series_uid=datasets[0].SeriesInstanceUID, modality="MR", files=outputs))
    np.testing.assert_array_equal(rebuilt.volume, original.volume)
    np.testing.assert_allclose(rebuilt.metadata["affine"], original.metadata["affine"])

    pixels = {ds.InstanceNumber: ds.PixelData for ds in (pydicom.dcmread(path) for path in inputs)}
    assert all(ds.PixelData == pixels[ds.InstanceNumber] for ds in datasets)


def test_same_key_gives_same_uids_and_names_other_key_does_not(tmp_path, monkeypatch):
    write_synthetic_series(tmp_path / "in")

    def run(name: str) -> tuple[list[str], list[str]]:
        _run(tmp_path / "in", tmp_path / name)
        outputs = _outputs(tmp_path / name)
        uids = [pydicom.dcmread(path).SOPInstanceUID for path in outputs]
        return [path.relative_to(tmp_path / name).as_posix() for path in outputs], uids

    first, second = run("out1"), run("out2")
    assert first == second
    monkeypatch.setenv(KEY_ENV_VAR, OTHER_KEY)
    other = run("out3")
    assert not set(other[0]) & set(first[0]) and not set(other[1]) & set(first[1])


def test_input_is_not_modified(tmp_path):
    inputs = write_synthetic_series(tmp_path / "in")
    before = {path: path.read_bytes() for path in inputs}
    _run(tmp_path / "in", tmp_path / "out")
    assert {path: path.read_bytes() for path in sorted((tmp_path / "in").rglob("*"))} == before


@pytest.mark.parametrize("relative", ["in", "in/out", "in/a/b"])
def test_output_inside_input_raises_before_reading_or_creating(tmp_path, monkeypatch, relative):
    write_synthetic_series(tmp_path / "in")
    monkeypatch.setattr(pydicom, "dcmread", lambda *a, **k: pytest.fail("read before the check"))
    with pytest.raises(ValueError, match=r"^Output directory must not be inside the input directory\.$"):
        anonymize_dicom_tree(tmp_path / "in", tmp_path / relative)
    assert sorted(p.name for p in (tmp_path / "in").iterdir()) == ["IMG0000.dcm", "IMG0001.dcm", "IMG0002.dcm"]


def test_missing_input_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        anonymize_dicom_tree(tmp_path / "missing", tmp_path / "out")
    (tmp_path / "file").write_text("x")
    with pytest.raises(NotADirectoryError):
        anonymize_dicom_tree(tmp_path / "file", tmp_path / "out")


def test_missing_key_raises_before_creating_anything(tmp_path, monkeypatch):
    write_synthetic_series(tmp_path / "in")
    monkeypatch.delenv(KEY_ENV_VAR)
    with pytest.raises(ValueError, match=r"^Anonymization key is not set or too short\.$"):
        anonymize_dicom_tree(tmp_path / "in", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_existing_report_raises_before_reading(tmp_path):
    write_synthetic_series(tmp_path / "in")
    _run(tmp_path / "in", tmp_path / "out")
    with pytest.raises(FileExistsError):
        _run(tmp_path / "in", tmp_path / "out")


def test_existing_output_is_reported_per_file_and_not_replaced(tmp_path):
    write_synthetic_series(tmp_path / "in")
    _run(tmp_path / "in", tmp_path / "out")
    (tmp_path / "out" / REPORT_NAME).unlink()
    written = {path: path.read_bytes() for path in _outputs(tmp_path / "out")}
    errors: list = []
    report = _run(tmp_path / "in", tmp_path / "out", errors)
    assert [type(error) for _, error in errors] == [FileExistsError] * 3
    assert report.files_written == 0 and report.files_failed == 3
    assert report.actions == {}  # counts only cover written files
    assert {path: path.read_bytes() for path in _outputs(tmp_path / "out")} == written
    assert not list((tmp_path / "out").rglob(".*.tmp"))


def test_bad_files_are_reported_and_the_batch_continues(tmp_path):
    inputs = write_synthetic_series(tmp_path / "in")
    (tmp_path / "in" / "README.txt").write_text("Doe^John study")
    (tmp_path / "in" / "empty.dcm").write_bytes(b"")
    no_uid = pydicom.dcmread(inputs[0])
    del no_uid.SOPInstanceUID
    no_uid.save_as(tmp_path / "in" / "no_uid.dcm")
    (tmp_path / "in" / ".git").mkdir()
    (tmp_path / "in" / ".git" / "config").write_text("hidden")
    errors: list = []
    report = _run(tmp_path / "in", tmp_path / "out", errors)
    assert sorted(path.name for path, _ in errors) == ["README.txt", "empty.dcm", "no_uid.dcm"]
    assert report.files_written == 3 and report.files_failed == 3
    assert len(_outputs(tmp_path / "out")) == 3
    assert not [value for value in _planted() for _, error in errors if value in str(error)]


def test_raising_callback_is_caught_and_only_its_type_logged(tmp_path, caplog):
    write_synthetic_series(tmp_path / "in")
    (tmp_path / "in" / "README.txt").write_text("not dicom")

    def explode(path, error):
        raise RuntimeError("Doe^John")

    with caplog.at_level(logging.WARNING):
        report = anonymize_dicom_tree(tmp_path / "in", tmp_path / "out", explode)
    assert report.files_written == 3
    assert "RuntimeError" in caplog.text and "Doe^John" not in caplog.text


def test_logs_hold_no_identifiers_paths_nor_key(tmp_path, caplog):
    write_synthetic_series(tmp_path / "in")
    (tmp_path / "in" / "README.txt").write_text("not dicom")
    with caplog.at_level(logging.DEBUG):
        _run(tmp_path / "in", tmp_path / "out")
    assert not [value for value in _planted() if value in caplog.text]
    assert KEY not in caplog.text and str(tmp_path) not in caplog.text


def test_report_is_saved_with_actions_and_counts_and_no_values(tmp_path):
    _, _, report = _anonymized(tmp_path)
    text = (tmp_path / "out" / REPORT_NAME).read_text(encoding="utf-8")
    assert text == report.to_json()
    data = json.loads(text)
    assert data["policy_version"] == POLICY_VERSION and data["files_written"] == 3
    actions = data["actions"]
    assert actions["PatientName"] == {"emptied": 3}
    assert actions["PatientID"] == {"replaced": 3}
    assert actions["StudyDate"] == {"generalized": 3}
    assert actions["PatientSex"] == {"kept": 3}
    assert actions["RequestAttributesSequence"] == {"removed": 3}
    assert actions["0009,1001"] == {"removed": 3}
    assert actions["PatientIdentityRemoved"] == {"replaced": 3}
    assert not [value for value in _planted() if value in text]
    assert KEY not in text and str(tmp_path) not in text and "2.25." not in text
