"""Colors, fonts and spacing of the GUI: the only module with visual literals (``docs/architecture/gui.md``).

The palettes, the spacing scale and the contrast check are plain data (tested without a display); only
``apply_theme`` touches Tk. The views ask for named styles (``"Error.TLabel"``...) and ``space``/``px`` sizes.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F6F3FA", "surface": "#FFFFFF", "row_alt": "#EFE9F6", "select_bg": "#DCCDF0", "border": "#CBBEDD",
        "text": "#241B2F", "muted": "#584A6B", "disabled": "#6A5D7C", "accent": "#5B2C9E", "accent_bg": "#5B2C9E",
        "on_accent": "#FFFFFF", "error": "#B42318", "warning": "#8A4B00", "ok": "#1E6B31",
        "hover": "#E2D6F2", "accent_hover": "#4A2287", "accent_pressed": "#3A1A6B", "input_border": "#6E6380",
        "focus": "#8E5BD9", "header_top": "#C4AEE6", "header_hover": "#2E1557", "header_text": "#241B2F",
        "header_muted": "#41345A", "header_done": "#14481F",
    },
    "dark": {
        "bg": "#1D1826", "surface": "#262031", "row_alt": "#2D2639", "select_bg": "#46336A", "border": "#433A52",
        "text": "#ECE6F4", "muted": "#B7ACC7", "disabled": "#9C90AE", "accent": "#C4A6F5", "accent_bg": "#C4A6F5",
        "on_accent": "#1A1324", "error": "#FF8A80", "warning": "#F2C14E", "ok": "#7BD88F",
        "hover": "#3B3150", "accent_hover": "#D4BEF8", "accent_pressed": "#E3D4FB", "input_border": "#7A6D90",
        "focus": "#C8A2FF", "header_top": "#45306E", "header_hover": "#FFFFFF", "header_text": "#F3EEFA",
        "header_muted": "#CFC4DF", "header_done": "#8FE3A2",
    },
}
THEMES = tuple(PALETTES)
DEFAULT_THEME = "light"

# The (text, background) pairs the window draws: each must reach 4.5:1 (WCAG AA, normal text).
TEXT_COLORS = ("text", "muted", "disabled", "accent", "error", "warning", "ok")
TEXT_PAIRS = (
    *((fg, bg) for fg in TEXT_COLORS for bg in ("bg", "surface", "row_alt")),
    ("text", "select_bg"), ("muted", "select_bg"), ("text", "hover"),
    ("on_accent", "accent_bg"), ("on_accent", "accent_hover"), ("on_accent", "accent_pressed"),
    # the header text is drawn over a gradient: it must read on both ends (its own tokens: the top is dark)
    *((fg, end) for fg in ("header_text", "header_muted", "header_done", "header_hover")
      for end in ("header_top", "bg")),
    ("on_accent", "accent_bg"),  # the current step pill
)
# Borders and the focus ring are not text: 3:1 against what they sit on (WCAG 1.4.11).
BORDER_PAIRS = tuple((fg, bg) for fg in ("focus", "input_border") for bg in ("bg", "surface", "row_alt"))

FONT_FAMILIES = ("Verdana", "DejaVu Sans")  # the first installed one; else the system font (none is bundled)
TK_FONTS = ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "TkCaptionFont", "TkSmallCaptionFont",
            "TkIconFont", "TkTooltipFont")

SPACE = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24}  # logical pixels (96 dpi)
WINDOW = (960, 680)  # logical pixels: a fixed window (design decision), centered on the screen
TASKBAR = 48  # logical pixels kept free at the bottom of the screen when the window does not fit
WRAP = 900  # logical pixels: the width of wrapped help and result texts (the body of the fixed window)
DONE_MARK = "✓"  # after the name of a finished step, so the state is not told by color alone
EDIT_MARK = "▾"  # after the heading of a column edited with one click

# Fixed sizes in logical pixels (``size`` scales them) and other drawing constants: the only place they are set.
SIZES = {
    "activity_bar": 160, "welcome_bar": 320, "status_wrap": 560, "card_wrap": 420, "dialog_wrap": 420,
    "tooltip_wrap": 360, "tooltip_dx": 12, "tooltip_dy": 4, "focus_ring": 3, "focus_line": 2, "border": 1,
    "card_min": 200, "icon_pad": 4,
}
BAR_STEP_MS = 12  # animation step of the indeterminate bars
DIALOG_TEXT = (60, 20)  # characters x lines of the sections dialog
MAPPING_COLUMNS = {"location": 260, "suffix": 80, "code": 160, "participant": 140, "session": 140, "label": 90}

# name: (base font, extra points, weight, underline). Three levels (design decision): name 13 bold, step title
# 12 normal, text 9 (bold only in the current step pill); all in the same family.
FONT_SIZES = {"MRIAppName": ("TkHeadingFont", 4, "bold", 0), "MRIStepTitle": ("TkHeadingFont", 3, "normal", 0),
              "MRIStepCurrent": ("TkDefaultFont", 0, "bold", 0), "MRILink": ("TkDefaultFont", 0, "normal", 1)}

_scale = 1.0  # screen pixels per logical pixel, set by apply_theme from Tk's scaling
_current = DEFAULT_THEME  # the palette of the last apply_theme (drawn widgets read it)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio of two ``#RRGGBB`` colors (1 to 21)."""

    def luminance(color: str) -> float:
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def mix(start: str, end: str, t: float) -> str:
    """The color at *t* (0 = *start*, 1 = *end*) of a straight RGB gradient."""
    a, b = ([int(color[i:i + 2], 16) for i in (1, 3, 5)] for color in (start, end))
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def pick_family(installed) -> str | None:
    """The first of FONT_FAMILIES in *installed*; ``None`` = keep the system font."""
    return next((family for family in FONT_FAMILIES if family in installed), None)


