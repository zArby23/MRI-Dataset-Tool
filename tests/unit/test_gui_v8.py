"""After an «Apply» that leaves every row with a class, the labels step offers to finalize them
(«Finalize» / «Later»), once per time they become complete. Tk tests are skipped without a display."""

import tkinter as tk
from types import SimpleNamespace

import pytest

from mri_dataset_tool.presentation.gui import dialogs, messages
from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Done


def _applied(controller: Controller, complete: bool, finalized: bool = False) -> None:
    """What ``labels_finished`` sees after the worker read the table again (no dataset is read)."""
    review = SimpleNamespace(is_complete=complete, dataset_pairs=2, labeled=2 if complete else 1,
                             not_in_dataset=0, invalid_ids=0)
    controller._new_sheet = SimpleNamespace(review=review, rows=[], classes=["AD", "CN"], finalized=finalized)
    assert controller.labels_finished(Done({"count": 1})).ok


def test_finalize_is_offered_once_each_time_the_labels_become_complete():
    controller = Controller()
    _applied(controller, complete=False)
    assert not controller.offer_finalize()
    _applied(controller, complete=True)
    assert controller.offer_finalize()  # the first complete apply asks
    _applied(controller, complete=True)
    assert not controller.offer_finalize()  # «Later», then another complete apply: not asked again
    _applied(controller, complete=False)
    _applied(controller, complete=True)
    assert controller.offer_finalize()  # incomplete and complete again: asked again


def test_finalize_is_not_offered_for_finalized_labels_or_a_dataset_without_labels():
    controller = Controller()
    _applied(controller, complete=True, finalized=True)
    assert not controller.offer_finalize()
    controller._new_sheet = None  # no classes were given: no label files
    controller.labels_finished(Done({"count": 0}))
    assert not controller.offer_finalize()


@pytest.mark.parametrize("language", messages.LANGUAGES)
def test_the_finalize_texts_exist_in_both_languages(language):
    controller = Controller()
    controller.language = language
    for code in ("FINALIZE", "FINALIZE_NOW_TITLE", "FINALIZE_NOW", "LATER"):
        assert controller.text(code) and "{" not in controller.text(code)
    assert controller.text("FINALIZE") == {"es": "Finalizar etiquetas", "en": "Finalize labels"}[language]


def _display() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure
        pytest.skip("No display available for Tk.")


@pytest.mark.parametrize(("answer", "finalized"), [(True, True), (False, False)])
def test_a_complete_apply_asks_and_finalize_runs_the_buttons_action(monkeypatch, answer, finalized):
    _display()
    from mri_dataset_tool.presentation.gui.app import App

    controller = Controller()
    app = App(controller)
    try:
        view = app.views["labels"]
        asked, ran = [], []
        monkeypatch.setattr(dialogs, "ask_ok_cancel", lambda title, text, **kw: asked.append((text, kw)) or answer)
        monkeypatch.setattr(view, "run", ran.append)
        view._action = "apply"
        _applied(controller, complete=False)  # the table before: some rows without a class
        review = SimpleNamespace(is_complete=True, dataset_pairs=2, labeled=2, not_in_dataset=0, invalid_ids=0)
        controller._new_sheet = SimpleNamespace(review=review, rows=[], classes=["AD", "CN"], finalized=False)
        view.on_event(Done({"count": 1}))
        app.update()
        assert [text for text, _ in asked] == [controller.text("FINALIZE_NOW")]
        assert asked[0][1]["ok_text"] == controller.text("FINALIZE") and asked[0][1]["cancel_text"] == controller.text("LATER")
        assert (ran == ["finalize"]) is finalized and (ran == []) is not finalized
    finally:
        app.destroy()
