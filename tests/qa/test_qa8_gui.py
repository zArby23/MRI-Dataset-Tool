"""QA8: adversarial audit of the look of the GUI (stage 5C). Report: docs/testing/qa_etapa8.md.

Small screens with display scaling, hostile texts (very long, emoji, RTL, CJK, combining marks) in the tables and
dialogs, a bigger system font, the real themed dialogs (stacked close questions), cell editors while the table
scrolls, the batch label of the mapping table with thousands of series and the report warnings of step 6. Known
defects are ``xfail(strict=True)`` with their finding id: they turn into failures once fixed, so the marker is
removed then. Only synthetic values; no file is written outside ``tmp_path``.
"""

import json
import string
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path, PurePosixPath
from tkinter import font as tkfont

import pytest

from mri_dataset_tool.application.services.dataset_ingest import SeriesDecision
from mri_dataset_tool.application.services.labels_table import LabelRow
from mri_dataset_tool.presentation.gui import app as app_module
from mri_dataset_tool.presentation.gui import messages, theme, widgets
from mri_dataset_tool.presentation.gui.controller import STEPS, Controller
from mri_dataset_tool.presentation.gui.worker import Done

REPO = Path(__file__).resolve().parents[2]
HOSTILE = ["Clase" + "x" * 300, " ".join(["palabra"] * 120), "Tumor🧠🔬👩‍⚕️", "ورم دماغي", "AD ورم 12",
           "é́ ñ", "脳腫瘍" * 40, "‮ABC"]


def _display() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError as error:  # only a missing display skips; any other Tk failure must fail the test
        if "no display name" not in str(error):
            raise
        pytest.skip("No display available for Tk.")


def _controller(rows: int = 20, values: list[str] | None = None) -> Controller:
    """A controller on step-3/5 data without reading any file: a DICOM preview and a label table."""
    values = values or [f"s{i}" for i in range(rows)]
    controller = Controller()
    controller.state.input_format = "dicom"
    controller.state.classes = {name: "" for name in (values if values[0] in HOSTILE else ["AD", "CN"])}
    controller.state.preview = [SeriesDecision(PurePosixPath(f"dir {i}/{value}/series"), "T1w", "MATCHED", f"p{i}", "v1")
                                for i, value in enumerate(values)]
    controller.state.label_rows = [LabelRow(f"p{i:02d}", "v1", None, "UNLABELED") for i in range(len(values))]
    controller.state.label_classes = list(controller.state.classes)
    controller.state.labels_available, controller.state.label_version = True, 1
    controller.state.label_counts = {"pairs": len(values), "labeled": 0, "foreign": 0, "invalid": 0}
    return controller


def _app(monkeypatch, controller: Controller, factor: float = 1.0, screen: tuple[int, int] | None = None):
    real = theme.apply_theme
    monkeypatch.setattr(theme, "apply_theme", lambda root, name=theme.DEFAULT_THEME: (
        root.tk.call("tk", "scaling", 96 / 72 * factor), real(root, name))[1])
    if screen is not None:
        monkeypatch.setattr(app_module.App, "winfo_screenwidth", lambda self: screen[0])
        monkeypatch.setattr(app_module.App, "winfo_screenheight", lambda self: screen[1])
    app = app_module.App(controller)
    app.views["labels"]._loaded_for = controller.state.dataset_root  # no dataset: the table is not reloaded
    app.errors = []
    app.report_callback_exception = lambda exc, val, tb: app.errors.append("".join(traceback.format_exception(exc, val, tb)))
    app.update()
    return app


def _past_the_right_edge(app) -> list[str]:
    edge = app.winfo_rootx() + app.winfo_width()
    found = []

    def walk(widget) -> None:
        if widget.winfo_ismapped() and widget.winfo_rootx() + widget.winfo_width() > edge + 1:
            found.append(f"{widget.winfo_class()} {widget}")
        for child in widget.winfo_children():
            if not isinstance(child, tk.Toplevel):
                walk(child)

    walk(app)
    return found


