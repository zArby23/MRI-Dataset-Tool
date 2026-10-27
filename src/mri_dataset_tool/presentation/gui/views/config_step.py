"""Step 2: run configuration, memory notice and consent, label classes, split ratios and seed."""

import tkinter as tk
from tkinter import filedialog, ttk

from mri_dataset_tool.presentation.gui.views import StepView


class ConfigStep(StepView):
    def build(self) -> None:
        state = self.controller.state
        self.config_path = tk.StringVar(value=str(state.config_path))
        self.allow_memory = tk.BooleanVar(value=state.allow_insufficient_memory)
        self.invalidate_on_edit(self.config_path, self.allow_memory)
        self.columnconfigure(1, weight=1)

        self._config_label = ttk.Label(self)
        self._config_label.grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(self, textvariable=self.config_path).grid(row=0, column=1, sticky="ew", padx=6)
        self._browse = ttk.Button(self, command=self._choose_config)
        self._browse.grid(row=0, column=2)

        self._memory = ttk.LabelFrame(self, padding=8)
        self._memory.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
        self._memory_text = ttk.Label(self._memory, wraplength=660, justify="left")
        self._memory_text.pack(anchor="w")
        self._allow = ttk.Checkbutton(self._memory, variable=self.allow_memory)
        self._allow.pack(anchor="w", pady=(6, 0))

        self._classes_label = ttk.Label(self)
        self._classes_label.grid(row=2, column=0, columnspan=3, sticky="w")
        self.classes = tk.Text(self, height=4, width=40)
        self.classes.grid(row=3, column=0, columnspan=3, sticky="ew", pady=4)
        self.classes.bind("<<Modified>>", self._classes_edited)
        self._validated_classes = self.classes.get("1.0", "end")  # the text of the last validation

        self._validate = ttk.Button(self, command=self.validate)
        self._validate.grid(row=6, column=0, sticky="w", pady=8)
        self._result = ttk.Label(self, wraplength=660, justify="left")
        self._result.grid(row=7, column=0, columnspan=3, sticky="w")
        self._check = None

    def refresh_texts(self) -> None:
        text = self.controller.text
        self._config_label.configure(text=text("CONFIG_FILE"))
        self._browse.configure(text=text("BROWSE"))
        self._memory.configure(text=text("MEMORY_TITLE"))
        self._memory_text.configure(text=text("MEMORY_NOTICE"))
        self._allow.configure(text=text("ALLOW_MEMORY"))
        self._classes_label.configure(text=text("CLASSES"))
        self._validate.configure(text=text("VALIDATE"))
        if self._check is None:
            self._result.configure(text="")
        elif self._check.ok:
            self._result.configure(text="\n".join([text("CONFIG_OK"), *self.controller.pipeline_summary()]))
        else:
            self._result.configure(text=self.controller.check_text(self._check, "CONFIG_OK"))

    def _choose_config(self) -> None:
        if chosen := filedialog.askopenfilename(parent=self, filetypes=[("YAML", "*.yaml *.yml")]):
            self.config_path.set(chosen)

    def _classes_edited(self, _event) -> None:
        """A <<Modified>> of the classes box. It can arrive late (text inserted by code or pasted is
        reported on the next event loop), so it reopens the step only if the step is shown and the text
        differs from the last validated one: a late event must never drop a finished run."""
        if not self.classes.edit_modified():
            return
        self.classes.edit_modified(False)
        if self.winfo_manager() == "pack" and self.classes.get("1.0", "end") != self._validated_classes:
            self._edited()

    def validate(self) -> None:
        self._validated_classes = self.classes.get("1.0", "end")
        self._check = self.controller.set_config(
            self.config_path.get(), self.allow_memory.get(), self._validated_classes,
        )
        self.refresh_texts()
        self.on_change()
