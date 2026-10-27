import os
from collections.abc import Callable
from pathlib import Path

import pydicom

from mri_dataset_tool.infrastructure.anonymization.dicom import anonymize_dataset
from mri_dataset_tool.infrastructure.anonymization.pseudonym import load_key, pseudonymize_label
from mri_dataset_tool.infrastructure.anonymization.report import AnonymizationReport
# Approved exception: reuses the private walker of the frozen DICOMBatchReader so both skip hidden files alike.
from mri_dataset_tool.infrastructure.dicom.batch_reader import _iter_visible_files
from mri_dataset_tool.infrastructure.dicom._study_assembler import quiet_value_validation
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

REPORT_NAME = "anonymization_report.json"


@quiet_value_validation()
def anonymize_dicom_tree(
    input_dir: Path,
    output_dir: Path,
    on_error: Callable[[Path, Exception], None] | None = None,
) -> AnonymizationReport:
    """Anonymize every DICOM file below *input_dir* into *output_dir* (RF09, RNF07).

    Each file is read whole with pydicom, the policy (``DICOM_ACTIONS``) is applied at every
    level and it is written to ``study-<id>/series-<id>/<id>.dcm``, where each ``<id>`` is a
    16-hex pseudonym of the new UID (names never carry identifiers). Pixel data are not
    touched. Inputs are never modified and outputs are never overwritten: an existing output
    raises ``FileExistsError``, reported per file. A file that cannot be read, is not DICOM,
    lacks a UID or fails to write is reported through ``on_error(path, error)`` and the batch
    continues; a callback that raises is caught and only its type is logged. Hidden files and
    directories (``.git``...) are skipped silently, as in ``DICOMBatchReader``.

    The report (actions and counts per tag, never values) is written to
    ``output_dir/anonymization_report.json`` and returned. Before reading or creating anything:
    *output_dir* inside (or equal to) *input_dir* → ``ValueError``; missing key →
    ``ValueError``; an existing report → ``FileExistsError``.
    """
    if not input_dir.exists():
        raise FileNotFoundError("Input directory does not exist.")
    if not input_dir.is_dir():
        raise NotADirectoryError("Input path is not a directory.")
    if output_dir.resolve().is_relative_to(input_dir.resolve()):
        raise ValueError("Output directory must not be inside the input directory.")
    key = load_key()
    report_path = output_dir / REPORT_NAME
    if report_path.exists():
        raise FileExistsError("Anonymization report already exists.")

    report = AnonymizationReport()
    for path in _iter_visible_files(input_dir):
        try:
            dataset = pydicom.dcmread(path)
            uids = [dataset.get(name) for name in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID")]
            if not all(uids):
                raise ValueError("Missing study, series or SOP instance UID.")
            file_report = AnonymizationReport()  # merged only if the file is written
            anonymize_dataset(dataset, key, file_report)
            study, series, instance = (
                pseudonymize_label(str(dataset[name].value), "path", key)
                for name in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID")
            )
            _write_new(dataset, output_dir / f"study-{study}" / f"series-{series}" / f"{instance}.dcm")
        except Exception as error:  # per-file boundary: any failure must not stop the batch
            report.files_failed += 1
            logger.warning("Skipping DICOM file that failed to anonymize (%s)", type(error).__name__)
            _report(on_error, path, error)
            continue
        report.files_written += 1
        report.merge_actions(file_report)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_new_text(report.to_json(), report_path)
    logger.info("Anonymized %d DICOM files. Errors: %d.", report.files_written, report.files_failed)
    return report


def _write_new(dataset: pydicom.Dataset, target: Path) -> None:
    """Write atomically (temporary file + ``os.replace``); an existing target is never replaced.

    As in ``NIfTIWriter``, there is a minimal window between the existence check and the
    replace (single-user process).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError("Output file already exists.")
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        dataset.save_as(temporary, enforce_file_format=True)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _write_new_text(text: str, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _report(
    on_error: Callable[[Path, Exception], None] | None, path: Path, error: Exception
) -> None:
    if on_error is None:
        return
    try:
        on_error(path, error)
    except Exception as callback_error:
        logger.warning("on_error callback failed (%s)", type(callback_error).__name__)
