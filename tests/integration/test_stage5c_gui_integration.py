"""Integration (stage 5C): the themed window walked with real services leaks nothing and still closes cleanly.

The figures, output trees and CLI byte equivalence of the wizard are those of ``test_stage5b_gui_integration``
(run unchanged: 5C only touches ``presentation/gui``). Here the real window (``App``) walks the synthetic DICOM
input with planted PHI through the six steps; every text the window shows (title, labels, buttons, status lines,
logs, tables, drawn texts of the header and cards, tooltips, dialogs, the footer activity, the closing summary,
a failed «Open the output folder»), in both languages and both themes, is swept for the planted values, the
paths and exception messages. The only path allowed is the location column of the mapping table and its
tooltip (as in 5B). The worker queue and the footer activity carry only codes and integers. The same finished
wizard is redrawn at 100/125/150 % scaling without anything passing the fixed window, and closing (the
window's X during the welcome, during a task, with label edits applied or failing to apply) prints no Tcl
error. Tk tests are skipped without a display.
"""

import dataclasses
import json
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

import pytest

from mri_dataset_tool.presentation.gui import app as app_module
from mri_dataset_tool.presentation.gui import dialogs, messages, theme, widgets
from mri_dataset_tool.presentation.gui.controller import Activity, Controller
from mri_dataset_tool.presentation.gui.views import export_step
from mri_dataset_tool.presentation.gui.worker import Done, Failed, ReportReadError, Skipped, Status, StudyFailed
from test_stage5_ingest_integration import CONFIG, INPUT_MARKER, KEY, SECRETS, UID, _dicom_input

REPO = Path(__file__).resolve().parents[2]
STEPS = ("input", "config", "mapping", "run", "labels", "export")
PLANTED_ERROR = "PlantedErrorMessage"  # the message of an exception the window must never show
INTERNAL = ("MRI_ANON_KEY", "allow_insufficient_memory", "max_output_voxels")
# The values a message may receive (reviewed one by one): counts, sizes, codes, type names, step texts, classes
# and names the tool writes (``folder`` = ml_exports_N, ``name`` = a report file). A new one needs a review: a
# path or an id could only reach a text through a placeholder.
PLACEHOLDERS = {
    "classes", "code", "codes", "count", "counts", "error_type", "errors", "failed", "files", "folder", "foreign",
    "free", "header", "invalid", "label", "labeled", "labels", "name", "number", "pairs", "participants",
    "required", "rows", "series", "skipped", "stage", "studies", "title", "total", "unreadable", "version",
    "warning",  # a fixed code of the dataset report (UNREADABLE_FILES...), never text read from the data
}
CODE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _native_scaling() -> float | None:
    """Tk's scaling of a fresh root, read at import (collection runs before any test scales a root)."""
    try:
        root = tk.Tk()
    except tk.TclError:  # no display: the Tk tests skip
        return None
    try:
        return float(root.tk.call("tk", "scaling"))
    finally:
        root.destroy()


NATIVE_SCALING = _native_scaling()


def _reset_scaling() -> None:
    """Give the next roots the native scaling again (QA8-11): a root inherits the ``tk scaling`` of the
    previous one in this process and computes its fonts from it while it is created, so only a root created
    after this sees native text sizes (resetting it after creating the root, as conftest does, is too late
    for the fonts)."""
    if NATIVE_SCALING is None:
        return
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", NATIVE_SCALING)
    finally:
        root.destroy()


@pytest.fixture
def native_display():
    """Native scaling before and after the test (QA8-11); the theme scale is restored by conftest (QA8-07)."""
    _reset_scaling()
    yield
    _reset_scaling()


def _display() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure (QA8-10)
        pytest.skip("No display available for Tk.")


# --- without a display ----------------------------------------------------------------------------


@pytest.mark.parametrize("language", messages.LANGUAGES)
def test_the_catalog_names_no_internal_setting_and_takes_no_path_or_id(language):
    """Every text of both languages: no planted value, no internal name, no severity prefix of its own, and
    only placeholders for counts, codes and type names (a path or an id could only arrive through one)."""
    catalog = messages.CATALOG[language]
    assert set(catalog) == set(messages.CATALOG["en" if language == "es" else "es"])
    for code, text in catalog.items():
        assert not [word for word in (*INTERNAL, *SECRETS, UID) if word in text], code
        if not code.startswith("PREFIX_"):
            assert not text.lstrip().startswith(("Error:", "Aviso:", "Listo:", "Warning:", "Done:")), code
        fields = set(re.findall(r"{(\w+)", text))
        assert fields <= PLACEHOLDERS, (code, fields - PLACEHOLDERS)