# --- without a display ----------------------------------------------------------------------------


def test_every_catalog_text_renders_with_its_own_placeholders():
    """Each key formats through ``messages.text`` with the names it uses (no stray braces), in both languages."""
    failures = []
    for language, catalog in messages.CATALOG.items():
        for code, template in catalog.items():
            if code == "REPORT_WARNING":  # QA8-02, below
                continue
            names = {field for _, field, _, _ in string.Formatter().parse(template) if field}
            try:
                shown = messages.text(code, language, **{name: 7 for name in names})
            except Exception as error:
                failures.append((language, code, type(error).__name__))
                continue
            if "{" in shown or "}" in shown:
                failures.append((language, code, "brace"))
    assert failures == []


def test_a_report_warning_without_its_own_text_is_shown(tmp_path):
    """Report warnings without a specific text (UNLABELED_SESSIONS, NON_FINITE_VOXELS...) use REPORT_WARNING."""
    controller = Controller()
    controller._export_kind = "report"
    controller._new_report = (tmp_path / "report_2", ["dataset_report.json"], {"UNLABELED_SESSIONS": 2})
    lines = controller.export_finished(Done({"files": 1}))
    shown = [controller.text(code, **values) for code, values in lines]  # what ExportStep.refresh_texts does
    assert any("UNLABELED_SESSIONS" in line and "2" in line for line in shown)


def _rows_handed_to_apply_edit(monkeypatch, series: int) -> int:
    """Rows ``apply_edit`` receives, summed over its calls, when every DICOM series (3 per study) is selected.
    ``apply_edit`` scans the rows it gets for each call, so this counts the work, not the seconds."""
    from mri_dataset_tool.presentation.gui import controller as controller_module

    handed = []
    real = controller_module.apply_edit
    monkeypatch.setattr(controller_module, "apply_edit", lambda mapping, rows, *rest: (
        handed.append(len(rows)), real(mapping, rows, *rest))[1])
    controller = Controller()
    controller.state.input_format, controller.state.classes = "dicom", {"AD": ""}
    controller.state.preview = [SeriesDecision(PurePosixPath(f"pat{i // 3:05d}/study/series{i % 3}"), "T1w", "MATCHED",
                                               f"p{i // 3}", "v1") for i in range(series)]
    assert controller.assign_mapping_label(list(range(series)), "AD").ok
    return sum(handed)


def test_batch_label_of_the_mapping_table_scales_with_the_selection(monkeypatch):
    """«Assign label to the selection» runs on the main thread (measured before the fix: 20 s for 1000 series, 83 s
    for 2000). Deterministic: four times the series must hand ``apply_edit`` about four times the rows (linear),
    not sixteen times (quadratic)."""
    small, large = _rows_handed_to_apply_edit(monkeypatch, 300), _rows_handed_to_apply_edit(monkeypatch, 1200)
    assert large <= 6 * small, (small, large)


# --- with a display -------------------------------------------------------------------------------


