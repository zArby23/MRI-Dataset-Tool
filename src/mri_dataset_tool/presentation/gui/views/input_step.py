"""Step 1: input folder and format, output folder (new or empty; inside one with content, a new folder by
name), anonymization key and disk space warning."""

import tkinter as tk
from tkinter import filedialog, ttk

from mri_dataset_tool.presentation.gui.controller import FORMATS
from mri_dataset_tool.presentation.gui.views import StepView
from mri_dataset_tool.presentation.gui.worker import Done, Event, Failed

FORMAT_NAMES = {"bids": "BIDS", "dicom": "DICOM", "nifti": "NIfTI"}


class InputStep(StepView):
    def build(self) -> None:
        state = self.controller.state
        self.input_dir = tk.StringVar(value="" if state.input_dir is None else str(state.input_dir))
        self.input_format = tk.StringVar(value=state.input_format)
        self.output_dir = tk.StringVar(value="" if state.output_dir is None else str(state.output_dir))
        self.new_folder = tk.StringVar()
        self.invalidate_on_edit(self.input_dir, self.input_format, self.output_dir, self.new_folder)
        self.output_dir.trace_add("write", lambda *_: self._hide_new_folder())  # the name was for that folder
        self.columnconfigure(1, weight=1)

        self._input_label = ttk.Label(self)
        self._input_label.grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(self, textvariable=self.input_dir).grid(row=0, column=1, sticky="ew", padx=6)
        self._input_browse = ttk.Button(self, command=lambda: self._browse(self.input_dir))
        self._input_browse.grid(row=0, column=2)

        self._format_label = ttk.Label(self)
        self._format_label.grid(row=1, column=0, sticky="w", pady=4)
        formats = ttk.Frame(self)
        formats.grid(row=1, column=1, sticky="w", padx=6)
        for name in FORMATS:
            ttk.Radiobutton(formats, text=FORMAT_NAMES[name], value=name, variable=self.input_format).pack(
                side="left", padx=(0, 12)
            )

        self._output_label = ttk.Label(self)
        self._output_label.grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(self, textvariable=self.output_dir).grid(row=2, column=1, sticky="ew", padx=6)
        self._output_browse = ttk.Button(self, command=lambda: self._browse(self.output_dir))
        self._output_browse.grid(row=2, column=2)

        self._new_folder_label = ttk.Label(self)  # shown only for an output folder with content
        self._new_folder_entry = ttk.Entry(self, textvariable=self.new_folder)

        self._key = ttk.Label(self, wraplength=640, justify="left")
        self._key.grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self._validate = ttk.Button(self, command=self.validate)
        self._validate.grid(row=5, column=0, sticky="w", pady=8)
        self._result = ttk.Label(self, wraplength=640, justify="left")
        self._result.grid(row=6, column=0, columnspan=3, sticky="w")
        self._disk = ttk.Label(self, wraplength=640, justify="left")
        self._disk.grid(row=7, column=0, columnspan=3, sticky="w", pady=4)
        self._check = None  # the last validation, redrawn in the current language
        self._disk_summary: dict[str, int] | None = None

    def refresh_texts(self) -> None:
        text = self.controller.text
        self._input_label.configure(text=text("INPUT_DIR"))
        self._format_label.configure(text=text("INPUT_FORMAT"))
        self._output_label.configure(text=text("OUTPUT_DIR"))
        self._new_folder_label.configure(text=text("NEW_FOLDER"))
        for button in (self._input_browse, self._output_browse):
            button.configure(text=text("BROWSE"))
        self._validate.configure(text=text("VALIDATE"), state="disabled" if self.controller.worker.busy else "normal")
        self._key.configure(text=self.controller.key_text())
        self._result.configure(text="" if self._check is None else self.controller.check_text(self._check, "INPUT_OK"))
        if self._disk_summary is not None:
            self._disk.configure(text=self.controller.disk_space_text(self._disk_summary))

    def _show_new_folder(self) -> None:
        self._new_folder_label.grid(row=3, column=0, sticky="w", pady=4)
        self._new_folder_entry.grid(row=3, column=1, sticky="ew", padx=6)
        self._new_folder_entry.focus_set()

    def _hide_new_folder(self) -> None:
        self.new_folder.set("")
        self._new_folder_label.grid_remove()
        self._new_folder_entry.grid_remove()

    def _browse(self, variable: tk.StringVar) -> None:
        if chosen := filedialog.askdirectory(parent=self, mustexist=False):
            variable.set(chosen)

    def validate(self) -> None:
        if self.controller.worker.busy:  # a double click while the disk space check runs
            return
        check = self._check = self.controller.set_input(
            self.input_dir.get(), self.input_format.get(), self.output_dir.get(), self.new_folder.get()
        )
        if check.code == "OUTPUT_NOT_EMPTY":
            self._show_new_folder()
        self._disk_summary = None
        self._disk.configure(text="")
        if check.ok:
            self._disk.configure(text=self.controller.text("CHECKING_DISK_SPACE"))
            self.controller.start_task(self.controller.disk_space_task())
        self.refresh_texts()
        self.on_change()

    def on_event(self, event: Event) -> None:
        if isinstance(event, Done):
            self._disk_summary = event.summary
        elif isinstance(event, Failed):  # the estimate failed: the run is not blocked
            self._disk.configure(text=self.controller.failure_text(event))
        self.refresh_texts()
