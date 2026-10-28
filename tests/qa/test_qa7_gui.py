"""QA7: adversarial audit of the GUI wizard (controller, worker, Tk window). Report: docs/testing/qa_etapa7.md.

Hostile field values (paths, folder names, classes, mapping cells and files, corrections files, ratios, seed,
the environment key), the worker and its queue (one task at a time, no lost events, language and filter
changes during a task, a failing view), quiet DICOM validation with real threads, PHI planted in DICOM,
NIfTI headers and BIDS sidecars through steps 1-6 (regenerated ``ml_exports_N`` and ``report_N`` included),
reopening steps, regenerated exports through junctions, and closing the window during a task. Only
synthetic values; work directories on ``E:/`` when it exists.
"""

import contextlib
import importlib.util
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import uuid
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest

from mri_dataset_tool.application.services.dataset_outputs import ML_EXPORT_FILES
from mri_dataset_tool.application.services.session_key import ensure_session_key
from mri_dataset_tool.infrastructure.dicom.reader import DICOMReader
from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Done, Failed, Status, StudyFailed

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_qa7_synthetic", REPO / "tests" / "unit" / "test_anonymize_dicom_tree.py")
synthetic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synthetic)

KEY = "qa7-anonymization-key-0123456789abcdef"
PLANTED = ["PlantedQa7Patient", "PlantedQa7Name", "PlantedQa7Study", "PlantedQa7Proto", "PlantedQa7Descrip",
           "PlantedQa7Aux", "PlantedQa7Intent", "PlantedQa7Ext", "PlantedQa7Sidecar", "PlantedQa7Folder",
           "PlantedQa7Sub", "PlantedQa7Ses", "1.2.PlantedQa7Uid"]
LIGHT = "pipeline:\n  steps:\n    - name: validate\n    - name: anonymize\n"


@pytest.fixture
def base(tmp_path):
    """Work directory on E:/ when it exists (outputs never on C:), else ``tmp_path``."""
    if os.path.isdir("E:/"):
        root = Path("E:/qa7_tmp") / uuid.uuid4().hex
        root.mkdir(parents=True)
        yield root
        shutil.rmtree(root, ignore_errors=True)
    else:
        yield tmp_path


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", KEY)


def _bids(root: Path, n: int = 3, sidecar: bool = False) -> Path:
    for i in range(n):
        anat = root / f"sub-PlantedQa7Sub{i}" / "ses-PlantedQa7Ses" / "anat"
        anat.mkdir(parents=True)
        name = f"sub-PlantedQa7Sub{i}_ses-PlantedQa7Ses_T1w"
        data = np.random.default_rng(i).uniform(1, 5, (6, 7, 5)).astype(np.float32)
        nib.save(_phi_image(data), anat / f"{name}.nii.gz")
        if sidecar:
            (anat / f"{name}.json").write_text(json.dumps(
                {"PatientName": "PlantedQa7Sidecar", "SeriesDescription": "PlantedQa7Sidecar", "RepetitionTime": 2.0}),
                encoding="utf-8")
    return root


def _phi_image(data: np.ndarray) -> nib.Nifti1Image:
    """A NIfTI with PHI planted in every free-text header field and an extension."""
    image = nib.Nifti1Image(data, np.eye(4))
    image.header["descrip"] = b"PlantedQa7Descrip"
    image.header["aux_file"] = b"PlantedQa7Aux"
    image.header["intent_name"] = b"PlantedQa7Intent"
    image.header.extensions.append(nib.nifti1.Nifti1Extension(6, b"PlantedQa7Ext"))
    return image


def _config(base: Path) -> Path:
    path = base / "light.yaml"
    path.write_text(LIGHT, encoding="utf-8")
    return path


def _task(controller: Controller, check_task, classify=None) -> list:
    """Run a task (or a ``(Check, task)`` pair) in the worker; every event it published."""
    if isinstance(check_task, tuple):
        check, check_task = check_task
        assert check.ok, check
    assert controller.start_task(check_task, *(() if classify is None else (classify,)))
    controller.worker.join(300)
    events = controller.poll()
    assert events and isinstance(events[-1], (Done, Failed)) and not controller.worker.busy
    return events


