"""``labels_table``: the label table as rows with defects, and edits through the corrections service."""

from pathlib import Path

import pytest

from mri_dataset_tool.application.services.labels import (
    finalize_labels,
    reopen_labels,
    review_labels,
    write_label_template,
)
from mri_dataset_tool.application.services.labels_table import (
    LabelRow,
    apply_label_edits,
    label_classes,
    labels_finalized,
    read_label_corrections,
    read_label_rows,
)

CLASSES = {"AD": "Alzheimer", "CN": ""}
PAIRS = [("a1", "v1"), ("a1", "v2"), ("b2", "v1"), ("c3", "v1")]


def _dataset(root: Path) -> Path:
    for subject, session in PAIRS:
        anat = root / f"sub-{subject}" / f"ses-{session}" / "anat"
        anat.mkdir(parents=True)
        (anat / f"sub-{subject}_ses-{session}_T1w.nii.gz").write_bytes(b"")
    write_label_template(root, CLASSES)
    return root


def _tsv(root: Path, *rows: str) -> None:
    (root / "labels.tsv").write_text("participant_id\tsession_id\tlabel\n" + "".join(f"{r}\n" for r in rows),
                                     encoding="utf-8")


def test_rows_list_every_pair_with_its_class_or_defect(tmp_path):
    root = _dataset(tmp_path / "dataset")
    assert read_label_rows(root) == [LabelRow(s, v, None, "UNLABELED") for s, v in PAIRS]
    _tsv(root, "sub-a1\tses-v1\tAD", "sub-a1\tses-v2\tPlantedClass", "sub-b2\tses-v1\tCN", "sub-b2\tses-v1\tAD",
         "sub-zz\tses-v1\tAD", "bad id\t\tCN")  # c3 missing; zz foreign; one invalid id
    assert read_label_rows(root) == [
        LabelRow("a1", "v1", "AD", None), LabelRow("a1", "v2", None, "UNKNOWN_CLASS"),
        LabelRow("b2", "v1", None, "DUPLICATED"), LabelRow("c3", "v1", None, "MISSING"),
    ]
    review = review_labels(root)  # foreign and invalid rows are only counted
    assert (review.not_in_dataset, review.invalid_ids) == (1, 1)
    assert "Planted" not in repr(read_label_rows(root))  # a defective cell is never returned


def test_edits_are_applied_logged_and_the_temporary_table_removed(tmp_path):
    root = _dataset(tmp_path / "dataset")
    assert apply_label_edits(root, {("a1", "v1"): "AD", ("b2", "v1"): "CN", ("c3", "v1"): ""}) == 2
    rows = {(r.participant, r.session): r for r in read_label_rows(root)}
    assert (rows[("a1", "v1")].label, rows[("b2", "v1")].label, rows[("c3", "v1")].defect) == ("AD", "CN", "UNLABELED")
    log = (root / "labels_changes.tsv").read_text(encoding="utf-8")
    assert "sub-a1" in log and "correct" in log
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dataset"]  # no temporary file left
    assert apply_label_edits(root, {}) == 0


@pytest.mark.parametrize(
    ("edits", "error"),
    [
        ({("a1", "v1"): "MCI"}, ValueError),  # not a class: all or nothing
        ({("zz", "v1"): "AD"}, ValueError),  # not a dataset pair
        ({("a1", "v1"): "AD\nsub-b2\tses-v1\tCN"}, ValueError),  # would inject a row
        ({("a 1", "v1"): "AD"}, ValueError),
    ],
)
def test_invalid_edits_change_nothing(tmp_path, edits, error):
    root = _dataset(tmp_path / "dataset")
    before = (root / "labels.tsv").read_bytes()
    with pytest.raises(error):
        apply_label_edits(root, {("b2", "v1"): "CN", **edits})
    assert (root / "labels.tsv").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dataset"]


def test_finalized_labels_reject_edits_until_reopened(tmp_path):
    root = _dataset(tmp_path / "dataset")
    apply_label_edits(root, {pair: "AD" for pair in PAIRS})
    assert label_classes(root) == ["AD", "CN"] and not labels_finalized(root)
    finalize_labels(root)
    assert labels_finalized(root)
    with pytest.raises(ValueError, match="Labels are finalized."):
        apply_label_edits(root, {("a1", "v1"): "CN"})
    reopen_labels(root)
    assert apply_label_edits(root, {("a1", "v1"): "CN"}) == 1


def test_corrections_are_read_as_edits_with_the_cli_rules(tmp_path):
    root = _dataset(tmp_path / "dataset")
    path = tmp_path / "fix.tsv"
    path.write_text("participant_id\tsession_id\tlabel\nsub-a1\tses-v1\tAD\nsub-b2\tses-v1\t\n", encoding="utf-8")
    assert read_label_corrections(root, path) == {("a1", "v1"): "AD", ("b2", "v1"): ""}
    assert (root / "labels.tsv").read_text(encoding="utf-8").count("\tAD") == 0  # nothing written
    cases = {
        "sub-zz\tses-v1\tAD": "Correction targets a participant/session not in the dataset.",
        "sub-a1\tses-v1\tAD\nsub-a1\tses-v1\tCN": "Corrections have a duplicate participant/session.",
        "sub-a1\tses-v1\tMCI": "Label table has an unknown class.",
        "bad id\t\tAD": "Corrections file is invalid.",
    }
    for rows, message in cases.items():
        path.write_text(f"participant_id\tsession_id\tlabel\n{rows}\n", encoding="utf-8")
        with pytest.raises(ValueError) as raised:
            read_label_corrections(root, path)
        assert str(raised.value) == message
    path.write_text("not a table\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrections file is invalid."):
        read_label_corrections(root, path)
    with pytest.raises(FileNotFoundError, match="Corrections file not found."):
        read_label_corrections(root, tmp_path / "none.tsv")


def test_an_unreadable_corrections_file_has_a_fixed_message(tmp_path):
    root = _dataset(tmp_path / "dataset")
    (tmp_path / "folder.tsv").mkdir()
    with pytest.raises(OSError) as raised:
        read_label_corrections(root, tmp_path / "folder.tsv")
    assert str(raised.value) == "Corrections file could not be read." and "folder" not in str(raised.value)
