"""GUI step 6 (exports and report): controller with the real services, equivalence with the CLI, PHI
sweep and a Tk smoke test (skipped without a display)."""

import json
import logging
import shutil
import tkinter as tk

import pytest

from mri_dataset_tool.presentation.cli.main import main
from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Done, Failed, ReportReadError
from test_cli_dataset import SECRETS, bids_input
from test_gui_run import _ready, _run, project  # noqa: F401  (project is a fixture)

ML_FILES = ["dataset_index.csv", "datalist.json", "splits.tsv", "splits.json"]


def _finalized(project, finalize: bool = True) -> Controller:
    """Built with classes AD/CN (labels incomplete: no ML exports yet), then labeled in step 5."""
    bids_input(project / "in")
    controller = _ready(project, "bids", "AD\nCN")
    _run(controller)
    controller.go_next()
    controller.load_labels()
    controller.edit_label(0, "AD")
    controller.edit_label(1, "CN")
    controller.apply_labels()
    if finalize:
        assert controller.finalize_labels().ok
    controller.go_next()
    assert controller.step == "export" or not finalize
    return controller


def _do(controller: Controller, check_and_task) -> list:
    check, task = check_and_task
    assert check.ok, check
    assert controller.start_task(task, controller.export_failure)
    controller.worker.join(60)
    return controller.poll()


def test_ml_exports_match_the_cli_export_ml(project, caplog):
    caplog.set_level(logging.DEBUG)
    controller = _finalized(project)
    dataset = controller.state.dataset_root
    assert not controller.ml_exports_present()
    shutil.copytree(dataset, project / "cli_dataset")
    events = _do(controller, controller.ml_exports_task(["0.5", "0.5", "0"], "3"))
    assert events[-1] == Done({"files": 4})
    lines = controller.export_finished(events[-1])
    assert lines[0] == ("ML_WRITTEN_IN", {"folder": "dataset", "files": 4})
    assert [v["name"] for _, v in lines[1:]] == ML_FILES and controller.ml_exports_present()

    assert main(["--quiet", "dataset", "export-ml", "cli_dataset", "--ratios", "0.5", "0.5", "0", "--seed", "3"]) == 0
    for name in ML_FILES:
        assert (dataset / name).read_bytes() == (project / "cli_dataset" / name).read_bytes()
    texts = [repr(events), repr(controller.state), caplog.text]
    assert not [s for s in [*SECRETS, str(project)] for text in texts if s in text]


def test_ml_exports_need_finalized_labels(project):
    controller = _finalized(project, finalize=False)  # the GUI has no --allow-unfinalized (design decision)
    events = _do(controller, controller.ml_exports_task(["1", "0", "0"], "0"))
    assert events[-1] == Failed("ML_LABELS_NOT_FINALIZED", "ValueError")
    assert not controller.ml_exports_present()


@pytest.mark.parametrize(("ratios", "seed", "code"), [
    (["0.5", "0.6", "0"], "0", "INVALID_RATIOS"), (["x", "0", "0"], "0", "INVALID_RATIOS"),
    (["1", "0", "0"], "1.5", "INVALID_SEED"),
])
def test_invalid_split_parameters(project, ratios, seed, code):
    controller = _finalized(project)
    check, task = controller.ml_exports_task(ratios, seed)
    assert check.code == code and task is None


def test_a_new_report_goes_to_the_next_free_folder_with_its_warnings(project):
    controller = _finalized(project)
    output = controller.state.output_dir
    assert controller.default_report_dir() == output / "report_2"  # build_dataset wrote output/report
    next(controller.state.dataset_root.rglob("*.nii.gz")).write_bytes(b"not a nifti")
    events = _do(controller, controller.report_task(str(output / "report_2")))
    assert ReportReadError("ValueError") in events and events[-1] == Done({"files": 4})
    lines = controller.export_finished(events[-1])
    assert ("REPORT_WARNING_UNREADABLE_FILES", {"count": 1}) in lines
    assert controller.state.report_dirs == [output / "report_2"] and controller.default_report_dir() == output / "report_3"
    assert controller.report_task(str(output / "report"))[0].code == "REPORT_DIR_NOT_EMPTY"
    assert controller.report_task(str(controller.state.dataset_root / "r"))[0].code == "REPORT_INSIDE_DATASET"
    assert controller.report_task("")[0].code == "REPORT_DIR_REQUIRED"


