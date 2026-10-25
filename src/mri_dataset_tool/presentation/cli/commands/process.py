"""``process IN --format nifti|bids --config CFG --output-dir OUT``: configured pipeline (RF06–RF09, RF15)."""

import argparse
from pathlib import Path

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.services.pipeline_run import StageFailed, previous_outputs_exist, run_pipeline
from mri_dataset_tool.infrastructure.config.loader import load_config
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

_STAGES = {
    "process": "Processing studies...",
    "manifest": "Writing the run manifest ({studies} studies, {files_written} files written)...",
    "verify": "Verifying: running again from the saved manifest...",
}


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers,
        "process",
        help="aplica el pipeline de la configuración a NIfTI o BIDS",
        description="Aplica los pasos de --config (validate, anonymize, reorient, resample, normalize...) a cada "
        "estudio, uno a la vez, y escribe cada serie como NIfTI float32 (study-NNN[_series-MMM].nii.gz) y el "
        "manifiesto de la corrida. Con el paso anonymize hace falta MRI_ANON_KEY. DICOM: conviértelo antes con "
        "'convert dicom-to-nifti'. allow_insufficient_memory solo se activa en la configuración. Rutas relativas "
        "(config/default.yaml, report.path) desde el directorio actual: ejecútalo desde la raíz del repositorio.",
    )
    parser.add_argument("input", type=Path, help="directorio NIfTI o dataset BIDS")
    parser.add_argument(
        "--format", required=True, choices=("nifti", "bids", "dicom"), metavar="{nifti,bids}", help="formato de la entrada"
    )
    parser.add_argument("--config", type=Path, required=True, help="archivo YAML de la corrida (pipeline.steps)")
    parser.add_argument("--output-dir", type=Path, required=True, help="directorio de los NIfTI procesados")
    parser.add_argument("--manifest-path", type=Path, help="JSON del manifiesto (por defecto report.path de la config)")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="reconstruye el pipeline desde el manifiesto y lo vuelve a correr para comprobar que se reproduce "
        "(tarda el doble); sin esta opción solo se comprueba que el manifiesto no tenga rutas de origen",
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    source, output_dir = args.input, args.output_dir
    if args.format == "dicom":
        print("DICOM input: convert it first with 'mri-dataset convert dicom-to-nifti'.")
        return EXIT_USAGE
    if not source.is_dir():
        print("Input directory not found.")
        return EXIT_USAGE
    if not args.config.is_file():
        print("Config file not found.")
        return EXIT_USAGE
    try:
        config = load_config(args.config)
    except Exception as error:  # fixed messages, but never printed: only the type
        print(f"Invalid config: {type(error).__name__}")
        return EXIT_USAGE
    if any(step.get("name") == "anonymize" for step in config["pipeline"]["steps"]) and not check_key():
        return EXIT_USAGE  # the anonymize step reads the key when it is built
    try:
        pipeline = pipeline_from_config(config)
    except Exception as error:
        print(f"Invalid config: {type(error).__name__}")
        return EXIT_USAGE
    manifest_path = args.manifest_path or Path(config["report"]["path"])
    if is_inside(output_dir, source) or is_inside(manifest_path, source):
        print("Outputs must not be inside the input directory.")
        return EXIT_USAGE
    if output_dir.exists() and not output_dir.is_dir():
        print("Output path is not a directory.")
        return EXIT_USAGE
    if previous_outputs_exist(output_dir, manifest_path):
        print("Outputs of a previous run exist (study-*.nii.gz in the output directory or the manifest); remove them first.")
        return EXIT_FAILED
    warn_if_low_disk_space(source, output_dir)

    errors, on_error = error_counter("error")
    replay_errors, on_replay_error = error_counter("replay error")
    try:
        result = run_pipeline(
            pipeline, config, args.format, source, output_dir, manifest_path, on_error,
            verify=args.verify, on_replay_error=on_replay_error,
            on_status=lambda stage, counts: status(_STAGES[stage].format(**counts)),
        )
    except StageFailed as failure:  # its cause may name a file
        print(f"Run failed at {failure.stage}: {failure.error_type}")
        return EXIT_FAILED

    studies, failed = len(result.reports), result.failed
    print(f"Studies: {studies}  ok: {studies - failed}  failed in a step: {failed}  files written: {result.files_written}")
    print(f"Errors by type: {format_counts(errors)}")
    redacts = any(getattr(step, "redacts_sources", False) for step in pipeline.steps)
    if result.no_sources:
        print("Manifest without source paths: yes")
    elif redacts:
        print("Manifest without source paths: no")
    else:  # by design: without a redacting step (anonymize) the manifest records the source paths
        print("Manifest without source paths: no (no anonymize step; the manifest records them)")
    if result.reproduced is None:
        print("Reproduced from manifest: not checked (use --verify)")
    else:
        print(f"Replay errors by type: {format_counts(replay_errors)}")
        print(f"Reproduced from manifest: {'yes' if result.reproduced else 'no'}")
    sources_ok = result.no_sources or not redacts
    return EXIT_OK if sources_ok and result.reproduced is not False else EXIT_FAILED
