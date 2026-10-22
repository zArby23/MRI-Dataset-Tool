import json
import weakref
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.services import dataset_report as service
from mri_dataset_tool.application.services.dataset import export_dataset
from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.dataset.labels import LabelTable, write_labels

SECRETS = ("SECRETNAME", "1.2.840.99", "19700101", "private", "sub-")
NAMES = ["dataset_report.json", "dataset_report.md", "dataset_report.xml", "dataset_report.xlsx"]


def _series(modality="T1w", shape=(3, 4, 5)) -> MRISeries:
    volume = np.arange(1, np.prod(shape) + 1, dtype=np.float32).reshape(shape)
    return MRISeries(
        series_uid="1.2.840.99.1",
        modality=modality,
        volume=volume,
        metadata={
            "shape": shape,
            "voxel_size": (1.0, 1.0, 1.0),
            "affine": np.eye(4),
            "orientation": ("R", "A", "S"),
            "PatientName": "SECRETNAME",
            "sidecar": {"RepetitionTime": 2.0, "AcquisitionDateTime": "19700101T1010", "PatientName": "SECRETNAME"},
        },
    )


def _dataset(tmp_path: Path, labels=True, pipeline=True, subject="01") -> Path:
    root = tmp_path / "ds"
    studies = [
        MRIStudy("1.2.840.99.3", [_series(), _series("dwi", (3, 4, 5, 2))], subject_id=subject, session_id="1"),
        MRIStudy("1.2.840.99.4", [_series()], subject_id=subject, session_id="2"),
        MRIStudy("1.2.840.99.5", [_series()], subject_id="02", session_id="1"),
    ]
    config = {"pipeline": {"steps": [{"name": "validate"}]}}
    export_dataset(studies, root, pipeline=pipeline_from_config(config) if pipeline else None, config=config)
    if labels:
        table = LabelTable({"AD": "Alzheimer", "CN": "Control", "MCI": "Mild"},
                           {(subject, "1"): "AD", (subject, "2"): None, ("02", "1"): "CN"})
        write_labels(table, root)
    return root


def _report(tmp_path: Path, root: Path, name="out", **kwargs) -> dict:
    paths = report_dataset(root, tmp_path / name, **kwargs)
    assert [p.name for p in paths] == NAMES
    return json.loads(paths[0].read_text(encoding="utf-8"))


def test_report_reproduces_the_exported_dataset(tmp_path: Path) -> None:
    summary = _report(tmp_path, _dataset(tmp_path))
    assert (summary["participants"], summary["sessions"], summary["studies"], summary["series"]) == (2, 3, 3, 4)
    assert {name: stats["series"] for name, stats in summary["modalities"].items()} == {"T1w": 3, "dwi": 1}
    assert summary["modalities"]["T1w"]["intensity"]["finite_voxels"] == 3 * 60
    assert summary["modalities"]["T1w"]["intensity"]["max"] == 60.0
    assert summary["modalities"]["dwi"]["shape"] == [{"value": [3, 4, 5, 2], "count": 1}]
    assert summary["labels"] == {
        "classes": {
            "AD": {"participants": 1, "sessions": 1, "series": 2},
            "CN": {"participants": 1, "sessions": 1, "series": 1},
            "MCI": {"participants": 0, "sessions": 0, "series": 0},
        },
        "unlabeled_sessions": 1,
        "unlabeled_participants": 1,
    }
    assert summary["pipeline"] == {
        "studies": 3,
        "steps": [{
            "name": "validate", "version": "1", "params": {"modalities": None},
            "studies_ok": 3, "studies_failed": 0, "error_types": {}, "series_transformed": 4,
        }],
    }
    assert summary["warnings"] == [{"code": "UNLABELED_SESSIONS", "count": 1}]


def test_every_format_is_written_and_readable(tmp_path: Path) -> None:
    out = tmp_path / "out"
    report_dataset(_dataset(tmp_path), out)
    ET.parse(out / "dataset_report.xml")
    with zipfile.ZipFile(out / "dataset_report.xlsx") as archive:
        assert "xl/worksheets/sheet7.xml" in archive.namelist()  # Pipeline sheet
    markdown = (out / "dataset_report.md").read_text(encoding="utf-8")
    assert "## Pipeline" in markdown and '| validate | 1 | {"modalities": null} | 3 | 0 | {} | 4 |' in markdown


def test_without_labels_or_manifest(tmp_path: Path) -> None:
    out = tmp_path / "out"
    report_dataset(_dataset(tmp_path, labels=False, pipeline=False), out)
    summary = json.loads((out / "dataset_report.json").read_text(encoding="utf-8"))
    assert summary["labels"] is None and summary["pipeline"] is None and summary["warnings"] == []
    assert "No run manifest." in (out / "dataset_report.md").read_text(encoding="utf-8")


