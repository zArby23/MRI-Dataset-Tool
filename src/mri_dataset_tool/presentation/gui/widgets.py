"""Widgets drawn with the theme: rounded buttons, the step pills, gradients, vector icons, links, tooltips,
status lines with an icon, selectable cards and the hover and «…» of table cells.

Colors and sizes come from ``theme``; ``theme.apply_theme`` calls ``retheme`` on the drawn ones. The views
create buttons with ``Button``: pointing it back to ``ttk.Button`` drops the rounded corners without touching them.
"""

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import font as tkfont
from tkinter import ttk

from mri_dataset_tool.presentation.gui import theme

ICONS = ("error", "warning", "ok", "info", "next", "back", "close")


def _rounded(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, r: float, **options) -> int:
    """A rounded rectangle as a smoothed polygon (the corner points are doubled so the sides stay straight)."""
    points = (x0 + r, y0, x0 + r, y0, x1 - r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y0 + r, x1, y1 - r,
              x1, y1 - r, x1, y1, x1 - r, y1, x1 - r, y1, x0 + r, y1, x0 + r, y1, x0, y1, x0, y1 - r,
              x0, y1 - r, x0, y0 + r, x0, y0 + r, x0, y0)
    return canvas.create_polygon(points, smooth=True, **options)


def _background(widget: tk.Misc) -> str:
    """The background of a ttk parent (its style or class), so a canvas blends in."""
    parent = widget.master
    try:
        style = str(parent.cget("style")) or parent.winfo_class()
        return ttk.Style(widget).lookup(style, "background") or theme.color("bg")
    except tk.TclError:  # not a ttk widget
        return theme.color("bg")


def icon_lines(kind: str, size: float) -> list[tuple[str, tuple[float, ...]]]:
    """The strokes of icon *kind* in a *size* box: ``("oval"|"line"|"poly", coordinates)``. Pure data, so every
    shape is tested to stay inside its box without a display."""
    s, m = size, size * 0.12  # m: the margin that keeps a stroke inside the box
    c = s / 2
    circle = ("oval", (m, m, s - m, s - m))
    shapes = {
        "error": [circle, ("line", (s * 0.35, s * 0.35, s * 0.65, s * 0.65)), ("line", (s * 0.65, s * 0.35, s * 0.35, s * 0.65))],
        "ok": [circle, ("line", (s * 0.30, s * 0.52, s * 0.45, s * 0.66, s * 0.70, s * 0.36))],
        "info": [circle, ("line", (c, s * 0.45, c, s * 0.72)), ("line", (c, s * 0.29, c, s * 0.33))],
        "warning": [("poly", (c, m, s - m, s - m, m, s - m)), ("line", (c, s * 0.40, c, s * 0.62)),
                    ("line", (c, s * 0.72, c, s * 0.76))],
        "next": [("line", (s * 0.38, s * 0.22, s * 0.66, c, s * 0.38, s * 0.78))],
        "back": [("line", (s * 0.62, s * 0.22, s * 0.34, c, s * 0.62, s * 0.78))],
        "close": [("line", (s * 0.28, s * 0.28, s * 0.72, s * 0.72)), ("line", (s * 0.72, s * 0.28, s * 0.28, s * 0.72))],
    }
    return shapes[kind]


def draw_icon(canvas: tk.Canvas, kind: str, x: float, y: float, size: float, color: str) -> None:
    """Draw icon *kind* with its top left corner at (x, y): strokes only, so it reads on any background."""
    width = max(1, round(size / 9))
    for shape, coords in icon_lines(kind, size):
        moved = [value + (x if i % 2 == 0 else y) for i, value in enumerate(coords)]
        if shape == "oval":
            canvas.create_oval(*moved, outline=color, width=width)
        elif shape == "poly":
            canvas.create_polygon(*moved, outline=color, fill="", width=width, joinstyle="round")
        else:
            canvas.create_line(*moved, fill=color, width=width, capstyle="round", joinstyle="round")


def elide(text: str, font: tkfont.Font, width: int) -> str:
    """*text* cut with «…» to fit *width* pixels (unchanged when it fits)."""
    if font.measure(text) <= width:
        return text
    low, high = 0, len(text)
    while low < high:  # the longest prefix that fits with the ellipsis
        middle = (low + high + 1) // 2
        if font.measure(text[:middle] + "…") <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…"


