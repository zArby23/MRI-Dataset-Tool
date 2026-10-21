"""QA1 (1): PHI sweep. Recognizable synthetic identifiers are planted where existing tests do not
put them (NIfTI header fields and extensions, BIDS names and sidecars, DICOM file meta, preamble,
other transfer syntaxes, UN VRs) and searched for in every output: files and their names, the
decompressed NIfTI, the manifest, the summary, DICOM written from the result and DEBUG logs.

Documented residual risks (docs/anonymization/policy.md §6) are not asserted absent: values of
allowed BIDS entities (``acq-<label>``) and of allowed free-text technical keys (``SequenceName``).
"""

import gzip
import json
import logging
from dataclasses import replace
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset
from pydicom.tag import Tag
from pydicom.uid import DeflatedExplicitVRLittleEndian, ExplicitVRLittleEndian, ImplicitVRLittleEndian

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config
from mri_dataset_tool.application.services.anonymize import anonymize_dicom_tree
from mri_dataset_tool.application.services.conversion import convert_dicom_to_nifti, convert_nifti_to_dicom
from mri_dataset_tool.application.services.summary import summarize_study
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.nifti.writer import NIfTIWriter
from mri_dataset_tool.infrastructure.processing.arrays import load_array

KEY = "qa-anonymization-key-0123456789abcdef"
SUBJECT, SESSION = "DOEJOHN", "19700512"
PLANTED = [SUBJECT, SESSION, "Doe^John", "PAT12345", "GeneralHosp", "2024-01-15", "20240115", "SECRETAE"]
STUDY_UID = "1.2.826.0.1.3680043.8.498.777"
FULL_PIPELINE = {
    "pipeline": {
        "steps": [
            {"name": "validate"},
            {"name": "anonymize"},
            {"name": "reorient"},
            {"name": "resample", "params": {"spacing": [1.5, 1.5, 1.5]}},
            {"name": "normalize"},
        ]
    }
}


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV_VAR, KEY)


def _leaks(text: str, planted: list[str] = PLANTED) -> list[str]:
    return [token for token in planted if token in text]


def _write_bids(root: Path) -> Path:
    anat = root / f"sub-{SUBJECT}" / f"ses-{SESSION}" / "anat"
    anat.mkdir(parents=True)
    (root / "dataset_description.json").write_text(json.dumps({"Name": "qa", "BIDSVersion": "1.8.0"}))
    data = (np.arange(6 * 5 * 4).reshape(6, 5, 4) % 7 + 1).astype(np.int16)
    image = nib.Nifti1Image(data, np.diag([2.0, 2.0, 3.0, 1.0]))
    image.header["descrip"] = b"Doe^John PAT12345"
    image.header["aux_file"] = b"PAT12345"
    image.header["db_name"] = b"GeneralHosp"
    image.header.set_intent(0, name="DoeJohn")
    image.header.extensions.append(nib.nifti1.Nifti1Extension(6, b"PATIENT Doe^John 19700512"))
    stem = f"sub-{SUBJECT}_ses-{SESSION}_acq-qa_run-1_T1w"
    nib.save(image, anat / f"{stem}.nii.gz")
    sidecar = {
        "PatientName": "Doe^John",
        "InstitutionName": "GeneralHosp",
        "AcquisitionDateTime": "2024-01-15T10:32:15",
        "RepetitionTime": 2.3,
    }
    (anat / f"{stem}.json").write_text(json.dumps(sidecar))
    return root


def test_input_really_carries_the_planted_values(tmp_path: Path) -> None:
    root = _write_bids(tmp_path / "ds")
    image = next(root.rglob("*.nii.gz"))
    text = gzip.decompress(image.read_bytes()).decode("latin-1") + str(image)
    text += next(root.rglob("*_T1w.json")).read_text()
    assert set(_leaks(text)) >= {SUBJECT, SESSION, "Doe^John", "PAT12345", "GeneralHosp", "2024-01-15"}


