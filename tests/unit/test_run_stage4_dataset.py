"""scripts/run_stage4_dataset.py: arguments, exit codes, skipped stages and a clean console."""

import importlib.util
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.anonymization.pseudonym import load_key, pseudonymize_label

REPO = Path(__file__).resolve().parents[2]
KEY = "k" * 40

_spec = importlib.util.spec_from_file_location("run_stage4_dataset", REPO / "scripts" / "run_stage4_dataset.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRI_ANON_KEY", KEY)


def _dataset(root: Path) -> Path:
    """Three participants with a T1w; sub-03 holds a NaN, so the pipeline's validate step rejects it."""
    rng = np.random.default_rng(0)
    for subject in ("01", "02", "03"):
        volume = rng.uniform(10, 100, (4, 5, 3)).astype(np.float32)
        if subject == "03":
            volume[1, 1, 1] = np.nan
        path = root / "in" / f"sub-{subject}" / "anat" / f"sub-{subject}_T1w.nii.gz"
        path.parent.mkdir(parents=True)
        nib.save(nib.Nifti1Image(volume, np.diag([1.5, 1.5, 1.5, 1.0])), path)
    return root / "in"


def _corrections(path: Path, rows: list[tuple[str, str]]) -> Path:
    key = load_key()
    lines = ["participant_id\tsession_id\tlabel"]
    lines += [f"sub-{pseudonymize_label(subject, 'subject', key)}\t\t{label}" for subject, label in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _assert_clean(out: str, tmp_path: Path) -> None:
    assert "sub-" not in out and str(tmp_path) not in out and tmp_path.as_posix() not in out and KEY not in out


def test_full_run_writes_dataset_labels_exports_and_report(tmp_path: Path, capsys) -> None:
    source = _dataset(tmp_path)
    corrections = _corrections(tmp_path / "fix.tsv", [("01", "AD"), ("02", "CN")])
    out_dir = tmp_path / "out"
    args = [str(source), "--output-dir", str(out_dir), "--classes", "AD=Alzheimer", "CN",
            "--corrections", str(corrections), "--ratios", "0.5", "0.5", "0", "--seed", "3"]

    assert script.main(args) == 0
    out = capsys.readouterr().out

    assert "Studies written: 2  series: 2  participants: 2  errors: 1" in out
    assert "Label template written (2 classes)." in out and "Label corrections applied: 2" in out
    assert "Labels finalized (2 labels)." in out
    assert "ML export files written: 4" in out and "Report files written: 4" in out
    assert "Errors by type: {'ValueError': 1}" in out
    assert "WARNING: the output is on drive C: or in the temporary directory" in out  # tmp_path
    _assert_clean(out, tmp_path)
    dataset = out_dir / "dataset"
    assert json.loads((dataset / "labels.json").read_text(encoding="utf-8"))["label"]["Levels"] == {
        "AD": "Alzheimer", "CN": "",
    }
    assert json.loads((dataset / "splits.json").read_text(encoding="utf-8"))["seed"] == 3
    report = json.loads((out_dir / "report" / "dataset_report.json").read_text(encoding="utf-8"))
    assert report["labels"]["classes"]["AD"]["participants"] == 1
    assert [step["name"] for step in report["pipeline"]["steps"]][:2] == ["validate", "anonymize"]

    assert script.main(args) == 1  # nothing is overwritten
    assert capsys.readouterr().out.endswith("Output directory already exists; choose a new one.\n")


def test_stages_without_arguments_are_skipped(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "out"
    assert script.main([str(_dataset(tmp_path)), "--output-dir", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "Labels: skipped (no --classes)." in out
    assert "ML export files written: 4" in out and "Report files written: 4" in out
    assert not (out_dir / "dataset" / "labels.tsv").exists()
    assert json.loads((out_dir / "report" / "dataset_report.json").read_text(encoding="utf-8"))["labels"] is None


def test_incomplete_labels_skip_the_ml_exports_but_not_the_report(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "out"
    assert script.main([str(_dataset(tmp_path)), "--output-dir", str(out_dir), "--classes", "AD", "CN"]) == 0
    out = capsys.readouterr().out
    assert "Label corrections: skipped (no --corrections)." in out
    assert "WARNING LABELS_INCOMPLETE: {'UNLABELED': 2}" in out
    assert "ML exports: skipped (labels incomplete; fix them or use --allow-unfinalized)." in out
    assert "Report files written: 4" in out
    dataset = out_dir / "dataset"
    assert (dataset / "labels.tsv").exists()
    assert not (dataset / "labels_final.json").exists() and not (dataset / "splits.json").exists()


def test_allow_unfinalized_writes_the_ml_exports(tmp_path: Path, capsys) -> None:
    source = _dataset(tmp_path)
    corrections = _corrections(tmp_path / "fix.tsv", [("01", "AD")])
    out_dir = tmp_path / "out"
    args = [str(source), "--output-dir", str(out_dir), "--classes", "AD", "CN",
            "--corrections", str(corrections), "--allow-unfinalized"]
    assert script.main(args) == 0
    out = capsys.readouterr().out
    assert "WARNING LABELS_INCOMPLETE: {'UNLABELED': 1}" in out and "ML export files written: 4" in out
    assert not (out_dir / "dataset" / "labels_final.json").exists()


def test_a_failing_stage_stops_with_its_name_and_type(tmp_path: Path, capsys) -> None:
    source = _dataset(tmp_path)
    corrections = _corrections(tmp_path / "fix.tsv", [("01", "XX")])  # class outside --classes
    args = [str(source), "--output-dir", str(tmp_path / "out"), "--classes", "AD", "--corrections", str(corrections)]
    assert script.main(args) == 1
    out = capsys.readouterr().out
    assert out.endswith("Run failed at labels: ValueError\n")
    _assert_clean(out, tmp_path)


def test_without_key_nothing_is_created(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.delenv("MRI_ANON_KEY")
    assert script.main([str(_dataset(tmp_path)), "--output-dir", str(tmp_path / "out")]) == 2
    assert capsys.readouterr().out == "MRI_ANON_KEY is not set or is shorter than 32 characters; nothing was run.\n"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--classes", "=x"], "Invalid --classes."),
        (["--classes", "+AD"], "Invalid --classes."),
        (["--corrections", "fix.tsv"], "--corrections needs --classes."),
        (["--classes", "AD", "--corrections", "missing.tsv"], "Corrections file not found."),
        (["--ratios", "0.5", "0.5", "0.5"], "Invalid --ratios."),
        (["--config", "missing.yaml"], "Config file not found."),
    ],
)
def test_invalid_arguments_exit_2_before_creating_anything(tmp_path: Path, capsys, extra, message) -> None:
    source = _dataset(tmp_path)
    extra = [str(tmp_path / e) if e.endswith((".tsv", ".yaml")) else e for e in extra]
    assert script.main([str(source), "--output-dir", str(tmp_path / "out"), *extra]) == 2
    assert capsys.readouterr().out == message + "\n"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("relative", [".", "derivatives/out"])
def test_output_inside_the_input_creates_nothing(tmp_path: Path, capsys, relative: str) -> None:
    source = _dataset(tmp_path)
    before = sorted(source.rglob("*"))
    assert script.main([str(source), "--output-dir", str(source / relative)]) == 2
    assert capsys.readouterr().out == "Output directory must be outside the dataset directory.\n"
    assert sorted(source.rglob("*")) == before


def test_missing_dataset_and_output_dir(tmp_path: Path, capsys) -> None:
    assert script.main([str(tmp_path / "nope"), "--output-dir", str(tmp_path / "out")]) == 2
    assert capsys.readouterr().out == "Dataset directory not found.\n"
    with pytest.raises(SystemExit) as exit_info:
        script.main([str(tmp_path)])
    assert exit_info.value.code == 2
    assert "the following arguments are required: --output-dir" in capsys.readouterr().err
