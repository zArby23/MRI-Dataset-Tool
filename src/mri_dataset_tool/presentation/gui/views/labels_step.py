"""Step 5: the label table of the dataset (one row per participant/session pseudonym), editable one by one or
in batch (selection, all unlabeled, a corrections TSV), and the apply / finalize / reopen actions (RF11, RF12).
Every edit stays pending until «Apply» (all or nothing, logged)."""

import tkinter as tk
from tkinter import filedialog, ttk

from mri_dataset_tool.presentation.gui import messages, theme, widgets
from mri_dataset_tool.presentation.gui.views import StepView
from mri_dataset_tool.presentation.gui.worker import Done, Event, Failed

COLUMNS = ("participant", "session", "label", "defect")
FILTERS = ("all", "unlabeled", "defect")
TSV_TYPES = [("TSV", "*.tsv")]


class LabelsStep(StepView):
    def build(self) -> None:
        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        self._reload = widgets.Button(buttons, command=self.reload)
        self._apply = widgets.Button(buttons, command=lambda: self.run("apply"))
        self._finalize = widgets.Button(buttons, command=lambda: self.run("finalize"))
        self._reopen = widgets.Button(buttons, command=lambda: self.run("reopen"))
        self._corrections = widgets.Button(buttons, command=self._load_corrections)
        for button in (self._reload, self._apply, self._finalize, self._reopen, self._corrections):
            button.pack(side="left", padx=(0, theme.space("s")))

        batch = ttk.Frame(self)
        batch.pack(fill="x", pady=(theme.space("s"), 0))
        show = ttk.Frame(self)  # its own row: with the class row it did not fit the window
        show.pack(fill="x", pady=(theme.space("s"), 0))
        self._class_label = ttk.Label(batch)
        self._class_label.pack(side="left")
        self.batch_class = tk.StringVar()
        self._batch_combo = ttk.Combobox(batch, textvariable=self.batch_class, state="readonly", width=16)
        self._batch_combo.pack(side="left", padx=theme.space("s"))
        self._assign = widgets.Button(batch, command=self.assign_selection)
        self._assign.pack(side="left", padx=(0, theme.space("s")))
        self._assign_unlabeled = widgets.Button(batch, command=self.assign_unlabeled)
        self._assign_unlabeled.pack(side="left")
        self._filter_label = ttk.Label(show)
        self._filter_label.pack(side="left")
        self.filter = tk.StringVar(value=self.controller.state.label_filter)
        self._filter_buttons = [ttk.Radiobutton(show, value=name, variable=self.filter, command=self._filter_changed)
                                for name in FILTERS]
        for button in self._filter_buttons:
            button.pack(side="left", padx=(theme.space("s"), 0))

        self._help = ttk.Label(self, wraplength=theme.wrap(), justify="left")
        self._help.pack(fill="x", pady=theme.space("s"))
        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", height=8, selectmode="extended")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        across = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        # one click on a «Label» cell opens the list of classes (a double click was not discovered)
        self._label_under_pointer = widgets.bind_cell_editing(self.tree, ("label",), self._open_editor)
        widgets.Tooltip(self.tree, lambda: self.controller.text("HINT_EDIT_LABEL") if self._label_under_pointer()
                        else None)
        widgets.bind_row_hover(self.tree)
        self._status = self.status_line()
        self._status.pack(fill="x", pady=theme.space("s"))
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
        pending = self.controller.pending_label_edits()
        # «Apply» stands out while there are edits to apply, so they are not forgotten
        self._apply.configure(text=text("APPLY"), state=editable if pending else "disabled", primary=bool(pending))
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
        if pending:  # the line the warning is about goes first
            unapplied = text("LABELS_UNAPPLIED", count=pending)
            lines.sort(key=lambda line: line != unapplied)
        code = self._message[0] if self._message is not None else "LABELS_UNAPPLIED" if pending else None
        self._status.configure(text="\n".join(lines), severity=messages.severity(code))

    def _draw_table(self) -> None:
        """Rebuild the rows only when they, their edits, the filter or the language changed (thousands of
        rows: a full rebuild on every window refresh would be slow)."""
        drawn = (self.controller.state.label_version, self.controller.language)
        if drawn == self._drawn:
            return
        self._drawn = drawn
        text, rows = self.controller.text, self.controller.state.label_rows
        for column in COLUMNS:
            mark = f" {theme.EDIT_MARK}" if column == "label" else ""
            self.tree.heading(column, text=text(f"COL_{column}") + mark)
        selected, focused = self.tree.selection(), self.tree.focus()  # kept across the rebuild
        self.tree.delete(*self.tree.get_children())
        for index in self.controller.visible_label_rows():
            label, defect = self.controller.effective_label(index)
            row = rows[index]
            self.tree.insert("", "end", iid=str(index), values=(
                row.participant, row.session or "", label, "" if defect is None else text(f"DEFECT_{defect}"),
            ))
        widgets.stripe(self.tree)
        self.tree.selection_set([item for item in selected if self.tree.exists(item)])
        if focused and self.tree.exists(focused):
            self.tree.focus(focused)

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
        if self.controller.start_task(task, self.controller.labels_failure, activity="labels"):
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
        return self.winfo_toplevel().ask("CONFIRM_TITLE", question)

    def _load_corrections(self) -> None:
        if path := filedialog.askopenfilename(parent=self, filetypes=TSV_TYPES):
            self.run_corrections(path)

    def run_corrections(self, path: str) -> None:
        check, task = self.controller.corrections_task(path)
        if not check.ok:
            self._say(check)
        elif self.controller.start_task(task, self.controller.labels_failure, activity="corrections"):
            self._action = "corrections"
            self._message = ("TASK_STARTED", {})
            self.refresh_texts()
            self.on_change()

    # --- one cell ---------------------------------------------------------------------------------

    def _open_editor(self, item: str, column: str) -> None:
        """One click (or Enter / F2) on a label cell: the editor with its list already open."""
        if (editor := self.start_edit(int(item))) is not None:
            widgets.open_list(editor)

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
        editor.bind("<Escape>", lambda _: self._close_editor(refocus=True))
        self._editor = editor
        return editor

    def commit_edit(self, index: int, value: str) -> None:
        self._close_editor()
        check = self.controller.edit_label(index, value)
        self._message = None if check.ok else (check.code, check.values)
        self.refresh_texts()
        self.on_change()

    def _close_editor(self, refocus: bool = False) -> None:
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None
            if refocus:  # Esc: back to the table, with its selection
                self.tree.focus_set()
