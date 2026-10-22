"""Label table of the dataset (RF11): ``labels.tsv`` + ``labels.json`` at the dataset root.

One categorical label per (participant, session) from a closed list of classes. An empty
label means "unlabeled", which is not the same as an unknown class (an error). Cells are
plain data and never evaluated; class names may not start with ``=``, ``+``, ``-``, ``@``,
tab or carriage return (CSV injection). Messages are fixed: never ids, labels or paths.
"""

import csv
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from mri_dataset_tool.infrastructure.dataset.bids_layout import validate_label

LABELS_TSV = "labels.tsv"
LABELS_JSON = "labels.json"
COLUMNS = ("participant_id", "session_id", "label")

# File format (approved by the human, see docs/dataset/labels.md): ids carry the BIDS prefix
# in the file and not in the API; an empty session cell means a dataset without sessions.
_SUB_PREFIX = "sub-"
_SES_PREFIX = "ses-"
_FORBIDDEN_IN_CLASS = ("\t", "\r", "\n")
# A class name ends up in every labelled row, so it may not look like a spreadsheet formula
# (CSV injection; decision of the human).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

LabelKey = tuple[str, str | None]


@dataclass(frozen=True)
class LabelTable:
    """``classes``: class -> description; ``labels``: (participant, session) -> class or None."""

    classes: dict[str, str]
    labels: dict[LabelKey, str | None] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "classes", dict(self.classes))
        object.__setattr__(self, "labels", dict(self.labels))
        _check_classes(self.classes)
        if not _is_text(self.description):
            raise ValueError("Label classes are invalid.")
        for (participant, session), label in self.labels.items():
            if not _is_id(participant) or not (session is None or _is_id(session)):
                raise ValueError("Label table has an invalid participant or session id.")
            if label is not None and label not in self.classes:
                raise ValueError("Label table has an unknown class.")


def parse_label_rows(path: Path) -> list[tuple[str, str, str]]:
    """Read ``labels.tsv`` checking only its structure; cells are returned as written.

    Returns ``(participant_id, session_id, label)`` per non-blank row, in file order.
    Extra columns are ignored. Missing columns, a malformed row or no rows → ``ValueError``.
    """
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:  # -sig: Excel adds a BOM
            rows = [row for row in csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE) if any(row)]
    except FileNotFoundError:
        raise FileNotFoundError("Label table not found.") from None
    except UnicodeDecodeError:
        raise ValueError("Label table is not valid UTF-8.") from None
    except OSError:
        raise OSError("Label table could not be read.") from None
    if len(rows) < 2:
        raise ValueError("Label table is empty.")
    header, *body = rows
    if len(set(header)) != len(header) or not set(COLUMNS) <= set(header):
        raise ValueError("Label table is missing required columns.")
    positions = [header.index(column) for column in COLUMNS]
    if any(len(row) != len(header) for row in body):
        raise ValueError("Label table has a malformed row.")
    return [tuple(row[i] for i in positions) for row in body]


def parse_label_key(participant_cell: str, session_cell: str) -> LabelKey:
    """Turn the id cells of a row into a table key; invalid → ``ValueError``."""
    participant = _strip_prefix(participant_cell, _SUB_PREFIX)
    session = None if session_cell == "" else _strip_prefix(session_cell, _SES_PREFIX)
    if participant is None or (session_cell != "" and session is None):
        raise ValueError("Label table has an invalid participant or session id.")
    return participant, session


def read_classes(root: Path) -> tuple[dict[str, str], str]:
    """Read ``labels.json``: returns (class -> description, table description)."""
    try:
        data = json.loads((root / LABELS_JSON).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError("Label classes file not found.") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Label classes file is invalid.") from None
    except OSError:
        raise OSError("Label classes file could not be read.") from None
    column = data.get("label") if isinstance(data, dict) else None
    levels = column.get("Levels") if isinstance(column, dict) else None
    description = column.get("Description", "") if isinstance(column, dict) else None
    if not isinstance(levels, dict) or not isinstance(description, str):
        raise ValueError("Label classes file is invalid.")
    if not _is_text(description):
        raise ValueError("Label classes are invalid.")
    _check_classes(levels)
    return levels, description


def read_labels(root: Path) -> LabelTable:
    """Strict read of ``labels.json`` + ``labels.tsv``; any defect → fixed ``ValueError``."""
    classes, description = read_classes(root)
    labels: dict[LabelKey, str | None] = {}
    for participant_cell, session_cell, label in parse_label_rows(root / LABELS_TSV):
        key = parse_label_key(participant_cell, session_cell)
        if key in labels:
            raise ValueError("Label table has a duplicate participant/session.")
        labels[key] = label or None
    return LabelTable(classes, labels, description)


def write_labels(table: LabelTable, root: Path) -> tuple[Path, Path]:
    """Write ``labels.tsv`` (rows sorted by participant, session) and ``labels.json``.

    Never overwrites: if either file exists → ``FileExistsError`` and nothing is written.
    Each file is written atomically (temporary + ``os.replace``). ``root`` must exist.
    """
    tsv_path, json_path = root / LABELS_TSV, root / LABELS_JSON
    if tsv_path.exists() or json_path.exists():
        raise FileExistsError("Label table already exists.")
    lines = ["\t".join(COLUMNS)]
    for (participant, session), label in sorted(table.labels.items(), key=lambda item: (item[0][0], item[0][1] or "")):
        session_cell = "" if session is None else _SES_PREFIX + session
        lines.append("\t".join((_SUB_PREFIX + participant, session_cell, label or "")))
    sidecar = {"label": {"Description": table.description, "Levels": table.classes}}
    _write_atomic(json_path, json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    try:
        _write_atomic(tsv_path, "\n".join(lines) + "\n")
    except BaseException:
        json_path.unlink(missing_ok=True)  # never leave half a table
        raise
    return tsv_path, json_path


def _check_classes(classes: object) -> None:
    if not isinstance(classes, dict) or not classes:
        raise ValueError("Label classes are invalid.")
    for name, description in classes.items():
        if (
            not _is_text(name)
            or not _is_text(description)
            or not name
            or name != name.strip()
            or name.startswith(_FORMULA_PREFIXES)
            or any(char in name or char in description for char in _FORBIDDEN_IN_CLASS)
        ):
            raise ValueError("Label classes are invalid.")


def _is_text(value: object) -> bool:
    """A ``str`` that encodes as UTF-8 (rejects lone surrogates)."""
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_id(value: object) -> bool:
    try:
        validate_label(value)
    except ValueError:
        return False
    return True


def _strip_prefix(cell: str, prefix: str) -> str | None:
    value = cell.removeprefix(prefix)
    return value if cell.startswith(prefix) and _is_id(value) else None


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise OSError("Label table could not be written.") from None  # the cause quotes the path
    except UnicodeEncodeError:
        tmp.unlink(missing_ok=True)
        raise ValueError("Label table could not be written.") from None  # the cause quotes the text
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
