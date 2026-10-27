"""Step 5: the label table of the dataset (one row per participant/session pseudonym), editable one by one or
in batch (selection, all unlabeled, a corrections TSV), and the apply / finalize / reopen actions (RF11, RF12).
Every edit stays pending until «Apply» (all or nothing, logged)."""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mri_dataset_tool.presentation.gui.views import StepView
from mri_dataset_tool.presentation.gui.worker import Done, Event, Failed

COLUMNS = ("participant", "session", "label", "defect")
FILTERS = ("all", "unlabeled", "defect")
TSV_TYPES = [("TSV", "*.tsv")]


class LabelsStep(StepView):
    def build(self) -> None:
        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        self._reload = ttk.Button(buttons, command=self.reload)
        self._apply = ttk.Button(buttons, command=lambda: self.run("apply"))
        self._finalize = ttk.Button(buttons, command=lambda: self.run("finalize"))
        self._reopen = ttk.Button(buttons, command=lambda: self.run("reopen"))
        self._corrections = ttk.Button(buttons, command=self._load_corrections)
        for button in (self._reload, self._apply, self._finalize, self._reopen, self._corrections):
            button.pack(side="left", padx=(0, 6))

        batch = ttk.Frame(self)
        batch.pack(fill="x", pady=(6, 0))
        self._class_label = ttk.Label(batch)
        self._class_label.pack(side="left")
        self.batch_class = tk.StringVar()
        self._batch_combo = ttk.Combobox(batch, textvariable=self.batch_class, state="readonly", width=16)
        self._batch_combo.pack(side="left", padx=6)
        self._assign = ttk.Button(batch, command=self.assign_selection)
        self._assign.pack(side="left", padx=(0, 6))
        self._assign_unlabeled = ttk.Button(batch, command=self.assign_unlabeled)
        self._assign_unlabeled.pack(side="left", padx=(0, 18))
        self._filter_label = ttk.Label(batch)
        self._filter_label.pack(side="left")
        self.filter = tk.StringVar(value=self.controller.state.label_filter)
        self._filter_buttons = [ttk.Radiobutton(batch, value=name, variable=self.filter, command=self._filter_changed)
                                for name in FILTERS]
        for button in self._filter_buttons:
            button.pack(side="left", padx=(6, 0))

        self._help = ttk.Label(self, wraplength=680, justify="left")
        self._help.pack(fill="x", pady=6)
        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", height=12, selectmode="extended")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._start_edit)
        self._status = ttk.Label(self, wraplength=680, justify="left")
        self._status.pack(fill="x", pady=6)
        self._editor = None
        self._message: tuple[str, dict] | None = None
        self._loaded_for = None  # the dataset whose table is shown
        self._drawn: tuple[int, str] | None = None  # (label_version, language) in the table
        self._action = ""  # the labels task that runs
        self._pending = 0  # edits a reload discards

    def refresh_texts(self) -> None:
        state, text = self.controller.state, self.controller.text
        shown = self.winfo_manager() == "pack"  # packed by the window: never while it is being built
        if shown and state.dataset_root is not None and state.dataset_root != self._loaded_for:
            self.reload()  # first time the step is shown for this dataset
            return
        busy = self.controller.worker.busy
        usable = state.labels_available and not busy
        editable = "normal" if usable and not state.labels_closed else "disabled"
        self._reload.configure(text=text("RELOAD"), state="normal" if state.dataset_root and not busy else "disabled")
        self._apply.configure(text=text("APPLY"), state=editable if state.label_edits else "disabled")
        self._finalize.configure(text=text("FINALIZE"), state=editable)
        self._reopen.configure(text=text("REOPEN"), state="normal" if usable and state.labels_closed else "disabled")
        self._corrections.configure(text=text("LOAD_CORRECTIONS"), state=editable)
        self._class_label.configure(text=text("BATCH_CLASS"))
        self._batch_combo.configure(values=("", *state.label_classes), state="readonly" if editable == "normal" else "disabled")
        self._assign.configure(text=text("ASSIGN_SELECTION"), state=editable)
        self._assign_unlabeled.configure(text=text("ASSIGN_UNLABELED"), state=editable)
        self._filter_label.configure(text=text("FILTER"))
        for name, button in zip(FILTERS, self._filter_buttons):
            button.configure(text=text(f"FILTER_{name}"))
        self._help.configure(text=text("LABELS_HELP"))
        self._draw_table()
        lines = self.controller.labels_status_lines()
        if self._message is not None:
            lines.append(text(self._message[0], **self._message[1]))
        self._status.configure(text="\n".join(lines))

    def _draw_table(self) -> None:
        """Rebuild the rows only when they, their edits, the filter or the language changed (thousands of
        rows: a full rebuild on every window refresh would be slow)."""
        drawn = (self.controller.state.label_version, self.controller.language)
        if drawn == self._drawn:
            return
        self._drawn = drawn
        text, rows = self.controller.text, self.controller.state.label_rows
        for column in COLUMNS:
            self.tree.heading(column, text=text(f"COL_{column}"))
        self.tree.delete(*self.tree.get_children())
        for index in self.controller.visible_label_rows():
            label, defect = self.controller.effective_label(index)
            row = rows[index]
            self.tree.insert("", "end", iid=str(index), values=(
                row.participant, row.session or "", label, "" if defect is None else text(f"DEFECT_{defect}"),
            ))

    def _say(self, check, ok_code: str | None = None) -> None:
        self._message = (check.code, check.values) if not check.ok else (ok_code, check.values) if ok_code else None
        self.refresh_texts()
        self.on_change()

    def reload(self) -> None:
        self._loaded_for = self.controller.state.dataset_root
        self.run("load")

    def run(self, action: str) -> None:
        """Start a labels task (load | apply | finalize | reopen) in the worker: thousands of pairs take
        seconds and the window must keep responding."""
        check, task = self.controller.labels_task(action)
        if not check.ok:
            self._say(check)
            return
        if self.controller.start_task(task, self.controller.labels_failure):
            self._action, self._pending = action, len(self.controller.state.label_edits)
            self._message = ("TASK_STARTED", {})
            self.refresh_texts()
            self.on_change()

    def on_event(self, event: Event) -> None:
        if isinstance(event, Done) and self._action == "corrections":
            self._message = ("CORRECTIONS_LOADED", self.controller.corrections_finished(event).values)
        elif isinstance(event, Done):
            check = self.controller.labels_finished(event)
            if not check.ok:  # NO_LABELS: the step is valid, nothing to edit
                self._message = (check.code, check.values)
            elif self._action == "apply":
                self._message = ("LABELS_APPLIED", check.values)
            elif self._action == "load" and self._pending:  # reloading discarded them: say so
                self._message = ("LABELS_DISCARDED", {"count": self._pending})
            else:
                self._message = None
        elif isinstance(event, Failed):
            self._message = (event.code, {"error_type": event.error_type, **event.values})
        self.refresh_texts()

    def _filter_changed(self) -> None:
        self.controller.set_label_filter(self.filter.get())
        self.refresh_texts()

    def assign_selection(self) -> None:
        indices = [int(item) for item in self.tree.selection()]
        self._say(self.controller.assign_labels(indices, self.batch_class.get()), "ASSIGNED")

    def assign_unlabeled(self) -> None:
        indices, label = self.controller.unlabeled_rows(), self.batch_class.get()
        if not indices:
            self._message = ("NOTHING_UNLABELED", {})
            self.refresh_texts()
            return
        question = self.controller.text("CONFIRM_ASSIGN_UNLABELED", label=label, count=len(indices))
        if self.confirm(question):
            self._say(self.controller.assign_labels(indices, label), "ASSIGNED")

    def confirm(self, question: str) -> bool:
        return messagebox.askokcancel(self.controller.text("CONFIRM_TITLE"), question, parent=self)

    def _load_corrections(self) -> None:
        if path := filedialog.askopenfilename(parent=self, filetypes=TSV_TYPES):
            self.run_corrections(path)

    def run_corrections(self, path: str) -> None:
        check, task = self.controller.corrections_task(path)
        if not check.ok:
            self._say(check)
        elif self.controller.start_task(task, self.controller.labels_failure):
            self._action = "corrections"
            self._message = ("TASK_STARTED", {})
            self.refresh_texts()
            self.on_change()

    # --- one cell ---------------------------------------------------------------------------------

    def _start_edit(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if item and self.tree.identify_column(event.x) == f"#{COLUMNS.index('label') + 1}":
            self.start_edit(int(item))

    def start_edit(self, index: int) -> ttk.Combobox | None:
        """A closed list of the classes over the label cell (``""`` = unlabeled)."""
        state = self.controller.state
        if self._editor is not None:
            self._editor.destroy()
        if self.controller.worker.busy:
            return None
        if state.labels_closed:
            self._message = ("LABELS_FINALIZED", {})
            self.refresh_texts()
            return None
        box = self.tree.bbox(str(index), "label")
        if not box:  # the cell is not visible (scrolled out or filtered)
            return None
        editor = ttk.Combobox(self.tree, values=("", *state.label_classes), state="readonly")
        editor.set(self.tree.set(str(index), "label"))
        x, y, width, height = box
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.bind("<<ComboboxSelected>>", lambda _: self.commit_edit(index, editor.get()))
        editor.bind("<Escape>", lambda _: self._close_editor())
        self._editor = editor
        return editor

    def commit_edit(self, index: int, value: str) -> None:
        self._close_editor()
        check = self.controller.edit_label(index, value)
        self._message = None if check.ok else (check.code, check.values)
        self.refresh_texts()
        self.on_change()

    def _close_editor(self) -> None:
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None
