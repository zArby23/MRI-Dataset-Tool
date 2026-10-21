import ast
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.application.services import summary as summary_module
from mri_dataset_tool.application.services.summary import summarize_study
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.anonymization.policy import (
    FILTERED_METADATA_KEYS,
    METADATA_WHITELIST,
    SIDECAR_WHITELIST,
)
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader

SECRETS = ("SECRET", "1.2.840.99", "19700101", "C:\\private", "/home/private")


def _leaky_series(volume, tmp_path: Path) -> MRISeries:
    return MRISeries(
        series_uid="1.2.840.99.1",
        modality="T1w",
        files=[tmp_path / "sub-SECRET_T1w.nii.gz"],
        volume=volume,
        metadata={
            "shape": None if volume is None else tuple(volume.shape),
            "voxel_size": (1.0, 1.0, 2.0),
            "affine": np.eye(4),
            "orientation": ("R", "A", "S"),
            "datatype": "int16",
            "validation": {"status": "ok", "findings": []},
            "PatientName": "SECRET^NAME",
            "PatientID": "SECRET-ID",
            "StudyDate": "19700101",
            "study_uid": "1.2.840.99.2",
            "source": "C:\\private\\scan.nii.gz",
            "provenance": {"tool": "mri-dataset-tool", "path": Path("/home/private/x")},
            "bids": {"sub": "SECRET", "ses": "SECRET", "suffix": "T1w"},
            "sidecar": {
                "RepetitionTime": 2.3,
                "EchoTime": 0.003,
                "SliceTiming": [0.0, 0.5, 1.0],
                "Manufacturer": "Siemens",
                "PatientName": "SECRET^NAME",
                "AcquisitionDateTime": "19700101T101010",
                "InstitutionName": "SECRET hospital",
                "FlipAngle": {"nested": "SECRET"},  # allowed key, disallowed shape
            },
        },
    )


def _leaky_study(volume, tmp_path: Path) -> MRIStudy:
    return MRIStudy(
        study_uid="1.2.840.99.3",
        series=[_leaky_series(volume, tmp_path)],
        subject_id="SECRET",
        session_id="SECRET",
    )


def test_no_identifier_path_or_unlisted_key_leaks(tmp_path: Path) -> None:
    result = summarize_study(_leaky_study(np.arange(24, dtype=np.int16).reshape(2, 3, 4), tmp_path))
    text = json.dumps(result)
    for secret in (*SECRETS, str(tmp_path)):
        assert secret not in text
    series = result["series"][0]
    for key in ("PatientName", "PatientID", "StudyDate", "study_uid", "source", "bids", "files", "series_uid"):
        assert key not in series
    assert series["sidecar"] == {
        "EchoTime": 0.003,
        "Manufacturer": "Siemens",
        "RepetitionTime": 2.3,
        "SliceTiming": [0.0, 0.5, 1.0],
    }
    allowed = (METADATA_WHITELIST - FILTERED_METADATA_KEYS) | {"modality", "sidecar", "validation", "dtype", "intensity"}
    assert set(series) <= allowed
    assert set(series["sidecar"]) <= SIDECAR_WHITELIST


def test_3d_summary_content_is_json_ready(tmp_path: Path) -> None:
    volume = np.arange(24, dtype=np.int16).reshape(2, 3, 4)
    result = summarize_study(_leaky_study(volume, tmp_path))
    assert json.loads(json.dumps(result)) == result
    series = result["series"][0]
    assert result["series_count"] == 1
    assert series["modality"] == "T1w"
    assert series["shape"] == [2, 3, 4]
    assert series["voxel_size"] == [1.0, 1.0, 2.0]
    assert series["orientation"] == ["R", "A", "S"]
    assert series["affine"] == np.eye(4).tolist()
    assert series["dtype"] == "int16" and series["datatype"] == "int16"
    assert series["intensity"] == {
        "min": 0.0,
        "max": 23.0,
        "mean": pytest.approx(11.5),
        "std": pytest.approx(volume.std()),
        "non_finite_voxels": 0,
    }


