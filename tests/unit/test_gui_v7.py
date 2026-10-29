"""Stage 5C V7 (QA8 fixes): report warnings with any code, the batch label per study, the step-6 card on small
screens, and the cell editors (kept on focus loss, never floating). Tk tests are skipped without a display."""

import json
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path, PurePosixPath

import pytest

from mri_dataset_tool.application.services.dataset_ingest import SeriesDecision
from mri_dataset_tool.application.services.ingest_preview import apply_edit
from mri_dataset_tool.presentation.gui import messages
from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Done

REPORT_WARNINGS = ("LABELS_UNREADABLE", "MANIFEST_UNREADABLE", "MISSING_SHAPE", "MISSING_SUBJECT_ID",
                   "NON_FINITE_VOXELS", "NO_VOLUME", "UNKNOWN_CLASS", "UNLABELED_SESSIONS", "UNREADABLE_FILES")
REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("language", messages.LANGUAGES)
def test_every_report_warning_code_is_shown(language, tmp_path):
    controller = Controller()
    controller.language = language
    controller._export_kind = "report"
    controller._new_report = (tmp_path / "report_2", [], {code: 3 for code in REPORT_WARNINGS})
    lines = controller.export_finished(Done({"files": 0}))
    shown = [controller.text(code, **values) for code, values in lines]
    assert all("{" not in line for line in shown)
    assert len(shown) == 1 + len(REPORT_WARNINGS) and all(line for line in shown)


def _decisions(count: int) -> list[SeriesDecision]:
    return [SeriesDecision(PurePosixPath(f"pat{i // 3:04d}/study/series{i % 3}"), "T1w", "MATCHED", f"p{i // 3}", "v1")
            for i in range(count)]


def test_the_batch_label_of_many_series_is_one_edit_per_study_with_the_same_result():
    controller = Controller()
    controller.state.input_format, controller.state.classes = "dicom", {"AD": ""}
    controller.state.preview = _decisions(30)
    assert controller.assign_mapping_label(list(range(30)), "AD").ok
    expected = []
    for index in range(30):
        expected = apply_edit(expected, controller.state.preview, "dicom", index, "label", "AD", {"AD": ""})
    assert controller.state.mapping == expected


def test_the_batch_label_still_refuses_a_folder_shared_with_another_study():
    controller = Controller()
    controller.state.input_format, controller.state.classes = "dicom", {"AD": ""}
    controller.state.preview = [SeriesDecision(PurePosixPath("a/x/s1"), "T1w", "MATCHED", "p1", "v1"),
                                SeriesDecision(PurePosixPath("a/y/s1"), "T2w", "MATCHED", "p1", "v1"),
                                SeriesDecision(PurePosixPath("a/x/s2"), "T2w", "MATCHED", "p2", "v1")]
    check = controller.assign_mapping_label([0], "AD")
    assert not check.ok and controller.state.mapping == []


EXPORT_SCRIPT = r"""
import sys, time
sys.path.insert(0, "tests/qa")
from test_qa8_gui import _controller
from mri_dataset_tool.presentation.gui import app as app_module, theme

width, height, factor = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
real = theme.apply_theme
theme.apply_theme = lambda root, name=theme.DEFAULT_THEME: (root.tk.call("tk", "scaling", 96 / 72 * factor), real(root, name))[1]
app_module.App.winfo_screenwidth = lambda self: width
app_module.App.winfo_screenheight = lambda self: height
controller = _controller()
app = app_module.App(controller)
controller.step = "export"
app.refresh()
limit = height - theme.px(theme.TASKBAR)
end = time.monotonic() + 3
while time.monotonic() < end and app.winfo_height() > limit:
    app.update(); time.sleep(0.02)
for _ in range(5):
    app.update(); time.sleep(0.02)
view = app.views["export"]
card = view._summary.master
print(card.winfo_y() + card.winfo_height() <= view.winfo_height())
app.destroy()
"""


def _display() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure
        pytest.skip("No display available for Tk.")


@pytest.mark.parametrize(("screen", "factor"), [((1366, 768), 1.25), ((1280, 720), 1.5)])
def test_the_summary_card_of_step_6_stays_inside_the_window_on_small_screens(screen, factor):
    """Own process: ``tk scaling`` is kept by the display across the Tk roots of one process."""
    _display()
    result = subprocess.run([sys.executable, "-c", EXPORT_SCRIPT, str(screen[0]), str(screen[1]), str(factor)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, cwd=REPO)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1] == "True"


def _mapping_app(monkeypatch):
    from mri_dataset_tool.presentation.gui.app import App

    controller = Controller()
    controller.state.input_format, controller.state.classes = "dicom", {"AD": ""}
    controller.state.preview = _decisions(3)
    app = App(controller)  # shown: a cell editor needs its cell on screen; the focus is set by hand in the test
    controller.step = "mapping"
    app.refresh()
    app.update()
    monkeypatch.setattr(app, "report_callback_exception", lambda *error: pytest.fail("callback raised"))
    return app, controller, app.views["mapping"]


@pytest.mark.parametrize(("leave", "stored"), [("other widget", True), ("step change", True), ("other program", False)])
def test_free_text_of_a_mapping_cell_is_stored_inside_the_window_and_kept_when_another_program_takes_the_focus(
        monkeypatch, leave, stored):
    """QA8-05: a click elsewhere or a step change stores the text; Alt+Tab to another program leaves it open."""
    _display()
    app, controller, view = _mapping_app(monkeypatch)
    try:
        editor = view.start_edit(0, "participant")
        editor.delete(0, "end")
        editor.insert(0, "nuevo")
        if leave == "step change":
            app._go_back()
        else:  # the focus as Tk reports it once the editor lost it: the table, or none (another program)
            monkeypatch.setattr(view, "focus_get", lambda: view.tree if leave == "other widget" else None)
            editor.event_generate("<FocusOut>")
        app.update()
        assert any(row.participant == "nuevo" for row in controller.state.mapping) is stored
        assert (view._editor is None) is stored
    finally:
        app.destroy()
