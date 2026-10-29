"""Integration: the GUI wizard (controller without Tk, real services in the worker) gives the CLI's dataset.

The synthetic inputs of the unified-input integration (DICOM with planted PHI, the same volumes as loose
NIfTI and as BIDS) plus a loose NIfTI with a NaN go through steps 1→6 with the controller: mapping edits
and a batch label (DICOM), a mapping file (NIfTI), a corrections file (BIDS), label batch assignment,
finalize/reopen, ML exports and a report. The DICOM run is repeated with ``mri-dataset`` (the GUI's saved
mapping, the same label corrections): same files, same bytes. PHI sweep over the output trees, the event
queue, the state, every text the controller produced, DEBUG logs, stdout and stderr. Reopening a step
after a run, new/empty/non-empty outputs, the close warning and a Tk walk of the window (with a display).
"""

import contextlib
import io
import json
import logging
import tkinter as tk
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.services.dataset_outputs import ML_EXPORT_FILES
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Done, Failed, Status, StudyFailed, failure
from test_stage4_dataset_integration import _contents
from test_stage5_cli_integration import _Transcript, _tree
from test_stage5_ingest_integration import (
    CONFIG,
    INPUT_MARKER,
    KEY,
    SECRETS,
    _bids_corrections,
    _bids_input,
    _dicom_input,
    _loose_inputs,
    _structure,
    _volumes,
)

REPO = Path(__file__).resolve().parents[2]
CLASSES = "AD=Alzheimer\nCN=Control"
RATIOS = ["0.7", "0.15", "0.15"]
NAN_NAME = "PlantedLoose_Nan_t2_tse.nii.gz"
# Files that legitimately differ between two runs: creation times (manifest, label log, final labels).
TIMED = {"code/run_manifest.json", "labels_changes.tsv", "labels_final.json"}


class _Session:
    """A controller plus everything it produced: events, texts and repr snapshots of its state."""

    def __init__(self) -> None:
        self.controller = Controller()
        self.events: list = []
        self.texts: list[str] = []
        self.states: list[str] = []

    def task(self, check_task, classify=failure):
        """Run a ``(Check, task)`` pair or a bare task in the worker; the last event (``Done``/``Failed``)."""
        if isinstance(check_task, tuple):
            check, check_task = check_task
            assert check.ok, check
        controller = self.controller
        assert controller.start_task(check_task, classify)
        assert controller.close_warning() is not None  # busy until the main thread drains the last event
        controller.worker.join(600)
        events = controller.poll()
        assert not controller.worker.busy
        self.events += events
        for event in events:
            if isinstance(event, Status):
                self.texts += controller.status_lines(event)
            elif isinstance(event, Failed):
                self.texts.append(controller.failure_text(event))
        self.snapshot()
        return events[-1]

    def labels(self, action: str) -> Done:
        controller = self.controller
        done = self.task(controller.labels_task(action), controller.labels_failure)
        assert isinstance(done, Done), done
        self.texts.append(repr(controller.labels_finished(done)))
        self.texts += controller.labels_status_lines()
        return done

    def export(self, check_task) -> Done:
        done = self.task(check_task, self.controller.export_failure)
        assert isinstance(done, Done), done
        controller = self.controller
        self.texts += [controller.text(code, **values) for code, values in controller.export_finished(done)]
        self.texts += controller.export_status_lines()
        return done

    def snapshot(self) -> None:
        """repr of the state without the paths the user chose (the GUI may show those, Q2)."""
        controller, state = self.controller, self.controller.state
        text = repr(state)
        chosen = [state.input_dir, state.output_dir, state.config_path, state.dataset_root, *state.report_dirs]
        for path in sorted((repr(p) for p in chosen if p is not None), key=len, reverse=True):
            text = text.replace(path, "<chosen>")
        self.states.append(text)
        self.texts += [controller.step_header(), controller.key_text()]


