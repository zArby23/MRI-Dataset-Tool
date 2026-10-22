"""Exporters of the dataset summary (``build_dataset_summary``): one dict, several formats.

Every format renders the same values: numbers are written with ``json.dumps`` so the
Markdown shows exactly the figures of the JSON. Writers never overwrite.
"""

import json
import os
from pathlib import Path
from typing import Any


def to_json(summary: dict[str, Any]) -> str:
    """Deterministic JSON text; NaN/Inf are rejected (``ValueError``)."""
    return json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_json(summary: dict[str, Any], path: Path) -> Path:
    return _write_text(path, to_json(summary))


def write_markdown(summary: dict[str, Any], path: Path) -> Path:
    return _write_text(path, to_markdown(summary))


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
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _write_text(path: Path, text: str) -> Path:
    """Atomic write (temporary file + ``os.replace``); an existing *path* is never replaced."""
    if path.exists():
        raise FileExistsError("Report file already exists.")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Report content is invalid.") from None  # the cause quotes the character
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
