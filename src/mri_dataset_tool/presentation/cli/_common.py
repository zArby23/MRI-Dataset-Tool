"""Shared CLI helpers. Every message is fixed text: never a path, an id or an exception message."""

import argparse
import logging
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from mri_dataset_tool.application.services.disk_space import check_free_space, estimate_input_bytes
from mri_dataset_tool.application.services.inputs import KEY_ENV_VAR, load_key

EXIT_OK = 0  # also when some studies failed and were reported (RF16)
EXIT_FAILED = 1  # previous output exists or a stage failed
EXIT_USAGE = 2  # invalid arguments, key or input; nothing was created

_quiet = False


class SpanishHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, "uso: " if prefix is None else prefix)


class CliArgumentParser(argparse.ArgumentParser):
    """``error()`` prints the usage and a fixed message: argparse's own message repeats the typed value
    (an invalid choice, an unrecognized path...), which may be an id. Subparsers inherit this class."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: Invalid arguments (see --help).\n")


def spanish_help(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Spanish titles and ``-h``; *parser* must be built with ``add_help=False``."""
    parser.formatter_class = SpanishHelpFormatter
    parser._positionals.title, parser._optionals.title = "argumentos", "opciones"
    parser.add_argument("-h", "--help", action="help", help="muestra esta ayuda y termina")
    return parser


def add_command(subparsers, name: str, **kwargs) -> argparse.ArgumentParser:
    """A subcommand parser with the Spanish help of the root parser."""
    return spanish_help(subparsers.add_parser(name, add_help=False, **kwargs))


def configure_output(quiet: bool = False, verbose: bool = False) -> None:
    """``--quiet`` hides status lines and logs below ERROR; ``--verbose`` shows DEBUG logs."""
    global _quiet
    _quiet = quiet
    level = logging.ERROR if quiet else logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig()  # a no-op if the root logger already has handlers (e.g. pytest)
    logging.getLogger().setLevel(level)


def status(message: str) -> None:
    """Print a stage or result line unless ``--quiet``. *message* must be fixed text and counts."""
    if not _quiet:
        print(message)


def progress(done: int, total: int, label: str) -> None:
    status(f"[{done}/{total}] {label}")


def warn_if_low_disk_space(source: Path, output: Path) -> None:
    """Fixed WARNING (also with ``--quiet``) if the estimated output reaches 90 % of the free space
    of the output drive; only aggregate figures, never paths. It does not block the run."""
    check = check_free_space(output, estimate_input_bytes(source))
    if check.insufficient:
        print(
            f"WARNING INSUFFICIENT_DISK_SPACE: estimated output {check.required / 2**30:.1f} GiB, "
            f"{check.free / 2**30:.1f} GiB free on the output drive; consider another drive."
        )


def check_key() -> bool:
    """True if the anonymization key is usable; otherwise prints a fixed message (never the key)."""
    try:
        load_key()
    except ValueError:
        print(f"{KEY_ENV_VAR} is not set or is shorter than 32 characters; nothing was run.")
        return False
    return True


def error_counter(label: str, echo: bool = True) -> tuple[Counter[str], Callable[[Path, Exception], None]]:
    """An ``on_error`` that counts by exception type and prints only the type (the path may be PHI).

    ``echo=False`` only counts (``--json`` output must stay parseable)."""
    counts: Counter[str] = Counter()

    def on_error(path: Path, error: Exception) -> None:
        counts[type(error).__name__] += 1
        if echo:
            status(f"  {label} {sum(counts.values())}: {type(error).__name__}")

    return counts, on_error


def format_counts(counts: Counter[str]) -> str:
    return str(dict(sorted(counts.items())) or "none")


def is_inside(path: Path, parent: Path) -> bool:
    """True if *path* is *parent* or below it (both resolved)."""
    return path.resolve().is_relative_to(parent.resolve())


def is_non_empty_dir(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())
