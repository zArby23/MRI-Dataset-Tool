"""Step 6: the ML exports (split ratios and seed) and the dataset report, and opening the output folder."""

import os
import subprocess
import sys
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, ttk

from mri_dataset_tool.presentation.gui.views import StepView
from mri_dataset_tool.presentation.gui.worker import Done, Event, Failed, ReportReadError


def open_folder(path: Path) -> None:
    """Open *path* in the file manager (a folder the user chose: the output or the report folder)."""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606  (a folder chosen by the user)
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ExportStep(StepView):
    def build(self) -> None:
        state = self.controller.state
        self.ratios = [tk.StringVar(value=str(r)) for r in state.ratios]
        self.seed = tk.StringVar(value=str(state.seed))
        self.report_dir = tk.StringVar()
        self.columnconfigure(1, weight=1)

        self._ml = ttk.LabelFrame(self, padding=8)
        self._ml.grid(row=0, column=0, columnspan=3, sticky="ew")
        self._ratios_label = ttk.Label(self._ml)
        self._ratios_label.grid(row=0, column=0, sticky="w")
        ratios = ttk.Frame(self._ml)
        ratios.grid(row=0, column=1, sticky="w", padx=6)
        for variable in self.ratios:
            ttk.Entry(ratios, textvariable=variable, width=6).pack(side="left", padx=(0, 6))
        self._seed_label = ttk.Label(self._ml)
        self._seed_label.grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(self._ml, textvariable=self.seed, width=8).grid(row=1, column=1, sticky="w", padx=6)
        self._write_ml = ttk.Button(self._ml, command=self.write_ml)
        self._write_ml.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self._ml_help = ttk.Label(self._ml, wraplength=640, justify="left")
        self._ml_help.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self._report = ttk.LabelFrame(self, padding=8)
        self._report.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
        self._report.columnconfigure(1, weight=1)
        self._report_label = ttk.Label(self._report)
        self._report_label.grid(row=0, column=0, sticky="w")
        ttk.Entry(self._report, textvariable=self.report_dir).grid(row=0, column=1, sticky="ew", padx=6)
        self._browse = ttk.Button(self._report, command=self._choose_report_dir)
        self._browse.grid(row=0, column=2)
        self._write_report = ttk.Button(self._report, command=self.write_report)
        self._write_report.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self._open = ttk.Button(self, command=self._open_output)
        self._open.grid(row=2, column=0, sticky="w")
        self.log = tk.Listbox(self, height=10)
        self.log.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=6)
        self.rowconfigure(3, weight=1)
        self._lines: list[tuple[str, dict]] = []  # (code, values) redrawn in the current language
        self._report_errors: Counter[str] = Counter()

    def refresh_texts(self) -> None:
        text, state = self.controller.text, self.controller.state
        if not self.report_dir.get() and state.dataset_root is not None and state.output_dir is not None:
            self.report_dir.set(str(self.controller.default_report_dir()))
        busy = "disabled" if self.controller.worker.busy else "normal"
        self._ml.configure(text=text("ML_EXPORTS"))
        self._ratios_label.configure(text=text("RATIOS"))
        self._seed_label.configure(text=text("SEED"))
        present = state.dataset_root is not None and self.controller.ml_exports_present()
        self._write_ml.configure(text=text("REGENERATE_ML" if present else "WRITE_ML"), state=busy)
        self._ml_help.configure(text=text("ML_REGENERATE_HELP"))
        self._report.configure(text=text("REPORT"))
        self._report_label.configure(text=text("REPORT_DIR"))
        self._browse.configure(text=text("BROWSE"))
        self._write_report.configure(text=text("WRITE_REPORT"), state=busy)
        self._open.configure(text=text("OPEN_FOLDER"), state="normal" if state.output_dir else "disabled")
        self.log.delete(0, "end")
        for line in self.controller.export_status_lines():
            self.log.insert("end", line)
        for code, values in self._lines:
            self.log.insert("end", text(code, **values))

    def _choose_report_dir(self) -> None:
        if chosen := filedialog.askdirectory(parent=self, mustexist=False):
            self.report_dir.set(chosen)

    def _start(self, check, task) -> None:
        if not check.ok:
            self._lines.append((check.code, check.values))
        elif self.controller.start_task(task, self.controller.export_failure):
            self._lines.append(("TASK_STARTED", {}))
        self.refresh_texts()
        self.on_change()

    def write_ml(self) -> None:
        self._start(*self.controller.ml_exports_task(
            [variable.get() for variable in self.ratios], self.seed.get()
        ))

    def write_report(self) -> None:
        self._start(*self.controller.report_task(self.report_dir.get()))

    def on_event(self, event: Event) -> None:
        if isinstance(event, ReportReadError):
            self._report_errors[event.error_type] += 1
        elif isinstance(event, Done):
            self._lines += self.controller.export_finished(event)
            if self._report_errors:
                self._lines.append(("RUN_REPORT_ERRORS", {"counts": self.controller.counts_text(self._report_errors)}))
                self._report_errors = Counter()
            if self.controller.state.report_dirs:  # the default moves on to the next free report folder
                self.report_dir.set(str(self.controller.default_report_dir()))
        elif isinstance(event, Failed):
            self._lines.append((event.code, {"error_type": event.error_type, "stage": event.stage, **event.values}))
        self.refresh_texts()

    def _open_output(self) -> None:
        open_folder(self.controller.state.output_dir)
