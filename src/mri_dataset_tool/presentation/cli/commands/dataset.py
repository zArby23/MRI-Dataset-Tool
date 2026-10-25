"""``dataset export-ml|report|build``: ML exports, report and the full dataset build (RF10, RF13, RF14)."""

import argparse
from pathlib import Path

from mri_dataset_tool.application.services.dataset import write_ml_exports
from mri_dataset_tool.application.services.dataset_build import (
    InvalidBuildInput,
    StageFailed,
    build_dataset,
    check_build_args,
    is_exported_dataset,
    load_build_pipeline,
)
from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.infrastructure.config.loader import DEFAULT_CONFIG_DIR
from mri_dataset_tool.infrastructure.dataset.splits import DEFAULT_RATIOS, DEFAULT_SEED, check_split_params
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
    warn_if_low_disk_space,
)

# Status events of build_dataset -> console text (counts only).
_MESSAGES = {
    "export": "Exporting the dataset (pipeline)...",
    "exported": "Studies written: {studies}  series: {series}  participants: {participants}  errors: {errors}",
    "labels_skipped": "Labels: skipped (no --classes).",
    "label_template": "Label template written ({classes} classes).",
    "corrections_skipped": "Label corrections: skipped (no --corrections).",
    "corrections_applied": "Label corrections applied: {rows}",
    "labels_finalized": "Labels finalized ({labels} labels).",
    "ml_exports_skipped": "ML exports: skipped (labels incomplete; fix them or use --allow-unfinalized).",
    "ml_exports": "ML export files written: {files}",
    "report": "Report files written: {files}",
}


def _split_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ratios", nargs=3, type=float, default=list(DEFAULT_RATIOS), metavar=("TRAIN", "VAL", "TEST"),
        help="proporciones de las particiones por participante (por defecto 0.7 0.15 0.15)",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="semilla de las particiones (por defecto 0)")
    parser.add_argument("--allow-unfinalized", action="store_true", help="exporta aunque las etiquetas no estén cerradas")


def add_parser(subparsers) -> None:
    parser = add_command(subparsers, "dataset", help="exportes para ML, reporte y construcción del dataset")
    actions = parser.add_subparsers(dest="action", title="acciones", metavar="ACCION", required=True)

    export_ml = add_command(
        actions, "export-ml", help="escribe dataset_index.csv, datalist.json y splits.*",
        description="Escribe dataset_index.csv, datalist.json, splits.tsv y splits.json en la raíz del dataset.",
    )
    export_ml.add_argument("dataset", type=Path, help="raíz del dataset BIDS exportado")
    _split_args(export_ml)

    report = add_command(
        actions, "report", help="escribe dataset_report.{json,md,xml,xlsx}",
        description="Resumen estadístico del dataset en JSON, Markdown, XML y XLSX (los cuatro o ninguno).",
    )
    report.add_argument("dataset", type=Path, help="raíz del dataset BIDS exportado")
    report.add_argument("output", type=Path, help="directorio del reporte, fuera del dataset")

    build = add_command(
        actions, "build", help="flujo completo: pipeline, dataset BIDS, etiquetas, exportes y reporte",
        description="Procesa IN (BIDS) con --config (debe incluir anonymize; requiere MRI_ANON_KEY) y escribe "
        "OUT/dataset y OUT/report. Con --classes escribe la plantilla de etiquetas; --corrections las asigna. "
        "Etiquetas completas: se cierran; incompletas: sin exportes para ML salvo --allow-unfinalized. "
        "config/default.yaml se lee desde el directorio actual.",
    )
    build.add_argument("input", type=Path, help="dataset BIDS de entrada")
    build.add_argument("--output-dir", type=Path, required=True, help="directorio nuevo, fuera de la entrada")
    build.add_argument("--config", type=Path, required=True, help="archivo YAML de la corrida (con anonymize)")
    build.add_argument("--classes", nargs="+", metavar="NAME[=DESCRIPTION]", help="clases; escribe la plantilla")
    build.add_argument("--corrections", type=Path, help="TSV de correcciones (exige --classes)")
    _split_args(build)

    for action in (export_ml, report, build):
        action.set_defaults(run=run)


