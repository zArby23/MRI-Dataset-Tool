"""Shared CLI helpers. Every message is fixed text: never a path, an id or an exception message."""

import argparse
import logging
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, load_key

EXIT_OK = 0  # also when some studies failed and were reported (RF16)
EXIT_FAILED = 1  # previous output exists or a stage failed
EXIT_USAGE = 2  # invalid arguments, key or input; nothing was created

_quiet = False


class SpanishHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, "uso: " if prefix is None else prefix)


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


def is_discouraged_location(path: Path) -> bool:
    """True if *path* is on drive C: or under the system temporary directory."""
    resolved = path.resolve()
    return resolved.drive.upper() == "C:" or resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())


def warn_if_discouraged(*paths: Path) -> None:
    if any(is_discouraged_location(path) for path in paths):
        print("WARNING: an output is on drive C: or in the temporary directory; large runs should go elsewhere (E:/).")


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
