import json
import logging
import re

import numpy as np
import pytest

from mri_dataset_tool.application.services import labels as labels_service
from mri_dataset_tool.application.services.labels import (
    INVALID_LABEL,
    apply_label_corrections,
    dataset_pairs,
    finalize_labels,
    label_fingerprint,
    reopen_labels,
    review_labels,
    write_label_template,
)
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.dataset.bids_writer import BIDSDatasetWriter
from mri_dataset_tool.infrastructure.dataset.labels import (
    CHANGES_TSV,
    FINAL_JSON,
    LABELS_JSON,
    LABELS_TSV,
    LabelTable,
    read_labels,
)

CLASSES = {"AD": "Alzheimer", "CN": "Control"}
HEADER = "participant_id\tsession_id\tlabel\n"


def make_tree(root, pairs):
    for subject, session in pairs:
        folder = root / f"sub-{subject}" / (f"ses-{session}" if session else "") / "anat"
        folder.mkdir(parents=True)
        (folder / "x.nii.gz").write_bytes(b"")
    return root


def write_table(root, rows: str, classes=CLASSES):
    (root / LABELS_TSV).write_text(HEADER + rows, encoding="utf-8")
    (root / LABELS_JSON).write_text(json.dumps({"label": {"Levels": classes}}), encoding="utf-8")


@pytest.fixture
def tree(tmp_path):
    return make_tree(tmp_path / "ds", [("02", "01"), ("01", "02"), ("01", "01"), ("03", None)])


def test_dataset_pairs_from_tree(tree):
    (tree / "sub-0_x").mkdir()
    (tree / ".sub-hidden").mkdir()
    (tree / "sub-04").write_text("not a folder", encoding="utf-8")
    (tree / "sub-01" / "ses-bad_x").mkdir()
    (tree / "code").mkdir()
    assert dataset_pairs(tree) == [("01", "01"), ("01", "02"), ("02", "01"), ("03", None)]


def test_folders_without_layout_images_are_not_pairs(tree):
    (tree / "sub-ghost").mkdir()
    (tree / "sub-empty" / "ses-01" / "anat").mkdir(parents=True)
    (tree / "sub-01" / "ses-03" / "anat").mkdir(parents=True)
    (tree / "sub-hidden" / "anat").mkdir(parents=True)
    (tree / "sub-hidden" / "anat" / ".x.nii.gz.tmp.nii.gz").write_bytes(b"")
    (tree / "sub-other" / "func").mkdir(parents=True)
    (tree / "sub-other" / "func" / "x.nii.gz").write_bytes(b"")
    (tree / "sub-loose").mkdir()
    (tree / "sub-loose" / "x.nii.gz").write_bytes(b"")
    (tree / "sub-json" / "anat").mkdir(parents=True)
    (tree / "sub-json" / "anat" / "x.json").write_text("{}", encoding="utf-8")
    assert dataset_pairs(tree) == [("01", "01"), ("01", "02"), ("02", "01"), ("03", None)]


def test_dataset_pairs_from_written_dataset(tmp_path):
    root = tmp_path / "ds"
    writer = BIDSDatasetWriter(root)
    affine = np.eye(4)
    for subject, session in [("b", "1"), ("a", None)]:
        series = MRISeries(
            modality="T1w",
            volume=np.zeros((2, 2, 2), dtype=np.float32),
            metadata={"shape": (2, 2, 2), "voxel_size": (1.0, 1.0, 1.0), "affine": affine, "orientation": ("R", "A", "S")},
        )
        assert writer.add_study(MRIStudy(study_uid=None, series=[series], subject_id=subject, session_id=session))
    writer.finalize()
    assert dataset_pairs(root) == [("a", None), ("b", "1")]


def test_dataset_root_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"^Dataset directory not found\.$"):
        dataset_pairs(tmp_path / "missing")
    (tmp_path / "file").write_text("", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match=r"^Dataset path is not a directory\.$"):
        dataset_pairs(tmp_path / "file")