@pytest.mark.parametrize(("screen", "factor"), [((1366, 768), 1.25), ((1280, 720), 1.25), ((1280, 720), 1.5)])
def test_the_status_line_of_steps_3_and_5_stays_visible_on_small_screens(screen, factor):
    """There the window is limited to the screen: the tables must give the room, not the message line. Each case
    runs in its own process: ``tk scaling`` is kept by the display across Tk roots of one process, and a later root
    computes its default font from it, so the text would not grow with the simulated scaling."""
    _display()
    result = subprocess.run([sys.executable, "-c", SMALL_SCREEN_SCRIPT, str(screen[0]), str(screen[1]), str(factor)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, cwd=REPO)
    assert result.returncode == 0, result.stderr[-2000:]
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


SMALL_SCREEN_SCRIPT = r"""
import json, sys, time
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
app.views["labels"]._loaded_for = controller.state.dataset_root
limit = height - theme.px(theme.TASKBAR)
cut = []
for step in ("mapping", "labels"):
    controller.step = step
    app.refresh()
    status = app.views[step]._status
    status.configure(text="Mensaje de prueba.\nSegunda l\u00ednea.", severity="error")
    end = time.monotonic() + 3  # the window manager applies the limited height a little later under load
    while time.monotonic() < end and app.winfo_height() > limit:
        app.update(); time.sleep(0.02)
    for _ in range(5):
        app.update(); time.sleep(0.02)
    assert app.winfo_height() <= limit
    if status._label.winfo_height() + 1 < status._label.winfo_reqheight():
        cut.append([step, status._label.winfo_height(), status._label.winfo_reqheight()])
app.destroy()
print(json.dumps(cut))
"""


def test_hostile_texts_in_the_tables_and_dialogs_stay_inside_the_window(monkeypatch):
    """Very long, emoji, RTL, CJK and combining texts in paths, classes and labels: no Tcl error, nothing past the
    right edge, cut locations with «…» that fit their column, and a dialog no wider than the window."""
    _display()
    controller = _controller(values=HOSTILE)
    app = _app(monkeypatch, controller)
    try:
        for step in ("mapping", "labels"):
            controller.step = step
            app.refresh()
            app.update()
            assert _past_the_right_edge(app) == [], step
        view = app.views["mapping"]
        font = tkfont.nametofont("TkDefaultFont", root=app)
        width = int(view.tree.column("location", "width"))
        assert all(font.measure(view.tree.set(str(i), "location")) <= width for i in range(len(HOSTILE)))
        controller.step = "labels"
        app.refresh()
        app.views["labels"]._status.configure(text=HOSTILE[0], severity="error")
        app.update()
        assert _past_the_right_edge(app) == []
        sizes = []

        def measure_and_close() -> None:
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and hasattr(w, "buttons"))
            dialog.update_idletasks()
            sizes.append(dialog.winfo_width())
            dialog.close(False)

        app.after(300, measure_and_close)
        app.ask("CONFIRM_TITLE", controller.text("CONFIRM_ASSIGN_UNLABELED", label=HOSTILE[0], count=3))
        assert sizes and sizes[0] <= app.winfo_width()
        assert app.errors == []
    finally:
        app.destroy()


@pytest.mark.parametrize("points", [11, 13])
def test_a_bigger_system_font_keeps_every_step_inside_the_fixed_window(monkeypatch, points):
    """Windows «Make text bigger» enlarges the system font without changing the DPI: the 960 px window keeps
    every control inside, in both languages."""
    _display()
    real = theme.apply_theme

    def bigger(root, name=theme.DEFAULT_THEME):
        for font in theme.TK_FONTS:
            tkfont.nametofont(font, root=root).configure(size=points)
        return real(root, name)

    monkeypatch.setattr(theme, "apply_theme", bigger)
    controller = _controller()
    app = app_module.App(controller)
    app.views["labels"]._loaded_for = None
    try:
        for language in messages.LANGUAGES:
            app._language.set(language)
            app._set_language()
            for step in STEPS:
                controller.step = step
                app.refresh()
                app.update()
                assert _past_the_right_edge(app) == [], (points, language, step)
    finally:
        app.destroy()


def test_a_cell_editor_does_not_float_over_another_row_after_scrolling(monkeypatch):
    """Open the editor of row 0, scroll the table to the end: the editor must not stay over another row (its
    value would go to row 0 while the user reads the row under it)."""
    _display()
    controller = _controller(rows=60)
    app = _app(monkeypatch, controller)
    try:
        controller.step = "mapping"
        app.refresh()
        app.update()
        view = app.views["mapping"]
        editor = view.start_edit(0, "participant")
        view.tree.yview_moveto(1.0)
        app.update()
        row_visible = bool(view.tree.bbox("0", "participant"))
        assert row_visible or not (editor.winfo_exists() and editor.winfo_ismapped())
    finally:
        app.destroy()


