"""``dataset_ingest`` service: --mapping validation, planning (ids, suffixes, labels) and streaming."""

import gc
import weakref
from pathlib import Path, PurePosixPath

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput
from mri_dataset_tool.application.services.dataset_ingest import (
    SeriesDecision,
    iter_ingested_studies,
    load_mapping,
    plan_ingest,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import pseudonymize_label
from test_anonymize_dicom_tree import KEY, write_synthetic_series

KEY_BYTES = KEY.encode()
STUDY_A, STUDY_B = "1.2.826.0.1.3680043.8.498.30001", "1.2.826.0.1.3680043.8.498.30002"
HEADER = "path\tparticipant\tsession\tsuffix"


def dicom_tree(root: Path) -> Path:
    """Patient PAT12345 with two studies: A = T1 (planted description) + ADC map, B = FLAIR."""
    write_synthetic_series(root / "a" / "t1", StudyInstanceUID=STUDY_A, SeriesInstanceUID=f"{STUDY_A}.1",
                           SeriesDescription="T1 MPRAGE PlantedDesc", ProtocolName="PlantedProto")
    write_synthetic_series(root / "a" / "adc", StudyInstanceUID=STUDY_A, SeriesInstanceUID=f"{STUDY_A}.2",
                           SeriesDescription="ep2d_diff_ADC")
    write_synthetic_series(root / "b" / "flair", StudyInstanceUID=STUDY_B, SeriesInstanceUID=f"{STUDY_B}.1",
                           SeriesDescription="t2_flair_tra")
    return root


def _nifti(path: Path, shape=(4, 5, 3)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.random.default_rng(0).uniform(1, 9, shape).astype(np.float32), np.eye(4)), path)
    return path


def _mapping(path: Path, *rows: str, header: str = HEADER) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _pair(subject: str, session: str | None) -> tuple[str, str | None]:
    return pseudonymize_label(subject, "subject", KEY_BYTES), None if session is None else pseudonymize_label(
        session, "session", KEY_BYTES
    )


# --- --mapping ----------------------------------------------------------------------------------------


def test_load_mapping_accepts_both_headers_and_normalizes_paths(tmp_path):
    root = dicom_tree(tmp_path / "in")
    rows = load_mapping(_mapping(tmp_path / "m.tsv", "a\tP01\t\t", "./a/t1\t\t\tT1w"), root)
    assert [(r.path.as_posix(), r.participant, r.suffix, r.label) for r in rows] == [("a", "P01", "", ""), ("a/t1", "", "T1w", "")]
    rows = load_mapping(_mapping(tmp_path / "l.tsv", "b\t\t\t\tCN", header=HEADER + "\tlabel"), root, {"AD": "", "CN": ""})
    assert rows[0].label == "CN"


@pytest.mark.parametrize(
    ("header", "rows", "classes", "message"),
    [
        ("path\tparticipant", [], None, "Invalid --mapping."),
        (HEADER, ["a\tP01"], None, "Invalid --mapping."),  # missing cells
        (HEADER, ["/abs\t\t\t"], None, "Invalid --mapping."),
        (HEADER, ["../a\t\t\t"], None, "Invalid --mapping."),
        (HEADER, ["a\\t1\t\t\t"], None, "Invalid --mapping."),
        (HEADER, ["C:a\t\t\t"], None, "Invalid --mapping."),
        (HEADER, ["\tP01\t\t"], None, "Invalid --mapping."),
        (HEADER, ["a\t\t\t", "./a\t\t\t"], None, "Invalid --mapping."),  # repeated after normalization
        (HEADER, ["a\tsub-01\t\t"], None, "Invalid --mapping."),
        (HEADER, ["a\t\tses 1\t"], None, "Invalid --mapping."),
        (HEADER, ["a\t\t\tbold"], None, "Invalid --mapping."),
        (HEADER + "\tlabel", ["a\t\t\t\tAD"], None, "Mapping labels need --classes."),
        (HEADER + "\tlabel", ["a\t\t\t\tXX"], {"AD": ""}, "Mapping label is not one of --classes."),
        (HEADER, ["a\t\t\t", "nope\t\t\t", "a/none\t\t\t"], None, "Mapping paths not found in the input: 2."),
    ],
)
def test_load_mapping_rejects_with_fixed_messages(tmp_path, header, rows, classes, message):
    root = dicom_tree(tmp_path / "in")
    with pytest.raises(InvalidBuildInput) as raised:
        load_mapping(_mapping(tmp_path / "m.tsv", *rows, header=header), root, classes)
    assert str(raised.value) == message


