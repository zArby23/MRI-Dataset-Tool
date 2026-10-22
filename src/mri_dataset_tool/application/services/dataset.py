"""Export processed studies as a BIDS dataset (RF10, RF13, RF15, RF16)."""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mri_dataset_tool.application.pipeline.manifest import RunManifest
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.services.labels import label_fingerprint
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.dataset.bids_writer import BIDSDatasetWriter
from mri_dataset_tool.infrastructure.dataset.index import scan_images, write_ml_files
from mri_dataset_tool.infrastructure.dataset.labels import FINAL_JSON, LABELS_JSON, LABELS_TSV, LabelTable, read_labels
from mri_dataset_tool.infrastructure.dataset.splits import (
    DEFAULT_RATIOS,
    DEFAULT_SEED,
    assign_splits,
    check_split_params,
    participant_strata,
)
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DatasetReport:
    """Counts only: never ids, paths or values. ``errors`` = calls to ``on_error``."""

    studies_written: int
    series_written: int
    participants: int
    errors: int


def export_dataset(
    studies: Iterable[MRIStudy],
    root: Path,
    on_error: Callable[[Path, Exception], None] | None = None,
    *,
    pipeline: Pipeline | None = None,
    config: dict[str, Any] | None = None,
    source_dir: Path | None = None,
) -> DatasetReport:
    """Write *studies* (consumed lazily, one alive at a time) as a BIDS dataset under *root*.

    With *pipeline*, each study is processed first and the run manifest (built with *config*)
    is written to ``code/run_manifest.json`` without source paths. A study or series that
    fails goes to ``on_error`` and the batch continues. *root* must not exist; with
    *source_dir*, a *root* inside it (or equal) → ``ValueError`` before anything is created.
    """
    if source_dir is not None and root.resolve().is_relative_to(source_dir.resolve()):
        raise ValueError("Output directory must be outside the input directory.")
    writer = BIDSDatasetWriter(root)
    studies_written = series_written = errors = 0

    def report_error(path: Path, error: Exception) -> None:
        nonlocal errors
        errors += 1
        if on_error is not None:
            try:
                on_error(path, error)
            except Exception as callback_error:
                logger.warning("on_error callback failed (%s)", type(callback_error).__name__)

    def add(study: MRIStudy, *_: Any) -> None:
        nonlocal studies_written, series_written
        try:
            written = writer.add_study(study, report_error)
        except Exception as error:
            logger.warning("Skipping study (%s)", type(error).__name__)
            report_error(Path(), error)
            return
        studies_written += bool(written)
        series_written += len(written)

    manifest_json = None
    if pipeline is None:
        for study in studies:
            add(study)
            del study  # don't hold it while the next one is read
    else:
        reports = pipeline.run(studies, on_result=add, on_error=report_error)
        # the dataset copy never carries input paths, even without an anonymize step (RNF07)
        reports = [replace(report, source_path=None) for report in reports]
        # report.path is a local path (often under the user's home): kept out of the dataset copy
        exported_config = {key: value for key, value in (config or {}).items() if key != "report"}
        manifest_json = RunManifest.from_run(exported_config, pipeline, reports).to_json()

    writer.finalize(manifest_json)
    result = DatasetReport(studies_written, series_written, len(writer.participants), errors)
    logger.info("Exported %d studies (%d series). Errors: %d.", studies_written, series_written, errors)
    return result


def write_ml_exports(
    root: Path, ratios: Any = DEFAULT_RATIOS, seed: Any = DEFAULT_SEED, *, allow_unfinalized: bool = False
) -> list[Path]:
    """Write ``dataset_index.csv``, ``datalist.json``, ``splits.tsv`` and ``splits.json`` for the
    BIDS dataset at *root* (RF13). Splits are by participant, stratified when ``labels.tsv`` exists.

    Reads only file names and the label table, never volumes. Invalid ratios/seed, a dataset
    without images or with files outside the layout → ``ValueError``; existing exports → ``FileExistsError``.
    With any label file (``labels.tsv``, ``labels.json``, ``labels_final.json``) the table is read
    (a missing file → ``FileNotFoundError``) and the labels must be closed (``labels_final.json`` whose ``sha256`` matches the
    current table) unless *allow_unfinalized* is true; otherwise
    ``ValueError("Labels are not finalized.")`` before writing anything. ``splits.json`` records it.
    """
    weights = check_split_params(ratios, seed)
    if not root.exists():
        raise FileNotFoundError("Dataset directory not found.")
    if not root.is_dir():
        raise NotADirectoryError("Dataset path is not a directory.")
    labels, finalized = None, None
    # any label file present means a labelled dataset: a lost labels.tsv must not export unlabelled
    if any((root / name).exists() for name in (LABELS_TSV, LABELS_JSON, FINAL_JSON)):
        labels = read_labels(root)  # a missing file → FileNotFoundError with a fixed message
        finalized = _labels_finalized(root, labels)
        if not finalized and not allow_unfinalized:
            raise ValueError("Labels are not finalized.")
    entries = scan_images(root)
    strata, unlabeled = participant_strata(
        ((entry.participant, entry.session) for entry in entries), None if labels is None else labels.labels
    )
    # every participant unlabeled: nothing to split, all are listed apart
    assignment, warnings = assign_splits(strata, weights, seed) if strata else ({}, [])
    written = write_ml_files(root, entries, labels, assignment, unlabeled, warnings, weights, seed, finalized)
    logger.info("Wrote ML exports: %d images, %d participants split, %d unlabeled.", len(entries), len(assignment), len(unlabeled))
    return written


def _labels_finalized(root: Path, labels: LabelTable) -> bool:
    """True if ``labels_final.json`` exists and its fingerprint matches *labels*."""
    try:
        recorded = json.loads((root / FINAL_JSON).read_text(encoding="utf-8"))["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return False  # missing or unreadable closure: not finalized
    return recorded == label_fingerprint(labels)