# --- the real window, walked once (module scope: the run is the stage 3 pipeline) ------------------


def _texts(widget: tk.Misc, mapping_tree: ttk.Treeview | None) -> list[str]:
    """Every text *widget* and its children show, except what the user typed (entries) and the location
    column of the mapping table (relative paths, allowed in 5B)."""
    found: list[str] = []
    if isinstance(widget, tk.Tk | tk.Toplevel):
        found.append(widget.title())
    if isinstance(widget, widgets.StatusLine | widgets.RoundedButton):
        found.append(widget.shown_text())
    elif isinstance(widget, tk.Canvas):
        found += [str(widget.itemcget(item, "text")) for item in widget.find_all() if widget.type(item) == "text"]
    elif isinstance(widget, tk.Listbox):
        found += [str(line) for line in widget.get(0, "end")]
    elif isinstance(widget, ttk.Treeview):
        columns = list(widget["columns"])
        found += [str(widget.heading(column, "text")) for column in columns]
        for item in widget.get_children():
            found += [str(value) for column, value in zip(columns, widget.item(item, "values"))
                      if not (widget is mapping_tree and column == "location")]
    elif isinstance(widget, ttk.Combobox):
        found += [str(value) for value in widget.cget("values")]
    elif isinstance(widget, tk.Text):
        found.append(widget.get("1.0", "end"))
    elif not isinstance(widget, ttk.Entry | tk.Entry):
        try:
            found.append(str(widget.cget("text")))
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        found += _texts(child, mapping_tree)
    return [text for text in found if text.strip()]


def _overflow(app) -> list[str]:
    """Mapped widgets of the current step that pass the right or bottom edge of the window."""
    right, bottom = app.winfo_rootx() + app.winfo_width(), app.winfo_rooty() + app.winfo_height()
    found = []

    def walk(widget) -> None:
        if widget.winfo_ismapped() and (widget.winfo_rootx() + widget.winfo_width() > right + 1
                                        or widget.winfo_rooty() + widget.winfo_height() > bottom + 1):
            found.append(f"{widget.winfo_class()} {widget}")
        for child in widget.winfo_children():
            if not isinstance(child, tk.Toplevel):
                walk(child)

    walk(app.views[app.controller.step])
    for widget in (app._next, app._back, app._privacy, app._activity_bar):
        walk(widget)
    return found