def test_review_complete_table(tree):
    write_table(tree, "sub-01\tses-01\tAD\nsub-01\tses-02\tCN\nsub-02\tses-01\tAD\nsub-03\t\tCN\n")
    review = review_labels(tree)
    assert review.dataset_pairs == 4
    assert review.class_counts == {"AD": 2, "CN": 2}
    assert review.labeled == 4
    assert review.is_complete


def test_review_counts_unused_classes_as_zero(tree):
    write_table(tree, "sub-01\tses-01\tAD\nsub-01\tses-02\tAD\nsub-02\tses-01\tAD\nsub-03\t\tAD\n")
    assert review_labels(tree).class_counts == {"AD": 4, "CN": 0}


@pytest.mark.parametrize(
    ("rows", "field", "expected"),
    [
        ("sub-01\tses-01\t\n", "unlabeled", [("01", "01")]),
        ("sub-01\tses-01\tMCI\n", "unknown_class", [("01", "01")]),
        ("sub-01\tses-01\tAD\nsub-01\tses-01\tCN\n", "duplicated", [("01", "01")]),
        ("sub-01\tses-01\tAD\nsub-01\tses-01\tAD\n", "duplicated", [("01", "01")]),
        ("sub-09\tses-01\tAD\nsub-03\tses-01\tCN\n", "not_in_dataset", 2),
        ("bad\t\tAD\nsub-0_1\t\tAD\nsub-01\t01\tAD\n", "invalid_ids", 3),
    ],
)
def test_review_detects_each_defect(tree, rows, field, expected):
    complete = {
        ("01", "01"): "sub-01\tses-01\tAD\n",
        ("01", "02"): "sub-01\tses-02\tCN\n",
        ("02", "01"): "sub-02\tses-01\tAD\n",
        ("03", None): "sub-03\t\tCN\n",
    }
    # Replace the complete row of the pair under test, if any, with the defective rows.
    if field in ("unlabeled", "unknown_class", "duplicated"):
        del complete[("01", "01")]
    write_table(tree, "".join(complete.values()) + rows)
    review = review_labels(tree)
    assert getattr(review, field) == expected
    assert not review.is_complete
    others = {"unlabeled": [], "unknown_class": [], "duplicated": [], "not_in_dataset": 0, "invalid_ids": 0}
    del others[field]
    assert {name: getattr(review, name) for name in others} == others
    assert review.missing == []


def test_review_detects_missing_pairs(tree):
    write_table(tree, "sub-01\tses-01\tAD\n")
    review = review_labels(tree)
    assert review.missing == [("01", "02"), ("02", "01"), ("03", None)]
    assert review.class_counts == {"AD": 1, "CN": 0}
    assert not review.is_complete


def test_review_structural_errors_propagate(tree):
    with pytest.raises(FileNotFoundError, match=r"^Label classes file not found\.$"):
        review_labels(tree)
    write_table(tree, "")
    with pytest.raises(ValueError, match=r"^Label table is empty\.$"):
        review_labels(tree)


def test_review_does_not_modify_files(tree):
    write_table(tree, "sub-01\tses-01\tMCI\n")
    before = snapshot(tree)
    review_labels(tree)
    assert snapshot(tree) == before


# --- template, corrections, finalize and reopen -------------------------------------------

CHANGES_HEADER = "timestamp_utc\taction\tparticipant_id\tsession_id\told_label\tnew_label"
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
FULL = "sub-01\tses-01\tAD\nsub-01\tses-02\tCN\nsub-02\tses-01\tAD\nsub-03\t\tCN\n"


def corrections(tmp_path, rows: str):
    path = tmp_path / "corrections.tsv"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def changes(root):
    lines = (root / CHANGES_TSV).read_text(encoding="utf-8").splitlines()
    assert lines[0] == CHANGES_HEADER
    rows = [line.split("\t") for line in lines[1:]]
    assert all(TIMESTAMP.fullmatch(row[0]) for row in rows)
    return [row[1:] for row in rows]


