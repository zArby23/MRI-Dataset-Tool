"""QA1 (2): hostile and edge-case inputs through the readers and the full stage 3 pipeline.

Each case states where it must fail (fixed-message ``ValueError`` in a given step) or that it
passes; the batch must always go on. Tests of the findings of
docs/testing/qa_etapa3.md name their id (QA1-NN).
"""

import struct
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.services.anonymize import anonymize_dicom_tree
from mri_dataset_tool.application.services.conversion import convert_dicom_to_nifti, convert_nifti_to_dicom
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader
from mri_dataset_tool.infrastructure.nifti.writer import NIfTIWriter

KEY = "qa-anonymization-key-0123456789abcdef"
STEPS = ["validate", "anonymize", "reorient", "resample", "normalize"]
CONFIG = {
    "pipeline": {
        "steps": [{"name": name, "params": {"spacing": [2, 2, 2]} if name == "resample" else {}} for name in STEPS]
    }
}
BASE = np.random.default_rng(0).random((6, 5, 4)).astype(np.float32) + 1


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV_VAR, KEY)


def _oblique() -> np.ndarray:
    affine = np.eye(4)
    affine[:3, :3] = nib.eulerangles.euler2mat(0.3, 0.2, 0.1) @ np.diag([1.0, 2.0, 3.0])
    affine[:3, 3] = [5, 6, 7]
    return affine


def _save(path: Path, data: np.ndarray, affine: np.ndarray = np.eye(4)) -> Path:
    nib.save(nib.Nifti1Image(data, affine, dtype=data.dtype), path)
    return path


def _run(path: Path, lazy: bool) -> tuple[list, list, list]:
    study = NIfTIReader().load_study(path, lazy=lazy)
    results, errors = [], []
    reports = pipeline_from_config(CONFIG).run(
        [study], lambda s, r: results.append(s), lambda p, e: errors.append(e)
    )
    return results, errors, reports


# (name, data, affine, failing step or None, fixed message or None)
CASES = [
    ("2d", BASE[..., 0], np.eye(4), "validate", "Voxel size must be three positive finite numbers."),
    ("5d", BASE[..., None, None].repeat(2, 3).repeat(2, 4), np.eye(4), "validate", "Unsupported volume dimensionality."),
    ("4d_single_volume", BASE[..., None], np.eye(4), None, None),
    ("nan", np.where(BASE > 1.5, np.nan, BASE).astype(np.float32), np.eye(4), "validate", "Volume contains non-finite values."),
    ("inf", np.where(BASE > 1.5, np.inf, BASE).astype(np.float32), np.eye(4), "validate", "Volume contains non-finite values."),
    ("float64_beyond_float32", BASE.astype(np.float64) * 1e307, np.eye(4), "normalize", "Volume contains non-finite values."),
    ("uint64", (BASE * 1000).astype(np.uint64), np.eye(4), None, None),
    ("int8", (BASE * 50).astype(np.int8), np.eye(4), None, None),
    ("constant", np.full((6, 5, 4), 7, np.uint8), np.eye(4), "normalize", "Volume is constant within the normalization mask."),
    ("all_zero", np.zeros((6, 5, 4), np.float32), np.eye(4), "normalize", "Normalization mask is empty."),
    ("single_slice", BASE[..., :1], np.eye(4), None, None),
    ("single_voxel", BASE[:1, :1, :1], np.eye(4), "normalize", "Volume is constant within the normalization mask."),
    ("oblique", BASE, _oblique(), None, None),
    ("lps", BASE, np.diag([-1.0, -1.0, 1.0, 1.0]), None, None),
    ("shear", BASE, np.array([[1, 0.5, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1.0]]), None, None),
]


