"""Stage 4 end to end (E2): BIDS input → stage 3 pipeline → BIDS dataset, labels, ML exports, report.

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
from collections.abc import Sequence
from pathlib import Path

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.services.dataset import export_dataset, write_ml_exports
from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.application.services.labels import (
    apply_label_corrections,
    finalize_labels,
    review_labels,
    write_label_template,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, load_key
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.dataset.labels import LabelTable
from mri_dataset_tool.infrastructure.dataset.splits import DEFAULT_RATIOS, DEFAULT_SEED, check_split_params

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "stage3_bids.yaml"
DEFAULT_DATASET = REPO / "data" / "raw" / "bids_test_studies"


def is_discouraged_location(path: Path) -> bool:
    """True if *path* is on drive C: or under the system temporary directory."""
    resolved = path.resolve()
    return resolved.drive.upper() == "C:" or resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())


def parse_classes(items: Sequence[str]) -> dict[str, str]:
    """``NAME`` or ``NAME=description`` → class → description."""
    return {name: description for name, _, description in (item.partition("=") for item in items)}


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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)  # bad or missing arguments: argparse prints usage and exits with 2
    try:
        load_key()
    except ValueError:
        print(f"{KEY_ENV_VAR} is not set or is shorter than 32 characters; nothing was run.")
        return 2
    # Every message is fixed text: never a path, an id or an exception message.
    if not args.dataset_root.is_dir():
        print("Dataset directory not found.")
        return 2
    if not args.config.is_file():
        print("Config file not found.")
        return 2
    classes = None
    if args.classes:
        classes = parse_classes(args.classes)
        try:
            LabelTable(classes)
        except ValueError:
            print("Invalid --classes.")
            return 2
    if args.corrections is not None and classes is None:
        print("--corrections needs --classes.")
        return 2
    if args.corrections is not None and not args.corrections.is_file():
        print("Corrections file not found.")
        return 2
    try:
        check_split_params(args.ratios, args.seed)
    except ValueError:
        print("Invalid --ratios.")
        return 2
    output_dir = args.output_dir
    if output_dir.resolve().is_relative_to(args.dataset_root.resolve()):  # never create anything in the input
        print("Output directory must be outside the dataset directory.")
        return 2
    if output_dir.exists():
        print("Output directory already exists; choose a new one.")
        return 1
    if is_discouraged_location(output_dir):
        print("WARNING: the output is on drive C: or in the temporary directory; large runs should go elsewhere (E:/).")

    try:
        config = load_config(args.config, config_dir=REPO / "config")
        pipeline = pipeline_from_config(config)
    except Exception as error:
        print(f"Invalid config: {type(error).__name__}")
        return 2
    if not any(step.name == "anonymize" for step in pipeline.steps):  # ids would be the source ones (QA4-01)
        print("The pipeline must include the anonymize step.")
        return 2
    logging.basicConfig(level=config["logging"]["level"])
    dataset, report_dir = output_dir / "dataset", output_dir / "report"
    errors: Counter[str] = Counter()

    def on_error(path: Path, error: Exception) -> None:  # path is never printed (PHI)
        errors[type(error).__name__] += 1
        print(f"  error {sum(errors.values())}: {type(error).__name__}")

    stage, labels_open = "export", False
    try:
        print("Exporting the dataset (stage 3 pipeline)...")
        output_dir.mkdir(parents=True)
        studies = BIDSBatchReader().iter_studies(args.dataset_root, on_error=on_error, lazy=True)
        exported = export_dataset(
            studies, dataset, on_error, pipeline=pipeline, config=config, source_dir=args.dataset_root
        )
        print(f"Studies written: {exported.studies_written}  series: {exported.series_written}  "
              f"participants: {exported.participants}  errors: {exported.errors}")

        stage = "labels"
        if classes is None:
            print("Labels: skipped (no --classes).")
        else:
            write_label_template(dataset, classes)
            print(f"Label template written ({len(classes)} classes).")
            if args.corrections is None:
                print("Label corrections: skipped (no --corrections).")
            else:
                print(f"Label corrections applied: {apply_label_corrections(dataset, args.corrections)}")
            review = review_labels(dataset)
            if review.is_complete:
                finalize_labels(dataset)
                print(f"Labels finalized ({review.labeled} labels).")
            else:
                defects = {
                    "UNLABELED": len(review.unlabeled),
                    "UNKNOWN_CLASS": len(review.unknown_class),
                    "DUPLICATED": len(review.duplicated),
                    "MISSING": len(review.missing),
                    "NOT_IN_DATASET": review.not_in_dataset,
                    "INVALID_IDS": review.invalid_ids,
                }
                print(f"WARNING LABELS_INCOMPLETE: { {code: n for code, n in defects.items() if n} }")
                labels_open = True

        stage = "ml exports"
        if labels_open and not args.allow_unfinalized:
            print("ML exports: skipped (labels incomplete; fix them or use --allow-unfinalized).")
        else:
            written = write_ml_exports(dataset, args.ratios, args.seed, allow_unfinalized=args.allow_unfinalized)
            print(f"ML export files written: {len(written)}")

        stage = "report"
        print(f"Report files written: {len(report_dataset(dataset, report_dir, on_error))}")
    except Exception as error:  # its message or traceback may name a file (sub-<id>)
        print(f"Run failed at {stage}: {type(error).__name__}")
        return 1

    print(f"Errors by type: {dict(sorted(errors.items())) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
