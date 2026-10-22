"""QA4 (2): hostile inputs for the stage 4 dataset: writer volumes, manipulated label files, foreign
files in the dataset, hostile paths. Known defects are ``xfail(strict=True)`` with their QA4 id
(docs/testing/qa_etapa4.md), so a fix turns them into a failure that asks to drop the marker.
"""

import importlib.util
import io
import json
import shutil
import sys
import warnings
import zipfile
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config
from mri_dataset_tool.application.services.dataset import export_dataset, write_ml_exports
from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.application.services.labels import (
    apply_label_corrections,
    dataset_pairs,
    finalize_labels,
    review_labels,
    write_label_template,
)
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.dataset.bids_writer import BIDSDatasetWriter
from mri_dataset_tool.infrastructure.dataset.labels import LabelTable

CLASSES = {"A": "Class A", "B": "Class B"}
ML_FILES = ("dataset_index.csv", "datalist.json", "splits.tsv", "splits.json")


def _study(subject: str, volume: np.ndarray | None = None, session: str | None = None, suffix: str = "T1w") -> MRIStudy:
    volume = np.random.default_rng(len(subject)).uniform(1, 9, (4, 5, 6)).astype(np.float32) if volume is None else volume
    metadata = {"shape": list(volume.shape), "affine": np.diag([1.0, 1.0, 1.0, 1.0])}
    return MRIStudy(None, [MRISeries(modality=suffix, volume=volume, metadata=metadata)], subject_id=subject, session_id=session)


def _dataset(root: Path, count: int = 4) -> Path:
    export_dataset([_study(f"p{i}") for i in range(count)], root)
    return root


def _labelled(root: Path) -> Path:
    _dataset(root, 6)
    write_label_template(root, CLASSES)
    corrections = root.parent / "corrections.tsv"
    corrections.write_text(
        "participant_id\tsession_id\tlabel\n" + "".join(f"sub-p{i}\t\t{'AB'[i % 2]}\n" for i in range(6)), encoding="utf-8"
    )
    apply_label_corrections(root, corrections)
    finalize_labels(root)
    return root


def _write_one(tmp_path: Path, volume: np.ndarray) -> tuple[list[Path], list[Exception]]:
    writer = BIDSDatasetWriter(tmp_path / "ds")
    errors: list[Exception] = []
    written = writer.add_study(_study("p1", volume), lambda _path, error: errors.append(error))
    return written, errors


# --- Writer: volumes the stage 3 pipeline would reject reach the writer through export_dataset(pipeline=None)


@pytest.mark.parametrize("shape", [(4, 4), (3, 3, 3, 2, 2)])
def test_writer_rejects_volumes_that_are_not_3d_or_4d(tmp_path: Path, shape) -> None:
    written, errors = _write_one(tmp_path, np.ones(shape, np.float32))
    assert written == [] and [type(e) for e in errors] == [ValueError]


