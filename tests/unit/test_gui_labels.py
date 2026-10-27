"""GUI step 5 (labels): controller with the real services on a dataset built by step 4, PHI sweep and a Tk
smoke test (skipped without a display)."""

import logging
import tkinter as tk

import pytest

from mri_dataset_tool.presentation.gui.controller import Controller
from test_cli_dataset import SECRETS, bids_input
from test_gui_run import _ready, _run, project  # noqa: F401  (project is a fixture)


def settle(app) -> None:
    """Wait for the labels task of the view and deliver its events (load, apply... run in the worker)."""
    app.controller.worker.join(120)
    app._poll()


def _labeled(project, classes: str = "AD\nCN") -> Controller:
    bids_input(project / "in")  # 3 subjects; PATIENT03 fails validate: 2 pairs in the dataset
    controller = _ready(project, "bids", classes)
    _run(controller)
    controller.go_next()
    assert controller.step == "labels"
    return controller


def test_labels_are_listed_edited_applied_finalized_and_reopened(project, caplog):
    caplog.set_level(logging.DEBUG)
    controller = _labeled(project)
    assert controller.load_labels().ok and not controller.can_go_next()
    state = controller.state
    assert [row.defect for row in state.label_rows] == ["UNLABELED", "UNLABELED"]
    assert state.label_classes == ["AD", "CN"] and state.label_counts["pairs"] == 2
    assert controller.finalize_labels().code == "LABELS_INCOMPLETE"  # finalize_labels needs is_complete

    assert controller.edit_label(0, "MCI").code == "LABEL_UNKNOWN_CLASS"
    assert controller.edit_label(0, "AD").ok and controller.edit_label(1, "CN").ok
    assert controller.finalize_labels().code == "LABELS_EDITS_PENDING"
    assert controller.apply_labels().values == {"count": 2} and state.label_edits == {}
    assert [(row.label, row.defect) for row in state.label_rows] == [("AD", None), ("CN", None)]
    assert "correct" in (state.dataset_root / "labels_changes.tsv").read_text(encoding="utf-8")

    assert controller.finalize_labels().ok and state.labels_closed and controller.can_go_next()
    assert controller.edit_label(0, "CN").code == "LABELS_FINALIZED"  # rejected until reopened
    assert controller.reopen_labels().ok and not state.labels_closed and not controller.can_go_next()
    assert controller.edit_label(0, "CN").ok and controller.apply_labels().values == {"count": 1}

    ids = [row.participant for row in state.label_rows] + [row.session for row in state.label_rows]
    texts = [repr(state), repr(controller.poll()), caplog.text, *controller.labels_status_lines()]
    assert not [s for s in [*SECRETS, *ids, str(project)] for text in texts if s in text]


def test_without_classes_the_step_is_valid_and_empty(project):
    controller = _labeled(project, classes="")
    check = controller.load_labels()
    assert check.code == "NO_LABELS" and controller.can_go_next() and controller.state.label_rows == []


def test_a_hand_edited_table_must_be_fixed_by_hand(project):
    controller = _labeled(project)
    controller.load_labels()
    tsv = controller.state.dataset_root / "labels.tsv"
    first = tsv.read_text(encoding="utf-8").splitlines()[1]
    tsv.write_text(tsv.read_text(encoding="utf-8") + first + "\n", encoding="utf-8")  # a repeated pair
    assert controller.load_labels().ok
    assert {row.defect for row in controller.state.label_rows} == {"DUPLICATED", "UNLABELED"}
    controller.edit_label(1, "AD")
    before = tsv.read_bytes()
    assert controller.apply_labels().code == "LABELS_FIX_BY_HAND" and tsv.read_bytes() == before


def test_labels_view_loads_edits_and_finalizes(project):
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App

    controller = _labeled(project)
    app = App(controller)
    app.withdraw()
    try:
        app.refresh()  # showing the step loads the table (in the worker)
        settle(app)
        view = app.views["labels"]
        items = view.tree.get_children()
        assert len(items) == 2 and view.tree.set(items[0], "defect") == controller.text("DEFECT_UNLABELED")
        assert str(view._apply.cget("state")) == "disabled" and str(view._reopen.cget("state")) == "disabled"
        view.tree.see(items[0])
        app.update()  # lay out the table so its cells have a box
        assert view.start_edit(0) is not None  # the editor over a visible cell
        for index, label in ((0, "AD"), (1, "CN")):
            view.commit_edit(index, label)
        assert view.tree.set(items[0], "label") == "AD" and str(view._apply.cget("state")) == "normal"
        view._apply.invoke()
        settle(app)
        assert controller.text("LABELS_APPLIED", count=2) in view._status.cget("text")
        view._finalize.invoke()
        settle(app)
        assert controller.state.labels_closed and str(app._next.cget("state")) == "normal"
        assert str(view._reopen.cget("state")) == "normal" and str(view._finalize.cget("state")) == "disabled"
        assert view.start_edit(0) is None and controller.text("LABELS_FINALIZED") in view._status.cget("text")
    finally:
        app.destroy()


def test_reload_says_how_many_pending_edits_it_discards(project):
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App

    controller = _labeled(project)
    app = App(controller)
    app.withdraw()
    try:
        app.refresh()
        settle(app)
        view = app.views["labels"]
        view.commit_edit(0, "AD")
        view._reload.invoke()
        settle(app)
        assert controller.text("LABELS_DISCARDED", count=1) in view._status.cget("text")
        assert controller.state.label_edits == {}
    finally:
        app.destroy()
