"""Manual check for stage 2: run a trivial step over data/raw/nifti_test_studies.

Usage, from the repository root:  python scripts/run_example_pipeline.py

Writes the run manifest to report.path of config/example_run.yaml (data/output/, ignored
by git), then rebuilds the pipeline from that manifest, runs it again and checks that
both runs match. Inspect the JSON: it must hold paths, step names and exception type
names only, never exception messages or header values.
"""

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.pipeline.step import register_step
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StudyReport
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader

REPO = Path(__file__).resolve().parents[1]
BATCH_DIR = REPO / "data" / "raw" / "nifti_test_studies"


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


def run(pipeline: Pipeline) -> tuple[list[StudyReport], int]:
    errors = 0

    def on_error(path: Path, error: Exception) -> None:
        nonlocal errors
        errors += 1

    reports = pipeline.run(
        NIfTIBatchReader().iter_studies(BATCH_DIR, on_error=on_error), on_result=lambda s, r: None, on_error=on_error
    )
    return reports, errors


def main() -> int:
    config = load_config(REPO / "config" / "example_run.yaml", config_dir=REPO / "config")
    logging.basicConfig(level=config["logging"]["level"])

    pipeline = pipeline_from_config(config)
    reports, errors = run(pipeline)
    manifest_path = REPO / config["report"]["path"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    RunManifest.from_run(config, pipeline, reports).write(manifest_path, overwrite=True)

    saved = RunManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    replay = pipeline_from_manifest(saved)
    replay_reports, _ = run(replay)
    reproduced = RunManifest.from_run(saved.config, replay, replay_reports) == saved

    print(f"Studies: {len(reports)}  errors reported: {errors}  reproduced from manifest: {reproduced}")
    print("Manifest written to report.path of config/example_run.yaml.")
    return 0 if reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())
