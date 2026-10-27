"""Preview and edition of the DICOM / loose NIfTI ingest decisions, for the GUI mapping table.

``preview_ingest`` returns what ``plan_ingest`` decided per series (headers only, nothing is created).
``apply_edit`` turns an edit of the table into ``--mapping`` rows (``MappingRow``), so the GUI and
``dataset build --mapping`` share one format; ``write_mapping`` saves them as that TSV. The paths are
relative to the input root and are shown only in the table and the saved TSV, never logged.
"""

import posixpath
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath

from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput
from mri_dataset_tool.application.services.dataset_ingest import (
    LABEL_COLUMN,
    MAPPING_COLUMNS,
    ErrorCallback,
    MappingRow,
    SeriesDecision,
    load_mapping,
    plan_ingest,
)
from mri_dataset_tool.infrastructure.dataset.bids_layout import SUFFIX_DATATYPES, validate_label

PreviewRow = SeriesDecision  # location, suffix | None, code, participant, session, label
EDITABLE_COLUMNS = ("suffix", "participant", "session", "label")
MAPPING_SUFFIXES = tuple(SUFFIX_DATATYPES)  # the suffixes a mapping row may force


def preview_ingest(
    input_format: str,
    root: Path,
    mapping: Sequence[MappingRow] | None = None,
    classes: dict[str, str] | None = None,
    on_skipped: ErrorCallback | None = None,
) -> list[PreviewRow]:
    """One row per input series, skipped ones included (``suffix`` ``None`` and their code).

    ``InvalidBuildInput`` as ``plan_ingest``, and for mapping labels without *classes* or outside them
    (as ``load_mapping``)."""
    for row in mapping or []:
        _check_label(row.label, classes)
    return list(plan_ingest(input_format, root, mapping=mapping, on_skipped=on_skipped).decisions)


def apply_edit(
    mapping: Sequence[MappingRow],
    rows: Sequence[PreviewRow],
    input_format: str,
    index: int,
    column: str,
    value: str,
    classes: dict[str, str] | None = None,
) -> list[MappingRow]:
    """*mapping* with the edit of *column* of preview row *index* (an empty *value* clears it).

    The suffix applies to the series folder (DICOM) or file (NIfTI); participant, session and label to
    the study: its folder in DICOM (the deepest folder holding all its series), the file in NIfTI.
    ``InvalidBuildInput`` (fixed text) for an invalid value or a folder that also holds other series
    or studies (a mapping file can still express it by hand)."""
    if column not in EDITABLE_COLUMNS:
        raise InvalidBuildInput("Invalid --mapping.")
    if column in ("participant", "session") and value:
        try:
            validate_label(value)
        except ValueError:
            raise InvalidBuildInput("Invalid --mapping.") from None
    if column == "suffix" and value and value not in MAPPING_SUFFIXES:
        raise InvalidBuildInput("Invalid --mapping.")
    if column == "label":
        _check_label(value, classes)
    row = rows[index]
    if column == "suffix":
        path = row.location
        if any(other.location == path for i, other in enumerate(rows) if i != index):
            raise InvalidBuildInput("Several series share this folder.")
    else:
        path = _study_path(rows, index) if input_format == "dicom" else row.location
    by_path = {item.path: item for item in mapping}
    by_path[path] = replace(by_path.get(path, MappingRow(path)), **{column: value})
    return sorted((item for item in by_path.values() if _has_values(item)), key=lambda item: item.path.parts)


def write_mapping(mapping: Sequence[MappingRow], path: Path, root: Path, classes: dict[str, str] | None = None) -> None:
    """Save *mapping* as a new ``--mapping`` TSV (with the label column) and read it back with
    ``load_mapping``; an existing *path* → ``FileExistsError`` (never overwritten). A file that does not
    read back is removed and its ``InvalidBuildInput`` raised."""
    lines = ["\t".join((*MAPPING_COLUMNS, LABEL_COLUMN))] + [
        "\t".join((row.path.as_posix(), row.participant, row.session, row.suffix, row.label)) for row in mapping
    ]
    handle = path.open("x", encoding="utf-8", newline="\n")  # "x": fails (creating nothing) if it exists
    try:
        with handle:
            handle.write("\n".join(lines) + "\n")
    except BaseException:
        path.unlink(missing_ok=True)  # only the file this call created: never a partial table
        raise
    try:
        load_mapping(path, root, classes)
    except InvalidBuildInput:
        path.unlink(missing_ok=True)
        raise


def _study_path(rows: Sequence[PreviewRow], index: int) -> PurePosixPath:
    """The deepest folder holding every series of the study of row *index* and no other series."""
    study = (rows[index].participant, rows[index].session)  # unique per DICOM study (plan_ingest checks it)
    inside = [row.location for row in rows if (row.participant, row.session) == study]
    folder = PurePosixPath(posixpath.commonpath([location.as_posix() for location in inside]))
    others = [row.location for row in rows if (row.participant, row.session) != study]
    if any(folder == PurePosixPath(".") or folder == other or folder in other.parents for other in others):
        raise InvalidBuildInput("The study folder also holds other studies.")
    return folder


def _check_label(label: str, classes: dict[str, str] | None) -> None:
    if label and classes is None:
        raise InvalidBuildInput("Mapping labels need --classes.")
    if label and label not in classes:
        raise InvalidBuildInput("Mapping label is not one of --classes.")


def _has_values(row: MappingRow) -> bool:
    return any((row.participant, row.session, row.suffix, row.label))
