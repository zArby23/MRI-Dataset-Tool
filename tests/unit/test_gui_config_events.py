"""GUI step 2: a late <<Modified>> of the classes box must never drop a finished run. Tk smoke test,
skipped without a display."""

import tkinter as tk

import pytest

from test_cli_dataset import bids_input
from test_gui_run import _run, project  # noqa: F401  (project is a fixture)


def test_a_late_modified_event_does_not_reopen_a_finished_run(project):
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App
    from mri_dataset_tool.presentation.gui.controller import Controller

    bids_input(project / "in")
    controller = Controller()
    app = App(controller)
    app.withdraw()
    try:
        assert controller.set_input(str(project / "in"), "bids", str(project / "gui")).ok
        controller.go_next()
        app.refresh()
        view = app.views["config"]
        view.config_path.set(str(project / "config" / "run.yaml"))
        view.classes.insert("1.0", "AD\nCN")  # by code, as a paste: its <<Modified>> arrives on the next loop
        view.validate()
        assert controller.go_next() == "run"
        app.refresh()
        _run(controller)  # the run finishes before Tk delivers the pending event
        assert controller.state.dataset_root is not None
        app.update()  # the late <<Modified>> is delivered now
        assert controller.state.dataset_root is not None and controller.can_go_next()

        controller.step = "config"  # a real edit on the shown step still reopens it
        app.refresh()
        view.classes.insert("end", "\nMCI")
        app.update()
        assert controller.state.dataset_root is None and not controller.can_go_next()
    finally:
        app.destroy()
