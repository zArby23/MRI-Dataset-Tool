"""Stage 2 closing criterion: a trivial pipeline over a synthetic batch records each
transformation, continues after a failure and is reproduced from the saved manifest."""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

import nibabel as nib
import numpy as np

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.step import register_step
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader


@register_step("example.scale")
@dataclass(frozen=True)
class ScaleStep:
    factor: float = 1.0
    name: ClassVar[str] = "example.scale"
    version: ClassVar[str] = "1"

    @property
    def params(self) -> dict[str, Any]:
        return {"factor": self.factor}

    def apply(self, study: MRIStudy) -> MRIStudy:
        return replace(study, series=[replace(s, volume=s.volume * self.factor) for s in study.series])


@register_step("example.check_shape")
@dataclass(frozen=True)
class CheckShapeStep:
    shape: list[int]
    name: ClassVar[str] = "example.check_shape"
    version: ClassVar[str] = "1"

    @property
    def params(self) -> dict[str, Any]:
        return {"shape": list(self.shape)}

    def apply(self, study: MRIStudy) -> MRIStudy:
        if any(list(s.volume.shape) != self.shape for s in study.series):
            raise ValueError("Unexpected volume shape.")
        return study


RUN_YAML = """\
pipeline:
  steps:
    - name: example.scale
      params: {factor: 2.0}
    - name: example.check_shape
      params: {shape: [2, 2, 2]}
report:
  path: run_manifest.json
"""


def _synthetic_batch(directory: Path) -> Path:
    directory.mkdir()
    for name, shape in [("sub-01_T1w", (2, 2, 2)), ("sub-02_T1w", (2, 2, 3)), ("sub-03_T1w", (2, 2, 2))]:
        nib.save(nib.Nifti1Image(np.ones(shape, dtype=np.float32), np.eye(4)), directory / f"{name}.nii.gz")
    return directory


def _run(pipeline, batch: Path) -> tuple[list[np.ndarray], list[str], list]:
    volumes: list[np.ndarray] = []
    errors: list[str] = []
    reports = pipeline.run(
        NIfTIBatchReader().iter_studies(batch),
        on_result=lambda study, report: volumes.append(study.series[0].volume),
        on_error=lambda path, error: errors.append(path.name),
    )
    return volumes, errors, reports


def test_example_pipeline_records_continues_and_reproduces(tmp_path: Path) -> None:
    batch = _synthetic_batch(tmp_path / "batch")
    run_file = tmp_path / "run.yaml"
    run_file.write_text(RUN_YAML, encoding="utf-8")
    config = load_config(run_file, config_dir=Path(__file__).resolve().parents[2] / "config")

    # first run: driven by the configuration
    pipeline = pipeline_from_config(config)
    volumes, errors, reports = _run(pipeline, batch)
    manifest_path = RunManifest.from_run(config, pipeline, reports).write(tmp_path / config["report"]["path"])

    assert errors == ["sub-02_T1w.nii.gz"]  # the failure is reported and the batch continues
    assert len(volumes) == 2 and all(np.all(v == 2.0) for v in volumes)
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [[step["status"] for step in r["steps"]] for r in saved["reports"]] == [
        ["ok", "ok"],
        ["ok", "failed"],
        ["ok", "ok"],
    ]
    assert saved["reports"][1]["steps"][1]["error_type"] == "ValueError"
    assert "Unexpected volume shape" not in manifest_path.read_text(encoding="utf-8")

    # second run: rebuilt only from the saved manifest
    loaded = RunManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    replay = pipeline_from_manifest(loaded)
    replay_volumes, replay_errors, replay_reports = _run(replay, batch)

    assert replay_errors == errors
    for got, expected in zip(replay_volumes, volumes, strict=True):
        np.testing.assert_array_equal(got, expected)
    assert RunManifest.from_run(loaded.config, replay, replay_reports) == loaded