def color(token: str) -> str:
    return PALETTES[_current][token]


def px(logical: float) -> int:
    """A size in logical pixels as screen pixels (grows with the display scaling)."""
    return round(logical * _scale)


def space(key: str) -> int:
    return px(SPACE[key])


def size(key: str) -> int:
    return px(SIZES[key])


def wrap() -> int:
    return px(WRAP)


def _font_size(size: int, extra: int) -> int:
    # Tk sizes: positive = points, negative = pixels (common on Linux); 1 pt is about 4/3 px at 96 dpi
    return size + extra if size > 0 else size - round(extra * 4 / 3)


def _fonts(root: tk.Misc) -> None:
    if family := pick_family(set(tkfont.families(root))):
        for name in TK_FONTS:
            tkfont.nametofont(name, root=root).configure(family=family)
    fonts = root.__dict__.setdefault("_theme_fonts", {})  # Tk deletes a named font when its Font object dies
    for name, (base, extra, weight, underline) in FONT_SIZES.items():
        spec = tkfont.nametofont(base, root=root).actual()
        spec.update(size=_font_size(spec["size"], extra), weight=weight, underline=underline)
        if name in fonts:
            fonts[name].configure(**spec)
        else:
            fonts[name] = tkfont.Font(root=root, name=name, **spec)


def _recolor_tk_widgets(widget: tk.Misc, colors: dict[str, str]) -> None:
    """The widgets that are not ``ttk`` (``Listbox``, ``Text``, drawn widgets) and the hover rows of the tables
    do not follow the style: colored one by one."""
    if isinstance(widget, (tk.Listbox, tk.Text)):
        widget.configure(background=colors["surface"], foreground=colors["text"], selectbackground=colors["select_bg"],
                         selectforeground=colors["text"], highlightcolor=colors["accent"],
                         highlightbackground=colors["border"])
        if isinstance(widget, tk.Listbox):  # no underlined «active» line: the log is read, not navigated
            widget.configure(activestyle="none")
        if isinstance(widget, tk.Text):  # an input: the border and font of the entries (Tk's default is TkFixedFont)
            widget.configure(insertbackground=colors["text"], relief="flat", borderwidth=0, highlightthickness=px(1),
                             font="TkTextFont",
                             highlightbackground=colors["input_border"], highlightcolor=colors["focus"])
    elif isinstance(widget, ttk.Treeview):  # created first, so "hover" wins over the striped "odd" rows
        widget.tag_configure("hover", background=colors["hover"])
        widget.tag_configure("odd", background=colors["row_alt"])
    elif callable(getattr(widget, "retheme", None)):  # widgets drawn on a Canvas (widgets.py)
        widget.retheme()
    for child in widget.winfo_children():
        _recolor_tk_widgets(child, colors)


