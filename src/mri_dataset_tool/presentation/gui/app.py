"""Main window of the wizard: ``mri-dataset-gui`` or ``python -m mri_dataset_tool.presentation.gui``.

The frame: a header with the name and the step indicator, the current step, the navigation and a footer
with the language, the theme and the privacy notice. ``main`` shows a welcome panel while a thread imports
the services (seconds on a cold start) and sets the session key; the controller and the step views are
imported only then, so this module stays light.
"""

import logging
import threading
import tkinter as tk
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from tkinter import ttk
from typing import TYPE_CHECKING

from mri_dataset_tool.presentation.gui import dialogs, messages, theme, widgets

if TYPE_CHECKING:
    from mri_dataset_tool.presentation.gui.controller import Controller

POLL_MS = 100

logger = logging.getLogger(__name__)

Startup = Callable[[], Callable[[], "Controller"]]  # runs in a thread; returns the controller factory (main thread)


def _views() -> dict:
    from mri_dataset_tool.presentation.gui.views.config_step import ConfigStep
    from mri_dataset_tool.presentation.gui.views.export_step import ExportStep
    from mri_dataset_tool.presentation.gui.views.input_step import InputStep
    from mri_dataset_tool.presentation.gui.views.labels_step import LabelsStep
    from mri_dataset_tool.presentation.gui.views.mapping_step import MappingStep
    from mri_dataset_tool.presentation.gui.views.run_step import RunStep

    return {"input": InputStep, "config": ConfigStep, "mapping": MappingStep, "run": RunStep,
            "labels": LabelsStep, "export": ExportStep}


def app_version() -> str | None:
    try:
        return version("mri-dataset-tool")
    except PackageNotFoundError:
        return None


def load_services() -> Callable[[], "Controller"]:
    """The startup work (worker thread, no Tk): import the services and views, set the session key."""
    from mri_dataset_tool.application.services.session_key import ensure_session_key
    from mri_dataset_tool.presentation.gui.controller import Controller

    _views()
    key_defined = ensure_session_key()  # a new key each start unless MRI_ANON_KEY is set

    def make() -> Controller:
        controller = Controller()
        controller.state.key_defined = key_defined
        return controller

    return make


def _run_startup(startup: Startup, holder: list[tuple]) -> None:
    """The startup thread: never touches Tk nor holds the window; the main thread reads *holder*."""
    try:
        holder.append(("ok", startup()))
    except Exception as error:  # only the type: the message may name a file
        logger.warning("GUI startup failed (%s)", type(error).__name__)
        holder.append(("failed", type(error).__name__))


