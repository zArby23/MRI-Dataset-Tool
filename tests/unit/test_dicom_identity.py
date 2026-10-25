"""DICOM identity pass: pseudonymized participant per study and a suffix decision per series, no PHI kept."""

import logging

from mri_dataset_tool.infrastructure.anonymization.pseudonym import pseudonymize_label
from mri_dataset_tool.infrastructure.dicom.identity import read_dicom_identities
from test_anonymize_dicom_tree import KEY, PLANTED, write_synthetic_series

KEY_BYTES = KEY.encode()
STUDY_A, STUDY_B = "1.2.826.0.1.3680043.8.498.30001", "1.2.826.0.1.3680043.8.498.30002"


def _series(root, name, study, series, **overrides):
    return write_synthetic_series(
        root / name, StudyInstanceUID=study, SeriesInstanceUID=f"{study}.{series}", **overrides
    )


def test_participant_is_the_pseudonym_of_patient_id_and_suffixes_are_decided(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    _series(tmp_path, "a1", STUDY_A, 1, SeriesDescription="T1 MPRAGE PlantedDesc", ProtocolName="PlantedProto")
    _series(tmp_path, "a2", STUDY_A, 2, SeriesDescription="ep2d_diff_ADC")
    _series(tmp_path, "b1", STUDY_B, 1, SeriesDescription="t2_flair", Modality="CT")
    (tmp_path / "README").write_text("not dicom", encoding="utf-8")
    identities = read_dicom_identities(tmp_path, KEY_BYTES)
    expected = pseudonymize_label("PAT12345", "subject", KEY_BYTES)
    assert identities.subject_by_study == {STUDY_A: expected, STUDY_B: expected}  # same patient, two studies
    assert identities.suffix_by_series == {
        f"{STUDY_A}.1": ("T1w", "MATCHED"),
        f"{STUDY_A}.2": (None, "EXCLUDED"),
        f"{STUDY_B}.1": (None, "EXCLUDED"),  # not MR
    }
    text = repr(identities) + caplog.text
    assert not [value for value in [*PLANTED[4:], "PlantedDesc", "PlantedProto", "MPRAGE"] if value in text]


def test_missing_or_inconsistent_patient_id_gives_one_participant_per_study(tmp_path):
    _series(tmp_path, "a", STUDY_A, 1, PatientID="")
    _series(tmp_path, "b1", STUDY_B, 1, PatientID="P1")
    _series(tmp_path, "b2", STUDY_B, 2, PatientID="P2")
    identities = read_dicom_identities(tmp_path, KEY_BYTES)
    assert identities.subject_by_study == {
        STUDY_A: pseudonymize_label(STUDY_A, "subject", KEY_BYTES),
        STUDY_B: pseudonymize_label(STUDY_B, "subject", KEY_BYTES),
    }


def test_series_without_descriptions_is_no_match(tmp_path):
    _series(tmp_path, "a", STUDY_A, 1, SeriesDescription="", ProtocolName="")
    assert read_dicom_identities(tmp_path, KEY_BYTES).suffix_by_series == {f"{STUDY_A}.1": (None, "NO_MATCH")}
