"""The label table of an exported dataset as rows, for the GUI labels step (Q6 of stage 5B).

``read_label_rows`` lists every (participant, session) pair of the dataset with its class and its
defect; rows of ``labels.tsv`` that are not dataset pairs (foreign or invalid ids) are only counted
by ``review_labels``. ``apply_label_edits`` applies edits through ``apply_label_corrections`` (all or
nothing, logged in ``labels_changes.tsv``). Only dataset ids (pseudonyms) and classes are handled.
"""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mri_dataset_tool.application.services.labels import apply_label_corrections, dataset_pairs, review_labels
from mri_dataset_tool.infrastructure.dataset.bids_layout import validate_label
from mri_dataset_tool.infrastructure.dataset.labels import LABELS_TSV, LabelKey, parse_label_key, parse_label_rows

UNLABELED, UNKNOWN_CLASS, DUPLICATED, MISSING = "UNLABELED", "UNKNOWN_CLASS", "DUPLICATED", "MISSING"


@dataclass(frozen=True)
class LabelRow:
    participant: str
    session: str | None
    label: str | None  # a class; None when unlabeled or defective (a defective cell is never shown)
    defect: str | None  # UNLABELED | UNKNOWN_CLASS | DUPLICATED | MISSING; None = labeled with a class


def read_label_rows(dataset_root: Path) -> list[LabelRow]:
    """One row per dataset pair, sorted as ``dataset_pairs``. Structural defects of the label files
    raise the fixed errors of ``review_labels``."""
    review = review_labels(dataset_root)
    defects = {
        **{key: UNLABELED for key in review.unlabeled},
        **{key: UNKNOWN_CLASS for key in review.unknown_class},
        **{key: DUPLICATED for key in review.duplicated},
        **{key: MISSING for key in review.missing},
    }
    labels: dict[LabelKey, str] = {}
    for participant_cell, session_cell, label in parse_label_rows(dataset_root / LABELS_TSV):
        try:
            labels[parse_label_key(participant_cell, session_cell)] = label
        except ValueError:  # counted by review_labels
            continue
    return [
        LabelRow(subject, session, None if (subject, session) in defects else labels[(subject, session)],
                 defects.get((subject, session)))
        for subject, session in dataset_pairs(dataset_root)
    ]


def apply_label_edits(dataset_root: Path, edits: dict[LabelKey, str]) -> int:
    """Set the class of each edited pair (``""`` = unlabeled); returns the number of changes.

    All or nothing, as ``apply_label_corrections`` (it rejects pairs outside the dataset and classes
    not in ``labels.json``). The temporary corrections table holds only pseudonyms, lives next to the
    dataset and is always removed."""
    if not edits:
        return 0
    lines = ["participant_id\tsession_id\tlabel"]
    for (subject, session), label in sorted(edits.items(), key=lambda item: (item[0][0], item[0][1] or "")):
        try:
            validate_label(subject)
            if session is not None:
                validate_label(session)
        except ValueError:
            raise ValueError("Label edits have an invalid participant or session id.") from None
        if any(character in label for character in "\t\r\n"):  # would add rows to the table
            raise ValueError("Label edits have an invalid class.")
        lines.append(f"sub-{subject}\t{'' if session is None else 'ses-' + session}\t{label}")
    handle, name = tempfile.mkstemp(prefix=".label_edits_", suffix=".tsv", dir=dataset_root.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as table:
            table.write("\n".join(lines) + "\n")
        return apply_label_corrections(dataset_root, Path(name))
    finally:
        Path(name).unlink(missing_ok=True)
