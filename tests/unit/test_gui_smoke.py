"""Tk smoke test of the wizard window; skipped without a display."""

import logging
import shutil
import threading
import tkinter as tk
from pathlib import Path

import pytest

from mri_dataset_tool.presentation.gui import controller as controller_module
from mri_dataset_tool.presentation.gui.app import App
from mri_dataset_tool.presentation.gui.controller import Controller

REPO = Path(__file__).resolve().parents[2]


def _app() -> App:
    try:  # probe with a bare Tk so a bug in App is not skipped as "no display"
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
    window = App(Controller())
    window.withdraw()
    return window


def test_window_opens_navigates_and_switches_language():
    app = _app()
    try:
        app.update()
        assert app.title() == "MRI Dataset Tool: asistente"
        assert str(app._next.cget("state")) == "disabled"
        app.controller.complete("input")
        app.refresh()
        app._next.invoke()
        assert app.controller.step == "config" and app.views["config"].winfo_manager() == "pack"
        assert app.views["input"].winfo_manager() == ""
        app._language.set("en")
        app._set_language()
        assert app.title() == "MRI Dataset Tool: wizard" and app._back.cget("text") == "< Back"
    finally:
        app.destroy()


def test_close_without_a_task_destroys_the_window():
    app = _app()
    try:
        app.request_close()
        with pytest.raises(tk.TclError):
            app.winfo_exists()
    finally:
        try:
            app.destroy()
        except tk.TclError:  # already destroyed by request_close
            pass


def test_input_and_config_steps_validate_through_the_controller(tmp_path, monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", "k" * 40)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / "config" / "default.yaml", tmp_path / "config" / "default.yaml")
    (tmp_path / "config" / "run.yaml").write_text(
        "pipeline:\n  steps:\n    - name: validate\n    - name: anonymize\n", encoding="utf-8")
    (tmp_path / "in").mkdir()
    app = _app()
    try:
        view = app.views["input"]
        view.validate()
        assert view._result.cget("text") == app.controller.text("INPUT_REQUIRED")
        view.input_dir.set(str(tmp_path / "in"))
        view.output_dir.set(str(tmp_path / "out"))
        view.validate()
        app.controller.worker.join(5)
        app._poll()
        assert view._disk.cget("text") == app.controller.text("DISK_SPACE_OK")  # an empty input needs no space
        assert str(app._next.cget("state")) == "normal"
        app._next.invoke()
        config = app.views["config"]
        config.config_path.set("config/run.yaml")
        config.classes.insert("1.0", "AD\nCN")
        config.validate()
        assert config._result.cget("text").startswith(app.controller.text("CONFIG_OK"))
        assert str(app._next.cget("state")) == "normal"
        config.allow_memory.set(True)  # an edit invalidates the step
        assert str(app._next.cget("state")) == "disabled"
        assert not (tmp_path / "out").exists()
    finally:
        app.destroy()


def test_validate_is_disabled_while_the_disk_check_runs(tmp_path, monkeypatch):
    (tmp_path / "in").mkdir()
    release = threading.Event()
    monkeypatch.setattr(controller_module, "estimate_input_bytes", lambda path: release.wait(5) and 0)
    app = _app()
    try:
        view = app.views["input"]
        view.input_dir.set(str(tmp_path / "in"))
        view.output_dir.set(str(tmp_path / "out"))
        view.validate()
        assert str(view._validate.cget("state")) == "disabled"
        view.validate()  # a second click does nothing (no RuntimeError)
        release.set()
        app.controller.worker.join(5)
        app._poll()
        assert str(view._validate.cget("state")) == "normal"
    finally:
        release.set()
        app.destroy()


def test_a_callback_exception_shows_only_its_type(capsys, caplog):
    caplog.set_level(logging.WARNING)  # independent of the root level other tests (CLI --quiet) leave behind
    app = _app()
    try:
        def boom():
            raise ValueError("PlantedSecret E:/PlantedPatient/scan.dcm")

        app._back.configure(command=boom, state="normal")
        app._back.invoke()
        assert app._status.cget("text") == app.controller.text("UNEXPECTED", error_type="ValueError")
        captured = capsys.readouterr()
        assert "Planted" not in captured.err + captured.out + caplog.text
        assert "ValueError" in caplog.text
    finally:
        app.destroy()


def test_an_output_folder_with_content_asks_for_a_new_folder_name(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "other.txt").write_text("x", encoding="utf-8")
    app = _app()
    try:
        view = app.views["input"]
        view.input_dir.set(str(tmp_path / "in"))
        view.output_dir.set(str(tmp_path / "busy"))
        view.validate()
        assert view._new_folder_entry.winfo_manager() == "grid"
        assert view._result.cget("text") == app.controller.text("OUTPUT_NOT_EMPTY")
        view.new_folder.set("run1")
        view.validate()
        app.controller.worker.join(5)
        app._poll()
        assert app.controller.state.output_dir == tmp_path / "busy" / "run1"
        view.output_dir.set(str(tmp_path / "elsewhere"))  # another folder: the name is cleared and hidden
        assert view.new_folder.get() == "" and view._new_folder_entry.winfo_manager() == ""
        assert [p.name for p in (tmp_path / "busy").iterdir()] == ["other.txt"]
    finally:
        app.destroy()
