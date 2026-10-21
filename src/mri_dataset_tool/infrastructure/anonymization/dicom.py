"""Apply the DICOM policy (``DICOM_ACTIONS``) to a pydicom dataset, at every level.

Elements not in the table are removed: private elements, unlisted sequences (with all their
nested content), overlays and file meta elements included. Each action is counted in an
``AnonymizationReport``; no value is ever logged or recorded.
"""

import re

from pydicom.dataset import Dataset

from mri_dataset_tool.infrastructure.anonymization.policy import (
    DICOM_ACTIONS,
    DICOM_DEFAULT_ACTION,
    DICOM_FIXED_VALUES,
    Action,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import pseudonymize_label, pseudonymize_uid
from mri_dataset_tool.infrastructure.anonymization.report import AnonymizationReport

_AGE = re.compile(r"(\d{3})([DWMY])")
_DAYS_PER_YEAR = {"D": 365.25, "W": 365.25 / 7, "M": 12, "Y": 1}


def generalize_date(value: str) -> str:
    """DA → ``YYYY0101``; anything that does not start with a 4-digit year → ``""``."""
    return value[:4] + "0101" if value[:4].isdigit() else ""


def generalize_datetime(value: str) -> str:
    """DT → ``YYYY`` (a valid DT); anything that does not start with a 4-digit year → ``""``."""
    return value[:4] if value[:4].isdigit() else ""


def generalize_age(value: str) -> str:
    """AS → lower bound of its 10-year range (``047Y`` → ``040Y``); >= 90 → ``090Y``; invalid → ``""``."""
    match = _AGE.fullmatch(value.strip())
    if not match:
        return ""
    years = int(int(match[1]) / _DAYS_PER_YEAR[match[2]])
    return f"{min(years // 10 * 10, 90):03d}Y"


_GENERALIZERS = {"DA": generalize_date, "DT": generalize_datetime, "AS": generalize_age}


def anonymize_dataset(dataset: Dataset, key: bytes, report: AnonymizationReport) -> None:
    """Anonymize *dataset* and its file meta in place (the caller passes a copy read from disk)."""
    if getattr(dataset, "preamble", None) is not None:
        dataset.preamble = b"\0" * 128  # free bytes outside any element: exporters may write PHI there
    file_meta = getattr(dataset, "file_meta", None)
    if file_meta is not None:
        _apply(file_meta, key, report)
    _apply(dataset, key, report)
    for keyword, value in DICOM_FIXED_VALUES.items():
        if keyword not in dataset:
            setattr(dataset, keyword, value)
            report.record(dataset[keyword].tag, Action.REPLACED)


def _apply(dataset: Dataset, key: bytes, report: AnonymizationReport) -> None:
    for tag in list(dataset.keys()):
        element = dataset[tag]
        action = DICOM_DEFAULT_ACTION if tag.is_private else DICOM_ACTIONS.get(element.keyword, DICOM_DEFAULT_ACTION)
        if action is Action.REMOVED:
            del dataset[tag]
        elif action is Action.EMPTIED:
            element.value = ""
        elif action is Action.REPLACED:
            element.value = _replacement(element.keyword, element.value, element.VR, key)
        elif action is Action.GENERALIZED:
            value = element.value
            generalized = _GENERALIZERS[element.VR](value) if isinstance(value, str) else ""
            element.value = generalized
            if not generalized:
                action = Action.EMPTIED
        elif element.VR == "SQ":  # a kept sequence: its items follow the same policy
            for item in element.value:
                _apply(item, key, report)
        report.record(tag, action)


def _replacement(keyword: str, value: object, vr: str, key: bytes) -> object:
    if keyword in DICOM_FIXED_VALUES:
        return DICOM_FIXED_VALUES[keyword]
    if not value:
        return value
    if vr == "UI":
        return pseudonymize_uid(str(value), key)
    return pseudonymize_label(str(value).strip(), "subject", key)  # PatientID, same domain as subject_id
