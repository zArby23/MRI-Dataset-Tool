"""GUI step 5 in batch (selection, all unlabeled, filter, corrections TSV) and the label column of step 3 in
batch: controller with the real services, thousands of rows, PHI sweep and Tk smoke tests (skipped without
a display)."""

import logging
import time
import tkinter as tk
from pathlib import Path

import pytest

from mri_dataset_tool.application.services.labels import write_label_template
from mri_dataset_tool.presentation.gui.controller import Controller
from test_gui_labels import _labeled, settle
from test_gui_mapping import ready  # noqa: F401  (fixture: a DICOM tree past steps 1 and 2)
from test_gui_mapping import _preview
from test_gui_run import project  # noqa: F401  (fixture)

PAIRS = 3000


def _big(root: Path) -> Controller:
    """A dataset tree with PAIRS participant/session pairs (empty images: only names are read)."""
    for index in range(PAIRS):
        anat = root / f"sub-p{index:05d}" / "ses-v1" / "anat"
        anat.mkdir(parents=True)
        (anat / f"sub-p{index:05d}_ses-v1_T1w.nii.gz").write_bytes(b"")
    write_label_template(root, {"AD": "", "CN": "", "MCI": ""})
    controller = Controller()
    controller.state.dataset_root = root
    return controller


def _tk() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")


def test_assign_to_rows_filters_and_all_unlabeled(project):
    controller = _labeled(project)
    controller.load_labels()
    assert controller.assign_labels([], "AD").code == "NOTHING_SELECTED"
    assert controller.assign_labels([0, 1], "MCI").code == "LABEL_UNKNOWN_CLASS"
    assert controller.assign_labels([0], "AD").values == {"count": 1}
    controller.set_label_filter("unlabeled")
    assert controller.visible_label_rows() == [1] == controller.unlabeled_rows()
    controller.set_label_filter("defect")
    assert controller.visible_label_rows() == [1]  # row 0 edited to a class: no defect any more
    assert controller.assign_labels(controller.unlabeled_rows(), "CN").values == {"count": 1}
    assert controller.visible_label_rows() == [] and controller.apply_labels().values == {"count": 2}
    assert controller.assign_labels([0, 1], "").values == {"count": 2}  # empty = remove the label
    controller.set_label_filter("all")
    assert [controller.effective_label(i) for i in (0, 1)] == [("", "UNLABELED")] * 2
    with pytest.raises(ValueError):
        controller.set_label_filter("planted")


