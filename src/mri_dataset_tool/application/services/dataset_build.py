"""Full dataset build: BIDS input → pipeline (with anonymize) → BIDS dataset, labels, ML exports, report.

Nothing here prints. Validation raises ``InvalidBuildInput`` (fixed message, safe to show) or
``FileExistsError`` before anything is created; progress goes to ``on_status(event, counts)``
(event names and counts only); a failed stage raises ``StageFailed`` (stage and exception type).
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.services.dataset import DatasetReport, export_dataset, write_ml_exports
from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.application.services.labels import (
    LabelReview,
    apply_label_corrections,
    dataset_pairs,
    finalize_labels,
    review_labels,
    write_label_template,
)
from mri_dataset_tool.application.services.pipeline_run import ErrorCallback, StageFailed, StatusCallback
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.config.loader import load_config
from mri_dataset_tool.infrastructure.dataset.bids_writer import TOOL_NAME
from mri_dataset_tool.infrastructure.dataset.labels import LabelTable
from mri_dataset_tool.infrastructure.dataset.splits import DEFAULT_RATIOS, DEFAULT_SEED, check_split_params

if TYPE_CHECKING:
    from mri_dataset_tool.application.services.dataset_ingest import IngestPlan


class InvalidBuildInput(ValueError):
    """An argument, the dataset or the config is invalid; the message is fixed text (no values)."""


@dataclass(frozen=True)
class DatasetBuildResult:
    exported: DatasetReport
    review: LabelReview | None  # None without classes
    ml_files: list[Path] | None  # None when skipped (labels incomplete)
    report_files: list[Path]


def is_exported_dataset(root: Path) -> bool:
    """True if *root* is a dataset written by this tool: its ``dataset_description.json`` (written by
    ``BIDSDatasetWriter.finalize``) names the tool in ``GeneratedBy``. A raw BIDS input does not, so the
    dataset commands never write label or ML files, with source ids, into an input."""
    try:
        description = json.loads((root / "dataset_description.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    generated_by = description.get("GeneratedBy") if isinstance(description, dict) else None
    return isinstance(generated_by, list) and any(
        isinstance(entry, dict) and entry.get("Name") == TOOL_NAME for entry in generated_by
    )


def parse_classes(items: Sequence[str]) -> dict[str, str]:
    """``NAME`` or ``NAME=description`` → class → description; a repeated name → ``ValueError``."""
    pairs = [item.partition("=")[::2] for item in items]
    classes = dict(pairs)
    if len(classes) != len(pairs):
        raise ValueError("Repeated class name.")
    return classes


def check_classes(items: Sequence[str]) -> dict[str, str]:
    """Parsed and valid label classes (``NAME[=description]`` items); else ``InvalidBuildInput``."""
    try:
        classes = parse_classes(items)
        LabelTable(classes)
    except ValueError:
        raise InvalidBuildInput("Invalid --classes.") from None
    return classes


def check_build_args(
    dataset_root: Path,
    output_dir: Path,
    config_path: Path,
    class_items: Sequence[str] | None = None,
    corrections: Path | None = None,
    ratios: Sequence[float] = DEFAULT_RATIOS,
    seed: int = DEFAULT_SEED,
) -> dict[str, str] | None:
    """Validate everything that needs no config; return the classes (``None`` without them).

    ``InvalidBuildInput`` for invalid arguments; ``FileExistsError`` if *output_dir* exists."""
    if not dataset_root.is_dir():
        raise InvalidBuildInput("Dataset directory not found.")
    if not config_path.is_file():
        raise InvalidBuildInput("Config file not found.")
    classes = check_classes(class_items) if class_items else None
    if corrections is not None and classes is None:
        raise InvalidBuildInput("--corrections needs --classes.")
    if corrections is not None and not corrections.is_file():
        raise InvalidBuildInput("Corrections file not found.")
    try:
        check_split_params(ratios, seed)
    except ValueError:
        raise InvalidBuildInput("Invalid --ratios.") from None
    if output_dir.resolve().is_relative_to(dataset_root.resolve()):  # never create anything in the input
        raise InvalidBuildInput("Output directory must be outside the dataset directory.")
    if output_dir.exists():
        raise FileExistsError("Output directory already exists; choose a new one.")
    return classes


def load_build_pipeline(config_path: Path, config_dir: Path) -> tuple[dict[str, Any], Pipeline]:
    """Load the run config and its pipeline, which must include ``anonymize``; else ``InvalidBuildInput``."""
    try:
        config = load_config(config_path, config_dir=config_dir)
        pipeline = pipeline_from_config(config)
    except Exception as error:
        raise InvalidBuildInput(f"Invalid config: {type(error).__name__}") from None
    if not any(step.name == "anonymize" for step in pipeline.steps):  # without it the dataset ids would be the source ones
        raise InvalidBuildInput("The pipeline must include the anonymize step.")
    return config, pipeline


def label_defects(review: LabelReview) -> dict[str, int]:
    """Non-zero defect counts of an incomplete review, by fixed code."""
    defects = {
        "UNLABELED": len(review.unlabeled),
        "UNKNOWN_CLASS": len(review.unknown_class),
        "DUPLICATED": len(review.duplicated),
        "MISSING": len(review.missing),
        "NOT_IN_DATASET": review.not_in_dataset,
        "INVALID_IDS": review.invalid_ids,
    }
    return {code: n for code, n in defects.items() if n}


def build_dataset(
    dataset_root: Path,
    output_dir: Path,
    pipeline: Pipeline,
    config: dict[str, Any],
    *,
    classes: dict[str, str] | None = None,
    corrections: Path | None = None,
    ratios: Sequence[float] = DEFAULT_RATIOS,
    seed: int = DEFAULT_SEED,
    allow_unfinalized: bool = False,
    on_skipped: ErrorCallback | None = None,
    on_error: ErrorCallback | None = None,
    on_report_error: ErrorCallback | None = None,
    on_status: StatusCallback | None = None,
    ingest: "IngestPlan | None" = None,
) -> DatasetBuildResult:
    """Write ``<output_dir>/dataset`` and ``<output_dir>/report`` (call ``check_build_args`` and
    ``load_build_pipeline`` first).

    Files the reader skips go to ``on_skipped``, study errors to ``on_error`` (the same events as
    ``DatasetReport.errors``) and report read errors to ``on_report_error``. Complete labels are
    finalized before the ML exports; incomplete ones skip them unless *allow_unfinalized*.
    Status events, in order: ``export``, ``exported``, then ``labels_skipped`` or
    ``label_template``, ``corrections_skipped`` or ``corrections_applied``, ``labels_finalized``
    or ``labels_incomplete`` (defect counts), ``ml_exports_skipped`` or ``ml_exports``, ``report``.

    With *ingest* (``dataset_ingest.plan_ingest`` for DICOM or loose NIfTI) the studies come from
    ``iter_ingested_studies`` instead of the BIDS reader (series that fail to build go to
    ``on_skipped``); ``ingested`` (skipped series by code, unused mapping rows) follows ``exported``,
    no exported study fails the export stage, and the mapping labels are applied to the template
    (``mapping_labels_applied``) before ``--corrections``.
    """
    status = on_status or (lambda event, counts: None)
    dataset, report_dir = output_dir / "dataset", output_dir / "report"
    stage, review, ml_files, labels_open = "export", None, None, False
    try:
        status("export", {})
        output_dir.mkdir(parents=True)
        if ingest is None:
            studies = BIDSBatchReader().iter_studies(dataset_root, on_error=on_skipped, lazy=True)
        else:
            from mri_dataset_tool.application.services.dataset_ingest import iter_ingested_studies  # imports this module

            studies = iter_ingested_studies(ingest, on_skipped)
        exported = export_dataset(studies, dataset, on_error, pipeline=pipeline, config=config, source_dir=dataset_root)
        status("exported", {
            "studies": exported.studies_written, "series": exported.series_written,
            "participants": exported.participants, "errors": exported.errors,
        })
        if ingest is not None:
            status("ingested", {**dict(sorted(ingest.skipped.items())), "MAPPING_UNUSED": ingest.mapping_unused})
            if exported.studies_written == 0:
                raise ValueError("No studies were exported.")

        stage = "labels"
        if classes is None:
            status("labels_skipped", {})
        else:
            write_label_template(dataset, classes)
            status("label_template", {"classes": len(classes)})
            if ingest is not None and ingest.labels:
                status("mapping_labels_applied", {"rows": _apply_mapping_labels(dataset, output_dir, ingest.labels)})
            if corrections is None:
                status("corrections_skipped", {})
            else:
                status("corrections_applied", {"rows": apply_label_corrections(dataset, corrections)})
            review = review_labels(dataset)
            if review.is_complete:
                finalize_labels(dataset)
                status("labels_finalized", {"labels": review.labeled})
            else:
                status("labels_incomplete", label_defects(review))
                labels_open = True

        stage = "ml exports"
        if labels_open and not allow_unfinalized:
            status("ml_exports_skipped", {})
        else:
            ml_files = write_ml_exports(dataset, ratios, seed, allow_unfinalized=allow_unfinalized)
            status("ml_exports", {"files": len(ml_files)})

        stage = "report"
        report_files = report_dataset(dataset, report_dir, on_report_error)
        status("report", {"files": len(report_files)})
    except Exception as error:  # its message or traceback may name a file (sub-<id>)
        raise StageFailed(stage, error) from error
    return DatasetBuildResult(exported, review, ml_files, report_files)


def _apply_mapping_labels(dataset: Path, output_dir: Path, labels: dict[tuple[str, str | None], str]) -> int:
    """Apply the mapping labels of the exported pairs with ``apply_label_corrections`` (all or nothing,
    logged in ``labels_changes.tsv``). Pairs whose study was not exported are left out. The temporary
    table holds only pseudonymized ids and is removed."""
    present = set(dataset_pairs(dataset))
    rows = ["participant_id\tsession_id\tlabel"] + [
        f"sub-{subject}\t{'' if session is None else 'ses-' + session}\t{label}"
        for (subject, session), label in sorted(labels.items(), key=lambda item: (item[0][0], item[0][1] or ""))
        if (subject, session) in present
    ]
    table = output_dir / ".mapping_labels.tsv"
    try:
        table.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return apply_label_corrections(dataset, table)
    finally:
        table.unlink(missing_ok=True)