@pytest.mark.parametrize("lazy", [False, True])
@pytest.mark.parametrize(("name", "data", "affine", "step", "message"), CASES, ids=[c[0] for c in CASES])
def test_hostile_volume_fails_in_the_expected_step_or_passes(
    tmp_path: Path, lazy: bool, name: str, data: np.ndarray, affine: np.ndarray, step: str | None, message: str | None
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # overflow while building the synthetic input
        path = _save(tmp_path / f"{name}.nii", data, affine)
    results, errors, (report,) = _run(path, lazy)
    if step is None:
        assert errors == [] and len(results) == 1
        volume = np.asarray(results[0].series[0].volume)
        assert volume.dtype == np.float32 and np.isfinite(volume).all()
        assert tuple(results[0].series[0].metadata["shape"]) == volume.shape
    else:
        assert results == [] and [str(e) for e in errors] == [message]
        assert [(s.name, s.status) for s in report.steps][-1] == (step, "failed")


COMPLEX = (np.arange(24).reshape(2, 3, 4) + 100j).astype(np.complex64)


@pytest.mark.parametrize("lazy", [False, True])
def test_complex_nifti_is_rejected_by_the_reader(tmp_path: Path, lazy: bool) -> None:
    """QA1-01 (fixed): the imaginary part is never silently dropped."""
    path = _save(tmp_path / "complex.nii", COMPLEX)
    with pytest.raises(ValueError, match="^Unsupported NIfTI data type.$"):
        NIfTIReader().load_study(path, lazy=lazy)


def test_complex_ndarray_volume_fails_its_study(tmp_path: Path) -> None:
    """QA1-01 (fixed): a complex ndarray reaching the pipeline by another way fails in validate."""
    series = MRISeries(volume=COMPLEX, metadata={"affine": np.eye(4), "shape": COMPLEX.shape, "voxel_size": (1.0, 1.0, 1.0)})
    results, errors = [], []
    (report,) = pipeline_from_config(CONFIG).run(
        [MRIStudy(study_uid=None, series=[series])], lambda s, r: results.append(s), lambda p, e: errors.append(e)
    )
    assert results == [] and [str(e) for e in errors] == ["Unsupported NIfTI data type."]
    assert (report.steps[-1].name, report.steps[-1].status) == ("validate", "failed")


def test_complex_nifti_to_dicom_writes_nothing(tmp_path: Path) -> None:
    path = _save(tmp_path / "complex.nii", COMPLEX)
    errors = []
    with pytest.raises(ValueError, match="No valid NIfTI studies were found."):
        convert_nifti_to_dicom(path, tmp_path / "out", on_error=lambda p, e: errors.append(e))
    assert [str(e) for e in errors] == ["Unsupported NIfTI data type."]
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*.dcm"))


def _corrupt(path: Path, cut: int = 0, dim: int | None = None) -> Path:
    """Write BASE to *path*, then cut *cut* trailing bytes or set dim[1] (byte 42) to *dim*."""
    _save(path, BASE)
    raw = bytearray(path.read_bytes())
    if dim is not None:
        struct.pack_into("<h", raw, 42, dim)
    path.write_bytes(bytes(raw[: len(raw) - cut]))
    return path


CORRUPT = {
    "truncated_nii": ("x.nii", {"cut": 40}),
    "header_only_nii": ("x.nii", {"cut": 96}),
    "dim_bigger_than_data": ("x.nii", {"dim": 60}),
    "negative_dim": ("x.nii", {"dim": -3}),
}


@pytest.mark.parametrize("lazy", [False, True])
@pytest.mark.parametrize("case", list(CORRUPT))
def test_corrupt_file_is_reported_and_the_batch_goes_on(tmp_path: Path, lazy: bool, case: str) -> None:
    name, corruption = CORRUPT[case]
    (tmp_path / "in").mkdir()
    _corrupt(tmp_path / "in" / f"a_{name}", **corruption)
    _save(tmp_path / "in" / "b_good.nii", BASE)
    read_errors, results, step_errors = [], [], []
    studies = NIfTIBatchReader().iter_studies(tmp_path / "in", on_error=lambda p, e: read_errors.append(e), lazy=lazy)
    pipeline_from_config(CONFIG).run(studies, lambda s, r: results.append(s), lambda p, e: step_errors.append(e))
    assert len(results) == 1
    assert [type(e) for e in read_errors + step_errors] == [ValueError]


@pytest.mark.parametrize("lazy", [False, True])
def test_negative_dim_error_has_a_fixed_message(tmp_path: Path, lazy: bool) -> None:
    """QA1-03 (fixed): no numpy message leaks through."""
    errors = []
    studies = NIfTIBatchReader().iter_studies(tmp_path, on_error=lambda p, e: errors.append(e), lazy=lazy)
    _corrupt(tmp_path / "x.nii", dim=-3)
    _save(tmp_path / "y_good.nii", BASE)
    pipeline_from_config(CONFIG).run(studies, lambda s, r: None, lambda p, e: errors.append(e))
    assert [str(e) for e in errors] in (["Unable to load NIfTI image."], ["Unable to read volume data."])


def test_unicode_spaces_hidden_and_long_paths(tmp_path: Path) -> None:
    deep = tmp_path / ("d" * 120) / ("e" * 120) / ("f" * 40)  # > 260 characters on Windows
    for relative in ("con espacio/a b.nii", "ñandú/señal_ü.nii.gz", "日本/画像.nii", ".hidden/x.nii", "vis/.y.nii"):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        _save(tmp_path / relative, BASE)
    deep.mkdir(parents=True)
    _save(deep / "long.nii", BASE)
    errors = []
    studies = list(NIfTIBatchReader().iter_studies(tmp_path, on_error=lambda p, e: errors.append(e), lazy=True))
    names = sorted(s.series[0].files[0].name for s in studies)
    assert errors == [] and names == ["a b.nii", "long.nii", "señal_ü.nii.gz", "画像.nii"]
    for study in studies:
        np.asarray(study.series[0].volume)  # the lazy proxy reopens these paths

    series = MRISeries(volume=BASE, metadata={"affine": np.eye(4)})
    assert NIfTIWriter().write(series, deep / "w.nii.gz").is_file()
    assert len(convert_nifti_to_dicom(deep / "long.nii", deep / "dicom ñ")) == 1
    assert len(convert_dicom_to_nifti(deep / "dicom ñ", deep / "nifti ü")) == 1
    report = anonymize_dicom_tree(deep / "dicom ñ", deep / "anon ü")
    assert (report.files_written, report.files_failed) == (BASE.shape[2], 0)


@pytest.mark.parametrize("lazy", [False, True])
def test_uppercase_extensions_are_read_and_written_compressed(tmp_path: Path, lazy: bool) -> None:
    """QA1-02 (fixed): .NII and .nii.GZ are NIfTI files; .nii.GZ output is gzip-compressed."""
    (tmp_path / "in").mkdir()
    _save(tmp_path / "in" / "a.NII", BASE)
    nib.save(nib.Nifti1Image(BASE, np.eye(4)), tmp_path / "in" / "b.nii.gz")
    (tmp_path / "in" / "b.nii.gz").rename(tmp_path / "in" / "b.nii.GZ")
    errors = []
    studies = list(NIfTIBatchReader().iter_studies(tmp_path / "in", on_error=lambda p, e: errors.append(e), lazy=lazy))
    assert errors == [] and sorted(s.series[0].files[0].name for s in studies) == ["a.NII", "b.nii.GZ"]
    for study in studies:
        assert np.allclose(np.asarray(study.series[0].volume), BASE)

    target = NIfTIWriter().write(MRISeries(volume=BASE, metadata={"affine": np.eye(4)}), tmp_path / "out.nii.GZ")
    assert target.read_bytes()[:2] == bytes([0x1F, 0x8B])  # gzip magic
    assert np.allclose(np.asarray(NIfTIReader().load_study(target, lazy=lazy).series[0].volume), BASE)


def test_duplicate_yaml_key_keeps_the_last_one(tmp_path: Path) -> None:
    """QA1-04 (documented limit, docs/architecture/config.md): no error, the last occurrence wins."""
    run_config = tmp_path / "run.yaml"
    run_config.write_text("pipeline:\n  steps: []\n  steps: [{name: validate}]\n", encoding="utf-8")
    config = load_config(run_config, config_dir=Path(__file__).resolve().parents[2] / "config")
    assert [step.name for step in pipeline_from_config(config).steps] == ["validate"]
