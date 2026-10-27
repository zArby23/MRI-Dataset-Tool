"""``dataset_outputs``: existing ML exports, a new or empty report folder and the report warnings."""

import json
from pathlib import Path

import pytest

from mri_dataset_tool.application.services.dataset_outputs import (
    REPORT_FILES,
    ml_exports_exist,
    report_warnings,
    write_report,
)
from mri_dataset_tool.presentation.cli.main import main
from test_cli_dataset import bids_input
from test_gui_run import project  # noqa: F401  (fixture: cwd with config/, key, log level restored)


def _built(project: Path, *extra: str) -> Path:
    bids_input(project / "in")  # PATIENT03 holds a NaN: 2 of 3 studies exported
    assert main(["--quiet", "dataset", "build", "in", "--output-dir", "out", "--config", "config/run.yaml",
                 "--ratios", "1", "0", "0", *extra]) == 0
    return project / "out" / "dataset"


def test_ml_exports_exist_after_a_build_without_classes_only(project):
    assert ml_exports_exist(_built(project))
    (project / "out2").mkdir()
    assert main(["--quiet", "dataset", "build", "in", "--output-dir", "out2", "--config", "config/run.yaml",
                 "--classes", "AD", "CN"]) == 0  # labels incomplete: the ML exports are skipped
    assert not ml_exports_exist(project / "out2" / "dataset")


def test_write_report_matches_the_cli_report(project):
    dataset = _built(project)
    names, warnings = write_report(dataset, project / "gui_report")
    assert names == list(REPORT_FILES) and warnings == report_warnings(project / "gui_report")
    assert main(["--quiet", "dataset", "report", str(dataset), "cli_report"]) == 0
    gui, cli = (json.loads((project / d / "dataset_report.json").read_text(encoding="utf-8"))
                for d in ("gui_report", "cli_report"))
    assert gui == cli
    for name in ("dataset_report.md", "dataset_report.xml"):  # XLSX bytes carry the save date
        assert (project / "gui_report" / name).read_bytes() == (project / "cli_report" / name).read_bytes()


def test_the_report_folder_must_be_new_or_empty_and_outside_the_dataset(project):
    dataset = _built(project)
    (project / "empty").mkdir()
    assert write_report(dataset, project / "empty")[0] == list(REPORT_FILES)
    (project / "busy").mkdir()
    (project / "busy" / ".hidden").write_text("", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_report(dataset, project / "busy")
    assert [p.name for p in (project / "busy").iterdir()] == [".hidden"]
    with pytest.raises(ValueError):
        write_report(dataset, dataset / "report")
    assert not (dataset / "report").exists()


def test_report_warnings_name_unreadable_files_labels_and_manifest(project):
    dataset = _built(project, "--classes", "AD", "CN")
    next(dataset.rglob("*.nii.gz")).write_bytes(b"not a nifti")
    (dataset / "labels.json").write_text("{", encoding="utf-8")
    (dataset / "code" / "run_manifest.json").write_text("{", encoding="utf-8")
    errors = []
    _, warnings = write_report(dataset, project / "report", lambda path, error: errors.append(type(error).__name__))
    assert {code: warnings[code] for code in ("UNREADABLE_FILES", "LABELS_UNREADABLE", "MANIFEST_UNREADABLE")} == {
        "UNREADABLE_FILES": 1, "LABELS_UNREADABLE": 1, "MANIFEST_UNREADABLE": 1,
    }
    assert len(errors) == 3
