"""Step 5: the label table of the dataset (one row per participant/session pseudonym), editable with the
classes, and the apply / finalize / reopen actions (RF11, RF12)."""

from tkinter import ttk

from mri_dataset_tool.presentation.gui.views import StepView

COLUMNS = ("participant", "session", "label", "defect")


class LabelsStep(StepView):
    def build(self) -> None:
        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        self._reload = ttk.Button(buttons, command=self.reload)
        self._apply = ttk.Button(buttons, command=lambda: self._act(self.controller.apply_labels, "LABELS_APPLIED"))
        self._finalize = ttk.Button(buttons, command=lambda: self._act(self.controller.finalize_labels))
        self._reopen = ttk.Button(buttons, command=lambda: self._act(self.controller.reopen_labels))
        for button in (self._reload, self._apply, self._finalize, self._reopen):
            button.pack(side="left", padx=(0, 6))
        self._help = ttk.Label(self, wraplength=680, justify="left")
        self._help.pack(fill="x", pady=6)
        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", height=12, selectmode="browse")
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

    def refresh_texts(self) -> None:
        state, text = self.controller.state, self.controller.text
        shown = self.winfo_manager() == "pack"  # packed by the window: never while it is being built
        if shown and state.dataset_root is not None and state.dataset_root != self._loaded_for:
            self.reload()  # first time the step is shown for this dataset
            return
        busy = self.controller.worker.busy
        usable = state.labels_available and not busy
        self._reload.configure(text=text("RELOAD"), state="normal" if state.dataset_root and not busy else "disabled")
        self._apply.configure(text=text("APPLY"),
                              state="normal" if usable and not state.labels_closed and state.label_edits else "disabled")
        self._finalize.configure(text=text("FINALIZE"),
                                 state="normal" if usable and not state.labels_closed else "disabled")
        self._reopen.configure(text=text("REOPEN"), state="normal" if usable and state.labels_closed else "disabled")
        self._help.configure(text=text("LABELS_HELP"))
        for column in COLUMNS:
            self.tree.heading(column, text=text(f"COL_{column}"))
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(state.label_rows):
            edited = state.label_edits.get((row.participant, row.session))
            self.tree.insert("", "end", iid=str(index), values=(
                row.participant, row.session or "", (row.label or "") if edited is None else edited,
                "" if row.defect is None or edited is not None else text(f"DEFECT_{row.defect}"),
            ))
        lines = self.controller.labels_status_lines()
        if self._message is not None:
            lines.append(text(self._message[0], **self._message[1]))
        self._status.configure(text="\n".join(lines))

    def reload(self) -> None:
        self._loaded_for = self.controller.state.dataset_root
        pending = len(self.controller.state.label_edits)  # reloading discards them: say so
        check = self.controller.load_labels()
        if not check.ok:
            self._message = (check.code, check.values)
        else:
            self._message = ("LABELS_DISCARDED", {"count": pending}) if pending else None
        self.refresh_texts()
        self.on_change()

    def _act(self, action, ok_code: str | None = None) -> None:
        check = action()
        self._message = (check.code, check.values) if not check.ok else (ok_code, check.values) if ok_code else None
        self.refresh_texts()
        self.on_change()

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
        if not box:  # the cell is not visible (scrolled out)
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
