"""ML/DL export files of a written BIDS dataset (RF13; no tensors, see docs/dataset/export.md): ``dataset_index.csv``, ``datalist.json``
(MONAI style), ``splits.tsv`` and ``splits.json``, all at the dataset root.

Paths are POSIX and relative to the dataset root. Ids carry the BIDS prefix in the files. Cells are
ids (alphanumeric), BIDS suffixes, relative paths, split names and class names (validated by
``labels.py`` against formula prefixes), so no cell can start a spreadsheet formula.
"""

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from mri_dataset_tool.infrastructure.bids.entities import parse_bids_filename
from mri_dataset_tool.infrastructure.bids.reader import find_nifti_files
from mri_dataset_tool.infrastructure.dataset.bids_layout import bids_path
from mri_dataset_tool.infrastructure.dataset.bids_writer import write_all
from mri_dataset_tool.infrastructure.dataset.labels import LabelTable
from mri_dataset_tool.infrastructure.dataset.splits import SPLITS

INDEX_CSV = "dataset_index.csv"
DATALIST_JSON = "datalist.json"
SPLITS_TSV = "splits.tsv"
SPLITS_JSON = "splits.json"
INDEX_COLUMNS = ("participant_id", "session_id", "suffix", "run", "image", "label", "split")
UNLABELED = "unlabeled"


@dataclass(frozen=True)
class ImageEntry:
    participant: str
    session: str | None
    suffix: str
    run: int | None
    image: str  # relative to the dataset root, POSIX


def scan_images(root: Path) -> list[ImageEntry]:
    """Every NIfTI image of the dataset, sorted by relative POSIX path (same order on every OS:
    ``Path`` ordering is case-insensitive on Windows); hidden entries are ignored.

    A NIfTI file whose path is not exactly what ``bids_path`` gives for its own entities
    (other entities, ``.nii``, wrong folder) → fixed ``ValueError``; none → ``ValueError``.
    """
    entries = []
    for file in find_nifti_files(root):
        relative = file.relative_to(root).as_posix()
        try:
            entities = parse_bids_filename(file.name)
            run_text = entities.other.get("run")
            run = None if run_text is None else int(run_text)
            expected = bids_path(entities.sub, entities.ses, entities.suffix, ".nii.gz", run)
        except ValueError:
            raise ValueError("Dataset contains a file outside the BIDS layout.") from None
        if expected.as_posix() != relative or set(entities.other) - {"run"}:
            raise ValueError("Dataset contains a file outside the BIDS layout.")
        entries.append(ImageEntry(entities.sub, entities.ses, entities.suffix, run, relative))
    if not entries:
        raise ValueError("No dataset images were found.")
    return sorted(entries, key=lambda entry: entry.image)


def write_ml_files(
    root: Path,
    entries: list[ImageEntry],
    labels: LabelTable | None,
    assignment: dict[str, str],
    unlabeled: list[str],
    warnings: list[dict[str, object]],
    ratios: tuple[float, ...],
    seed: int,
    labels_finalized: bool | None = None,
) -> list[Path]:
    """Write the four export files (all or none; existing → ``FileExistsError``).

    *labels_finalized* goes to ``splits.json`` (``None`` = dataset without labels).
    """
    rows = []
    datalist: dict[str, list[dict[str, str]]] = {name: [] for name in SPLITS}
    datalist_unlabeled: list[dict[str, str]] = []
    for entry in entries:
        label = None if labels is None else labels.labels.get((entry.participant, entry.session))
        split = assignment.get(entry.participant, "")
        rows.append((
            f"sub-{entry.participant}",
            "" if entry.session is None else f"ses-{entry.session}",
            entry.suffix,
            "" if entry.run is None else str(entry.run),
            entry.image,
            label or "",
            split,
        ))
        item = {"image": entry.image} if label is None else {"image": entry.image, "label": label}
        if labels is not None and label is None:
            datalist_unlabeled.append(item)  # never in a split with an invented label
        else:
            datalist[split].append(item)

    document: dict[str, object] = dict(datalist)
    if labels is not None:
        document["classes"] = sorted(labels.classes)
        document[UNLABELED] = datalist_unlabeled
    counts = {name: sum(1 for split in assignment.values() if split == name) for name in SPLITS}
    summary = {
        "seed": seed,
        "ratios": dict(zip(SPLITS, ratios)),
        "stratified": labels is not None,
        "labels_finalized": labels_finalized,
        "participants": counts,
        "unlabeled_participants": [f"sub-{p}" for p in unlabeled],
        "warnings": warnings,
    }
    split_lines = ["participant_id\tsplit", *(f"sub-{p}\t{s}" for p, s in assignment.items())]
    return write_all({
        root / INDEX_CSV: _csv(INDEX_COLUMNS, rows),
        root / DATALIST_JSON: _json(document),
        root / SPLITS_TSV: "".join(f"{line}\n" for line in split_lines).encode("utf-8"),
        root / SPLITS_JSON: _json(summary),
    })


def _csv(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _json(data: dict[str, object]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
