"""Keyboard and accessibility of the stage 5C widgets (V4 review M3): the format cards, the themed dialogs,
tooltips, icon shapes, «…» cutting and the fixed text of a failed «Open the output folder». The Tk tests
are skipped without a display; key events need the keyboard focus, so their windows are shown."""

import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

import pytest

from mri_dataset_tool.presentation.gui import dialogs, messages, theme, widgets


def _root() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure
        pytest.skip("No display available for Tk.")
    theme.apply_theme(root)
    return root


def _press(widget: tk.Misc, *keys: str) -> None:
    """Give *widget* the keyboard focus and press *keys* (the window must be shown)."""
    widget.focus_force()
    widget.update()
    for key in keys:
        before = widget.focus_get()
        before.event_generate(key)
        for _ in range(100):  # a loaded machine moves the focus late: wait for Tab to land before the next key
            widget.update()
            if key != "<Tab>" or widget.focus_get() is not before:
                break
            time.sleep(0.01)


# --- without a display ----------------------------------------------------------------------------


@pytest.mark.parametrize("kind", widgets.ICONS)
def test_every_icon_stays_inside_its_box(kind):
    size = 18.0
    for _, coords in widgets.icon_lines(kind, size):
        assert all(0 <= value <= size for value in coords)


def test_actions_not_done_are_warnings_not_errors():
    for code in ("LABELS_FINALIZED", "LABELS_EDITS_PENDING", "TASK_RUNNING", "NOTHING_SELECTED", "WARN_NOT_4D_DWI"):
        assert messages.severity(code) == "warning"
    assert messages.severity("INPUT_OK") == "ok" and messages.severity("TASK_STARTED") == "info"
    assert messages.severity("STAGE_FAILED") == "error" and messages.severity(None) == "info"


# --- with a display -------------------------------------------------------------------------------


def test_elide_cuts_with_an_ellipsis_only_when_needed():
    root = _root()
    try:
        font = tkfont.nametofont("TkDefaultFont", root=root)
        assert widgets.elide("a/adc", font, 500) == "a/adc"
        long = "sub-01/ses-01/" + "x" * 200
        cut = widgets.elide(long, font, 120)
        assert cut.endswith("…") and long.startswith(cut[:-1]) and font.measure(cut) <= 120
        assert widgets.elide(long, font, 1) == "…"
    finally:
        root.destroy()


def test_format_cards_follow_arrows_space_and_enter():
    root = _root()
    try:
        variable = tk.StringVar(root, value="bids")
        cards = widgets.ChoiceCards(root, variable, ("bids", "dicom", "nifti"))
        cards.pack()
        root.update()
        _press(cards.cards["bids"], "<Right>")
        assert variable.get() == "dicom" and root.focus_get() is cards.cards["dicom"]
        _press(cards.cards["dicom"], "<Down>", "<Down>")  # wraps around
        assert variable.get() == "bids"
        _press(cards.cards["bids"], "<Left>")
        assert variable.get() == "nifti"
        variable.set("bids")
        _press(cards.cards["dicom"], "<space>")
        assert variable.get() == "dicom"
        _press(cards.cards["nifti"], "<Return>")
        assert variable.get() == "nifti"
        assert all(int(card.cget("takefocus")) == 1 for card in cards.cards.values())
    finally:
        root.destroy()


def _answer(root: tk.Tk, *keys: str) -> bool:
    """Open ``ask_ok_cancel`` and press *keys* in it once it is shown."""
    def act() -> None:
        dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
        _press(dialog.focus_get() or dialog, *keys)

    root.after(300, act)
    answer = dialogs.ask_ok_cancel("Title", "Question?", parent=root, ok_text="OK", cancel_text="Cancel")
    assert root.grab_current() is None  # the grab was released
    return answer


@pytest.mark.parametrize(("keys", "expected"), [
    (("<Escape>",), False),
    (("<Return>",), True),  # the focus starts on OK
    (("<Tab>", "<Return>"), False),  # Tab to Cancel: Enter answers Cancel (not the dialog's OK too)
    (("<Tab>", "<space>"), False),
])
def test_ok_cancel_dialog_keys(keys, expected):
    root = _root()
    try:
        assert _answer(root, *keys) is expected
    finally:
        root.destroy()


def test_sections_dialog_scrolls_to_its_section_and_closes_with_escape():
    root = _root()
    seen = {}

    def act() -> None:
        dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
        text = dialog.dialog_text
        seen["top"] = text.yview()[0]
        seen["bold"] = "heading" in text.tag_names(text.index("memory"))
        _press(dialog, "<Escape>")

    try:
        root.after(300, act)
        paragraphs = [f"Paragraph {n} " + "word " * 60 for n in range(8)]
        dialogs.show_sections(root, "Title", [("privacy", "Privacy", paragraphs), ("memory", "Memory", ["Last."])],
                              "Close", section="memory")
        assert seen["top"] > 0 and seen["bold"]  # scrolled down to the bold «Memory» heading
        assert root.grab_current() is None and not [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    finally:
        root.destroy()


def test_tooltip_opens_on_keyboard_focus_and_closes_with_escape():
    root = _root()
    try:
        icon = widgets.InfoIcon(root, lambda: "Help text")
        icon.pack()
        root.update()
        _press(icon)
        root.after(widgets.Tooltip.DELAY_MS + 200, lambda: None)
        root.update()
        deadline = root.tk.call("clock", "milliseconds") + 3000
        while icon.tooltip.window is None and root.tk.call("clock", "milliseconds") < deadline:
            root.update()
        assert icon.tooltip.window is not None  # the focus alone opened it: no mouse needed
        _press(icon, "<Escape>")
        assert icon.tooltip.window is None
    finally:
        root.destroy()


def test_failed_open_folder_shows_only_the_error_type(monkeypatch):
    root = _root()
    root.destroy()
    from mri_dataset_tool.presentation.gui.app import App
    from mri_dataset_tool.presentation.gui.controller import Controller
    from mri_dataset_tool.presentation.gui.views import export_step

    def fail(path):
        raise OSError("E:/PlantedPatient/output")

    monkeypatch.setattr(export_step, "open_folder", fail)
    controller = Controller()
    controller.state.output_dir = Path("E:/PlantedPatient/output")  # only in memory: nothing is opened
    app = App(controller)
    app.withdraw()
    try:
        view = app.views["export"]
        view.refresh_texts()
        view._open.invoke()
        shown = "\n".join(view.log.get(0, "end"))
        assert app.controller.text("OPEN_FAILED", error_type="OSError") in shown and "Planted" not in shown
    finally:
        app.destroy()
