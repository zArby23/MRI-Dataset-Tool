"""GUI worker: one task at a time in a thread; the queue holds only codes, type names and integers."""

import logging
import threading
from pathlib import Path

import pytest

from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput
from mri_dataset_tool.application.services.pipeline_run import StageFailed
from mri_dataset_tool.presentation.gui.worker import Done, Failed, Skipped, Status, StudyFailed, Worker, failure

SECRET = "PlantedSecret"
SECRET_PATH = Path("E:/PlantedPatient/sub-PlantedId/scan.dcm")


def _run(task) -> list:
    worker = Worker()
    worker.start(task)
    worker.join(5)
    assert worker.busy  # until the main thread drains the last event
    events = worker.drain()
    assert not worker.busy
    return events


def test_events_carry_no_paths_messages_or_text_values(caplog):
    caplog.set_level(logging.DEBUG)

    def task(reporter):
        reporter.on_status("exported", {"studies": 2, "leak": SECRET})
        reporter.on_skipped(SECRET_PATH, ValueError(SECRET))
        reporter.on_error(SECRET_PATH, OSError(f"{SECRET} {SECRET_PATH}"))
        raise StageFailed("export", RuntimeError(SECRET))

    events = _run(task)
    assert events == [Status("exported", {"studies": 2}), Skipped("ValueError"), StudyFailed("OSError"),
                      Failed("STAGE_FAILED", "RuntimeError", "export")]
    assert "Planted" not in repr(events) + caplog.text


def test_done_carries_the_integer_summary():
    assert _run(lambda reporter: {"files": 4, "path": str(SECRET_PATH)}) == [Done({"files": 4})]
    assert _run(lambda reporter: None) == [Done({})]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (FileExistsError(SECRET), Failed("OUTPUT_EXISTS", "FileExistsError")),
        (InvalidBuildInput(SECRET), Failed("INVALID_INPUT", "InvalidBuildInput", values={"error_type": "InvalidBuildInput"})),
        (InvalidBuildInput("Invalid --ratios."), Failed("INVALID_RATIOS", "InvalidBuildInput")),
        (InvalidBuildInput("Mapping paths not found in the input: 2."),
         Failed("MAPPING_PATHS_NOT_FOUND", "InvalidBuildInput", values={"count": 2})),
        (StageFailed("report", KeyError(SECRET)), Failed("STAGE_FAILED", "KeyError", "report")),
        (ZeroDivisionError(SECRET), Failed("UNEXPECTED", "ZeroDivisionError")),
    ],
)
def test_failure_is_classified_by_type(error, expected):
    assert failure(error) == expected


def test_one_task_at_a_time_and_a_new_one_after_the_last_event():
    release = threading.Event()
    worker = Worker()
    worker.start(lambda reporter: release.wait(5) and None)
    assert worker.busy
    with pytest.raises(RuntimeError):
        worker.start(lambda reporter: None)
    release.set()
    worker.join(5)
    assert worker.busy and worker.drain() == [Done({})] and not worker.busy
    worker.start(lambda reporter: None)
    worker.join(5)
    assert worker.drain() == [Done({})]


def test_the_thread_is_a_daemon():
    seen = []
    worker = Worker()
    worker.start(lambda reporter: seen.append(threading.current_thread().daemon))
    worker.join(5)
    assert seen == [True]
