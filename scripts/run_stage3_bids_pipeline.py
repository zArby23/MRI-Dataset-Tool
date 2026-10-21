"""Stage 3 pipeline over a BIDS dataset (QA2): config/stage3_bids.yaml.

Usage, from the repository root (the key is a secret of at least 32 characters):

    $env:MRI_ANON_KEY = "<secret>"          # PowerShell;  bash: export MRI_ANON_KEY=<secret>
    python scripts/run_stage3_bids_pipeline.py --output-dir E:/mri/stage3 --manifest-path E:/mri/stage3.json
    python scripts/run_stage3_bids_pipeline.py <dataset_root> --output-dir ... --manifest-path ...

The pipeline comes only from config/stage3_bids.yaml (anatomy resampled to 1 mm, dwi to 2 mm;
a series whose modality is in neither list is not resampled). Studies are read lazily, one
(subject, session) at a time, with BIDSBatchReader from <dataset_root> (default
data/raw/bids_test_studies). Each series is written as float32 to
<output-dir>/study-NNN_series-MMM.nii.gz (positions in the input order, never source names)
and the run manifest to --manifest-path. Both are required: large outputs must not go to C:
or the temporary directory (a warning is printed, the run is not blocked). Nothing is
overwritten: if outputs of a previous run exist the script stops before running. The pipeline
is then rebuilt from the saved manifest and run again to check reproducibility. Errors print
only their exception type; neither the console nor the manifest show paths, names or messages.
"""

import argparse
import logging
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import numpy as np

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StudyReport
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, load_key
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.nifti.writer import NIfTIWriter
from mri_dataset_tool.infrastructure.processing.arrays import load_array

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "stage3_bids.yaml"
DEFAULT_DATASET = REPO / "data" / "raw" / "bids_test_studies"


def output_name(index: int, series_index: int) -> str:
    return f"study-{index:03d}_series-{series_index:03d}.nii.gz"


def is_discouraged_location(path: Path) -> bool:
    """True if *path* is on drive C: or under the system temporary directory."""
    resolved = path.resolve()
    return resolved.drive.upper() == "C:" or resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())


def run(pipeline: Pipeline, dataset_root: Path, output_dir: Path | None) -> tuple[list[StudyReport], Counter[str], int]:
    """Run *pipeline* over the BIDS studies of *dataset_root*; write results to *output_dir* if given.

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
            target = output_dir / output_name(report.index, series_index)
            try:
                writer.write(replace(series, volume=load_array(series.volume, np.float32)), target, overwrite=False)
                written += 1
            except Exception as error:  # a failed write is reported like any other error; the batch continues
                on_error(target, error)

    studies = BIDSBatchReader().iter_studies(dataset_root, on_error=on_error, lazy=True)
    reports = pipeline.run(studies, on_result=on_result, on_error=on_error)
    return reports, errors, written


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 3 pipeline over a BIDS dataset (config/stage3_bids.yaml).")
    parser.add_argument("dataset_root", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, required=True, help="directory for the processed NIfTI files")
    parser.add_argument("--manifest-path", type=Path, required=True, help="JSON file for the run manifest")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)  # missing --output-dir / --manifest-path: argparse prints usage and exits with 2
    try:
        load_key()
    except ValueError:
        print(f"{KEY_ENV_VAR} is not set or is shorter than 32 characters; nothing was run.")
        return 2
    dataset_root, output_dir, manifest_path = args.dataset_root, args.output_dir, args.manifest_path
    if not dataset_root.is_dir():
        print("Dataset directory not found.")  # fixed text: never the path
        return 2
    if is_discouraged_location(output_dir) or is_discouraged_location(manifest_path):
        print("WARNING: an output is on drive C: or in the temporary directory; large runs should go elsewhere (E:/).")

    config = load_config(CONFIG_PATH, config_dir=REPO / "config")
    logging.basicConfig(level=config["logging"]["level"])
    if manifest_path.exists() or any(output_dir.glob("study-*.nii.gz")):
        print("Outputs of a previous run exist (study-*.nii.gz in the output directory or the manifest); remove them first.")
        return 1

    pipeline = pipeline_from_config(config)
    print("Running stage 3 BIDS pipeline...")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        reports, errors, written = run(pipeline, dataset_root, output_dir)
    except ValueError as error:  # the reader itself failed (no valid studies, invalid dataset_description.json)
        print(f"Reading the dataset failed: {type(error).__name__}")
        return 1

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest.from_run(config, pipeline, reports)
    manifest.write(manifest_path)
    text = manifest_path.read_text(encoding="utf-8")
    root = dataset_root.resolve()
    no_sources = all(p not in text for p in (str(root), root.as_posix(), "sub-"))

    saved = RunManifest.from_json(text)
    replay = pipeline_from_manifest(saved)
    replay_reports, _, _ = run(replay, dataset_root, None)
    reproduced = RunManifest.from_run(saved.config, replay, replay_reports) == saved

    failed = sum(1 for report in reports if report.steps and report.steps[-1].status == "failed")
    print(f"Studies: {len(reports)}  ok: {len(reports) - failed}  failed in a step: {failed}  files written: {written}")
    print(f"Errors by type: {dict(sorted(errors.items())) or 'none'}")
    print(f"Manifest without source paths: {no_sources}  reproduced from manifest: {reproduced}")
    return 0 if no_sources and reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
