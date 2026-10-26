"""QA6: adversarial audit of the DICOM/loose-NIfTI ingest (``dataset build --format dicom|nifti``).

Covers what the unit and E6 tests leave out: pydicom validation warnings that echo header values,
vendor series names (Siemens/GE/Philips) the suffix rules can get wrong, unusual ``PatientID`` values,
hostile ``--mapping`` tables, PHI in loose NIfTI names and header fields, voxel-level equivalence of the
three formats and peak memory of a larger DICOM batch. Known defects are ``xfail(strict=True)`` with the
finding id of ``docs/testing/qa_etapa6.md``. Planted values contain ``Planted`` (case-insensitive search).
"""

import gzip
import hashlib
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import unicodedata
import uuid
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from mri_dataset_tool.application.services.anonymize import anonymize_dicom_tree
from mri_dataset_tool.application.services.conversion import convert_dicom_to_nifti
from mri_dataset_tool.application.services.dataset_build import (
    InvalidBuildInput,
    build_dataset,
    check_build_args,
    load_build_pipeline,
)
from mri_dataset_tool.application.services.dataset_ingest import (
    NOT_4D_DWI,
    iter_ingested_studies,
    load_mapping,
    plan_ingest,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import pseudonymize_label
from mri_dataset_tool.infrastructure.dataset.suffix_rules import suffix_from_text
from mri_dataset_tool.infrastructure.dicom.batch_reader import DICOMBatchReader
from mri_dataset_tool.infrastructure.dicom.identity import read_dicom_identities
from mri_dataset_tool.infrastructure.dicom.reader import DICOMReader
from mri_dataset_tool.infrastructure.dicom.volume_builder import build_series_volume

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_qa6_synthetic", REPO / "tests" / "unit" / "test_anonymize_dicom_tree.py")
synthetic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synthetic)

KEY = "qa6-anonymization-key-0123456789abcdef"
KEY_BYTES = KEY.encode()
UID = "1.2.826.0.1.3680043.8.498.66"
HEADER = "path\tparticipant\tsession\tsuffix"
# Non-conformant UIDs (letters): pydicom's reading validation echoes them in its warnings.
BAD_STUDY_UID, BAD_SERIES_UID = "1.2.PlantedStudyUid.9", "1.2.PlantedSeriesUid.1"


@pytest.fixture
def base(tmp_path):
    """Work directory on E:/ when it exists (large outputs never on C:), else ``tmp_path``."""
    if os.path.isdir("E:/"):
        root = Path("E:/qa6_tmp") / uuid.uuid4().hex
        root.mkdir(parents=True)
        yield root
        shutil.rmtree(root, ignore_errors=True)
    else:
        yield tmp_path


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    return KEY_BYTES


def _series(root: Path, folder: str, study: str, series: str, **overrides) -> Path:
    synthetic.write_synthetic_series(root / folder, StudyInstanceUID=study, SeriesInstanceUID=series, **overrides)
    return root


def _mapping(path: Path, *rows: str, header: str = HEADER) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


# --- QA6-01: pydicom validation warnings echo UIDs --------------------------------------------------


def _bad_uid_tree(root: Path) -> Path:
    return _series(root, "s", BAD_STUDY_UID, BAD_SERIES_UID, SeriesDescription="T1 MPRAGE")


def _leaked(records, caplog) -> list[str]:
    texts = [str(w.message) for w in records] + [r.getMessage() for r in caplog.records]
    return [text for text in texts if "planted" in text.lower()]


READ_POINTS = {
    "DICOMReader": lambda root, out: DICOMReader().load_study(root / "s"),
    "DICOMBatchReader": lambda root, out: DICOMBatchReader().load_studies(root),
    "identity": lambda root, out: read_dicom_identities(root, KEY_BYTES),
    "plan_ingest": lambda root, out: plan_ingest("dicom", root, key=KEY_BYTES),
    "anonymize_dicom_tree": lambda root, out: anonymize_dicom_tree(root, out),
    "convert_dicom_to_nifti": lambda root, out: convert_dicom_to_nifti(root, out),
    "volume_builder": lambda root, out: build_series_volume(_quiet_series(root)),
}


