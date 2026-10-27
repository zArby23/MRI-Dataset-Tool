"""GUI controller without Tk: navigation of the wizard, texts, events and the close warning."""

import logging
import shutil
import threading
from collections import namedtuple
from pathlib import Path

import pytest

from mri_dataset_tool.application.services import disk_space
from mri_dataset_tool.application.services.inputs import project_config_dir
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main
from mri_dataset_tool.presentation.gui import messages
from mri_dataset_tool.presentation.gui.controller import STEPS, Check, Controller
from mri_dataset_tool.presentation.gui.worker import Done

REPO = Path(__file__).resolve().parents[2]
RUN_CONFIG = "pipeline:\n  steps:\n    - name: validate\n    - name: anonymize\n"
Usage = namedtuple("Usage", "total used free")


def test_the_mapping_step_applies_only_to_dicom_and_nifti():
    controller = Controller()
    assert controller.steps() == ["input", "config", "run", "labels", "export"]
    for input_format in ("dicom", "nifti"):
        controller.state.input_format = input_format
        assert controller.steps() == list(STEPS)


def test_next_needs_the_current_step_validated():
    controller = Controller()
    assert not controller.can_go_back() and not controller.can_go_next()
    assert controller.go_next() == "input"
    controller.complete("input")
    assert controller.go_next() == "config"
    assert controller.go_back() == "input"
    controller.complete("config")
    controller.state.input_format = "dicom"
    assert [controller.go_next(), controller.go_next()] == ["config", "mapping"]
    assert not controller.can_go_next()  # mapping not validated yet


def test_reopen_invalidates_the_step_and_the_later_ones():
    controller = Controller()
    for step in STEPS:
        controller.complete(step)
    controller.reopen("config")
    assert controller.go_next() == "config" and not controller.can_go_next()


def test_the_last_step_has_no_next():
    controller = Controller()
    controller.step = "export"
    controller.complete("export")
    assert not controller.can_go_next()


def test_texts_follow_the_language():
    controller = Controller()
    assert controller.step_header() == "Paso 1 de 5: Entrada"
    controller.set_language("en")
    assert controller.step_header() == "Step 1 of 5: Input"
    with pytest.raises(ValueError):
        controller.set_language("fr")


def test_navigation_and_closing_while_a_task_runs():
    controller = Controller()
    controller.complete("input")
    release = threading.Event()
    controller.worker.start(lambda reporter: release.wait(5) and None)
    assert not controller.can_go_next()
    assert controller.close_warning() == controller.text("CLOSE_WHILE_RUNNING")
    release.set()
    controller.worker.join(5)
    assert controller.poll() == [Done({})] and controller.poll() == []
    assert controller.close_warning() is None and controller.can_go_next()


# --- steps 1 and 2: validation identical to `mri-dataset dataset build` -----------------------------