def _settle(app, timeout: float = 600) -> None:
    app.controller.worker.join(timeout)
    app._poll()
    app.update()


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory):
    """Steps 1→6 in the real window on the DICOM input with planted PHI; everything shown is recorded."""
    _display()
    _reset_scaling()  # built at native scaling whatever ran before (QA8-11)
    tmp = tmp_path_factory.mktemp("e8")
    record = {"texts": [], "events": [], "activity": [], "dialogs": [], "tooltips": [], "callback_errors": [],
              "location_tips": []}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MRI_ANON_KEY", KEY)
        patch.chdir(REPO)
        source = _dicom_input(tmp / INPUT_MARKER / "dicom")
        output = tmp / "out"
        tips: list[widgets.Tooltip] = []
        real_tip = widgets.Tooltip.__init__
        patch.setattr(widgets.Tooltip, "__init__", lambda self, *a, **k: (real_tip(self, *a, **k), tips.append(self))[0])

        def asked(kind):
            def answer(title, text, *args, **kwargs):
                record["dialogs"].append((kind, title, text, [label for _, label in kwargs.get("choices", args[0] if args else [])]
                                          if kind == "choice" else []))
                return {"ok_cancel": True, "choice": "cancel", "sections": None}[kind]
            return answer

        patch.setattr(dialogs, "ask_ok_cancel", asked("ok_cancel"))
        patch.setattr(dialogs, "ask_choice", asked("choice"))
        patch.setattr(dialogs, "show_sections", lambda parent, title, sections, close, section=None: record["dialogs"].append(
            ("sections", title, "\n".join(h + "\n" + "\n".join(p) for _, h, p in sections), [close])))

        def failing_open(path):
            raise OSError(f"{PLANTED_ERROR} {path}")

        patch.setattr(export_step, "open_folder", failing_open)

        controller = Controller()
        real_poll = controller.poll

        def poll():
            events = real_poll()
            record["events"] += events
            record["activity"].append((dataclasses.asdict(controller.activity), controller.activity_text()))
            return events

        controller.poll = poll
        app = app_module.App(controller)
        patch.setattr(app, "report_callback_exception",
                      lambda exc, val, tb: record["callback_errors"].append(exc.__name__))
        mapping_tree = app.views["mapping"].tree

        def shown() -> None:
            app.update()
            record["texts"] += _texts(app, mapping_tree)
            record["activity"].append((dataclasses.asdict(controller.activity), app._activity.cget("text")))

        try:
            views = app.views
            app.update()
            views["input"].input_dir.set(str(source))
            views["input"].input_format.set("dicom")
            views["input"].output_dir.set(str(output))
            views["input"].validate()
            shown()
            _settle(app, 60)
            shown()
            app._next.invoke()
            views["config"].config_path.set(str(CONFIG))
            views["config"].classes.insert("1.0", "AD=Alzheimer\nCN=Control")
            views["config"].validate()
            app.refresh()
            app.show_privacy("memory")  # the step 2 link
            shown()
            app._next.invoke()
            assert controller.step == "mapping"
            views["mapping"].run_preview()
            shown()  # the footer shows the preview activity
            _settle(app)
            shown()
            record["location_tips"] = [row.location.as_posix() for row in controller.state.preview]
            app._next.invoke()
            assert controller.step == "run"
            views["run"].run()
            shown()
            _settle(app)
            shown()
            assert controller.state.dataset_root == output / "dataset"
            app._next.invoke()
            _settle(app)  # step 5 loads its table in the worker
            labels = views["labels"]
            labels.batch_class.set("CN")
            labels.assign_unlabeled()  # asks first (recorded, accepted)
            shown()
            app._go_next()  # pending edits: the three-button question (answered «Cancel»: stays)
            assert controller.step == "labels"
            app.request_close()  # the window's X with pending edits: the same question, the window stays
            labels.run("apply")
            _settle(app)
            labels.run("finalize")
            _settle(app)
            shown()
            app._next.invoke()
            assert controller.step == "export"
            views["export"].write_ml()
            _settle(app)
            views["export"].report_dir.set(str(tmp / "report2"))
            views["export"].write_report()
            _settle(app)
            views["export"]._open.invoke()  # the file manager fails with a planted message
            shown()
            record["tooltips"] = [text for text in (tip.text() for tip in tips) if text]  # while the window lives
            app.request_close(confirm=True)  # the «Close» button asks (recorded, answered OK → closes)
            assert app._closed
        finally:
            if not app._closed:
                app.destroy()
        # The finished wizard again in a new window: both languages, both themes, every step.
        app = app_module.App(controller)
        patch.setattr(app, "report_callback_exception",
                      lambda exc, val, tb: record["callback_errors"].append(exc.__name__))
        record["redraw_overflow"] = []
        try:
            for name in theme.THEMES:
                app._set_theme(name)  # in place: the existing widgets follow
                for language in messages.LANGUAGES:
                    app._language.set(language)
                    app._set_language()
                    for step in STEPS:
                        controller.step = step
                        app.refresh()
                        _settle(app, 60)
                        record["texts"] += _texts(app, app.views["mapping"].tree)
                        record["redraw_overflow"] += [(name, language, step, w) for w in _overflow(app)]
            record["window"] = (app.winfo_width(), app.winfo_height(), app.resizable(),
                                (theme.px(theme.WINDOW[0]), theme.px(theme.WINDOW[1])))  # px() of this window
            record["linespace"] = tkfont.nametofont("TkDefaultFont", root=app).metrics("linespace")
        finally:
            app.destroy()
    return {"tmp": tmp, "output": output, "source": source, "controller": controller, **record}


def _forbidden(walked) -> list[str]:
    tmp = walked["tmp"]
    return [*SECRETS, UID, PLANTED_ERROR, str(tmp), tmp.as_posix(), str(walked["source"])]


def test_the_window_walk_built_the_dataset_and_its_exports(walked):
    controller, output = walked["controller"], walked["output"]
    summary = controller.state.run_summary
    assert {key: summary[key] for key in ("studies", "series", "participants")} == {
        "studies": 4, "series": 7, "participants": 3}  # the figures of the 5B DICOM walk
    assert controller.state.labels_closed
    assert json.loads((output / "dataset" / "splits.json").read_text(encoding="utf-8"))["labels_finalized"] is True
    assert len(list((walked["tmp"] / "report2").iterdir())) == 4
    assert walked["callback_errors"] == []


