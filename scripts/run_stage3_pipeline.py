"""Stage 3 closing pipeline (E1): validate -> anonymize -> reorient -> resample -> normalize.

Usage, from the repository root (the key is a secret of at least 32 characters):

    $env:MRI_ANON_KEY = "<secret>"          # PowerShell;  bash: export MRI_ANON_KEY=<secret>
    python scripts/run_stage3_pipeline.py

The pipeline comes only from config/stage3_example.yaml. Studies are read lazily, one at a
time, from data/raw/nifti_test_studies; each processed series is written as float32 to
data/processed/study-NNN.nii.gz (NNN = position in the input order, never the source name)
and the run manifest to report.path (data/output/). Nothing is overwritten: if outputs of a
previous run exist the script stops before running. The pipeline is then rebuilt from the
saved manifest and run again to check reproducibility. Errors print only their exception
type; neither the console nor the manifest show input paths, names or messages.
"""

import logging
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StudyReport
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, load_key
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.nifti.writer import NIfTIWriter
from mri_dataset_tool.infrastructure.processing.arrays import load_array

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "stage3_example.yaml"
INPUT_DIR = REPO / "data" / "raw" / "nifti_test_studies"
OUTPUT_DIR = REPO / "data" / "processed"


def output_name(index: int, series_index: int, series_count: int) -> str:
    suffix = "" if series_count == 1 else f"_series-{series_index:03d}"
    return f"study-{index:03d}{suffix}.nii.gz"


def run(pipeline: Pipeline, input_dir: Path, output_dir: Path | None) -> tuple[list[StudyReport], Counter[str], int]:
    """Run *pipeline* over the NIfTI files of *input_dir*; write results to *output_dir* if given.

    Returns the reports, the error count per exception type and the number of files written.
    """
    errors: Counter[str] = Counter()
    written = 0
    writer = NIfTIWriter()

    def on_error(path: Path, error: Exception) -> None:  # path is never printed (PHI)
        errors[type(error).__name__] += 1
        print(f"  error {sum(errors.values())}: {type(error).__name__}")

    def on_result(study: MRIStudy, report: StudyReport) -> None:
        nonlocal written
        if output_dir is None:
            return
        for series_index, series in enumerate(study.series, start=1):
            if series.volume is None:
                continue
            target = output_dir / output_name(report.index, series_index, len(study.series))
            try:
                writer.write(replace(series, volume=load_array(series.volume, np.float32)), target, overwrite=False)
                written += 1
            except Exception as error:  # a failed write is reported like any other error; the batch continues
                on_error(target, error)

    studies = NIfTIBatchReader().iter_studies(input_dir, on_error=on_error, lazy=True)
    reports = pipeline.run(studies, on_result=on_result, on_error=on_error)
    return reports, errors, written


def main() -> int:
    try:
        load_key()
    except ValueError:
        print(f"{KEY_ENV_VAR} is not set or is shorter than 32 characters; nothing was run.")
        return 2
    if not INPUT_DIR.is_dir():
        print("Input directory not found: data/raw/nifti_test_studies")  # fixed text: never the absolute path
        return 2

    config = load_config(CONFIG_PATH, config_dir=REPO / "config")
    logging.basicConfig(level=config["logging"]["level"])
    manifest_path = REPO / config["report"]["path"]
    if manifest_path.exists() or any(OUTPUT_DIR.glob("study-*.nii.gz")):
        print("Outputs of a previous run exist (data/processed/study-*.nii.gz or the manifest); remove them first.")
        return 1

    pipeline = pipeline_from_config(config)
    print("Running stage 3 pipeline...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reports, errors, written = run(pipeline, INPUT_DIR, OUTPUT_DIR)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest.from_run(config, pipeline, reports)
    manifest.write(manifest_path)
    text = manifest_path.read_text(encoding="utf-8")
    no_sources = str(INPUT_DIR) not in text and str(INPUT_DIR.as_posix()) not in text and "sub-" not in text

    saved = RunManifest.from_json(text)
    replay = pipeline_from_manifest(saved)
    replay_reports, _, _ = run(replay, INPUT_DIR, None)
    reproduced = RunManifest.from_run(saved.config, replay, replay_reports) == saved

    failed = sum(1 for report in reports if report.steps and report.steps[-1].status == "failed")
    print(f"Studies: {len(reports)}  ok: {len(reports) - failed}  failed in a step: {failed}  files written: {written}")
    print(f"Errors by type: {dict(sorted(errors.items())) or 'none'}")
    print(f"Manifest without source paths: {no_sources}  reproduced from manifest: {reproduced}")
    print(f"Manifest: {manifest_path.relative_to(REPO).as_posix()}  outputs: {OUTPUT_DIR.relative_to(REPO).as_posix()}/")
    return 0 if no_sources and reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())