def _walk(session: _Session, source: Path, fmt: str, output: Path, *, new_folder: str = "", classes: str = CLASSES,
          mapping=None, table=None) -> Done:
    """Steps 1→4: input, config, (mapping), run. *table* loads a mapping file before the first preview
    (without it, neutral NIfTI names map nothing and the preview fails); *mapping* edits the preview."""
    controller = session.controller
    check = controller.set_input(str(source), fmt, str(output), new_folder)
    assert check.ok, check
    disk = session.task(controller.disk_space_task())
    session.texts.append(controller.disk_space_text(disk.summary))
    assert controller.go_next() == "config"
    assert controller.set_config(str(CONFIG), False, classes, RATIOS, "0").ok
    session.texts += controller.pipeline_summary()
    controller.go_next()
    if fmt != "bids":
        assert controller.step == "mapping"
        if table:
            table(controller)
        assert isinstance(session.task(controller.preview_task()), Done)
        controller.preview_finished()
        if mapping:
            mapping(controller)
            assert isinstance(session.task(controller.preview_task()), Done)
            controller.preview_finished()
        assert controller.go_next() == "run"
    done = session.task(controller.run_task())
    assert isinstance(done, Done), done
    controller.run_finished()
    assert controller.go_next() == "labels"
    return done


def _rows(controller: Controller, location: str) -> list[int]:
    return [i for i, row in enumerate(controller.state.preview) if row.location.as_posix().startswith(location)]


def _nan_input(root: Path, images) -> Path:
    """Loose NIfTI without a mapping: two files that map and one T2 with a NaN (validate fails it)."""
    root.mkdir(parents=True)
    nib.save(images["PlantedFolderAlpha", "visit1", "t1"], root / "PlantedLoose_Alice_t1_mprage.nii.gz")
    nib.save(images["PlantedFolderBeta", "visit1", "t1"], root / "PlantedLoose_Bob_t1_mprage.nii.gz")
    image = images["PlantedFolderAlpha", "visit1", "t2"]
    data = np.asarray(image.dataobj, np.float32).copy()
    data[0, 0, 0] = np.nan
    nib.save(nib.Nifti1Image(data, image.affine), root / NAN_NAME)
    return root