def test_writer_does_not_silently_turn_finite_values_into_inf(tmp_path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        written, errors = _write_one(tmp_path, np.full((3, 3, 3), 1e300))
    assert errors or np.isfinite(np.asanyarray(nib.load(written[0]).dataobj)).all()


@pytest.mark.parametrize("shape", [(4, 4, 1), (3, 3, 3, 1)])
def test_single_slice_and_single_volume_4d_round_trip(tmp_path: Path, shape) -> None:
    written, errors = _write_one(tmp_path, np.arange(np.prod(shape), dtype=np.float32).reshape(shape) + 1)
    assert errors == [] and nib.load(written[0]).shape == shape


def test_complex_volume_is_reported_and_nothing_is_left(tmp_path: Path) -> None:
    written, errors = _write_one(tmp_path, np.ones((3, 3, 3), np.complex64))
    assert written == [] and [str(e) for e in errors] == ["Unsupported NIfTI data type."]
    assert [p.name for p in (tmp_path / "ds").iterdir()] == []  # no empty sub-/anat folders, no temporaries


def test_truncated_lazy_gz_is_reported_and_the_rest_is_exported(tmp_path: Path) -> None:
    source = tmp_path / "in"
    for index in range(3):
        path = source / f"sub-p{index}" / "anat" / f"sub-p{index}_T1w.nii.gz"
        path.parent.mkdir(parents=True)
        nib.save(nib.Nifti1Image(np.random.default_rng(index).random((16, 16, 16)).astype(np.float32), np.eye(4)), path)
    broken = source / "sub-p1" / "anat" / "sub-p1_T1w.nii.gz"
    broken.write_bytes(broken.read_bytes()[: broken.stat().st_size // 2])
    errors: list[Exception] = []
    root = tmp_path / "ds"
    report = export_dataset(BIDSBatchReader().iter_studies(source, lazy=True), root, lambda _p, e: errors.append(e))
    assert (report.series_written, report.errors) == (2, 1)
    assert [str(e) for e in errors] == ["Unable to read volume data."]
    assert not (root / "sub-p1").exists() and not list(root.rglob(".*.tmp*"))
    assert (root / "participants.tsv").read_text(encoding="utf-8").split() == ["participant_id", "sub-p0", "sub-p2"]


# --- Labels: classes and manipulated files


def test_a_class_accepted_by_the_label_table_can_be_reported(tmp_path: Path) -> None:
    # QA4-04 (fixed): a class the report cannot hold is rejected when declared.
    classes = {"A\x01": "x", "B": "y"}
    with pytest.raises(ValueError, match=r"^Label classes are invalid\.$"):
        LabelTable(classes)  # this is what the launcher's --classes check runs
    root = _dataset(tmp_path / "ds")
    with pytest.raises(ValueError, match=r"^Label classes are invalid\.$"):
        write_label_template(root, classes)
    assert not (root / "labels.tsv").exists()
    write_label_template(root, {"Ñandú 漢": "x", "B": "y"})  # unusual but accepted → reportable
    assert len(report_dataset(root, tmp_path / "report")) == 4


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('participant_id\tsession_id\tlabel\n"sub-p0"\t\tA\n', "Label table has an invalid participant or session id."),
        ("participant_id\tsession_id\tlabel\nsub-p0\t\t=HYPERLINK(1)\n", "Label table has an unknown class."),
        ("participant_id\tsession_id\tlabel\nsub-p0\t\t+A\n", "Label table has an unknown class."),
        ("participant_id\tsession_id\tlabel\nsub-p0\t\tA\t\n", "Label table has a malformed row."),
        ("participant_id\tsession_id\tlabel\nsub-p0 \t\tA\n", "Label table has an invalid participant or session id."),
        ("participant_id\tsession_id\tlabel\nsub-pé\t\tA\n", "Label table has an invalid participant or session id."),
        ("participant_id\tsession_id\tlabel\nsub-zz\t\tA\n", "Correction targets a participant/session not in the dataset."),
        ("participant_id\tsession_id\tlabel\nsub-p0\t\tA\nsub-p0\t\tB\n", "Corrections have a duplicate participant/session."),
        ("participant_id\tsession_id\tlabel\n", "Label table is empty."),
        ("participant_id\tlabel\nsub-p0\tA\n", "Label table is missing required columns."),
        ("participant_id\tsession_id\tlabel\nsub-p0\t\tA\x00\n", "Label table has an unknown class."),
        (None, "Label table is not valid UTF-8."),
    ],
)
def test_hostile_corrections_are_rejected_whole_with_a_fixed_message(tmp_path: Path, body, message) -> None:
    root = _dataset(tmp_path / "ds")
    write_label_template(root, CLASSES)
    before = (root / "labels.tsv").read_bytes()
    corrections = tmp_path / "c.tsv"
    if body is None:
        corrections.write_text("participant_id\tsession_id\tlabel\nsub-p0\t\tA\n", encoding="utf-16")  # Excel "Unicode text"
    else:
        corrections.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        apply_label_corrections(root, corrections)
    assert str(caught.value) == message
    assert (root / "labels.tsv").read_bytes() == before and not (root / "labels_changes.tsv").exists()


def test_formatting_only_edits_keep_the_closure_and_a_label_edit_breaks_it(tmp_path: Path) -> None:
    root = _labelled(tmp_path / "ds")
    text = (root / "labels.tsv").read_text(encoding="utf-8")
    (root / "labels.tsv").write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))  # Excel: BOM + CRLF
    assert len(write_ml_exports(root)) == 4
    for name in ML_FILES:
        (root / name).unlink()
    (root / "labels.tsv").write_text(text.replace("sub-p0\t\tA", "sub-p0\t\tB"), encoding="utf-8")
    with pytest.raises(ValueError, match="^Labels are not finalized.$"):
        write_ml_exports(root)
    assert not any((root / name).exists() for name in ML_FILES)