def _second_x_while_a_close_question_is_open(monkeypatch) -> tuple[list, list[str]]:
    """The window's X twice during a task (a real, unreplaced question): how many questions are open when the
    user answers «OK», and the callback errors.

    Driven by state, not by the clock (fixed 200/600/1000 ms timers raced under load): the second X comes once the
    first question is on screen, and «OK» right after it. The question does not take the system focus here
    (``focus_set`` instead of ``focus_force``), so a key or click meant for another window cannot answer it."""
    monkeypatch.setattr(tk.Misc, "focus_force", tk.Misc.focus_set)
    controller = Controller()
    app = _app(monkeypatch, controller)
    release = threading.Event()
    controller.start_task(lambda reporter: release.wait(30) and None, activity="run")
    app.refresh()
    seen = []

    def questions():
        return [w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and hasattr(w, "buttons")]

    def second_x() -> None:
        if not any(w.winfo_viewable() for w in questions()):
            app.after(20, second_x)
            return
        app.after(20, accept_last)  # scheduled first: without the guard the second X opens a question and waits
        app.request_close()

    def accept_last() -> None:
        seen.append(len(questions()))
        questions()[-1].close(True)

    try:
        app.after(0, app.request_close)
        app.after(20, second_x)
        app.after(10000, lambda: (seen.append("timeout"), app.destroy()))  # a safety net
        app.mainloop()
        return seen or ["closed before «OK»"], app.errors
    finally:
        release.set()
        if not app._closed:
            app.destroy()


def test_a_second_close_question_while_the_first_is_open_closes_cleanly(monkeypatch):
    """Whether one or two questions are open, answering «OK» closes the window without a callback error."""
    _display()
    seen, errors = _second_x_while_a_close_question_is_open(monkeypatch)
    assert seen in ([1], [2]) and errors == []


def test_the_x_while_a_close_question_is_open_asks_only_once(monkeypatch):
    _display()
    seen, errors = _second_x_while_a_close_question_is_open(monkeypatch)
    assert seen == [1] and errors == []


# --- QA8-05: free text of a mapping cell (step 3) -------------------------------------------------------


def _typed_participant(app, controller, text: str = "nuevo"):
    """Step 3 with the editor of a free-text cell open and *text* typed, not confirmed."""
    controller.step = "mapping"
    app.refresh()
    app.update()
    view = app.views["mapping"]
    editor = view.start_edit(0, "participant")
    editor.focus_force()
    editor.delete(0, "end")
    editor.insert(0, text)
    app.update()
    return view, editor


def _stored(controller, text: str = "nuevo") -> bool:
    return any(row.participant == text for row in controller.state.mapping)


def test_free_text_of_a_mapping_cell_is_kept_when_the_editor_loses_the_focus(monkeypatch):
    _display()
    controller = _controller()
    app = _app(monkeypatch, controller)
    try:
        view, _ = _typed_participant(app, controller)
        view.tree.focus_force()  # a click elsewhere
        for _ in range(5):
            app.update()
            time.sleep(0.02)
        assert _stored(controller) and app.errors == []
    finally:
        app.destroy()


def test_free_text_of_a_mapping_cell_is_kept_when_the_step_changes(monkeypatch):
    _display()
    controller = _controller()
    app = _app(monkeypatch, controller)
    try:
        view, _ = _typed_participant(app, controller)
        app._go_back()  # «Back» or the shortcuts: the same move
        app.update()
        assert _stored(controller) and view._editor is None and app.errors == []
    finally:
        app.destroy()


def test_escape_cancels_the_free_text_of_a_mapping_cell(monkeypatch):
    """Esc keeps the cancelling behavior the manual describes: nothing is stored and the editor goes away."""
    _display()
    controller = _controller()
    app = _app(monkeypatch, controller)
    try:
        view, editor = _typed_participant(app, controller)
        editor.event_generate("<Escape>")
        for _ in range(5):
            app.update()
            time.sleep(0.02)
        assert not _stored(controller) and view._editor is None and app.errors == []
    finally:
        app.destroy()
