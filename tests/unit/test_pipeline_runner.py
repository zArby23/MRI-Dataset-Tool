import json
import logging
import weakref
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StepRecord, StudyReport


@dataclass(frozen=True)
class AddStep:
    amount: float = 1.0
    name: ClassVar[str] = "test.add"
    version: ClassVar[str] = "1"

    @property
    def params(self) -> dict[str, Any]:
        return {"amount": self.amount}

    def apply(self, study: MRIStudy) -> MRIStudy:
        return replace(study, series=[replace(s, volume=s.volume + self.amount) for s in study.series])


@dataclass(frozen=True)
class FailOnSubjectStep:
    subject_id: str
    name: ClassVar[str] = "test.fail"
    version: ClassVar[str] = "2"

    @property
    def params(self) -> dict[str, Any]:
        return {"subject_id": self.subject_id}

    def apply(self, study: MRIStudy) -> MRIStudy:
        if study.subject_id == self.subject_id:
            raise ValueError("PatientName=SECRET leaked into the message")
        return study


@dataclass
class TrackingStep:
    """Keeps weak references to every input it sees."""

    seen: list[weakref.ref] = field(default_factory=list)
    name: ClassVar[str] = "test.track"
    version: ClassVar[str] = "1"
    params: ClassVar[dict[str, Any]] = {}

    def apply(self, study: MRIStudy) -> MRIStudy:
        self.seen.append(weakref.ref(study))
        return replace(study)


def _study(subject: str, tmp_path: Path) -> MRIStudy:
    series = MRISeries(
        series_uid=f"1.2.SECRET.{subject}",
        files=[tmp_path / f"sub-SECRET{subject}_T1w.nii.gz"],
        volume=np.zeros((2, 2, 2)),
    )
    return MRIStudy(study_uid=f"1.2.SECRET.{subject}", series=[series], subject_id=subject)


def test_failure_in_second_study_is_reported_and_batch_continues(tmp_path: Path) -> None:
    studies = [_study(s, tmp_path) for s in ("01", "02", "03")]
    results: list[tuple[MRIStudy, StudyReport]] = []
    errors: list[tuple[Path, Exception]] = []
    pipeline = Pipeline([AddStep(2.0), FailOnSubjectStep("02"), AddStep(1.0)])

    reports = pipeline.run(studies, lambda s, r: results.append((s, r)), lambda p, e: errors.append((p, e)))

    assert [r.index for _, r in results] == [1, 3]
    assert all(np.all(s.series[0].volume == 3.0) for s, _ in results)
    assert np.all(studies[0].series[0].volume == 0.0)  # input not mutated
    assert len(errors) == 1
    assert errors[0][0] == studies[1].series[0].files[0]
    assert isinstance(errors[0][1], ValueError)

    assert [r.index for r in reports] == [1, 2, 3]
    assert reports[1] == StudyReport(
        index=2,
        source_path=str(studies[1].series[0].files[0]),
        steps=[
            StepRecord("test.add", "1", {"amount": 2.0}, "ok"),
            StepRecord("test.fail", "2", {"subject_id": "02"}, "failed", "ValueError"),
        ],
    )
    assert [rec.status for rec in reports[0].steps] == ["ok", "ok", "ok"]
    assert results[0][1] is reports[0]


def test_report_never_contains_exception_message(tmp_path: Path) -> None:
    reports = Pipeline([FailOnSubjectStep("01")]).run([_study("01", tmp_path)], lambda s, r: None)
    assert "leaked" not in json.dumps([r.to_dict() for r in reports])


def test_raising_callbacks_are_caught_and_batch_continues(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    calls: list[str] = []

    def on_result(study: MRIStudy, report: StudyReport) -> None:
        calls.append("result")
        raise RuntimeError("SECRET in on_result")

    def on_error(path: Path, error: Exception) -> None:
        calls.append("error")
        raise KeyError("SECRET in on_error")

    studies = [_study(s, tmp_path) for s in ("01", "02", "03")]
    with caplog.at_level(logging.WARNING):
        reports = Pipeline([FailOnSubjectStep("02")]).run(studies, on_result, on_error)

    assert calls == ["result", "error", "result"]
    assert len(reports) == 3
    assert "on_result callback failed (RuntimeError)" in caplog.text
    assert "on_error callback failed (KeyError)" in caplog.text
    assert "SECRET" not in caplog.text


def test_streaming_is_lazy_and_releases_each_study(tmp_path: Path) -> None:
    tracker = TrackingStep()
    consumed = 0
    output_refs: list[weakref.ref] = []

    def source() -> Iterator[MRIStudy]:
        nonlocal consumed
        for subject in ("01", "02", "03"):
            # every study handed out before this one must already be released
            assert all(ref() is None for ref in tracker.seen + output_refs)
            consumed += 1
            yield _study(subject, tmp_path)

    def on_result(study: MRIStudy, report: StudyReport) -> None:
        assert consumed == report.index  # the next study was not read yet
        output_refs.append(weakref.ref(study))

    reports = Pipeline([tracker]).run(source(), on_result)

    assert len(reports) == 3
    assert all(ref() is None for ref in tracker.seen + output_refs)


def test_logs_have_no_paths_or_uids(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    studies = [_study(s, tmp_path) for s in ("01", "02")]
    with caplog.at_level(logging.DEBUG):
        Pipeline([AddStep(), FailOnSubjectStep("02")]).run(studies, lambda s, r: None, lambda p, e: None)

    assert "SECRET" not in caplog.text
    assert str(tmp_path) not in caplog.text
    assert "Pipeline finished: 2 studies, 1 failed" in caplog.text


def test_study_without_files_reports_no_source_path() -> None:
    errors: list[Path] = []
    study = MRIStudy(study_uid=None, series=[], subject_id="01")

    reports = Pipeline([FailOnSubjectStep("01")]).run([study], lambda s, r: None, lambda p, e: errors.append(p))

    assert reports[0].source_path is None
    assert errors == [Path()]


def test_empty_pipeline_passes_studies_through(tmp_path: Path) -> None:
    results: list[StudyReport] = []
    reports = Pipeline([]).run([_study("01", tmp_path)], lambda s, r: results.append(r))
    assert reports == results == [StudyReport(1, str(tmp_path / "sub-SECRET01_T1w.nii.gz"), [])]
