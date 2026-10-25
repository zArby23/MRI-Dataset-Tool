"""Stage 4 end to end: BIDS input → stage 3 pipeline → BIDS dataset, labels, ML exports, report.

Usage, from the repository root (the key is a secret of at least 32 characters):

    $env:MRI_ANON_KEY = "<secret>"          # PowerShell;  bash: export MRI_ANON_KEY=<secret>
    python scripts/run_stage4_dataset.py --output-dir E:/mri/stage4
    python scripts/run_stage4_dataset.py <dataset_root> --output-dir E:/mri/stage4 \
        --classes AD=Alzheimer CN=Control --corrections labels_fix.tsv --ratios 0.7 0.15 0.15 --seed 0

Studies are read lazily from <dataset_root> (default data/raw/bids_test_studies), processed
with --config (default config/stage3_bids.yaml; it must include the anonymize step, so the
dataset ids are pseudonyms) and written to <output-dir>/dataset; the report goes to
<output-dir>/report. With --classes a label template (every session unlabeled)
is written; --corrections (same columns as labels.tsv) then assigns labels and needs --classes.
Complete labels are finalized (finalize_labels) before the ML exports; incomplete ones skip the
ML exports with a warning (codes and counts) unless --allow-unfinalized. --output-dir must not exist; large runs should go to
E:/ (a warning is printed for C: or the temporary directory, the run is not blocked). The
console shows only exception types and counts, never paths or ids.
Exit codes: 0 ok, 1 previous output or a failed stage, 2 key or arguments.
"""

import argparse
import logging
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from mri_dataset_tool.application.services.dataset_build import (
    InvalidBuildInput,
    StageFailed,
    build_dataset,
    check_build_args,
    load_build_pipeline,
    parse_classes,  # noqa: F401 (tests use it from here)
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, load_key
from mri_dataset_tool.infrastructure.dataset.splits import DEFAULT_RATIOS, DEFAULT_SEED

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "stage3_bids.yaml"
DEFAULT_DATASET = REPO / "data" / "raw" / "bids_test_studies"


def is_discouraged_location(path: Path) -> bool:
    """True if *path* is on drive C: or under the system temporary directory."""
    resolved = path.resolve()
    return resolved.drive.upper() == "C:" or resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())


def _counter(label: str) -> tuple[Counter[str], Callable[[Path, Exception], None]]:
    """An ``on_error`` that counts by exception type and prints only the type (the path may be PHI)."""
    counts: Counter[str] = Counter()

    def on_error(path: Path, error: Exception) -> None:
        counts[type(error).__name__] += 1
        print(f"  {label} {sum(counts.values())}: {type(error).__name__}")

    return counts, on_error


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 4: export a labelled, split and reported BIDS dataset.")
    parser.add_argument("dataset_root", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory for the dataset and the report")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="run configuration (pipeline steps)")
    parser.add_argument("--classes", nargs="+", metavar="NAME[=DESCRIPTION]", help="label classes; writes a template")
    parser.add_argument("--corrections", type=Path, help="labels TSV to apply to the template (needs --classes)")
    parser.add_argument("--ratios", nargs=3, type=float, default=list(DEFAULT_RATIOS), metavar=("TRAIN", "VAL", "TEST"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--allow-unfinalized", action="store_true", help="write the ML exports even if the labels are incomplete"
    )
    return parser.parse_args(argv)


_MESSAGES = {
    "export": "Exporting the dataset (stage 3 pipeline)...",
    "exported": "Studies written: {studies}  series: {series}  participants: {participants}  errors: {errors}",
    "labels_skipped": "Labels: skipped (no --classes).",
    "label_template": "Label template written ({classes} classes).",
    "corrections_skipped": "Label corrections: skipped (no --corrections).",
    "corrections_applied": "Label corrections applied: {rows}",
    "labels_finalized": "Labels finalized ({labels} labels).",
    "ml_exports_skipped": "ML exports: skipped (labels incomplete; fix them or use --allow-unfinalized).",
    "ml_exports": "ML export files written: {files}",
    "report": "Report files written: {files}",
}


def _print_status(event: str, counts: dict[str, int]) -> None:
    if event == "labels_incomplete":
        print(f"WARNING LABELS_INCOMPLETE: {counts}")
    else:
        print(_MESSAGES[event].format(**counts))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)  # bad or missing arguments: argparse prints usage and exits with 2
    try:
        load_key()
    except ValueError:
        print(f"{KEY_ENV_VAR} is not set or is shorter than 32 characters; nothing was run.")
        return 2
    # Every message is fixed text: never a path, an id or an exception message.
    try:
        classes = check_build_args(
            args.dataset_root, args.output_dir, args.config, args.classes, args.corrections, args.ratios, args.seed
        )
    except InvalidBuildInput as error:
        print(error)
        return 2
    except FileExistsError as error:
        print(error)
        return 1
    output_dir = args.output_dir
    if is_discouraged_location(output_dir):
        print("WARNING: the output is on drive C: or in the temporary directory; large runs should go elsewhere (E:/).")

    try:
        config, pipeline = load_build_pipeline(args.config, REPO / "config")
    except InvalidBuildInput as error:
        print(error)
        return 2
    logging.basicConfig(level=config["logging"]["level"])
    # Separate counts: files the reader skips (e.g. git-annex pointers) are not export errors.
    skipped, on_skipped = _counter("input file skipped")
    errors, on_error = _counter("error")  # the same events as DatasetReport.errors
    report_errors, on_report_error = _counter("report read error")

    try:
        build_dataset(
            args.dataset_root, output_dir, pipeline, config,
            classes=classes, corrections=args.corrections, ratios=args.ratios, seed=args.seed,
            allow_unfinalized=args.allow_unfinalized,
            on_skipped=on_skipped, on_error=on_error, on_report_error=on_report_error, on_status=_print_status,
        )
    except StageFailed as failure:
        print(f"Run failed at {failure.stage}: {failure.error_type}")
        return 1

    print(f"Errors by type: {dict(sorted(errors.items())) or 'none'}")
    print(f"Input files skipped by the reader: {dict(sorted(skipped.items())) or 'none'}")
    print(f"Report read errors: {dict(sorted(report_errors.items())) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