@pytest.fixture
def labeled(tree):
    write_label_template(tree, CLASSES)
    return tree


def test_template_lists_dataset_pairs_unlabeled(tree):
    path = write_label_template(tree, CLASSES, "Diagnosis")
    assert path == tree / LABELS_TSV
    expected = HEADER + "sub-01\tses-01\t\nsub-01\tses-02\t\nsub-02\tses-01\t\nsub-03\t\t\n"
    assert path.read_text(encoding="utf-8") == expected
    assert read_labels(tree).classes == CLASSES
    assert not (tree / CHANGES_TSV).exists()


@pytest.mark.parametrize("existing", [LABELS_TSV, LABELS_JSON])
def test_template_never_overwrites(tree, existing):
    (tree / existing).write_text("keep", encoding="utf-8")
    before = snapshot(tree)
    with pytest.raises(FileExistsError, match=r"^Label table already exists\.$"):
        write_label_template(tree, CLASSES)
    assert snapshot(tree) == before


def test_template_needs_participants_and_valid_classes(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match=r"^Dataset has no participants\.$"):
        write_label_template(tmp_path / "empty", CLASSES)
    tree = make_tree(tmp_path / "ds", [("01", None)])
    with pytest.raises(ValueError, match=r"^Label classes are invalid\.$"):
        write_label_template(tree, {"=x": ""})
    assert not (tree / LABELS_TSV).exists()


def test_corrections_assign_and_log(labeled, tmp_path):
    assert apply_label_corrections(labeled, corrections(tmp_path, FULL)) == 4
    assert read_labels(labeled).labels == {
        ("01", "01"): "AD",
        ("01", "02"): "CN",
        ("02", "01"): "AD",
        ("03", None): "CN",
    }
    assert changes(labeled) == [
        ["correct", "sub-01", "ses-01", "", "AD"],
        ["correct", "sub-01", "ses-02", "", "CN"],
        ["correct", "sub-02", "ses-01", "", "AD"],
        ["correct", "sub-03", "", "", "CN"],
    ]


def test_log_only_appends_and_skips_unchanged_rows(labeled, tmp_path):
    apply_label_corrections(labeled, corrections(tmp_path, FULL))
    first = (labeled / CHANGES_TSV).read_bytes()
    assert apply_label_corrections(labeled, corrections(tmp_path, "sub-01\tses-01\tAD\nsub-03\t\tAD\n")) == 1
    assert (labeled / CHANGES_TSV).read_bytes().startswith(first)
    assert changes(labeled)[-1] == ["correct", "sub-03", "", "CN", "AD"]
    after = (labeled / CHANGES_TSV).read_bytes()
    assert apply_label_corrections(labeled, corrections(tmp_path, "sub-01\tses-01\tAD\n")) == 0
    assert (labeled / CHANGES_TSV).read_bytes() == after


def test_log_without_final_newline_keeps_rows_apart(labeled, tmp_path):
    apply_label_corrections(labeled, corrections(tmp_path, "sub-01\tses-01\tAD\n"))
    log = labeled / CHANGES_TSV
    log.write_bytes(log.read_bytes().rstrip(b"\n"))  # hand edit drops the final newline
    apply_label_corrections(labeled, corrections(tmp_path, "sub-03\t\tCN\n"))
    assert changes(labeled) == [
        ["correct", "sub-01", "ses-01", "", "AD"],
        ["correct", "sub-03", "", "", "CN"],
    ]


def test_missing_corrections_file_has_own_message(labeled, tmp_path):
    before = snapshot(labeled)
    with pytest.raises(FileNotFoundError, match=r"^Corrections file not found\.$") as info:
        apply_label_corrections(labeled, tmp_path / "missing.tsv")
    assert info.value.__cause__ is None
    assert snapshot(labeled) == before