def test_load_mapping_missing_or_unreadable_file(tmp_path):
    with pytest.raises(InvalidBuildInput, match="^Mapping file not found.$"):
        load_mapping(tmp_path / "none.tsv", tmp_path)
    (tmp_path / "bad.tsv").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(InvalidBuildInput, match=r"^Invalid --mapping\.$"):
        load_mapping(tmp_path / "bad.tsv", tmp_path)


# --- DICOM ---------------------------------------------------------------------------------------------


def test_dicom_plan_without_mapping(tmp_path):
    plan = plan_ingest("dicom", dicom_tree(tmp_path / "in"), KEY_BYTES)
    subject = pseudonymize_label("PAT12345", "subject", KEY_BYTES)
    assert [(s, ses, sfx) for _, s, ses, sfx in plan.entries] == [
        (subject, pseudonymize_label(STUDY_A, "session", KEY_BYTES), ["T1w", None]),
        (subject, pseudonymize_label(STUDY_B, "session", KEY_BYTES), ["FLAIR"]),
    ]
    assert plan.series == 2 and plan.skipped == {"EXCLUDED": 1} and plan.labels == {} and plan.mapping_unused == 0


def test_dicom_studies_are_streamed_as_float32_with_suffixes(tmp_path):
    plan = plan_ingest("dicom", dicom_tree(tmp_path / "in"), KEY_BYTES)
    alive = []

    def track(study):
        gc.collect()
        assert all(ref() is None for ref in alive), "a previous study is still alive"
        alive.append(weakref.ref(study))
        return [(s.modality, s.volume.dtype, s.volume.shape == tuple(s.metadata["shape"])) for s in study.series], study.subject_id

    seen = list(map(track, iter_ingested_studies(plan)))
    subject = pseudonymize_label("PAT12345", "subject", KEY_BYTES)
    assert seen == [([("T1w", np.float32, True)], subject), ([("FLAIR", np.float32, True)], subject)]


def test_mapping_sets_ids_suffix_and_labels(tmp_path):
    root = dicom_tree(tmp_path / "in")
    (root / "notes").mkdir()
    (root / "notes" / "x.txt").write_text("x", encoding="utf-8")
    rows = load_mapping(_mapping(tmp_path / "m.tsv", ".\tP01\t\t\t", "a\t\tV1\t\tAD", "a/adc\t\t\tT2w\t", "b\t\tV2\t\tCN",
                                 "notes\t\t\t\t", header=HEADER + "\tlabel"), root, {"AD": "", "CN": ""})
    plan = plan_ingest("dicom", root, KEY_BYTES, rows)
    assert [(s, ses, sfx) for _, s, ses, sfx in plan.entries] == [("P01", "V1", ["T1w", "T2w"]), ("P01", "V2", ["FLAIR"])]
    assert plan.labels == {_pair("P01", "V1"): "AD", _pair("P01", "V2"): "CN"}
    assert plan.skipped == {} and plan.mapping_unused == 1  # the notes/ row matches no series


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (["a/t1\t\t\t\tAD", "a/adc\t\t\tT2w\tCN"], "Mapping assigns different labels to the same participant/session."),
        (["a/t1\tP02\t\t\t"], "Mapping gives one study more than one participant or session."),
    ],
)
def test_conflicting_mappings_are_rejected(tmp_path, rows, message):
    root = dicom_tree(tmp_path / "in")
    mapping = load_mapping(_mapping(tmp_path / "m.tsv", *rows, header=HEADER + "\tlabel"), root, {"AD": "", "CN": ""})
    with pytest.raises(InvalidBuildInput, match=f"^{message}$"):
        plan_ingest("dicom", root, KEY_BYTES, mapping)


def test_nothing_mappable_or_no_input(tmp_path):
    write_synthetic_series(tmp_path / "in" / "loc", SeriesDescription="localizer")
    with pytest.raises(InvalidBuildInput, match="^No input series could be mapped to a BIDS suffix.$"):
        plan_ingest("dicom", tmp_path / "in", KEY_BYTES)
    (tmp_path / "empty").mkdir()
    for fmt in ("dicom", "nifti"):
        with pytest.raises(InvalidBuildInput, match="^No valid input studies were found.$"):
            plan_ingest(fmt, tmp_path / "empty", KEY_BYTES)


