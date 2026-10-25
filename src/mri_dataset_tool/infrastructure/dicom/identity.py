"""Pseudonymized participant per DICOM study and a BIDS suffix decision per series.

A second header pass (``DICOMBatchReader`` does not read these tags): ``PatientID``,
``SeriesDescription`` and ``ProtocolName`` live only inside this function. Only the HMAC
pseudonym of the participant and the suffix decision (a suffix and a fixed code) are returned;
UIDs are used as keys in memory. Nothing is logged but counts and exception types.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pydicom

from mri_dataset_tool.infrastructure.anonymization.pseudonym import pseudonymize_label
from mri_dataset_tool.infrastructure.dataset.suffix_rules import EXCLUDED, suffix_from_text
from mri_dataset_tool.infrastructure.dicom.batch_reader import _iter_visible_files
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

IDENTITY_TAGS = ["StudyInstanceUID", "SeriesInstanceUID", "Modality", "PatientID", "SeriesDescription", "ProtocolName"]


@dataclass(frozen=True)
class DicomIdentities:
    subject_by_study: dict[str, str]  # study UID -> 16-hex participant pseudonym
    suffix_by_series: dict[str, tuple[str | None, str]]  # series UID -> (suffix, code)


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


def read_dicom_identities(directory: Path, key: bytes) -> DicomIdentities:
    """Read the identity tags below *directory* (same files and order as ``DICOMBatchReader``).

    Participant: the pseudonym of the study's ``PatientID``; without one, or with different
    ``PatientID`` values in the study, the pseudonym of the ``StudyInstanceUID`` (one participant
    per study). Suffix: ``suffix_from_text`` over the series descriptions; a non-MR series is
    ``EXCLUDED``. Unreadable or non-DICOM files are skipped silently (the batch reader reports them).
    """
    patients: dict[str, set[str]] = defaultdict(set)
    texts: dict[str, set[str]] = defaultdict(set)
    non_mr: set[str] = set()
    skipped = 0
    for path in _iter_visible_files(directory):
        try:
            dataset = pydicom.dcmread(path, stop_before_pixels=True, specific_tags=IDENTITY_TAGS)
        except Exception:  # not DICOM or unreadable: already reported by DICOMBatchReader
            skipped += 1
            continue
        study, series = _text(dataset.get("StudyInstanceUID")), _text(dataset.get("SeriesInstanceUID"))
        if not study or not series:
            continue
        if patient := _text(dataset.get("PatientID")):
            patients[study].add(patient)
        else:
            patients[study].add("")  # a file without PatientID makes the study ambiguous
        texts[series].update(t for t in (_text(dataset.get("SeriesDescription")), _text(dataset.get("ProtocolName"))) if t)
        if _text(dataset.get("Modality")).upper() != "MR":
            non_mr.add(series)

    subject_by_study = {
        study: pseudonymize_label(next(iter(ids)) if len(ids) == 1 and "" not in ids else study, "subject", key)
        for study, ids in patients.items()
    }
    suffix_by_series = {
        series: (None, EXCLUDED) if series in non_mr else suffix_from_text(*sorted(words), exclude_sub=True)
        for series, words in texts.items()  # every series has an entry, with or without descriptions
    }
    logger.debug("DICOM identities: %d studies, %d series, %d files skipped.", len(subject_by_study), len(suffix_by_series), skipped)
    return DicomIdentities(subject_by_study, suffix_by_series)