def test_4d_intensity_matches_whole_volume(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    volume = rng.normal(100, 20, (3, 4, 5, 6))
    intensity = summarize_study(_leaky_study(volume, tmp_path))["series"][0]["intensity"]
    assert intensity["mean"] == pytest.approx(volume.mean())
    assert intensity["std"] == pytest.approx(volume.std())
    assert (intensity["min"], intensity["max"]) == (volume.min(), volume.max())


def test_non_finite_voxels_are_counted_not_propagated(tmp_path: Path) -> None:
    volume = np.ones((2, 2, 2))
    volume[0, 0, 0], volume[1, 1, 1] = np.nan, np.inf
    intensity = summarize_study(_leaky_study(volume, tmp_path))["series"][0]["intensity"]
    assert intensity == {"min": 1.0, "max": 1.0, "mean": 1.0, "std": 0.0, "non_finite_voxels": 2}
    json.dumps(intensity, allow_nan=False)


def test_series_without_volume_has_only_metadata(tmp_path: Path) -> None:
    series = summarize_study(_leaky_study(None, tmp_path))["series"][0]
    assert series["dtype"] is None and series["intensity"] is None
    assert "shape" in series and series["shape"] is None


def test_lazy_volume_matches_eager_without_being_materialized(tmp_path: Path) -> None:
    path = tmp_path / "scan.nii.gz"
    data = np.arange(3 * 4 * 5 * 2, dtype=np.int16).reshape(3, 4, 5, 2)
    nib.save(nib.Nifti1Image(data, np.eye(4)), path)
    lazy_study = NIfTIReader().load_study(path, lazy=True)
    lazy = summarize_study(lazy_study)
    eager = summarize_study(NIfTIReader().load_study(path))

    assert not isinstance(lazy_study.series[0].volume, np.ndarray)
    assert lazy["series"][0]["dtype"] == "int16"  # on-disk dtype
    assert eager["series"][0]["dtype"] == "float64"  # get_fdata
    del lazy["series"][0]["dtype"], eager["series"][0]["dtype"]
    assert lazy == eager


def test_summary_is_deterministic(tmp_path: Path) -> None:
    study = _leaky_study(np.arange(24, dtype=np.float32).reshape(2, 3, 4), tmp_path)
    assert json.dumps(summarize_study(study)) == json.dumps(summarize_study(study))


def test_allow_lists_are_imported_not_redefined() -> None:
    tree = ast.parse(Path(summary_module.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "mri_dataset_tool.infrastructure.anonymization.policy"
        for alias in node.names
    }
    assert {"METADATA_WHITELIST", "SIDECAR_WHITELIST"} <= imported
    literal_sets = [n for n in ast.walk(tree) if isinstance(n, (ast.Set, ast.List)) and len(n.elts) > 3]
    assert literal_sets == []


def test_non_basic_values_are_dropped_not_stringified() -> None:
    assert summary_module._plain({"b": 1, "a": Path("/home/private/x"), "c": [1, object()]}) == {"b": 1}
    assert summary_module._plain(np.float32(1.5)) == 1.5 and type(summary_module._plain(np.int64(2))) is int


def test_non_finite_metadata_and_sidecar_values_are_dropped(tmp_path: Path) -> None:
    study = _leaky_study(np.ones((2, 2, 2)), tmp_path)
    series = study.series[0]
    series.metadata["voxel_size"] = (1.0, float("nan"), 1.0)
    series.metadata["bitpix"] = np.float64("inf")
    series.metadata["sidecar"].update(EchoTime=float("nan"), RepetitionTime=float("inf"), SliceTiming=[0.0, float("nan")])

    summary = summarize_study(study)

    json.dumps(summary, allow_nan=False)
    result = summary["series"][0]
    assert "voxel_size" not in result and "bitpix" not in result
    assert result["sidecar"] == {"Manufacturer": "Siemens"}
    assert result["shape"] == [2, 2, 2]


def test_validation_is_included_through_the_policy_filter(tmp_path: Path) -> None:
    study = _leaky_study(np.ones((2, 2, 2)), tmp_path)
    metadata = study.series[0].metadata

    metadata["validation"] = {"status": "ok", "findings": ["CONSTANT_VOLUME", "SINGLE_VOLUME_4D"]}
    assert summarize_study(study)["series"][0]["validation"] == {
        "status": "ok",
        "findings": ["CONSTANT_VOLUME", "SINGLE_VOLUME_4D"],
    }

    metadata["validation"] = {"status": "SECRET", "findings": ["CONSTANT_VOLUME", "SECRET name", 3], "note": "SECRET"}
    result = summarize_study(study)["series"][0]["validation"]
    assert result == {"findings": ["CONSTANT_VOLUME"]}

    for raw in ("SECRET", None, {"note": "SECRET"}):
        metadata["validation"] = raw
        assert "validation" not in summarize_study(study)["series"][0]
