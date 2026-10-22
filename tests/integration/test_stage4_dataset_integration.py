"""E2 integration: synthetic BIDS batch → stage 3 pipeline → BIDS dataset → labels → ML exports → report."""

import csv
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

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.services.dataset import export_dataset, write_ml_exports
from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.application.services.labels import (
    apply_label_corrections,
    dataset_pairs,
    finalize_labels,
    review_labels,
    write_label_template,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import load_key, pseudonymize_label
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.config.loader import load_config

REPO = Path(__file__).resolve().parents[2]
KEY = "k" * 40
CLASSES = {"tumor": "Tumor", "control": "Control"}
INPUT_MARKER = "InputRootMarker7731"  # a folder name of the input tree: must never reach the output

# Planted identifiers: original ids (pseudonymized by `anonymize`), sidecar PHI and a NIfTI header field.
SUBJECTS = {"JohnDoe01": "Visit19570312", "JaneRoe02": "Visit19601105", "MaxMus03": "Visit19720730", "NanCase04": "Visit19800101"}
PHI_SIDECAR = {
    "PatientName": "Doe^PlantedName",
    "PatientID": "PlantedPatientId778899",
    "InstitutionName": "PlantedHospital",
    "AcquisitionDateTime": "1957-03-12T08:15:00",
    "DeviceSerialNumber": "PlantedSerial4242",
}
PLANTED = [*SUBJECTS, *SUBJECTS.values(), *PHI_SIDECAR.values(), "PlantedDescrip", INPUT_MARKER]


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRI_ANON_KEY", KEY)


def _save(path: Path, volume: np.ndarray, affine: np.ndarray, sidecar: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = nib.Nifti1Image(volume.astype(np.float32), affine)
    image.header["descrip"] = b"PlantedDescrip"
    nib.save(image, path)
    if sidecar is not None:
        path.with_name(path.name.replace(".nii.gz", ".json")).write_text(json.dumps(sidecar), encoding="utf-8")


def _input(tmp_path: Path) -> Path:
    """Four studies: LPS 1.5 mm T1w + 4D dwi; RAS 1 mm T1w + T2w; oblique-free LAS anisotropic T1w; T1w with NaN."""
    rng = np.random.default_rng(0)
    root = tmp_path / INPUT_MARKER / "bids"
    (root / "dataset_description.json").parent.mkdir(parents=True)
    (root / "dataset_description.json").write_text('{"Name": "synthetic", "BIDSVersion": "1.9.0"}', encoding="utf-8")
    sidecar = {**PHI_SIDECAR, "EchoTime": 0.03, "RepetitionTime": 2.0}
    las = np.diag([-0.8, 1.2, 2.0, 1.0])
    las[:3, 3] = [10.0, -20.0, 5.0]
    nan_volume = rng.uniform(10, 100, (6, 6, 6))
    nan_volume[2, 2, 2] = np.nan
    images = {
        ("JohnDoe01", "anat", "T1w"): (rng.uniform(10, 100, (6, 8, 5)), np.diag([-1.5, -1.5, 1.5, 1.0])),
        ("JohnDoe01", "dwi", "dwi"): (rng.uniform(10, 100, (8, 6, 4, 3)), np.eye(4)),
        ("JaneRoe02", "anat", "T1w"): (rng.uniform(10, 100, (7, 7, 7)), np.eye(4)),
        ("JaneRoe02", "anat", "T2w"): (rng.uniform(10, 100, (7, 7, 7)), np.eye(4)),
        ("MaxMus03", "anat", "T1w"): (rng.uniform(10, 100, (10, 6, 4)), las),
        ("NanCase04", "anat", "T1w"): (nan_volume, np.eye(4)),
    }
    for (subject, folder, suffix), (volume, affine) in images.items():
        session = SUBJECTS[subject]
        name = f"sub-{subject}_ses-{session}_{suffix}.nii.gz"
        _save(root / f"sub-{subject}" / f"ses-{session}" / folder / name, volume, affine, sidecar)
    return root


def _config() -> dict:
    return load_config(REPO / "config" / "stage3_bids.yaml", config_dir=REPO / "config")


def _export(input_root: Path, dataset: Path) -> tuple[object, list[tuple[Path, Exception]]]:
    config = _config()
    errors: list[tuple[Path, Exception]] = []
    report = export_dataset(
        BIDSBatchReader().iter_studies(input_root, lazy=True),
        dataset,
        lambda path, error: errors.append((path, error)),
        pipeline=pipeline_from_config(config),
        config=config,
        source_dir=input_root,
    )
    return report, errors


def _label_and_split(dataset: Path, tmp_path: Path) -> None:
    write_label_template(dataset, CLASSES, "Diagnosis")
    pairs = dataset_pairs(dataset)
    corrections = tmp_path / "corrections.tsv"
    rows = ["participant_id\tsession_id\tlabel"]
    rows += [f"sub-{p}\tses-{s}\t{'control' if i == 0 else 'tumor'}" for i, (p, s) in enumerate(pairs)]
    corrections.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert apply_label_corrections(dataset, corrections) == len(pairs)
    assert review_labels(dataset).is_complete
    finalize_labels(dataset)
    write_ml_exports(dataset, seed=7)


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory: pytest.TempPathFactory):
    """The whole stage 4 flow once (module scope: it runs the stage 3 pipeline)."""
    tmp_path = tmp_path_factory.mktemp("e2")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MRI_ANON_KEY", KEY)
        input_root = _input(tmp_path)
        out = tmp_path / "out"
        dataset = out / "dataset"
        report, errors = _export(input_root, dataset)
        _label_and_split(dataset, tmp_path)
        report_paths = report_dataset(dataset, out / "report")
    return input_root, out, dataset, report, errors, report_paths


def test_invalid_study_is_reported_and_the_rest_is_exported(pipeline_run) -> None:
    _, _, dataset, report, errors, _ = pipeline_run

    assert [type(error).__name__ for _, error in errors] == ["ValueError"]
    assert (report.studies_written, report.series_written, report.participants, report.errors) == (3, 5, 3, 1)
    participants = (dataset / "participants.tsv").read_text(encoding="utf-8").splitlines()
    assert participants[0] == "participant_id" and len(participants) == 4
    assert sorted(p.relative_to(dataset).parts[2] for p in dataset.rglob("*.nii.gz")) == ["anat"] * 4 + ["dwi"]
    for image in dataset.rglob("*.nii.gz"):
        sidecar = json.loads(image.with_name(image.name.replace(".nii.gz", ".json")).read_text(encoding="utf-8"))
        assert sidecar == {"EchoTime": 0.03, "RepetitionTime": 2.0}  # input sidecars were read, then filtered
        assert nib.load(image).get_data_dtype() == np.float32


def test_dataset_reads_back_with_the_pipeline_geometry(pipeline_run) -> None:
    input_root, _, dataset, *_ = pipeline_run
    expected = {}
    pipeline = pipeline_from_config(_config())

    def keep(study, _report) -> None:
        for series in study.series:
            expected[(study.subject_id, study.session_id, series.modality)] = (
                tuple(series.metadata["shape"]),
                np.asarray(series.metadata["affine"]),
            )

    pipeline.run(BIDSBatchReader().iter_studies(input_root, lazy=True), keep)
    studies = BIDSBatchReader().load_studies(dataset, lazy=True)

    read_back = {(s.subject_id, s.session_id, series.modality): series for s in studies for series in s.series}
    assert set(read_back) == set(expected) and len(read_back) == 5
    for key, series in read_back.items():
        shape, affine = expected[key]
        assert tuple(series.metadata["shape"]) == shape
        np.testing.assert_allclose(series.metadata["affine"], affine, atol=1e-4)
        assert tuple(series.metadata["orientation"]) == ("R", "A", "S")
        spacing = 2.0 if key[2] == "dwi" else 1.0
        np.testing.assert_allclose(series.metadata["voxel_size"], [spacing] * 3, atol=1e-5)
    t1_shapes = sorted(tuple(s.metadata["shape"]) for k, s in read_back.items() if k[2] == "T1w")
    assert (9, 12, 8) in t1_shapes  # LPS 6x8x5 at 1.5 mm → RAS 1 mm, field of view kept (ceil)


def test_manifest_travels_without_paths_and_reproduces(pipeline_run) -> None:
    _, _, dataset, *_ = pipeline_run
    text = (dataset / "code" / "run_manifest.json").read_text(encoding="utf-8")
    manifest = RunManifest.from_json(text)

    assert all(report.source_path is None for report in manifest.reports)
    assert "report" not in manifest.config
    assert [s.name for s in pipeline_from_manifest(manifest).steps] == [s["name"] for s in _config()["pipeline"]["steps"]]
    # the NaN study fails at validate and records no further step
    assert sorted(report.steps[-1].status for report in manifest.reports) == ["failed", "ok", "ok", "ok"]
    assert sorted(len(report.steps) for report in manifest.reports) == [1, 6, 6, 6]
    description = json.loads((dataset / "dataset_description.json").read_text(encoding="utf-8"))
    assert "Anonymization policy" in description["GeneratedBy"][0]["Description"]


def test_labels_are_final_and_splits_have_no_leakage(pipeline_run) -> None:
    _, _, dataset, *_ = pipeline_run
    final = json.loads((dataset / "labels_final.json").read_text(encoding="utf-8"))
    assert final["label_count"] == 3 and final["class_counts"] == {"control": 1, "tumor": 2}

    splits = dict(row.split("\t") for row in (dataset / "splits.tsv").read_text(encoding="utf-8").splitlines()[1:])
    assert len(splits) == 3 and set(splits.values()) <= {"training", "validation", "testing"}
    with (dataset / "dataset_index.csv").open(encoding="utf-8", newline="") as handle:
        index = list(csv.DictReader(handle))
    assert len(index) == 5
    for row in index:
        assert row["split"] == splits[row["participant_id"]]  # every image of a participant in its split
        assert row["label"] in CLASSES and not Path(row["image"]).is_absolute()
        assert (dataset / row["image"]).is_file()
    datalist = json.loads((dataset / "datalist.json").read_text(encoding="utf-8"))
    images = [item["image"] for split in ("training", "validation", "testing") for item in datalist[split]]
    assert sorted(images) == sorted(row["image"] for row in index)
    assert datalist["unlabeled"] == [] and datalist["classes"] == sorted(CLASSES)
    assert json.loads((dataset / "splits.json").read_text(encoding="utf-8"))["seed"] == 7


def test_report_matches_the_dataset(pipeline_run) -> None:
    _, out, _, _, _, report_paths = pipeline_run
    assert sorted(p.name for p in report_paths) == [
        "dataset_report.json", "dataset_report.md", "dataset_report.xlsx", "dataset_report.xml",
    ]
    summary = json.loads((out / "report" / "dataset_report.json").read_text(encoding="utf-8"))
    assert (summary["participants"], summary["sessions"], summary["series"]) == (3, 3, 5)
    assert {name: c["sessions"] for name, c in summary["labels"]["classes"].items()} == {"control": 1, "tumor": 2}
    assert summary["labels"]["unlabeled_sessions"] == 0
    assert summary["pipeline"]["studies"] == 4
    assert set(summary["modalities"]) == {"T1w", "T2w", "dwi"}


def _contents(path: Path) -> bytes:
    data = path.read_bytes()
    if path.name.endswith(".nii.gz"):
        return gzip.decompress(data)[:352]  # the header; voxel bytes are not text
    if path.suffix == ".xlsx":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return b"".join(archive.read(name) for name in archive.namelist())
    return data


def test_no_phi_paths_or_user_name_anywhere_in_the_output(pipeline_run) -> None:
    input_root, out, *_ = pipeline_run
    forbidden = [*PLANTED, str(input_root), input_root.as_posix(), str(out), out.as_posix()]
    user = getpass.getuser()
    if len(user) >= 4:
        forbidden.append(user)
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len(files) > 20
    for path in out.rglob("*"):
        relative = path.relative_to(out).as_posix()
        assert not any(marker.lower() in relative.lower() for marker in PLANTED), relative
        if path.is_file():
            text = _contents(path).decode("utf-8", errors="replace").lower()
            leaked = [marker for marker in forbidden if marker.lower() in text or marker.replace("\\", "\\\\").lower() in text]
            assert not leaked, (relative, leaked)


def test_no_phi_in_debug_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    input_root = _input(tmp_path)
    dataset = tmp_path / "out" / "dataset"
    with caplog.at_level(logging.DEBUG):
        _export(input_root, dataset)
        _label_and_split(dataset, tmp_path)
        report_dataset(dataset, tmp_path / "out" / "report")
    text = caplog.text.lower()
    assert caplog.records
    for marker in [*PLANTED, str(tmp_path), tmp_path.as_posix()]:
        assert marker.lower() not in text, marker


def test_existing_output_is_not_overwritten(pipeline_run) -> None:
    input_root, out, dataset, *_ = pipeline_run
    before = sorted((p.relative_to(out).as_posix(), p.stat().st_size) for p in out.rglob("*") if p.is_file())

    with pytest.raises(FileExistsError):
        _export(input_root, dataset)
    with pytest.raises(FileExistsError):
        write_ml_exports(dataset, seed=7)
    with pytest.raises(FileExistsError):
        report_dataset(dataset, out / "report")

    assert sorted((p.relative_to(out).as_posix(), p.stat().st_size) for p in out.rglob("*") if p.is_file()) == before


# --- Launcher (scripts/run_stage4_dataset.py) ---------------------------------------------------

_spec = importlib.util.spec_from_file_location("run_stage4_dataset", REPO / "scripts" / "run_stage4_dataset.py")
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


def _corrections(tmp_path: Path) -> Path:
    """Labels written before the run: pseudonyms are deterministic for the same key."""
    key = load_key()
    rows = ["participant_id\tsession_id\tlabel"]
    for i, (subject, session) in enumerate(list(SUBJECTS.items())[:3]):
        sub, ses = pseudonymize_label(subject, "subject", key), pseudonymize_label(session, "session", key)
        rows.append(f"sub-{sub}\tses-{ses}\t{'CN' if i == 0 else 'AD'}")
    path = tmp_path / "corrections.tsv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _assert_clean_console(text: str, *paths: Path) -> None:
    lowered = text.lower()
    for marker in [*PLANTED, *(str(p) for p in paths), *(p.as_posix() for p in paths)]:
        assert marker.lower() not in lowered, marker
    assert "sub-" not in lowered and "ses-" not in lowered


def test_launcher_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog) -> None:
    input_root = _input(tmp_path)
    out = tmp_path / "run"
    argv = [str(input_root), "--output-dir", str(out), "--classes", "AD=Alzheimer", "CN=Control",
            "--corrections", str(_corrections(tmp_path)), "--ratios", "0.5", "0.25", "0.25", "--seed", "3"]

    with caplog.at_level(logging.DEBUG):
        assert launcher.main(argv) == 0

    console = capsys.readouterr()
    _assert_clean_console(console.out + console.err + caplog.text, tmp_path, input_root, out)
    assert "Errors by type: {'ValueError': 1}" in console.out
    dataset = out / "dataset"
    assert review_labels(dataset).is_complete and (dataset / "labels_final.json").is_file()  # complete → finalized
    assert json.loads((dataset / "splits.json").read_text(encoding="utf-8"))["seed"] == 3
    summary = json.loads((out / "report" / "dataset_report.json").read_text(encoding="utf-8"))
    assert (summary["participants"], summary["series"]) == (3, 5)
    assert {name: c["sessions"] for name, c in summary["labels"]["classes"].items()} == {"AD": 2, "CN": 1}
    assert len(BIDSBatchReader().load_studies(dataset, lazy=True)) == 3


