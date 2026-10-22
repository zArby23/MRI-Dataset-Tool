import json
import logging
import re

import pytest

from mri_dataset_tool.infrastructure.dataset.labels import (
    LABELS_JSON,
    LABELS_TSV,
    LabelTable,
    parse_label_key,
    parse_label_rows,
    read_classes,
    read_labels,
    write_labels,
)

CLASSES = {"AD": "Alzheimer", "CN": "Control"}
HEADER = "participant_id\tsession_id\tlabel\n"


def make_table(**overrides) -> LabelTable:
    values = {
        "classes": CLASSES,
        "labels": {("02", "01"): "CN", ("01", "02"): None, ("01", "01"): "AD"},
        "description": "Diagnosis",
    }
    values.update(overrides)
    return LabelTable(**values)


def write_files(root, tsv: str, classes=CLASSES) -> None:
    (root / LABELS_TSV).write_text(tsv, encoding="utf-8", newline="")
    (root / LABELS_JSON).write_text(json.dumps({"label": {"Levels": classes}}), encoding="utf-8")


def test_round_trip(tmp_path):
    table = make_table()
    write_labels(table, tmp_path)
    assert read_labels(tmp_path) == table


def test_written_tsv_is_sorted_utf8_with_prefixes_and_lf(tmp_path):
    write_labels(make_table(classes={"Ñandú": "", **CLASSES}, labels={("01", None): "Ñandú"}), tmp_path)
    data = (tmp_path / LABELS_TSV).read_bytes()
    assert data == (HEADER + "sub-01\t\tÑandú\n").encode("utf-8")
    other = tmp_path / "other"
    other.mkdir()
    write_labels(make_table(), other)
    lines = (other / LABELS_TSV).read_text(encoding="utf-8").splitlines()
    assert lines[1:] == ["sub-01\tses-01\tAD", "sub-01\tses-02\t", "sub-02\tses-01\tCN"]


