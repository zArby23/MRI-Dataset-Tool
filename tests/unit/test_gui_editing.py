"""One-click cell editing, pending label edits that are not forgotten, the run log without empty
«none» lines and bars that fit the fixed window. The Tk tests are skipped without a display."""

import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pytest

from mri_dataset_tool.application.services.labels_table import LabelRow
from mri_dataset_tool.presentation.gui import messages, widgets
from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Failed


def _labels_controller() -> Controller:
    """A controller on the labels step with three rows (no dataset is read: the rows are set directly)."""
    controller = Controller()
    state = controller.state
    state.dataset_root = Path("E:/not-read/dataset")
    state.labels_available, state.label_classes = True, ["AD", "CN"]
    state.label_rows = [LabelRow("a1", None, "AD", None), LabelRow("b2", None, None, "UNLABELED"),
                        LabelRow("c3", None, None, "UNLABELED")]
    state.label_counts = {"pairs": 3, "labeled": 1, "foreign": 0, "invalid": 0}
    state.label_version += 1
    controller.step = "labels"
    return controller


# --- without a display ----------------------------------------------------------------------------


def test_pending_label_edits_ask_before_leaving_the_step():
    controller = _labels_controller()
    assert controller.pending_label_edits() == 0 and controller.leave_question() is None
    assert controller.assign_labels([1, 2], "CN").ok
    assert controller.pending_label_edits() == 2 and controller.leave_question() == 2
    controller.step = "export"  # only the labels step asks
    assert controller.leave_question() is None
    controller.step = "labels"
    version = controller.state.label_version
    controller.discard_label_edits()
    assert controller.pending_label_edits() == 0 and controller.state.label_version > version


def test_messages_do_not_repeat_the_severity_prefix():
    """The status line adds «Error:», «Aviso:» or «Listo:»: no text starts with one itself."""
    for language in messages.LANGUAGES:
        prefixes = tuple(messages.text(f"PREFIX_{s}", language) for s in ("error", "warning", "ok"))
        assert [code for code, text in messages.CATALOG[language].items()
                if text.startswith(prefixes) and not code.startswith("PREFIX_")] == []


def test_label_status_lines_count_the_changes_not_applied():
    controller = _labels_controller()
    controller.assign_labels([1], "AD")
    assert controller.text("LABELS_UNAPPLIED", count=1) in controller.labels_status_lines()
    assert messages.severity("LABELS_UNAPPLIED") == "warning"


# --- with a display -------------------------------------------------------------------------------


def _display() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure
        pytest.skip("No display available for Tk.")


def _app(controller: Controller):
    from mri_dataset_tool.presentation.gui.app import App

    step, controller.step = controller.step, "input"  # built on step 1: showing step 5 would read the dataset
    app = App(controller)
    app.withdraw()
    app.views["labels"]._loaded_for = controller.state.dataset_root  # the rows are set: nothing to read
    controller.step = step
    app.refresh()
    app.update()
    return app


def test_one_click_opens_only_editable_cells_and_enter_or_f2_open_the_focused_row():
    _display()
    root = tk.Tk()
    try:
        tree = ttk.Treeview(root, columns=("name", "label"), show="headings")
        tree.pack()
        tree.insert("", "end", iid="0", values=("x", "AD"))
        opened = []
        widgets.bind_cell_editing(tree, ("label",), lambda item, column: opened.append((item, column)))
        root.update()
        x_name, y, *_ = tree.bbox("0", "name")
        x_label, *_ = tree.bbox("0", "label")
        tree.event_generate("<ButtonRelease-1>", x=x_name + 2, y=y + 2)
        assert opened == []  # a click elsewhere only selects
        tree.event_generate("<ButtonRelease-1>", x=x_label + 2, y=y + 2)
        assert opened == [("0", "label")]
        tree.focus("0")
        tree.event_generate("<Motion>", x=x_label + 2, y=y + 2)
        assert str(tree.cget("cursor")) == "hand2"
        tree.event_generate("<Motion>", x=x_name + 2, y=y + 2)
        assert str(tree.cget("cursor")) == ""
        assert {"<Key-Return>", "<Key-F2>"} <= set(tree.bind())
    finally:
        root.destroy()


