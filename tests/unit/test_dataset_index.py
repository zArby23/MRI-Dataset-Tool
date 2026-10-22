import csv
import json
from pathlib import Path

import numpy as np
import pytest

from mri_dataset_tool.application.services.dataset import write_ml_exports
from mri_dataset_tool.application.services.labels import finalize_labels
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.dataset import bids_writer
from mri_dataset_tool.infrastructure.dataset.bids_writer import BIDSDatasetWriter
from mri_dataset_tool.infrastructure.dataset.index import ImageEntry, scan_images
from mri_dataset_tool.infrastructure.dataset.labels import LabelTable, write_labels

EXPORTS = ("dataset_index.csv", "datalist.json", "splits.tsv", "splits.json")
CLASSES = {"AD": "Alzheimer", "CN": "Control"}


def _touch(root: Path, *relatives: str) -> Path:
    for relative in relatives:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return root


def _dataset(root: Path, participants: int = 8) -> Path:
    """Two sessions per participant, a T1w each and two T2w runs in ses-1."""
    files = []
    for i in range(participants):
        p = f"p{i:02d}"
        files += [f"sub-{p}/ses-1/anat/sub-{p}_ses-1_T1w.nii.gz", f"sub-{p}/ses-2/anat/sub-{p}_ses-2_T1w.nii.gz"]
        files += [f"sub-{p}/ses-1/anat/sub-{p}_ses-1_run-{r}_T2w.nii.gz" for r in (1, 2)]
    _touch(root, *files, "dataset_description.json", "sub-p00/ses-1/anat/sub-p00_ses-1_T1w.json", ".git/x.nii.gz")
    return root