def _export_ml(args: argparse.Namespace) -> int:
    try:
        check_split_params(args.ratios, args.seed)
    except ValueError:
        print("Invalid --ratios.")
        return EXIT_USAGE
    if not args.dataset.is_dir():
        print("Dataset directory not found.")
        return EXIT_USAGE
    if not is_exported_dataset(args.dataset):  # never write ML files (source ids) into a raw input
        print("Not a dataset exported by this tool.")
        return EXIT_USAGE
    try:
        written = write_ml_exports(args.dataset, args.ratios, args.seed, allow_unfinalized=args.allow_unfinalized)
    except FileExistsError:
        print("ML export files already exist.")
        return EXIT_FAILED
    except Exception as error:  # e.g. labels not finalized; only the type is shown
        print(f"ML exports failed: {type(error).__name__}")
        return EXIT_FAILED
    print(f"ML export files written: {len(written)}")
    return EXIT_OK


def _report(args: argparse.Namespace) -> int:
    if not args.dataset.is_dir():
        print("Dataset directory not found.")
        return EXIT_USAGE
    if not is_exported_dataset(args.dataset):
        print("Not a dataset exported by this tool.")
        return EXIT_USAGE
    if is_inside(args.output, args.dataset):
        print("Report directory must be outside the dataset.")
        return EXIT_USAGE
    if args.output.exists() and not args.output.is_dir():
        print("Output path is not a directory.")
        return EXIT_USAGE
    errors, on_error = error_counter("report read error")
    status("Writing the dataset report...")
    try:
        written = report_dataset(args.dataset, args.output, on_error)
    except FileExistsError:  # raised before reading anything
        print("Report files already exist.")
        return EXIT_FAILED
    except Exception as error:  # e.g. no valid studies; its message may name a file
        print(f"Report failed: {type(error).__name__}")
        return EXIT_FAILED
    print(f"Report files written: {len(written)}")
    print(f"Report read errors: {format_counts(errors)}")
    return EXIT_OK


def _print_status(event: str, counts: dict[str, int]) -> None:
    if event == "labels_incomplete":
        print(f"WARNING LABELS_INCOMPLETE: {counts}")
    else:
        status(_MESSAGES[event].format(**counts))


def _build(args: argparse.Namespace) -> int:
    if not check_key():
        return EXIT_USAGE
    try:
        classes = check_build_args(
            args.input, args.output_dir, args.config, args.classes, args.corrections, args.ratios, args.seed
        )
    except InvalidBuildInput as error:  # fixed text
        print(error)
        return EXIT_USAGE
    except FileExistsError as error:  # fixed text
        print(error)
        return EXIT_FAILED
    try:
        config, pipeline = load_build_pipeline(args.config, DEFAULT_CONFIG_DIR)
    except InvalidBuildInput as error:
        print(error)
        return EXIT_USAGE
    warn_if_low_disk_space(args.input, args.output_dir)

    # Separate counts: files the reader skips (e.g. git-annex pointers) are not export errors.
    skipped, on_skipped = error_counter("input file skipped")
    errors, on_error = error_counter("error")
    report_errors, on_report_error = error_counter("report read error")
    try:
        build_dataset(
            args.input, args.output_dir, pipeline, config,
            classes=classes, corrections=args.corrections, ratios=args.ratios, seed=args.seed,
            allow_unfinalized=args.allow_unfinalized,
            on_skipped=on_skipped, on_error=on_error, on_report_error=on_report_error, on_status=_print_status,
        )
    except StageFailed as failure:  # its cause may name a file
        print(f"Run failed at {failure.stage}: {failure.error_type}")
        return EXIT_FAILED
    print(f"Errors by type: {format_counts(errors)}")
    print(f"Input files skipped by the reader: {format_counts(skipped)}")
    print(f"Report read errors: {format_counts(report_errors)}")
    return EXIT_OK


def run(args: argparse.Namespace) -> int:
    return {"export-ml": _export_ml, "report": _report, "build": _build}[args.action](args)