@pytest.mark.parametrize("content", [b"[]", b"null", b'{"sha256": 5}', b"\xff\xfe", b""])
def test_malformed_closure_file_means_not_finalized(tmp_path: Path, content: bytes) -> None:
    root = _labelled(tmp_path / "ds")
    (root / "labels_final.json").write_bytes(content)
    with pytest.raises(ValueError, match="^Labels are not finalized.$"):
        write_ml_exports(root)


def test_changes_log_without_final_newline_gets_a_clean_row(tmp_path: Path) -> None:
    root = _labelled(tmp_path / "ds")
    log = root / "labels_changes.tsv"
    log.write_bytes(log.read_bytes().rstrip(b"\n"))
    (root / "labels_final.json").unlink()  # hand removal instead of reopen_labels
    corrections = tmp_path / "c.tsv"
    corrections.write_text("participant_id\tsession_id\tlabel\nsub-p0\t\tB\n", encoding="utf-8")
    assert apply_label_corrections(root, corrections) == 1
    rows = log.read_text(encoding="utf-8").splitlines()
    assert all(len(row.split("\t")) == 6 for row in rows), rows


# --- Foreign content inside the dataset


def test_foreign_nifti_blocks_the_ml_exports_but_not_the_report(tmp_path: Path) -> None:
    root = _dataset(tmp_path / "ds")
    nib.save(nib.Nifti1Image(np.ones((3, 3, 3), np.float32), np.eye(4)), root / "sub-p0" / "anat" / "sub-p0_acq-x_T1w.nii.gz")
    with pytest.raises(ValueError, match="^Dataset contains a file outside the BIDS layout.$"):
        write_ml_exports(root)
    assert not any((root / name).exists() for name in ML_FILES)
    assert len(report_dataset(root, tmp_path / "report")) == 4


def test_bidsignore_and_hidden_folders_are_ignored(tmp_path: Path) -> None:
    root = _dataset(tmp_path / "ds")
    (root / ".bidsignore").write_text("labels*\ndataset_index.csv\ndatalist.json\nsplits.*\n", encoding="utf-8")
    hidden = root / ".git" / "sub-p9" / "anat"
    hidden.mkdir(parents=True)
    nib.save(nib.Nifti1Image(np.ones((3, 3, 3), np.float32), np.eye(4)), hidden / "sub-p9_T1w.nii.gz")
    assert [p for p, _ in dataset_pairs(root)] == ["p0", "p1", "p2", "p3"]
    write_label_template(root, CLASSES)
    assert len(write_ml_exports(root, allow_unfinalized=True)) == 4
    report_dataset(root, tmp_path / "report")
    summary = json.loads((tmp_path / "report" / "dataset_report.json").read_text(encoding="utf-8"))
    assert (summary["participants"], summary["warnings"]) == (4, [{"code": "UNLABELED_SESSIONS", "count": 4}])