def _quiet_series(root: Path):
    """The series as read with warnings silenced, so only the builder's own warnings are recorded."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logging.getLogger("pydicom").disabled = True
        try:
            return DICOMBatchReader().load_studies(root)[0].series[0]
        finally:
            logging.getLogger("pydicom").disabled = False


@pytest.mark.parametrize("point", READ_POINTS)
def test_non_conformant_uids_are_not_echoed_by_pydicom_warnings(point, base, key, caplog):
    """QA6-01 (fixed): no warning or log record quotes a non-conformant UID while reading."""
    root = _bad_uid_tree(base / "in")
    caplog.clear()  # writing the tree warns too; only the reads are under test
    caplog.set_level(logging.DEBUG)
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        READ_POINTS[point](root, base / "out")
    assert _leaked(records, caplog) == []


@pytest.mark.parametrize("command", ["build", "inspect"])
def test_non_conformant_uids_never_reach_the_console(command, base, key):
    root = _bad_uid_tree(base / "in")
    args = {
        "build": ["dataset", "build", str(root), "--format", "dicom", "--output-dir", str(base / "out"),
                  "--config", str(REPO / "config" / "stage3_bids.yaml")],
        "inspect": ["inspect", "--format", "dicom", str(root)],
    }[command]
    result = subprocess.run(
        [sys.executable, "-m", "mri_dataset_tool.presentation.cli", "--quiet", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO, env={**os.environ, "MRI_ANON_KEY": KEY},
    )
    assert result.returncode == 0, result.stdout
    assert "planted" not in (result.stdout + result.stderr).lower()


# --- QA6-02/03: vendor series names ------------------------------------------------------------------


@pytest.mark.parametrize("text", ["t2_spc_da-fl_sag_p2_iso", "t2_spc_da-fl_irprep_sag_p2_iso"])
def test_siemens_space_dark_fluid_is_not_t2w(text):
    assert suffix_from_text(text, exclude_sub=True)[0] != "T2w"


@pytest.mark.parametrize("text", ["T2_STAR_HEMO", "Ax T2 Star", "T2 STAR"])
def test_t2_star_in_two_words_is_not_t2w(text):
    assert suffix_from_text(text, exclude_sub=True)[0] != "T2w"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Correct today; guards against a regression when QA6-02/03 are fixed.
        ("t1_mprage_sag_p2_iso", "T1w"), ("Sag CUBE T2", "T2w"), ("Sag CUBE FLAIR", "FLAIR"), ("T2W_TSE", "T2w"),
        ("T1W_3D_TFE", "T1w"), ("3D_Brain_VIEW_FLAIR_SHC", "FLAIR"), ("Ax DTI 30 dir", "dwi"),
        ("t2_flair_tra", "FLAIR"), ("T2 FLAIR PROPELLER", "FLAIR"),
        # Derived, contrast and gradient-echo names must stay unmapped.
        ("t1_mprage_sag_p2_iso_MPR_Tra", None), ("ep2d_diff_mddw_20_p2_ColFA", None), ("T1W_3D_TFE+C", None),
        ("T1_3D_TFE_SENSE_PostGado", None), ("T2*W_FFE", None), ("Ax T2* GRE", None), ("t2_swi_tra_p2_Mag", None),
        ("gre_field_mapping", None), ("Ax SWAN", None), ("eADC", None), ("Survey_SHC", None), ("3-Plane Loc", None),
        # QA6-04 (decision of the human): derived, reformatted and STIR/relaxometry names are excluded.
        ("Sag T1 Reformatted", None), ("t1_mprage_sag_ND", None), ("T2 relaxometry", None), ("Cor T2 STIR", None),
        ("sub-01_space-MNI_desc-preproc_T1w", None),
        # QA6-02/03 fixed: never T2w, and the fixes do not swallow real names.
        ("t2_spc_da-fl_sag_p2_iso", None), ("T2_STAR_HEMO", "T2starw"), ("t2_space_sag_p2_iso", "T2w"),
        ("t2_tse_tra_2nd", "T2w"),
    ],
)
def test_vendor_names(text, expected):
    assert suffix_from_text(text, exclude_sub=True)[0] == expected


def test_ge_adc_named_as_diffusion_is_dropped_as_not_4d(base, key):
    """GE stores the ADC as 'Apparent Diffusion Coefficient (mm2/s)': the text gives dwi, the 3D volume saves it."""
    root = _series(base / "in", "adc", f"{UID}1", f"{UID}1.1", SeriesDescription="Apparent Diffusion Coefficient (mm2/s)")
    _series(root, "t1", f"{UID}1", f"{UID}1.2", SeriesDescription="Sag T1")
    plan = plan_ingest("dicom", root, key=key)
    studies = list(iter_ingested_studies(plan))
    assert [s.modality for s in studies[0].series] == ["T1w"]
    assert plan.skipped[NOT_4D_DWI] == 1


# --- PatientID ---------------------------------------------------------------------------------------


def test_unusual_patient_ids(base, key, caplog):
    """Padded/Unicode/long ids group studies; empty or blank ones give one participant per study;
    case is significant. No PatientID reaches the plan or the DEBUG logs."""
    ids = {
        "u1": "PlantedÄÜ-ñ", "u2": "PlantedÄÜ-ñ ", "l1": "Planted" + "L" * 120, "l2": "Planted" + "L" * 120,
        "e1": "", "e2": "   ", "c1": "plantedcase", "c2": "PLANTEDCASE",
    }
    root = base / "in"
    for index, (folder, patient) in enumerate(ids.items(), start=1):
        _series(root, folder, f"{UID}2{index}", f"{UID}2{index}.1", PatientID=patient, SeriesDescription="T1")
    caplog.set_level(logging.DEBUG)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # long LO values: pydicom warns with the length only
        plan = plan_ingest("dicom", root, key=key)
    subjects = {Path(study.series[0].files[0]).parent.name: subject for study, subject, *_ in plan.entries}
    assert subjects["u1"] == subjects["u2"] == pseudonymize_label("PlantedÄÜ-ñ", "subject", key)
    assert subjects["l1"] == subjects["l2"]
    assert subjects["e1"] != subjects["e2"]  # one participant per study
    assert subjects["c1"] != subjects["c2"]
    assert len(plan.entries) == 8
    assert "planted" not in repr([entry[1:] for entry in plan.entries]).lower()
    assert "planted" not in caplog.text.lower()


def test_one_file_without_patient_id_splits_the_patient(base, key):
    """Documented: a study with a file lacking PatientID becomes its own participant, even if the same
    patient's other study is consistent (the patient ends up as two participants)."""
    root = _series(base / "in", "a", f"{UID}31", f"{UID}31.1", PatientID="PlantedP1", SeriesDescription="T1")
    _series(root, "b", f"{UID}32", f"{UID}32.1", PatientID="PlantedP1", SeriesDescription="T1")
    _series(root, "b2", f"{UID}32", f"{UID}32.2", PatientID="", SeriesDescription="T2")
    plan = plan_ingest("dicom", root, key=key)
    assert len({subject for _, subject, *_ in plan.entries}) == 2
    assert plan.missing_patient_id == 1  # QA6-06: counted for the MISSING_PATIENT_ID warning


