"""Integration: DICOM, loose NIfTI and BIDS inputs through ``dataset build`` reach the same dataset.

A synthetic DICOM tree (three patients, four studies, planted PHI in PatientID, PatientName,
SeriesDescription, ProtocolName, StudyDescription and folder names; a localizer and an ADC map that must
be skipped) → ``dataset build --format dicom --mapping`` with labels → ``labels review`` → ``labels apply`` →
``labels finalize`` → ``dataset export-ml`` → ``dataset report``. The same volumes as loose NIfTI (with and
without a mapping) and as BIDS give a structurally equal dataset. PHI sweep over console, DEBUG logs,
output tree, manifest, labels and XML report; invalid mappings exit 2 creating nothing; executables.
"""

import importlib.util
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.anonymization.pseudonym import pseudonymize_label
from mri_dataset_tool.infrastructure.dicom.batch_reader import DICOMBatchReader
from mri_dataset_tool.infrastructure.dicom.volume_builder import build_series_volume
from test_stage4_dataset_integration import _contents
from test_stage5_cli_integration import _executables, _Transcript, _tree

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_synthetic_dicom", REPO / "tests" / "unit" / "test_anonymize_dicom_tree.py")
synthetic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synthetic)
CONFIG = REPO / "config" / "stage3_bids.yaml"
KEY = "e6-integration-key-0123456789abcdefghij"
CLASSES = ["AD=Alzheimer", "CN=Control"]
UID = "1.2.826.0.1.3680043.8.498.6"
INPUT_MARKER = "InputMarkerE6"

# patient folder -> (PatientID, PatientName, StudyDescription); Gamma has no PatientID (one participant per study)
PATIENTS = {
    "PlantedFolderAlpha": ("PAT-ALPHA-01", "Planted^Alice", "PlantedStudyAlpha"),
    "PlantedFolderBeta": ("PAT-BETA-02", "Planted^Bob", "PlantedStudyBeta"),
    "PlantedFolderGamma": ("", "Planted^Carol", "PlantedStudyGamma"),
}
# (patient, visit, series folder, SeriesDescription, frames, BIDS suffix or None when it must be skipped)
SERIES = [
    ("PlantedFolderAlpha", "visit1", "t1", "t1_mprage_sag PlantedSeriesTok", 1, "T1w"),
    ("PlantedFolderAlpha", "visit1", "t2", "t2_tse_tra", 1, "T2w"),
    ("PlantedFolderAlpha", "visit1", "scout", "AAHead_Scout", 1, None),
    ("PlantedFolderAlpha", "visit2", "flair", "t2_flair_tra", 1, "FLAIR"),
    ("PlantedFolderAlpha", "visit2", "dwi", "ep2d_diff_mddw_20", 3, "dwi"),
    ("PlantedFolderAlpha", "visit2", "adc", "ep2d_diff_ADC", 1, None),
    ("PlantedFolderBeta", "visit1", "t1", "T1 MPRAGE", 1, "T1w"),
    ("PlantedFolderBeta", "visit1", "t2", "Ax T2 TSE", 1, "T2w"),
    ("PlantedFolderGamma", "visit1", "t1", "Sag T1 SE", 1, "T1w"),
]
# session label per (patient, visit) and class; Beta is left unlabeled by the DICOM mapping
LABELS = {("PlantedFolderAlpha", "visit1"): "AD", ("PlantedFolderAlpha", "visit2"): "AD",
          ("PlantedFolderBeta", "visit1"): "CN", ("PlantedFolderGamma", "visit1"): "CN"}
BIDS_IDS = {"PlantedFolderAlpha": "PlantedBidsA", "PlantedFolderBeta": "PlantedBidsB", "PlantedFolderGamma": "PlantedBidsC"}
VISITS = {"visit1": "PlantedVisitOne", "visit2": "PlantedVisitTwo"}
SECRETS = [
    *synthetic.PLANTED, INPUT_MARKER, *PATIENTS, *[v for values in PATIENTS.values() for v in values if v],
    "PlantedSeriesTok", "PlantedProtoTok", "t1_mprage_sag", "AAHead_Scout", "ep2d_diff", "PlantedLoose",
    *BIDS_IDS.values(), *VISITS.values(), "PlantedMapPart", KEY,
]


def _study_uid(patient: str, visit: str) -> str:
    return f"{UID}{list(PATIENTS).index(patient) + 1}{visit[-1]}"


