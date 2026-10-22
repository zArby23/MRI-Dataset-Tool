"""Exporters of the dataset summary (``build_dataset_summary``): one dict, several formats.

Every format renders the same values: numbers are written with ``json.dumps`` (Markdown,
XML) or as numeric cells (XLSX), so each shows exactly the figures of the JSON. Writers
are atomic and never overwrite; content that cannot be encoded gives a fixed error.
"""

import io
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from openpyxl import Workbook

_INVALID = "Report content is invalid."
# Characters XML 1.0 forbids (ElementTree would write them and produce a malformed file);
# openpyxl rejects the same control characters.
_INVALID_CHARS = re.compile(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
# Children of these dicts are named by data (modality, class), so they become name attributes.
_XML_NAMED_CHILDREN = {"modalities": "modality", "classes": "class"}


def to_json(summary: dict[str, Any]) -> str:
    """Deterministic JSON text; NaN/Inf are rejected (``ValueError``)."""
    return json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_json(summary: dict[str, Any], path: Path) -> Path:
    return _write_text(path, to_json(summary))


def write_markdown(summary: dict[str, Any], path: Path) -> Path:
    return _write_text(path, to_markdown(summary))


def write_xml(summary: dict[str, Any], path: Path) -> Path:
    return _write_text(path, to_xml(summary))


def to_xml(summary: dict[str, Any]) -> str:
    """``<dataset_report>`` with one element per key (sorted); lists of records are ``<item>`` elements.

    Strings are element text; numbers, ``null`` and lists of scalars are their JSON text.
    Modalities and classes are ``<modality name="...">``/``<class name="...">``.
    """
    root = ET.Element("dataset_report")
    _xml_fill(root, "dataset_report", summary)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _xml_fill(element: ET.Element, key: str, value: Any) -> None:
    if isinstance(value, dict):
        for child_key in sorted(value):
            if key in _XML_NAMED_CHILDREN:
                child = ET.SubElement(element, _XML_NAMED_CHILDREN[key], name=_checked(child_key))
            else:
                child = ET.SubElement(element, child_key)
            _xml_fill(child, child_key, value[child_key])
    elif isinstance(value, list) and any(isinstance(item, dict) for item in value):
        for item in value:
            _xml_fill(ET.SubElement(element, "item"), "item", item)
    else:
        element.text = _checked(_text(value))


def write_xlsx(summary: dict[str, Any], path: Path) -> Path:
    """One sheet per section; values only (no formulas, macros or links), every string stored as text.

    The cells are deterministic; the file bytes are not (openpyxl stamps save times).
    Floats keep 16 significant digits (openpyxl writes ``%.16g``; Excel shows 15), so the
    17th digit of a JSON float can differ.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, (header, rows) in _xlsx_sheets(summary).items():
        sheet = workbook.create_sheet(title)
        for row in [header, *rows]:
            sheet.append([value if _is_number(value) else _checked(_text(value)) for value in row])
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"  # never a formula, even when it starts with = + - @
    buffer = io.BytesIO()
    workbook.save(buffer)
    return _write_bytes(path, buffer.getvalue())


def _xlsx_sheets(summary: dict[str, Any]) -> dict[str, tuple[list[str], list[list[Any]]]]:
    modalities = summary["modalities"]
    labels = summary["labels"]
    totals = [[key, summary[key]] for key in ("participants", "sessions", "studies", "series")]
    if labels is not None:
        totals += [[key, labels[key]] for key in ("unlabeled_sessions", "unlabeled_participants")]
    intensity_keys = list(next(iter(modalities.values()))["intensity"]) if modalities else []
    distributions = [
        [name, key, item["value"], item["count"]]
        for name, stats in modalities.items()
        for key in ("shape", "voxel_size", "orientation", "dtype")
        for item in stats[key]
    ]
    classes = [] if labels is None else [
        [name, c["participants"], c["sessions"], c["series"]] for name, c in labels["classes"].items()
    ]
    return {
        "Totals": (["item", "count"], totals),
        "Modalities": (["modality", "series"], [[name, stats["series"]] for name, stats in modalities.items()]),
        "Distributions": (["modality", "field", "value", "count"], distributions),
        "Intensity": (
            ["modality", *intensity_keys],
            [[name, *(stats["intensity"][key] for key in intensity_keys)] for name, stats in modalities.items()],
        ),
        "Labels": (["class", "participants", "sessions", "series"], classes),
        "Warnings": (["code", "count"], [[w["code"], w["count"]] for w in summary["warnings"]]),
    }


def to_markdown(summary: dict[str, Any]) -> str:
    lines = ["# Dataset report", "", "## Totals", ""]
    lines += _table(["item", "count"], [[key, summary[key]] for key in ("participants", "sessions", "studies", "series")])
    lines += ["", "## Modalities", ""]
    modalities = summary["modalities"]
    lines += _table(["modality", "series"], [[name, stats["series"]] for name, stats in modalities.items()])
    for name, stats in modalities.items():
        lines += ["", f"### {_cell(name)}", ""]
        for key in ("shape", "voxel_size", "orientation", "dtype"):
            lines += [f"**{key}**", ""]
            lines += _table(["value", "count"], [[item["value"], item["count"]] for item in stats[key]])
            lines.append("")
        lines += ["**intensity**", ""]
        lines += _table(list(stats["intensity"]), [list(stats["intensity"].values())])
    lines += ["", "## Labels", ""]
    labels = summary["labels"]
    if labels is None:
        lines.append("No labels.")
    else:
        rows = [[name, c["participants"], c["sessions"], c["series"]] for name, c in labels["classes"].items()]
        lines += _table(["class", "participants", "sessions", "series"], rows)
        lines += ["", f"Unlabeled sessions: {labels['unlabeled_sessions']}"]
        lines += [f"Unlabeled participants: {labels['unlabeled_participants']}"]
    lines += ["", "## Warnings", ""]
    if summary["warnings"]:
        lines += _table(["code", "count"], [[w["code"], w["count"]] for w in summary["warnings"]])
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return lines + ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]


def _cell(value: Any) -> str:
    return _text(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)


def _is_number(value: Any) -> bool:
    if isinstance(value, float):
        json.dumps(value, allow_nan=False)  # NaN/Inf: the same ValueError as to_json
    return value is None or isinstance(value, (bool, int, float))


def _checked(text: str) -> str:
    """Reject text with characters XML/XLSX cannot hold (control characters, lone surrogates)."""
    if _INVALID_CHARS.search(text):
        raise ValueError(_INVALID)
    return text


def _write_text(path: Path, text: str) -> Path:
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(_INVALID) from None  # the cause quotes the character
    return _write_bytes(path, data)


def _write_bytes(path: Path, data: bytes) -> Path:
    """Atomic write (temporary file + ``os.replace``); an existing *path* is never replaced."""
    if path.exists():
        raise FileExistsError("Report file already exists.")
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException as error:
        tmp.unlink(missing_ok=True)
        if isinstance(error, OSError):
            raise OSError("Report file could not be written.") from None  # the cause quotes the path
        raise
    return path