def test_a_report_folder_filled_meanwhile_is_never_mixed(project):
    controller = _finalized(project)
    folder = controller.state.output_dir / "late"
    check, task = controller.report_task(str(folder))
    folder.mkdir()
    (folder / "other.txt").write_text("x", encoding="utf-8")
    assert controller.start_task(task, controller.export_failure)
    controller.worker.join(60)
    assert controller.poll()[-1] == Failed("REPORT_DIR_NOT_EMPTY", "FileExistsError")
    assert [p.name for p in folder.iterdir()] == ["other.txt"]


# --- Tk smoke ---------------------------------------------------------------------------------------


def test_export_view_writes_ml_exports_and_a_report_and_opens_the_output(project, monkeypatch):
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui import app as app_module
    from mri_dataset_tool.presentation.gui.views import export_step

    opened = []
    monkeypatch.setattr(export_step, "open_folder", opened.append)
    controller = _finalized(project)
    window = app_module.App(controller)
    window.withdraw()
    try:
        window.refresh()
        view = window.views["export"]
        assert view.report_dir.get() == str(controller.state.output_dir / "report_2")
        assert view._write_ml.cget("text") == controller.text("WRITE_ML")
        view.write_ml()
        assert str(view._write_ml.cget("state")) == "disabled"  # running
        controller.worker.join(60)
        window._poll()
        log = view.log.get(0, "end")
        assert controller.text("ML_WRITTEN_IN", folder="dataset", files=4) in log and "  datalist.json" in log
        assert view._write_ml.cget("text") == controller.text("REGENERATE_ML")  # the next set goes to a new folder
        view.seed.set("7")
        view.write_ml()
        controller.worker.join(60)
        window._poll()
        assert controller.text("ML_WRITTEN_IN", folder="ml_exports_2", files=4) in view.log.get(0, "end")
        view.write_report()
        controller.worker.join(60)
        window._poll()
        assert controller.text("REPORT_WRITTEN", files=4) in view.log.get(0, "end")
        assert view.report_dir.get() == str(controller.state.output_dir / "report_3")
        view._open.invoke()
        assert opened == [controller.state.output_dir]
    finally:
        window.destroy()


def test_regenerated_exports_go_to_new_folders_with_paths_to_the_dataset(project):
    controller = _finalized(project)
    dataset, output = controller.state.dataset_root, controller.state.output_dir
    events = _do(controller, controller.ml_exports_task(["0.7", "0.15", "0.15"], "0"))  # the standard set
    controller.export_finished(events[-1])
    standard = {name: (dataset / name).read_bytes() for name in ML_FILES}
    assert controller.next_ml_exports_dir() == output / "ml_exports_2"
    events = _do(controller, controller.ml_exports_task(["0.5", "0.5", "0"], "3"))
    assert events[-1] == Done({"files": 4})
    assert controller.export_finished(events[-1])[0] == ("ML_WRITTEN_IN", {"folder": "ml_exports_2", "files": 4})
    assert {name: (dataset / name).read_bytes() for name in ML_FILES} == standard  # never touched
    regenerated = output / "ml_exports_2"
    datalist = json.loads((regenerated / "datalist.json").read_text(encoding="utf-8"))
    images = [item["image"] for split in ("training", "validation", "testing") for item in datalist[split]]
    assert images and all(image.startswith("../dataset/sub-") for image in images)
    # how MONAI's load_decathlon_datalist resolves them: base_dir = the folder of datalist.json
    assert all((regenerated / image).resolve().is_file() for image in images)
    splits = json.loads((regenerated / "splits.json").read_text(encoding="utf-8"))
    assert (splits["seed"], splits["labels_finalized"]) == (3, True)
    assert controller.next_ml_exports_dir() == output / "ml_exports_3"
    assert controller.state.ml_dirs == [dataset, regenerated]
