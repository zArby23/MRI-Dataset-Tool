"""QA4 (1): PHI sweep of the exported dataset, end to end through the stage 4 launcher at DEBUG.

Identifiers are planted where E2 does not put them: entity values (``acq-``), the input root folder,
the input ``participants.tsv``/``README``/``dataset_description.json``, a root-level inherited sidecar,
non-scalar values under allowed sidecar keys, NIfTI header text fields and a header extension, a hidden
folder, an unsupported suffix and a hand-typed label that a correction later replaces. Every planted value
contains ``Planted`` and is searched (case-insensitive) in every file name and file (XLSX zip parts, NIfTI
header and extensions), the console and the DEBUG logs. Allowed free-text sidecar keys (``SequenceName``)
are a documented residual risk of the policy and are not planted.
"""

import contextlib
import getpass
import gzip
import importlib.util
import io
import json
import logging
import zipfile
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
import yaml

from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.application.services.labels import (
    apply_label_corrections,
    dataset_pairs,
    finalize_labels,
    reopen_labels,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, load_key, pseudonymize_label

REPO = Path(__file__).resolve().parents[2]
KEY = "qa4-anonymization-key-0123456789abcdef"
MARK = "planted"
PHI_SIDECAR = {
    "PatientName": "Doe^PlantedName",
    "PatientID": "PlantedId778899",
    "InstitutionName": "PlantedHospital",
    "AcquisitionDateTime": "PlantedDate1957-03-12",
    "Manufacturer": {"Nested": "PlantedNested"},  # allowed key, non-scalar value: must be dropped
    "FlipAngle": [9, "PlantedInList", {"x": 1}],
    "EchoTime": 0.03,
}

_spec = importlib.util.spec_from_file_location("run_stage4_dataset_qa4", REPO / "scripts" / "run_stage4_dataset.py")
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV_VAR, KEY)


def _save(path: Path, shape: tuple[int, ...], sidecar: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.random.default_rng(len(path.name)).uniform(10, 100, shape).astype(np.float32)
    image = nib.Nifti1Image(data, np.diag([-1.5, 1.5, 1.5, 1.0]))
    header = image.header
    header["descrip"] = b"PlantedDescrip"
    header["aux_file"] = b"PlantedAux"
    header["intent_name"] = b"PlantedIntent"
    header["db_name"] = b"PlantedDb"
    header.extensions.append(nib.nifti1.Nifti1Extension(6, b"PlantedExtension Doe^John"))
    nib.save(image, path)
    if sidecar is not None:
        path.with_name(path.name.replace(".nii.gz", ".json")).write_text(json.dumps(sidecar), encoding="utf-8")


def _input(tmp_path: Path) -> Path:
    root = tmp_path / "PlantedRoot ñ espacio" / "bids"
    root.mkdir(parents=True)
    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "PlantedStudyName", "BIDSVersion": "1.9.0", "Authors": ["PlantedAuthor"]}), encoding="utf-8"
    )
    (root / "participants.tsv").write_text("participant_id\tname\tage\nsub-PlantedSubA\tPlantedPerson\t57\n", encoding="utf-8")
    (root / "README").write_text("PlantedReadme\n", encoding="utf-8")
    (root / "T1w.json").write_text(json.dumps({"PatientBirthDate": "PlantedBirth", "RepetitionTime": 2.0}), encoding="utf-8")
    a = root / "sub-PlantedSubA" / "ses-PlantedSesA"
    _save(a / "anat" / "sub-PlantedSubA_ses-PlantedSesA_acq-PlantedAcq_T1w.nii.gz", (6, 7, 5), PHI_SIDECAR)
    _save(a / "dwi" / "sub-PlantedSubA_ses-PlantedSesA_dir-PlantedDir_dwi.nii.gz", (6, 6, 4, 3), PHI_SIDECAR)
    _save(a / "func" / "sub-PlantedSubA_ses-PlantedSesA_task-PlantedTask_bold.nii.gz", (5, 5, 5, 2))  # not exported
    b = root / "sub-PlantedSubB" / "ses-PlantedSesB" / "anat"
    _save(b / "sub-PlantedSubB_ses-PlantedSesB_run-1_T1w.nii.gz", (6, 6, 6), PHI_SIDECAR)
    _save(b / "sub-PlantedSubB_ses-PlantedSesB_run-2_T1w.nii.gz", (5, 6, 7), PHI_SIDECAR)
    _save(root / "sub-PlantedSubC" / "ses-PlantedSesC" / "anat" / "sub-PlantedSubC_ses-PlantedSesC_FLAIR.nii.gz", (6, 6, 6))
    _save(root / ".git" / "sub-PlantedHidden_T1w.nii.gz", (4, 4, 4))
    return root


