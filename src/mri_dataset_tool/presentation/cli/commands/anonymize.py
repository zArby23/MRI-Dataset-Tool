"""``anonymize IN OUT``: DICOM tree anonymized with policy v1 (RF09)."""

import argparse
from collections import Counter
from pathlib import Path

from mri_dataset_tool.application.services.anonymize import REPORT_NAME, anonymize_dicom_tree
from mri_dataset_tool.presentation.cli._common import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    add_command,
    check_key,
    error_counter,
    format_counts,
    is_inside,
    status,
    warn_if_discouraged,
)


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers,
        "anonymize",
        help="anonimiza un árbol DICOM",
        description="Anonimiza cada archivo DICOM de IN en OUT (política v1) y escribe anonymization_report.json. "
        "Requiere la variable de entorno MRI_ANON_KEY (32 caracteres o más).",
    )
    parser.add_argument("input", type=Path, help="directorio con archivos DICOM")
    parser.add_argument("output", type=Path, help="directorio de salida, fuera de la entrada")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    source, output = args.input, args.output
    if not check_key():
        return EXIT_USAGE
    if not source.is_dir():
        print("Input directory not found.")
        return EXIT_USAGE
    if is_inside(output, source):
        print("Output directory must not be inside the input.")
        return EXIT_USAGE
    if output.exists() and not output.is_dir():
        print("Output path is not a directory.")
        return EXIT_USAGE
    if (output / REPORT_NAME).exists():
        print("Anonymization report already exists; use a new output directory.")
        return EXIT_FAILED
    warn_if_discouraged(output)

    errors, on_error = error_counter("file skipped or failed")
    status("Anonymizing DICOM files...")
    try:
        report = anonymize_dicom_tree(source, output, on_error)
    except FileExistsError:
        print("Output already exists.")
        return EXIT_FAILED
    except Exception as error:  # its message may name a file
        print(f"Run failed: {type(error).__name__}")
        return EXIT_FAILED

    totals: Counter[str] = Counter()
    for counts in report.actions.values():  # tag label → action → count; never values
        totals.update(counts)
    print(f"Files written: {report.files_written}  failed: {report.files_failed}  policy: v{report.policy_version}")
    print(f"Actions ({len(report.actions)} tags): {format_counts(totals)}")
    print(f"Errors by type: {format_counts(errors)}")
    return EXIT_OK