def _built(base: Path, classes: str = "AD\nCN", fmt: str = "bids", source: Path | None = None) -> Controller:
    """A controller after a successful run (steps 1, 2, 4) over a small synthetic BIDS input."""
    controller = Controller()
    source = source or _bids(base / "in")
    assert controller.set_input(str(source), fmt, str(base / "out")).ok
    assert controller.set_config(str(_config(base)), False, classes).ok
    events = _task(controller, controller.run_task())
    assert isinstance(events[-1], Done), events[-1]
    controller.run_finished()
    return controller


def _finalized(base: Path) -> Controller:
    controller = _built(base)
    assert controller.load_labels().ok
    assert controller.assign_labels(controller.unlabeled_rows(), "CN").ok
    assert controller.apply_labels().ok and controller.finalize_labels().ok
    return controller


# --- hostile field values -----------------------------------------------------------------------------


@pytest.mark.parametrize("name, expected", [
    ("a\nb", "INVALID_FOLDER_NAME"), ("a/b", "INVALID_FOLDER_NAME"), ("..", "INVALID_FOLDER_NAME"),
    ("CON", "INVALID_FOLDER_NAME"), ("con.txt", "INVALID_FOLDER_NAME"), ("a\x00", "INVALID_FOLDER_NAME"),
    ("x.", "INVALID_FOLDER_NAME"), ("x ", "INVALID_FOLDER_NAME"), ("a:b", "INVALID_FOLDER_NAME"),
    ("salida ñ 日本", None), ("y" * 250, None),
])
def test_new_folder_names(name, expected, base, key):
    (base / "parent").mkdir()
    (base / "parent" / "keep.txt").write_text("x", encoding="utf-8")
    check = Controller().set_input(str(_bids(base / "in", 1)), "bids", str(base / "parent"), name)
    assert check.code == expected


@pytest.mark.parametrize("name, valid", [("y" * 300, False), ("ñ" * 128, False), ("ñ" * 127, True), ("y" * 255, True)])
def test_a_new_folder_name_is_limited_to_255_utf8_bytes(name, valid, base, key):
    """QA7-02 (fixed): a name the file system cannot hold is refused at step 1, not at the run."""
    (base / "parent").mkdir()
    (base / "parent" / "keep.txt").write_text("x", encoding="utf-8")
    check = Controller().set_input(str(_bids(base / "in", 1)), "bids", str(base / "parent"), name)
    assert check.code == (None if valid else "INVALID_FOLDER_NAME")


@pytest.mark.skipif(os.name != "nt", reason="Windows drives and NTFS streams")
def test_an_output_with_a_colon_or_a_missing_drive_is_refused_at_step_1(base, key):
    """QA7-02 (fixed): an NTFS stream (``.../o/a:b``), a drive-relative path (``Path(...) / "a:b"`` is ``a:b``)
    and a drive that does not exist give ``INVALID_OUTPUT_PATH`` without creating anything."""
    import string

    source = str(_bids(base / "in", 1))
    missing = next((f"{letter}:/qa7/out" for letter in reversed(string.ascii_uppercase[3:])
                    if not os.path.exists(f"{letter}:/")), None)
    outputs = [f"{base}/o/a:b", str(base / "o" / "a:b"), *([missing] if missing else [])]
    for output in outputs:
        assert Controller().set_input(source, "bids", output).code == "INVALID_OUTPUT_PATH", output
    assert not (base / "o").exists()


def test_unicode_spaces_and_long_paths_run(base, key):
    source = _bids(base / "entrada con espacios ñ 日本" / ("d" * 100), 1)
    output = base / ("e" * 120) / "salida ü"
    controller = Controller()
    assert controller.set_input(str(source), "bids", str(output)).ok
    assert controller.set_config(str(_config(base)), False, "").ok
    assert isinstance(_task(controller, controller.run_task())[-1], Done)
    assert (output / "dataset" / "dataset_description.json").is_file()