def test_empty_correction_sets_unlabeled(labeled, tmp_path):
    apply_label_corrections(labeled, corrections(tmp_path, FULL))
    apply_label_corrections(labeled, corrections(tmp_path, "sub-01\tses-01\t\n"))
    assert read_labels(labeled).labels[("01", "01")] is None
    assert changes(labeled)[-1] == ["correct", "sub-01", "ses-01", "AD", ""]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ("sub-01\tses-01\tAD\nsub-09\tses-01\tCN\n", "Correction targets a participant/session not in the dataset."),
        ("sub-01\tses-01\tAD\nsub-03\t\tMCI\n", "Label table has an unknown class."),
        ("sub-01\tses-01\tAD\nsub-01\tses-01\tCN\n", "Corrections have a duplicate participant/session."),
        ("sub-01\tses-01\tAD\nbad\t\tCN\n", "Label table has an invalid participant or session id."),
        ("sub-01\tses-01\tAD\nsub-03\t\t=1+1\n", "Label table has an unknown class."),
    ],
)
def test_corrections_are_all_or_nothing(labeled, tmp_path, rows, message):
    before = snapshot(labeled)
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        apply_label_corrections(labeled, corrections(tmp_path, rows))
    assert snapshot(labeled) == before


def test_corrections_fix_unknown_class_and_missing_pair(tree, tmp_path):
    write_table(tree, "sub-01\tses-01\tMCI\n")
    with pytest.raises(ValueError, match=r"^Label table has an unknown class\.$"):
        apply_label_corrections(tree, corrections(tmp_path, "sub-03\t\tCN\n"))
    assert apply_label_corrections(tree, corrections(tmp_path, "sub-01\tses-01\tAD\nsub-03\t\tCN\n")) == 2
    assert changes(tree) == [
        ["correct", "sub-01", "ses-01", INVALID_LABEL, "AD"],
        ["correct", "sub-03", "", "", "CN"],
    ]
    assert read_labels(tree).labels == {("01", "01"): "AD", ("03", None): "CN"}


@pytest.mark.parametrize(
    "rows",
    ["sub-01\tses-01\tAD\nsub-01\tses-01\tAD\n", "sub-09\t\tAD\n", "bad\t\tAD\n"],
)
def test_corrections_refuse_table_needing_hand_fix(tree, tmp_path, rows):
    write_table(tree, rows)
    before = snapshot(tree)
    with pytest.raises(ValueError, match=r"^Label table must be fixed by hand before corrections\.$"):
        apply_label_corrections(tree, corrections(tmp_path, "sub-03\t\tCN\n"))
    assert snapshot(tree) == before


def test_failed_table_write_rolls_back_log(labeled, tmp_path, monkeypatch):
    apply_label_corrections(labeled, corrections(tmp_path, "sub-01\tses-01\tAD\n"))
    before = snapshot(labeled)

    def fail(*args, **kwargs):
        raise OSError("Label table could not be written.")

    monkeypatch.setattr(labels_service, "write_labels", fail)
    with pytest.raises(OSError):
        apply_label_corrections(labeled, corrections(tmp_path, "sub-03\t\tCN\n"))
    assert snapshot(labeled) == before


def test_failed_log_on_new_file_leaves_nothing(labeled, tmp_path, monkeypatch):
    before = snapshot(labeled)

    def fail(*args, **kwargs):
        raise OSError("Label table could not be written.")

    monkeypatch.setattr(labels_service, "write_labels", fail)
    with pytest.raises(OSError):
        apply_label_corrections(labeled, corrections(tmp_path, "sub-03\t\tCN\n"))
    assert snapshot(labeled) == before


