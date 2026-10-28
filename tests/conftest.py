"""Shared pytest setup: retry a Tk root whose library files could not be read (a transient failure)."""

import time
import tkinter
import warnings

# Observed in full runs on Windows under load: a new Tk interpreter sometimes cannot read its own existing
# library files ("couldn't read file .../tk8.6/panedwindow.tcl", "invalid command name tcl_findLibrary").
TK_LOAD_ERRORS = ("usable tk.tcl", "usable init.tcl", "tcl_findLibrary", "couldn't read file")
ATTEMPTS, PAUSE_S = 3, 0.2


class TkLoadRetryWarning(UserWarning):
    """A Tk root was created again after its library failed to load (shown in the pytest summary)."""


def pytest_configure(config) -> None:
    original = tkinter.Tk.__init__

    def init(self, *args, **kwargs) -> None:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return original(self, *args, **kwargs)
            except tkinter.TclError as error:  # "no display name" and any other error are not retried
                if attempt == ATTEMPTS or not any(text in str(error) for text in TK_LOAD_ERRORS):
                    raise
                warnings.warn(f"Tk library load failed; retry {attempt} of {ATTEMPTS - 1}.", TkLoadRetryWarning)
                time.sleep(PAUSE_S)

    tkinter.Tk.__init__ = init