@pytest.mark.parametrize("lazy", [False, True])
def test_bids_full_pipeline_outputs_carry_no_planted_value(
    tmp_path: Path, lazy: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    root = _write_bids(tmp_path / "ds")
    out = tmp_path / "out"
    out.mkdir()
    pipeline = pipeline_from_config(FULL_PIPELINE)
    results, errors = [], []
    reports = pipeline.run(
        BIDSBatchReader().iter_studies(root, on_error=lambda p, e: errors.append(e), lazy=lazy),
        on_result=lambda study, report: results.append(study),
        on_error=lambda p, e: errors.append(e),
    )
    assert errors == [] and len(results) == 1
    study = results[0]
    series = study.series[0]

    written = NIfTIWriter().write(
        replace(series, volume=load_array(series.volume, np.float32)), out / "study-001.nii.gz"
    )
    convert_nifti_to_dicom(written, out / "dicom")
    texts = {
        "manifest": RunManifest.from_run(FULL_PIPELINE, pipeline, reports).to_json(),
        "summary": json.dumps(summarize_study(study)),
        "nifti": gzip.decompress(written.read_bytes()).decode("latin-1"),
        "names": " ".join(str(p.relative_to(tmp_path / "out")) for p in out.rglob("*")),
        "study": repr((study.study_uid, study.subject_id, study.session_id, series.series_uid, series.files)),
        "metadata": repr(series.metadata),
        "logs": caplog.text,
    }
    texts.update({p.name: p.read_bytes().decode("latin-1") for p in (out / "dicom").rglob("*.dcm")})
    assert {name: _leaks(text) for name, text in texts.items() if _leaks(text)} == {}


def _dicom(path: Path, syntax: str, index: int, **values) -> None:
    meta = Dataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    meta.MediaStorageSOPInstanceUID = f"{STUDY_UID}.1.{index}"
    meta.TransferSyntaxUID = syntax
    meta.SourceApplicationEntityTitle = "SECRETAE"
    meta.PrivateInformationCreatorUID = "1.2.3"
    meta.PrivateInformation = b"Doe^John"
    ds = FileDataset(path, {}, file_meta=meta, preamble=b"Doe^John".ljust(128, b"\0"))
    ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = STUDY_UID, f"{STUDY_UID}.1"
    ds.PatientName, ds.PatientID, ds.PatientBirthDate = "Doe^John", "PAT12345", "19700512"
    ds.StudyDate, ds.InstitutionName, ds.Modality = "20240115", "GeneralHosp", "MR"
    ds.Rows = ds.Columns = 2
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit, ds.PixelRepresentation, ds.SamplesPerPixel = 15, 0, 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.ImageOrientationPatient, ds.PixelSpacing = [1, 0, 0, 0, 1, 0], [1, 1]
    ds.ImagePositionPatient = [0, 0, index]
    ds.PixelData = np.arange(4, dtype=np.uint16).tobytes()
    for name, value in values.items():
        setattr(ds, name, value)
    ds.save_as(path, enforce_file_format=True)


def _write_hostile_dicom_tree(source: Path) -> None:
    source.mkdir()
    _dicom(source / "explicit.dcm", ExplicitVRLittleEndian, 0)
    _dicom(source / "implicit.dcm", ImplicitVRLittleEndian, 1)
    _dicom(source / "deflated.dcm", DeflatedExplicitVRLittleEndian, 2)
    _dicom(source / "unvr.dcm", ExplicitVRLittleEndian, 3)
    ds = pydicom.dcmread(source / "unvr.dcm")  # identifiers stored with an unknown VR (UN)
    for tag, value in ((0x00080020, b"20240115"), (0x00100010, b"Doe^John"), (0x00100030, b"19700512")):
        ds[Tag(tag)] = pydicom.DataElement(Tag(tag), "UN", value)
    ds.save_as(source / "unvr.dcm")


def test_dicom_tree_variants_carry_no_planted_value(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    source = tmp_path / "in"
    _write_hostile_dicom_tree(source)
    assert all(b"Doe^John" in p.read_bytes() or p.name == "deflated.dcm" for p in source.iterdir())
    caplog.clear()

    errors = []
    report = anonymize_dicom_tree(source, tmp_path / "anon", on_error=lambda p, e: errors.append(e))
    assert (report.files_written, report.files_failed, errors) == (4, 0, [])
    planted = [*PLANTED, STUDY_UID]
    for path in (tmp_path / "anon").rglob("*"):
        assert _leaks(str(path.relative_to(tmp_path)), planted) == []
        if path.is_file():
            raw = path.read_bytes()
            if path.suffix == ".dcm":
                dataset = pydicom.dcmread(path)
                raw += repr(dataset).encode() + repr(dataset.file_meta).encode()
                assert dataset.preamble == b"\0" * 128
            assert _leaks(raw.decode("latin-1"), planted) == [], path.name
    assert _leaks(caplog.text, planted) == []


def test_dicom_to_nifti_output_and_logs_carry_no_planted_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    source = tmp_path / "in"
    source.mkdir()
    for index in range(3):
        _dicom(source / f"{index}.dcm", ExplicitVRLittleEndian, index)
    studies = convert_dicom_to_nifti(source, tmp_path / "nifti")
    assert len(studies) == 1
    (output,) = (tmp_path / "nifti").glob("*.nii.gz")
    assert _leaks(gzip.decompress(output.read_bytes()).decode("latin-1") + output.name, [*PLANTED, STUDY_UID]) == []
    assert _leaks(caplog.text, [*PLANTED, STUDY_UID]) == []
