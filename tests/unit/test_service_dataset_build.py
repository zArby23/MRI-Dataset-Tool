"""``dataset_build`` service (validation before creating anything, status events, typed failures)."""

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.services.dataset_build import (
    InvalidBuildInput,
    StageFailed,
    build_dataset,
    check_build_args,
    load_build_pipeline,
    parse_classes,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import load_key, pseudonymize_label

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config" / "stage3_bids.yaml"
KEY = "k" * 40


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", KEY)


def _dataset(root: Path) -> Path:
    """Three participants with a T1w; sub-03 holds a NaN, so the validate step rejects it."""
    rng = np.random.default_rng(0)
    for subject in ("01", "02", "03"):
        volume = rng.uniform(10, 100, (4, 5, 3)).astype(np.float32)
        if subject == "03":
            volume[1, 1, 1] = np.nan
        path = root / f"sub-{subject}" / "anat" / f"sub-{subject}_T1w.nii.gz"
        path.parent.mkdir(parents=True)
        nib.save(nib.Nifti1Image(volume, np.diag([1.5, 1.5, 1.5, 1.0])), path)
    return root


def _corrections(path: Path, rows: list[tuple[str, str]]) -> Path:
    key = load_key()
    lines = ["participant_id\tsession_id\tlabel"]
    lines += [f"sub-{pseudonymize_label(subject, 'subject', key)}\t\t{label}" for subject, label in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _build(source: Path, out: Path, **kwargs):
    config, pipeline = load_build_pipeline(CONFIG, REPO / "config")
    events, errors = [], []
    result = build_dataset(
        source, out, pipeline, config, on_error=lambda p, e: errors.append(type(e).__name__),
        on_status=lambda event, counts: events.append((event, counts)), **kwargs,
    )
    return result, events, errors


def test_parse_classes():
    assert parse_classes(["AD=Alzheimer", "CN"]) == {"AD": "Alzheimer", "CN": ""}
    with pytest.raises(ValueError, match="Repeated class name."):
        parse_classes(["A=x", "A=y"])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"dataset_root": "missing"}, "Dataset directory not found."),
        ({"config_path": "none.yaml"}, "Config file not found."),
        ({"class_items": ["A", "A"]}, "Invalid --classes."),
        ({"class_items": ["=bad"]}, "Invalid --classes."),
        ({"corrections": "fix.tsv"}, "--corrections needs --classes."),
        ({"class_items": ["A"], "corrections": "none.tsv"}, "Corrections file not found."),
        ({"ratios": (0.5, 0.6, 0.1)}, "Invalid --ratios."),
        ({"output_dir": "ds/out"}, "Output directory must be outside the dataset directory."),
    ],
)
def test_check_build_args_rejects_before_creating_anything(tmp_path, kwargs, message):
    _dataset(tmp_path / "ds")
    (tmp_path / "fix.tsv").write_text("x", encoding="utf-8")
    args = {"dataset_root": "ds", "output_dir": "out", "config_path": CONFIG, **kwargs}
    paths = ("dataset_root", "output_dir", "config_path", "corrections")
    args = {k: tmp_path / v if k in paths else v for k, v in args.items()}  # an absolute CONFIG stays as is
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(InvalidBuildInput) as raised:
        check_build_args(**args)
    assert str(raised.value) == message
    assert sorted(tmp_path.rglob("*")) == before


def test_check_build_args_existing_output_and_classes(tmp_path):
    source = _dataset(tmp_path / "ds")
    assert check_build_args(source, tmp_path / "out", CONFIG) is None
    assert check_build_args(source, tmp_path / "out", CONFIG, ["AD=x", "CN"]) == {"AD": "x", "CN": ""}
    (tmp_path / "out").mkdir()
    with pytest.raises(FileExistsError, match="Output directory already exists; choose a new one."):
        check_build_args(source, tmp_path / "out", CONFIG)


def test_load_build_pipeline_requires_anonymize_and_a_valid_config(tmp_path):
    no_anon = tmp_path / "no_anon.yaml"
    no_anon.write_text("pipeline:\n  steps:\n    - name: validate\n", encoding="utf-8")
    with pytest.raises(InvalidBuildInput, match="The pipeline must include the anonymize step."):
        load_build_pipeline(no_anon, REPO / "config")
    bad = tmp_path / "bad.yaml"
    bad.write_text("pipeline: [unclosed", encoding="utf-8")
    with pytest.raises(InvalidBuildInput, match=r"^Invalid config: ValueError$"):
        load_build_pipeline(bad, REPO / "config")
    config, pipeline = load_build_pipeline(CONFIG, REPO / "config")
    assert "anonymize" in [step.name for step in pipeline.steps] and "pipeline" in config


def test_full_build_with_complete_labels(tmp_path):
    fix = _corrections(tmp_path / "fix.tsv", [("01", "AD"), ("02", "CN")])
    result, events, errors = _build(
        _dataset(tmp_path / "ds"), tmp_path / "out", classes={"AD": "", "CN": ""}, corrections=fix, ratios=(0.5, 0.5, 0)
    )
    assert [event for event, _ in events] == [
        "export", "exported", "label_template", "corrections_applied", "labels_finalized", "ml_exports", "report",
    ]
    counts = dict(events)
    assert counts["exported"] == {"studies": 2, "series": 2, "participants": 2, "errors": 1}
    assert counts["corrections_applied"] == {"rows": 2} and counts["labels_finalized"] == {"labels": 2}
    assert result.review.is_complete and result.ml_files and len(result.report_files) == 4
    assert errors == ["ValueError"]
    assert all(isinstance(n, int) for _, c in events for n in c.values())  # counts only, never paths or ids


def test_incomplete_labels_skip_ml_exports_unless_allowed(tmp_path):
    source = _dataset(tmp_path / "ds")
    result, events, _ = _build(source, tmp_path / "out1", classes={"AD": "", "CN": ""})
    assert ("labels_incomplete", {"UNLABELED": 2}) in events and ("ml_exports_skipped", {}) in events
    assert result.ml_files is None and not result.review.is_complete
    result, events, _ = _build(source, tmp_path / "out2", classes={"AD": "", "CN": ""}, allow_unfinalized=True)
    assert result.ml_files and "ml_exports" in [event for event, _ in events]


def test_without_classes_labels_are_skipped(tmp_path):
    result, events, _ = _build(_dataset(tmp_path / "ds"), tmp_path / "out")
    assert "labels_skipped" in [event for event, _ in events] and result.review is None and result.ml_files


def test_a_failed_stage_raises_stage_failed(tmp_path):
    bad_fix = tmp_path / "fix.tsv"
    bad_fix.write_text("not\ta labels\ttable\nsub-x\t\tAD\n", encoding="utf-8")
    with pytest.raises(StageFailed) as raised:
        _build(_dataset(tmp_path / "ds"), tmp_path / "out", classes={"AD": ""}, corrections=bad_fix)
    assert raised.value.stage == "labels" and str(raised.value) == "Stage failed: labels."