def _config(tmp_path: Path) -> Path:
    config = yaml.safe_load((REPO / "config" / "stage3_bids.yaml").read_text(encoding="utf-8"))
    config["logging"] = {"level": "DEBUG"}
    config["report"] = {"path": str(tmp_path / "PlantedReportPath" / "m.json")}
    path = tmp_path / "debug.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def _contents(path: Path) -> bytes:
    data = path.read_bytes()
    if path.name.endswith(".nii.gz"):
        raw = gzip.decompress(data)
        offset = int(nib.load(path).header["vox_offset"])
        return raw[:offset]  # header and extensions; voxel bytes are not text
    if path.suffix == ".xlsx":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return b"".join(archive.read(name) for name in archive.namelist())
    return data


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("qa4phi")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(KEY_ENV_VAR, KEY)
        source = _input(tmp_path)
        key = load_key()
        sub_a, ses_a = pseudonymize_label("PlantedSubA", "subject", key), pseudonymize_label("PlantedSesA", "session", key)
        corrections = tmp_path / "corrections.tsv"
        corrections.write_text(f"participant_id\tsession_id\tlabel\tnote\nsub-{sub_a}\tses-{ses_a}\tAD\tPlantedNote\n", encoding="utf-8")
        out = tmp_path / "out"
        handler = _ListHandler()
        root_logger = logging.getLogger()
        previous_level = root_logger.level
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)
        console = io.StringIO()
        try:
            with contextlib.redirect_stdout(console):
                code = launcher.main([
                    str(source), "--output-dir", str(out), "--config", str(_config(tmp_path)),
                    "--classes", "AD=Alzheimer", "CN=Control", "--corrections", str(corrections), "--allow-unfinalized",
                ])
            dataset = out / "dataset"
            # hand edit with a PHI-like label, then a correction replaces it: the log must not keep it
            pairs = dataset_pairs(dataset)
            rows = ["participant_id\tsession_id\tlabel"]
            rows += [f"sub-{p}\tses-{s}\t{'PlantedHandLabel' if i == 0 else 'CN'}" for i, (p, s) in enumerate(pairs)]
            (dataset / "labels.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
            fix = tmp_path / "fix.tsv"
            fix.write_text(f"participant_id\tsession_id\tlabel\nsub-{pairs[0][0]}\tses-{pairs[0][1]}\tAD\n", encoding="utf-8")
            apply_label_corrections(dataset, fix)
            finalize_labels(dataset)
            reopen_labels(dataset)
            finalize_labels(dataset)
            report_dataset(dataset, out / "report2")
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(previous_level)
    return code, source, out, console.getvalue(), handler.text()


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.name} {record.getMessage()} {record.exc_text or ''}")

    def text(self) -> str:
        return "\n".join(self.lines)


def _forbidden(source: Path, out: Path) -> list[str]:
    forbidden = [MARK, str(source), source.as_posix(), str(out), out.as_posix(), "Doe^John"]
    user = getpass.getuser()
    return forbidden + ([user] if len(user) >= 4 else [])


def test_input_really_carries_the_planted_values(run) -> None:
    _, source, *_ = run
    header = nib.load(next(source.rglob("*acq-PlantedAcq_T1w.nii.gz"))).header
    assert header["aux_file"].tobytes().startswith(b"PlantedAux")
    assert b"PlantedExtension" in header.extensions[0].get_content()


def test_launcher_ran_and_exported_every_supported_series(run) -> None:
    code, _, out, console, _ = run
    assert code == 0, console
    dataset = out / "dataset"
    images = sorted(p.relative_to(dataset).parts[-2] + "/" + p.name.split("_")[-1] for p in dataset.rglob("*.nii.gz"))
    assert images == ["anat/FLAIR.nii.gz", "anat/T1w.nii.gz", "anat/T1w.nii.gz", "anat/T1w.nii.gz", "dwi/dwi.nii.gz"]
    assert (out / "report" / "dataset_report.xlsx").is_file() and (dataset / "datalist.json").is_file()
    changes = (dataset / "labels_changes.tsv").read_text(encoding="utf-8")
    assert "	<invalid>	AD" in changes and changes.count("finalize") == 2 and "reopen" in changes


def test_no_planted_value_in_any_output_name_or_content(run) -> None:
    _, source, out, *_ = run
    forbidden = _forbidden(source, out)
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len(files) > 25
    for path in out.rglob("*"):
        relative = path.relative_to(out).as_posix().lower()
        assert MARK not in relative, relative
        if path.is_file():
            text = _contents(path).decode("utf-8", errors="replace").lower()
            leaked = [m for m in forbidden if m.lower() in text or m.replace("\\", "\\\\").lower() in text]
            assert not leaked, (relative, leaked)


def test_no_planted_value_in_console_or_debug_logs(run) -> None:
    _, source, out, console, logs = run
    assert logs  # DEBUG logging really ran
    text = (console + logs).lower()
    for marker in _forbidden(source, out):
        assert marker.lower() not in text, marker
    assert "sub-" not in console.lower() and "ses-" not in console.lower()


def test_sidecars_hold_only_allowed_scalars(run) -> None:
    _, _, out, *_ = run
    for sidecar in (out / "dataset").rglob("sub-*.json"):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert set(data) <= {"EchoTime", "RepetitionTime"}, data
        assert all(isinstance(v, (int, float)) for v in data.values())