@pytest.mark.parametrize("text, valid", [
    ("=x", False), ("+a", False), ("-a", False), ("@a", False), ("AD\nAD", False), ("AD=\tx", False),
    ("AD=\x00", False), ("AD=\ud800", False), ("AD\r\nCN", True), (" AD \n CN ", True), ("AD=", True),
    ("AD==x", True), ("AD=@cmd", True),  # a description only goes to labels.json, never to a TSV or XLSX cell
])
def test_hostile_classes(text, valid, base, key):
    controller = Controller()
    assert controller.set_input(str(_bids(base / "in", 1)), "bids", str(base / "out")).ok
    assert controller.set_config(str(_config(base)), False, text).ok is valid


@pytest.mark.parametrize("ratios, seed, code", [
    (["nan", "0", "1"], "0", "INVALID_RATIOS"), (["inf", "0", "0"], "0", "INVALID_RATIOS"),
    (["1e309", "0", "0"], "0", "INVALID_RATIOS"), (["0,7", "0.15", "0.15"], "0", "INVALID_RATIOS"),
    (["0.7", "0.15", "0.15000001"], "0", "INVALID_RATIOS"), (["", "", ""], "0", "INVALID_RATIOS"),
    (["0.7", "0.15", "0.15"], "1e3", "INVALID_SEED"), (["0.7", "0.15", "0.15"], "9" * 5000, "INVALID_SEED"),
    (["0.7", "0.15", "0.15"], "", "INVALID_SEED"), (["0.7", "0.15", "0.15"], " -3 ", None),
])
def test_hostile_ratios_and_seed_in_step_6(ratios, seed, code, base, key):
    controller = _finalized(base)
    check, task = controller.ml_exports_task(ratios, seed)
    assert check.code == code
    if code is None:
        assert isinstance(_task(controller, task, controller.export_failure)[-1], Done)


@pytest.mark.parametrize("column, value", [
    ("participant", "../x"), ("participant", "sub-01"), ("participant", "a\tb"), ("participant", "a\nb"),
    ("participant", "=1+1"), ("participant", "ñ"), ("session", "a b"), ("suffix", "bold"), ("suffix", "t1w"),
    ("label", "XX"),
])
def test_hostile_mapping_cells_are_refused(column, value, base, key):
    source = base / "in"
    nib.save(_phi_image(np.ones((4, 4, 3), np.float32)), (source.mkdir() or source) / "scan_t1_mprage.nii.gz")
    controller = Controller()
    assert controller.set_input(str(source), "nifti", str(base / "out")).ok
    assert controller.set_config(str(_config(base)), False, "AD\nCN").ok
    assert isinstance(_task(controller, controller.preview_task())[-1], Done)
    controller.preview_finished()
    before = list(controller.state.mapping)
    check = controller.edit_mapping(0, column, value)
    assert not check.ok and controller.state.mapping == before


def test_saving_the_mapping_table(base, key):
    """Never overwritten; QA7-03 (fixed): a folder or a missing parent give a code, not a raw ``OSError``."""
    source = base / "in"
    nib.save(_phi_image(np.ones((4, 4, 3), np.float32)), (source.mkdir() or source) / "scan_t1_mprage.nii.gz")
    controller = Controller()
    assert controller.set_input(str(source), "nifti", str(base / "out")).ok
    assert controller.set_config(str(_config(base)), False, "").ok
    _task(controller, controller.preview_task())
    controller.preview_finished()
    assert controller.edit_mapping(0, "participant", "P1").ok
    existing = base / "map.tsv"
    existing.write_text("mine", encoding="utf-8")
    assert controller.save_mapping_file(str(existing)).code == "MAPPING_FILE_EXISTS"
    assert existing.read_text(encoding="utf-8") == "mine"
    for path in (base / "missing" / "map.tsv", base):
        assert controller.save_mapping_file(str(path)).code == "MAPPING_FILE_UNWRITABLE"
    assert not (base / "missing").exists()
    assert controller.load_mapping_file(str(base)).code is not None  # a folder: refused with a code


