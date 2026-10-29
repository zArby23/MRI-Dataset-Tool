"""Shared pytest setup: retry a Tk root whose library files could not be read (a transient failure), and keep
the display scaling and the GUI theme scale of one test from leaking into the next."""

import time
import tkinter
import warnings

import pytest

from mri_dataset_tool.presentation.gui import theme

# Observed in full runs on Windows under load: a new Tk interpreter sometimes cannot read its own existing
# library files ("couldn't read file .../tk8.6/panedwindow.tcl", "invalid command name tcl_findLibrary").
TK_LOAD_ERRORS = ("usable tk.tcl", "usable init.tcl", "tcl_findLibrary", "couldn't read file")
ATTEMPTS, PAUSE_S = 3, 0.2
# `tk scaling` belongs to the display and survives one Tk root: a test that simulates 125 % would hand it to the
# next root, whose default fonts are computed from it. Every root starts from the first one's value.
DEFAULT_TK_SCALING: list[float] = []


class TkLoadRetryWarning(UserWarning):
    """A Tk root was created again after its library failed to load (shown in the pytest summary)."""


def pytest_configure(config) -> None:
    original = tkinter.Tk.__init__

    def init(self, *args, **kwargs) -> None:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                original(self, *args, **kwargs)
                if not DEFAULT_TK_SCALING:
                    DEFAULT_TK_SCALING.append(float(self.tk.call("tk", "scaling")))
                else:
                    self.tk.call("tk", "scaling", DEFAULT_TK_SCALING[0])
                return
            except tkinter.TclError as error:  # "no display name" and any other error are not retried
                if attempt == ATTEMPTS or not any(text in str(error) for text in TK_LOAD_ERRORS):
                    raise
                warnings.warn(f"Tk library load failed; retry {attempt} of {ATTEMPTS - 1}.", TkLoadRetryWarning)
                time.sleep(PAUSE_S)

    tkinter.Tk.__init__ = init


@pytest.fixture(autouse=True)
def restore_theme_scale():
    """``theme._scale`` / ``_current`` are module globals set by ``apply_theme``: restored after each test."""
    scale, current = theme._scale, theme._current
    yield
    theme._scale, theme._current = scale, current