def test_write_is_deterministic(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(), second.mkdir()
    write_labels(make_table(), first)
    write_labels(make_table(), second)
    for name in (LABELS_TSV, LABELS_JSON):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_labels_json_format(tmp_path):
    write_labels(make_table(), tmp_path)
    assert json.loads((tmp_path / LABELS_JSON).read_text(encoding="utf-8")) == {
        "label": {"Description": "Diagnosis", "Levels": CLASSES}
    }
    assert read_classes(tmp_path) == (CLASSES, "Diagnosis")


def test_empty_label_is_unlabeled_not_invalid(tmp_path):
    write_files(tmp_path, HEADER + "sub-01\tses-01\t\n")
    assert read_labels(tmp_path).labels == {("01", "01"): None}


def test_unknown_class_is_invalid(tmp_path):
    write_files(tmp_path, HEADER + "sub-01\tses-01\tMCI\n")
    with pytest.raises(ValueError, match=r"^Label table has an unknown class\.$"):
        read_labels(tmp_path)


@pytest.mark.parametrize("name", ["=1+1", "+a", "-b", "@cmd", "\tx", "\rx"])
def test_formula_like_class_names_are_rejected(tmp_path, name):
    with pytest.raises(ValueError, match=r"^Label classes are invalid\.$"):
        make_table(classes={name: "", **CLASSES})
    (tmp_path / LABELS_JSON).write_text(json.dumps({"label": {"Levels": {name: ""}}}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"^Label classes are invalid\.$"):
        read_classes(tmp_path)


def test_formula_like_cell_is_read_as_data_but_is_not_a_class(tmp_path):
    write_files(tmp_path, HEADER + "sub-01\t\t=HYPERLINK(1)\n")
    assert parse_label_rows(tmp_path / LABELS_TSV) == [("sub-01", "", "=HYPERLINK(1)")]
    with pytest.raises(ValueError, match=r"^Label table has an unknown class\.$"):
        read_labels(tmp_path)


def test_formula_chars_inside_names_and_descriptions_are_data(tmp_path):
    table = make_table(classes={"A=B": "=desc", "CN": "@x"}, labels={("01", None): "A=B"})
    write_labels(table, tmp_path)
    assert read_labels(tmp_path) == table


def test_reads_excel_bom_crlf_extra_columns_and_blank_lines(tmp_path):
    tsv = "\ufeffnotes\tlabel\tsession_id\tparticipant_id\r\nx\tAD\t\tsub-01\r\n\r\n"
    write_files(tmp_path, tsv)
    assert read_labels(tmp_path).labels == {("01", None): "AD"}


@pytest.mark.parametrize(
    ("tsv", "message"),
    [
        ("", "Label table is empty."),
        (HEADER, "Label table is empty."),
        ("participant_id\tlabel\nsub-01\tAD\n", "Label table is missing required columns."),
        ("participant_id\tsession_id\tlabel\tlabel\nsub-01\t\tAD\tAD\n", "Label table is missing required columns."),
        (HEADER + "sub-01\tAD\n", "Label table has a malformed row."),
        (HEADER + "sub-01\t\tAD\textra\n", "Label table has a malformed row."),
        (HEADER + "sub-01\tses-01\tAD\nsub-01\tses-01\tCN\n", "Label table has a duplicate participant/session."),
    ],
)
def test_structural_errors(tmp_path, tsv, message):
    write_files(tmp_path, tsv)
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        read_labels(tmp_path)


@pytest.mark.parametrize(
    ("participant", "session"),
    [
        ("01", ""),
        ("sub-", ""),
        ("sub-0_1", ""),
        ("sub-0 1", ""),
        ("sub-../x", ""),
        ("sub-01", "01"),
        ("sub-01", "ses-"),
        ("sub-01", "ses-a/b"),
        ("SUB-01", ""),
    ],
)
def test_invalid_ids_are_rejected(tmp_path, participant, session):
    write_files(tmp_path, HEADER + f"{participant}\t{session}\tAD\n")
    with pytest.raises(ValueError, match=r"^Label table has an invalid participant or session id\.$"):
        read_labels(tmp_path)


def test_parse_label_key():
    assert parse_label_key("sub-01", "") == ("01", None)
    assert parse_label_key("sub-a1", "ses-B2") == ("a1", "B2")


def test_tolerant_parse_keeps_defects_for_review(tmp_path):
    write_files(tmp_path, HEADER + "sub-01\t\tMCI\nsub-01\t\tAD\nbad\t\t\n")
    assert parse_label_rows(tmp_path / LABELS_TSV) == [("sub-01", "", "MCI"), ("sub-01", "", "AD"), ("bad", "", "")]


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps([]),
        json.dumps({"label": {}}),
        json.dumps({"label": {"Levels": {}}}),
        json.dumps({"label": {"Levels": ["AD"]}}),
        json.dumps({"label": {"Levels": {"AD": 1}}}),
        json.dumps({"label": {"Levels": {" AD": ""}}}),
        json.dumps({"label": {"Levels": {"A\tD": ""}}}),
        json.dumps({"label": {"Levels": {"A\x01": ""}}}),
        json.dumps({"label": {"Levels": {"AD": "x\x1f"}}}),
        json.dumps({"label": {"Levels": {"AD": ""}, "Description": "\x00"}}),
        json.dumps({"label": {"Levels": {"A\ufffe": ""}}}),
        json.dumps({"label": {"Levels": {"AD": ""}, "Description": 3}}),
    ],
)
def test_invalid_classes_file(tmp_path, content):
    (tmp_path / LABELS_JSON).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=r"^Label classes (file is|are) invalid\.$"):
        read_classes(tmp_path)


def test_invalid_utf8_tsv(tmp_path):
    write_files(tmp_path, "")
    (tmp_path / LABELS_TSV).write_bytes(b"participant_id\tsession_id\tlabel\n\xff\t\t\n")
    with pytest.raises(ValueError, match=r"^Label table is not valid UTF-8\.$") as info:
        read_labels(tmp_path)
    assert info.value.__cause__ is None