@pytest.mark.parametrize("content, code", [
    ("participant_id\tsession_id\tlabel\n{p}\t{s}\t=1+1\n", "LABEL_UNKNOWN_CLASS"),
    ("participant_id\tsession_id\tlabel\nsub-ffff\tses-ffff\tAD\n", "LABEL_PAIR_UNKNOWN"),
    ("participant_id\tsession_id\tlabel\n{p}\t{s}\tAD\n{p}\t{s}\tCN\n", "LABEL_CORRECTIONS_INVALID"),
    ("participant_id\tsession_id\tlabel\nsub-../../x\t\tAD\n", "LABEL_CORRECTIONS_INVALID"),
    ("", "LABEL_CORRECTIONS_INVALID"),
    (None, "LABEL_CORRECTIONS_INVALID"),  # random bytes
    ("\ufeffparticipant_id\tsession_id\tlabel\r\n{p}\t{s}\tAD\r\n", None),
])
def test_hostile_corrections_files(content, code, base, key):
    controller = _built(base)
    assert controller.load_labels().ok
    row = controller.state.label_rows[0]
    path = base / "corrections.tsv"
    if content is None:
        path.write_bytes(np.random.default_rng(0).bytes(400))
    else:
        path.write_text(content.format(p=f"sub-{row.participant}", s=f"ses-{row.session}"), encoding="utf-8", newline="")
    check = controller.load_label_corrections(str(path))
    assert check.code == code
    assert len(controller.state.label_edits) == (1 if code is None else 0)


@pytest.mark.parametrize("value", ["", "short", "k" * 31])
def test_a_short_or_empty_environment_key_is_replaced_and_never_shown(value, monkeypatch, caplog):
    monkeypatch.setenv("MRI_ANON_KEY", value)
    caplog.set_level(logging.DEBUG)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        controller = Controller()
        controller.state.key_defined = ensure_session_key()
    session_key = os.environ["MRI_ANON_KEY"]
    assert len(session_key) == 64 and session_key != value and not controller.state.key_defined
    shown = [repr(controller.state), controller.key_text(), out.getvalue(), caplog.text]
    controller.set_language("en")
    shown.append(controller.key_text())
    assert not [blob for blob in shown if session_key in blob]


# --- worker, queue and threads --------------------------------------------------------------------------


def test_one_task_at_a_time_and_a_failure_keeps_every_event():
    controller = Controller()
    release = threading.Event()

    def failing(reporter):
        for n in range(500):
            reporter.on_status("export", {"n": n})
        reporter.on_error(Path("PlantedQa7Folder/x"), ValueError("PlantedQa7Patient"))
        release.wait(10)
        raise OSError("PlantedQa7Folder")

    assert controller.start_task(failing)
    assert not controller.start_task(lambda reporter: {})  # a double click: refused, nothing started
    controller.set_language("en")  # during the task
    release.set()
    controller.worker.join(10)
    events = controller.poll()
    assert [e.counts["n"] for e in events if isinstance(e, Status)] == list(range(500))
    assert StudyFailed("ValueError") in events and events[-1] == Failed("UNEXPECTED", "OSError")
    assert "Planted" not in repr(events) + controller.failure_text(events[-1])
    assert controller.start_task(lambda reporter: {}) and isinstance(_drain(controller)[-1], Done)


def _drain(controller: Controller) -> list:
    controller.worker.join(10)
    return controller.poll()


def test_label_filter_and_language_change_during_a_labels_task(base, key):
    controller = _built(base)
    assert controller.load_labels().ok
    check, task = controller.labels_task("load")
    assert controller.start_task(task, controller.labels_failure)
    controller.set_label_filter("unlabeled")
    controller.set_language("en")
    assert controller.assign_labels([0], "AD").code == "TASK_RUNNING"  # the table is being read
    events = _drain(controller)
    assert controller.labels_finished(events[-1]).ok
    assert controller.visible_label_rows() == controller.unlabeled_rows() and controller.state.label_rows


def _tk_app():
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App

    app = App(Controller())
    app.withdraw()
    return app


def _pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.update()
        time.sleep(0.02)


def test_the_window_keeps_polling_after_a_view_fails_on_an_event(caplog):
    """QA7-01 (fixed): a view that raises on an event must not stop the queue polling."""
    app = _tk_app()
    try:
        view = app.views[app.controller.step]
        view.on_event = lambda event: (_ for _ in ()).throw(KeyError("x"))
        assert app.controller.start_task(lambda reporter: {})
        app.controller.worker.join(5)
        _pump(app, 0.5)
        assert app._callback_error == "KeyError"  # shown by type only
        view.on_event = lambda event: None
        assert app.controller.start_task(lambda reporter: {})
        app.controller.worker.join(5)
        _pump(app, 0.5)
        assert not app.controller.worker.busy  # else: «task running» forever, every close asks to confirm
    finally:
        app.destroy()