# --- --mapping ---------------------------------------------------------------------------------------


@pytest.fixture
def mapped_tree(base):
    root = _series(base / "in", "s/a", f"{UID}41", f"{UID}41.1", SeriesDescription="T1")
    return _series(root, "s/b", f"{UID}41", f"{UID}41.2", SeriesDescription="T2")


@pytest.mark.parametrize(
    ("rows", "header", "message"),
    [
        (["s\tP01\t\t\textra"], HEADER, "Invalid --mapping."),  # one column too many
        (["s\tP01\t\t"], "path \tparticipant\tsession\tsuffix", "Invalid --mapping."),
        (["s\tP01\t\t"], "Path\tparticipant\tsession\tsuffix", "Invalid --mapping."),
        (["s\tP01\t\t", "./s/\tP02\t\t"], HEADER, "Invalid --mapping."),  # duplicate after normalization
        (["s/a/../b\tP01\t\t"], HEADER, "Invalid --mapping."),
        (["s\tPÄ01\t\t"], HEADER, "Invalid --mapping."),  # non-ASCII id
        (["s\tP\uff101\t\t"], HEADER, "Invalid --mapping."),  # full-width digit
        (["s\tsub-P01\t\t"], HEADER, "Invalid --mapping."),
        (["s\t\t\tt1w"], HEADER, "Invalid --mapping."),  # suffix case
        (["s\t\t\tbold"], HEADER, "Invalid --mapping."),
        (["//server/share\tP01\t\t"], HEADER, "Invalid --mapping."),  # UNC
        (["C:/in/s\tP01\t\t"], HEADER, "Invalid --mapping."),
        (["S\tP01\t\t"], HEADER, "Mapping paths not found in the input: 1."),  # case
        (["s\tP01\t\t\tad"], HEADER + "\tlabel", "Mapping label is not one of --classes."),
    ],
)
def test_hostile_mapping_tables_are_rejected_with_fixed_text(mapped_tree, base, rows, header, message):
    with pytest.raises(InvalidBuildInput) as raised:
        load_mapping(_mapping(base / "m.tsv", *rows, header=header), mapped_tree, {"AD": ""})
    assert str(raised.value) == message


def test_mapping_tolerates_crlf_bom_and_padded_cells(mapped_tree, base, key):
    table = base / "m.tsv"
    table.write_bytes(("\ufeff" + HEADER + "\r\n" + " s \t P01 \t\t\r\n").encode("utf-8"))
    plan = plan_ingest("dicom", mapped_tree, key=key, mapping=load_mapping(table, mapped_tree))
    assert [entry[1] for entry in plan.entries] == ["P01"]