def _dicom_input(root: Path) -> Path:
    for index, (patient, visit, folder, description, frames, _) in enumerate(SERIES, start=1):
        patient_id, name, study_description = PATIENTS[patient]
        study = _study_uid(patient, visit)
        for frame in range(frames):
            directory = root / patient / visit / folder
            synthetic.write_synthetic_series(
                directory / f"v{frame}" if frames > 1 else directory,
                PatientID=patient_id, PatientName=name, StudyDescription=study_description,
                SeriesDescription=description, ProtocolName=f"PlantedProtoTok{index}",
                StudyInstanceUID=study, SeriesInstanceUID=f"{study}.{index}", FrameOfReferenceUID=f"{study}.9",
                **({"TemporalPositionIdentifier": frame + 1} if frames > 1 else {}),
            )
    return root


def _volumes(dicom: Path) -> dict[tuple[str, str, str], nib.Nifti1Image]:
    """The same volumes as NIfTI images, built from each DICOM series folder."""
    images = {}
    for patient, visit, folder, *_ in SERIES:
        series = DICOMBatchReader().load_studies(dicom / patient / visit / folder)[0].series[0]
        built = build_series_volume(series)
        images[patient, visit, folder] = nib.Nifti1Image(np.asarray(built.volume, np.float32), built.metadata["affine"])
    return images


def _tsv(path: Path, *rows: str, header: str = "path\tparticipant\tsession\tsuffix\tlabel") -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _loose_inputs(root: Path, images) -> tuple[Path, Path, Path]:
    """Neutral names + a mapping for every file (the localizer and ADC rows only give no suffix), and
    names with suffix words and PHI without a mapping."""
    mapped, rows = root / "mapped", []
    for index, (patient, visit, folder, _, _, suffix) in enumerate(SERIES, start=1):
        name = f"vol{index:02d}.nii.gz"
        mapped.mkdir(parents=True, exist_ok=True)
        nib.save(images[patient, visit, folder], mapped / name)
        if suffix:
            label = LABELS[patient, visit]
            rows.append(f"{name}\tPlantedMapPart{patient.removeprefix('PlantedFolder')}\t{VISITS[visit]}\t{suffix}\t{label}")
    mapping = _tsv(root / "nifti_map.tsv", *rows)
    unmapped = root / "unmapped"
    unmapped.mkdir()
    for name, key in [("PlantedLoose_Alice_t1_mprage", "t1"), ("PlantedLoose_Alice_t2_tse", "t2"),
                      ("PlantedLoose_Alice_AAHead_Scout", "scout")]:
        nib.save(images["PlantedFolderAlpha", "visit1", key], unmapped / f"{name}.nii.gz")
    return mapped, mapping, unmapped


def _bids_input(root: Path, images) -> Path:
    for patient, visit, folder, _, _, suffix in SERIES:
        if suffix:
            sub, ses = BIDS_IDS[patient], VISITS[visit]
            datatype = "dwi" if suffix == "dwi" else "anat"
            path = root / f"sub-{sub}" / f"ses-{ses}" / datatype / f"sub-{sub}_ses-{ses}_{suffix}.nii.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            nib.save(images[patient, visit, folder], path)
    return root


def _bids_corrections(path: Path) -> Path:
    key = KEY.encode()
    rows = [
        f"sub-{pseudonymize_label(BIDS_IDS[patient], 'subject', key)}\t"
        f"ses-{pseudonymize_label(VISITS[visit], 'session', key)}\t{label}"
        for (patient, visit), label in LABELS.items()
    ]
    return _tsv(path, *rows, header="participant_id\tsession_id\tlabel")


def _fill_unlabeled(dataset: Path, path: Path, label: str) -> Path:
    """Corrections from the dataset's own labels.tsv (only pseudonyms): every empty label → *label*."""
    lines = (dataset / "labels.tsv").read_text(encoding="utf-8").splitlines()
    rows = [line.rsplit("\t", 1)[0] + f"\t{label}" for line in lines[1:] if line.endswith("\t")]
    return _tsv(path, *rows, header=lines[0])


def _structure(dataset: Path) -> list:
    """Order-free shape of a dataset: per participant, per session, its label and its images
    (datatype, suffix, shape, voxel size); the ids themselves are left out."""
    lines = (dataset / "labels.tsv").read_text(encoding="utf-8").splitlines()[1:]
    labels = {(sub, ses): label for sub, ses, label in (line.split("\t") for line in lines)}
    sessions: dict[tuple[str, str], list] = {}
    for path in dataset.rglob("*.nii.gz"):
        sub, ses, datatype = path.relative_to(dataset).parts[:3]
        image = nib.load(path)
        entry = (datatype, path.name.split("_")[-1], image.shape, tuple(round(float(z), 3) for z in image.header.get_zooms()))
        sessions.setdefault((sub, ses), []).append(entry)
    participants: dict[str, list] = {}
    for (sub, ses), entries in sessions.items():
        participants.setdefault(sub, []).append((labels[sub, ses], sorted(entries)))
    return sorted(sorted(sessions_of) for sessions_of in participants.values())


