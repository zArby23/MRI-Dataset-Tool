"""Main window of the wizard: ``mri-dataset-gui`` or ``python -m mri_dataset_tool.presentation.gui``."""

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from mri_dataset_tool.application.services.session_key import ensure_session_key
from mri_dataset_tool.presentation.gui import messages
from mri_dataset_tool.presentation.gui.controller import STEPS, Controller
from mri_dataset_tool.presentation.gui.views import StepView
from mri_dataset_tool.presentation.gui.views.config_step import ConfigStep
from mri_dataset_tool.presentation.gui.views.input_step import InputStep
from mri_dataset_tool.presentation.gui.views.labels_step import LabelsStep
from mri_dataset_tool.presentation.gui.views.mapping_step import MappingStep
from mri_dataset_tool.presentation.gui.views.run_step import RunStep

VIEWS = {"input": InputStep, "config": ConfigStep, "mapping": MappingStep, "run": RunStep,
         "labels": LabelsStep}  # the other steps: placeholders until built

POLL_MS = 100

logger = logging.getLogger(__name__)


class App(tk.Tk):
    def __init__(self, controller: Controller | None = None) -> None:
        super().__init__()
        self.controller = controller or Controller()
        self.minsize(720, 480)
        self._language = tk.StringVar(value=self.controller.language)
        self._build_menu()
        self._header = ttk.Label(self, padding=(12, 12, 12, 0), font=("TkDefaultFont", 12, "bold"))
        self._header.pack(fill="x")
        self._body = ttk.Frame(self)
        self._body.pack(fill="both", expand=True)
        buttons = ttk.Frame(self, padding=12)
        buttons.pack(fill="x")
        self._status = ttk.Label(buttons, foreground="#a00000")  # an unexpected error in a callback
        self._status.pack(side="left")
        self._callback_error: str | None = None  # type name of the last callback that raised
        self._next = ttk.Button(buttons, command=self._go_next)
        self._next.pack(side="right")
        self._back = ttk.Button(buttons, command=self._go_back)
        self._back.pack(side="right", padx=(0, 6))
        self.views = {step: VIEWS.get(step, StepView)(self._body, self.controller, step, self.refresh) for step in STEPS}
        self.protocol("WM_DELETE_WINDOW", self.request_close)
        self.refresh()
        self.after(POLL_MS, self._poll)

    def _build_menu(self) -> None:
        self._menubar = tk.Menu(self, tearoff=False)
        self._language_menu = tk.Menu(self._menubar, tearoff=False)
        for language in messages.LANGUAGES:
            self._language_menu.add_radiobutton(variable=self._language, value=language, command=self._set_language)
        self._menubar.add_cascade(menu=self._language_menu)
        self.configure(menu=self._menubar)

    def refresh(self) -> None:
        """Redraw texts, the current step and the navigation buttons."""
        text = self.controller.text
        self.title(text("APP_TITLE"))
        self._menubar.entryconfigure(0, label=text("MENU_LANGUAGE"))
        for index, language in enumerate(messages.LANGUAGES):
            self._language_menu.entryconfigure(index, label=text(f"LANGUAGE_{language}"))
        self._header.configure(text=self.controller.step_header())
        self._status.configure(
            text="" if self._callback_error is None else text("UNEXPECTED", error_type=self._callback_error))
        self._back.configure(text=text("BACK"), state="normal" if self.controller.can_go_back() else "disabled")
        self._next.configure(text=text("NEXT"), state="normal" if self.controller.can_go_next() else "disabled")
        for step, view in self.views.items():  # shown first: a view may load its data when shown
            if step == self.controller.step:
                view.pack(fill="both", expand=True)
            else:
                view.pack_forget()
            view.refresh_texts()

    def _set_language(self) -> None:
        self.controller.set_language(self._language.get())
        self.refresh()

    def _go_next(self) -> None:
        self.controller.go_next()
        self.refresh()

    def _go_back(self) -> None:
        self.controller.go_back()
        self.refresh()

    def _poll(self) -> None:
        events = self.controller.poll()
        for event in events:
            self.views[self.controller.step].on_event(event)
        if events:
            self.refresh()
        self.after(POLL_MS, self._poll)

    def report_callback_exception(self, exc, val, tb) -> None:
        """A callback raised: log and show only its type (the message or traceback may name a file)."""
        logger.warning("GUI callback failed (%s)", exc.__name__)
        self._callback_error = exc.__name__
        try:
            self.refresh()
        except Exception as error:  # never raise from the error handler itself
            logger.warning("GUI refresh failed (%s)", type(error).__name__)

    def request_close(self) -> None:
        warning = self.controller.close_warning()
        if warning is None or messagebox.askokcancel(self.controller.text("CLOSE_TITLE"), warning, parent=self):
            self.destroy()


def main() -> None:
    controller = Controller()
    controller.state.key_defined = ensure_session_key()  # a new key each start unless MRI_ANON_KEY is set
    App(controller).mainloop()