def test_mapping_in_another_unicode_normalization_is_not_found(base):
    """Folder written in NFD, row in NFC (macOS / copy-paste): fixed text, nothing guessed."""
    folder = unicodedata.normalize("NFD", "PlantedPacienté")
    root = _series(base / "in", f"{folder}/a", f"{UID}51", f"{UID}51.1", SeriesDescription="T1")
    table = _mapping(base / "m.tsv", unicodedata.normalize("NFC", "PlantedPacienté") + "\tP01\t\t")
    with pytest.raises(InvalidBuildInput, match=r"^Mapping paths not found in the input: 1\.$"):
        load_mapping(table, root)


def test_consistent_per_series_participant_is_rejected(mapped_tree, base, key):
    """QA6-05 (minor, documented rule): the same participant on every series folder, but on no row that
    holds the whole study, is rejected with a message that speaks of 'more than one participant'."""
    rows = load_mapping(_mapping(base / "m.tsv", "s/a\tP01\t\t", "s/b\tP01\t\t"), mapped_tree)
    with pytest.raises(InvalidBuildInput, match="more than one participant"):
        plan_ingest("dicom", mapped_tree, key=key, mapping=rows)


# --- PHI in loose NIfTI -------------------------------------------------------------------------------


def _nifti(path: Path, value: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = nib.Nifti1Image(np.full((6, 5, 4), value, np.float32) + np.arange(4, dtype=np.float32), np.diag([1.0, 1.1, 1.2, 1]))
    image.header["descrip"] = b"PlantedDescrip"
    image.header["aux_file"] = b"PlantedAux"
    image.header["intent_name"] = b"PlantedInt"
    image.header.extensions.append(nib.nifti1.Nifti1Extension(6, b"PlantedExtension Doe^John"))
    nib.save(image, path)
    return path


def test_loose_nifti_names_and_header_text_never_reach_the_dataset(base, key, caplog):
    root = base / "in"
    _nifti(root / "PlantedDoe John" / "PlantedDoe_John_T1.nii.gz")
    _nifti(root / "PlantedSmith" / "PlantedSmith_flair.nii", 2.0)
    config, pipeline = load_build_pipeline(REPO / "config" / "stage3_bids.yaml", REPO / "config")
    plan = plan_ingest("nifti", root, key=key)
    caplog.set_level(logging.DEBUG)
    out = base / "out"
    build_dataset(root, out, pipeline, config, classes={"AD": ""}, allow_unfinalized=True, ingest=plan)
    leaks = []
    for path in out.rglob("*"):
        text = path.relative_to(out).as_posix().encode()
        if path.is_file():
            data = path.read_bytes()
            text += gzip.decompress(data) if path.name.endswith(".gz") else data
        if b"planted" in text.lower() or str(root).encode() in text:
            leaks.append(path.relative_to(out).as_posix())
    assert leaks == []
    assert "planted" not in caplog.text.lower()


# --- equivalence of the three formats ----------------------------------------------------------------


def _voxels(dataset: Path) -> list:
    """Order-free content: per image its suffix, shape, affine and a hash of its voxels (ids left out)."""
    entries = []
    for path in sorted(dataset.rglob("*.nii.gz")):
        image = nib.load(path)
        data = np.asarray(image.dataobj, dtype=np.float32)
        entries.append((path.name.split("_")[-1], image.shape, np.round(image.affine, 4).tolist(),
                        hashlib.sha256(np.round(data, 4).tobytes()).hexdigest()))
    return sorted(entries)


def _report_numbers(out: Path) -> dict:
    report = json.loads((out / "report" / "dataset_report.json").read_text(encoding="utf-8"))
    return {k: report.get(k) for k in ("studies", "participants", "sessions", "series", "modalities")}


def test_dicom_nifti_and_bids_give_the_same_voxels_affines_and_report(base, key):
    """E6 compares shapes and voxel sizes; here the voxels, the affines and the report numbers."""
    dicom = base / "dicom"
    series = [("a", f"{UID}61", "T1 MPRAGE", "T1w", "PlantedA"), ("b", f"{UID}62", "t2_flair_tra", "FLAIR", "PlantedB")]
    for folder, study, description, _, patient in series:
        synthetic.write_synthetic_series(dicom / folder, n_slices=4, StudyInstanceUID=study, SeriesInstanceUID=f"{study}.1",
                                         SeriesDescription=description, PatientID=patient)
    nifti, bids = base / "nifti", base / "bids"
    for (folder, _, _, suffix, _), study in zip(series, DICOMBatchReader().load_studies(dicom)):
        built = build_series_volume(study.series[0])
        image = nib.Nifti1Image(np.asarray(built.volume, np.float32), built.metadata["affine"])
        nifti.mkdir(exist_ok=True)
        nib.save(image, nifti / f"{folder}_{suffix}.nii.gz")
        (bids / f"sub-{folder}" / "ses-1" / "anat").mkdir(parents=True)
        nib.save(image, bids / f"sub-{folder}" / "ses-1" / "anat" / f"sub-{folder}_ses-1_{suffix}.nii.gz")
    nifti_map = _mapping(base / "nifti.tsv", "a_T1w.nii.gz\ta\t1\t", "b_FLAIR.nii.gz\tb\t1\t")
    config_path = REPO / "config" / "stage3_bids.yaml"
    config, pipeline = load_build_pipeline(config_path, REPO / "config")
    results = {}
    for name, root, fmt, table in [("dicom", dicom, "dicom", None), ("nifti", nifti, "nifti", nifti_map), ("bids", bids, "bids", None)]:
        out = base / f"out_{name}"
        check_build_args(root, out, config_path)
        plan = None if fmt == "bids" else plan_ingest(fmt, root, key=key, mapping=table and load_mapping(table, root))
        build_dataset(root, out, pipeline, config, ingest=plan)
        results[name] = (_voxels(out / "dataset"), _report_numbers(out))
    assert len(results["dicom"][0]) == 2
    assert results["nifti"] == results["dicom"]
    assert results["bids"] == results["dicom"]


# --- RNF02: a larger DICOM batch ---------------------------------------------------------------------

ROWS, COLS, SLICES = 160, 160, 48
_PEAK = (
    "import sys, warnings, psutil\n"
    "warnings.simplefilter('ignore')\n"
    "from mri_dataset_tool.presentation.cli.main import main\n"
    "code = main(sys.argv[1:])\n"
    "info = psutil.Process().memory_info()\n"
    "if hasattr(info, 'peak_wset'):\n"
    "    peak = info.peak_wset\n"
    "else:\n"
    "    import resource; peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024\n"
    "print('PEAK', peak, 'CODE', code)\n"
)


def _large_series(directory: Path, study: str, patient: str) -> None:
    directory.mkdir(parents=True)
    rng = np.random.default_rng(len(study))
    for index in range(SLICES):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = pydicom.uid.MRImageStorage
        meta.MediaStorageSOPInstanceUID = f"{study}.1.{index + 1}"
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(directory / f"{index:03d}.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study, f"{study}.1"
        ds.Modality, ds.PatientID, ds.SeriesDescription = "MR", patient, "T1 MPRAGE"
        ds.Rows, ds.Columns, ds.PixelSpacing, ds.SliceThickness = ROWS, COLS, [1.0, 1.0], 1.0
        ds.ImageOrientationPatient, ds.ImagePositionPatient = [1, 0, 0, 0, 1, 0], [0.0, 0.0, float(index)]
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit, ds.PixelRepresentation = 15, 0
        ds.PixelData = rng.integers(100, 1000, (ROWS, COLS), dtype=np.uint16).tobytes()
        ds.save_as(directory / f"{index:03d}.dcm", enforce_file_format=True)


def _dicom_peak(base: Path, count: int, config: Path) -> int:
    root = base / f"in{count}"
    for i in range(count):
        _large_series(root / f"p{i:02d}", f"{UID}7{count:02d}{i:02d}", f"QAP{i:02d}")
    result = subprocess.run(
        [sys.executable, "-c", _PEAK, "--quiet", "dataset", "build", str(root), "--format", "dicom",
         "--output-dir", str(base / f"out{count}"), "--config", str(config)],
        capture_output=True, text=True, cwd=REPO, env={**os.environ, "MRI_ANON_KEY": KEY},
    )
    line = [l for l in result.stdout.splitlines() if l.startswith("PEAK")]
    assert line and line[0].endswith("CODE 0"), result.stdout + result.stderr
    assert len(list((base / f"out{count}" / "dataset").rglob("*.nii.gz"))) == count
    return int(line[0].split()[1])


def test_dicom_ingest_peak_memory_does_not_grow_with_the_batch(base):
    config = base / "steps.yaml"
    config.write_text("pipeline:\n  steps:\n    - name: validate\n    - name: anonymize\n", "utf-8")
    small, large = _dicom_peak(base, 4, config), _dicom_peak(base, 16, config)
    one_volume = ROWS * COLS * SLICES * 8  # the float64 build
    assert large - small < one_volume * 2, (small // 2**20, large // 2**20)