@pytest.fixture(scope="module")
def flow(tmp_path_factory: pytest.TempPathFactory):
    """Every build and label step once (module scope: each build runs the pipeline)."""
    tmp = tmp_path_factory.mktemp("e6")
    cli = _Transcript()
    codes, outputs = {}, {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MRI_ANON_KEY", KEY)
        patch.chdir(REPO)  # config/default.yaml is read from the current directory
        dicom = _dicom_input(tmp / INPUT_MARKER / "dicom")
        images = _volumes(dicom)
        mapped, nifti_map, unmapped = _loose_inputs(tmp / INPUT_MARKER / "nifti", images)
        bids = _bids_input(tmp / INPUT_MARKER / "bids", images)
        dicom_map = _tsv(
            tmp / "dicom_map.tsv",
            *[f"PlantedFolderAlpha/{visit}\t\t\t\tAD" for visit in ("visit1", "visit2")],
            "PlantedFolderGamma\t\t\t\tCN",
        )
        inputs_before = _tree(tmp / INPUT_MARKER)
        out = tmp / "out"
        dataset = out / "dicom" / "dataset"
        steps = [
            ("build_dicom", ["dataset", "build", dicom, "--format", "dicom", "--mapping", dicom_map,
                             "--output-dir", out / "dicom", "--config", CONFIG, "--classes", *CLASSES]),
            ("review_incomplete", ["labels", "review", dataset, "--json"]),
            ("apply", ["labels", "apply", dataset, "--corrections", "{fill}"]),
            ("review_complete", ["labels", "review", dataset, "--json"]),
            ("finalize", ["labels", "finalize", dataset]),
            ("export_ml", ["dataset", "export-ml", dataset]),
            ("report", ["dataset", "report", dataset, out / "dicom" / "report_final"]),
            ("build_nifti_mapped", ["dataset", "build", mapped, "--format", "nifti", "--mapping", nifti_map,
                                    "--output-dir", out / "nifti_mapped", "--config", CONFIG, "--classes", *CLASSES]),
            ("build_nifti_unmapped", ["dataset", "build", unmapped, "--format", "nifti",
                                      "--output-dir", out / "nifti_unmapped", "--config", CONFIG]),
            ("build_bids", ["dataset", "build", bids, "--output-dir", out / "bids", "--config", CONFIG,
                            "--classes", *CLASSES, "--corrections", _bids_corrections(tmp / "bids_fix.tsv")]),
        ]
        for name, argv in steps:
            if "{fill}" in argv:
                argv = [_fill_unlabeled(dataset, tmp / "fill.tsv", "CN") if a == "{fill}" else a for a in argv]
            codes[name], outputs[name] = cli(*argv)
        inputs_after = _tree(tmp / INPUT_MARKER)
    return {"tmp": tmp, "out": out, "cli": cli, "codes": codes, "outputs": outputs, "dicom": dicom,
            "dicom_map": dicom_map, "inputs": (inputs_before, inputs_after)}


def test_input_carries_the_planted_values(flow) -> None:
    files = sorted(p for p in flow["dicom"].rglob("*") if p.is_file())
    text = b"".join(p.read_bytes() for p in files).decode("latin-1")
    for value in ["PAT-ALPHA-01", "Planted^Alice", "PlantedStudyAlpha", "PlantedSeriesTok", "PlantedProtoTok1"]:
        assert value in text, value


def test_exit_codes_and_inputs_untouched(flow) -> None:
    assert flow["codes"] == {
        "build_dicom": 0, "review_incomplete": 0, "apply": 0, "review_complete": 0, "finalize": 0,
        "export_ml": 0, "report": 0, "build_nifti_mapped": 0, "build_nifti_unmapped": 0, "build_bids": 0,
    }
    assert flow["inputs"][0] == flow["inputs"][1]


def test_dicom_build_ids_suffixes_and_mapping_labels(flow) -> None:
    out = flow["outputs"]["build_dicom"]
    assert "Studies written: 4  series: 7  participants: 3  errors: 0" in out
    assert "WARNING UNMAPPED_SERIES: {'EXCLUDED': 2}" in out  # the localizer and the ADC map
    assert "Mapping labels applied: 3" in out
    assert "WARNING LABELS_INCOMPLETE: {'UNLABELED': 1}" in out and "ML exports: skipped" in out
    dataset = flow["out"] / "dicom" / "dataset"
    key = KEY.encode()
    alpha = dataset / f"sub-{pseudonymize_label('PAT-ALPHA-01', 'subject', key)}"
    assert len(list(alpha.glob("ses-*"))) == 2  # one PatientID, two studies = two sessions
    gamma = pseudonymize_label(_study_uid("PlantedFolderGamma", "visit1"), "subject", key)
    assert (dataset / f"sub-{gamma}").is_dir()  # without PatientID: the study is the participant
    names = sorted(p.name.split("_")[-1] for p in dataset.rglob("*.nii.gz"))
    assert names == ["FLAIR.nii.gz", "T1w.nii.gz", "T1w.nii.gz", "T1w.nii.gz", "T2w.nii.gz", "T2w.nii.gz", "dwi.nii.gz"]
    (dwi,) = dataset.rglob("*_dwi.nii.gz")
    assert len(nib.load(dwi).shape) == 4 and nib.load(dwi).get_data_dtype() == np.float32


def test_dicom_labels_step_by_step_and_xml_report(flow) -> None:
    outputs = flow["outputs"]
    assert json.loads(outputs["review_incomplete"]) == {
        "class_counts": {"AD": 2, "CN": 1}, "complete": False, "dataset_pairs": 4, "defects": {"UNLABELED": 1},
        "labeled": 3,
    }
    assert json.loads(outputs["review_complete"])["class_counts"] == {"AD": 2, "CN": 2}
    assert "ML export files written: 4" in outputs["export_ml"] and "Report files written: 4" in outputs["report"]
    dataset = flow["out"] / "dicom" / "dataset"
    assert (dataset / "labels_final.json").is_file() and (dataset / "splits.json").is_file()
    changes = (dataset / "labels_changes.tsv").read_text(encoding="utf-8")
    assert changes.count("\tcorrect\t") == 4 and changes.count("\tfinalize\t") == 1  # mapping 3 + apply 1
    xml = ET.parse(flow["out"] / "dicom" / "report_final" / "dataset_report.xml").getroot()
    report = json.loads((flow["out"] / "dicom" / "report_final" / "dataset_report.json").read_text(encoding="utf-8"))
    assert (report["participants"], report["sessions"], report["series"]) == (3, 4, 7)
    assert (xml.findtext("participants"), xml.findtext("sessions"), xml.findtext("series")) == ("3", "4", "7")
    classes = {c.get("name"): c.findtext("sessions") for c in xml.iter("class")}
    assert classes == {"AD": "2", "CN": "2"} and xml.findtext("labels/unlabeled_sessions") == "0"


def test_nifti_inputs(flow) -> None:
    mapped = flow["outputs"]["build_nifti_mapped"]
    assert "Studies written: 4  series: 7  participants: 3  errors: 0" in mapped
    assert "WARNING UNMAPPED_SERIES: {'NO_MATCH': 2}" in mapped  # neutral names without a mapped suffix
    assert "Mapping labels applied: 4" in mapped and "Labels finalized (4 labels)." in mapped
    unmapped = flow["outputs"]["build_nifti_unmapped"]
    assert "Studies written: 2  series: 2  participants: 2  errors: 0" in unmapped  # one participant per file
    assert "WARNING UNMAPPED_SERIES: {'EXCLUDED': 1}" in unmapped
    assert not list((flow["out"] / "nifti_unmapped" / "dataset").glob("sub-*/ses-*"))  # no sessions without a mapping


def test_the_three_formats_give_the_same_dataset(flow) -> None:
    out = flow["out"]
    assert "Labels finalized (4 labels)." in flow["outputs"]["build_bids"]
    dicom = _structure(out / "dicom" / "dataset")
    assert len(dicom) == 3 and sum(len(sessions) for sessions in dicom) == 4
    assert _structure(out / "nifti_mapped" / "dataset") == dicom
    assert _structure(out / "bids" / "dataset") == dicom
    for name in ("dicom", "nifti_mapped", "bids"):
        report = json.loads((out / name / "report" / "dataset_report.json").read_text(encoding="utf-8"))
        assert (report["studies"], report["participants"], report["sessions"], report["series"]) == (4, 3, 4, 7), name


def test_no_phi_in_console_or_debug_logs(flow) -> None:
    cli = flow["cli"]
    assert cli.logs.getvalue()  # --verbose: the services' logs were captured
    text = cli.text.lower()
    for marker in [*SECRETS, str(flow["tmp"]), flow["tmp"].as_posix()]:
        assert marker.lower() not in text, marker
    assert "sub-" not in text and "ses-" not in text


def test_no_phi_anywhere_in_the_output_tree(flow) -> None:
    out, tmp = flow["out"], flow["tmp"]
    forbidden = [*SECRETS, str(tmp), tmp.as_posix()]
    files = [p for p in out.rglob("*") if p.is_file()]
    assert not list(out.rglob(".mapping_labels.tsv"))
    for required in ("dataset/code/run_manifest.json", "dataset/labels.tsv", "dataset/labels_changes.tsv",
                     "report_final/dataset_report.xml", "report_final/dataset_report.xlsx"):
        assert out / "dicom" / required in files, required
    for path in out.rglob("*"):
        relative = path.relative_to(out).as_posix()
        assert not any(marker.lower() in relative.lower() for marker in SECRETS), relative
        if path.is_file():
            content = _contents(path).decode("utf-8", errors="replace").lower()
            leaked = [m for m in forbidden if m.lower() in content or m.replace("\\", "\\\\").lower() in content]
            assert not leaked, (relative, leaked)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (["../outside\t\t\t\t"], "Invalid --mapping."),
        (["{abs}\t\t\t\t"], "Invalid --mapping."),
        (["PlantedFolderAlpha\\visit1\t\t\t\t"], "Invalid --mapping."),
        (["PlantedFolderAlpha\t\t\tT3w\t"], "Invalid --mapping."),
        (["PlantedFolderMissing\t\t\t\t"], "Mapping paths not found in the input: 1."),
        (["PlantedFolderAlpha\t\t\t\tXX"], "Mapping label is not one of --classes."),
        (["PlantedFolderAlpha/visit1/t1\t\t\t\tAD", "PlantedFolderAlpha/visit1/t2\t\t\t\tCN"],
         "Mapping assigns different labels to the same participant/session."),
        ([".\tPlantedMapPartX\tPlantedVisitOne\t\t"], "Mapping gives the same participant/session to more than one study."),
    ],
)
def test_invalid_mapping_exits_two_and_creates_nothing(flow, tmp_path, monkeypatch, rows, message) -> None:
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    monkeypatch.chdir(REPO)
    mapping = _tsv(tmp_path / "map.tsv", *[row.format(abs=flow["dicom"].as_posix()) for row in rows])
    before, inputs = _tree(tmp_path), _tree(flow["dicom"])
    cli = _Transcript()
    code, out = cli("dataset", "build", flow["dicom"], "--format", "dicom", "--mapping", mapping,
                    "--output-dir", tmp_path / "out", "--config", CONFIG, "--classes", *CLASSES)
    assert (code, out.strip().splitlines()[-1]) == (2, message)
    assert _tree(tmp_path) == before and _tree(flow["dicom"]) == inputs
    assert not [m for m in [*SECRETS, str(flow["tmp"]), str(tmp_path)] if m.lower() in cli.text.lower()]