def test_a_language_change_keeps_the_pending_mapping_edits_on_screen(base, key):
    """QA7-04 (fixed)."""
    source = base / "in"
    nib.save(_phi_image(np.ones((4, 4, 3), np.float32)), (source.mkdir() or source) / "scan_t1_mprage.nii.gz")
    app = _tk_app()
    try:
        controller = app.controller
        assert controller.set_input(str(source), "nifti", str(base / "out")).ok
        assert controller.set_config(str(_config(base)), False, "").ok
        controller.go_next(), controller.go_next()
        app.refresh()
        view = app.views["mapping"]
        view.run_preview()
        controller.worker.join(30)
        app._poll()
        view.commit_edit(0, "participant", "P1")
        assert view.tree.set("0", "participant") == "P1" and len(controller.state.mapping) == 1
        app._language.set("en")
        app._set_language()
        assert view.tree.set("0", "participant") == "P1"  # the edit is still pending (state.mapping)
    finally:
        app.destroy()


def test_quiet_dicom_validation_with_real_threads(base, key, caplog):
    """The GUI worker reads a DICOM tree with non-conformant UIDs while the main thread reads another:
    no UID in warnings or logs, and pydicom's setting is restored when both end."""
    for i in range(4):
        synthetic.write_synthetic_series(base / "in" / f"s{i}", StudyInstanceUID=f"1.2.PlantedQa7Uid.{i}",
                                         SeriesInstanceUID=f"1.2.PlantedQa7Uid.{i}.1", SeriesDescription="T1 MPRAGE")
    synthetic.write_synthetic_series(base / "other", StudyInstanceUID="1.2.PlantedQa7Uid.9",
                                     SeriesInstanceUID="1.2.PlantedQa7Uid.9.1")
    previous = pydicom.config.settings.reading_validation_mode
    controller = Controller()
    assert controller.set_input(str(base / "in"), "dicom", str(base / "out")).ok
    assert controller.set_config(str(_config(base)), False, "").ok
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        for _ in range(5):
            assert controller.start_task(controller.preview_task())
            while controller.worker.busy:
                DICOMReader().load_study(base / "other")
                controller.poll()
            controller.preview_finished()
    texts = [str(w.message) for w in records] + [r.getMessage() for r in caplog.records]
    assert not [t for t in texts if "planted" in t.lower()]
    assert len(controller.state.preview) == 4
    assert pydicom.config.settings.reading_validation_mode == previous