def test_finalize_writes_counts_and_fingerprint(labeled, tmp_path):
    apply_label_corrections(labeled, corrections(tmp_path, FULL))
    path = finalize_labels(labeled)
    assert path == labeled / FINAL_JSON
    final = json.loads(path.read_text(encoding="utf-8"))
    assert final == {
        "label_count": 4,
        "class_counts": {"AD": 2, "CN": 2},
        "sha256": label_fingerprint(read_labels(labeled)),
    }
    assert re.fullmatch(r"[0-9a-f]{64}", final["sha256"])
    assert changes(labeled)[-1] == ["finalize", "", "", "", ""]


@pytest.mark.parametrize(
    "rows",
    [
        FULL.replace("sub-03\t\tCN", "sub-03\t\t"),
        FULL.replace("sub-03\t\tCN", "sub-03\t\tMCI"),
        FULL.replace("sub-03\t\tCN\n", ""),
        FULL + "sub-03\t\tCN\n",
        FULL + "sub-09\t\tCN\n",
        FULL + "bad\t\tCN\n",
    ],
)
def test_finalize_refuses_incomplete_or_invalid(tree, rows):
    write_table(tree, rows)
    before = snapshot(tree)
    with pytest.raises(ValueError, match=r"^Labels are incomplete or invalid\.$"):
        finalize_labels(tree)
    assert snapshot(tree) == before


def test_finalized_labels_refuse_changes_until_reopened(labeled, tmp_path):
    apply_label_corrections(labeled, corrections(tmp_path, FULL))
    finalize_labels(labeled)
    before = snapshot(labeled)
    with pytest.raises(ValueError, match=r"^Labels are finalized\.$"):
        apply_label_corrections(labeled, corrections(tmp_path, "sub-03\t\tAD\n"))
    with pytest.raises(FileExistsError, match=r"^Labels are already finalized\.$"):
        finalize_labels(labeled)
    assert snapshot(labeled) == before

    reopen_labels(labeled)
    assert not (labeled / FINAL_JSON).exists()
    assert changes(labeled)[-1] == ["reopen", "", "", "", ""]
    assert apply_label_corrections(labeled, corrections(tmp_path, "sub-03\t\tAD\n")) == 1
    finalize_labels(labeled)
    actions = [row[0] for row in changes(labeled)]
    assert actions == ["correct"] * 4 + ["finalize", "reopen", "correct", "finalize"]


def test_reopen_requires_finalized(labeled):
    with pytest.raises(ValueError, match=r"^Labels are not finalized\.$"):
        reopen_labels(labeled)
    assert not (labeled / CHANGES_TSV).exists()


def test_fingerprint_tracks_content_not_formatting():
    base = LabelTable(CLASSES, {("01", None): "AD", ("02", None): "CN"})
    reordered = LabelTable(dict(reversed(CLASSES.items())), {("02", None): "CN", ("01", None): "AD"})
    assert label_fingerprint(base) == label_fingerprint(reordered)
    for changed in (
        LabelTable(CLASSES, {("01", None): "CN", ("02", None): "CN"}),
        LabelTable({**CLASSES, "MCI": ""}, base.labels),
        LabelTable({"AD": "other", "CN": "Control"}, base.labels),
    ):
        assert label_fingerprint(changed) != label_fingerprint(base)


def test_no_paths_or_ids_in_service_errors_or_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    root = make_tree(tmp_path / "Doe_John", [("SECRET1", None)])
    write_label_template(root, CLASSES)
    errors = []
    for call in (
        lambda: apply_label_corrections(root, corrections(tmp_path, "sub-SECRET2\t\tAD\n")),
        lambda: finalize_labels(root),
        lambda: reopen_labels(root),
        lambda: dataset_pairs(tmp_path / "Doe_John_missing"),
    ):
        with pytest.raises((ValueError, FileNotFoundError)) as info:
            call()
        errors.append(str(info.value))
    for secret in ("SECRET1", "SECRET2", "Doe_John", str(tmp_path)):
        assert all(secret not in error for error in errors)
        assert secret not in caplog.text
