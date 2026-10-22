"""Label review and correction service (RF12, RF15) over an exported BIDS dataset.

The (participant, session) pairs come from the dataset tree (``sub-*``/``ses-*`` folders);
labels live in ``labels.tsv`` + ``labels.json`` at its root (``infrastructure/dataset/labels``).
Results and messages carry only counts and dataset ids (pseudonyms), never paths.
"""

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mri_dataset_tool.infrastructure.dataset.bids_layout import validate_label
from mri_dataset_tool.infrastructure.dataset.labels import (
    FINAL_JSON,
    LABELS_TSV,
    LabelKey,
    LabelTable,
    appended_label_changes,
    label_changes_text,
    parse_label_key,
    parse_label_rows,
    read_classes,
    read_labels,
    remove_final_labels,
    serialize_labels,
    write_final_labels,
    write_labels,
)

# Logged instead of a previous value that is not a class (hand edits may hold anything).
INVALID_LABEL = "<invalid>"


@dataclass(frozen=True)
class LabelReview:
    """Defects of the label table against the dataset. Lists hold dataset pairs, sorted.

    Rows of a duplicated pair are only listed in ``duplicated``; rows whose ids are invalid or
    not in the dataset are only counted (they are not dataset ids).
    """

    dataset_pairs: int
    class_counts: dict[str, int]
    unlabeled: list[LabelKey]
    unknown_class: list[LabelKey]
    duplicated: list[LabelKey]
    missing: list[LabelKey]
    not_in_dataset: int
    invalid_ids: int

    @property
    def labeled(self) -> int:
        return sum(self.class_counts.values())

    @property
    def is_complete(self) -> bool:
        return not (
            self.unlabeled
            or self.unknown_class
            or self.duplicated
            or self.missing
            or self.not_in_dataset
            or self.invalid_ids
        )


def dataset_pairs(dataset_root: Path) -> list[LabelKey]:
    """(participant, session) pairs of the dataset tree, sorted; ``None`` = no session level.

    Hidden entries and folders whose name is not ``sub-``/``ses-`` + a valid BIDS label are
    ignored.
    """
    _check_root(dataset_root)
    pairs: list[LabelKey] = []
    for subject_dir in sorted(dataset_root.iterdir()):
        subject = _folder_label(subject_dir, "sub-")
        if subject is None:
            continue
        sessions = [s for d in sorted(subject_dir.iterdir()) if (s := _folder_label(d, "ses-")) is not None]
        pairs.extend((subject, session) for session in sessions or [None])
    return pairs


def review_labels(dataset_root: Path) -> LabelReview:
    """Compare ``labels.tsv`` with the dataset tree and the classes of ``labels.json``.

    Structural defects (missing files, missing columns, malformed rows, invalid classes file)
    raise the fixed errors of the label module; content defects are reported.
    """
    pairs = dataset_pairs(dataset_root)
    classes, _ = read_classes(dataset_root)
    rows_by_key: dict[LabelKey, list[str]] = defaultdict(list)
    invalid_ids = 0
    for participant_cell, session_cell, label in parse_label_rows(dataset_root / LABELS_TSV):
        try:
            rows_by_key[parse_label_key(participant_cell, session_cell)].append(label)
        except ValueError:
            invalid_ids += 1

    known = set(pairs)
    counts: Counter[str] = Counter({name: 0 for name in classes})
    unlabeled: list[LabelKey] = []
    unknown_class: list[LabelKey] = []
    duplicated: list[LabelKey] = []
    for key in pairs:
        labels = rows_by_key.get(key, [])
        if len(labels) > 1:
            duplicated.append(key)
        elif labels == [""]:
            unlabeled.append(key)
        elif labels and labels[0] in classes:
            counts[labels[0]] += 1
        elif labels:
            unknown_class.append(key)
    return LabelReview(
        dataset_pairs=len(pairs),
        class_counts=dict(sorted(counts.items())),
        unlabeled=unlabeled,
        unknown_class=unknown_class,
        duplicated=duplicated,
        missing=[key for key in pairs if key not in rows_by_key],
        not_in_dataset=sum(len(labels) for key, labels in rows_by_key.items() if key not in known),
        invalid_ids=invalid_ids,
    )


def write_label_template(dataset_root: Path, classes: dict[str, str], description: str = "") -> Path:
    """Write ``labels.json`` with *classes* and ``labels.tsv`` with every dataset pair unlabeled.

    Returns the ``labels.tsv`` path. Existing label files → ``FileExistsError``; a dataset
    without participants → ``ValueError``. Labels are then assigned with ``apply_label_corrections``.
    """
    pairs = dataset_pairs(dataset_root)
    if not pairs:
        raise ValueError("Dataset has no participants.")
    tsv_path, _ = write_labels(LabelTable(classes, dict.fromkeys(pairs), description), dataset_root)
    return tsv_path