@pytest.mark.parametrize("command", _executables(), ids=["python-m", "mri-dataset"])
def test_installed_entry_points(command, flow, tmp_path) -> None:
    if not command:
        pytest.skip("mri-dataset is not installed (pip install -e .)")
    env = {**os.environ, "MRI_ANON_KEY": KEY}
    run = lambda *argv: subprocess.run([*command, *map(str, argv)], capture_output=True, text=True, cwd=REPO, env=env)

    help_text = run("dataset", "build", "--help").stdout
    assert "--format" in help_text and "--mapping" in help_text
    review = run("labels", "review", flow["out"] / "dicom" / "dataset", "--json")
    assert review.returncode == 0 and json.loads(review.stdout)["complete"] is True
    bad = _tsv(tmp_path / "bad.tsv", "../outside\t\t\t\t")
    invalid = run("dataset", "build", flow["dicom"], "--format", "dicom", "--mapping", bad,
                  "--output-dir", tmp_path / "o", "--config", CONFIG, "--classes", *CLASSES)
    assert invalid.returncode == 2 and not (tmp_path / "o").exists()
    for result in (review, invalid):
        text = (result.stdout + result.stderr).lower()
        assert not [m for m in [*SECRETS, str(flow["tmp"]), str(tmp_path)] if m.lower() in text]