@pytest.fixture(scope="module")
def flow(tmp_path_factory: pytest.TempPathFactory):
    """Every GUI walk and the CLI reference once (module scope: each build runs the stage 3 pipeline)."""
    tmp = tmp_path_factory.mktemp("e7")
    out, err, logs = io.StringIO(), io.StringIO(), io.StringIO()
    handler = logging.StreamHandler(logs)
    handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    level = root_logger.level
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)
    sessions: dict[str, _Session] = {}
    cli = _Transcript()
    try:
        with pytest.MonkeyPatch.context() as patch, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            patch.setenv("MRI_ANON_KEY", KEY)
            patch.chdir(REPO)  # the CLI reads config/default.yaml from the current directory
            dicom = _dicom_input(tmp / INPUT_MARKER / "dicom")
            images = _volumes(dicom)
            mapped, nifti_map, _ = _loose_inputs(tmp / INPUT_MARKER / "nifti", images)
            bids = _bids_input(tmp / INPUT_MARKER / "bids", images)
            nan = _nan_input(tmp / INPUT_MARKER / "nan", images)
            inputs_before = _tree(tmp / INPUT_MARKER)
            gui = tmp / "gui"

            # DICOM: labels by study through the table, Beta left unlabeled, then a batch label in step 5.
            dicom_session = sessions["dicom"] = _Session()

            def dicom_mapping(controller: Controller) -> None:
                alpha, gamma = _rows(controller, "PlantedFolderAlpha/"), _rows(controller, "PlantedFolderGamma/")
                assert controller.assign_mapping_label(alpha, "AD").ok
                assert controller.assign_mapping_label(gamma, "CN").ok
                assert controller.save_mapping_file(str(tmp / "gui_dicom_map.tsv")).ok

            run = _walk(dicom_session, dicom, "dicom", gui / "dicom", mapping=dicom_mapping)
            controller = dicom_session.controller
            dicom_session.labels("load")
            assert not controller.state.labels_closed and not controller.can_go_next()
            unlabeled = controller.unlabeled_rows()
            assert len(unlabeled) == 1 and controller.assign_labels(unlabeled, "CN").ok
            dicom_session.labels("apply")
            dicom_session.labels("finalize")
            assert controller.state.labels_closed and controller.go_next() == "export"
            dicom_session.export(controller.ml_exports_task(RATIOS, "0"))
            dicom_session.export(controller.report_task(str(gui / "dicom" / "report_final")))
            dicom_run = run

            # The same DICOM flow through the CLI with the GUI's saved mapping and the same correction.
            corrections = tmp / "fill.tsv"
            cli_codes = {}
            cli_out = tmp / "cli" / "dicom"
            cli_codes["build"], _ = cli("dataset", "build", dicom, "--format", "dicom", "--mapping",
                                        tmp / "gui_dicom_map.tsv", "--output-dir", cli_out, "--config", CONFIG,
                                        "--classes", "AD=Alzheimer", "CN=Control")
            lines = (cli_out / "dataset" / "labels.tsv").read_text(encoding="utf-8").splitlines()
            corrections.write_text("\n".join([lines[0], *[line + "CN" for line in lines[1:] if line.endswith("\t")]])
                                   + "\n", encoding="utf-8")
            cli_codes["apply"], _ = cli("labels", "apply", cli_out / "dataset", "--corrections", corrections)
            cli_codes["finalize"], _ = cli("labels", "finalize", cli_out / "dataset")
            cli_codes["export_ml"], _ = cli("dataset", "export-ml", cli_out / "dataset", "--ratios", *RATIOS, "--seed", "0")
            cli_codes["report"], _ = cli("dataset", "report", cli_out / "dataset", cli_out / "report_final")

            # Loose NIfTI with a mapping file (labels: finalized by the build); reopened and closed again.
            nifti_session = sessions["nifti"] = _Session()
            parent = gui / "nifti_parent"
            parent.mkdir(parents=True)
            (parent / "keep.txt").write_text("not mine", encoding="utf-8")
            assert nifti_session.controller.set_input(str(mapped), "nifti", str(parent)).code == "OUTPUT_NOT_EMPTY"

            def load_table(controller: Controller) -> None:
                assert controller.load_mapping_file(str(nifti_map)).ok

            nifti_run = _walk(nifti_session, mapped, "nifti", parent, new_folder="gui_nifti", table=load_table)
            nifti_session.labels("load")
            assert nifti_session.controller.state.labels_closed and nifti_session.controller.can_go_next()
            nifti_session.labels("reopen")
            assert not nifti_session.controller.can_go_next()
            nifti_session.labels("finalize")
            nifti_session.controller.go_next()
            assert nifti_session.controller.ml_exports_present()  # finalized at build time: the build wrote them
            nifti_dataset = parent / "gui_nifti" / "dataset"
            standard_ml = {name: (nifti_dataset / name).read_bytes() for name in ML_EXPORT_FILES}
            # step 6 with other parameters: a regenerated set next to the dataset, the standard one untouched
            nifti_session.export(nifti_session.controller.ml_exports_task(["0.5", "0.5", "0"], "7"))
            assert {name: (nifti_dataset / name).read_bytes() for name in ML_EXPORT_FILES} == standard_ml

            # BIDS into an existing empty folder; labels from a corrections file chosen by the user.
            bids_session = sessions["bids"] = _Session()
            (gui / "bids").mkdir()
            bids_run = _walk(bids_session, bids, "bids", gui / "bids")
            bids_session.labels("load")
            check = bids_session.controller.load_label_corrections(str(_bids_corrections(tmp / "bids_fix.tsv")))
            assert check.ok and check.values == {"count": 4}
            bids_session.labels("apply")
            bids_session.labels("finalize")

            # Loose NIfTI without a mapping and without classes: a NaN fails one study, no labels.
            nan_session = sessions["nan"] = _Session()
            nan_run = _walk(nan_session, nan, "nifti", gui / "nan", classes="")
            nan_session.labels("load")
            assert not nan_session.controller.state.labels_available and nan_session.controller.can_go_next()

            inputs_after = _tree(tmp / INPUT_MARKER)
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(level)
        _common.configure_output()
    return {
        "tmp": tmp, "gui": gui, "cli_out": cli_out, "cli": cli, "cli_codes": cli_codes, "sessions": sessions,
        "runs": {"dicom": dicom_run, "nifti": nifti_run, "bids": bids_run, "nan": nan_run},
        "inputs": (inputs_before, inputs_after), "stdout": out.getvalue(), "stderr": err.getvalue(),
        "logs": logs.getvalue(), "corrections": corrections, "dicom": dicom,
    }


def test_inputs_untouched_and_the_cli_reference_ran(flow) -> None:
    assert flow["inputs"][0] == flow["inputs"][1]
    assert flow["cli_codes"] == {"build": 0, "apply": 0, "finalize": 0, "export_ml": 0, "report": 0}


