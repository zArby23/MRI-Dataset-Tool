"""``ingest_preview``: the GUI mapping table (preview, edits as ``--mapping`` rows, TSV save)."""

import logging
from pathlib import Path, PurePosixPath

import pytest

from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput
from mri_dataset_tool.application.services.dataset_ingest import MappingRow, load_mapping, plan_ingest
from mri_dataset_tool.application.services.ingest_preview import (
    PreviewRow,
    apply_edit,
    preview_ingest,
    write_mapping,
)
from test_anonymize_dicom_tree import PLANTED
from test_service_dataset_ingest import KEY_BYTES, _nifti, dicom_tree

CLASSES = {"AD": "", "CN": ""}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", KEY_BYTES.decode())


def _row(location: str, participant: str, session: str | None, suffix: str | None = "T1w") -> PreviewRow:
    return PreviewRow(PurePosixPath(location), suffix, "MATCHED" if suffix else "NO_MATCH", participant, session)


def test_preview_lists_every_series_with_its_decision_and_no_header_text(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    root = dicom_tree(tmp_path / "in")
    rows = preview_ingest("dicom", root)
    assert [(r.location.as_posix(), r.suffix, r.code) for r in sorted(rows, key=lambda r: r.location)] == [
        ("a/adc", None, "EXCLUDED"), ("a/t1", "T1w", "MATCHED"), ("b/flair", "FLAIR", "MATCHED"),
    ]
    assert rows == plan_ingest("dicom", root).decisions
    text = repr(rows) + caplog.text
    assert not [value for value in [*PLANTED, "PlantedDesc", "PlantedProto"] if value in text]
    assert not (tmp_path / "out").exists()


def test_dicom_edits_go_to_the_series_and_study_folders(tmp_path):
    root = dicom_tree(tmp_path / "in")
    rows = sorted(preview_ingest("dicom", root), key=lambda r: r.location)
    adc, t1 = rows[0], rows[1]
    mapping = apply_edit([], rows, "dicom", 0, "suffix", "dwi")
    mapping = apply_edit(mapping, rows, "dicom", 1, "participant", "P01")  # the study of a/t1 is folder "a"
    mapping = apply_edit(mapping, rows, "dicom", 1, "label", "AD", CLASSES)
    assert mapping == [MappingRow(PurePosixPath("a"), participant="P01", label="AD"),
                       MappingRow(PurePosixPath("a/adc"), suffix="dwi")]
    new = {r.location.as_posix(): r for r in preview_ingest("dicom", root, mapping, CLASSES)}
    assert (new["a/adc"].suffix, new["a/adc"].code, new["a/adc"].participant) == ("dwi", "MAPPED", "P01")
    assert (new["a/t1"].participant, new["a/t1"].label) == ("P01", "AD")
    assert new["b/flair"].participant == t1.participant == adc.participant  # untouched study, same patient
    assert apply_edit(mapping, rows, "dicom", 1, "participant", "") == [
        MappingRow(PurePosixPath("a"), label="AD"), MappingRow(PurePosixPath("a/adc"), suffix="dwi"),
    ]  # an empty value clears the cell; a row with no value left is dropped
    assert apply_edit([MappingRow(PurePosixPath("a/adc"), suffix="dwi")], rows, "dicom", 0, "suffix", "") == []


def test_nifti_edits_go_to_the_file_and_group_files_into_one_study(tmp_path):
    root = tmp_path / "in"
    for name in ("x_T1.nii.gz", "y_FLAIR.nii.gz"):
        _nifti(root / name)
    rows = preview_ingest("nifti", root)
    mapping = []
    for index in range(2):
        mapping = apply_edit(mapping, rows, "nifti", index, "participant", "P01")
    assert [row.path.as_posix() for row in mapping] == ["x_T1.nii.gz", "y_FLAIR.nii.gz"]
    plan = plan_ingest("nifti", root, mapping=mapping)
    assert [(subject, session, len(files)) for subject, session, files in plan.entries] == [("P01", None, 2)]


@pytest.mark.parametrize(
    ("column", "value", "classes", "message"),
    [
        ("participant", "P-01", None, "Invalid --mapping."),
        ("session", "ses-1", None, "Invalid --mapping."),
        ("suffix", "bold", None, "Invalid --mapping."),
        ("label", "AD", None, "Mapping labels need --classes."),
        ("label", "MCI", CLASSES, "Mapping label is not one of --classes."),
        ("location", "x", None, "Invalid --mapping."),
    ],
)
def test_invalid_edits_are_rejected_with_fixed_text(column, value, classes, message):
    rows = [_row("a/t1", "s1", "v1")]
    with pytest.raises(InvalidBuildInput) as raised:
        apply_edit([], rows, "dicom", 0, column, value, classes)
    assert str(raised.value) == message


def test_edits_that_a_folder_cannot_express_are_rejected():
    shared = [_row("s", "p1", "v1"), _row("s", "p1", "v1", "T2w")]  # two series in one folder
    with pytest.raises(InvalidBuildInput, match="Several series share this folder."):
        apply_edit([], shared, "dicom", 0, "suffix", "FLAIR")
    nested = [_row("a", "p1", "v1"), _row("a/b", "p2", "v2")]  # study p1/v1 is "a", which holds study p2/v2
    with pytest.raises(InvalidBuildInput, match="The study folder also holds other studies."):
        apply_edit([], nested, "dicom", 0, "participant", "P01")
    assert apply_edit([], nested, "dicom", 1, "participant", "P02") == [MappingRow(PurePosixPath("a/b"), "P02")]


def test_preview_checks_mapping_labels_against_the_classes(tmp_path):
    root = dicom_tree(tmp_path / "in")
    mapping = [MappingRow(PurePosixPath("a"), label="AD")]
    with pytest.raises(InvalidBuildInput, match="Mapping labels need --classes."):
        preview_ingest("dicom", root, mapping)
    with pytest.raises(InvalidBuildInput, match="Mapping label is not one of --classes."):
        preview_ingest("dicom", root, mapping, {"CN": ""})


def test_write_mapping_round_trips_and_never_overwrites(tmp_path):
    root = dicom_tree(tmp_path / "in")
    mapping = [MappingRow(PurePosixPath("a"), "P01", "", "", "AD"), MappingRow(PurePosixPath("a/adc"), suffix="dwi")]
    path = tmp_path / "map.tsv"
    write_mapping(mapping, path, root, CLASSES)
    assert load_mapping(path, root, CLASSES) == mapping
    assert path.read_text(encoding="utf-8").splitlines()[0] == "path\tparticipant\tsession\tsuffix\tlabel"
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_mapping([], path, root, CLASSES)
    assert path.read_bytes() == before


def test_write_mapping_removes_a_table_that_does_not_read_back(tmp_path):
    root = dicom_tree(tmp_path / "in")
    with pytest.raises(InvalidBuildInput, match="Mapping paths not found in the input: 1."):
        write_mapping([MappingRow(PurePosixPath("gone"), "P01")], tmp_path / "map.tsv", root)
    assert not (tmp_path / "map.tsv").exists()


def test_write_mapping_leaves_no_partial_table_when_the_write_fails(tmp_path, monkeypatch):
    root = dicom_tree(tmp_path / "in")

    class Broken:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def write(self, text):
            self.handle.write(text[:5])
            raise OSError("disk full")

    original = Path.open
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: Broken(original(self, *a, **k)))
    with pytest.raises(OSError):
        write_mapping([MappingRow(PurePosixPath("a"), "P01")], tmp_path / "map.tsv", root)
    monkeypatch.undo()
    assert not (tmp_path / "map.tsv").exists()


def test_write_mapping_never_removes_what_it_did_not_create(tmp_path):
    root = dicom_tree(tmp_path / "in")
    folder = tmp_path / "taken.tsv"  # open("x") fails before creating anything
    folder.mkdir()
    (folder / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        write_mapping([MappingRow(PurePosixPath("a"), "P01")], folder, root)
    assert (folder / "keep.txt").read_text(encoding="utf-8") == "x"
    other = tmp_path / "other.tsv"
    other.write_text("someone else's", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_mapping([], other, root)
    assert other.read_text(encoding="utf-8") == "someone else's"