def test_launcher_existing_output_dir_exits_1_without_changes(tmp_path: Path, capsys) -> None:
    out = tmp_path / "run"
    out.mkdir()
    (out / "keep.txt").write_text("x", encoding="utf-8")

    assert launcher.main([str(_input(tmp_path)), "--output-dir", str(out)]) == 1

    assert capsys.readouterr().out.strip() == "Output directory already exists; choose a new one."
    assert [p.name for p in out.iterdir()] == ["keep.txt"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--classes", "=AD"], "Invalid --classes."),
        (["--corrections", "x.tsv"], "--corrections needs --classes."),
        (["--classes", "AD", "--corrections", "missing.tsv"], "Corrections file not found."),
        (["--ratios", "0.5", "0.5", "0.5"], "Invalid --ratios."),
    ],
)
def test_launcher_invalid_arguments_exit_2_before_creating_anything(tmp_path: Path, capsys, extra, message) -> None:
    out = tmp_path / "run"
    assert launcher.main([str(_input(tmp_path)), "--output-dir", str(out), *extra]) == 2
    assert capsys.readouterr().out.strip() == message
    assert not out.exists()


def test_launcher_without_key_exits_2(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("MRI_ANON_KEY")
    out = tmp_path / "run"
    assert launcher.main([str(_input(tmp_path)), "--output-dir", str(out)]) == 2
    assert "nothing was run" in capsys.readouterr().out and not out.exists()


def test_launcher_output_inside_the_input_creates_nothing(tmp_path: Path, capsys) -> None:
    input_root = _input(tmp_path)
    before = sorted(p.relative_to(input_root).as_posix() for p in input_root.rglob("*"))

    assert launcher.main([str(input_root), "--output-dir", str(input_root / "derivatives" / "out")]) != 0

    assert sorted(p.relative_to(input_root).as_posix() for p in input_root.rglob("*")) == before
    _assert_clean_console(capsys.readouterr().out, tmp_path, input_root)
