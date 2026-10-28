"""One view per wizard step; views only draw and delegate to the controller."""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from mri_dataset_tool.presentation.gui import theme, widgets
from mri_dataset_tool.presentation.gui.controller import Controller
from mri_dataset_tool.presentation.gui.worker import Event


class StepView(ttk.Frame):
    """Base of the step views. *on_change* asks the window to redraw (e.g. after a validation)."""

    def __init__(self, master, controller: Controller, step: str, on_change: Callable[[], None]) -> None:
        super().__init__(master, padding=theme.space("m"))
        self.controller, self.step, self.on_change = controller, step, on_change
        self.build()
        self.refresh_texts()

    def build(self) -> None:
        self._placeholder = ttk.Label(self)
        self._placeholder.pack(anchor="w")

    def refresh_texts(self) -> None:
        """Redraw every text in the current language."""
        self._placeholder.configure(text=self.controller.text("STEP_PENDING"))

    def on_event(self, event: Event) -> None:
        """A worker event while this step is shown."""

    def focus_first(self) -> None:
        """Give the keyboard focus to the first control of the step (the next in Tab order after the step)."""
        self.update_idletasks()  # Tab order skips widgets not mapped yet: finish laying out the step first
        target = self.tk.call("tk_focusNext", str(self))
        if target and str(target).startswith(str(self)):
            self.nametowidget(str(target)).focus_set()

    def status_line(self, master: tk.Misc | None = None) -> widgets.StatusLine:
        """A message line with the severity icon, prefix and color, in the current language."""
        return widgets.StatusLine(master or self, lambda: {severity: self.controller.text(f"PREFIX_{severity}")
                                                           for severity in ("error", "warning", "ok")})

    def invalidate_on_edit(self, *variables: tk.Variable) -> None:
        """Editing any of *variables* invalidates this step until it is validated again."""
        for variable in variables:
            variable.trace_add("write", lambda *_: self._edited())

    def _edited(self) -> None:
        self.controller.reopen(self.step)
        self.on_change()
