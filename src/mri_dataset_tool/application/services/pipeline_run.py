"""Run a configured pipeline over NIfTI or BIDS studies: float32 NIfTI outputs, manifest, replay check.

Studies are read lazily and processed one at a time (RNF02). Nothing here prints: progress goes
to ``on_status(stage, counts)`` (stage names and counts only, never paths or ids) and failures of
a whole stage raise ``StageFailed`` (stage and exception type only).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_manifest
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StudyReport
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.nifti.writer import NIfTIWriter
from mri_dataset_tool.infrastructure.processing.arrays import load_array

INPUT_FORMATS = ("nifti", "bids")

ErrorCallback = Callable[[Path, Exception], None]
StatusCallback = Callable[[str, dict[str, int]], None]


class StageFailed(Exception):
    """A whole stage failed; the cause is chained. The message holds only the stage name."""

    def __init__(self, stage: str, error: Exception) -> None:
        super().__init__(f"Stage failed: {stage}.")
        self.stage = stage
        self.error_type = type(error).__name__


@dataclass(frozen=True)
class PipelineRunResult:
    reports: list[StudyReport]
    files_written: int
    no_sources: bool  # the manifest names neither the input root nor a sub- id
    reproduced: bool | None  # None when the replay was not requested

    @property
    def failed(self) -> int:
        return sum(1 for report in self.reports if report.steps and report.steps[-1].status == "failed")


def output_name(input_format: str, index: int, series_index: int, series_count: int) -> str:
    """``study-NNN[_series-MMM].nii.gz``: positions in the input order, never source names.

    NIfTI inputs have one series, so the series suffix is added only when there are several;
    BIDS sessions always carry it."""
    if input_format == "nifti" and series_count == 1:
        return f"study-{index:03d}.nii.gz"
    return f"study-{index:03d}_series-{series_index:03d}.nii.gz"


def previous_outputs_exist(output_dir: Path, manifest_path: Path) -> bool:
    return manifest_path.exists() or any(output_dir.glob("study-*.nii.gz"))


def read_studies(input_format: str, root: Path, on_error: ErrorCallback | None) -> Iterable[MRIStudy]:
    """Lazy studies of a NIfTI directory or a BIDS dataset (validates *root* immediately)."""
    if input_format == "nifti":
        return NIfTIBatchReader().iter_studies(root, on_error=on_error, lazy=True)
    if input_format == "bids":
        return BIDSBatchReader().iter_studies(root, on_error=on_error, lazy=True)
    raise ValueError("Unsupported input format.")


def process_studies(
    pipeline: Pipeline,
    studies: Iterable[MRIStudy],
    output_dir: Path | None,
    on_error: ErrorCallback,
    input_format: str,
) -> tuple[list[StudyReport], int]:
    """Run *pipeline*; write each processed series as float32 to *output_dir* if given.

    A failed write is reported through ``on_error`` like any other error and the batch continues.
    Returns the reports and the number of files written."""
    written = 0
    writer = NIfTIWriter()

    def on_result(study: MRIStudy, report: StudyReport) -> None:
        nonlocal written
        if output_dir is None:
            return
        for series_index, series in enumerate(study.series, start=1):
            if series.volume is None:
                continue
            target = output_dir / output_name(input_format, report.index, series_index, len(study.series))
            try:
                writer.write(replace(series, volume=load_array(series.volume, np.float32)), target, overwrite=False)
                written += 1
            except Exception as error:  # a failed write is reported like any other error; the batch continues
                on_error(target, error)

    reports = pipeline.run(studies, on_result=on_result, on_error=on_error)
    return reports, written


def run_pipeline(
    pipeline: Pipeline,
    config: dict[str, Any],
    input_format: str,
    input_root: Path,
    output_dir: Path,
    manifest_path: Path,
    on_error: ErrorCallback,
    *,
    verify: bool = True,
    on_replay_error: ErrorCallback | None = None,
    on_status: StatusCallback | None = None,
) -> PipelineRunResult:
    """Process, write the manifest, check it has no source paths and, with *verify*, rebuild the
    pipeline from the saved manifest and run it again (without writing) to compare.

    Studies that fail are reported through ``on_error`` (RF16); the replay reports through
    ``on_replay_error``. Any other failure raises ``StageFailed`` (``process``, ``manifest`` or
    ``verify``). The caller checks ``previous_outputs_exist`` first: nothing is overwritten.
    """
    status = on_status or (lambda stage, counts: None)
    stage = "process"
    try:
        status(stage, {})
        output_dir.mkdir(parents=True, exist_ok=True)
        reports, written = process_studies(
            pipeline, read_studies(input_format, input_root, on_error), output_dir, on_error, input_format
        )

        stage = "manifest"
        status(stage, {"studies": len(reports), "files_written": written})
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        RunManifest.from_run(config, pipeline, reports).write(manifest_path)
        text = manifest_path.read_text(encoding="utf-8")
        root = input_root.resolve()
        no_sources = all(p not in text for p in (str(root), root.as_posix(), "sub-"))

        reproduced = None
        if verify:
            stage = "verify"
            status(stage, {})
            saved = RunManifest.from_json(text)
            replay = pipeline_from_manifest(saved)
            replay_reports, _ = process_studies(
                replay,
                read_studies(input_format, input_root, on_replay_error),
                None,
                on_replay_error or (lambda path, error: None),
                input_format,
            )
            reproduced = RunManifest.from_run(saved.config, replay, replay_reports) == saved
    except Exception as error:  # its message or traceback may name a file (sub-<id>)
        raise StageFailed(stage, error) from error
    return PipelineRunResult(reports, written, no_sources, reproduced)
