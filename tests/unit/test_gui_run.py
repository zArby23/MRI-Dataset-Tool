"""GUI step 4 (run): ``build_dataset`` in the worker with the real services, CLI equivalence, failures per
stage, PHI sweep and a Tk smoke test (skipped without a display)."""

import logging
import re
import shutil
import tkinter as tk
from pathlib import Path

import pytest

from mri_dataset_tool.application.services import dataset_build
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main
from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Done, Failed, Status, StudyFailed
from test_cli_dataset import SECRETS, bids_input
from test_service_dataset_ingest import KEY_BYTES, _nifti, dicom_tree

REPO = Path(__file__).resolve().parents[2]
RUN_CONFIG = "pipeline:\n  steps:\n    - name: validate\n    - name: anonymize\n"
DICOM_SECRETS = ["PAT12345", "Doe^John", "PlantedDesc", "PlantedProto"]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """cwd with its own config/ for the CLI (the GUI reads the project's config/). The CLI changes the root
    log level (``--quiet``): it is restored afterwards."""
    monkeypatch.setenv("MRI_ANON_KEY", KEY_BYTES.decode())
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / "config" / "default.yaml", tmp_path / "config" / "default.yaml")
    (tmp_path / "config" / "run.yaml").write_text(RUN_CONFIG, encoding="utf-8")
    root = logging.getLogger()
    level = root.level
    yield tmp_path
    _common.configure_output()
    root.setLevel(level)


def _ready(project: Path, fmt: str, classes: str = "") -> Controller:
    controller = Controller()
    assert controller.set_input(str(project / "in"), fmt, str(project / "gui")).ok
    assert controller.set_config(str(project / "config" / "run.yaml"), False, classes, ["1", "0", "0"], "0").ok
    if fmt != "bids":
        assert controller.start_task(controller.preview_task())
        controller.worker.join(30)
        assert isinstance(controller.poll()[-1], Done)
        controller.preview_finished()
    controller.step = "run"
    return controller


def _run(controller: Controller) -> list:
    assert controller.start_task(controller.run_task())
    controller.worker.join(120)
    events = controller.poll()
    if isinstance(events[-1], Done):
        controller.run_finished()
    return events


def _cli_summary(capsys) -> dict[str, int]:
    out = capsys.readouterr().out
    match = re.search(r"Studies written: (\d+)  series: (\d+)  participants: (\d+)  errors: (\d+)", out)
    return dict(zip(("studies", "series", "participants", "errors"), map(int, match.groups())))


def _names(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.suffix in (".gz", ".json", ".tsv")}


