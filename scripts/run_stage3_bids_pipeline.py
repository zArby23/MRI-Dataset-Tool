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
After "Run failed", delete the partial outputs (study-*.nii.gz) before retrying.
"""

import argparse
import logging
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config  # noqa: F401 (tests patch RunManifest)
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.services.pipeline_run import (
    StageFailed,
    previous_outputs_exist,
    process_studies,
    read_studies,
    run_pipeline,
)
from mri_dataset_tool.domain.models.transformation import StudyReport
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, load_key
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader  # noqa: F401 (tests patch it)
from mri_dataset_tool.infrastructure.config.loader import load_config

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "stage3_bids.yaml"
DEFAULT_DATASET = REPO / "data" / "raw" / "bids_test_studies"


def is_discouraged_location(path: Path) -> bool:
    """True if *path* is on drive C: or under the system temporary directory."""
    resolved = path.resolve()
    return resolved.drive.upper() == "C:" or resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())


def _printer() -> tuple[Counter[str], Callable[[Path, Exception], None]]:
    errors: Counter[str] = Counter()

    def on_error(path: Path, error: Exception) -> None:  # path is never printed (PHI)
        errors[type(error).__name__] += 1
        print(f"  error {sum(errors.values())}: {type(error).__name__}")

    return errors, on_error


def run(pipeline: Pipeline, dataset_root: Path, output_dir: Path | None) -> tuple[list[StudyReport], Counter[str], int]:
    """Run *pipeline* over the BIDS studies of *dataset_root*; write results to *output_dir* if given.

    Returns the reports, the error count per exception type and the number of files written.
    """
    errors, on_error = _printer()
    reports, written = process_studies(pipeline, read_studies("bids", dataset_root, on_error), output_dir, on_error, "bids")
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
    if previous_outputs_exist(output_dir, manifest_path):
        print("Outputs of a previous run exist (study-*.nii.gz in the output directory or the manifest); remove them first.")
        return 1

    pipeline = pipeline_from_config(config)
    print("Running stage 3 BIDS pipeline...")
    errors, on_error = _printer()
    _, on_replay_error = _printer()
    try:
        result = run_pipeline(
            pipeline, config, "bids", dataset_root, output_dir, manifest_path, on_error, on_replay_error=on_replay_error
        )
    except StageFailed as failure:  # the reader or a write failed: its message or traceback may name a file
        print(f"Run failed: {failure.error_type}")
        return 1

    studies, failed = len(result.reports), result.failed
    print(f"Studies: {studies}  ok: {studies - failed}  failed in a step: {failed}  files written: {result.files_written}")
    print(f"Errors by type: {dict(sorted(errors.items())) or 'none'}")
    print(f"Manifest without source paths: {result.no_sources}  reproduced from manifest: {result.reproduced}")
    return 0 if result.no_sources and result.reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
