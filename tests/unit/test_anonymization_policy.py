import re

import pytest
from pydicom.datadict import tag_for_keyword

from mri_dataset_tool.infrastructure.anonymization.policy import (
    DICOM_ACTIONS,
    DICOM_DEFAULT_ACTION,
    DICOM_FIXED_VALUES,
    METADATA_WHITELIST,
    POLICY_VERSION,
    SIDECAR_WHITELIST,
    Action,
    filter_validation,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import (
    KEY_ENV_VAR,
    load_key,
    pseudonymize_label,
    pseudonymize_uid,
)

KEY = b"k" * 32
OTHER_KEY = b"o" * 32
UID = "1.2.840.113619.2.55.3.604688119.971.1"
DICOM_UID = re.compile(r"(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*")


def test_load_key_reads_environment(monkeypatch):
    monkeypatch.setenv(KEY_ENV_VAR, "s" * 32)
    assert load_key() == b"s" * 32


@pytest.mark.parametrize("value", [None, "", "short-key"])
def test_load_key_without_valid_key_raises_fixed_message(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(KEY_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(KEY_ENV_VAR, value)
    with pytest.raises(ValueError, match=r"^Anonymization key is not set or too short\.$"):
        load_key()


def test_uid_pseudonym_is_a_valid_dicom_uid_and_deterministic():
    pseudonym = pseudonymize_uid(UID, KEY)
    assert pseudonym.startswith("2.25.")
    assert len(pseudonym) <= 64 and DICOM_UID.fullmatch(pseudonym)
    assert pseudonymize_uid(UID, KEY) == pseudonym
    assert pseudonymize_uid(UID, OTHER_KEY) != pseudonym
    assert pseudonymize_uid(UID + "1", KEY) != pseudonym


def test_uid_pseudonym_is_idempotent_only_under_its_key():
    pseudonym = pseudonymize_uid(UID, KEY)
    assert pseudonymize_uid(pseudonym, KEY) == pseudonym
    assert pseudonymize_uid(pseudonym, OTHER_KEY) != pseudonym


def test_uid_with_root_2_25_that_does_not_verify_is_replaced():
    assert pseudonymize_uid("2.25.12345", KEY) != "2.25.12345"


def test_label_pseudonym_is_16_hex_deterministic_and_domain_separated():
    pseudonym = pseudonymize_label("PAT12345", "subject", KEY)
    assert re.fullmatch(r"[0-9a-f]{16}", pseudonym)
    assert pseudonymize_label("PAT12345", "subject", KEY) == pseudonym
    assert pseudonymize_label("PAT12345", "subject", OTHER_KEY) != pseudonym
    assert pseudonymize_label("PAT12345", "session", KEY) != pseudonym


def test_label_pseudonym_is_idempotent_and_hex_originals_are_replaced():
    pseudonym = pseudonymize_label("PAT12345", "subject", KEY)
    assert pseudonymize_label(pseudonym, "subject", KEY) == pseudonym
    assert pseudonymize_label("0123456789abcdef", "subject", KEY) != "0123456789abcdef"


def test_policy_version_is_a_string():
    assert isinstance(POLICY_VERSION, str) and POLICY_VERSION


def test_deidentification_marks_have_fixed_values_with_the_policy_version():
    assert DICOM_FIXED_VALUES["PatientIdentityRemoved"] == "YES"
    assert POLICY_VERSION in DICOM_FIXED_VALUES["DeidentificationMethod"]
    assert all(DICOM_ACTIONS[keyword] is Action.REPLACED for keyword in DICOM_FIXED_VALUES)


def test_dicom_actions_use_known_keywords_and_actions():
    assert DICOM_DEFAULT_ACTION is Action.REMOVED
    for keyword, action in DICOM_ACTIONS.items():
        assert tag_for_keyword(keyword) is not None, keyword
        assert isinstance(action, Action)


@pytest.mark.parametrize(
    ("keyword", "action"),
    [
        ("PatientName", Action.EMPTIED),
        ("PatientID", Action.REPLACED),
        ("PatientBirthDate", Action.EMPTIED),
        ("PatientIdentityRemoved", Action.REPLACED),
        ("DeidentificationMethod", Action.REPLACED),
        ("PatientAge", Action.GENERALIZED),
        ("PatientSex", Action.KEPT),
        ("StudyInstanceUID", Action.REPLACED),
        ("StudyDate", Action.GENERALIZED),
        ("StudyTime", Action.EMPTIED),
    ],
)
def test_dicom_actions_follow_the_policy(keyword, action):
    assert DICOM_ACTIONS[keyword] is action


@pytest.mark.parametrize(
    "keyword",
    [
        "PatientAddress", "OtherPatientIDs", "PatientWeight", "InstitutionName", "StationName",
        "DeviceSerialNumber", "PerformingPhysicianName", "OperatorsName", "SeriesDescription",
        "StudyDescription", "ProtocolName", "ImageComments", "SeriesTime", "AcquisitionTime",
        "ReferencedImageSequence", "RequestAttributesSequence",
    ],
)
def test_identifying_and_free_text_dicom_elements_are_removed_by_default(keyword):
    assert keyword not in DICOM_ACTIONS


@pytest.mark.parametrize(
    "key",
    ["PatientName", "PatientID", "AcquisitionDateTime", "InstitutionName", "DeviceSerialNumber",
     "SeriesDescription", "ProtocolName", "ImagingFrequency"],
)
def test_sidecar_whitelist_excludes_identifying_keys(key):
    assert key not in SIDECAR_WHITELIST


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"status": "ok", "findings": ["CONSTANT_VOLUME", "Doe^John", 3], "note": "x"},
         {"status": "ok", "findings": ["CONSTANT_VOLUME"]}),
        ({"status": "Doe^John", "findings": "CONSTANT_VOLUME"}, {}),
        ("ok", {}),
        (None, {}),
    ],
)
def test_filter_validation_keeps_only_known_status_and_codes(value, expected):
    assert filter_validation(value) == expected


def test_metadata_whitelist_excludes_files_and_identifiers():
    assert not METADATA_WHITELIST & {"files", "study_uid", "series_uid", "subject_id", "session_id", "path"}
