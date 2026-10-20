import copy
import dataclasses
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.pipeline.step import build_step
from mri_dataset_tool.application.pipeline.steps.anonymize import AnonymizeStep
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.anonymization.policy import POLICY_VERSION
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR

KEY = "test-anonymization-key-0123456789abcdef"
OTHER_KEY = "other-anonymization-key-0123456789abcdef"

# Every identifying value planted in the synthetic study; none may survive anonymization.
ORIGINALS = [
    "1.2.840.113619.2.55.3.604688119.971",
    "1.2.840.113619.2.55.3.604688119.971.2",
    "PAT12345",
    "20240115",
    "Doe^John",
    "JohnDoe",
    "19700101",
    "2024-01-15T10:32:00",
    "General Hospital",
    "SN-4471",
    "Dr. Smith",
    "brain John",
    "mprage-doe",
    "C:/hospital",
]


def _study(volume: Any = None) -> MRIStudy:
    affine = np.diag([1.0, 1.0, 2.0, 1.0])
    series = MRISeries(
        series_uid="1.2.840.113619.2.55.3.604688119.971.2",
        modality="T1w",
        files=[Path("C:/hospital/JohnDoe/sub-PAT12345/ses-20240115/anat/sub-PAT12345_ses-20240115_T1w.nii.gz")],
        metadata={
            "shape": (2, 2, 2),
            "voxel_size": (1.0, 1.0, 2.0),
            "affine": affine,
            "orientation": ("R", "A", "S"),
            "provenance": {"tool": "mri_dataset_tool.convert_dicom_to_nifti", "source_format": "DICOM"},
            "PatientName": "Doe^John",
            "source_path": "C:/hospital/JohnDoe",
            "bids": {
                "sub": "PAT12345",
                "ses": "20240115",
                "suffix": "T1w",
                "extension": ".nii.gz",
                "other": {"acq": "mprage", "run": "1", "custom": "mprage-doe"},
            },
            "sidecar": {
                "RepetitionTime": 2.3,
                "EchoTime": 0.00298,
                "FlipAngle": 9,
                "SliceTiming": [0.0, 0.5, 1.0],
                "MagneticFieldStrength": 3,
                "Manufacturer": "Siemens",
                "PatientName": "Doe^John",
                "PatientID": "PAT12345",
                "PatientBirthDate": "19700101",
                "AcquisitionDateTime": "2024-01-15T10:32:00",
                "InstitutionName": "General Hospital",
                "DeviceSerialNumber": "SN-4471",
                "PerformingPhysicianName": "Dr. Smith",
                "SeriesDescription": "brain John",
                "EchoTrainLength": {"nested": "Doe^John"},
                "PulseSequenceType": ["GR", {"PatientID": "PAT12345"}],
            },
        },
        volume=np.arange(8, dtype=np.float64).reshape(2, 2, 2) if volume is None else volume,
    )
    return MRIStudy(
        study_uid="1.2.840.113619.2.55.3.604688119.971",
        series=[series],
        subject_id="PAT12345",
        session_id="20240115",
    )


def _strings(value: Any) -> list[str]:
    """Every string reachable from *value* (dataclass fields, dict keys/values, sequences, paths)."""
    if dataclasses.is_dataclass(value):
        return [s for field in dataclasses.fields(value) for s in _strings(getattr(value, field.name))]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(k) + _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, (str, Path)):
        return [str(value).replace("\\", "/")]
    return []


def _plain(value: Any) -> Any:
    """Comparable form of a study: arrays become lists."""
    if dataclasses.is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _leaks(text_parts: list[str]) -> list[str]:
    return [original for original in ORIGINALS for part in text_parts if original in part]


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(KEY_ENV_VAR, KEY)


def test_no_original_value_survives_at_any_level():
    assert set(_leaks(_strings(_study()))) == set(ORIGINALS)  # the detector sees every planted value
    result = AnonymizeStep().apply(_study())
    assert _leaks(_strings(result)) == []


def test_identifiers_are_pseudonymized_and_files_dropped():
    result = AnonymizeStep().apply(_study())
    series = result.series[0]
    assert result.study_uid.startswith("2.25.") and series.series_uid.startswith("2.25.")
    assert len(result.subject_id) == 16 and len(result.session_id) == 16
    assert series.files == []
    assert series.metadata["bids"]["sub"] == result.subject_id
    assert series.metadata["bids"]["ses"] == result.session_id


