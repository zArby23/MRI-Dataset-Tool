import copy
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from mri_dataset_tool.application.pipeline.step import ProcessingStep
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StepRecord, StudyReport
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class Pipeline:
    """Apply processing steps in order, one study at a time (RF15, RF16, RNF02)."""

    def __init__(self, steps: Sequence[ProcessingStep]) -> None:
        self.steps = list(steps)

    def run(
        self,
        studies: Iterable[MRIStudy],
        on_result: Callable[[MRIStudy, StudyReport], None],
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> list[StudyReport]:
        """Run every step over each study of *studies*, consumed lazily.

        A processed study is handed to ``on_result(study, report)`` and released before
        the next one is read, so only one study is in memory at a time. When a step
        raises, the following steps are skipped for that study, ``on_error(path, error)``
        is called with the study's first file and the batch continues. Returns one
        ``StudyReport`` per study (successful and failed), in input order; reports hold
        paths, step names and exception type names, never exception messages.

        If ``on_error`` keeps the exception, its ``__traceback__`` keeps the failing
        study (and its volume) alive; keep only what is needed, e.g. ``type(error)``.
        """
        reports: list[StudyReport] = []
        failed_count = 0

        # no enumerate(): its cached result tuple keeps the previous study alive while the next is read
        index = 0
        for study in studies:
            index += 1
            source = study.series[0].files[0] if study.series and study.series[0].files else None
            records: list[StepRecord] = []
            current: MRIStudy | None = study
            for step in self.steps:
                try:
                    current = step.apply(current)
                except Exception as error:  # per-study boundary: any failure must not stop the batch
                    records.append(
                        StepRecord(step.name, step.version, copy.deepcopy(step.params), "failed", type(error).__name__)
                    )
                    current = None
                    failed_count += 1
                    logger.warning("Skipping study that failed in a processing step (%s)", type(error).__name__)
                    # shortcut: a study without files reports Path(); upgrade if such sources appear
                    _call_safely("on_error", on_error, source or Path(), error)
                    break
                records.append(StepRecord(step.name, step.version, copy.deepcopy(step.params), "ok"))

            report = StudyReport(index, str(source) if source is not None else None, records)
            reports.append(report)
            if current is not None:
                _call_safely("on_result", on_result, current, report)
            del study, current  # release before reading the next study (RNF02)

        logger.info("Pipeline finished: %d studies, %d failed", len(reports), failed_count)
        return reports


def _call_safely(label: str, callback: Callable[..., None] | None, *args: Any) -> None:
    if callback is None:
        return
    try:
        callback(*args)
    except Exception as callback_error:
        logger.warning("%s callback failed (%s)", label, type(callback_error).__name__)