def test_run_summaries_and_events(flow) -> None:
    runs = flow["runs"]
    expected = {"studies": 4, "series": 7, "participants": 3, "errors": 0, "report_files": 4}
    assert runs["dicom"].summary == runs["nifti"].summary == runs["bids"].summary == expected
    assert runs["nan"].summary == {"studies": 2, "series": 2, "participants": 2, "errors": 1, "report_files": 4}
    assert StudyFailed("ValueError") in flow["sessions"]["nan"].events  # validate rejects the NaN, the batch goes on
    texts = flow["sessions"]["dicom"].texts
    assert any("UNMAPPED_SERIES" in t and "EXCLUDED 2" in t for t in texts)  # the localizer and the ADC map
    assert any("UNMAPPED_SERIES" in t and "NO_MATCH 2" in t for t in flow["sessions"]["nifti"].texts)


def test_a_regenerated_ml_set_resolves_to_the_dataset_images(flow) -> None:
    output = flow["gui"] / "nifti_parent" / "gui_nifti"
    regenerated = output / "ml_exports_2"
    assert sorted(p.name for p in regenerated.iterdir()) == sorted(ML_EXPORT_FILES)
    splits = json.loads((regenerated / "splits.json").read_text(encoding="utf-8"))
    assert (splits["seed"], splits["ratios"], splits["labels_finalized"]) == (7, {"training": 0.5, "validation": 0.5, "testing": 0.0}, True)
    datalist = json.loads((regenerated / "datalist.json").read_text(encoding="utf-8"))
    images = [entry["image"] for entries in datalist.values() if isinstance(entries, list)
              for entry in entries if isinstance(entry, dict)]
    assert len(images) == 7 and all(image.startswith("../dataset/sub-") for image in images)
    # MONAI's load_decathlon_datalist joins the datalist folder and each image
    assert all((regenerated / image).resolve().is_file() for image in images)
    assert all((output / "dataset" / image.removeprefix("../dataset/")).is_file() for image in images)


def test_the_four_inputs_give_the_cli_dataset(flow) -> None:
    gui = flow["gui"]
    dicom = _structure(gui / "dicom" / "dataset")
    assert len(dicom) == 3 and sum(len(sessions) for sessions in dicom) == 4
    assert _structure(flow["cli_out"] / "dataset") == dicom
    assert _structure(gui / "nifti_parent" / "gui_nifti" / "dataset") == dicom
    assert _structure(gui / "bids" / "dataset") == dicom
    assert not (gui / "nifti_parent" / "dataset").exists()  # the folder with content was never used
    assert (gui / "nifti_parent" / "keep.txt").read_text(encoding="utf-8") == "not mine"


def test_dicom_gui_and_cli_write_the_same_files_and_bytes(flow) -> None:
    gui, cli = flow["gui"] / "dicom", flow["cli_out"]
    names = lambda root: sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert names(gui) == names(cli)
    for relative in names(gui / "dataset"):
        if relative not in TIMED:
            assert (gui / "dataset" / relative).read_bytes() == (cli / "dataset" / relative).read_bytes(), relative
    final = lambda root: {key: value for key, value in json.loads(
        (root / "dataset" / "labels_final.json").read_text(encoding="utf-8")).items()
        if key in ("label_count", "class_counts", "sha256")}
    assert final(gui) == final(cli) and final(gui)["label_count"] == 4
    for report in ("report", "report_final"):
        assert (gui / report / "dataset_report.json").read_bytes() == (cli / report / "dataset_report.json").read_bytes()
    actions = lambda root: [line.split("\t")[1] for line in
                            (root / "dataset" / "labels_changes.tsv").read_text(encoding="utf-8").splitlines()[1:]]
    assert actions(gui) == actions(cli)


def test_reopening_a_step_after_the_run_needs_another_output(flow) -> None:
    controller = flow["sessions"]["dicom"].controller
    output = flow["gui"] / "dicom"
    before = _tree(output)
    controller.step = "config"
    check = controller.set_config(str(CONFIG), False, CLASSES, RATIOS, "1")  # any change reopens config...
    assert check.code == "OUTPUT_EXISTS"  # ...and the used output is never taken again
    assert controller.state.dataset_root is None and not controller.can_go_next()
    controller.step = "input"
    assert controller.set_input(str(flow["dicom"]), "dicom", str(output)).code == "OUTPUT_NOT_EMPTY"
    assert _tree(output) == before