def test_missing_files_have_fixed_messages(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"^Label classes file not found\.$"):
        read_labels(tmp_path)
    (tmp_path / LABELS_JSON).write_text(json.dumps({"label": {"Levels": CLASSES}}), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match=r"^Label table not found\.$"):
        read_labels(tmp_path)


@pytest.mark.parametrize("existing", [LABELS_TSV, LABELS_JSON])
def test_never_overwrites(tmp_path, existing):
    (tmp_path / existing).write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match=r"^Label table already exists\.$"):
        write_labels(make_table(), tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == [existing]
    assert (tmp_path / existing).read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "overrides",
    [
        {"classes": {"A\ud800": ""}},
        {"classes": {"AD": "x\ud800"}},
        {"description": "\udcff"},
    ],
)
def test_unencodable_text_is_rejected_before_writing(tmp_path, overrides):
    with pytest.raises(ValueError, match=r"^Label classes are invalid\.$") as info:
        make_table(**overrides)
    assert "\ud800" not in str(info.value) and "\udcff" not in str(info.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("levels", ['{"A\\ud800": ""}', '{"AD": "\\udcff"}'])
def test_unencodable_classes_file_is_rejected(tmp_path, levels):
    (tmp_path / LABELS_JSON).write_text(f'{{"label": {{"Levels": {levels}}}}}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"^Label classes are invalid\.$"):
        read_classes(tmp_path)


def test_unexpected_write_error_leaves_no_files(tmp_path):
    table = make_table()
    object.__setattr__(table, "description", "x\ud800")  # bypasses validation
    with pytest.raises(ValueError, match=r"^Label table could not be written\.$") as info:
        write_labels(table, tmp_path)
    assert info.value.__cause__ is None
    assert list(tmp_path.iterdir()) == []


def test_overwrite_replaces_both_files(tmp_path):
    write_labels(make_table(), tmp_path)
    updated = make_table(labels={("01", None): "CN"})
    write_labels(updated, tmp_path, overwrite=True)
    assert read_labels(tmp_path) == updated
    assert sorted(p.name for p in tmp_path.iterdir()) == [LABELS_JSON, LABELS_TSV]


def test_failed_overwrite_keeps_previous_table(tmp_path):
    write_labels(make_table(), tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    table = make_table()
    object.__setattr__(table, "description", "x\ud800")  # bypasses validation
    with pytest.raises(ValueError, match=r"^Label table could not be written\.$"):
        write_labels(table, tmp_path, overwrite=True)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_write_failure_leaves_nothing(tmp_path):
    with pytest.raises(OSError, match=r"^Label table could not be written\.$"):
        write_labels(make_table(), tmp_path / "missing")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"classes": {}},
        {"classes": {"": ""}},
        {"labels": {("01", None): "MCI"}},
        {"labels": {("0_1", None): "AD"}},
        {"labels": {("01", ""): "AD"}},
        {"description": None},
    ],
)
def test_table_validation(overrides):
    with pytest.raises(ValueError):
        make_table(**overrides)


def test_table_does_not_share_input_dicts():
    classes, labels = dict(CLASSES), {("01", None): "AD"}
    table = LabelTable(classes, labels)
    classes["X"], labels[("02", None)] = "", "AD"
    assert table.classes == CLASSES and table.labels == {("01", None): "AD"}


def test_no_ids_labels_or_paths_in_errors_or_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    secret_dir = tmp_path / "Doe_John"
    secret_dir.mkdir()
    write_files(secret_dir, HEADER + "sub-SECRET1\tses-01\tSECRETCLASS\n")
    with pytest.raises(ValueError) as info:
        read_labels(secret_dir)
    for secret in ("SECRET1", "SECRETCLASS", "Doe_John"):
        assert secret not in str(info.value) and secret not in caplog.text
