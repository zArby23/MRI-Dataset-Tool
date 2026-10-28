"""Modal dialogs drawn with the theme (instead of the native ``messagebox``); the file choosers stay native.

``ask_ok_cancel`` is the single point for every confirmation: callers use it through this module
(``dialogs.ask_ok_cancel(...)``) so a test can replace it.
"""

import tkinter as tk
from collections.abc import Sequence
from tkinter import ttk

from mri_dataset_tool.presentation.gui import theme, widgets


class _Dialog(tk.Toplevel):
    """A modal window over *parent*, centered on it; Esc closes it with *cancel_value*."""

    def __init__(self, parent: tk.Misc, title: str, cancel_value: object) -> None:
        super().__init__(parent)
        self.withdraw()  # placed before it is shown
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.configure(background=theme.color("bg"))
        self.result = cancel_value
        self.protocol("WM_DELETE_WINDOW", lambda: self.close(cancel_value))
        self.bind("<Escape>", lambda _: self.close(cancel_value))
        self.body = ttk.Frame(self, padding=theme.space("l"))
        self.body.pack(fill="both", expand=True)
        self.buttons = ttk.Frame(self.body)

    def add_buttons(self, choices: Sequence[tuple[str, object, bool]]) -> list[widgets.RoundedButton]:
        """(text, value, primary) from right to left; Enter activates the primary one."""
        self.buttons.pack(side="bottom", fill="x", pady=(theme.space("l"), 0))
        made = []
        for text, value, primary in choices:
            button = widgets.Button(self.buttons, text=text, primary=primary, command=lambda v=value: self.close(v))
            button.pack(side="right", padx=(theme.space("s"), 0))
            if primary:
                self.bind("<Return>", lambda _, b=button: b.invoke())
            made.append(button)
        return made

    def show(self, focus: tk.Misc) -> object:
        parent = self.master.winfo_toplevel()
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.grab_set()
        focus.focus_force()  # a modal dialog takes the keyboard focus even if the window had lost it
        self.wait_window()
        return self.result

    def close(self, value: object) -> None:
        self.result = value
        self.grab_release()
        self.destroy()


def ask_ok_cancel(title: str, text: str, parent: tk.Misc | None = None, ok_text: str = "OK",
                  cancel_text: str = "Cancel") -> bool:
    """Ask a yes/no question (the decision ``messagebox.askokcancel`` took); ``True`` = accepted."""
    dialog = _Dialog(parent or tk._default_root, title, False)
    ttk.Label(dialog.body, text=text, wraplength=theme.size("dialog_wrap"), justify="left").pack(anchor="w")
    accept, _ = dialog.add_buttons([(ok_text, True, True), (cancel_text, False, False)])
    return bool(dialog.show(accept))


def show_sections(parent: tk.Misc, title: str, sections: Sequence[tuple[str, str, Sequence[str]]],
                  close_text: str, section: str | None = None) -> None:
    """Show read-only *sections* ``(key, heading, paragraphs)`` with bold headings, scrolled to *section*."""
    dialog = _Dialog(parent, title, None)
    frame = ttk.Frame(dialog.body)
    frame.pack(fill="both", expand=True)
    text = tk.Text(frame, wrap="word", width=theme.DIALOG_TEXT[0], height=theme.DIALOG_TEXT[1], padx=theme.space("m"), pady=theme.space("s"),
                   font="TkDefaultFont", cursor="arrow")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    text.tag_configure("heading", font="MRIStepCurrent", spacing1=theme.space("s"), spacing3=theme.space("xs"))
    text.tag_configure("paragraph", spacing3=theme.space("s"))
    for key, heading, paragraphs in sections:
        text.mark_set(key, "end-1c")
        text.mark_gravity(key, "left")
        text.insert("end", heading + "\n", "heading")
        for paragraph in paragraphs:
            text.insert("end", paragraph + "\n", "paragraph")
    text.configure(state="disabled")
    theme.recolor(text)  # a tk.Text does not follow the ttk style
    (close,) = dialog.add_buttons([(close_text, None, True)])
    dialog.update_idletasks()
    if section is not None:
        text.yview(section)
    dialog.dialog_text = text  # for tests: what the dialog shows and where it is scrolled
    dialog.show(close)
