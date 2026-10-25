"""``inspect``: allow-listed technical metadata of the studies under a path (RF04)."""

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from mri_dataset_tool.application.services.summary import summarize_study
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.bids.reader import BIDSReader
from mri_dataset_tool.infrastructure.dicom.batch_reader import DICOMBatchReader
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader, is_nifti_file
from mri_dataset_tool.presentation.cli._common import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    add_command,
    error_counter,
    format_counts,
    status,
)


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers,
        "inspect",
        help="muestra los metadatos técnicos de los estudios",
        description="Muestra los metadatos técnicos (lista blanca) de cada estudio, sin identificadores ni rutas. "
        "DICOM: solo cabeceras (sin dtype ni intensidad).",
    )
    parser.add_argument("path", type=Path, help="directorio (DICOM, NIfTI, BIDS) o archivo (NIfTI, BIDS)")
    parser.add_argument("--format", required=True, choices=("dicom", "nifti", "bids"), help="formato de la entrada")
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    parser.set_defaults(run=run)


def _studies(fmt: str, path: Path, on_error: Callable[[Path, Exception], None]) -> Iterable[MRIStudy]:
    if fmt == "dicom":
        return DICOMBatchReader().load_studies(path, on_error=on_error)  # headers only, no pixels
    if fmt == "nifti":
        if path.is_dir():
            return NIfTIBatchReader().iter_studies(path, on_error=on_error, lazy=True)
        return [NIfTIReader().load_study(path, lazy=True)]
    if path.is_dir():
        return BIDSBatchReader().iter_studies(path, on_error=on_error, lazy=True)
    return [BIDSReader().load_study(path, on_error=on_error, lazy=True)]


def _print_study(number: int, summary: dict[str, Any]) -> None:
    print(f"Study {number}: {summary['series_count']} series")
    for index, series in enumerate(summary["series"], start=1):
        print(f"  Series {index}")
        for key, value in series.items():
            print(f"    {key}: {json.dumps(value)}")


def run(args: argparse.Namespace) -> int:
    path: Path = args.path
    err_out = sys.stderr if args.json else sys.stdout  # --json: stdout holds only JSON
    if not path.exists():
        print("Input path not found.", file=err_out)
        return EXIT_USAGE
    if args.format == "dicom" and not path.is_dir():
        print("DICOM input must be a directory.", file=err_out)
        return EXIT_USAGE
    if args.format == "nifti" and path.is_file() and not is_nifti_file(path):
        print("NIfTI input must be a .nii or .nii.gz file or a directory.", file=err_out)
        return EXIT_USAGE

    errors, on_error = error_counter("file skipped", echo=not args.json)
    summaries = []
    if not args.json:
        status("Reading studies...")
    try:
        for study in _studies(args.format, path, on_error):  # one study loaded at a time (lazy)
            try:
                summary = summarize_study(study)  # a lazy volume is read here (e.g. truncated .nii.gz)
            except Exception as error:  # per-study boundary: the batch continues (RF16)
                on_error(Path(), error)
                continue
            summaries.append(summary)
            if not args.json:
                _print_study(len(summaries), summary)
    except Exception as error:  # the reader failed (invalid root, no valid studies); its message may name a file
        print(f"Run failed: {type(error).__name__}", file=err_out)
        return EXIT_FAILED

    if args.json:
        print(json.dumps({"studies": summaries, "errors": dict(sorted(errors.items()))}, indent=2, sort_keys=True))
    else:
        print(f"Studies: {len(summaries)}")
        print(f"Errors by type: {format_counts(errors)}")
    return EXIT_OK