def test_bids_run_matches_the_cli_and_leaks_nothing(project, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    bids_input(project / "in")  # PATIENT03 holds a NaN: validate fails that study and the batch goes on
    controller = _ready(project, "bids")
    events = _run(controller)
    assert events[-1] == Done({"studies": 2, "series": 2, "participants": 2, "errors": 1, "report_files": 4})
    assert StudyFailed("ValueError") in events
    assert controller.state.dataset_root == project / "gui" / "dataset" and controller.go_next() == "labels"
    lines = [line for event in events if isinstance(event, Status) for line in controller.status_lines(event)]
    assert controller.text("EV_exported", studies=2, series=2, participants=2, errors=1) in lines

    main(["dataset", "build", "in", "--output-dir", "cli", "--config", "config/run.yaml", "--ratios", "1", "0", "0"])
    assert _cli_summary(capsys) == {k: v for k, v in events[-1].summary.items() if k != "report_files"}
    assert _names(project / "gui" / "dataset") == _names(project / "cli" / "dataset")  # same key, same pseudonyms

    texts = [repr(events), *lines, caplog.text]
    leaks = [s for s in [*SECRETS, str(project), project.as_posix()] for text in texts if s in text]
    assert leaks == []


def test_dicom_run_uses_the_mapping_and_shows_the_fixed_warnings(project, capsys):
    dicom_tree(project / "in")  # one patient, studies a (T1 + ADC map) and b (FLAIR)
    controller = _ready(project, "dicom", "AD\nCN")
    for location, label in (("a/t1", "AD"), ("b/flair", "CN")):
        index = next(i for i, row in enumerate(controller.state.preview) if row.location.as_posix() == location)
        assert controller.edit_mapping(index, "label", label).ok
    events = _run(controller)
    assert events[-1].summary["studies"] == 2 and events[-1].summary["participants"] == 1
    lines = [line for event in events if isinstance(event, Status) for line in controller.status_lines(event)]
    assert controller.text("WARN_UNMAPPED_SERIES", codes="EXCLUDED 1") in lines
    assert controller.text("EV_mapping_labels_applied", rows=2) in lines
    assert controller.text("EV_labels_finalized", labels=2) in lines
    assert (project / "gui" / "dataset" / "labels_final.json").is_file()
    texts = [repr(events), *lines]
    assert not [s for s in [*DICOM_SECRETS, "a/t1", "b/flair"] for text in texts if s in text]


def test_loose_nifti_run_matches_the_cli(project, capsys):
    for name in ("x_T1.nii.gz", "y_T2.nii.gz", "notes.nii.gz"):
        _nifti(project / "in" / name)
    controller = _ready(project, "nifti")
    events = _run(controller)
    lines = [line for event in events if isinstance(event, Status) for line in controller.status_lines(event)]
    assert controller.text("WARN_UNMAPPED_SERIES", codes="NO_MATCH 1") in lines
    capsys.readouterr()
    main(["--quiet", "dataset", "build", "in", "--format", "nifti", "--output-dir", "cli", "--config", "config/run.yaml"])
    out = capsys.readouterr().out
    assert "WARNING UNMAPPED_SERIES: {'NO_MATCH': 1}" in out
    assert _names(project / "gui" / "dataset") == _names(project / "cli" / "dataset")


@pytest.mark.parametrize(
    ("stage", "target"),
    [("export", "export_dataset"), ("labels", "write_label_template"), ("ml exports", "write_ml_exports"),
     ("report", "report_dataset")],
)
def test_a_failed_stage_is_reported_by_stage_and_type(project, monkeypatch, caplog, stage, target):
    caplog.set_level(logging.DEBUG)
    bids_input(project / "in")

    def broken(*args, **kwargs):
        raise OSError(f"PlantedSecret {project}")

    monkeypatch.setattr(dataset_build, target, broken)
    controller = _ready(project, "bids", "AD\nCN" if stage != "export" else "")
    if stage == "ml exports":
        controller.state.classes = None  # without classes the ML exports are written right away
    events = _run(controller)
    assert events[-1] == Failed("STAGE_FAILED", "OSError", stage)
    assert controller.failure_text(events[-1]) == controller.text("STAGE_FAILED", stage=stage, error_type="OSError")
    assert controller.state.dataset_root is None and not controller.can_go_next()
    assert "Planted" not in repr(events) + caplog.text


def test_an_output_filled_after_step_1_is_not_used(project):
    bids_input(project / "in")
    controller = _ready(project, "bids")
    (project / "gui").mkdir()
    (project / "gui" / "other.txt").write_text("x", encoding="utf-8")
    events = _run(controller)
    assert events[-1] == Failed("OUTPUT_EXISTS", "FileExistsError")
    assert [p.name for p in (project / "gui").iterdir()] == ["other.txt"]


def test_a_change_before_the_run_needs_a_new_run(project):
    bids_input(project / "in")
    controller = _ready(project, "bids")
    _run(controller)
    controller.reopen("config")
    assert controller.state.dataset_root is None


# --- Tk smoke ---------------------------------------------------------------------------------------


def test_run_view_shows_progress_lines_and_unlocks_labels(project):
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App

    bids_input(project / "in")
    controller = _ready(project, "bids")
    controller.step = "run"
    app = App(controller)
    app.withdraw()
    try:
        app.refresh()
        view = app.views["run"]
        view.run()
        assert str(view._run.cget("state")) == "disabled" and str(app._back.cget("state")) == "disabled"
        controller.worker.join(120)
        app._poll()
        lines = view.log.get(0, "end")
        assert controller.text("RUN_DONE") in lines and controller.text("RUN_ERRORS", counts="ValueError 1") in lines
        assert str(app._next.cget("state")) == "normal" and str(view._run.cget("state")) == "disabled"
        app._language.set("en")
        app._set_language()
        assert "Done." in view.log.get(0, "end")
    finally:
        app.destroy()