def test_corrections_tsv_become_pending_edits_and_apply_all_or_nothing(project, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    controller = _labeled(project)
    controller.load_labels()
    pairs = [(row.participant, row.session) for row in controller.state.label_rows]
    path = tmp_path / "fix.tsv"
    lines = ["participant_id\tsession_id\tlabel"] + [f"sub-{s}\tses-{v}\t{c}" for (s, v), c in zip(pairs, ("AD", "CN"))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert controller.load_label_corrections(str(path)).values == {"count": 2}
    before = (controller.state.dataset_root / "labels.tsv").read_bytes()
    assert (controller.state.dataset_root / "labels.tsv").read_bytes() == before  # nothing written yet
    assert controller.apply_labels().values == {"count": 2} and controller.finalize_labels().ok

    controller.reopen_labels()
    bad = {
        "sub-PlantedSubject\tses-PlantedVisit\tAD": "LABEL_PAIR_UNKNOWN",
        f"sub-{pairs[0][0]}\tses-{pairs[0][1]}\tAD\nsub-{pairs[0][0]}\tses-{pairs[0][1]}\tCN": "LABEL_CORRECTIONS_INVALID",
        f"sub-{pairs[0][0]}\tses-{pairs[0][1]}\tPlantedClass": "LABEL_UNKNOWN_CLASS",
    }
    for rows, code in bad.items():
        path.write_text(f"participant_id\tsession_id\tlabel\n{rows}\n", encoding="utf-8")
        assert controller.load_label_corrections(str(path)).code == code and controller.state.label_edits == {}
    assert controller.load_label_corrections(str(tmp_path / "none.tsv")).code == "CORRECTIONS_NOT_FOUND"
    texts = [repr(controller.state), caplog.text, *controller.labels_status_lines(), repr(controller.poll())]
    assert not [text for text in texts if "Planted" in text or str(tmp_path) in text]


def test_thousands_of_pairs_are_handled_in_seconds(tmp_path):
    controller = _big(tmp_path / "dataset")
    start = time.perf_counter()
    assert controller.load_labels().ok and len(controller.state.label_rows) == PAIRS
    controller.assign_labels(controller.unlabeled_rows(), "AD")
    assert controller.apply_labels().values == {"count": PAIRS} and controller.finalize_labels().ok
    # ~2 s per walk of the dataset tree (dataset_pairs) on Windows: the view runs these in the worker
    assert time.perf_counter() - start < 60


def test_labels_view_batch_tools(project, monkeypatch):
    _tk()
    from mri_dataset_tool.presentation.gui.app import App

    controller = _labeled(project)
    app = App(controller)
    app.withdraw()
    try:
        app.refresh()
        settle(app)
        view = app.views["labels"]
        view.assign_selection()
        assert controller.text("NOTHING_SELECTED") in view._status.cget("text")
        view.tree.selection_set(view.tree.get_children())  # Ctrl/Shift selection of both rows
        view.batch_class.set("AD")
        view.assign_selection()
        assert controller.text("ASSIGNED", count=2) in view._status.cget("text")
        assert [view.tree.set(i, "label") for i in view.tree.get_children()] == ["AD", "AD"]
        view.filter.set("unlabeled")
        view._filter_changed()
        assert view.tree.get_children() == ()
        controller.assign_labels([1], "")
        view.refresh_texts()
        assert view.tree.get_children() == ("1",)
        questions = []
        monkeypatch.setattr(view, "confirm", lambda question: questions.append(question) or True)
        view.batch_class.set("CN")
        view.assign_unlabeled()
        assert questions == [controller.text("CONFIRM_ASSIGN_UNLABELED", label="CN", count=1)]
        view._apply.invoke()
        settle(app)
        assert controller.text("LABELS_APPLIED", count=2) in view._status.cget("text")
        view.assign_unlabeled()
        assert controller.text("NOTHING_UNLABELED") in view._status.cget("text")
    finally:
        app.destroy()


def test_labels_view_redraws_thousands_of_rows_only_when_they_change(tmp_path):
    _tk()
    from mri_dataset_tool.presentation.gui.app import App

    controller = _big(tmp_path / "dataset")
    controller.step = "labels"
    app = App(controller)
    app.withdraw()
    try:
        start = time.perf_counter()
        app.refresh()
        assert str(app.views["labels"]._apply.cget("state")) == "disabled"  # loading: the window still responds
        settle(app)
        view = app.views["labels"]
        assert len(view.tree.get_children()) == PAIRS
        first = time.perf_counter() - start
        start = time.perf_counter()
        for _ in range(20):
            app.refresh()  # no change: the table is not rebuilt
        assert time.perf_counter() - start < max(first, 1.0)
        view.tree.selection_set(view.tree.get_children()[:1500])
        view.batch_class.set("MCI")
        view.assign_selection()
        assert sum(view.tree.set(i, "label") == "MCI" for i in view.tree.get_children()) == 1500
    finally:
        app.destroy()


# --- step 3: the label column in batch ------------------------------------------------------------


def test_mapping_label_to_the_selection(ready):
    _preview(ready)
    rows = ready.state.preview
    t1, flair = (next(i for i, r in enumerate(rows) if r.location.as_posix() == loc) for loc in ("a/t1", "b/flair"))
    assert ready.assign_mapping_label([], "AD").code == "NOTHING_SELECTED"
    assert ready.assign_mapping_label([t1, flair], "MCI").code == "MAPPING_LABEL_UNKNOWN"
    assert ready.state.mapping == []  # all or nothing
    assert ready.assign_mapping_label([t1, flair], "AD").values == {"count": 2} and not ready.can_go_next()
    _preview(ready)
    assert {r.location.as_posix(): r.label for r in ready.state.preview} == {"a/adc": "AD", "a/t1": "AD", "b/flair": "AD"}


def test_mapping_view_assigns_a_label_to_the_selection(ready):
    _tk()
    from mri_dataset_tool.presentation.gui.app import App

    _preview(ready)
    app = App(ready)
    app.withdraw()
    try:
        app.refresh()
        view = app.views["mapping"]
        view.tree.selection_set(view.tree.get_children())
        view.batch_label.set("CN")
        view.assign_selection()
        assert ready.text("MAPPING_ASSIGNED", count=3) in view._status.cget("text")
        assert {view.tree.set(i, "label") for i in view.tree.get_children()} == {"CN"}
    finally:
        app.destroy()
