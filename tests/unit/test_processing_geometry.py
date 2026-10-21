import ast
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.processing import geometry
from mri_dataset_tool.infrastructure.processing.geometry import (
    apply_to_series,
    check_modalities,
    replace_volume,
    validate_geometry,
)

_THETA = np.deg2rad(30)
_OBLIQUE = np.array(
    [
        [np.cos(_THETA), -np.sin(_THETA), 0.0, 5.0],
        [np.sin(_THETA), np.cos(_THETA), 0.0, -3.0],
        [0.0, 0.0, 1.0, 2.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)

# (affine, expected voxel_size, expected orientation)
AFFINES = {
    "ras": (np.diag([1.0, 1.0, 1.0, 1.0]), (1.0, 1.0, 1.0), ("R", "A", "S")),
    "lps": (np.diag([-1.0, -1.0, 1.0, 1.0]), (1.0, 1.0, 1.0), ("L", "P", "S")),
    "oblique": (_OBLIQUE, (1.0, 1.0, 1.0), ("R", "A", "S")),
    "anisotropic": (np.diag([0.5, 2.0, 3.0, 1.0]), (0.5, 2.0, 3.0), ("R", "A", "S")),
    "permuted": (
        np.array([[0.0, 0.0, 2.0, 0.0], [-1.5, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]),
        (1.5, 1.0, 2.0),
        ("P", "S", "R"),
    ),
}


def _series(**kwargs) -> MRISeries:
    defaults = dict(
        modality="T1w",
        files=[Path("a.nii.gz")],
        metadata={"shape": (2, 3, 4), "affine": np.eye(4), "datatype": "float64", "bids": {"sub": "01"}},
        volume=np.zeros((2, 3, 4)),
    )
    defaults.update(kwargs)
    return MRISeries(**defaults)


@pytest.mark.parametrize("name", AFFINES)
def test_replace_volume_recomputes_canonical_geometry(name: str) -> None:
    affine, voxel_size, orientation = AFFINES[name]
    volume = np.arange(5 * 6 * 7, dtype=np.float32).reshape(5, 6, 7)

    result = replace_volume(_series(), volume, affine)

    assert result.volume is volume
    assert result.metadata["shape"] == (5, 6, 7)
    np.testing.assert_allclose(result.metadata["voxel_size"], voxel_size)
    np.testing.assert_array_equal(result.metadata["affine"], affine)
    assert result.metadata["orientation"] == orientation
    validate_geometry(result)


def test_replace_volume_keeps_other_metadata_and_files_without_mutating_input() -> None:
    series = _series()
    original_metadata = dict(series.metadata)
    affine = AFFINES["lps"][0]

    result = replace_volume(series, np.ones((2, 2, 2)), affine)

    assert result is not series
    assert result.files == series.files and result.files is not series.files
    assert result.modality == "T1w"
    assert result.metadata["datatype"] == "float64"
    assert result.metadata["bids"] == {"sub": "01"}
    assert series.metadata == original_metadata
    assert series.volume.shape == (2, 3, 4)
    affine[0, 0] = 7.0  # the stored affine is a copy
    assert result.metadata["affine"][0, 0] == -1.0


def test_replace_volume_does_not_share_nested_metadata_with_input() -> None:
    series = _series(metadata={"affine": np.eye(4), "sidecar": {"EchoTime": 0.03}, "provenance": {"tool": "x"}})

    result = replace_volume(series, np.ones((2, 2, 2)), np.eye(4))
    result.metadata["sidecar"]["EchoTime"] = 1.0
    result.metadata["provenance"]["tool"] = "y"

    assert series.metadata["sidecar"] == {"EchoTime": 0.03}
    assert series.metadata["provenance"] == {"tool": "x"}


def test_replace_volume_4d_takes_spatial_geometry_from_affine() -> None:
    result = replace_volume(_series(), np.zeros((2, 3, 4, 5)), AFFINES["anisotropic"][0])

    assert result.metadata["shape"] == (2, 3, 4, 5)
    assert result.metadata["voxel_size"] == (0.5, 2.0, 3.0)


BAD_AFFINES = {
    "not_4x4": np.eye(3),
    "ragged": [[1, 0], [0, 1, 0]],
    "text": [["a"] * 4] * 4,
    "nan": np.diag([1.0, np.nan, 1.0, 1.0]),
    "inf": np.diag([1.0, 1.0, np.inf, 1.0]),
    "singular": np.diag([1.0, 0.0, 1.0, 1.0]),
    "projective_last_row": np.array([[1.0, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0.5, 1]]),
}


@pytest.mark.parametrize("name", BAD_AFFINES)
def test_invalid_affine_is_rejected_with_fixed_message(name: str) -> None:
    with pytest.raises(ValueError, match=r"^Affine must") as replace_error:
        replace_volume(_series(), np.zeros((2, 3, 4)), BAD_AFFINES[name])
    with pytest.raises(ValueError, match=r"^Affine must") as validate_error:
        validate_geometry(_series(metadata={"shape": (2, 3, 4), "affine": BAD_AFFINES[name]}))

    assert replace_error.value.__cause__ is None
    assert validate_error.value.__cause__ is None


def test_validate_geometry_rejects_shape_mismatch_missing_volume_and_affine() -> None:
    with pytest.raises(ValueError, match="^Series shape does not match its volume.$"):
        validate_geometry(_series(metadata={"shape": (2, 3, 5), "affine": np.eye(4)}))
    with pytest.raises(ValueError, match="^Series shape does not match its volume.$"):
        validate_geometry(_series(metadata={"affine": np.eye(4)}))
    with pytest.raises(ValueError, match="^Series shape does not match its volume.$"):
        validate_geometry(_series(metadata={"shape": 3, "affine": np.eye(4)}))
    with pytest.raises(ValueError, match="^Series has no volume.$"):
        validate_geometry(_series(volume=None))
    with pytest.raises(ValueError, match="^Series has no affine.$"):
        validate_geometry(_series(metadata={"shape": (2, 3, 4)}))


def test_validate_geometry_accepts_list_affine_from_manifest_like_metadata() -> None:
    validate_geometry(_series(metadata={"shape": [2, 3, 4], "affine": np.eye(4).tolist()}))


def _mark(series: MRISeries) -> tuple[MRISeries, dict]:
    return replace_volume(series, series.volume + 1, series.metadata["affine"]), {"marked": True}


def _study() -> MRIStudy:
    return MRIStudy(
        study_uid=None,
        series=[
            _series(modality="T1w"),
            _series(modality="bold"),
            _series(modality=None),
            _series(modality="T1w", volume=None),
        ],
    )


def test_apply_to_series_without_filter_transforms_every_series_with_volume() -> None:
    study = _study()

    result, outputs = apply_to_series(study, _mark)

    assert outputs == {"series": [{"index": 0, "marked": True}, {"index": 1, "marked": True}, {"index": 2, "marked": True}]}
    assert result is not study
    assert [s.volume.max() if s.volume is not None else None for s in result.series] == [1, 1, 1, None]
    assert result.series[3] is study.series[3]
    assert all(s.volume is None or s.volume.max() == 0 for s in study.series)


def test_apply_to_series_with_filter_only_transforms_listed_modalities() -> None:
    study = _study()

    result, outputs = apply_to_series(study, _mark, ["T1w"])

    assert outputs == {"series": [{"index": 0, "marked": True}]}
    assert result.series[0].volume.max() == 1
    assert result.series[1:] == study.series[1:]
    assert all(a is b for a, b in zip(result.series[1:], study.series[1:]))  # modality=None excluded


def test_apply_to_series_with_empty_filter_selects_nothing() -> None:
    study = _study()

    result, outputs = apply_to_series(study, _mark, [])

    assert result.series == study.series
    assert outputs == {"series": []}


@pytest.mark.parametrize("modalities", ["T1w", 3, [1], {"T1w": 1}])
def test_invalid_modalities_are_rejected(modalities) -> None:
    with pytest.raises(ValueError, match="^Modalities must be a list of strings.$"):
        check_modalities(modalities)
    with pytest.raises(ValueError, match="^Modalities must be a list of strings.$"):
        apply_to_series(_study(), _mark, modalities)


def test_processing_geometry_does_not_import_application() -> None:
    package = Path(geometry.__file__).parent
    for module in package.glob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(name.startswith("mri_dataset_tool.application") for name in names), module.name


def test_manifest_registers_builtin_steps_without_manual_import() -> None:
    # fresh interpreter: only importing the manifest module must load the built-in steps package
    code = (
        "import sys\n"
        "from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config\n"
        "assert 'mri_dataset_tool.application.pipeline.steps' in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