def test_series_that_fail_to_build_are_reported_and_skipped(tmp_path):
    root = dicom_tree(tmp_path / "in")
    plan = plan_ingest("dicom", root, KEY_BYTES)
    for path in (root / "b" / "flair").iterdir():  # corrupt the pixels of the FLAIR series after planning
        path.write_bytes(path.read_bytes()[:-20])
    errors = []
    studies = list(iter_ingested_studies(plan, lambda path, error: errors.append(type(error).__name__)))
    assert len(studies) == 1 and len(errors) == 1


# --- NIfTI ---------------------------------------------------------------------------------------------


def test_nifti_fallback_one_participant_per_file_and_dwi_must_be_4d(tmp_path):
    root = tmp_path / "in"
    _nifti(root / "PlantedName_T1.nii.gz")
    _nifti(root / "x" / "flair.nii")
    _nifti(root / "scan.nii.gz")  # no rule matches
    _nifti(root / "dwi.nii.gz")  # 3D: skipped while iterating
    _nifti(root / "dwi_4d.nii.gz", shape=(4, 5, 3, 2))
    plan = plan_ingest("nifti", root, KEY_BYTES)
    assert plan.skipped == {"NO_MATCH": 1} and plan.series == 4
    subjects = {subject for subject, _, _ in plan.entries}  # file order is OS-dependent (case)
    assert subjects == {pseudonymize_label(name, "subject", KEY_BYTES) for name in
                        ("PlantedName_T1.nii.gz", "dwi.nii.gz", "dwi_4d.nii.gz", "x/flair.nii")}
    studies = list(iter_ingested_studies(plan))
    assert sorted(s.series[0].modality for s in studies) == ["FLAIR", "T1w", "dwi"]
    assert plan.skipped == {"NO_MATCH": 1, "NOT_4D_DWI": 1}
    assert all(s.session_id is None and "Planted" not in s.subject_id for s in studies)


def test_nifti_mapping_groups_files_of_one_participant(tmp_path):
    root = tmp_path / "in"
    _nifti(root / "p1" / "a.nii.gz")
    _nifti(root / "p1" / "b.nii.gz")
    rows = load_mapping(_mapping(tmp_path / "m.tsv", "p1\tP1\tS1\t", "p1/a.nii.gz\t\t\tT1w", "p1/b.nii.gz\t\t\tT2w"), root)
    plan = plan_ingest("nifti", root, KEY_BYTES, rows)
    (study,) = list(iter_ingested_studies(plan))
    assert (study.subject_id, study.session_id) == ("P1", "S1")
    assert [s.modality for s in study.series] == ["T1w", "T2w"]


# --- conflicts and table details ------------------------------------------------------------------------


def test_two_dicom_studies_with_the_same_participant_and_session_are_rejected(tmp_path):
    root = dicom_tree(tmp_path / "in")
    rows = load_mapping(_mapping(tmp_path / "m.tsv", ".\tP01\tV1\t"), root)
    with pytest.raises(InvalidBuildInput, match="^Mapping gives the same participant/session to more than one study.$"):
        plan_ingest("dicom", root, KEY_BYTES, rows)


def test_pairs_are_compared_as_the_pseudonyms_the_dataset_will_hold(tmp_path):
    root = tmp_path / "in"
    write_synthetic_series(root / "a", StudyInstanceUID=STUDY_A, SeriesInstanceUID=f"{STUDY_A}.1", SeriesDescription="T1")
    write_synthetic_series(root / "b", StudyInstanceUID=STUDY_B, SeriesInstanceUID=f"{STUDY_B}.1", SeriesDescription="T1",
                           PatientID="OTHER1")
    # study a: automatic id = pseudonym of PatientID PAT12345; study b: the mapping id "PAT12345", which
    # anonymize turns into that same pseudonym; same session V1 -> the writer would reject one of them
    rows = load_mapping(_mapping(tmp_path / "m.tsv", "a\t\tV1\t", "b\tPAT12345\tV1\t"), root)
    with pytest.raises(InvalidBuildInput, match="^Mapping gives the same participant/session to more than one study.$"):
        plan_ingest("dicom", root, KEY_BYTES, rows)


def test_a_participant_with_and_without_session_is_rejected(tmp_path):
    root = tmp_path / "in"
    _nifti(root / "a_T1.nii.gz")
    _nifti(root / "b_T2.nii.gz")
    rows = load_mapping(_mapping(tmp_path / "m.tsv", "a_T1.nii.gz\tP1\t\t", "b_T2.nii.gz\tP1\tS1\t"), root)
    with pytest.raises(InvalidBuildInput, match="^Mapping gives a participant both sessions and no session.$"):
        plan_ingest("nifti", root, KEY_BYTES, rows)