# --- PHI through steps 1-6 ------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["bids", "nifti", "dicom"])
def test_no_planted_phi_in_any_output_text_queue_or_log(fmt, base, key, caplog):
    source = base / "PlantedQa7Folder"
    if fmt == "dicom":
        for i in range(2):
            synthetic.write_synthetic_series(
                source / f"PlantedQa7Folder{i}", PatientID=f"PlantedQa7Patient{i}", PatientName="PlantedQa7Name",
                StudyDescription="PlantedQa7Study", ProtocolName="PlantedQa7Proto", SeriesDescription="T1 MPRAGE",
                StudyInstanceUID=f"1.2.PlantedQa7Uid.{i}", SeriesInstanceUID=f"1.2.PlantedQa7Uid.{i}.1")
    elif fmt == "nifti":
        source.mkdir()
        for i in range(2):
            nib.save(_phi_image(np.random.default_rng(i).uniform(1, 5, (6, 7, 5)).astype(np.float32)),
                     source / f"PlantedQa7Patient{i}_t1_mprage.nii.gz")
    else:
        _bids(source, 2, sidecar=True)
    caplog.clear()  # writing the synthetic DICOM warns too; only the GUI is under test
    caplog.set_level(logging.DEBUG)
    out = io.StringIO()
    events, texts = [], []
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        controller = Controller()
        assert controller.set_input(str(source), fmt, str(base / "out")).ok
        assert controller.set_config(str(_config(base)), False, "AD\nCN").ok
        if fmt != "bids":
            events += _task(controller, controller.preview_task())
            controller.preview_finished()
        events += _task(controller, controller.run_task())
        controller.run_finished()
        assert controller.load_labels().ok
        assert controller.assign_labels(controller.unlabeled_rows(), "AD").ok
        assert controller.apply_labels().ok and controller.finalize_labels().ok
        for _ in range(2):  # the dataset set, then ml_exports_2 (or 2 and 3 if the build wrote them)
            events += _task(controller, controller.ml_exports_task(["0.5", "0.5", "0"], "3"), controller.export_failure)
            texts += [controller.text(c, **v) for c, v in controller.export_finished(events[-1])]
        for _ in range(2):  # report_2, report_3
            events += _task(controller, controller.report_task(str(controller.default_report_dir())),
                            controller.export_failure)
            texts += [controller.text(c, **v) for c, v in controller.export_finished(events[-1])]
    for event in events:
        if isinstance(event, Status):
            texts += controller.status_lines(event)
    texts += controller.labels_status_lines() + controller.export_status_lines()
    output = base / "out"
    assert (output / "ml_exports_2" / "datalist.json").is_file() and (output / "report_3").is_dir()
    state = repr(controller.state).replace(repr(source), "<chosen>")  # the input path the user chose (shown)
    blobs = [repr(events), state, *texts, out.getvalue(), caplog.text]
    for path in output.rglob("*"):
        blobs.append(path.relative_to(output).as_posix())
        if path.is_file():
            data = path.read_bytes()
            if path.name.endswith(".gz"):
                import gzip
                data = gzip.decompress(data)
            blobs.append(data.decode("utf-8", errors="replace"))
    leaked = sorted({(m, blob[:80]) for m in PLANTED for blob in blobs if m.lower() in blob.lower()})
    assert not leaked
    assert not [b for b in [repr(events), *texts, out.getvalue(), caplog.text] if str(base) in b or base.as_posix() in b]


# --- reopening and regenerated exports ----------------------------------------------------------------


def test_reopening_after_the_exports_keeps_every_written_set(base, key):
    controller = _finalized(base)
    _task(controller, controller.ml_exports_task(["0.7", "0.15", "0.15"], "0"), controller.export_failure)
    dataset = base / "out" / "dataset"
    first = {name: (dataset / name).read_bytes() for name in ML_EXPORT_FILES}
    assert controller.reopen_labels().ok and controller.state.labels_closed is False
    check, task = controller.ml_exports_task(["0.7", "0.15", "0.15"], "1")
    event = _task(controller, task, controller.export_failure)[-1]
    assert isinstance(event, Failed) and event.code == "ML_LABELS_NOT_FINALIZED"  # never with open labels
    assert not (base / "out" / "ml_exports_2").exists()
    assert controller.finalize_labels().ok
    (base / "out" / "ml_exports_2").write_text("a file, not a folder", encoding="utf-8")
    _task(controller, controller.ml_exports_task(["0.7", "0.15", "0.15"], "1"), controller.export_failure)
    assert sorted(p.name for p in (base / "out" / "ml_exports_3").iterdir()) == sorted(ML_EXPORT_FILES)
    assert {name: (dataset / name).read_bytes() for name in ML_EXPORT_FILES} == first
    controller.step = "input"  # an earlier step changed: the built output is never taken again
    assert controller.set_input(str(base / "in"), "bids", str(base / "out")).code == "OUTPUT_NOT_EMPTY"
    assert controller.state.dataset_root is None


