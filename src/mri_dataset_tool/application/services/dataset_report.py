"""Statistical report of a written BIDS dataset (RF14, RF15, RF16).

Reads what was actually exported (``BIDSBatchReader`` in lazy mode, one study at a time),
the labels (``labels.tsv``/``labels.json``, if present) and the steps of
``code/run_manifest.json``, and writes ``dataset_report.{json,md,xml,xlsx}``.
"""

from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from mri_dataset_tool.application.pipeline.manifest import RunManifest
from mri_dataset_tool.application.services.summary import summarize_study
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.dataset.exporters import write_json, write_markdown, write_xlsx, write_xml
from mri_dataset_tool.infrastructure.dataset.labels import LABELS_JSON, LABELS_TSV, read_labels
from mri_dataset_tool.infrastructure.dataset.report import StudyEntry, build_dataset_summary
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

MANIFEST_PATH = Path("code") / "run_manifest.json"
REPORT_WRITERS = {
    "dataset_report.json": write_json,
    "dataset_report.md": write_markdown,
    "dataset_report.xml": write_xml,
    "dataset_report.xlsx": write_xlsx,
}


def report_dataset(
    dataset_root: Path, output_dir: Path, on_error: Callable[[Path, Exception], None] | None = None
) -> list[Path]:
    """Write the four report files into *output_dir* and return their paths.

    *output_dir* must be outside the dataset (it would otherwise become part of it) and is
    created if missing. If any report file already exists, ``FileExistsError`` before
    reading anything. A study, label table or manifest that cannot be read goes to
    ``on_error`` and the report is built from the rest, with a warning code and count.
    """
    if not dataset_root.exists():
        raise FileNotFoundError("Dataset directory does not exist.")
    if not dataset_root.is_dir():
        raise NotADirectoryError("Dataset path is not a directory.")
    if output_dir.resolve().is_relative_to(dataset_root.resolve()):
        raise ValueError("Report directory must be outside the dataset.")
    paths = [output_dir / name for name in REPORT_WRITERS]
    if any(path.exists() for path in paths):
        raise FileExistsError("Report file already exists.")

    errors: Counter[str] = Counter()

    def report_error(code: str, path: Path, error: Exception) -> None:
        errors[code] += 1
        if on_error is not None:
            try:
                on_error(path, error)
            except Exception as callback_error:
                logger.warning("on_error callback failed (%s)", type(callback_error).__name__)

    labels, classes = None, None
    if (dataset_root / LABELS_TSV).exists() or (dataset_root / LABELS_JSON).exists():
        try:
            table = read_labels(dataset_root)
            labels, classes = table.labels, list(table.classes)
        except Exception as error:
            report_error("LABELS_UNREADABLE", dataset_root / LABELS_TSV, error)

    pipeline = None
    if (manifest_path := dataset_root / MANIFEST_PATH).exists():
        try:
            pipeline = _pipeline_summary(RunManifest.from_json(manifest_path.read_text(encoding="utf-8")))
        except Exception as error:
            report_error("MANIFEST_UNREADABLE", manifest_path, error)

    entries = _entries(dataset_root, lambda path, error: report_error("UNREADABLE_FILES", path, error))
    summary = build_dataset_summary(entries, labels, classes)
    summary["pipeline"] = pipeline
    warnings = Counter({w["code"]: w["count"] for w in summary["warnings"]}) + errors
    summary["warnings"] = [{"code": code, "count": warnings[code]} for code in sorted(warnings)]

    written: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        for path, writer in zip(paths, REPORT_WRITERS.values()):
            written.append(writer(summary, path))
    except BaseException:
        for path in written:  # all four files or none
            path.unlink(missing_ok=True)
        raise
    logger.info("Dataset report written (%d studies, %d series)", summary["studies"], summary["series"])
    return written


def _entries(root: Path, on_error: Callable[[Path, Exception], None]) -> Iterator[StudyEntry]:
    """One summarized study at a time; a volume that fails to read skips that study (RF16)."""
    for study in BIDSBatchReader().iter_studies(root, on_error, lazy=True):
        try:
            entry = (study.subject_id, study.session_id, summarize_study(study))
        except Exception as error:
            files = study.series[0].files if study.series else []
            on_error(files[0] if files else Path(), error)
            continue
        finally:
            del study  # released before the next one is read
        yield entry
        del entry


def _pipeline_summary(manifest: RunManifest) -> dict[str, Any]:
    """Steps as executed, with per-step counts aggregated from the study reports (no outputs values)."""
    steps = []
    for position, step in enumerate(manifest.steps):
        records = [report.steps[position] for report in manifest.reports if len(report.steps) > position]
        failed = [record for record in records if record.status == "failed"]
        steps.append({
            "name": step["name"],
            "version": step["version"],
            "params": step["params"],
            "studies_ok": len(records) - len(failed),
            "studies_failed": len(failed),
            "error_types": dict(sorted(Counter(record.error_type for record in failed).items())),
            "series_transformed": sum(len(record.outputs.get("series", [])) for record in records),
        })
    return {"studies": len(manifest.reports), "steps": steps}
