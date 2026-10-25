"""C6: ``dataset export-ml|report|build`` over a synthetic BIDS input; counts only on the console."""

import json
import logging
from collections import namedtuple
import shutil
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.services import disk_space
from mri_dataset_tool.infrastructure.anonymization.pseudonym import load_key, pseudonymize_label
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main

REPO = Path(__file__).resolve().parents[2]
KEY = "k" * 40
SUBJECTS = ("PATIENT01", "PATIENT02", "PATIENT03")
SECRETS = [*SUBJECTS, "VISIT1", "Doe^Secret", KEY, "sub-"]
RUN_CONFIG = "pipeline:\n  steps:\n    - name: validate\n    - name: anonymize\n"


@pytest.fixture(autouse=True)
def cli_env(tmp_path, monkeypatch):
    """Run from tmp_path with its own config/ (config/default.yaml is read from the cwd)."""
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / "config" / "default.yaml", tmp_path / "config" / "default.yaml")
    (tmp_path / "config" / "run.yaml").write_text(RUN_CONFIG, encoding="utf-8")
    (tmp_path / "config" / "plain.yaml").write_text("pipeline:\n  steps:\n    - name: validate\n", encoding="utf-8")
    root = logging.getLogger()
    level = root.level
    yield
    _common.configure_output()
    root.setLevel(level)


def bids_input(root: Path) -> Path:
    """Three sessions with a T1w; PATIENT03 holds a NaN (validate rejects it); sidecars carry PHI."""
    rng = np.random.default_rng(0)
    for subject in SUBJECTS:
        volume = rng.uniform(10, 100, (4, 5, 3)).astype(np.float32)
        if subject == "PATIENT03":
            volume[1, 1, 1] = np.nan
        anat = root / f"sub-{subject}" / "ses-VISIT1" / "anat"
        anat.mkdir(parents=True)
        nib.save(nib.Nifti1Image(volume, np.diag([1.5, 1.5, 1.5, 1.0])), anat / f"sub-{subject}_ses-VISIT1_T1w.nii.gz")
        (anat / f"sub-{subject}_ses-VISIT1_T1w.json").write_text(
            json.dumps({"RepetitionTime": 2.3, "PatientName": "Doe^Secret"}), encoding="utf-8"
        )
    return root


