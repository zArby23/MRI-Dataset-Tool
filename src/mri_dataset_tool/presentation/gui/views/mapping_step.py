"""Step 3 (DICOM / loose NIfTI): the detected series with their suffix decision, editable, and the
``--mapping`` TSV (load / save). The relative paths of the table are shown only here (D2)."""

import tkinter as tk
from tkinter import filedialog, ttk

from mri_dataset_tool.application.services.ingest_preview import EDITABLE_COLUMNS, MAPPING_SUFFIXES
from mri_dataset_tool.presentation.gui.views import StepView
from mri_dataset_tool.presentation.gui.worker import Done, Event, Failed, Skipped

COLUMNS = ("location", "suffix", "code", "participant", "session", "label")
TSV_TYPES = [("TSV", "*.tsv")]


class MappingStep(StepView):
    def build(self) -> None:
        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        self._preview = ttk.Button(buttons, command=self.run_preview)
        self._load = ttk.Button(buttons, command=self._load_file)
        self._save = ttk.Button(buttons, command=self._save_file)
        for button in (self._preview, self._load, self._save):
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
        for column, width in zip(COLUMNS, (260, 80, 160, 140, 140, 90)):
            self.tree.column(column, width=width, stretch=column == "location")
        self.tree.bind("<Double-1>", self._start_edit)
        self._status = ttk.Label(self, wraplength=680, justify="left")
        self._status.pack(fill="x", pady=6)
        self._editor: tk.Widget | None = None
        self._message: tuple[str, dict] | None = None  # (code, values) redrawn in the current language
        self._skipped_files = 0
        self._shown: tuple[int, str] | None = None  # (preview, language) in the table: pending edits survive a redraw

    def refresh_texts(self) -> None:
        text = self.controller.text
        busy = "disabled" if self.controller.worker.busy else "normal"
        self._preview.configure(text=text("PREVIEW"), state=busy)
        self._load.configure(text=text("LOAD_MAPPING"), state=busy)
        self._save.configure(text=text("SAVE_MAPPING"), state=busy)
        self._help.configure(text=text("MAPPING_HELP"))
        for column in COLUMNS:
            self.tree.heading(column, text=text(f"COL_{column}"))
        self._status.configure(text="" if self._message is None else text(self._message[0], **self._message[1]))
        self._fill()

    def _fill(self) -> None:
        shown = (id(self.controller.state.preview), self.controller.language)
        if shown == self._shown:
            return
        self._shown = shown
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.controller.state.preview):
            self.tree.insert("", "end", iid=str(index), values=(
                row.location.as_posix(), row.suffix or "", self.controller.text(f"CODE_{row.code}"),
                row.participant, row.session or "", row.label,
            ))

    def _say(self, code: str, **values: object) -> None:
        self._message = (code, values)
        self.refresh_texts()

    def run_preview(self) -> None:
        if self.controller.start_task(self.controller.preview_task()):
            self._skipped_files = 0
            self._say("PREVIEW_RUNNING")
            self.on_change()

    def on_event(self, event: Event) -> None:
        if isinstance(event, Skipped):
            self._skipped_files += 1
        elif isinstance(event, Done):
            self.controller.preview_finished()
            self._say("PREVIEW_OK", series=event.summary["series"], skipped=event.summary["skipped"],
                      files=self._skipped_files)
        elif isinstance(event, Failed):
            self._say(event.code, **{"error_type": event.error_type, "stage": event.stage, **event.values})

    def _load_file(self) -> None:
        if path := filedialog.askopenfilename(parent=self, filetypes=TSV_TYPES):
            check = self.controller.load_mapping_file(path)
            self._say("MAPPING_LOADED" if check.ok else check.code, **check.values)
            self.on_change()

    def _save_file(self) -> None:
        if path := filedialog.asksaveasfilename(parent=self, filetypes=TSV_TYPES, defaultextension=".tsv",
                                                confirmoverwrite=False):
            check = self.controller.save_mapping_file(path)
            self._say("MAPPING_SAVED" if check.ok else check.code, **check.values)

    # --- cell editing -----------------------------------------------------------------------------

    def _start_edit(self, event) -> None:
        item, column_id = self.tree.identify_row(event.y), self.tree.identify_column(event.x)
        if not item or self.controller.worker.busy:
            return
        column = COLUMNS[int(column_id[1:]) - 1]
        if column not in EDITABLE_COLUMNS:
            return
        self.start_edit(int(item), column)

    def start_edit(self, index: int, column: str) -> tk.Widget | None:
        """Open the editor of a cell (a closed list for suffix and label, free text otherwise)."""
        self._close_editor()
        current = self.tree.set(str(index), column)
        if column == "suffix":
            editor = ttk.Combobox(self.tree, values=("", *MAPPING_SUFFIXES), state="readonly")
        elif column == "label":
            editor = ttk.Combobox(self.tree, values=("", *(self.controller.state.classes or {})), state="readonly")
        else:
            editor = ttk.Entry(self.tree)
        if isinstance(editor, ttk.Combobox):
            editor.set(current)
        else:
            editor.insert(0, current)
        box = self.tree.bbox(str(index), column)
        if not box:  # the cell is not visible (scrolled out)
            editor.destroy()
            return None
        x, y, width, height = box
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.bind("<Return>", lambda _: self.commit_edit(index, column, editor.get()))
        editor.bind("<Escape>", lambda _: self._close_editor())
        editor.bind("<<ComboboxSelected>>", lambda _: self.commit_edit(index, column, editor.get()))
        self._editor = editor
        return editor

    def commit_edit(self, index: int, column: str, value: str) -> None:
        self._close_editor()
        check = self.controller.edit_mapping(index, column, value)
        if check.ok:
            self.tree.set(str(index), column, value)  # shown until the next preview recomputes the table
            self._message = ("EDIT_PENDING", {})
            self._status.configure(text=self.controller.text("EDIT_PENDING"))
        else:
            self._message = (check.code, check.values)
            self._status.configure(text=self.controller.text(check.code, **check.values))
        self.on_change()

    def _close_editor(self) -> None:
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None