def test_a_subject_folder_without_images_is_not_a_dataset_pair(tmp_path: Path) -> None:
    root = _dataset(tmp_path / "ds")
    (root / "sub-ghost").mkdir()
    assert [p for p, _ in dataset_pairs(root)] == ["p0", "p1", "p2", "p3"]


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive file system")
@pytest.mark.xfail(strict=True, reason="QA4-08: ids that differ only in case share a folder on Windows")
def test_ids_differing_only_in_case_stay_separate(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    export_dataset([_study("AB", session="01"), _study("ab")], root)
    assert sorted(dataset_pairs(root)) == [("AB", "01"), ("ab", None)]
    assert len(write_ml_exports(root)) == 4


def test_unicode_spaces_and_long_output_paths(tmp_path: Path) -> None:
    out = tmp_path / "salida ñandú 漢字" / ("x" * 90) / ("y" * 90)
    root = out / "dataset con espacios"
    assert len(str(root / "sub-p0" / "anat" / ".sub-p0_T1w.nii.gz.tmp.nii.gz")) > 260
    _labelled(root)
    assert len(write_ml_exports(root)) == 4
    assert len(report_dataset(root, out / "reporte ü")) == 4
    assert review_labels(root).is_complete and len(BIDSBatchReader().load_studies(root, lazy=True)) == 6
    shutil.rmtree(tmp_path / "salida ñandú 漢字")


# --- Report formats with hand-edited content


def test_hand_edited_manifest_cannot_put_a_formula_in_the_xlsx(tmp_path: Path) -> None:
    root = _dataset(tmp_path / "ds")
    manifest = json.loads(RunManifest.from_run({}, pipeline_from_config({"pipeline": {"steps": [{"name": "validate"}]}}), []).to_json())
    manifest["steps"][0].update(name='=HYPERLINK("http://x","y")', params={"a": "@SUM(1)", "b": "-2+3", "c": "=1+1"})
    (root / "code").mkdir()
    (root / "code" / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    paths = report_dataset(root, tmp_path / "report")
    xlsx = next(p for p in paths if p.suffix == ".xlsx")
    with zipfile.ZipFile(io.BytesIO(xlsx.read_bytes())) as archive:
        sheets = b"".join(archive.read(n) for n in archive.namelist() if n.startswith("xl/worksheets/"))
    assert b"<f>" not in sheets and b"<f " not in sheets
    summary = json.loads((tmp_path / "report" / "dataset_report.json").read_text(encoding="utf-8"))
    assert summary["pipeline"]["steps"][0]["name"].startswith("=HYPERLINK")  # the hostile text really reached the report


def test_finalized_labels_without_their_table_block_the_ml_exports(tmp_path: Path) -> None:
    root = _labelled(tmp_path / "ds")
    (root / "labels.tsv").rename(root / "labels.txt")  # a rename or an Excel "save as"
    with pytest.raises((ValueError, FileNotFoundError)):
        write_ml_exports(root)


_spec = importlib.util.spec_from_file_location("run_stage4_dataset_qa4h", Path(__file__).resolve().parents[2] / "scripts" / "run_stage4_dataset.py")
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


def test_repeated_class_names_are_rejected() -> None:
    with pytest.raises(ValueError):
        launcher.parse_classes(["A=first", "A=second"])


def test_launcher_refuses_a_pipeline_without_anonymize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """QA4-01 (fixed in 23b7490): without anonymize the dataset would carry the source ids."""
    monkeypatch.setenv("MRI_ANON_KEY", "qa4-anonymization-key-0123456789abcdef")
    source = tmp_path / "in" / "sub-PlantedName" / "anat"
    source.mkdir(parents=True)
    nib.save(nib.Nifti1Image(np.ones((3, 3, 3), np.float32), np.eye(4)), source / "sub-PlantedName_T1w.nii.gz")
    config = tmp_path / "c.yaml"
    config.write_text("pipeline:\n  steps:\n    - name: validate\n", encoding="utf-8")
    out = tmp_path / "out"
    assert launcher.main([str(tmp_path / "in"), "--output-dir", str(out), "--config", str(config)]) == 2
    assert capsys.readouterr().out.splitlines()[-1] == "The pipeline must include the anonymize step." and not out.exists()
