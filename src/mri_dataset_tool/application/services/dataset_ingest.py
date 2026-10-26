"""DICOM and loose NIfTI inputs as BIDS-ready studies for ``export_dataset`` (``dataset build``).

``plan_ingest`` reads only headers and the optional ``--mapping`` table and decides, before
anything is created, the participant, session, BIDS suffix and label of every series; invalid
mappings and conflicting labels raise ``InvalidBuildInput``. ``iter_ingested_studies`` then
yields one study at a time with its volumes (DICOM built as float32, NIfTI lazy). Participant
and session ids are either pseudonyms (``pseudonymize_label``, the same as the ``anonymize``
step, which leaves them unchanged) or mapping labels that ``anonymize`` pseudonymizes. Source
names, paths, ``PatientID`` and descriptions are never returned, logged or written.
Rules and table format: ``docs/dataset/ingest.md``.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

import numpy as np

from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.anonymization.pseudonym import load_key, pseudonymize_label
from mri_dataset_tool.infrastructure.bids.reader import find_nifti_files
from mri_dataset_tool.infrastructure.dataset.bids_layout import SUFFIX_DATATYPES, validate_label
from mri_dataset_tool.infrastructure.dataset.labels import LabelKey
from mri_dataset_tool.infrastructure.dataset.suffix_rules import suffix_from_text
from mri_dataset_tool.infrastructure.dicom.batch_reader import DICOMBatchReader
from mri_dataset_tool.infrastructure.dicom.identity import read_dicom_identities
from mri_dataset_tool.infrastructure.dicom.volume_builder import build_series_volume
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader

INGEST_FORMATS = ("dicom", "nifti")
MAPPING_COLUMNS = ("path", "participant", "session", "suffix")
LABEL_COLUMN = "label"
MAPPED = "MAPPED"  # suffix forced by the mapping table
NOT_4D_DWI = "NOT_4D_DWI"
_NIFTI_EXTENSION = re.compile(r"\.nii(\.gz)?$", re.IGNORECASE)

ErrorCallback = Callable[[Path, Exception], None]


@dataclass(frozen=True)
class MappingRow:
    path: PurePosixPath  # relative to the input root; "." = everything
    participant: str = ""
    session: str = ""
    suffix: str = ""
    label: str = ""


@dataclass
class IngestPlan:
    """What ``iter_ingested_studies`` will yield. ``skipped`` (code -> series) grows while iterating."""

    input_format: str
    root: Path
    entries: list = field(default_factory=list)  # DICOM: (study, subject, session, suffixes); NIfTI: (subject, session, [(path, suffix)])
    labels: dict[LabelKey, str] = field(default_factory=dict)  # final (pseudonymized) pair -> class
    skipped: Counter = field(default_factory=Counter)
    mapping_unused: int = 0
    missing_patient_id: int = 0  # DICOM studies whose participant fell back to the study (no PatientID, not mapped)

    @property
    def series(self) -> int:
        if self.input_format == "dicom":
            return sum(suffix is not None for *_, suffixes in self.entries for suffix in suffixes)
        return sum(len(files) for *_, files in self.entries)


def load_mapping(path: Path, input_root: Path, classes: dict[str, str] | None = None) -> list[MappingRow]:
    """Parse and validate a ``--mapping`` TSV; every problem is an ``InvalidBuildInput`` with fixed text."""
    try:
        text = path.read_text(encoding="utf-8-sig")  # tolerates the BOM spreadsheet programs add
    except FileNotFoundError:
        raise InvalidBuildInput("Mapping file not found.") from None
    except (OSError, UnicodeDecodeError):
        raise InvalidBuildInput("Invalid --mapping.") from None
    lines = [line for line in text.splitlines() if line.strip()]
    header = tuple(lines[0].split("\t")) if lines else ()
    if header not in (MAPPING_COLUMNS, (*MAPPING_COLUMNS, LABEL_COLUMN)):
        raise InvalidBuildInput("Invalid --mapping.")
    rows, seen, missing = [], set(), 0
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) != len(header):
            raise InvalidBuildInput("Invalid --mapping.")
        row = dict(zip(header, (cell.strip() for cell in cells)))
        raw = row["path"]
        relative = PurePosixPath(raw)
        if not raw or "\\" in raw or ":" in raw or relative.is_absolute() or ".." in relative.parts:
            raise InvalidBuildInput("Invalid --mapping.")
        if relative in seen:
            raise InvalidBuildInput("Invalid --mapping.")
        seen.add(relative)
        try:
            for name in ("participant", "session"):
                if row[name]:
                    validate_label(row[name])
        except ValueError:
            raise InvalidBuildInput("Invalid --mapping.") from None
        if row["suffix"] and row["suffix"] not in SUFFIX_DATATYPES:
            raise InvalidBuildInput("Invalid --mapping.")
        label = row.get(LABEL_COLUMN, "")
        if label and classes is None:
            raise InvalidBuildInput("Mapping labels need --classes.")
        if label and label not in classes:
            raise InvalidBuildInput("Mapping label is not one of --classes.")
        if not _exists_exactly(input_root, relative):
            missing += 1
        rows.append(MappingRow(relative, row["participant"], row["session"], row["suffix"], label))
    if missing:
        raise InvalidBuildInput(f"Mapping paths not found in the input: {missing}.")
    return rows


def _exists_exactly(root: Path, relative: PurePosixPath) -> bool:
    """*relative* exists below *root* with exactly these names: on Windows ``exists()`` ignores case,
    but the rows are compared with the input paths case-sensitively."""
    current = root
    for part in relative.parts:
        try:
            if part not in {entry.name for entry in current.iterdir()}:
                return False
        except OSError:  # not a directory, or unreadable
            return False
        current = current / part
    return True


def _resolve(rows: Sequence[MappingRow], files: Sequence[PurePosixPath], used: set[int]) -> dict[str, str]:
    """Per column, the non-empty value of the deepest row that contains every file in *files*."""
    values: dict[str, str] = {}
    applicable = [
        (len(row.path.parts), index, row)
        for index, row in enumerate(rows)
        if all(row.path == PurePosixPath(".") or row.path == f or row.path in f.parents for f in files)
    ]
    for _, index, row in sorted(applicable, key=lambda item: item[0]):  # shallow first: deeper rows overwrite
        used.add(index)
        for name in ("participant", "session", "suffix", "label"):
            if value := getattr(row, name):
                values[name] = value
    return values


def plan_ingest(
    input_format: str,
    root: Path,
    key: bytes | None = None,
    mapping: Sequence[MappingRow] | None = None,
    on_skipped: ErrorCallback | None = None,
) -> IngestPlan:
    """Decide ids, suffixes and labels from headers only (nothing is created).

    Unmapped series are counted in ``skipped`` by code (``NO_MATCH``, ``AMBIGUOUS``, ``EXCLUDED``);
    files the readers skip go to *on_skipped*. ``InvalidBuildInput``: no valid input studies, no
    series with a suffix, or two labels for the same participant/session.
    """
    key = load_key() if key is None else key  # the anonymization key (MRI_ANON_KEY)
    rows, used = list(mapping or []), set()
    plan = IngestPlan(input_format, root)
    pair_labels: dict[LabelKey, set[str]] = {}

    def place(subject: str, session: str | None, values: dict[str, str]) -> None:
        if label := values.get("label"):
            pair = (pseudonymize_label(subject, "subject", key),
                    None if session is None else pseudonymize_label(session, "session", key))
            pair_labels.setdefault(pair, set()).add(label)

    if input_format == "dicom":
        try:
            studies = DICOMBatchReader().load_studies(root, on_error=on_skipped)
        except ValueError:
            raise InvalidBuildInput("No valid input studies were found.") from None
        identities = read_dicom_identities(root, key)
        for study in studies:
            subject_default = identities.subject_by_study.get(study.study_uid) or pseudonymize_label(
                study.study_uid, "subject", key
            )
            session_default = pseudonymize_label(study.study_uid, "session", key)
            study_files = [PurePosixPath(f.relative_to(root).as_posix()) for s in study.series for f in s.files]
            study_values = _resolve(rows, study_files, used)  # rows that contain the whole study
            subject = study_values.get("participant", subject_default)
            plan.missing_patient_id += "participant" not in study_values and study.study_uid in identities.missing_patient_id
            session = study_values.get("session", session_default)
            suffixes = []
            for series in study.series:
                files = [PurePosixPath(f.relative_to(root).as_posix()) for f in series.files]
                values = _resolve(rows, files, used)
                if any(values.get(name, study_values.get(name)) != study_values.get(name) for name in ("participant", "session")):
                    raise InvalidBuildInput("Mapping gives one study more than one participant or session.")
                suffix, code = (values["suffix"], MAPPED) if "suffix" in values else identities.suffix_by_series.get(
                    series.series_uid, (None, "NO_MATCH")
                )
                suffixes.append(suffix)
                if suffix is None:
                    plan.skipped[code] += 1
                else:
                    place(subject, session, values)
            plan.entries.append((study, subject, session, suffixes))
    elif input_format == "nifti":
        files = find_nifti_files(root) if root.is_dir() else []
        if not files:
            raise InvalidBuildInput("No valid input studies were found.")
        groups: dict[tuple[str, str | None], list[tuple[Path, str]]] = {}
        for path in files:
            relative = PurePosixPath(path.relative_to(root).as_posix())
            values = _resolve(rows, [relative], used)
            suffix, code = (values["suffix"], MAPPED) if "suffix" in values else suffix_from_text(
                _NIFTI_EXTENSION.sub("", path.name)
            )
            if suffix is None:
                plan.skipped[code] += 1
                continue
            # without a mapped participant, one participant per file, from a keyed hash of its path
            subject = values.get("participant") or pseudonymize_label(relative.as_posix(), "subject", key)
            session = values.get("session") or None
            groups.setdefault((subject, session), []).append((path, suffix))
            place(subject, session, values)
        plan.entries = [(subject, session, group) for (subject, session), group in groups.items()]
    else:
        raise InvalidBuildInput("Invalid --format.")

    _check_pairs(plan, key)
    if any(len(labels) > 1 for labels in pair_labels.values()):
        raise InvalidBuildInput("Mapping assigns different labels to the same participant/session.")
    plan.labels = {pair: labels.pop() for pair, labels in pair_labels.items()}
    plan.mapping_unused = len(rows) - len(used)
    if plan.series == 0:
        raise InvalidBuildInput("No input series could be mapped to a BIDS suffix.")
    return plan


def iter_ingested_studies(plan: IngestPlan, on_error: ErrorCallback | None = None) -> Iterator[MRIStudy]:
    """Yield the planned studies one at a time (RNF02). A series that fails to build or load goes
    to *on_error* and the rest continue; a ``dwi`` that is not 4D is skipped (``NOT_4D_DWI``)."""
    report = on_error or (lambda path, error: None)
    if plan.input_format == "dicom":
        for study, subject, session, suffixes in plan.entries:
            series_out = []
            for series, suffix in zip(study.series, suffixes):
                if suffix is None:
                    continue
                try:
                    built = build_series_volume(series)
                except Exception as error:  # per-series boundary: the batch continues (RF16)
                    report(series.files[0], error)
                    continue
                if not _unusable_dwi(plan, built, suffix):
                    series_out.append(replace(built, modality=suffix, volume=np.asarray(built.volume, dtype=np.float32)))
                del built  # the float64 volume is released before the next series is built
            if series_out:
                yield MRIStudy(study_uid=study.study_uid, series=series_out, subject_id=subject, session_id=session)
            del series_out
        return
    reader = NIfTIReader()
    for subject, session, files in plan.entries:
        series_out = []
        for path, suffix in files:
            try:
                loaded = reader.load_study(path, lazy=True).series[0]
            except Exception as error:
                report(path, error)
                continue
            if not _unusable_dwi(plan, loaded, suffix):
                series_out.append(replace(loaded, modality=suffix))
            del loaded
        if series_out:
            yield MRIStudy(study_uid=None, series=series_out, subject_id=subject, session_id=session)
        del series_out


def _check_pairs(plan: IngestPlan, key: bytes) -> None:
    """The dataset writer rejects a repeated (participant, session) and a participant with and without
    sessions; caught here, before anything is created, instead of losing a study during the export.
    Compared as the dataset will hold them: after ``anonymize`` a mapping id "X" and a PatientID "X"
    become the same pseudonym (automatic ids are already pseudonyms and stay unchanged)."""
    if plan.input_format == "dicom":
        raw = [(subject, session) for _, subject, session, suffixes in plan.entries if any(suffixes)]
    else:
        raw = [(subject, session) for subject, session, _ in plan.entries]
    pairs = [
        (pseudonymize_label(subject, "subject", key), None if session is None else pseudonymize_label(session, "session", key))
        for subject, session in raw
    ]
    if len(pairs) != len(set(pairs)):
        raise InvalidBuildInput("Mapping gives the same participant/session to more than one study.")
    with_session = {subject for subject, session in pairs if session is not None}
    if any(session is None and subject in with_session for subject, session in pairs):
        raise InvalidBuildInput("Mapping gives a participant both sessions and no session.")


def _unusable_dwi(plan: IngestPlan, series: MRISeries, suffix: str) -> bool:
    """A ``dwi`` must be 4D: a 3D one is a derived map (ADC, trace...) or a single volume; it is skipped."""
    if suffix == "dwi" and len(series.metadata.get("shape", ())) != 4:
        plan.skipped[NOT_4D_DWI] += 1
        return True
    return False
