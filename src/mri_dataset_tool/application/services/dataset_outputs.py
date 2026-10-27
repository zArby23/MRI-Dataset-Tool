"""What the GUI exports step needs on top of ``write_ml_exports`` and ``report_dataset``: which outputs
already exist, a report folder that is new or empty (the same rule as the build output), and the
report warnings (codes and counts only)."""

import json
from collections.abc import Callable
from pathlib import Path

from mri_dataset_tool.application.services.dataset_build import is_new_or_empty_dir
from mri_dataset_tool.application.services.dataset_report import REPORT_WRITERS, report_dataset
from mri_dataset_tool.infrastructure.dataset.index import DATALIST_JSON, INDEX_CSV, SPLITS_JSON, SPLITS_TSV

ML_EXPORT_FILES = (INDEX_CSV, DATALIST_JSON, SPLITS_TSV, SPLITS_JSON)
REPORT_FILES = tuple(REPORT_WRITERS)
REPORT_JSON = "dataset_report.json"


def ml_exports_exist(dataset_root: Path) -> bool:
    """True if any ML export file is already in the dataset (``write_ml_exports`` would refuse)."""
    return any((dataset_root / name).exists() for name in ML_EXPORT_FILES)


def write_report(
    dataset_root: Path, report_dir: Path, on_error: Callable[[Path, Exception], None] | None = None
) -> tuple[list[str], dict[str, int]]:
    """``report_dataset`` into *report_dir*, which must be new or an empty folder (never mixed with other
    files; ``FileExistsError``) outside the dataset (``ValueError`` from ``report_dataset``). Returns
    the names of the files written and the report warnings (code → count)."""
    if not is_new_or_empty_dir(report_dir):
        raise FileExistsError("Report directory is not empty.")
    written = report_dataset(dataset_root, report_dir, on_error)
    return [path.name for path in written], report_warnings(report_dir)


def report_warnings(report_dir: Path) -> dict[str, int]:
    """The warnings of the written report (``dataset_report.json``): code → count."""
    summary = json.loads((report_dir / REPORT_JSON).read_text(encoding="utf-8"))
    return {item["code"]: item["count"] for item in summary["warnings"]}