class App(tk.Tk):
    """``App(controller)`` builds the wizard at once; ``App(startup=...)`` shows the welcome panel until
    *startup* (run in a thread) returns the controller factory."""

    def __init__(self, controller: "Controller | None" = None, startup: Startup | None = None) -> None:
        super().__init__()
        self.controller: Controller | None = None
        self._after_id: str | None = None
        self.views: dict = {}
        self._language = tk.StringVar(value=messages.DEFAULT_LANGUAGE if controller is None else controller.language)
        self._theme = theme.DEFAULT_THEME
        theme.apply_theme(self, self._theme)
        self._place_window()
        self._callback_error: str | None = None  # type name of the last callback that raised
        self._build_frame()
        self.protocol("WM_DELETE_WINDOW", self.request_close)
        if startup is None:
            if controller is None:
                from mri_dataset_tool.presentation.gui.controller import Controller
                controller = Controller()
            self._start(controller)
        else:
            self._startup_result: tuple | None = None
            holder: list[tuple] = []  # filled by the thread, which never holds the window (Tk objects die in it)
            self._startup_holder = holder
            self._build_welcome()
            self.refresh()
            threading.Thread(target=_run_startup, args=(startup, holder), daemon=True).start()
            self._schedule(self._poll_startup)

    # --- frame ------------------------------------------------------------------------------------

    def _place_window(self) -> None:
        """A fixed size (design decision: no resizing nor maximizing), scaled with the display and centered;
        never larger than the screen (minus room for the taskbar)."""
        width = min(theme.px(theme.WINDOW[0]), self.winfo_screenwidth())
        height = min(theme.px(theme.WINDOW[1]), self.winfo_screenheight() - theme.px(theme.TASKBAR))
        x, y = (self.winfo_screenwidth() - width) // 2, (self.winfo_screenheight() - theme.px(theme.TASKBAR) - height) // 2
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        self.resizable(False, False)

    def _build_frame(self) -> None:
        m, s = theme.space("m"), theme.space("s")
        self._header_canvas = widgets.HeaderCanvas(self)  # the name and the steps over a gradient
        self._header_canvas.pack(side="top", fill="x")
        self._header = ttk.Label(self, style="StepTitle.TLabel", padding=(m, 0, m, 0))
        self._header.pack(side="top", fill="x")

        footer = ttk.Frame(self, style="Footer.TFrame", padding=(m, theme.space("xs")))
        footer.pack(side="bottom", fill="x")
        self._privacy = widgets.Button(footer, command=self.show_privacy)
        self._privacy.pack(side="right")
        self._theme_combo = ttk.Combobox(footer, state="readonly", width=10)
        self._theme_combo.pack(side="right", padx=(theme.space("xs"), m))
        self._theme_combo.bind("<<ComboboxSelected>>", lambda _: self._set_theme(theme.THEMES[self._theme_combo.current()]))
        self._theme_label = ttk.Label(footer, style="Footer.TLabel")
        self._theme_label.pack(side="right")
        self._language_combo = ttk.Combobox(footer, state="readonly", width=10)
        self._language_combo.pack(side="right", padx=(theme.space("xs"), m))
        self._language_combo.bind("<<ComboboxSelected>>", self._language_chosen)
        self._language_label = ttk.Label(footer, style="Footer.TLabel")
        self._language_label.pack(side="right")
        # the activity of the running task; idle: an empty bar the color of the footer, so the height never changes
        # its own row of the footer: at 800 px the selectors leave no room for a stage with its counts
        activity = ttk.Frame(self, style="Footer.TFrame", padding=(m, theme.space("xs"), m, 0))
        activity.pack(side="bottom", fill="x")
        self._activity_bar = ttk.Progressbar(activity, style="Footer.Horizontal.TProgressbar", mode="determinate",
                                             length=theme.size("activity_bar"))
        self._activity_bar.pack(side="left")
        self._activity = ttk.Label(activity, style="Footer.TLabel", anchor="w")
        self._activity.pack(side="left", fill="x", expand=True, padx=(theme.space("s"), theme.space("m")))
        self._activity_running = False
        ttk.Separator(self).pack(side="bottom", fill="x")

        buttons = ttk.Frame(self, padding=m)
        buttons.pack(side="bottom", fill="x")
        self._status = widgets.StatusLine(buttons, lambda: {severity: self._text(f"PREFIX_{severity}")
                                                            for severity in ("error", "warning", "ok")},
                                          wraplength=theme.size("status_wrap"))  # an unexpected error in a callback
        self._status.pack(side="left")
        self._next = widgets.Button(buttons, primary=True, icon="next", command=self._go_next)
        self._next.pack(side="right")
        self._back = widgets.Button(buttons, icon="back", command=self._go_back)
        self._back.pack(side="right", padx=(0, s))
        ttk.Separator(self).pack(side="bottom", fill="x")

        self._body = ttk.Frame(self)
        self._body.pack(fill="both", expand=True)

    def _build_welcome(self) -> None:
        """A card centered over the header gradient (the header and the step title are hidden meanwhile)."""
        self._header_canvas.pack_forget()
        self._header.pack_forget()
        self._welcome = widgets.GradientCanvas(self._body)
        self._welcome.pack(fill="both", expand=True)
        card = ttk.Frame(self._welcome, style="Card.TFrame", padding=theme.space("xl"))
        self._welcome.place_card(card)
        self._welcome_name = ttk.Label(card, style="Card.AppName.TLabel")
        self._welcome_subtitle = ttk.Label(card, style="Card.TLabel")
        self._welcome_version = ttk.Label(card, style="Card.Muted.TLabel")
        self._welcome_progress = ttk.Progressbar(card, mode="indeterminate", length=theme.size("welcome_bar"))
        self._welcome_status = ttk.Label(card, style="Card.TLabel")
        for widget in (self._welcome_name, self._welcome_subtitle, self._welcome_version):
            widget.pack(anchor="center", pady=(0, theme.space("xs")))
        self._welcome_progress.pack(anchor="center", pady=(theme.space("l"), theme.space("s")))
        self._welcome_status.pack(anchor="center")
        ttk.Separator(card).pack(fill="x", pady=theme.space("l"))
        self._welcome_privacy = ttk.Label(card, style="Card.Muted.TLabel", wraplength=theme.size("card_wrap"), justify="center")
        self._welcome_privacy.pack(anchor="center")
        self._welcome_link = widgets.Link(card, style="Card.Link.TLabel", command=self.show_privacy)
        self._welcome_link.pack(anchor="center", pady=(theme.space("xs"), 0))
        self._welcome_close = widgets.Button(card, command=self.destroy)  # shown if the startup fails
        self._welcome_progress.start(theme.BAR_STEP_MS)

    def _start(self, controller: "Controller") -> None:
        """Build the steps (main thread); the welcome panel, if any, goes away."""
        self.controller = controller
        controller.set_language(self._language.get())
        if getattr(self, "_welcome", None) is not None:
            self._welcome_progress.stop()  # its timer must not outlive the bar
            self._welcome.destroy()
            self._welcome = None
            self._header_canvas.pack(side="top", fill="x", before=self._body)
            self._header.pack(side="top", fill="x", before=self._body)
        from mri_dataset_tool.presentation.gui.controller import STEPS
        from mri_dataset_tool.presentation.gui.views import StepView

        views = _views()
        self.views = {step: views.get(step, StepView)(self._body, controller, step, self.refresh) for step in STEPS}
        theme.apply_theme(self, self._theme)  # again: the lists, text boxes and tables of the views are new
        self.refresh()
        self._schedule(self._poll)

    def _schedule(self, callback: Callable[[], None]) -> None:
        """The single pending poll (a direct call of ``_poll`` replaces it); ``destroy`` cancels it."""
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self._after_id = self.after(POLL_MS, callback)

    def destroy(self) -> None:
        """Cancel the poll and stop the animated bars first: their pending Tcl timers would run on a
        destroyed window and print errors."""
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        for bar in (getattr(self, "_welcome_progress", None), getattr(self, "_activity_bar", None)):
            if bar is not None and bar.winfo_exists():
                bar.stop()
        super().destroy()

    # --- startup (welcome) ------------------------------------------------------------------------

    def _poll_startup(self) -> None:
        self._after_id = None
        if not self._startup_holder:
            self._schedule(self._poll_startup)
            return
        outcome, value = self._startup_result = self._startup_holder[0]
        if outcome == "ok":
            try:
                self._start(value())
                return
            except Exception as error:
                logger.warning("GUI startup failed (%s)", type(error).__name__)
                value = type(error).__name__
        self._welcome_progress.stop()
        self._welcome_progress.pack_forget()
        self._welcome_status.configure(style="Error.TLabel",
                                       text=messages.text("STARTUP_FAILED", self._language.get(), error_type=value))
        self._welcome_close.pack(anchor="center", pady=(theme.space("s"), 0))

    # --- redraw -----------------------------------------------------------------------------------

    def _text(self, code: str, **values: object) -> str:
        return messages.text(code, self._language.get(), **values)

    def refresh(self) -> None:
        """Redraw texts, the step indicator, the current step and the navigation buttons."""
        text = self._text
        self.title(text("APP_NAME") if self.controller is None
                   else text("APP_TITLE_STEP", header=self.controller.step_header()))
        self._language_label.configure(text=text("MENU_LANGUAGE"))
        self._language_combo.configure(values=[text(f"LANGUAGE_{language}") for language in messages.LANGUAGES])
        self._language_combo.current(messages.LANGUAGES.index(self._language.get()))
        self._theme_label.configure(text=text("THEME_LABEL"))
        self._theme_combo.configure(values=[text(f"THEME_{name}") for name in theme.THEMES])
        self._theme_combo.current(theme.THEMES.index(self._theme))
        self._privacy.configure(text=text("PRIVACY_BUTTON"))
        self._status.configure(
            text="" if self._callback_error is None else text("UNEXPECTED", error_type=self._callback_error),
            severity="error")
        if self.controller is None:
            self._header_canvas.set_content(text("APP_NAME"), [])
            self._refresh_welcome()
            for button, code in ((self._back, "BACK"), (self._next, "NEXT")):
                button.configure(text=text(code), state="disabled")
            return
        self._refresh_steps()
        self._refresh_activity()
        self._header.configure(text=self.controller.step_header())
        self._back.configure(text=text("BACK"), state="normal" if self.controller.can_go_back() else "disabled")
        self._next.configure(text=text("NEXT"), state="normal" if self.controller.can_go_next() else "disabled")
        for step, view in self.views.items():  # shown first: a view may load its data when shown
            if step == self.controller.step:
                view.pack(fill="both", expand=True)
            else:
                view.pack_forget()
            view.refresh_texts()

    def _refresh_steps(self) -> None:
        """The steps of the current format: «n Name», with a mark when done (not color alone)."""
        steps = []
        for number, (step, state) in enumerate(self.controller.step_states(), start=1):
            name = f"{number} {self._text(f'STEP_{step}')}"
            steps.append((step, f"{name} {theme.DONE_MARK}" if state == "done" else name, state))
        self._header_canvas.set_content(self._text("APP_NAME"), steps)

    def _refresh_activity(self) -> None:
        """The footer indicator from ``controller.activity`` (fed by the worker events: codes and counts)."""
        active = self.controller.activity.task is not None
        if active != self._activity_running:
            if active:
                self._activity_bar.configure(mode="indeterminate")
                self._activity_bar.start(theme.BAR_STEP_MS)
            else:  # determinate at 0: an empty trough (a stopped indeterminate bar keeps its block)
                self._activity_bar.stop()
                self._activity_bar.configure(mode="determinate", value=0)
            self._activity_running = active
        self._activity.configure(text=self.controller.activity_text())

    def _refresh_welcome(self) -> None:
        if getattr(self, "_welcome", None) is None:
            return
        text, number = self._text, app_version()
        self._welcome_name.configure(text=text("APP_NAME"))
        self._welcome_subtitle.configure(text=text("WELCOME_SUBTITLE"))
        self._welcome_version.configure(text=text("VERSION", version=number or text("VERSION_UNKNOWN")))
        self._welcome_privacy.configure(text=text("PRIVACY_SUMMARY"))
        self._welcome_link.configure(text=text("MORE_INFO"))
        if self._startup_result is None:
            self._welcome_status.configure(text=text("LOADING"))
        self._welcome_close.configure(text=text("CLOSE"))

    # --- footer and navigation --------------------------------------------------------------------

    def _language_chosen(self, _event=None) -> None:
        self._language.set(messages.LANGUAGES[self._language_combo.current()])
        self._set_language()

    def _set_language(self) -> None:
        if self.controller is not None:
            self.controller.set_language(self._language.get())
        self.refresh()

    def _set_theme(self, name: str) -> None:
        self._theme = name
        theme.apply_theme(self, name)
        self.refresh()

    def privacy_sections(self) -> list[tuple[str, str, list[str]]]:
        """The two sections of the «Privacy and memory use» dialog (a single source: ``messages``)."""
        text = self._text
        return [("privacy", text("PRIVACY_HEADING"), [text(f"PRIVACY_{part}") for part in ("LEAD", 1, 2, 3, 4)]),
                ("memory", text("MEMORY_TITLE"), [text(f"MEMORY_{n}") for n in (1, 2, 3)])]

    def show_privacy(self, section: str | None = None) -> None:
        """The privacy and memory dialog, scrolled to *section* (``"memory"`` from the step 2 link)."""
        dialogs.show_sections(self, self._text("PRIVACY_TITLE"), self.privacy_sections(), self._text("CLOSE"),
                              section)

    def _go_next(self) -> None:
        self.controller.go_next()
        self.refresh()

    def _go_back(self) -> None:
        self.controller.go_back()
        self.refresh()

    # --- events and closing -----------------------------------------------------------------------

    def _poll(self) -> None:
        try:
            events = self.controller.poll()
            for event in events:
                try:
                    self.views[self.controller.step].on_event(event)
                except Exception as error:  # one failing event must not hide the next ones
                    self.report_callback_exception(type(error), error, error.__traceback__)
            if events:
                self.refresh()
        finally:  # never stop polling: else busy stays True for good
            self._schedule(self._poll)

    def report_callback_exception(self, exc, val, tb) -> None:
        """A callback raised: log and show only its type (the message or traceback may name a file)."""
        logger.warning("GUI callback failed (%s)", exc.__name__)
        self._callback_error = exc.__name__
        try:
            self.refresh()
        except Exception as error:  # never raise from the error handler itself
            logger.warning("GUI refresh failed (%s)", type(error).__name__)

    def ask(self, title_code: str, text: str) -> bool:
        """A themed OK/Cancel question (through the module attribute: tests replace ``dialogs.ask_ok_cancel``)."""
        return dialogs.ask_ok_cancel(self._text(title_code), text, parent=self, ok_text=self._text("DIALOG_OK"),
                                     cancel_text=self._text("DIALOG_CANCEL"))

    def request_close(self, confirm: bool = False) -> None:
        """Close the window: the X asks only while a task runs; the «Close» button (*confirm*) always asks."""
        if self.controller is None:
            self.destroy()
            return
        question = self.controller.close_question(confirm)
        if question is None or self.ask(question[0], self._text(question[1])):
            self.destroy()


def main() -> None:
    App(startup=load_services).mainloop()