def test_unreadable_files_are_reported_and_the_rest_is_summarized(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    truncated = root / "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz"
    truncated.write_bytes(truncated.read_bytes()[:-30])  # this small file fails already when loaded
    garbage = root / "sub-03/anat/sub-03_T1w.nii.gz"
    garbage.parent.mkdir(parents=True)
    garbage.write_bytes(b"not a nifti")  # fails when loaded
    errors: list[tuple[Path, str]] = []
    summary = _report(tmp_path, root, on_error=lambda path, error: errors.append((path, type(error).__name__)))
    assert sorted(errors) == [(truncated, "ValueError"), (garbage, "ValueError")]
    assert (summary["studies"], summary["series"]) == (2, 3)
    assert {"code": "UNREADABLE_FILES", "count": 2} in summary["warnings"]


def test_a_volume_that_fails_to_read_skips_only_its_study(tmp_path: Path, monkeypatch) -> None:
    real = service.summarize_study

    def failing(study):
        if study.subject_id == "02":
            raise ValueError("Unable to read volume data.")  # what a truncated lazy .nii.gz gives
        return real(study)

    monkeypatch.setattr(service, "summarize_study", failing)
    root = _dataset(tmp_path)
    errors: list[Path] = []
    summary = _report(tmp_path, root, on_error=lambda path, error: errors.append(path))
    assert errors == [root / "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz"]
    assert (summary["studies"], summary["participants"]) == (2, 1)
    assert {"code": "UNREADABLE_FILES", "count": 1} in summary["warnings"]


def test_invalid_labels_and_manifest_are_reported(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    (root / "labels.json").write_text("{", encoding="utf-8")
    (root / "code/run_manifest.json").write_text("[]", encoding="utf-8")
    errors: list[Path] = []
    summary = _report(tmp_path, root, on_error=lambda path, error: errors.append(path))
    assert errors == [root / "labels.tsv", root / "code/run_manifest.json"]
    assert summary["labels"] is None and summary["pipeline"] is None
    codes = {w["code"] for w in summary["warnings"]}
    assert {"LABELS_UNREADABLE", "MANIFEST_UNREADABLE"} <= codes


def test_on_error_that_raises_does_not_stop_the_report(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    (root / "labels.json").write_text("{", encoding="utf-8")

    def boom(path, error):
        raise RuntimeError("callback")

    assert _report(tmp_path, root, on_error=boom)["labels"] is None


@pytest.mark.parametrize("relative", [".", "derivatives/report"])
def test_output_inside_the_dataset_is_rejected(tmp_path: Path, relative: str) -> None:
    root = _dataset(tmp_path)
    before = sorted(root.rglob("*"))
    with pytest.raises(ValueError, match=r"^Report directory must be outside the dataset\.$"):
        report_dataset(root, root / relative)
    assert sorted(root.rglob("*")) == before


def test_missing_dataset(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"^Dataset directory does not exist\.$"):
        report_dataset(tmp_path / "nope", tmp_path / "out")
    (tmp_path / "file").write_text("x")
    with pytest.raises(NotADirectoryError, match=r"^Dataset path is not a directory\.$"):
        report_dataset(tmp_path / "file", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_existing_report_is_not_overwritten(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "dataset_report.xml").write_text("previous", encoding="utf-8")
    with pytest.raises(FileExistsError, match=r"^Report file already exists\.$"):
        report_dataset(root, out)
    assert [p.name for p in out.iterdir()] == ["dataset_report.xml"]
    assert (out / "dataset_report.xml").read_text(encoding="utf-8") == "previous"


def test_a_failed_write_leaves_no_report(tmp_path: Path, monkeypatch) -> None:
    def fail(summary, path):
        raise OSError("Report file could not be written.")

    monkeypatch.setitem(service.REPORT_WRITERS, "dataset_report.xlsx", fail)
    with pytest.raises(OSError):
        report_dataset(_dataset(tmp_path), tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


def test_one_study_alive_at_a_time(tmp_path: Path, monkeypatch) -> None:
    root = _dataset(tmp_path)
    previous: list[weakref.ref] = []
    real = service.summarize_study

    def checking(study):
        assert all(ref() is None for ref in previous)
        previous.append(weakref.ref(study))
        return real(study)

    monkeypatch.setattr(service, "summarize_study", checking)
    assert _report(tmp_path, root)["studies"] == 3
    assert len(previous) == 3


def test_report_is_deterministic(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    report_dataset(root, tmp_path / "a")
    report_dataset(root, tmp_path / "b")
    for name in NAMES[:3]:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_no_phi_ids_or_paths_in_the_report(tmp_path: Path) -> None:
    root = _dataset(tmp_path, subject="SECRETNAME")
    out = tmp_path / "out"
    report_dataset(root, out)
    contents = [(out / name).read_bytes() for name in NAMES[:3]]
    with zipfile.ZipFile(out / "dataset_report.xlsx") as archive:
        contents += [archive.read(name) for name in archive.namelist()]
    for content in contents:
        for secret in (*SECRETS, str(tmp_path), tmp_path.as_posix()):
            assert secret.encode() not in content