def test_labels_table_keeps_the_selection_and_shows_apply_while_edits_are_pending():
    _display()
    controller = _labels_controller()
    app = _app(controller)
    try:
        view = app.views["labels"]
        assert str(view._apply.cget("style")) == "TButton"  # nothing to apply
        assert view.tree.heading("label", "text").endswith("▾")
        view.tree.selection_set(["1", "2"])
        view.commit_edit(1, "CN")  # a one-cell edit redraws the table
        assert set(view.tree.selection()) == {"1", "2"}  # «Assign to selection» still acts on them
        assert str(view._apply.cget("style")) == "Accent.TButton" and view._apply.cget("state") == "normal"
        assert controller.text("LABELS_UNAPPLIED", count=1) in view._status.cget("text")
        assert view._status.cget("severity") == "warning"
        view.assign_selection()  # with no class chosen: clears both rows, still pending
        assert controller.pending_label_edits() == 2
        app.deiconify()  # the editor is placed over a visible cell
        app.update()
        editor = view.start_edit(0)
        assert editor is not None and set(view.tree.selection()) == {"1", "2"}  # opening keeps it too
        view._close_editor(refocus=True)
        assert set(view.tree.selection()) == {"1", "2"} and controller.pending_label_edits() == 2
    finally:
        app.destroy()


@pytest.mark.parametrize(("choice", "step", "pending"), [(None, "labels", 1), ("cancel", "labels", 1),
                                                          ("discard", "run", 0)])
def test_leaving_the_labels_step_with_pending_edits_asks(monkeypatch, choice, step, pending):
    _display()
    from mri_dataset_tool.presentation.gui import dialogs

    asked = []
    monkeypatch.setattr(dialogs, "ask_choice", lambda title, text, choices, **_: asked.append(
        [value for value, _ in choices]) or choice)
    controller = _labels_controller()
    controller.assign_labels([1], "CN")
    app = _app(controller)
    try:
        app._back.invoke()
        assert asked == [["apply", "discard", "cancel"]]
        assert controller.step == step and controller.pending_label_edits() == pending
    finally:
        app.destroy()


def test_apply_and_continue_applies_first_and_moves_when_it_succeeded(monkeypatch):
    _display()
    from mri_dataset_tool.presentation.gui import dialogs

    monkeypatch.setattr(dialogs, "ask_choice", lambda *a, **k: "apply")
    controller = _labels_controller()
    controller.assign_labels([1], "CN")
    app = _app(controller)
    try:
        started = []
        monkeypatch.setattr(app.views["labels"], "run", started.append)
        app._go_back()
        assert started == ["apply"] and controller.step == "labels"  # it waits for the apply task
        controller.state.label_edits = {}  # the task applied them
        monkeypatch.setattr(controller, "poll", lambda: [object()])
        monkeypatch.setattr(app.views["labels"], "on_event", lambda event: None)
        app._poll()
        assert controller.step == "run"
    finally:
        app.destroy()


def test_run_log_shows_no_empty_lines_only_what_happened():
    _display()
    controller = Controller()
    controller.step = "run"
    app = _app(controller)
    try:
        view = app.views["run"]
        view._lines = [("text", "RUN_RUNNING"), ("text", "RUN_DONE")]
        view.refresh_texts()
        lines = view.log.get(0, "end")
        assert controller.text("RUN_CLEAN") in lines and controller.text("NONE") not in " ".join(lines)
        view._skipped["OSError"] = 2
        view._lines.append(("failed", Failed("STAGE_FAILED", "OSError", "report")))
        view.refresh_texts()
        lines = view.log.get(0, "end")
        assert controller.text("RUN_SKIPPED", counts="OSError 2") in lines and controller.text("RUN_CLEAN") not in lines
        assert not any(controller.text("RUN_ERRORS", counts=controller.text("NONE")) == line for line in lines)
    finally:
        app.destroy()


def test_low_disk_space_shows_a_single_warning_prefix():
    _display()
    controller = Controller()
    app = _app(controller)
    try:
        view = app.views["input"]
        view._disk_summary = {"required": 2**30, "free": 2**30, "insufficient": 1}
        view.refresh_texts()
        shown = view._disk.shown_text()
        prefix = controller.text("PREFIX_warning")
        assert shown.startswith(prefix) and shown.count(prefix) == 1
        assert shown.count("1.0") == 2  # the figures computed from bytes (GiB, one decimal), whatever the wording
    finally:
        app.destroy()


