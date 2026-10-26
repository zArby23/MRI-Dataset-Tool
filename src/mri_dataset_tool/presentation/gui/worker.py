"""One long task at a time in a background thread; its events go to a ``queue.Queue``.

Only the main (Tk) thread touches widgets: it drains the queue with ``after``. The task gets a
``Reporter`` whose callbacks fit the services (``on_status``, ``on_skipped``, ``on_error``,
``on_report_error``) and
publish only stage names, integer counts and exception type names. Tasks cannot be cancelled; the
thread is a daemon, so closing the window stops it (the window warns first).
"""

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput
from mri_dataset_tool.application.services.pipeline_run import StageFailed
from mri_dataset_tool.presentation.gui import messages

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Status:
    stage: str
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Skipped:  # a file the reader skipped
    error_type: str


@dataclass(frozen=True)
class StudyFailed:  # a study failed and the batch went on (RF16)
    error_type: str


@dataclass(frozen=True)
class ReportReadError:  # a file the dataset report could not read
    error_type: str


@dataclass(frozen=True)
class Failed:  # the task stopped; ``code`` is a ``messages`` code, ``values`` fill its text
    code: str
    error_type: str
    stage: str | None = None
    values: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Done:
    summary: dict[str, int] = field(default_factory=dict)


Event = Status | Skipped | StudyFailed | ReportReadError | Failed | Done


class Reporter:
    """Service callbacks that publish events; paths and messages are dropped here."""

    def __init__(self, events: queue.Queue) -> None:
        self._events = events

    def on_status(self, stage: str, counts: dict[str, int]) -> None:
        self._events.put(Status(stage, {name: n for name, n in counts.items() if type(n) is int}))

    def on_skipped(self, path: Path, error: Exception) -> None:
        self._events.put(Skipped(type(error).__name__))

    def on_error(self, path: Path, error: Exception) -> None:
        self._events.put(StudyFailed(type(error).__name__))

    def on_report_error(self, path: Path, error: Exception) -> None:
        self._events.put(ReportReadError(type(error).__name__))


def failure(error: Exception) -> Failed:
    """The ``Failed`` event of an exception, by type (never its message)."""
    if isinstance(error, StageFailed):
        return Failed("STAGE_FAILED", error.error_type, error.stage)
    if isinstance(error, FileExistsError):
        return Failed("OUTPUT_EXISTS", type(error).__name__)
    if isinstance(error, InvalidBuildInput):
        code, values = messages.invalid_input(error)
        return Failed(code, type(error).__name__, values=values)
    return Failed("UNEXPECTED", type(error).__name__)


class Worker:
    def __init__(self, events: queue.Queue | None = None) -> None:
        self.events: queue.Queue = events if events is not None else queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False  # set by start, cleared only by drain (the main thread), on Done/Failed

    @property
    def busy(self) -> bool:
        return self._running

    def start(self, task: Callable[[Reporter], dict[str, int] | None]) -> None:
        """Run ``task(reporter)`` in a thread; it ends with ``Done(summary)`` or ``Failed`` (see ``drain``)."""
        if self.busy:
            raise RuntimeError("A task is already running.")
        self._running = True
        self._thread = threading.Thread(target=self._run, args=(task,), daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, task: Callable[[Reporter], dict[str, int] | None]) -> None:
        try:
            summary = task(Reporter(self.events)) or {}
            event: Event = Done({name: n for name, n in summary.items() if type(n) is int})
        except Exception as error:  # the window must never crash; only the type is shown or logged
            event = failure(error)
            logger.warning("GUI task failed: %s (%s)", event.code, event.error_type)
        self.events.put(event)

    def drain(self) -> list[Event]:
        """The events published since the last call (never blocks). Call it from the main thread only:
        the task counts as running until its ``Done``/``Failed`` is drained, so a stale last event can
        never be taken for the one of a newer task."""
        events = []
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return events
            events.append(event)
            if isinstance(event, (Done, Failed)):
                self._running = False