def corrections(path: Path, rows: list[tuple[str, str]]) -> Path:
    """A corrections TSV with the pseudonymized ids of *rows* (subject, label)."""
    key = load_key()
    lines = ["participant_id\tsession_id\tlabel"]
    lines += [
        f"sub-{pseudonymize_label(s, 'subject', key)}\tses-{pseudonymize_label('VISIT1', 'session', key)}\t{label}"
        for s, label in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build(tmp_path: Path, *extra: str, out: str = "out") -> int:
    return main(["dataset", "build", str(tmp_path / "in"), "--output-dir", out, "--config", "config/run.yaml", *extra])


def clean(text: str, tmp_path: Path) -> bool:
    return not [s for s in [*SECRETS, str(tmp_path), tmp_path.as_posix()] if s in text]


def test_build_with_complete_labels(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    bids_input(tmp_path / "in")
    fix = corrections(tmp_path / "fix.tsv", [("PATIENT01", "AD"), ("PATIENT02", "CN")])
    assert main(["--verbose", "dataset", "build", str(tmp_path / "in"), "--output-dir", "out", "--config",
                 "config/run.yaml", "--classes", "AD=Alzheimer", "CN", "--corrections", str(fix),
                 "--ratios", "0.5", "0.5", "0"]) == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "Studies written: 2  series: 2  participants: 2  errors: 1" in out
    assert "Label corrections applied: 2" in out and "Labels finalized (2 labels)." in out
    assert "ML export files written: 4" in out and "Report files written: 4" in out
    assert "Errors by type: {'ValueError': 1}" in out
    assert (tmp_path / "out" / "dataset" / "labels_final.json").is_file()
    for text in (out, captured.err, caplog.text):
        assert clean(text, tmp_path)


def test_build_with_incomplete_labels_skips_ml_exports(tmp_path, capsys):
    bids_input(tmp_path / "in")
    assert build(tmp_path, "--classes", "AD", "CN") == 0
    out = capsys.readouterr().out
    assert "WARNING LABELS_INCOMPLETE: {'UNLABELED': 2}" in out and "ML exports: skipped" in out
    assert not (tmp_path / "out" / "dataset" / "splits.json").exists()


def test_build_quiet_keeps_warnings_and_totals(tmp_path, capsys):
    bids_input(tmp_path / "in")
    assert main(["--quiet", "dataset", "build", str(tmp_path / "in"), "--output-dir", "out", "--config",
                 "config/run.yaml", "--classes", "AD"]) == 0
    out = capsys.readouterr().out
    assert "Exporting" not in out and "WARNING LABELS_INCOMPLETE" in out and "Errors by type" in out


@pytest.mark.parametrize(
    ("extra", "message", "code"),
    [
        (["--config", "config/plain.yaml"], "The pipeline must include the anonymize step.", 2),
        (["--config", "config/none.yaml"], "Config file not found.", 2),
        (["--classes", "A", "A"], "Invalid --classes.", 2),
        (["--corrections", "fix.tsv"], "--corrections needs --classes.", 2),
        (["--ratios", "0.5", "0.6", "0.1"], "Invalid --ratios.", 2),
        (["--output-dir", "in/out"], "Output directory must be outside the dataset directory.", 2),
        (["--output-dir", "busy"], "Output directory already exists; choose a new one.", 1),
    ],
)
def test_build_validation_before_creating_anything(tmp_path, capsys, extra, message, code):
    bids_input(tmp_path / "in")
    (tmp_path / "fix.tsv").write_text("x", encoding="utf-8")
    (tmp_path / "busy").mkdir()
    before = sorted(tmp_path.rglob("*"))
    # later options win in argparse, so the defaults of build() are overridden by *extra*
    assert build(tmp_path, *extra) == code
    out = capsys.readouterr().out
    assert message in out and clean(out, tmp_path)
    assert sorted(tmp_path.rglob("*")) == before


def test_build_needs_the_key_and_the_input(tmp_path, monkeypatch, capsys):
    assert build(tmp_path) == 2  # no input
    assert "Dataset directory not found." in capsys.readouterr().out
    bids_input(tmp_path / "in")
    monkeypatch.delenv("MRI_ANON_KEY")
    assert build(tmp_path) == 2
    assert "MRI_ANON_KEY is not set" in capsys.readouterr().out and not (tmp_path / "out").exists()


def test_build_failed_stage(tmp_path, capsys):
    bids_input(tmp_path / "in")
    (tmp_path / "bad.tsv").write_text("not\ta labels\ttable\n", encoding="utf-8")
    assert build(tmp_path, "--classes", "AD", "--corrections", "bad.tsv") == 1
    out = capsys.readouterr().out
    assert "Run failed at labels: ValueError" in out and clean(out, tmp_path)


def test_export_ml_after_finalizing_labels(tmp_path, capsys):
    bids_input(tmp_path / "in")
    assert build(tmp_path, "--classes", "AD", "CN") == 0  # incomplete: no ML exports yet
    dataset = str(tmp_path / "out" / "dataset")
    assert main(["dataset", "export-ml", dataset]) == 1
    assert "ML exports failed: ValueError" in capsys.readouterr().out  # labels not finalized
    fix = corrections(tmp_path / "fix.tsv", [("PATIENT01", "AD"), ("PATIENT02", "CN")])
    assert main(["labels", "apply", dataset, "--corrections", str(fix)]) == 0
    assert main(["labels", "finalize", dataset]) == 0
    capsys.readouterr()
    assert main(["dataset", "export-ml", dataset, "--ratios", "0.5", "0.5", "0", "--seed", "3"]) == 0
    assert "ML export files written: 4" in capsys.readouterr().out
    assert main(["dataset", "export-ml", dataset]) == 1
    assert "ML export files already exist." in capsys.readouterr().out


def test_export_ml_allow_unfinalized(tmp_path, capsys):
    bids_input(tmp_path / "in")
    assert build(tmp_path, "--classes", "AD") == 0
    assert main(["dataset", "export-ml", str(tmp_path / "out" / "dataset"), "--allow-unfinalized"]) == 0
    assert "ML export files written: 4" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["dataset", "export-ml", "missing"], "Dataset directory not found."),
        (["dataset", "export-ml", "in", "--ratios", "1", "1", "1"], "Invalid --ratios."),
        (["dataset", "report", "missing", "rep"], "Dataset directory not found."),
        (["dataset", "report", "in", "in/rep"], "Report directory must be outside the dataset."),
        (["dataset", "report", "in", "a_file"], "Output path is not a directory."),
    ],
)
def test_export_ml_and_report_validation(tmp_path, capsys, argv, message):
    bids_input(tmp_path / "in")
    # passes is_exported_dataset, so the later checks are reached
    (tmp_path / "in" / "dataset_description.json").write_text('{"GeneratedBy": [{"Name": "MRI-Dataset-Tool"}]}', "utf-8")
    (tmp_path / "a_file").write_text("x", encoding="utf-8")
    before = sorted(tmp_path.rglob("*"))
    assert main(argv) == 2
    assert message in capsys.readouterr().out
    assert sorted(tmp_path.rglob("*")) == before


def test_report_writes_four_files_and_never_overwrites(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    bids_input(tmp_path / "in")
    assert build(tmp_path) == 0
    dataset = str(tmp_path / "out" / "dataset")
    capsys.readouterr()
    assert main(["--verbose", "dataset", "report", dataset, "rep"]) == 0
    captured = capsys.readouterr()
    assert "Report files written: 4" in captured.out and "Report read errors: none" in captured.out
    assert len(list((tmp_path / "rep").iterdir())) == 4
    for text in (captured.out, captured.err, caplog.text):
        assert clean(text, tmp_path)
    assert main(["dataset", "report", dataset, "rep"]) == 1
    assert "Report files already exist." in capsys.readouterr().out


@pytest.mark.parametrize(("free", "warned"), [(10, True), (10**15, False)])
def test_low_disk_space_warns_without_changing_the_exit_code(tmp_path, monkeypatch, capsys, free, warned):
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(disk_space.shutil, "disk_usage", lambda path: usage(free, 0, free))
    bids_input(tmp_path / "in")
    assert build(tmp_path) == 0
    out = capsys.readouterr().out
    assert ("WARNING INSUFFICIENT_DISK_SPACE" in out) == warned
    assert "drive C:" not in out
    assert clean(out, tmp_path)