def test_nothing_the_window_shows_leaks_phi_paths_or_exception_messages(walked):
    forbidden = [word.lower() for word in _forbidden(walked)]
    texts = [*walked["texts"], *walked["tooltips"], *[text for _, text in walked["activity"]],
             *[" ".join([title, text, *labels]) for _, title, text, labels in walked["dialogs"]]]
    assert len(texts) > 200  # the sweep really saw the window
    leaked = {word for text in texts for word in forbidden if word in text.lower()}
    assert not leaked
    assert not [text for text in texts if any(word in text for word in INTERNAL)]
    joined = "\n".join(texts)
    controller = walked["controller"]
    # the new texts of 5C were there: closing summary, failed open, activity, the three-button questions
    counts = {key: controller.state.run_summary.get(key, 0) for key in ("studies", "series", "participants", "skipped")}
    for code, values in (("SUMMARY_DONE", counts), ("OPEN_FAILED", {"error_type": "OSError"})):
        assert any(messages.text(code, language, **values) in joined for language in messages.LANGUAGES), code
    assert {kind for kind, *_ in walked["dialogs"]} == {"ok_cancel", "choice", "sections"}
    assert any(text for _, text in walked["activity"])  # a running task showed its activity


def test_only_the_mapping_location_shows_a_relative_path(walked):
    """The location column and its tooltip show the relative path of each series (5B decision); it never
    holds the input root, and no other text does."""
    source = walked["source"]
    locations = walked["location_tips"]
    assert locations and not [loc for loc in locations if str(source) in loc or source.as_posix() in loc]
    # the locations carry planted folder names: the sweep of the other texts would see them if they leaked
    assert any(secret in loc for loc in locations for secret in SECRETS)
    texts = [*walked["texts"], *walked["tooltips"]]
    assert not [text for text in texts for loc in locations if loc in text]


def test_the_queue_and_the_activity_hold_only_codes_and_integers(walked):
    events = walked["events"]
    assert {type(event) for event in events} >= {Status, Done}
    for event in events:
        assert isinstance(event, Status | Skipped | StudyFailed | ReportReadError | Failed | Done)
        for name, value in dataclasses.asdict(event).items():
            if isinstance(value, dict):
                assert all(CODE.fullmatch(k) and type(v) is int for k, v in value.items()), (event, name)
            elif value is not None:
                assert type(value) is int or (isinstance(value, str) and CODE.fullmatch(value)), (event, name)
    for activity, _ in walked["activity"]:
        assert set(activity) == {field.name for field in dataclasses.fields(Activity)}
        assert activity["task"] is None or CODE.fullmatch(activity["task"])
        assert all(type(activity[key]) is int for key in ("skipped", "failed", "unreadable"))
        stage = activity["stage"]
        assert stage is None or (CODE.fullmatch(stage["stage"]) and all(type(v) is int for v in stage["counts"].values()))


def test_both_themes_and_languages_redraw_every_step_inside_the_fixed_window(walked):
    assert walked["redraw_overflow"] == []
    width, height, resizable, expected = walked["window"]
    assert (width, height) == expected and resizable == (False, False)


@pytest.mark.parametrize("factor", [1.25, 1.5])
def test_the_finished_wizard_fits_at_each_display_scaling(walked, native_display, monkeypatch, factor):
    """At 125 and 150 % of the native scaling (a 1920x1080 screen) the text really grows and nothing passes
    the window."""
    real = theme.apply_theme
    monkeypatch.setattr(theme, "apply_theme", lambda root, name=theme.DEFAULT_THEME: (
        root.tk.call("tk", "scaling", NATIVE_SCALING * factor), real(root, name))[1])
    monkeypatch.setattr(app_module.App, "winfo_screenwidth", lambda self: 1920)
    monkeypatch.setattr(app_module.App, "winfo_screenheight", lambda self: 1080)
    controller = walked["controller"]
    app = app_module.App(controller)
    try:
        assert app.winfo_height() <= 1080 - theme.px(theme.TASKBAR) and app.winfo_width() <= 1920
        assert theme.px(100) == round(100 * factor)
        # the text grows with the scaling (inside the suite too: a root recomputes its fonts at creation)
        linespace = tkfont.nametofont("TkDefaultFont", root=app).metrics("linespace")
        # measured at 100/125/150/200 %: 14, 18, 22, 29 px, so never below native * factor; the 1 px is for the
        # whole-point rounding of other platforms' fonts, and the text must grow whatever the rounding
        assert walked["linespace"] < linespace >= walked["linespace"] * factor - 1, (linespace, walked["linespace"], factor)
        overflow = []
        for step in STEPS:
            controller.step = step
            app.refresh()
            _settle(app, 60)
            overflow += [(step, widget) for widget in _overflow(app)]
        assert overflow == []
    finally:
        app.destroy()