def _rows(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def test_scan_images_reads_names_only(tmp_path: Path) -> None:
    root = _touch(tmp_path, "sub-a/anat/sub-a_T1w.nii.gz", "sub-a/ses-1/dwi/sub-a_ses-1_run-2_dwi.nii.gz")
    assert scan_images(root) == [
        ImageEntry("a", None, "T1w", None, "sub-a/anat/sub-a_T1w.nii.gz"),
        ImageEntry("a", "1", "dwi", 2, "sub-a/ses-1/dwi/sub-a_ses-1_run-2_dwi.nii.gz"),
    ]


@pytest.mark.parametrize(
    "relative",
    [
        "sub-a/anat/sub-b_T1w.nii.gz",
        "sub-a/func/sub-a_T1w.nii.gz",
        "sub-a/anat/sub-a_T1w.nii",
        "sub-a/anat/sub-a_acq-x_T1w.nii.gz",
        "sub-a/anat/sub-a_run-01_T1w.nii.gz",
        "sub-a/anat/sub-a_bold.nii.gz",
        "code/x.nii.gz",
        "sub-a_T1w.nii.gz",
    ],
)
def test_files_outside_the_layout_are_rejected(tmp_path: Path, relative) -> None:
    with pytest.raises(ValueError, match=r"^Dataset contains a file outside the BIDS layout\.$"):
        scan_images(_touch(tmp_path, relative))


def test_dataset_without_images(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"^No dataset images were found\.$"):
        write_ml_exports(_touch(tmp_path, "README"))
    with pytest.raises(FileNotFoundError, match=r"^Dataset directory not found\.$"):
        write_ml_exports(tmp_path / "missing")
    with pytest.raises(NotADirectoryError, match=r"^Dataset path is not a directory\.$"):
        write_ml_exports(tmp_path / "README")


def test_exports_without_labels(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    assert write_ml_exports(root) == [root / name for name in EXPORTS]
    index = _rows(root / "dataset_index.csv")
    assert len(index) == 32 and list(index[0]) == ["participant_id", "session_id", "suffix", "run", "image", "label", "split"]
    assert index[0] == {
        "participant_id": "sub-p00", "session_id": "ses-1", "suffix": "T1w", "run": "",
        "image": "sub-p00/ses-1/anat/sub-p00_ses-1_T1w.nii.gz", "label": "", "split": index[0]["split"],
    }
    assert [r["image"] for r in index] == sorted(r["image"] for r in index)  # byte order, not Windows order
    assert all((root / row["image"]).is_file() and not Path(row["image"]).is_absolute() for row in index)
    datalist = json.loads((root / "datalist.json").read_text(encoding="utf-8"))
    assert set(datalist) == {"training", "validation", "testing"}
    assert sum(len(v) for v in datalist.values()) == 32 and "label" not in datalist["training"][0]
    summary = json.loads((root / "splits.json").read_text(encoding="utf-8"))
    assert summary["seed"] == 0 and summary["ratios"] == {"training": 0.7, "validation": 0.15, "testing": 0.15}
    assert summary["participants"] == {"training": 6, "validation": 1, "testing": 1} and not summary["stratified"]
    assert summary["labels_finalized"] is None
    splits = _rows(root / "splits.tsv", "\t")
    assert [r["participant_id"] for r in splits] == [f"sub-p{i:02d}" for i in range(8)]


def test_no_leakage_and_coherent_files(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    write_ml_exports(root, (0.5, 0.25, 0.25), 7)
    split_of = {r["participant_id"]: r["split"] for r in _rows(root / "splits.tsv", "\t")}
    for row in _rows(root / "dataset_index.csv"):
        assert row["split"] == split_of[row["participant_id"]]  # every session and run of a participant
    datalist = json.loads((root / "datalist.json").read_text(encoding="utf-8"))
    for split, items in datalist.items():
        for item in items:
            assert split_of[item["image"].split("/")[0]] == split
    assert json.loads((root / "splits.json").read_text(encoding="utf-8"))["seed"] == 7


def test_stratified_exports_with_unlabeled(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    labels = {(f"p{i:02d}", s): ("AD" if i < 4 else "CN") for i in range(7) for s in ("1", "2")}
    labels[("p03", "2")] = None  # an unlabeled session of a labelled participant
    write_labels(LabelTable(CLASSES, labels), root)  # p07 is not in the table at all
    write_ml_exports(root, allow_unfinalized=True)
    summary = json.loads((root / "splits.json").read_text(encoding="utf-8"))
    assert summary["stratified"] and summary["unlabeled_participants"] == ["sub-p07"]
    assert summary["labels_finalized"] is False
    assert summary["warnings"] == []
    splits = {r["participant_id"]: r["split"] for r in _rows(root / "splits.tsv", "\t")}
    assert "sub-p07" not in splits
    for members in (range(4), range(4, 7)):
        assert {splits[f"sub-p{i:02d}"] for i in members} == {"training", "validation", "testing"}
    datalist = json.loads((root / "datalist.json").read_text(encoding="utf-8"))
    assert datalist["classes"] == ["AD", "CN"]
    labelled = [item for split in ("training", "validation", "testing") for item in datalist[split]]
    assert all(item["label"] in CLASSES for item in labelled) and len(labelled) == 27
    assert sorted(i["image"] for i in datalist["unlabeled"]) == sorted(
        ["sub-p03/ses-2/anat/sub-p03_ses-2_T1w.nii.gz"] + [r["image"] for r in _rows(root / "dataset_index.csv") if r["participant_id"] == "sub-p07"]
    )
    index = {r["image"]: r for r in _rows(root / "dataset_index.csv")}
    assert index["sub-p03/ses-2/anat/sub-p03_ses-2_T1w.nii.gz"]["label"] == ""
    assert index["sub-p03/ses-2/anat/sub-p03_ses-2_T1w.nii.gz"]["split"] == splits["sub-p03"]
    assert index["sub-p07/ses-1/anat/sub-p07_ses-1_T1w.nii.gz"]["split"] == ""


def test_few_participants_warning_is_recorded(tmp_path: Path) -> None:
    root = _dataset(tmp_path, 5)
    write_labels(LabelTable(CLASSES, {("p00", "1"): "AD"} | {(f"p{i:02d}", "1"): "CN" for i in range(1, 5)}), root)
    write_ml_exports(root, allow_unfinalized=True)
    warnings = json.loads((root / "splits.json").read_text(encoding="utf-8"))["warnings"]
    assert warnings == [{"code": "FEW_PARTICIPANTS", "participants": 1, "stratum": ["AD"]}]


def test_all_participants_unlabeled(tmp_path: Path) -> None:
    root = _dataset(tmp_path, 2)
    write_labels(LabelTable(CLASSES, {("p00", "1"): None, ("p01", "1"): None}), root)
    write_ml_exports(root, allow_unfinalized=True)
    datalist = json.loads((root / "datalist.json").read_text(encoding="utf-8"))
    assert [len(datalist[s]) for s in ("training", "validation", "testing", "unlabeled")] == [0, 0, 0, 8]
    assert (root / "splits.tsv").read_text(encoding="utf-8") == "participant_id\tsplit\n"


@pytest.mark.parametrize(("ratios", "seed"), [((0.5, 0.5, 0.5), 0), ((0.7, 0.15, 0.15), "0")])
def test_invalid_parameters_write_nothing(tmp_path: Path, ratios, seed) -> None:
    root = _dataset(tmp_path)
    with pytest.raises(ValueError):
        write_ml_exports(root, ratios, seed)
    assert not any((root / name).exists() for name in EXPORTS)


def test_never_overwrites_and_is_all_or_nothing(tmp_path: Path, monkeypatch) -> None:
    root = _dataset(tmp_path)
    (root / "splits.json").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match=r"^Dataset file already exists\.$"):
        write_ml_exports(root)
    assert (root / "splits.json").read_text(encoding="utf-8") == "keep"
    assert not any((root / name).exists() for name in EXPORTS[:3])
    (root / "splits.json").unlink()

    real, calls = bids_writer._write_bytes, []

    def fail_last(path, data):
        calls.append(path)
        if len(calls) == 4:
            raise OSError("Dataset file could not be written.")
        real(path, data)

    monkeypatch.setattr(bids_writer, "_write_bytes", fail_last)
    with pytest.raises(OSError):
        write_ml_exports(root)
    assert not any((root / name).exists() for name in EXPORTS)
    assert not list(root.glob(".*.tmp"))


def test_deterministic(tmp_path: Path) -> None:
    def run(root: Path) -> dict[str, bytes]:
        _dataset(root)
        write_labels(LabelTable(CLASSES, {(f"p{i:02d}", "1"): "AD" if i % 2 else "CN" for i in range(8)}), root)
        write_ml_exports(root, allow_unfinalized=True)
        return {name: (root / name).read_bytes() for name in EXPORTS}

    assert run(tmp_path / "one") == run(tmp_path / "two")


def test_on_a_dataset_written_by_the_writer_without_private_data(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    writer = BIDSDatasetWriter(root)
    for subject in ("a1", "b2", "c3"):
        volume = np.ones((2, 2, 2), np.float32)
        series = MRISeries(modality="T1w", volume=volume, metadata={"shape": (2, 2, 2), "affine": np.eye(4)})
        writer.add_study(MRIStudy(study_uid=None, series=[series, series], subject_id=subject, session_id="01"))
    writer.finalize()
    write_ml_exports(root)
    images = [r["image"] for r in _rows(root / "dataset_index.csv")]
    assert images[:2] == ["sub-a1/ses-01/anat/sub-a1_ses-01_run-1_T1w.nii.gz", "sub-a1/ses-01/anat/sub-a1_ses-01_run-2_T1w.nii.gz"]
    for name in EXPORTS:
        text = (root / name).read_text(encoding="utf-8")
        assert str(tmp_path) not in text and str(tmp_path.as_posix()) not in text and "Users" not in text


def _labelled_dataset(root: Path) -> Path:
    _dataset(root, 6)
    write_labels(LabelTable(CLASSES, {(f"p{i:02d}", s): "AD" if i < 3 else "CN" for i in range(6) for s in ("1", "2")}), root)
    return root


def _assert_rejected(root: Path) -> None:
    with pytest.raises(ValueError) as info:
        write_ml_exports(root)
    assert str(info.value) == "Labels are not finalized."
    assert not any((root / name).exists() for name in EXPORTS)


def test_unfinalized_labels_are_rejected_by_default(tmp_path: Path) -> None:
    _assert_rejected(_labelled_dataset(tmp_path))


@pytest.mark.parametrize("closure", ["not json", "[]", '{"other": 1}', '{"sha256": "0"}'])
def test_invalid_closure_is_not_finalized(tmp_path: Path, closure) -> None:
    root = _labelled_dataset(tmp_path)
    (root / "labels_final.json").write_text(closure, encoding="utf-8")
    _assert_rejected(root)


def test_closure_is_stale_after_editing_the_labels(tmp_path: Path) -> None:
    root = _labelled_dataset(tmp_path)
    finalize_labels(root)
    tsv = root / "labels.tsv"
    tsv.write_text(tsv.read_text(encoding="utf-8").replace("sub-p00	ses-1	AD", "sub-p00	ses-1	CN"), encoding="utf-8")
    _assert_rejected(root)


def test_valid_closure_is_exported_and_recorded(tmp_path: Path) -> None:
    root = _labelled_dataset(tmp_path)
    finalize_labels(root)
    write_ml_exports(root)
    summary = json.loads((root / "splits.json").read_text(encoding="utf-8"))
    assert summary["labels_finalized"] is True and summary["stratified"]


def test_allow_unfinalized_exports_and_records_it(tmp_path: Path) -> None:
    root = _labelled_dataset(tmp_path)
    write_ml_exports(root, allow_unfinalized=True)
    assert json.loads((root / "splits.json").read_text(encoding="utf-8"))["labels_finalized"] is False


def test_dataset_without_labels_needs_no_closure(tmp_path: Path) -> None:
    root = _dataset(tmp_path, 3)
    write_ml_exports(root)
    assert json.loads((root / "splits.json").read_text(encoding="utf-8"))["labels_finalized"] is None


@pytest.mark.parametrize(("lost", "message"), [("labels.tsv", "Label table not found."), ("labels.json", "Label classes file not found.")])
def test_label_files_without_their_pair_block_the_exports(tmp_path: Path, lost, message) -> None:
    """A renamed labels.tsv must not turn a labelled dataset into an unlabelled export."""
    root = _labelled_dataset(tmp_path)
    finalize_labels(root)
    (root / lost).rename(root / f"{lost}.bak")
    with pytest.raises(FileNotFoundError) as info:
        write_ml_exports(root, allow_unfinalized=True)
    assert str(info.value) == message
    assert not any((root / name).exists() for name in EXPORTS)