def apply_label_corrections(dataset_root: Path, corrections_path: Path) -> int:
    """Apply a corrections TSV (same columns as ``labels.tsv``) and log each change.

    All or nothing: a correction for a pair outside the dataset, a repeated pair, an invalid
    id, or a resulting table with an unknown class rejects the whole file. An empty label sets
    the pair back to unlabeled. The current table may hold unknown classes or miss pairs
    (corrections can fix them) but duplicated, invalid or foreign rows must be fixed by hand.
    Returns the number of changes; rows equal to the current value are not logged.
    """
    if (dataset_root / FINAL_JSON).exists():
        raise ValueError("Labels are finalized.")
    pairs = set(dataset_pairs(dataset_root))
    classes, description = read_classes(dataset_root)
    current: dict[LabelKey, str] = {}
    for participant_cell, session_cell, label in parse_label_rows(dataset_root / LABELS_TSV):
        try:
            key = parse_label_key(participant_cell, session_cell)
        except ValueError:
            raise ValueError("Label table must be fixed by hand before corrections.") from None
        if key in current or key not in pairs:
            raise ValueError("Label table must be fixed by hand before corrections.")
        current[key] = label

    updated = dict(current)
    corrected: set[LabelKey] = set()
    try:
        correction_rows = parse_label_rows(corrections_path)
    except FileNotFoundError:
        raise FileNotFoundError("Corrections file not found.") from None
    for participant_cell, session_cell, label in correction_rows:
        key = parse_label_key(participant_cell, session_cell)
        if key not in pairs:
            raise ValueError("Correction targets a participant/session not in the dataset.")
        if key in corrected:
            raise ValueError("Corrections have a duplicate participant/session.")
        corrected.add(key)
        updated[key] = label
    table = LabelTable(classes, {key: label or None for key, label in updated.items()}, description)

    changes = [
        (key, _logged(current.get(key, ""), classes), updated[key])
        for key in sorted(corrected, key=_sort_key)
        if current.get(key) != updated[key]
    ]
    if changes:
        with appended_label_changes(dataset_root, label_changes_text(_now(), "correct", changes)):
            write_labels(table, dataset_root, overwrite=True)
    return len(changes)


def finalize_labels(dataset_root: Path) -> Path:
    """Close the labels: every dataset pair labeled with a known class, nothing else in the table.

    Writes ``labels_final.json`` (label count, count per class and the SHA-256 of the canonical
    table, no date) and logs a ``finalize`` row. Already finalized → ``FileExistsError``.
    """
    if (dataset_root / FINAL_JSON).exists():
        raise FileExistsError("Labels are already finalized.")
    review = review_labels(dataset_root)
    if not review.is_complete:
        raise ValueError("Labels are incomplete or invalid.")
    fingerprint = label_fingerprint(read_labels(dataset_root))
    final = {"label_count": review.labeled, "class_counts": review.class_counts, "sha256": fingerprint}
    with appended_label_changes(dataset_root, label_changes_text(_now(), "finalize", [(None, "", "")])):
        return write_final_labels(dataset_root, final)


def reopen_labels(dataset_root: Path) -> None:
    """Explicitly reopen finalized labels: removes ``labels_final.json`` and logs a ``reopen`` row."""
    _check_root(dataset_root)
    if not (dataset_root / FINAL_JSON).exists():
        raise ValueError("Labels are not finalized.")
    with appended_label_changes(dataset_root, label_changes_text(_now(), "reopen", [(None, "", "")])):
        remove_final_labels(dataset_root)


def label_fingerprint(table: LabelTable) -> str:
    """SHA-256 of the canonical ``labels.tsv`` + ``labels.json`` (formatting-only edits keep it)."""
    tsv_text, json_text = serialize_labels(table)
    return hashlib.sha256((tsv_text + json_text).encode("utf-8")).hexdigest()


def _logged(label: str, classes: dict[str, str]) -> str:
    return label if label == "" or label in classes else INVALID_LABEL


def _sort_key(key: LabelKey) -> tuple[str, str]:
    return key[0], key[1] or ""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_root(dataset_root: Path) -> None:
    if not dataset_root.exists():
        raise FileNotFoundError("Dataset directory not found.")
    if not dataset_root.is_dir():
        raise NotADirectoryError("Dataset path is not a directory.")


def _folder_label(path: Path, prefix: str) -> str | None:
    if not path.is_dir() or not path.name.startswith(prefix):
        return None
    try:
        return validate_label(path.name.removeprefix(prefix))
    except ValueError:
        return None