def _junction(link: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if result.returncode:
        pytest.skip("junctions are not available")


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions")
def test_report_folder_through_a_junction_into_the_dataset_is_refused(base, key):
    controller = _finalized(base)
    link = base / "link"
    _junction(link, base / "out" / "dataset" / "code_like")
    assert controller.report_task(str(link))[0].code == "REPORT_INSIDE_DATASET"


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions")
def test_regenerated_set_through_an_output_junction_resolves(base, key, tmp_path):
    """The output is a junction (on C:, tmp_path) to a folder on E:: ``../dataset/...`` still resolves."""
    if base == tmp_path:
        pytest.skip("needs E:")
    link = tmp_path / "out_link"
    _junction(link, base / "real_out")
    controller = Controller()
    assert controller.set_input(str(_bids(base / "in", 2)), "bids", str(link)).ok
    assert controller.set_config(str(_config(base)), False, "").ok
    assert isinstance(_task(controller, controller.run_task())[-1], Done)
    controller.run_finished()
    assert controller.load_labels().code == "NO_LABELS"
    _task(controller, controller.ml_exports_task(["0.5", "0.5", "0"], "1"), controller.export_failure)
    regenerated = link / "ml_exports_2"
    datalist = json.loads((regenerated / "datalist.json").read_text(encoding="utf-8"))
    images = [entry["image"] for entry in datalist.get("unlabeled", []) + datalist["training"] + datalist["validation"]]
    assert images and all(os.path.isfile(os.path.normpath(regenerated / image)) for image in images)
    os.rmdir(link)


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions")
def test_an_empty_ml_exports_junction_to_another_drive_fails_with_a_code(base, key, tmp_path):
    if Path(tmp_path).drive.upper() == base.drive.upper():  # e.g. --basetemp on E:: no other drive to point to
        pytest.skip("tmp_path is on the drive of the output; the junction must point to another drive")
    controller = _finalized(base)
    _task(controller, controller.ml_exports_task(["0.7", "0.15", "0.15"], "0"), controller.export_failure)
    _junction(base / "out" / "ml_exports_2", tmp_path / "elsewhere")
    event = _task(controller, controller.ml_exports_task(["0.7", "0.15", "0.15"], "1"), controller.export_failure)[-1]
    assert isinstance(event, Failed) and event.code == "ML_DIR_OTHER_DRIVE"
    assert not any((tmp_path / "elsewhere").iterdir())
    os.rmdir(base / "out" / "ml_exports_2")


# --- closing the window during a task -------------------------------------------------------------------

CLOSE_SCRIPT = r"""
import sys, time, logging
from pathlib import Path
import numpy as np, nibabel as nib
from mri_dataset_tool.presentation.gui import dialogs
logging.basicConfig(level=logging.DEBUG)
base = Path(sys.argv[1])
from mri_dataset_tool.application.services.session_key import ensure_session_key
from mri_dataset_tool.presentation.gui.app import App
from mri_dataset_tool.presentation.gui.controller import Controller
src = base / "in"
for i in range(20):
    a = src / f"sub-PlantedQa7Sub{i:02d}" / "anat"; a.mkdir(parents=True)
    nib.save(nib.Nifti1Image(np.random.rand(48, 48, 32).astype("f4"), np.eye(4)), a / f"sub-PlantedQa7Sub{i:02d}_T1w.nii.gz")
cfg = base / "run.yaml"
cfg.write_text("pipeline:\n  steps:\n    - name: validate\n    - name: anonymize\n    - name: resample\n      params: {spacing: [0.5, 0.5, 0.5]}\n")
controller = Controller(); controller.state.key_defined = ensure_session_key()
app = App(controller); app.withdraw()
asked = []
dialogs.ask_ok_cancel = lambda *a, **k: asked.append(1) or True
assert controller.set_input(str(src), "bids", str(base / "out")).ok
assert controller.set_config(str(cfg), False, "AD\nCN").ok
controller.go_next(); controller.go_next()
app.views["run"].run()
app.after(300, app.request_close)
app.mainloop()
print("closed", controller.worker.busy, len(asked), flush=True)
"""


def test_closing_during_the_run_asks_and_ends_the_process_cleanly(base):
    if not os.environ.get("DISPLAY") and os.name != "nt":
        pytest.skip("No display available for Tk.")
    result = subprocess.run([sys.executable, "-c", CLOSE_SCRIPT, str(base)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", cwd=REPO, timeout=300,
                            env={**os.environ, "MRI_ANON_KEY": "", "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "closed True 1"  # it asked once and closed with the task running
    assert "Traceback" not in result.stderr and "Fatal Python error" not in result.stderr
    assert "planted" not in (result.stdout + result.stderr).lower()
    assert (base / "out" / "dataset").is_dir()  # the output is incomplete: the manual says to empty it