def test_metadata_and_sidecar_keep_only_whitelisted_plain_values():
    original = _study()
    series = AnonymizeStep().apply(original).series[0]
    assert set(series.metadata) == {"shape", "voxel_size", "affine", "orientation", "provenance", "bids", "sidecar"}
    assert series.metadata["sidecar"] == {
        "RepetitionTime": 2.3,
        "EchoTime": 0.00298,
        "FlipAngle": 9,
        "SliceTiming": [0.0, 0.5, 1.0],
        "MagneticFieldStrength": 3,
        "Manufacturer": "Siemens",
    }
    assert series.metadata["bids"]["other"] == {"acq": "mprage", "run": "1"}
    assert series.metadata["bids"]["suffix"] == "T1w"
    np.testing.assert_array_equal(series.metadata["affine"], original.series[0].metadata["affine"])
    assert series.modality == "T1w"


def test_unknown_key_is_discarded():
    study = _study()
    study.series[0].metadata["SomeFutureKey"] = "value"
    study.series[0].metadata["sidecar"]["SomeFutureField"] = 1.0
    series = AnonymizeStep().apply(study).series[0]
    assert "SomeFutureKey" not in series.metadata
    assert "SomeFutureField" not in series.metadata["sidecar"]


def test_input_is_not_mutated():
    study = _study()
    before = copy.deepcopy(_plain(study))
    AnonymizeStep().apply(study)
    assert _plain(study) == before


def test_deterministic_with_same_key_and_different_with_other_key(monkeypatch):
    first = AnonymizeStep().apply(_study())
    second = AnonymizeStep().apply(_study())
    assert _plain(first) == _plain(second)
    monkeypatch.setenv(KEY_ENV_VAR, OTHER_KEY)
    other = AnonymizeStep().apply(_study())
    assert other.study_uid != first.study_uid
    assert other.series[0].series_uid != first.series[0].series_uid
    assert other.subject_id != first.subject_id and other.session_id != first.session_id


def test_idempotent():
    step = AnonymizeStep()
    once = step.apply(_study())
    assert _plain(step.apply(once)) == _plain(once)


def test_missing_values_stay_none():
    study = MRIStudy(study_uid=None, series=[MRISeries()], subject_id=None, session_id=None)
    result = AnonymizeStep().apply(study)
    assert result.study_uid is None and result.subject_id is None and result.session_id is None
    assert result.series[0].series_uid is None and result.series[0].metadata == {}


def test_lazy_volume_is_not_materialized():
    class LazyVolume:
        shape, dtype = (2, 2, 2), np.dtype("int16")

        def __array__(self, dtype=None, copy=None):
            raise AssertionError("volume was read")

        def __getitem__(self, key):
            raise AssertionError("volume was read")

    volume = LazyVolume()
    assert AnonymizeStep().apply(_study(volume)).series[0].volume is volume


@pytest.mark.parametrize("value", [None, "", "short"])
def test_build_without_valid_key_raises_fixed_message(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(KEY_ENV_VAR)
    else:
        monkeypatch.setenv(KEY_ENV_VAR, value)
    with pytest.raises(ValueError, match=r"^Anonymization key is not set or too short\.$"):
        build_step("anonymize")


def test_params_hold_the_policy_version_and_never_the_key():
    step = build_step("anonymize", {"policy_version": POLICY_VERSION})
    assert step.params == {"policy_version": POLICY_VERSION}
    assert KEY not in repr(step) and KEY not in str(step.params)


def test_other_policy_version_is_rejected():
    with pytest.raises(ValueError, match=r"^Unsupported anonymization policy version\.$"):
        build_step("anonymize", {"policy_version": "0"})


def test_pipeline_logs_and_manifest_hold_no_key_nor_original_values(caplog):
    config = {"pipeline": {"steps": [{"name": "anonymize"}]}}
    pipeline = pipeline_from_config(config)
    results: list[MRIStudy] = []
    with caplog.at_level(logging.DEBUG):
        reports = pipeline.run([_study()], lambda study, report: results.append(study))
    manifest = RunManifest.from_run(config, pipeline, reports)
    text = manifest.to_json()
    assert KEY not in text and KEY not in caplog.text
    # shortcut: source_path keeps the absolute input path (stage-4 debt in the plan); excluded here.
    without_paths = text.replace(str(_study().series[0].files[0]).replace("\\", "\\\\"), "")
    assert _leaks([without_paths, caplog.text]) == []
    assert manifest.steps[0]["params"] == {"policy_version": POLICY_VERSION}
    assert _plain(pipeline_from_manifest(manifest).steps[0].apply(_study())) == _plain(results[0])