def test_no_phi_in_queue_state_texts_logs_or_console(flow) -> None:
    forbidden = [*SECRETS, NAN_NAME, "PlantedLoose", str(flow["tmp"]), flow["tmp"].as_posix()]
    for name, session in flow["sessions"].items():
        blobs = [repr(session.events), *session.states, *session.texts]
        leaked = [m for m in forbidden for blob in blobs if m.lower() in blob.lower()]
        assert not leaked, (name, leaked)
        assert not [blob for blob in blobs if "sub-" in blob or "ses-" in blob], name
    assert flow["logs"]  # DEBUG logs of the services were captured
    for stream in ("logs", "stdout", "stderr"):
        text = flow[stream].lower()
        assert not [m for m in forbidden if m.lower() in text], stream


def test_no_phi_anywhere_in_the_gui_output_trees(flow) -> None:
    gui, tmp = flow["gui"], flow["tmp"]
    forbidden = [*SECRETS, NAN_NAME, "PlantedLoose", str(tmp), tmp.as_posix()]
    assert (gui / "dicom" / "dataset" / "splits.json").is_file()
    assert json.loads((gui / "dicom" / "dataset" / "splits.json").read_text(encoding="utf-8"))["labels_finalized"] is True
    for path in gui.rglob("*"):
        relative = path.relative_to(gui).as_posix()
        if relative == "nifti_parent/keep.txt":
            continue
        assert not any(m.lower() in relative.lower() for m in forbidden), relative
        if path.is_file():
            content = _contents(path).decode("utf-8", errors="replace").lower()
            leaked = [m for m in forbidden if m.lower() in content or m.replace("\\", "\\\\").lower() in content]
            assert not leaked, (relative, leaked)


# --- Tk: the real window, step by step (skipped without a display) ------------------------------------


def _settle(app, timeout: float = 600) -> None:
    app.controller.worker.join(timeout)
    app._poll()
    app.update()


def test_tk_window_walk(tmp_path, monkeypatch) -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        if "no display name" not in str(error) and "connect to display" not in str(error):
            raise  # only a missing display skips; any other Tk error is a failure
        pytest.skip("No display available for Tk.")
    from mri_dataset_tool.presentation.gui.app import App
    from mri_dataset_tool.presentation.gui import dialogs

    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    source = tmp_path / "in"
    for sub, value in (("PlantedA", 1.0), ("PlantedB", 2.0)):
        anat = source / f"sub-{sub}" / "anat"
        anat.mkdir(parents=True)
        data = np.random.default_rng(0).uniform(value, value + 5, (6, 7, 5)).astype(np.float32)
        nib.save(nib.Nifti1Image(data, np.eye(4)), anat / f"sub-{sub}_T1w.nii.gz")
    config = tmp_path / "run.yaml"
    config.write_text("pipeline:\n  steps:\n    - name: validate\n    - name: anonymize\n", encoding="utf-8")
    app = App(Controller())
    app.withdraw()
    try:
        views = app.views
        views["input"].input_dir.set(str(source))
        views["input"].output_dir.set(str(tmp_path / "out"))
        views["input"].validate()
        _settle(app, 60)
        app._next.invoke()
        assert app.controller.step == "config"
        views["config"].config_path.set(str(config))
        views["config"].classes.insert("1.0", "AD\nCN")
        # Inserted by code, <<Modified>> may arrive after the run: it must not reopen the step (E7-01).
        views["config"].validate()
        app.refresh()
        app._next.invoke()
        assert app.controller.step == "run"
        views["run"].run()
        assert app.controller.close_warning() is not None
        _settle(app)
        assert app.controller.state.dataset_root == tmp_path / "out" / "dataset"
        app._next.invoke()
        _settle(app)  # the labels step loads its table in the worker when shown
        labels = views["labels"]
        labels.batch_class.set("CN")
        monkeypatch.setattr(labels, "confirm", lambda question: True)
        # a complete apply now asks «finalize now?»; «Later», so the button below finalizes as in 5B
        monkeypatch.setattr(dialogs, "ask_ok_cancel", lambda *args, **kwargs: False)
        labels.assign_unlabeled()
        labels.run("apply")
        _settle(app)
        labels.run("finalize")
        _settle(app)
        assert app.controller.state.labels_closed
        app._next.invoke()
        assert app.controller.step == "export"
        views["export"].write_ml()
        _settle(app)
        assert (tmp_path / "out" / "dataset" / "splits.json").is_file()
        views["export"].report_dir.set(str(tmp_path / "report2"))
        views["export"].write_report()
        _settle(app)
        assert len(list((tmp_path / "report2").iterdir())) == 4
        shown = "\n".join(views["export"].log.get(0, "end"))
        assert "Planted" not in shown and str(tmp_path) not in shown
    finally:
        app.destroy()
