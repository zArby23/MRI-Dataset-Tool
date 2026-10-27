"""``convert dicom-to-nifti|nifti-to-dicom IN OUT`` (RF05)."""

import argparse
from pathlib import Path

from mri_dataset_tool.application.services.conversion import convert_dicom_to_nifti, convert_nifti_to_dicom
from mri_dataset_tool.application.services.inputs import is_nifti_file
from mri_dataset_tool.presentation.cli._common import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    add_command,
    error_counter,
    format_counts,
    is_inside,
    is_non_empty_dir,
    status,
    warn_if_low_disk_space,
)


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers,
        "convert", help="convierte DICOM a NIfTI o NIfTI a DICOM", description="Convierte entre DICOM y NIfTI."
    )
    directions = parser.add_subparsers(dest="direction", title="sentidos", metavar="SENTIDO", required=True)
    for name, help_text, input_help in (
        ("dicom-to-nifti", "un .nii.gz por serie DICOM", "directorio con estudios DICOM"),
        ("nifti-to-dicom", "una serie DICOM por NIfTI 3D (4D no se admite)", "archivo .nii/.nii.gz o directorio"),
    ):
        sub = add_command(directions, name, help=help_text, description=help_text)
        sub.add_argument("input", type=Path, help=input_help)
        sub.add_argument("output", type=Path, help="directorio de salida nuevo o vacío, fuera de la entrada")
        sub.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    source, output = args.input, args.output
    to_nifti = args.direction == "dicom-to-nifti"
    if not source.exists():
        print("Input path not found.")
        return EXIT_USAGE
    if to_nifti and not source.is_dir():
        print("DICOM input must be a directory.")
        return EXIT_USAGE
    if not to_nifti and source.is_file() and not is_nifti_file(source):
        print("NIfTI input must be a .nii or .nii.gz file or a directory.")
        return EXIT_USAGE
    if is_inside(output, source):
        print("Output directory must not be inside the input.")
        return EXIT_USAGE
    if output.exists() and not output.is_dir():
        print("Output path is not a directory.")
        return EXIT_USAGE
    if is_non_empty_dir(output):
        print("Output directory is not empty; use a new one.")
        return EXIT_FAILED
    warn_if_low_disk_space(source, output)

    # DICOM: also counts the files of the tree the reader skips (README, DICOMDIR, ...).
    errors, on_error = error_counter("file skipped or failed")
    status("Converting DICOM to NIfTI..." if to_nifti else "Converting NIfTI to DICOM...")
    try:
        studies = (convert_dicom_to_nifti if to_nifti else convert_nifti_to_dicom)(source, output, on_error)
    except FileExistsError:
        print("Output already exists.")
        return EXIT_FAILED
    except Exception as error:  # its message may name a file
        print(f"Run failed: {type(error).__name__}")
        return EXIT_FAILED

    if to_nifti:
        print(f"Studies converted: {len(studies)}  series written: {sum(len(s.series) for s in studies)}")
    else:
        files = sum(len(series.files) for study in studies for series in study.series)
        print(f"Studies converted: {len(studies)}  DICOM files written: {files}")
    print(f"Errors by type: {format_counts(errors)}")
    return EXIT_OK
