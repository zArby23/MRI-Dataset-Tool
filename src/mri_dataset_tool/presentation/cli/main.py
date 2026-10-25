"""Root parser of ``mri-dataset``: global options and one subcommand per module in ``commands``."""

import argparse
from collections.abc import Sequence

from mri_dataset_tool.application.pipeline.manifest import collect_versions
from mri_dataset_tool.presentation.cli._common import EXIT_USAGE, configure_output, spanish_help
from mri_dataset_tool.presentation.cli.commands import anonymize, convert, inspect

COMMANDS: tuple = (inspect, convert, anonymize)  # modules with add_parser(subparsers) and run(args) -> int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mri-dataset",
        description="Prepara datasets de resonancia magnética (DICOM, NIfTI, BIDS) para ML/DL.",
        add_help=False,
    )
    spanish_help(parser)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {collect_versions()['mri_dataset_tool']}",
        help="muestra la versión y termina",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-q", "--quiet", action="store_true", help="solo avisos, errores y el resultado final")
    verbosity.add_argument("-v", "--verbose", action="store_true", help="muestra los logs de depuración")
    subparsers = parser.add_subparsers(dest="command", title="comandos", metavar="COMANDO", required=True)
    for command in COMMANDS:
        command.add_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exit_:  # --help/--version exit with 0, bad arguments with 2
        return EXIT_USAGE if exit_.code not in (0, None) else 0
    configure_output(args.quiet, args.verbose)
    return args.run(args)
