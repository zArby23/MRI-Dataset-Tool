"""Step 4: the dataset build in the worker, with its stages, fixed warnings, errors by type and a summary."""

import tkinter as tk
from collections import Counter
from tkinter import ttk

from mri_dataset_tool.presentation.gui import theme, widgets
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
        self._help = ttk.Label(self, wraplength=theme.wrap(), justify="left")
        self._help.pack(fill="x")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=theme.space("s"))
        self._run = widgets.Button(row, command=self.run)
        self._run.pack(side="left")  # the activity indicator is in the window's footer
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
        for line, severity in self._render():
            self.log.insert("end", line)
            self.log.itemconfigure("end", foreground=theme.color(severity))

    def _render(self) -> list[tuple[str, str]]:
        """The log lines with their severity color (a theme token). Warnings already start with «Aviso CODE:»;
        failures get the «Error:» prefix, so the severity reads without color."""
        text, lines = self.controller.text, []
        for kind, payload in self._lines:
            if kind == "status":
                warning = payload.stage in ("ingested", "labels_incomplete")  # the fixed warnings of the CLI
                lines += [(line, "warning" if warning else "text") for line in self.controller.status_lines(payload)]
            elif kind == "failed":
                lines.append((f'{text("PREFIX_error")} {self.controller.failure_text(payload)}', "error"))
                lines.append((text("RUN_FAILED_HINT"), "error"))
            else:
                lines.append((text(payload), "ok" if payload == "RUN_DONE" else "text"))
        if self._lines and not self.controller.worker.busy:
            counts = self.controller.counts_text
            problems = [(code, counter) for code, counter in (("RUN_ERRORS", self._errors), ("RUN_SKIPPED", self._skipped),
                                                              ("RUN_REPORT_ERRORS", self._report_errors)) if counter]
            # only what happened: one «No errors.» line instead of three «none»
            lines += [(text(code, counts=counts(counter)), "warning") for code, counter in problems] or [
                (text("RUN_CLEAN"), "ok")]
        return lines

    def run(self) -> None:
        if not self.controller.start_task(self.controller.run_task(), activity="run"):
            return
        self._lines, self._errors, self._skipped, self._report_errors = [("text", "RUN_RUNNING")], Counter(), Counter(), Counter()
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
            self.controller.run_finished({**event.summary, "skipped": sum(self._skipped.values())})
            self._lines.append(("text", "RUN_DONE"))
        elif isinstance(event, Failed):
            self._lines.append(("failed", event))
