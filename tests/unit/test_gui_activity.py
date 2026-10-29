"""The activity indicator: the controller's ``Activity`` fed by the worker events, without a
display; the footer bar and the severity colors of the run log with Tk (skipped without a display)."""

import threading
import tkinter as tk
from pathlib import Path

import pytest

from mri_dataset_tool.presentation.gui import theme
from mri_dataset_tool.presentation.gui.controller import Activity, Controller
from mri_dataset_tool.presentation.gui.worker import Failed

SECRET = "E:/PlantedPatient/scan.dcm"


def _blocked_task(release: threading.Event, fail: bool = False):
    def task(reporter):
        reporter.on_status("export", {})
        reporter.on_skipped(Path(SECRET), OSError(SECRET))
        reporter.on_error(Path(SECRET), ValueError(SECRET))
        reporter.on_report_error(Path(SECRET), OSError(SECRET))
        release.wait(10)
        if fail:
            raise RuntimeError(SECRET)
        return {"studies": 1}

    return task


def _poll_until(controller: Controller, condition) -> None:
    for _ in range(500):
        controller.poll()
        if condition():
            return
        threading.Event().wait(0.01)
    raise AssertionError("timed out")


@pytest.mark.parametrize("fail", [False, True])
def test_activity_follows_the_events_and_clears_on_done_or_failed(fail):
    controller = Controller()
    assert controller.activity == Activity() and controller.activity_text() == ""
    release = threading.Event()
    assert controller.start_task(_blocked_task(release, fail), activity="run")
    assert controller.activity.task == "run"
    assert controller.activity_text() == controller.text("ACTIVITY_run")
    _poll_until(controller, lambda: controller.activity.unreadable == 1)
    activity = controller.activity
    assert (activity.skipped, activity.failed, activity.unreadable, activity.stage.stage) == (1, 1, 1, "export")
    line = controller.activity_text()
    assert line.startswith(controller.text("EV_export"))
    assert controller.text("ACTIVITY_COUNTS", skipped=1, failed=1, unreadable=1) in line and "Planted" not in line
    release.set()
    controller.worker.join(10)
    events = controller.poll()
    assert isinstance(events[-1], Failed) == fail
    assert controller.activity == Activity() and controller.activity_text() == ""


def test_unknown_activity_name_falls_back_to_a_generic_text():
    controller = Controller()
    release = threading.Event()
    controller.start_task(lambda reporter: release.wait(10) and None)
    assert controller.activity_text() == controller.text("TASK_STARTED")
    release.set()
    controller.worker.join(10)
    controller.poll()


def test_every_task_of_the_views_has_an_activity_text():
    controller = Controller()
    for name in ("disk_space", "preview", "run", "labels", "corrections", "ml", "report"):
        for language in ("es", "en"):
            controller.set_language(language)
            assert controller.text(f"ACTIVITY_{name}")


def test_footer_bar_runs_only_while_a_task_runs():
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App

    app = App(Controller())
    app.withdraw()
    try:
        app.update()
        assert str(app._activity_bar.cget("mode")) == "determinate" and app._activity.cget("text") == ""
        release = threading.Event()
        app.controller.start_task(_blocked_task(release), activity="report")
        app.refresh()
        assert str(app._activity_bar.cget("mode")) == "indeterminate"
        assert app._activity.cget("text") == app.controller.text("ACTIVITY_report")
        release.set()
        app.controller.worker.join(10)
        app._poll()
        assert str(app._activity_bar.cget("mode")) == "determinate" and float(app._activity_bar.cget("value")) == 0
        assert app._activity.cget("text") == ""
    finally:
        app.destroy()


def test_run_log_colors_and_prefixes_failures():
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App

    app = App(Controller())
    app.withdraw()
    try:
        view = app.views["run"]
        view._lines = [("text", "RUN_RUNNING"), ("failed", Failed("STAGE_FAILED", "OSError", "export"))]
        view.refresh_texts()
        lines = view.log.get(0, "end")
        failure = app.controller.text("STAGE_FAILED", stage="export", error_type="OSError")
        assert lines[1] == f'{app.controller.text("PREFIX_error")} {failure}'
        assert str(view.log.itemcget(1, "foreground")).upper() == theme.color("error")
        assert str(view.log.itemcget(0, "foreground")).upper() == theme.color("text")
    finally:
        app.destroy()