def recolor(widget: tk.Misc) -> None:
    """Color a widget created after ``apply_theme`` (and its children) with the current palette."""
    _recolor_tk_widgets(widget, PALETTES[_current])


def apply_theme(root: tk.Tk, name: str = DEFAULT_THEME) -> None:
    """Style the whole window with palette *name* (again on a theme change: existing widgets follow)."""
    global _scale, _current
    if name not in PALETTES:
        raise ValueError("Unsupported theme.")
    c, _current = PALETTES[name], name
    _scale = max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
    _fonts(root)
    style = ttk.Style(root)
    style.theme_use("clam")  # on Windows and Linux, and every color can be set (vista ignores backgrounds)
    style.configure(".", background=c["bg"], foreground=c["text"], fieldbackground=c["surface"],
                    bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["border"], troughcolor=c["row_alt"],
                    focuscolor=c["accent"], selectbackground=c["select_bg"], selectforeground=c["text"],
                    insertcolor=c["text"], arrowcolor=c["text"])
    style.map(".", foreground=[("disabled", c["disabled"])], background=[("active", c["row_alt"])])
    for entry in ("TEntry", "TCombobox"):  # the input border: dim at rest, bright with the focus
        style.configure(entry, bordercolor=c["input_border"], lightcolor=c["surface"], darkcolor=c["surface"])
        style.map(entry, bordercolor=[("focus", c["focus"])], lightcolor=[("focus", c["focus"])])
    style.map("TEntry", fieldbackground=[("readonly", c["bg"])])
    style.map("TCombobox", fieldbackground=[("readonly", c["surface"]), ("disabled", c["bg"])],
              selectbackground=[("readonly", c["surface"])], selectforeground=[("readonly", c["text"])])
    style.configure("TLabelframe.Label", foreground=c["text"])
    for indicator in ("TCheckbutton", "TRadiobutton"):
        style.configure(indicator, indicatorbackground=c["surface"], indicatorforeground=c["text"],
                        upperbordercolor=c["border"], lowerbordercolor=c["border"])
        style.map(indicator, indicatorbackground=[("disabled", c["bg"]), ("pressed", c["row_alt"])])
    style.configure("TSeparator", background=c["border"])
    style.configure("Treeview", background=c["surface"], fieldbackground=c["surface"], foreground=c["text"],
                    rowheight=round(tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace") * 1.4))
    style.map("Treeview", background=[("selected", c["select_bg"])], foreground=[("selected", c["text"])])
    # neutral headings with a line below (darkcolor draws the bottom edge in clam)
    style.configure("Treeview.Heading", background=c["row_alt"], foreground=c["text"], relief="flat",
                    bordercolor=c["input_border"], lightcolor=c["row_alt"], darkcolor=c["input_border"])
    style.map("Treeview.Heading", background=[("active", c["hover"])])
    style.configure("AppName.TLabel", font="MRIAppName")
    style.configure("StepTitle.TLabel", font="MRIStepTitle")
    style.configure("Muted.TLabel", foreground=c["muted"])
    style.configure("Link.TLabel", foreground=c["accent"], font="MRILink")
    style.map("Link.TLabel", foreground=[("active", c["header_hover"])])
    style.configure("Summary.TFrame", relief="solid", borderwidth=1, bordercolor=c["ok"])
    style.configure("Card.TFrame", background=c["surface"], relief="solid", borderwidth=1, bordercolor=c["border"])
    for card in ("Card.TLabel", "Card.AppName.TLabel", "Card.Muted.TLabel", "Card.Link.TLabel"):
        style.configure(card, background=c["surface"])
    for severity in ("error", "warning", "ok"):
        style.configure(f"{severity.capitalize()}.TLabel", foreground=c[severity])
    style.configure("Footer.TFrame", background=c["row_alt"])
    style.configure("Footer.TLabel", background=c["row_alt"])
    style.configure("Footer.Horizontal.TProgressbar", troughcolor=c["row_alt"], background=c["accent"],
                    bordercolor=c["row_alt"], lightcolor=c["accent"], darkcolor=c["accent"])
    root.configure(background=c["bg"])
    for option, color in (("background", "surface"), ("foreground", "text"), ("selectBackground", "select_bg"),
                          ("selectForeground", "text")):
        root.option_add(f"*TCombobox*Listbox.{option}", c[color])  # the drop-down list of comboboxes
    _recolor_tk_widgets(root, c)
