"""Stage 5C V5: display scaling (simulated 100/125/150 % on a 1920x1080 screen), keyboard focus order, initial
focus, shortcuts and the Windows DPI declaration. The Tk tests are skipped without a display; the window is
shown because keyboard focus and real geometry need it."""

import time
import tkinter as tk

import pytest

from mri_dataset_tool.presentation.gui import app as app_module
from mri_dataset_tool.presentation.gui import theme
from mri_dataset_tool.presentation.gui.controller import Controller

STEPS = ("input", "config", "mapping", "run", "labels", "export")


def _display() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure
        pytest.skip("No display available for Tk.")


def _app(monkeypatch, factor: float = 1.0, screen: tuple[int, int] | None = None):
    """A shown window at display *factor* (Tk scaling as Windows gives it) on a *screen* in physical pixels."""
    real = theme.apply_theme
    monkeypatch.setattr(theme, "apply_theme",
                        lambda root, name=theme.DEFAULT_THEME: (root.tk.call("tk", "scaling", 96 / 72 * factor),
                                                                real(root, name))[1])
    if screen is not None:
        monkeypatch.setattr(app_module.App, "winfo_screenwidth", lambda self: screen[0])
        monkeypatch.setattr(app_module.App, "winfo_screenheight", lambda self: screen[1])
    controller = Controller()
    controller.state.input_format = "dicom"
    controller.state.classes = {"AD": "", "CN": ""}
    app = app_module.App(controller)
    app.views["labels"]._loaded_for = controller.state.dataset_root
    app.update()
    return app


def _inside(app, widget) -> bool:
    top, bottom = app.winfo_rooty(), app.winfo_rooty() + app.winfo_height()
    left, right = app.winfo_rootx(), app.winfo_rootx() + app.winfo_width()
    return (widget.winfo_ismapped() and top <= widget.winfo_rooty() and widget.winfo_rooty() + widget.winfo_height() <= bottom + 1
            and left <= widget.winfo_rootx() and widget.winfo_rootx() + widget.winfo_width() <= right + 1)


def _overflow(app) -> list[str]:
    edge = app.winfo_rootx() + app.winfo_width()
    found = []

    def walk(widget) -> None:
        if widget.winfo_ismapped() and widget.winfo_rootx() + widget.winfo_width() > edge + 1:
            found.append(f"{widget.winfo_class()} {widget}")
        for child in widget.winfo_children():
            if not isinstance(child, tk.Toplevel):
                walk(child)

    walk(app.views[app.controller.step])
    return found


# --- without a display ----------------------------------------------------------------------------


def test_dpi_awareness_only_on_windows_and_never_fails(monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    assert app_module.enable_dpi_awareness() is False
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    import ctypes

    monkeypatch.delattr(ctypes, "windll", raising=False)  # an interpreter without it (or an old Windows)
    assert app_module.enable_dpi_awareness() is False


# --- with a display -------------------------------------------------------------------------------


@pytest.mark.parametrize("factor", [1.0, 1.25, 1.5])
def test_every_step_fits_a_full_hd_screen_at_each_scaling(monkeypatch, factor):
    """At 150 % the 960x680 window is taller than the usable screen: it is limited to it; the tables and logs
    give the room, and the navigation and the footer stay visible."""
    _display()
    app = _app(monkeypatch, factor, screen=(1920, 1080))
    try:
        assert app.winfo_height() <= 1080 - theme.px(theme.TASKBAR) and app.winfo_width() <= 1920
        assert theme.px(100) == round(100 * factor)
        for step in STEPS:
            app.controller.step = step
            app.refresh()
            app.update()
            assert _overflow(app) == [], (factor, step)
            for widget in (app._next, app._back, app._privacy, app._theme_combo, app._activity_bar):
                assert _inside(app, widget), (factor, step, str(widget))
    finally:
        app.destroy()


def _tab_chain(app, view) -> list[tk.Misc]:
    """The focusable widgets of *view* in Tab order."""
    chain, current = [], str(view)
    while True:
        current = str(app.tk.call("tk_focusNext", current))
        if not current.startswith(str(view)) or current in [str(w) for w in chain]:
            return chain
        chain.append(app.nametowidget(current))


@pytest.mark.parametrize("step", STEPS)
def test_tab_order_reads_top_to_bottom_and_left_to_right(monkeypatch, step):
    _display()
    app = _app(monkeypatch)
    try:
        app.controller.step = step
        app.refresh()
        app.update()
        chain = [w for w in _tab_chain(app, app.views[step]) if w.winfo_ismapped()]
        assert chain, step
        # rows by vertical center (a button is taller than an entry on the same row), then left to right
        rows = [((w.winfo_rooty() + w.winfo_height() // 2) // theme.px(16), w.winfo_rootx()) for w in chain]
        assert rows == sorted(rows), [str(w) for w in chain]
    finally:
        app.destroy()


def test_a_new_step_starts_with_the_keyboard_on_its_first_control(monkeypatch):
    _display()
    app = _app(monkeypatch)
    try:
        app.focus_force()
        app.update()
        for step in ("config", "run", "input"):
            app.controller.step = step
            app.refresh()
            app.update()
            first = _tab_chain(app, app.views[step])[0]
            # the widget the window gives the keyboard to: kept by Tk even while another program has the focus
            assert app.focus_lastfor() is first, step
    finally:
        app.destroy()


def _take_focus(app, limit: float = 1.0) -> None:
    """Generated keys reach the window only while it has the system focus: ask for it, and skip (a limit of the
    test machine, not of the GUI) if another program keeps it."""
    end = time.monotonic() + limit
    while app.focus_get() is None:
        if time.monotonic() > end:
            pytest.skip("Another program holds the system focus: generated keys would not reach the window.")
        app.focus_force()
        app.update()
        time.sleep(0.02)


def test_shortcuts_move_like_the_buttons_and_ctrl_enter_does_nothing_in_the_classes_box(monkeypatch):
    _display()
    app = _app(monkeypatch)
    controller = app.controller
    try:
        controller.complete("input")
        app.refresh()
        _take_focus(app)
        app.event_generate("<Alt-Right>")
        app.update()
        assert controller.step == "config"
        classes = app.views["config"].classes
        classes.focus_force()
        classes.update()
        before = classes.get("1.0", "end")
        controller.complete("config")
        app.refresh()
        classes.focus_force()
        classes.event_generate("<Control-Return>")
        app.update()
        assert controller.step == "config" and classes.get("1.0", "end") == before  # no new line, no step change
        app.focus_force()
        app.event_generate("<Control-Return>")
        app.update()
        assert controller.step == "mapping"
        app.event_generate("<Alt-Left>")
        app.update()
        assert controller.step == "config"
        controller.step = "input"
        app.refresh()
        app.event_generate("<Alt-Left>")  # no previous step: nothing happens
        app.update()
        assert controller.step == "input"
    finally:
        app.destroy()