# --- closing in a subprocess: no Tcl error after the window is gone -------------------------------

CLOSE_SCRIPT = r"""
import shutil, sys, threading, time, tkinter
from pathlib import Path
from mri_dataset_tool.application.services.labels import write_label_template
from mri_dataset_tool.presentation.gui import app as m, dialogs
from mri_dataset_tool.presentation.gui.controller import Controller

case, base = sys.argv[1], Path(sys.argv[2])
release = threading.Event()
asked = []
dialogs.ask_ok_cancel = lambda *a, **k: asked.append("ok_cancel") or True
dialogs.ask_choice = lambda *a, **k: asked.append("choice") or "apply"
if case == "welcome":
    window = m.App(startup=lambda: (release.wait(30), Controller)[1])
elif case == "task":
    controller = Controller()
    window = m.App(controller)
    controller.start_task(lambda reporter: release.wait(30) and None, activity="run")
    window.refresh()
else:  # apply_ok | apply_fail: label edits pending on step 5
    root = base / "dataset"
    for index in range(3):
        anat = root / f"sub-p{index}" / "ses-v1" / "anat"
        anat.mkdir(parents=True)
        (anat / f"sub-p{index}_ses-v1_T1w.nii.gz").write_bytes(b"")
    write_label_template(root, {"AD": "", "CN": ""})
    controller = Controller()
    controller.state.dataset_root, controller.state.output_dir, controller.step = root, base, "labels"
    window = m.App(controller)
    end = time.monotonic() + 30
    while time.monotonic() < end and (controller.worker.busy or not controller.state.label_rows):
        window.update(); time.sleep(0.05)
    assert controller.assign_labels([0], "AD").ok
    window.refresh()
    if case == "apply_fail":
        shutil.rmtree(root)  # the apply task does not find the dataset
if case == "apply_fail":
    window.request_close()  # the window's X: «Apply and close»
    end = time.monotonic() + 30
    while time.monotonic() < end and (controller.worker.busy or window._after_apply is not None):
        window.update(); time.sleep(0.05)
    shown = window.views["labels"]._status
    print("open", window._closed, controller.pending_label_edits(), shown.cget("severity"), flush=True)
    window.destroy()
else:
    window.after(400, window.request_close)  # the window's X
    window.mainloop()  # returns once the window is destroyed
    if case == "apply_ok":
        print("labels", "AD" in (base / "dataset" / "labels.tsv").read_text(encoding="utf-8"), flush=True)
# Tcl timers belong to the thread: a later root would run a leftover one of the destroyed window
later = tkinter.Tk()
end = time.monotonic() + 0.6
while time.monotonic() < end:
    later.update(); time.sleep(0.02)
later.destroy()
release.set()
print("closed", ",".join(asked), flush=True)
"""


@pytest.mark.parametrize(("case", "expected"), [
    ("welcome", ["closed"]),  # no controller yet: closes at once
    ("task", ["closed ok_cancel"]),  # a running task asks first
    ("apply_ok", ["labels True", "closed choice"]),  # applied, then closed
    ("apply_fail", ["open False 1 error", "closed choice"]),  # the apply failed: open, edit kept, error shown
])
def test_closing_with_the_window_x_prints_no_tcl_error(tmp_path, case, expected):
    _display()
    result = subprocess.run([sys.executable, "-c", CLOSE_SCRIPT, case, str(tmp_path)], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=180, cwd=REPO)
    assert result.returncode == 0, result.stderr[-2000:]
    assert [line.strip() for line in result.stdout.splitlines()] == expected,(result.stdout, result.stderr[-2000:])
    for error in ("application has been destroyed", "invalid command name", "Traceback", "bgerror", "TclError"):
        assert error not in result.stderr, result.stderr[-2000:]
