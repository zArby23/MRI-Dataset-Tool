"""GUI step 3 (mapping): controller without Tk, PHI sweep and a Tk smoke test (skipped without a display)."""

import logging
import tkinter as tk
from pathlib import Path

import pytest

from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Done, Failed
from test_anonymize_dicom_tree import PLANTED
from test_service_dataset_ingest import KEY_BYTES, dicom_tree

REPO = Path(__file__).resolve().parents[2]
SECRETS = [*PLANTED, "PlantedDesc", "PlantedProto"]


@pytest.fixture
def ready(tmp_path, monkeypatch) -> Controller:
    """A controller past steps 1 and 2 on a DICOM tree (patient PAT12345, studies a and b)."""
    monkeypatch.setenv("MRI_ANON_KEY", KEY_BYTES.decode())
    dicom_tree(tmp_path / "in")
    controller = Controller()
    assert controller.set_input(str(tmp_path / "in"), "dicom", str(tmp_path / "out")).ok
    assert controller.set_config(str(REPO / "config" / "stage3_bids.yaml"), False, "AD\nCN", ["1", "0", "0"], "0").ok
    controller.go_next()
    assert controller.go_next() == "mapping"
    return controller


def _preview(controller: Controller) -> list:
    assert controller.start_task(controller.preview_task())
    controller.worker.join(30)
    events = controller.poll()
    if isinstance(events[-1], Done):
        controller.preview_finished()
    return events


def test_preview_runs_in_the_worker_and_unlocks_the_step(ready):
    assert not ready.can_go_next()
    events = _preview(ready)
    assert events[-1] == Done({"series": 3, "skipped": 1})  # only counts in the queue
    assert len(ready.state.preview) == 3 and ready.can_go_next()


def test_edits_reopen_the_step_until_the_next_preview(ready):
    _preview(ready)
    t1 = next(i for i, row in enumerate(ready.state.preview) if row.location.as_posix() == "a/t1")
    assert ready.edit_mapping(t1, "participant", "P01").ok and not ready.can_go_next()
    assert ready.edit_mapping(t1, "label", "AD").ok
    assert ready.edit_mapping(t1, "label", "MCI").code == "MAPPING_LABEL_UNKNOWN"
    assert ready.edit_mapping(t1, "participant", "P 1").code == "INVALID_MAPPING"
    _preview(ready)
    row = next(row for row in ready.state.preview if row.location.as_posix() == "a/t1")
    assert (row.participant, row.label) == ("P01", "AD") and ready.can_go_next()


def test_a_preview_that_fails_keeps_the_step_closed(ready):
    _preview(ready)
    for location in ("a/t1", "b/flair"):  # one patient: studies a and b would both be (patient, V1)
        index = next(i for i, row in enumerate(ready.state.preview) if row.location.as_posix() == location)
        assert ready.edit_mapping(index, "session", "V1").ok
    events = _preview(ready)
    assert events[-1] == Failed("MAPPING_PAIR_REPEATED", "InvalidBuildInput") and not ready.can_go_next()


def test_save_and_load_the_table(ready, tmp_path):
    _preview(ready)
    ready.edit_mapping(0, "suffix", "dwi")
    path = tmp_path / "map.tsv"
    assert ready.save_mapping_file(str(path)).ok
    assert ready.save_mapping_file(str(path)).code == "MAPPING_FILE_EXISTS"
    assert not [secret for secret in SECRETS if secret in path.read_text(encoding="utf-8")]  # paths only (D2)
    saved = list(ready.state.mapping)
    ready.state.mapping = []
    assert ready.load_mapping_file(str(path)).ok and ready.state.mapping == saved
    assert ready.load_mapping_file(str(tmp_path / "none.tsv")).code == "MAPPING_NOT_FOUND"


def test_a_new_input_drops_the_table(ready, tmp_path):
    _preview(ready)
    ready.edit_mapping(0, "suffix", "dwi")
    (tmp_path / "other").mkdir()
    assert ready.set_input(str(tmp_path / "other"), "dicom", str(tmp_path / "out")).ok
    assert ready.state.preview == [] and ready.state.mapping == []


def test_paths_and_header_values_stay_out_of_state_repr_queue_and_logs(ready, caplog):
    caplog.set_level(logging.DEBUG)
    events = _preview(ready)
    ready.edit_mapping(0, "suffix", "dwi")
    texts = [repr(ready.state), repr(events), caplog.text]
    assert not [secret for secret in [*SECRETS, "a/t1", "a/adc", "b/flair"] for text in texts if secret in text]


# --- Tk smoke ---------------------------------------------------------------------------------------


def test_mapping_view_previews_edits_and_redraws(ready):
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App

    app = App(ready)
    app.withdraw()
    try:
        app.refresh()
        view = app.views["mapping"]
        view.run_preview()
        assert str(view._preview.cget("state")) == "disabled"
        ready.worker.join(30)
        app._poll()
        assert len(view.tree.get_children()) == 3 and str(app._next.cget("state")) == "normal"
        codes = {view.tree.set(item, "location"): view.tree.set(item, "code") for item in view.tree.get_children()}
        assert codes["a/adc"] == ready.text("CODE_EXCLUDED")
        item = next(i for i in view.tree.get_children() if view.tree.set(i, "location") == "a/adc")
        view.tree.see(item)
        app.update()
        editor = view.start_edit(int(item), "suffix")
        editor.set("dwi")
        view.commit_edit(int(item), "suffix", "dwi")
        assert view.tree.set(item, "suffix") == "dwi"  # kept on the redraw that follows the edit
        assert view._status.cget("text") == ready.text("EDIT_PENDING")
        assert str(app._next.cget("state")) == "disabled"
        view.commit_edit(int(item), "participant", "bad id")
        assert view._status.cget("text") == ready.text("INVALID_MAPPING")
    finally:
        app.destroy()
