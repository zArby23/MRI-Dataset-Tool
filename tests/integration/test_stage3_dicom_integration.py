"""Integration: synthetic DICOM through conversion, anonymization and the stage 3 pipeline."""

import dataclasses
import gzip
import importlib.util
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config
from mri_dataset_tool.application.services.anonymize import REPORT_NAME, anonymize_dicom_tree
from mri_dataset_tool.application.services.conversion import convert_dicom_to_nifti
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.dicom.volume_builder import build_series_volume
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader

REPO = Path(__file__).resolve().parents[2]
# shortcut: reuses the realistic generator of the A2 unit test; move to tests/synthetic_dicom.py if a third user appears
_spec = importlib.util.spec_from_file_location("_synthetic_dicom", REPO / "tests" / "unit" / "test_anonymize_dicom_tree.py")
synthetic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synthetic)

N_SLICES = 6
PLANTED = [*synthetic.PLANTED, *(synthetic.sop_uid(i) for i in range(N_SLICES))]


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(synthetic.KEY_ENV_VAR, synthetic.KEY)


def _run_stage3(nifti_dir: Path) -> tuple[list, list, str]:
    """Run config/stage3_example.yaml over *nifti_dir* lazily; return results, error types and the manifest."""
    config = load_config(REPO / "config" / "stage3_example.yaml", config_dir=REPO / "config")
    pipeline = pipeline_from_config(config)
    results, errors = [], []
    reports = pipeline.run(
        NIfTIBatchReader().iter_studies(nifti_dir, lazy=True),
        lambda study, report: results.append((study, report)),
        lambda path, error: errors.append(type(error).__name__),
    )
    return results, errors, RunManifest.from_run(config, pipeline, reports).to_json()


def _center(affine: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    return (np.asarray(affine) @ np.append((np.asarray(shape[:3]) - 1) / 2, 1.0))[:3]


def _strings(value) -> list[str]:
    if dataclasses.is_dataclass(value):
        return [s for f in dataclasses.fields(value) for s in _strings(getattr(value, f.name))]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(k) + _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item)]
    return [str(value)] if isinstance(value, (str, Path)) else []


def test_dicom_converted_to_nifti_keeps_its_geometry_through_the_stage3_pipeline(tmp_path: Path) -> None:
    inputs = synthetic.write_synthetic_series(tmp_path / "dicom", n_slices=N_SLICES)
    expected = build_series_volume(MRISeries(series_uid=synthetic.SERIES_UID, modality="MR", files=inputs))

    converted = convert_dicom_to_nifti(tmp_path / "dicom", tmp_path / "nifti")

    # conversion keeps the DICOM geometry (LPS headers -> RAS+ affine) and the rescaled values
    image = nib.load(converted[0].series[0].files[0])
    np.testing.assert_allclose(image.affine, expected.metadata["affine"])
    np.testing.assert_allclose(image.get_fdata(), expected.volume)
    assert "".join(nib.aff2axcodes(image.affine)) == "LPS"

    results, errors, manifest = _run_stage3(tmp_path / "nifti")

    assert errors == [] and len(results) == 1
    (study, report), = results
    series = study.series[0]
    assert [s.status for s in report.steps] == ["ok"] * 5
    assert report.steps[2].outputs == {"series": [{"index": 0, "source": "LPS", "target": "RAS"}]}
    # RAS, 1 mm, physical field of view kept and centered on the same world point
    assert series.metadata["orientation"] == ("R", "A", "S")
    np.testing.assert_allclose(series.metadata["voxel_size"], [1.0, 1.0, 1.0])
    extent = np.asarray(image.shape) * np.asarray(image.header.get_zooms()[:3])
    assert series.metadata["shape"] == tuple(int(n) for n in np.ceil(extent - 1e-6))
    np.testing.assert_allclose(_center(series.metadata["affine"], series.metadata["shape"]), _center(image.affine, image.shape))
    assert series.volume.dtype == np.float32 and np.isfinite(series.volume).all()
    assert str(tmp_path) not in manifest and "sub-" not in manifest


def test_anonymized_dicom_converts_to_nifti_without_identifiers(tmp_path: Path) -> None:
    synthetic.write_synthetic_series(tmp_path / "dicom", n_slices=N_SLICES)
    original = convert_dicom_to_nifti(tmp_path / "dicom", tmp_path / "nifti_original")
    assert synthetic.STUDY_UID in _strings(original)  # the detector does see identifiers without anonymization

    anonymize_dicom_tree(tmp_path / "dicom", tmp_path / "anonymized")
    errors: list[str] = []
    converted = convert_dicom_to_nifti(
        tmp_path / "anonymized", tmp_path / "nifti", on_error=lambda path, error: errors.append(path.name)
    )

    assert errors == [REPORT_NAME]  # the audit report is not DICOM: skipped by the reader, nothing else
    outputs = sorted((tmp_path / "nifti").iterdir())
    assert [p.name for p in outputs] == ["study-001_series-001.nii.gz"]
    # no identifier in the NIfTI bytes (header, extensions, data) nor in the returned model
    raw = gzip.decompress(outputs[0].read_bytes())
    assert [v for v in PLANTED if v.encode() in raw] == []
    assert [v for v in PLANTED if any(v in s for s in _strings(converted))] == []
    assert converted[0].study_uid.startswith("2.25.") and converted[0].series[0].series_uid.startswith("2.25.")
    # anonymization keeps what the volume needs: same voxels and geometry as without it
    anonymized_image, original_image = nib.load(outputs[0]), nib.load(original[0].series[0].files[0])
    np.testing.assert_array_equal(anonymized_image.get_fdata(), original_image.get_fdata())
    np.testing.assert_allclose(anonymized_image.affine, original_image.affine)
