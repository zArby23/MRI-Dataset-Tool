"""The GUI theme and frame (stage 5C, V1-V2): palettes, contrast and the literal sweep without a display;
the styled window, the step indicator, the footer and the welcome panel with Tk (skipped without a display)."""

import os
import re
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

import pytest

from mri_dataset_tool.presentation.gui import app as app_module
from mri_dataset_tool.presentation.gui import messages, theme, widgets
from mri_dataset_tool.presentation.gui.controller import Controller

GUI = Path(app_module.__file__).parent


# --- without a display ----------------------------------------------------------------------------


def test_contrast_ratio_matches_wcag_reference_values():
    assert theme.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert theme.contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    assert theme.contrast_ratio("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.01)  # the AA gray
    assert theme.contrast_ratio("#FFFFFF", "#767676") == theme.contrast_ratio("#767676", "#FFFFFF")


@pytest.mark.parametrize("name", theme.THEMES)
def test_every_text_pair_reaches_aa_contrast(name):
    palette = theme.PALETTES[name]
    low = {f"{fg}/{bg}": theme.contrast_ratio(palette[fg], palette[bg]) for fg, bg in theme.TEXT_PAIRS}
    assert min(low.values()) >= 4.5, {pair: round(r, 2) for pair, r in low.items() if r < 4.5}


@pytest.mark.parametrize("name", theme.THEMES)
def test_focus_ring_and_input_borders_reach_three_to_one(name):
    palette = theme.PALETTES[name]
    assert min(theme.contrast_ratio(palette[fg], palette[bg]) for fg, bg in theme.BORDER_PAIRS) >= 3


def test_header_gradient_runs_from_a_darker_top_to_the_background():
    for name, palette in theme.PALETTES.items():
        assert theme.mix(palette["header_top"], palette["bg"], 0) == palette["header_top"]
        assert theme.mix(palette["header_top"], palette["bg"], 1) == palette["bg"]
        assert theme.contrast_ratio(palette["header_top"], palette["bg"]) > 1.5  # clearly visible (V4e)
        assert theme.contrast_ratio(palette["hover"], palette["row_alt"]) > 1.1  # a hovered striped row shows
    light = theme.PALETTES["light"]  # darker than the background in the light theme
    assert theme.contrast_ratio(light["header_top"], "#FFFFFF") > theme.contrast_ratio(light["bg"], "#FFFFFF")
    assert theme.mix("#000000", "#FFFFFF", 0.5) == "#808080"


def test_font_family_prefers_verdana_then_dejavu_then_the_system():
    assert theme.pick_family({"Arial", "Verdana", "DejaVu Sans"}) == "Verdana"
    assert theme.pick_family({"DejaVu Sans", "Liberation Sans"}) == "DejaVu Sans"
    assert theme.pick_family({"Arial"}) is None


def test_close_question_asks_while_a_task_runs_and_on_the_close_button(monkeypatch):
    controller = Controller()
    assert controller.close_question() is None  # the window's X, no task: close at once
    assert controller.close_question(confirm=True) == ("CLOSE_CONFIRM_TITLE", "CLOSE_CONFIRM")
    monkeypatch.setattr(type(controller.worker), "busy", property(lambda self: True))
    assert controller.close_question() == controller.close_question(True) == ("CLOSE_TITLE", "CLOSE_WHILE_RUNNING")
    assert all(messages.text(code, "en") for code in ("CLOSE_CONFIRM_TITLE", "CLOSE_CONFIRM"))


def test_palettes_have_the_same_tokens_and_valid_colors():
    tokens = set(theme.PALETTES[theme.DEFAULT_THEME])
    assert theme.DEFAULT_THEME == "light" and set(theme.THEMES) == {"light", "dark"}
    for palette in theme.PALETTES.values():
        assert set(palette) == tokens
        assert all(re.fullmatch(r"#[0-9A-F]{6}", color) for color in palette.values())


def test_spacing_scales_with_the_display():
    assert theme.SPACE == {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24}
    assert theme._font_size(9, 3) == 12 and theme._font_size(-12, 3) == -16  # points / pixels


def test_views_and_app_have_no_visual_literals():
    """Colors, fonts, paddings, pixel sizes and animation steps come only from theme.py (the dark theme and
    scaling need it). Widths in characters (entries, combo boxes) scale with the font and are allowed."""
    pattern = re.compile(r"#[0-9a-fA-F]{3,6}\b|font=\(|wraplength=\d|length=\d|px\(\d|start\(\d")
    pads = re.compile(r"\b(?:padding|padx|pady)=(\([^)]*\)|\d+)")  # 0 is allowed: no space is not a size
    files = [path for path in (*GUI.glob("*.py"), *(GUI / "views").glob("*.py")) if path.name != "theme.py"]
    found = [f"{path.name}:{n}" for path in files
             for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
             if pattern.search(line) or any(re.search(r"\b[1-9]", pad) for pad in pads.findall(line))]
    assert found == []


def test_app_module_does_not_import_the_services():
    """The welcome panel shows while the services load: importing app.py must stay light."""
    code = ("import sys; import mri_dataset_tool.presentation.gui.app; "
            "print('mri_dataset_tool.presentation.gui.controller' in sys.modules, 'scipy' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.split() == ["False", "False"]


def test_version_is_unknown_without_package_metadata(monkeypatch):
    def missing(name):
        raise app_module.PackageNotFoundError(name)

    monkeypatch.setattr(app_module, "version", missing)
    assert app_module.app_version() is None


def test_step_states_follow_validation_and_format():
    controller = Controller()
    assert controller.step_states() == [("input", "current"), ("config", "pending"), ("run", "pending"),
                                        ("labels", "pending"), ("export", "pending")]  # BIDS: no mapping
    controller.state.input_format = "dicom"
    controller.complete("input")
    controller.go_next()
    assert controller.step_states()[:3] == [("input", "done"), ("config", "current"), ("mapping", "pending")]
    controller.reopen("input")
    assert controller.step_states()[0] == ("input", "pending")


def test_new_texts_exist_in_both_languages_without_placeholders_for_data():
    for code in ("APP_NAME", "WELCOME_SUBTITLE", "LOADING", "PRIVACY_SUMMARY", "THEME_light", "THEME_dark"):
        assert all(messages.text(code, language) for language in messages.LANGUAGES)


@pytest.mark.parametrize("language", messages.LANGUAGES)
def test_no_visible_text_names_internal_settings(language):
    """The window never names the key variable or configuration parameters (the manual does)."""
    forbidden = ("MRI_ANON_KEY", "allow_insufficient_memory", "max_output_voxels")
    assert [code for code, text in messages.CATALOG[language].items() if any(word in text for word in forbidden)] == []


# --- with a display -------------------------------------------------------------------------------


def _display() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")


def test_window_shows_name_steps_and_footer_and_switches_theme():
    _display()
    app = app_module.App(Controller())
    app.withdraw()
    try:
        app.update()
        header = app._header_canvas
        assert header._name == "MRI Dataset Tool"
        assert header.step_texts() == ["1 Entrada", "2 Configuración", "3 Ejecución", "4 Etiquetas",
                                       "5 Exportes y reporte"]
        assert header._steps[0][2] == "current"
        app.controller.complete("input")
        app.refresh()
        app._next.invoke()
        assert header.step_texts()[0] == f"1 Entrada {theme.DONE_MARK}"
        assert str(app._next.cget("style")) == "Accent.TButton" and str(app._status.cget("style")) == "Error.TLabel"
        narrow = widgets.HeaderCanvas(app)
        narrow.configure(width=theme.px(300))  # not packed: it lays out for its requested width
        narrow.set_content("MRI Dataset Tool", header._steps)
        assert len({narrow.coords(item)[1] for item, _ in narrow._items.values()}) > 1  # the steps wrap

        app._language_combo.current(1)
        app._language_chosen()
        assert app.controller.language == "en" and app._privacy.cget("text") == "Privacy and memory"

        log = app.views["run"].log
        app._set_theme("dark")
        assert str(log.cget("background")).upper() == theme.PALETTES["dark"]["surface"]
        assert app._theme_combo.get() == "Dark"
        app._set_theme("light")
        assert str(log.cget("background")).upper() == theme.PALETTES["light"]["surface"]
    finally:
        app.destroy()


def _wait(app, condition, limit: float = 60.0) -> None:
    """Process Tk events until *condition* holds; the limit is generous (a loaded machine runs the full suite)."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        app.update()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def test_welcome_panel_until_startup_finishes_then_the_first_step(monkeypatch):
    _display()
    release = __import__("threading").Event()

    def startup():
        release.wait(10)
        return Controller

    app = app_module.App(startup=startup)
    app.withdraw()
    try:
        app.update()
        assert app.controller is None and app._welcome_status.cget("text") == "Cargando…"
        assert app._welcome_privacy.cget("text") == messages.text("PRIVACY_SUMMARY")
        assert str(app._next.cget("state")) == "disabled"
        release.set()
        _wait(app, lambda: app.controller is not None)
        assert app._welcome is None and app.views["input"].winfo_manager() == "pack"
    finally:
        app.destroy()


def test_failed_startup_shows_only_the_error_type():
    _display()

    def startup():
        raise OSError("C:/secret/patient/path")

    app = app_module.App(startup=startup)
    app.withdraw()
    try:
        _wait(app, lambda: app._welcome_close.winfo_manager() == "pack")
        status = app._welcome_status.cget("text")
        assert "OSError" in status and "secret" not in status
        app.request_close()  # no controller: closes at once
    finally:
        try:
            app.destroy()
        except tk.TclError:
            pass


def test_rounded_button_behaves_like_a_ttk_button():
    _display()
    root = tk.Tk()
    root.withdraw()
    try:
        theme.apply_theme(root)
        calls = []
        button = widgets.Button(root, text="Go", command=lambda: calls.append(1) or "done")
        button.pack()
        root.update()
        assert button.invoke() == "done" and calls == [1] and button.cget("text") == "Go" == button["text"]
        button.configure(state="disabled", text="Stop")
        assert button.invoke() == "" and calls == [1] and str(button.cget("state")) == "disabled"
        assert button.instate(["disabled"]) and int(button.cget("takefocus")) == 0
        button.state(["!disabled"])
        assert button.cget("state") == "normal" and button.cget("takefocus") in (1, "1")
        assert {"<Key-space>", "<Key-Return>", "<Key-KP_Enter>"} <= set(button.bind())  # Space and Enter
        button._set(focus=True)  # a withdrawn window gets no real focus: the ring is drawn on FocusIn
        assert any(button.itemcget(item, "outline") == theme.color("focus") for item in button.find_all()
                   if button.type(item) == "polygon")
        width = int(button.cget("width"))
        button.configure(text="A much longer label")
        assert int(button.cget("width")) > width  # resized to its text (a language change)
    finally:
        root.destroy()


def test_close_button_of_the_last_step_asks_first(monkeypatch):
    _display()
    asked = []
    monkeypatch.setattr(app_module.dialogs, "ask_ok_cancel", lambda title, text, **_: asked.append(text) or False)
    app = app_module.App(Controller())
    app.withdraw()
    try:
        close = app.views["export"]._close
        assert close.cget("text") == "Cerrar"
        close.invoke()
        assert asked == ["¿Cerrar la herramienta?"] and app.winfo_exists()  # cancelled: still open
    finally:
        app.destroy()


def test_startup_and_every_step_redraw_in_both_themes_without_callback_errors(monkeypatch):
    """A TclError while starting or redrawing (drawn widgets, fonts, styles) would show only its type in the
    window: here it fails the test."""
    _display()
    errors = []
    monkeypatch.setattr(app_module.App, "report_callback_exception",
                        lambda self, exc, val, tb: errors.append(exc.__name__))
    app = app_module.App(startup=lambda: Controller)
    app.withdraw()
    try:
        app._set_theme("dark")  # during the welcome
        app._language.set("en")
        app._set_language()
        _wait(app, lambda: app.controller is not None)
        app.controller.state.input_format = "dicom"
        for step in ("input", "config", "mapping", "run", "labels", "export"):
            app.controller.step = step
            for name in theme.THEMES:
                app._set_theme(name)
                app.update()
        app.views["input"]._formats.choose("nifti")
        app.update()
        assert app.views["input"].input_format.get() == "nifti"
        assert errors == [] and app._callback_error is None
    finally:
        app.destroy()


def _families(app) -> dict[str, set[str]]:
    """The font family each textual widget of the window really uses, by widget class."""
    from tkinter import font as tkfont
    from tkinter import ttk

    style, found = ttk.Style(app), {}

    def family(spec) -> str:
        return tkfont.Font(root=app, font=spec or "TkDefaultFont").actual("family")

    def walk(widget) -> None:
        if isinstance(widget, tk.Canvas):
            for item in widget.find_all():
                if widget.type(item) == "text":
                    found.setdefault("Canvas text", set()).add(family(widget.itemcget(item, "font")))
        elif isinstance(widget, (tk.Listbox, tk.Text, tk.Label)):
            found.setdefault(widget.winfo_class(), set()).add(family(widget.cget("font")))
        elif isinstance(widget, (ttk.Label, ttk.Entry, ttk.Combobox, ttk.Checkbutton, ttk.Treeview)):
            spec = str(widget.cget("font")) if "font" in widget.keys() else ""
            found.setdefault(widget.winfo_class(), set()).add(
                family(spec or style.lookup(str(widget.cget("style")) or widget.winfo_class(), "font")))
        for child in widget.winfo_children():
            walk(child)

    walk(app)
    found["Treeview.Heading"] = {family(style.lookup("Treeview.Heading", "font"))}
    return found


def test_every_text_of_the_window_uses_the_chosen_family():
    """Labels, entries, lists, the classes box, tables, drawn texts (header, pills, buttons, cards, status
    lines) and tooltips use the theme family; the native file choosers and title bar are not Tk's to style."""
    _display()
    from tkinter import font as tkfont

    app = app_module.App(Controller())
    app.withdraw()
    try:
        chosen = theme.pick_family(set(tkfont.families(app))) or tkfont.nametofont("TkDefaultFont").actual("family")
        app.controller.state.input_format = "dicom"
        for step in ("input", "config", "mapping", "run", "labels", "export"):
            app.controller.step = step
            app.refresh()
        tip = app.views["export"]._ml_info.tooltip
        tip.show()
        app.update()
        families = _families(app)
        tip.hide()
        assert {name: fams for name, fams in families.items() if fams != {chosen}} == {}
        assert {"Canvas text", "Text", "Listbox", "TEntry", "Treeview"} <= set(families)
    finally:
        app.destroy()


def test_tk_root_is_retried_only_when_its_library_fails_to_load(monkeypatch):
    """tests/conftest.py: a transient library load failure is retried (and reported); other errors are not."""
    _display()
    real, calls = tk._tkinter.create, []

    def flaky(*args):
        calls.append(1)
        if len(calls) < 3:
            raise tk.TclError("Can't find a usable tk.tcl in the following directories")
        return real(*args)

    monkeypatch.setattr(tk._tkinter, "create", flaky)
    with pytest.warns(UserWarning, match="Tk library load failed"):
        tk.Tk().destroy()
    assert len(calls) == 3

    def broken(*args):
        calls.append(1)
        raise tk.TclError("no display name and no $DISPLAY environment variable")

    calls.clear()
    monkeypatch.setattr(tk._tkinter, "create", broken)
    with pytest.raises(tk.TclError, match="no display name"):
        tk.Tk()
    assert len(calls) == 1


CLOSE_SCRIPT = """
import sys, threading
from mri_dataset_tool.presentation.gui import app as m
from mri_dataset_tool.presentation.gui.controller import Controller
release = threading.Event()
if sys.argv[1] == "welcome":
    window = m.App(startup=lambda: (release.wait(30), Controller)[1])
else:
    controller = Controller()
    window = m.App(controller)
    controller.start_task(lambda reporter: release.wait(30) and None, activity="run")
    window.refresh()
window.after(500, window.destroy)
window.mainloop()
# Tcl timers belong to the thread: a later root (the next window, the next test) would run a leftover one
import time, tkinter
later = tkinter.Tk()
end = time.monotonic() + 0.6
while time.monotonic() < end:
    later.update()
    time.sleep(0.02)
later.destroy()
release.set()
print("closed", flush=True)
"""


@pytest.mark.parametrize("moment", ["welcome", "task"])
def test_closing_with_a_running_bar_prints_no_tcl_errors(moment):
    """Closing while the welcome bar or the footer bar runs: no Tcl timer may run on the destroyed window."""
    if not os.environ.get("DISPLAY") and os.name != "nt":
        pytest.skip("No display available for Tk.")
    result = subprocess.run([sys.executable, "-c", CLOSE_SCRIPT, moment], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    assert result.returncode == 0 and result.stdout.strip() == "closed", result.stderr[-2000:]
    for error in ("application has been destroyed", "invalid command name", "Traceback", "bgerror"):
        assert error not in result.stderr