def test_mapping_with_a_bom_is_read(tmp_path):
    root = dicom_tree(tmp_path / "in")
    path = tmp_path / "m.tsv"
    path.write_bytes(("﻿" + HEADER + "\na\tP01\t\t\n").encode("utf-8"))
    assert load_mapping(path, root)[0].participant == "P01"


def test_mapping_paths_must_match_case_exactly(tmp_path):
    root = dicom_tree(tmp_path / "in")
    with pytest.raises(InvalidBuildInput, match=r"^Mapping paths not found in the input: 2\.$"):
        load_mapping(_mapping(tmp_path / "m.tsv", "A\t\t\t", "a/T1\t\t\t", "a/t1\t\t\t"), root)


def test_a_row_for_one_file_of_a_dicom_series_does_not_apply(tmp_path):
    root = dicom_tree(tmp_path / "in")
    one_file = sorted((root / "a" / "t1").iterdir())[0].relative_to(root).as_posix()
    rows = load_mapping(_mapping(tmp_path / "m.tsv", f"{one_file}\t\t\tT2w"), root)
    plan = plan_ingest("dicom", root, KEY_BYTES, rows)
    assert plan.entries[0][3] == ["T1w", None] and plan.mapping_unused == 1


def test_the_key_is_read_from_the_environment_when_not_given(tmp_path, monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    plan = plan_ingest("dicom", dicom_tree(tmp_path / "in"))
    assert plan.entries[0][1] == pseudonymize_label("PAT12345", "subject", KEY_BYTES)


def test_studies_without_patient_id_are_counted_unless_mapped(tmp_path):  # QA6-06
    root = dicom_tree(tmp_path / "in")
    write_synthetic_series(root / "b" / "t2", StudyInstanceUID=STUDY_B, SeriesInstanceUID=f"{STUDY_B}.2",
                           SeriesDescription="T2 TSE", PatientID="")
    assert plan_ingest("dicom", root, key=KEY_BYTES).missing_patient_id == 1
    rows = load_mapping(_mapping(tmp_path / "m.tsv", "b	P01		"), root)
    assert plan_ingest("dicom", root, key=KEY_BYTES, mapping=rows).missing_patient_id == 0
    assert plan_ingest("dicom", dicom_tree(tmp_path / "ok"), key=KEY_BYTES).missing_patient_id == 0


def test_plan_records_one_decision_per_dicom_series(tmp_path):
    root = dicom_tree(tmp_path / "in")
    rows = load_mapping(_mapping(tmp_path / "m.tsv", "b	P01			CN", header=HEADER + "	label"), root, {"CN": ""})
    plan = plan_ingest("dicom", root, key=KEY_BYTES, mapping=rows)
    subject_a = pseudonymize_label("PAT12345", "subject", KEY_BYTES)
    session_a = pseudonymize_label(STUDY_A, "session", KEY_BYTES)
    assert sorted(plan.decisions, key=lambda d: d.location) == [
        SeriesDecision(PurePosixPath("a/adc"), None, "EXCLUDED", subject_a, session_a),
        SeriesDecision(PurePosixPath("a/t1"), "T1w", "MATCHED", subject_a, session_a),
        SeriesDecision(PurePosixPath("b/flair"), "FLAIR", "MATCHED", "P01",
                       pseudonymize_label(STUDY_B, "session", KEY_BYTES), "CN"),
    ]


def test_plan_records_one_decision_per_nifti_file_also_when_skipped(tmp_path):
    root = tmp_path / "in"
    _nifti(root / "x" / "scan_T1.nii.gz")
    _nifti(root / "notes.nii.gz")
    rows = load_mapping(_mapping(tmp_path / "m.tsv", "notes.nii.gz	P02	V1	T2w"), root)
    plan = plan_ingest("nifti", root, key=KEY_BYTES, mapping=rows)
    by_location = {d.location.as_posix(): d for d in plan.decisions}
    assert by_location["notes.nii.gz"] == SeriesDecision(by_location["notes.nii.gz"].location, "T2w", "MAPPED", "P02", "V1")
    assert (by_location["x/scan_T1.nii.gz"].suffix, by_location["x/scan_T1.nii.gz"].code) == ("T1w", "MATCHED")
    plan = plan_ingest("nifti", root, key=KEY_BYTES)
    assert {d.location.as_posix(): d.code for d in plan.decisions} == {"notes.nii.gz": "NO_MATCH", "x/scan_T1.nii.gz": "MATCHED"}
    assert plan.skipped == {"NO_MATCH": 1}  # decisions do not change what is skipped
