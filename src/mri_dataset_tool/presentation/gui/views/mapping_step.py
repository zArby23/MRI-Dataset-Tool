"""Step 3 (DICOM / loose NIfTI): the detected series with their suffix decision, editable, and the
``--mapping`` TSV (load / save). The relative paths of the table are shown only here."""

import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from mri_dataset_tool.application.services.ingest_preview import EDITABLE_COLUMNS, MAPPING_SUFFIXES
from mri_dataset_tool.presentation.gui import messages, theme, widgets
from mri_dataset_tool.presentation.gui.views import StepView
from mri_dataset_tool.presentation.gui.worker import Done, Event, Failed, Skipped

COLUMNS = ("location", "suffix", "code", "participant", "session", "label")
TSV_TYPES = [("TSV", "*.tsv")]


class MappingStep(StepView):
    def build(self) -> None:
        self._editor: tk.Widget | None = None
        self._editing: tuple[int, str] = (0, "")
        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        self._preview = widgets.Button(buttons, command=self.run_preview)
        self._load = widgets.Button(buttons, command=self._load_file)
        self._save = widgets.Button(buttons, command=self._save_file)
        for button in (self._preview, self._load, self._save):
            button.pack(side="left", padx=(0, theme.space("s")))
        self.batch_label = tk.StringVar()
        self._batch_combo = ttk.Combobox(buttons, textvariable=self.batch_label, state="readonly", width=14)
        self._batch_combo.pack(side="left", padx=(theme.space("l"), theme.space("s")))
        self._assign = widgets.Button(buttons, command=self.assign_selection)
        self._assign.pack(side="left")
        self._help = ttk.Label(self, wraplength=theme.wrap(), justify="left")
        self._help.pack(fill="x", pady=theme.space("s"))
        # packed before the table: when the window is limited to a small screen, the table yields the room
        self._status = self.status_line()
        self._status.pack(side="bottom", fill="x", pady=theme.space("s"))
        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", height=8, selectmode="extended")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        across = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=lambda *a: (scroll.set(*a), self._follow_editor()),
                            xscrollcommand=lambda *a: (across.set(*a), self._follow_editor()))
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        for column in COLUMNS:
            self.tree.column(column, width=theme.px(theme.MAPPING_COLUMNS[column]), stretch=column == "location")
        # one click on an editable cell opens its editor (a double click was not discovered)
        self._editable_under_pointer = widgets.bind_cell_editing(self.tree, EDITABLE_COLUMNS, self._open_editor)
        self.tree.bind("<ButtonRelease-1>", self._column_resized, add="+")
        self.tree.bind("<Configure>", lambda _: self._follow_editor(), add="+")
        self.tree.bind("<Configure>", lambda _: self._elide_locations(), add="+")
        widgets.bind_row_hover(self.tree)
        self._location_tip = widgets.Tooltip(self.tree, self._tip_under_pointer)
        self._elided_width: int | None = None  # the location column width the «…» were computed for
        self._message: tuple[str, dict] | None = None  # (code, values) redrawn in the current language
        self._skipped_files = 0
        # (preview list, language) in the table, compared with `is`: pending edits survive a language change
        self._shown: tuple[list, str] | None = None

    def refresh_texts(self) -> None:
        text = self.controller.text
        busy = "disabled" if self.controller.worker.busy else "normal"
        self._preview.configure(text=text("PREVIEW"), state=busy)
        self._load.configure(text=text("LOAD_MAPPING"), state=busy)
        self._save.configure(text=text("SAVE_MAPPING"), state=busy)
        classes = self.controller.state.classes or {}
        self._batch_combo.configure(values=("", *classes), state="readonly" if classes and busy == "normal" else "disabled")
        self._assign.configure(text=text("ASSIGN_LABEL_SELECTION"), state=busy if classes else "disabled")
        self._help.configure(text=text("MAPPING_HELP"))
        for column in COLUMNS:
            mark = f" {theme.EDIT_MARK}" if column in EDITABLE_COLUMNS else ""
            self.tree.heading(column, text=text(f"COL_{column}") + mark)
        self._show_message()
        self._fill()

    def _fill(self) -> None:
        preview, language = self.controller.state.preview, self.controller.language
        if self._shown is not None and self._shown[0] is preview and self._shown[1] == language:
            return
        same_preview, self._shown = self._shown is not None and self._shown[0] is preview, (preview, language)
        if same_preview:  # only the language changed: the cells keep the pending edits
            for index, row in enumerate(self.controller.state.preview):
                self.tree.set(str(index), "code", self.controller.text(f"CODE_{row.code}"))
            return
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.controller.state.preview):
            self.tree.insert("", "end", iid=str(index), values=(
                row.location.as_posix(), row.suffix or "", self.controller.text(f"CODE_{row.code}"),
                row.participant, row.session or "", row.label,
            ))
        widgets.stripe(self.tree)
        self._elide_locations(force=True)

    def _elide_locations(self, force: bool = False) -> None:
        """Paths longer than their column end with «…»; the tooltip shows them whole. Computed again only for new
        rows or a new column width (thousands of series: not on every <Configure> of the window)."""
        font = tkfont.nametofont("TkDefaultFont", root=self)
        width = int(self.tree.column("location", "width")) - theme.space("m")
        if width == self._elided_width and not force:
            return
        self._elided_width = width
        for index, row in enumerate(self.controller.state.preview):
            if self.tree.exists(str(index)):
                self.tree.set(str(index), "location", widgets.elide(row.location.as_posix(), font, width))

    def _column_resized(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) == "separator":  # not on every click: thousands of rows
            self._elide_locations()
            self._follow_editor()

    def _tip_under_pointer(self) -> str | None:
        """The whole path of a cut location cell, or the hint of an editable cell, under the pointer."""
        if self._editable_under_pointer():
            return self.controller.text("HINT_EDIT_CELL")
        return self._location_under_pointer()

    def _location_under_pointer(self) -> str | None:
        """The whole path of the cell under the pointer, only when it was cut."""
        x = self.tree.winfo_pointerx() - self.tree.winfo_rootx()
        y = self.tree.winfo_pointery() - self.tree.winfo_rooty()
        item = self.tree.identify_row(y)
        if not item or widgets.column_at(self.tree, item, x) != "location":
            return None
        whole = self.controller.state.preview[int(item)].location.as_posix()
        return whole if self.tree.set(item, "location") != whole else None

    def _show_message(self) -> None:
        if self._message is None:
            self._status.configure(text="")
        else:
            code, values = self._message
            self._status.configure(text=self.controller.text(code, **values), severity=messages.severity(code))

    def _say(self, code: str, **values: object) -> None:
        self._message = (code, values)
        self.refresh_texts()

    def run_preview(self) -> None:
        if self.controller.start_task(self.controller.preview_task(), activity="preview"):
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

    def assign_selection(self) -> None:
        indices = [int(item) for item in self.tree.selection()]
        check = self.controller.assign_mapping_label(indices, self.batch_label.get())
        if check.ok:
            for index in indices:  # shown until the next preview recomputes the table
                self.tree.set(str(index), "label", self.batch_label.get())
            self._message = ("MAPPING_ASSIGNED", check.values)
        else:
            self._message = (check.code, check.values)
        self._show_message()
        self.on_change()

    # --- cell editing -----------------------------------------------------------------------------

    def _open_editor(self, item: str, column: str) -> None:
        """One click (or Enter / F2) on an editable cell: its editor, a list already open for suffix and label."""
        if self.controller.worker.busy:
            return
        editor = self.start_edit(int(item), column)
        if isinstance(editor, ttk.Combobox):
            widgets.open_list(editor)

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
        editor.bind("<Escape>", lambda _: self._close_editor(refocus=True))
        if isinstance(editor, ttk.Entry) and not isinstance(editor, ttk.Combobox):  # free text: kept on focus loss
            editor.bind("<FocusOut>", lambda _: self.after_idle(self._focus_left, editor))
        editor.bind("<<ComboboxSelected>>", lambda _: self.commit_edit(index, column, editor.get()))
        self._editor, self._editing = editor, (index, column)
        return editor

    def commit_edit(self, index: int, column: str, value: str) -> None:
        self._close_editor()
        check = self.controller.edit_mapping(index, column, value)
        if check.ok:
            self.tree.set(str(index), column, value)  # shown until the next preview recomputes the table
            self._message = ("EDIT_PENDING", {})
        else:
            self._message = (check.code, check.values)
        self._show_message()
        self.on_change()

    def finish_edit(self) -> None:
        """Click elsewhere, Tab or a step change: free text is stored, a list is closed (Esc cancels)."""
        editor = self._editor
        if isinstance(editor, ttk.Combobox) or editor is None:
            self._close_editor()
        else:
            self.commit_edit(*self._editing, editor.get())

    def _focus_left(self, editor: tk.Widget) -> None:
        """The focus went to another widget of the window: the text is stored. Another program taking the focus
        (Alt+Tab, a notification) keeps the editor open, so coming back goes on typing."""
        try:
            focus = self.focus_get()
        except KeyError:  # Tkinter cannot name the popdown of an open list: still inside the window
            focus = self
        if self._editor is editor and focus is not None and focus is not editor:
            self.finish_edit()

    def _follow_editor(self) -> None:
        """The table scrolled or a column moved: the editor goes with its cell, or is finished if it left view."""
        if self._editor is None:
            return
        box = self.tree.bbox(str(self._editing[0]), self._editing[1])
        if box:
            self._editor.place(x=box[0], y=box[1], width=box[2], height=box[3])
        else:
            self.finish_edit()

    def _close_editor(self, refocus: bool = False) -> None:
        if self._editor is not None:
            editor, self._editor = self._editor, None
            editor.destroy()
            if refocus:  # Esc: back to the table, with its selection
                self.tree.focus_set()
