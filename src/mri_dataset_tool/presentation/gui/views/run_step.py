"""Step 4: the dataset build in the worker, with its stages, fixed warnings, errors by type and a summary."""

import tkinter as tk
from collections import Counter
from tkinter import ttk

from mri_dataset_tool.presentation.gui.views import StepView
from mri_dataset_tool.presentation.gui.worker import (
    Done,
    Event,
    Failed,
    ReportReadError,
    Skipped,
    Status,
    StudyFailed,
)


class RunStep(StepView):
    def build(self) -> None:
        self._help = ttk.Label(self, wraplength=680, justify="left")
        self._help.pack(fill="x")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=8)
        self._run = ttk.Button(row, command=self.run)
        self._run.pack(side="left")
        self._progress = ttk.Progressbar(row, mode="indeterminate", length=240)
        self._progress.pack(side="left", padx=12)
        self.log = tk.Listbox(self, height=14)
        self.log.pack(fill="both", expand=True)
        self._lines: list[tuple] = []  # (kind, payload) redrawn in the current language
        self._errors: Counter[str] = Counter()
        self._skipped: Counter[str] = Counter()
        self._report_errors: Counter[str] = Counter()

    def refresh_texts(self) -> None:
        text = self.controller.text
        busy = self.controller.worker.busy
        self._help.configure(text=text("RUN_HELP"))
        done = self.controller.state.dataset_root is not None  # the output now has content: one run per output
        self._run.configure(text=text("RUN"), state="disabled" if busy or done else "normal")
        self.log.delete(0, "end")
        for line in self._render():
            self.log.insert("end", line)

    def _render(self) -> list[str]:
        text, lines = self.controller.text, []
        for kind, payload in self._lines:
            if kind == "status":
                lines += self.controller.status_lines(payload)
            elif kind == "failed":
                lines.append(self.controller.failure_text(payload))
                lines.append(text("RUN_FAILED_HINT"))
            else:
                lines.append(text(payload))
        if self._lines and not self.controller.worker.busy:
            counts = self.controller.counts_text
            lines += [text("RUN_ERRORS", counts=counts(self._errors)), text("RUN_SKIPPED", counts=counts(self._skipped)),
                      text("RUN_REPORT_ERRORS", counts=counts(self._report_errors))]
        return lines

    def run(self) -> None:
        if not self.controller.start_task(self.controller.run_task()):
            return
        self._lines, self._errors, self._skipped, self._report_errors = [("text", "RUN_RUNNING")], Counter(), Counter(), Counter()
        self._progress.start(12)
        self.on_change()

    def on_event(self, event: Event) -> None:
        if isinstance(event, Status):
            self._lines.append(("status", event))
        elif isinstance(event, StudyFailed):
            self._errors[event.error_type] += 1
        elif isinstance(event, Skipped):
            self._skipped[event.error_type] += 1
        elif isinstance(event, ReportReadError):
            self._report_errors[event.error_type] += 1
        elif isinstance(event, Done):
            self.controller.run_finished()
            self._lines.append(("text", "RUN_DONE"))
            self._progress.stop()
        elif isinstance(event, Failed):
            self._lines.append(("failed", event))
            self._progress.stop()