KEY = "k" * 40


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run from tmp_path with its own config/ (config/default.yaml is read from the cwd) and a BIDS input."""
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / "config" / "default.yaml", tmp_path / "config" / "default.yaml")
    (tmp_path / "config" / "run.yaml").write_text(RUN_CONFIG, encoding="utf-8")
    (tmp_path / "config" / "plain.yaml").write_text("pipeline:\n  steps:\n    - name: validate\n", encoding="utf-8")
    (tmp_path / "config" / "broken.yaml").write_text("pipeline: [\n", encoding="utf-8")
    anat = tmp_path / "in" / "sub-PlantedSubject" / "ses-PlantedVisit" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-PlantedSubject_ses-PlantedVisit_T1w.nii.gz").write_bytes(b"")
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "notes.txt").write_text("x", encoding="utf-8")
    root = logging.getLogger()
    level = root.level
    yield tmp_path
    _common.configure_output()  # the CLI calls change the root log level
    root.setLevel(level)


CASES = {  # name: (input, output, config, classes, ratios, seed)
    "missing input": ("nowhere", "out", "config/run.yaml", [], ["0.7", "0.15", "0.15"], "0"),
    "output inside": ("in", "in/out", "config/run.yaml", [], ["0.7", "0.15", "0.15"], "0"),
    "output exists": ("in", "taken", "config/run.yaml", [], ["0.7", "0.15", "0.15"], "0"),
    "missing config": ("in", "out", "config/none.yaml", [], ["0.7", "0.15", "0.15"], "0"),
    "invalid classes": ("in", "out", "config/run.yaml", ["A", "A"], ["0.7", "0.15", "0.15"], "0"),
    "invalid ratios": ("in", "out", "config/run.yaml", [], ["0.5", "0.5", "0.5"], "0"),
    "no anonymize": ("in", "out", "config/plain.yaml", [], ["0.7", "0.15", "0.15"], "0"),
    "broken config": ("in", "out", "config/broken.yaml", [], ["0.7", "0.15", "0.15"], "0"),
}


def _cli_code(capsys, case) -> tuple[int, str]:
    source, output, config, classes, ratios, seed = case
    argv = ["dataset", "build", source, "--output-dir", output, "--config", config, "--ratios", *ratios, "--seed", seed]
    exit_code = main([*argv, *(["--classes", *classes] if classes else [])])
    line = capsys.readouterr().out.strip().splitlines()[-1]
    return exit_code, "OUTPUT_EXISTS" if line.startswith("Output directory already exists") else messages.invalid_input(
        ValueError(line))[0]


def _gui_check(case) -> Check:
    source, output, config, classes, ratios, seed = case
    controller = Controller()
    check = controller.set_input(source, "bids", output)
    if check.ok:
        check = controller.set_config(config, False, "\n".join(classes), ratios, seed)
    return check


@pytest.mark.parametrize("name", CASES)
def test_steps_reject_what_the_cli_rejects_with_the_same_code(project, capsys, name):
    exit_code, cli_code = _cli_code(capsys, CASES[name])
    assert exit_code == (1 if name == "output exists" else 2)
    # the GUI asks for a new folder inside an output with content instead of stopping (G2-fix)
    assert _gui_check(CASES[name]).code == {"OUTPUT_EXISTS": "OUTPUT_NOT_EMPTY"}.get(cli_code, cli_code)
    assert not (project / "out").exists() and not (project / "in" / "out").exists()


def test_gui_only_parsing_errors(project):
    controller = Controller()
    assert controller.set_config("config/run.yaml", False, "", ["0.7"] * 3, "0").code == "INPUT_REQUIRED"
    assert controller.set_input("", "bids", "out").code == "INPUT_REQUIRED"
    assert controller.set_input("in", "bids", " ").code == "OUTPUT_REQUIRED"
    assert controller.set_input("in", "analyze", "out").code == "INVALID_FORMAT"
    assert controller.set_input("in", "bids", "out").ok
    assert controller.set_config("config/run.yaml", False, "", ["0.7", "x", "0.15"], "0").code == "INVALID_RATIOS"
    assert controller.set_config("config/run.yaml", False, "", ["0.7", "0.15", "0.15"], "1.5").code == "INVALID_SEED"


def test_valid_steps_fill_the_state_and_unlock_the_next_step(project):
    controller = Controller()
    assert controller.set_input("in", "dicom", "out").ok and controller.state.input_format == "dicom"
    controller.go_next()
    check = controller.set_config("config/run.yaml", True, "AD=Alzheimer\n\nCN\n", ["0.6", "0.2", "0.2"], "7")
    assert check.ok and controller.go_next() == "mapping"
    state = controller.state
    assert state.classes == {"AD": "Alzheimer", "CN": ""} and state.ratios == (0.6, 0.2, 0.2) and state.seed == 7
    assert controller.pipeline_summary() == ['validate {"modalities": null}', 'anonymize {"policy_version": "1"}']
    assert not (project / "out").exists()
    texts = [repr(state), *controller.pipeline_summary(), controller.check_text(check, "CONFIG_OK")]
    assert not [text for text in texts if KEY in text or "Planted" in text]


def test_memory_consent_reaches_the_pipeline(project):
    (project / "config" / "memory.yaml").write_text(
        RUN_CONFIG + "    - name: resample\n    - name: normalize\n", encoding="utf-8")
    controller = Controller()
    controller.set_input("in", "bids", "out")
    assert controller.set_config("config/memory.yaml", True, "", ["0.7", "0.15", "0.15"], "0").ok
    params = {step.name: step.params.get("allow_insufficient_memory") for step in controller.state.pipeline.steps}
    assert params == {"validate": None, "anonymize": None, "resample": True, "normalize": True}
    assert controller.set_config("config/memory.yaml", False, "", ["0.7", "0.15", "0.15"], "0").ok
    assert {step.params.get("allow_insufficient_memory") for step in controller.state.pipeline.steps} <= {None, False}


def test_disk_space_task_and_text(project, monkeypatch):
    controller = Controller()
    controller.set_input("in", "bids", "out")
    monkeypatch.setattr(disk_space.shutil, "disk_usage", lambda path: Usage(10, 10, 2**30))
    controller.worker.start(controller.disk_space_task())
    controller.worker.join(5)
    [done] = controller.poll()
    assert done.summary == {"required": 0, "free": 2**30, "insufficient": 0}
    assert controller.disk_space_text(done.summary) == controller.text("DISK_SPACE_OK")
    low = {"required": 2**30, "free": 2**30, "insufficient": 1}
    assert controller.disk_space_text(low).startswith("Aviso: la salida estimada (1.0 GiB)")


def test_key_text_follows_the_state():
    controller = Controller()
    assert controller.key_text() == controller.text("KEY_DEFINED")
    controller.state.key_defined = False
    assert controller.key_text() == controller.text("KEY_GENERATED")


def test_a_second_task_is_refused_while_one_runs():
    controller = Controller()
    release = threading.Event()
    assert controller.start_task(lambda reporter: release.wait(5) and None) is True
    assert controller.start_task(lambda reporter: None) is False  # e.g. a double click
    release.set()
    controller.worker.join(5)
    assert controller.poll() == [Done({})]
    assert controller.start_task(lambda reporter: None) is True
    controller.worker.join(5)


def test_paths_are_not_stripped(project):
    controller = Controller()
    assert controller.set_input(" in", "bids", "out").code == "INPUT_NOT_FOUND"  # as the CLI with " in"


def test_config_and_preset_come_from_the_project_not_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    monkeypatch.chdir(tmp_path)  # no config/ here
    (tmp_path / "in").mkdir()
    controller = Controller()
    assert controller.state.config_path == REPO / "config" / "stage3_bids.yaml"
    assert project_config_dir() == REPO / "config"
    assert controller.set_input("in", "bids", "out").ok
    check = controller.set_config(str(controller.state.config_path), False, "", ["0.7", "0.15", "0.15"], "0")
    assert check.ok and controller.state.pipeline.steps[1].name == "anonymize"
    assert not (tmp_path / "out").exists()


def test_output_new_empty_or_with_content(project):
    controller = Controller()
    (project / "empty").mkdir()
    assert controller.set_input("in", "bids", "empty").ok and controller.state.output_dir == Path("empty")
    assert controller.set_input("in", "bids", "taken").code == "OUTPUT_NOT_EMPTY"  # never mixed with notes.txt
    assert controller.set_input("in", "bids", "taken", "run1").ok
    assert controller.state.output_dir == Path("taken") / "run1" and not (project / "taken" / "run1").exists()
    for name in ("a/b", "..", "x.", "CON", "a:b", "y" * 256):
        assert controller.set_input("in", "bids", "taken", name).code == "INVALID_FOLDER_NAME"
    (project / "taken" / "run2").mkdir()  # even empty: the name must be new
    assert controller.set_input("in", "bids", "taken", "run2").code == "FOLDER_NAME_EXISTS"
    assert controller.set_input("in", "bids", "taken", "notes.txt").code == "FOLDER_NAME_EXISTS"
    assert [p.name for p in (project / "taken").iterdir()] == ["notes.txt", "run2"]


def test_an_output_path_that_could_only_fail_at_the_run_is_refused(project):
    """QA7-02: a new folder of the path with an invalid name or on a missing drive, caught in step 1."""
    controller = Controller()
    for output in ("new/a:b", "new/" + "y" * 256, "new/CON/x", "new/x./y"):
        assert controller.set_input("in", "bids", output).code == "INVALID_OUTPUT_PATH"
    assert controller.set_input("in", "bids", "new/deeper/run").ok
    assert not (project / "new").exists()


def test_an_output_with_only_a_hidden_file_is_not_used(project):
    (project / "mac").mkdir()
    (project / "mac" / ".DS_Store").write_text("", encoding="utf-8")
    assert Controller().set_input("in", "bids", "mac").code == "OUTPUT_NOT_EMPTY"
    assert [p.name for p in (project / "mac").iterdir()] == [".DS_Store"]