def _overflow(app) -> list[str]:
    """The widgets of the current step whose right edge passes the window's."""
    edge = app.winfo_rootx() + app.winfo_width()
    out = []

    def walk(widget) -> None:
        if widget.winfo_ismapped() and widget.winfo_rootx() + widget.winfo_width() > edge + 1:
            out.append(f"{widget.winfo_class()} {widget}")
        for child in widget.winfo_children():
            if not isinstance(child, tk.Toplevel):
                walk(child)

    walk(app.views[app.controller.step])
    return out


@pytest.mark.parametrize("language", messages.LANGUAGES)
def test_no_bar_passes_the_window_edge(language):
    _display()
    controller = Controller(language=language)
    controller.state.input_format = "dicom"
    controller.state.classes = {"AD": "", "CN": ""}
    app = _app(controller)
    app.deiconify()  # mapped widgets have their real geometry
    try:
        for step in ("input", "config", "mapping", "run", "labels", "export"):
            controller.step = step
            if step == "labels":
                app.views["labels"]._loaded_for = controller.state.dataset_root
            app.refresh()
            app.update()
            assert _overflow(app) == [], step
    finally:
        app.destroy()


def _wait_task(app, controller, limit: float = 30.0) -> None:
    import time

    deadline = time.monotonic() + limit
    while controller.worker.busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.02)
    app._poll()
    app.update()


def test_a_failed_apply_and_continue_stays_with_the_edits_and_a_later_task_does_not_move(monkeypatch):
    """A real failure: the dataset root does not exist, so applying raises FileNotFoundError."""
    _display()
    from mri_dataset_tool.presentation.gui import dialogs

    monkeypatch.setattr(dialogs, "ask_choice", lambda *a, **k: "apply")
    controller = _labels_controller()
    controller.complete("run")
    controller.assign_labels([1], "CN")
    app = _app(controller)
    try:
        app._go_back()
        _wait_task(app, controller)
        view = app.views["labels"]
        assert controller.step == "labels" and controller.pending_label_edits() == 1 and app._after_apply is None
        assert "FileNotFoundError" in view._status.cget("text") and view._status.cget("severity") == "error"
        view.run("load")  # a later task (Reload) must not run the old move
        _wait_task(app, controller)
        assert controller.step == "labels"
    finally:
        app.destroy()


def test_close_question_asks_about_label_edits_not_applied(monkeypatch):
    controller = _labels_controller()
    assert controller.close_question() is None
    controller.assign_labels([1], "CN")
    assert controller.close_question() == controller.close_question(True) == ("LEAVE_PENDING_TITLE", "CLOSE_PENDING")
    controller.step = "export"
    assert controller.close_question() is None
    controller.step = "labels"
    monkeypatch.setattr(type(controller.worker), "busy", property(lambda self: True))
    assert controller.close_question() == ("CLOSE_TITLE", "CLOSE_WHILE_RUNNING")  # a running task asks first


@pytest.mark.parametrize("choice", [None, "cancel", "discard", "apply"])
def test_closing_with_label_edits_not_applied_asks_with_three_buttons(monkeypatch, choice):
    _display()
    from mri_dataset_tool.presentation.gui import dialogs

    asked = []
    monkeypatch.setattr(dialogs, "ask_choice", lambda title, text, choices, **_: asked.append(
        [value for value, _ in choices]) or choice)
    controller = _labels_controller()
    controller.assign_labels([1], "CN")
    app = _app(controller)
    started = []
    monkeypatch.setattr(app.views["labels"], "run", started.append)
    try:
        app.request_close()  # the window's X
        assert asked == [["apply", "discard", "cancel"]]
        if choice == "discard":
            assert app._closed
            return
        assert not app._closed
        if choice == "apply":
            assert started == ["apply"]  # closes only when the apply ends well
            controller.state.label_edits = {}
            monkeypatch.setattr(controller, "poll", lambda: [object()])
            monkeypatch.setattr(app.views["labels"], "on_event", lambda event: None)
            app._poll()
            assert app._closed
    finally:
        if not app._closed:
            app.destroy()