class RoundedButton(tk.Canvas):
    """A button with rounded corners that behaves like ``ttk.Button`` for the code around it: ``invoke``,
    ``configure``/``cget`` of ``text``, ``state`` and ``command``, ``state``/``instate``; Tab focus with a
    visible ring, Space and Enter activate it. *primary* fills it with the accent color. *icon* (``next``,
    ``back``, ``close``) is drawn beside the text; it replaces the «<»/«>» of the text, which ``cget`` keeps."""

    def __init__(self, master, text: str = "", command: Callable[[], object] | None = None, state: str = "normal",
                 primary: bool = False, style: str = "", icon: str | None = None, **options) -> None:
        super().__init__(master, highlightthickness=0, borderwidth=0, takefocus=1, **options)
        self._text, self._command, self._state, self._primary, self._icon = text, command, str(state), primary, icon
        self._hover = self._pressed = self._focus = False
        self._call = self.register(self._run)  # invoked through Tk: an error goes to report_callback_exception
        for sequence, handler in (("<Enter>", lambda _: self._set(hover=True)),
                                  ("<Leave>", lambda _: self._set(hover=False, pressed=False)),
                                  ("<ButtonPress-1>", self._press), ("<ButtonRelease-1>", self._release),
                                  ("<FocusIn>", lambda _: self._set(focus=True)),
                                  ("<FocusOut>", lambda _: self._set(focus=False)),
                                  ("<KeyPress-space>", self._key), ("<Return>", self._key), ("<KP_Enter>", self._key)):
            self.bind(sequence, handler)
        self._draw()

    def _key(self, _event) -> str:
        """Space or Enter on the focused button: it alone acts ("break": a dialog's Enter must not also run)."""
        self.invoke()
        return "break"

    # --- ttk.Button compatibility -----------------------------------------------------------------

    def invoke(self):
        if self._state == "disabled":
            return ""
        return self.tk.call(self._call)

    def _run(self):
        return None if self._command is None else self._command()

    def configure(self, cnf=None, **options):
        options = {**(cnf or {}), **options}
        if not options:
            return super().configure()
        for key in ("text", "command", "state", "style"):
            if key in options:
                value = options.pop(key)
                if key == "text":
                    self._text = str(value)
                elif key == "command":
                    self._command = value
                elif key == "state":
                    self._state = str(value)
        if options:
            super().configure(**options)
        self._draw()

    config = configure

    def cget(self, key: str):
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        if key == "command":
            return self._command
        if key == "style":
            return "Accent.TButton" if self._primary else "TButton"
        return super().cget(key)

    def __getitem__(self, key: str):
        return self.cget(key)

    def state(self, statespec=None):
        """ttk ``state``: only the ``disabled`` flag is kept."""
        if statespec is not None:
            for flag in statespec:
                if flag.lstrip("!") == "disabled":
                    self.configure(state="normal" if flag.startswith("!") else "disabled")
        return ("disabled",) if self._state == "disabled" else ()

    def instate(self, statespec) -> bool:
        disabled = self._state == "disabled"
        return all((flag.lstrip("!") != "disabled") or (disabled != flag.startswith("!")) for flag in statespec)

    # --- drawing ----------------------------------------------------------------------------------

    def retheme(self) -> None:
        self._draw()

    def shown_text(self) -> str:
        """The text drawn: without the «<»/«>» an arrow icon replaces."""
        if self._icon == "back":
            return self._text.removeprefix("<").strip()
        if self._icon == "next":
            return self._text.removesuffix(">").strip()
        return self._text

    def _set(self, **flags: bool) -> None:
        for name, value in flags.items():
            setattr(self, f"_{name}", value)
        self._draw()

    def _press(self, _event) -> None:
        if self._state != "disabled":
            self.focus_set()
            self._set(pressed=True)

    def _release(self, _event) -> None:
        clicked = self._pressed and self._hover
        self._set(pressed=False)
        if clicked:
            self.invoke()

    def _colors(self) -> tuple[str, str, str]:
        """(fill, outline, text) for the current state."""
        c = theme.color
        if self._state == "disabled":
            return c("bg"), c("border"), c("disabled")
        if self._primary:
            fill = c("accent_pressed") if self._pressed else c("accent_hover") if self._hover else c("accent_bg")
            return fill, fill, c("on_accent")
        fill = c("select_bg") if self._pressed else c("hover") if self._hover else c("surface")
        return fill, c("input_border"), c("text")

    def _draw(self) -> None:
        font = tkfont.nametofont("TkDefaultFont", root=self)
        ring, padx, pady = theme.size("focus_ring"), theme.space("m"), theme.space("xs")
        line = font.metrics("linespace")
        label = self.shown_text()
        icon = line if self._icon else 0
        gap = theme.space("xs") if self._icon and label else 0
        width = font.measure(label) + icon + gap + 2 * (padx + ring)
        height = line + 2 * (pady + ring)
        radius = min(theme.space("m"), (height - 2 * ring) // 2)  # clearly rounded, never past a pill
        super().configure(width=width, height=height, background=_background(self),
                          takefocus=0 if self._state == "disabled" else 1)
        self.delete("all")
        fill, outline, text = self._colors()
        if self._focus and self._state != "disabled":
            _rounded(self, 1, 1, width - 1, height - 1, radius + ring, fill="", outline=theme.color("focus"),
                     width=theme.size("focus_line"))
        _rounded(self, ring, ring, width - ring, height - ring, radius, fill=fill, outline=outline)
        x = ring + padx
        if self._icon and self._icon != "next":  # icon first
            draw_icon(self, self._icon, x, (height - icon) / 2, icon, text)
            x += icon + gap
        self.create_text(x, height / 2, anchor="w", text=label, fill=text, font=font)
        if self._icon == "next":
            draw_icon(self, "next", x + font.measure(label) + gap, (height - icon) / 2, icon, text)


Button = RoundedButton  # ttk.Button here brings back square buttons without touching the views


class GradientCanvas(tk.Canvas):
    """A canvas filled with the header gradient (``header_top`` to ``bg``), with a centered card on it."""

    def __init__(self, master) -> None:
        super().__init__(master, highlightthickness=0, borderwidth=0)
        self._card: int | None = None
        self.bind("<Configure>", lambda _: self._draw())

    def place_card(self, card: tk.Misc) -> None:
        self._card = self.create_window(0, 0, window=card, anchor="center")
        self._draw()

    def retheme(self) -> None:
        self._draw()

    def _draw(self) -> None:
        width, height = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        self.delete("gradient")
        start, end = theme.color("header_top"), theme.color("bg")
        for line in range(height):
            self.create_line(0, line, width, line, tags="gradient",
                             fill=theme.mix(start, end, min(1.0, line / max(height * 0.6, 1))))
        self.tag_lower("gradient")
        if self._card is not None:
            self.coords(self._card, width / 2, height * 0.45)


class HeaderCanvas(tk.Canvas):
    """The header: the app name and the step pills over a gradient from ``header_top`` to ``bg``. The current
    step is a filled pill in bold; a finished one ends with a check mark, so the state is not told by color
    alone. Pills that do not fit go to a second row."""

    STYLES = {"done": ("header_done", "TkDefaultFont"), "current": ("on_accent", "MRIStepCurrent"),
              "pending": ("header_muted", "TkDefaultFont")}

    def __init__(self, master) -> None:
        super().__init__(master, highlightthickness=0, borderwidth=0, height=1)
        self._name = ""
        self._steps: list[tuple[str, str, str]] = []  # (step, text, state)
        self._hover: str | None = None
        self._items: dict[str, tuple[int, str]] = {}  # step: (canvas text item, color token)
        self.bind("<Configure>", lambda _: self._draw())

    def set_content(self, name: str, steps: list[tuple[str, str, str]]) -> None:
        self._name, self._steps = name, steps
        self._draw()

    def step_texts(self) -> list[str]:
        return [text for _, text, _ in self._steps]

    def retheme(self) -> None:
        self._draw()

    def _hover_step(self, step: str | None) -> None:
        """Recolor only (a redraw would delete the item under the pointer and fire Enter again); the filled
        current pill keeps its text color."""
        self._hover = step
        for name, (item, token) in self._items.items():
            hovered = name == step and token != "on_accent"
            self.itemconfigure(item, fill=theme.color("header_hover" if hovered else token))

    def _draw(self) -> None:
        m, gap, padx = theme.space("m"), theme.space("s"), theme.space("s")
        width = max(self.winfo_width(), self.winfo_reqwidth())
        name_font = tkfont.nametofont("MRIAppName", root=self)
        row = tkfont.nametofont("TkDefaultFont", root=self).metrics("linespace") + 2 * theme.space("xs")
        top = m + name_font.metrics("linespace") + theme.space("xs")
        x, y, placed = m, top, []
        for step, text, state in self._steps:
            pill = tkfont.nametofont(self.STYLES[state][1], root=self).measure(text) + 2 * padx
            if x > m and x + pill > width - m:  # does not fit: next row
                x, y = m, y + row + theme.space("xs")
            placed.append((step, text, state, x, y, pill))
            x += pill + gap
        height = y + row + m
        if int(self.cget("height")) != height:
            self.configure(height=height)
        self.delete("all")
        start, end = theme.color("header_top"), theme.color("bg")
        for line in range(height):
            self.create_line(0, line, width, line, fill=theme.mix(start, end, line / max(height - 1, 1)))
        self.create_text(m, m, anchor="nw", text=self._name, font=name_font, fill=theme.color("header_text"))
        self._items = {}
        for step, text, state, x, y, pill in placed:
            token, font = self.STYLES[state]
            if state == "current":
                _rounded(self, x, y, x + pill, y + row, row // 2, fill=theme.color("accent_bg"), outline="")
            hovered = step == self._hover and state != "current"
            item = self.create_text(x + padx, y + row / 2, anchor="w", text=text, font=font,
                                    fill=theme.color("header_hover" if hovered else token))
            self._items[step] = (item, token)
            self.tag_bind(item, "<Enter>", lambda _, s=step: self._hover_step(s))
            self.tag_bind(item, "<Leave>", lambda _: self._hover_step(None))


class Link(ttk.Label):
    """Underlined accent text that runs *command* on click, Enter or Space; reachable with Tab."""

    def __init__(self, master, command: Callable[[], object], style: str = "Link.TLabel", **options) -> None:
        super().__init__(master, style=style, cursor="hand2", takefocus=1, **options)
        self._command = command
        for sequence in ("<Button-1>", "<Return>", "<KeyPress-space>"):
            self.bind(sequence, lambda _: self._command())
        self.bind("<Enter>", lambda _: self.state(["active"]))
        self.bind("<Leave>", lambda _: self.state(["!active"]))
        self.bind("<FocusIn>", lambda _: self.state(["active"]))
        self.bind("<FocusOut>", lambda _: self.state(["!active"]))


class Tooltip:
    """A small text box near *widget* after a short delay on hover or keyboard focus; Esc, leaving or losing
    the focus closes it. *text* may be a function (``None`` = nothing to show); it never takes the focus."""

    DELAY_MS = 400

    def __init__(self, widget: tk.Misc, text: str | Callable[[], str | None]) -> None:
        self.widget, self._text = widget, text
        self._after: str | None = None
        self.window: tk.Toplevel | None = None
        self._shown = ""
        for sequence in ("<Enter>", "<FocusIn>"):
            widget.bind(sequence, lambda _: self.schedule(), add="+")
        for sequence in ("<Leave>", "<FocusOut>", "<Escape>", "<ButtonPress>"):
            widget.bind(sequence, lambda _: self.hide(), add="+")
        widget.bind("<Motion>", lambda _: self._moved(), add="+")
        widget.bind("<Destroy>", lambda event: self.hide() if event.widget is widget else None, add="+")

    def text(self) -> str | None:
        return self._text() if callable(self._text) else self._text

    def _moved(self) -> None:
        if self.window is not None and self.text() != self._shown:  # another cell: another text
            self.hide()
            self.schedule()
        elif self.window is None and self._after is None:
            self.schedule()

    def schedule(self) -> None:
        self._cancel()
        self._after = self.widget.after(self.DELAY_MS, self.show)

    def _cancel(self) -> None:
        if self._after is not None:
            self.widget.after_cancel(self._after)
            self._after = None

    def show(self) -> None:
        self._after = None
        text = self.text()
        if not text or self.window is not None:
            return
        self._shown = text
        self.window = window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        tk.Label(window, text=text, justify="left", wraplength=theme.size("tooltip_wrap"), font="TkDefaultFont",
                 background=theme.color("surface"), foreground=theme.color("text"), padx=theme.space("s"),
                 pady=theme.space("xs"), highlightthickness=1, highlightbackground=theme.color("input_border"),
                 ).pack()
        x = self.widget.winfo_pointerx() if self.widget.winfo_containing(*self.widget.winfo_pointerxy()) \
            else self.widget.winfo_rootx()
        window.geometry(f"+{x + theme.size("tooltip_dx")}+{self.widget.winfo_rooty() + self.widget.winfo_height() + theme.size("tooltip_dy")}")

    def hide(self) -> None:
        self._cancel()
        if self.window is not None:
            self.window.destroy()
            self.window = None


class InfoIcon(tk.Canvas):
    """An ⓘ icon that shows *text* in a tooltip on hover and on keyboard focus (reachable with Tab)."""

    def __init__(self, master, text: Callable[[], str]) -> None:
        size = tkfont.nametofont("TkDefaultFont", root=master).metrics("linespace") + theme.size("icon_pad")
        super().__init__(master, width=size, height=size, highlightthickness=0, borderwidth=0, takefocus=1)
        self._size, self._focus = size, False
        self.tooltip = Tooltip(self, text)
        self.bind("<FocusIn>", lambda _: self._set_focus(True), add="+")
        self.bind("<FocusOut>", lambda _: self._set_focus(False), add="+")
        self._draw()

    def retheme(self) -> None:
        self._draw()

    def _set_focus(self, focus: bool) -> None:
        self._focus = focus
        self._draw()

    def _draw(self) -> None:
        self.configure(background=_background(self))
        self.delete("all")
        draw_icon(self, "info", 0, 0, self._size, theme.color("focus" if self._focus else "accent"))


class StatusLine(ttk.Frame):
    """A message with its severity: icon, «Error:»/«Aviso:»/«Listo:» prefix and color (the state reads
    without icon or color). ``cget("text")`` is the message alone, as with the ``ttk.Label`` it replaces.
    *prefixes* gives the prefix texts of the current language (``severity: text``)."""

    def __init__(self, master, prefixes: Callable[[], dict[str, str]], wraplength: int | None = None) -> None:
        super().__init__(master)
        self._prefixes, self._text, self._severity = prefixes, "", "info"
        size = tkfont.nametofont("TkDefaultFont", root=self).metrics("linespace")
        self._icon = tk.Canvas(self, width=size, height=size, highlightthickness=0, borderwidth=0, takefocus=0)
        self._size = size
        self._label = ttk.Label(self, wraplength=wraplength or theme.wrap(), justify="left")
        self._label.pack(side="right", fill="x", expand=True)

    def configure(self, cnf=None, **options):
        options = {**(cnf or {}), **options}
        if "text" in options or "severity" in options:  # a new text without a severity is plain information
            self._text = str(options.pop("text", self._text))
            self._severity = options.pop("severity", None) or "info"
            self._draw()
        options.pop("style", None)
        if options:
            return super().configure(**options)
        return None

    config = configure

    def cget(self, key: str):
        if key == "text":
            return self._text
        if key == "severity":
            return self._severity
        if key == "style":  # the label style of the severity, as the ttk.Label had
            return {"error": "Error.TLabel", "warning": "Warning.TLabel", "ok": "Ok.TLabel"}.get(self._severity, "TLabel")
        return super().cget(key)

    def retheme(self) -> None:
        self._draw()

    def shown_text(self) -> str:
        prefix = self._prefixes().get(self._severity, "") if self._text else ""
        return f"{prefix} {self._text}" if prefix else self._text

    def _draw(self) -> None:
        self._label.configure(text=self.shown_text(), style=self.cget("style"))
        self._icon.delete("all")
        if self._text and self._severity in ("error", "warning", "ok"):
            self._icon.configure(background=_background(self._icon))
            draw_icon(self._icon, self._severity, 0, 0, self._size, theme.color(self._severity))
            self._icon.pack(side="left", anchor="n", padx=(0, theme.space("xs")), before=self._label)
        else:
            self._icon.pack_forget()


class ChoiceCards(ttk.Frame):
    """Selectable cards for a ``tk.StringVar`` (the radio buttons they replace): name and one help line. The
    chosen one has an accent border, a check mark and a bold name; Tab reaches them, the arrow keys move the
    choice, Space and Enter choose."""

    def __init__(self, master, variable: tk.StringVar, values: Sequence[str]) -> None:
        super().__init__(master)
        self.variable, self.values = variable, list(values)
        self._texts: dict[str, tuple[str, str]] = {value: (value, "") for value in values}
        self.cards: dict[str, tk.Canvas] = {}
        self._hover: str | None = None
        self._focus: str | None = None
        for column, value in enumerate(values):
            card = tk.Canvas(self, highlightthickness=0, borderwidth=0, takefocus=1)
            card.grid(row=0, column=column, sticky="nsew", padx=(0, theme.space("s")))
            self.columnconfigure(column, weight=1, uniform="cards")
            for sequence, handler in (("<Button-1>", lambda _, v=value: self.choose(v, focus=True)),
                                      ("<KeyPress-space>", lambda _, v=value: self.choose(v)),
                                      ("<Return>", lambda _, v=value: self.choose(v)),
                                      ("<Left>", lambda _, v=value: self._step(v, -1)),
                                      ("<Up>", lambda _, v=value: self._step(v, -1)),
                                      ("<Right>", lambda _, v=value: self._step(v, 1)),
                                      ("<Down>", lambda _, v=value: self._step(v, 1)),
                                      ("<Enter>", lambda _, v=value: self._set(hover=v)),
                                      ("<Leave>", lambda _: self._set(hover=None)),
                                      ("<FocusIn>", lambda _, v=value: self._set(focus=v)),
                                      ("<FocusOut>", lambda _: self._set(focus=None)),
                                      ("<Configure>", lambda _: self._draw())):
                card.bind(sequence, handler)
            self.cards[value] = card
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def set_texts(self, texts: dict[str, tuple[str, str]]) -> None:
        """``value: (name, help line)`` in the current language."""
        self._texts = texts
        self._draw()

    def choose(self, value: str, focus: bool = False) -> None:
        if focus:
            self.cards[value].focus_set()
        if self.variable.get() != value:
            self.variable.set(value)

    def _step(self, value: str, offset: int) -> str:
        target = self.values[(self.values.index(value) + offset) % len(self.values)]
        self.choose(target, focus=True)
        return "break"

    def _set(self, **flags) -> None:
        for name, value in flags.items():
            setattr(self, f"_{name}", value)
        self._draw()

    def retheme(self) -> None:
        self._draw()

    def _draw(self) -> None:
        font = tkfont.nametofont("TkDefaultFont", root=self)
        bold = tkfont.nametofont("MRIStepCurrent", root=self)
        line, pad, ring = font.metrics("linespace"), theme.space("m"), theme.size("focus_ring")
        height = 2 * line + theme.space("xs") + 2 * (pad + ring)
        for value, card in self.cards.items():
            chosen = self.variable.get() == value
            name, help_text = self._texts.get(value, (value, ""))
            width = max(card.winfo_width(), theme.size("card_min"))
            card.configure(height=height, background=_background(card))
            card.delete("all")
            if self._focus == value:
                _rounded(card, 1, 1, width - 1, height - 1, theme.space("m") + ring, fill="",
                         outline=theme.color("focus"), width=theme.size("focus_line"))
            fill = theme.color("hover") if self._hover == value or chosen else theme.color("surface")
            _rounded(card, ring, ring, width - ring, height - ring, theme.space("m"), fill=fill,
                     outline=theme.color("accent" if chosen else "input_border"), width=theme.size("focus_line" if chosen else "border"))
            title = f"{theme.DONE_MARK} {name}" if chosen else name
            card.create_text(ring + pad, ring + pad, anchor="nw", text=title, font=bold if chosen else font,
                             fill=theme.color("accent" if chosen else "text"))
            card.create_text(ring + pad, ring + pad + line + theme.space("xs"), anchor="nw", font=font,
                             text=elide(help_text, font, width - 2 * (ring + pad)), fill=theme.color("muted"))


def bind_row_hover(tree: ttk.Treeview) -> None:
    """Tint the row under the pointer (the ``hover`` tag, colored by ``theme.apply_theme``)."""
    current: list[str] = [""]

    def mark(item: str, on: bool) -> None:
        if item and tree.exists(item):
            tags = [tag for tag in tree.item(item, "tags") if tag != "hover"]
            tree.item(item, tags=[*tags, "hover"] if on else tags)

    def move(event) -> None:
        item = tree.identify_row(event.y)
        if item != current[0]:
            mark(current[0], False)
            mark(item, True)
            current[0] = item

    def leave(_event) -> None:
        mark(current[0], False)
        current[0] = ""

    tree.bind("<Motion>", move, add="+")
    tree.bind("<Leave>", leave, add="+")


def stripe(tree: ttk.Treeview) -> None:
    """Alternate row colors (the ``odd`` tag) after the rows were inserted or filtered."""
    for index, item in enumerate(tree.get_children()):
        tags = [tag for tag in tree.item(item, "tags") if tag != "odd"]
        tree.item(item, tags=[*tags, "odd"] if index % 2 else tags)
