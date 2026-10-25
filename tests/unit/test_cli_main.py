"""C0: root parser, global options, exit codes and the shared CLI helpers."""

import argparse
import logging
import subprocess
from collections import namedtuple
import sys
from pathlib import Path

import pytest

from mri_dataset_tool.application.services import disk_space
from mri_dataset_tool.presentation.cli import _common, main as cli_main
from mri_dataset_tool.presentation.cli.main import main

KEY = "k" * 32


class _FakeCommand:
    """A command module stand-in: records the parsed args and returns a fixed code."""

    def __init__(self, code: int) -> None:
        self.code, self.seen = code, None

    def add_parser(self, subparsers) -> None:
        parser = subparsers.add_parser("fake", help="comando de prueba")
        parser.add_argument("value")
        parser.set_defaults(run=self.run)

    def run(self, args: argparse.Namespace) -> int:
        self.seen = args
        _common.status("Doing fake work...")
        return self.code


@pytest.fixture(autouse=True)
def _reset_output():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    _common.configure_output()  # clears the quiet flag
    root.handlers[:], root.level = handlers, level


@pytest.fixture
def fake(monkeypatch):
    command = _FakeCommand(code=0)
    monkeypatch.setattr(cli_main, "COMMANDS", (command,))
    return command


def test_help_is_spanish_and_exits_zero(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("uso: mri-dataset")
    assert "opciones" in out and "comandos" in out and "muestra esta ayuda" in out


def test_version_exits_zero(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("mri-dataset ")


@pytest.mark.parametrize(
    "argv", [[], ["unknown"], ["--quiet", "--verbose", "fake", "x"], ["fake"], ["--bogus", "fake", "x"]]
)
def test_bad_arguments_exit_two(fake, argv):
    assert main(argv) == _common.EXIT_USAGE
    assert fake.seen is None


@pytest.mark.parametrize("code", [0, 1, 2])
def test_dispatches_to_command_and_returns_its_code(monkeypatch, code):
    command = _FakeCommand(code)
    monkeypatch.setattr(cli_main, "COMMANDS", (command,))
    assert main(["fake", "value-1"]) == code
    assert command.seen.value == "value-1"


def test_quiet_hides_status_and_verbose_enables_debug(fake, capsys):
    main(["--quiet", "fake", "x"])
    assert capsys.readouterr().out == ""
    assert logging.getLogger().level == logging.ERROR
    main(["--verbose", "fake", "x"])
    assert "Doing fake work..." in capsys.readouterr().out
    assert logging.getLogger().level == logging.DEBUG
    main(["fake", "x"])
    assert logging.getLogger().level == logging.WARNING


def test_python_dash_m_runs_the_cli():
    result = subprocess.run(
        [sys.executable, "-m", "mri_dataset_tool.presentation.cli", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.startswith("uso: mri-dataset")


def test_check_key(monkeypatch, capsys):
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    assert _common.check_key()
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("MRI_ANON_KEY", "short-secret")
    assert not _common.check_key()
    out = capsys.readouterr().out
    assert "MRI_ANON_KEY is not set" in out and "short-secret" not in out


def test_error_counter_prints_only_the_type(capsys):
    counts, on_error = _common.error_counter("error")
    secret = Path("sub-PATIENT01") / "ses-1" / "scan.nii.gz"
    on_error(secret, ValueError(f"cannot read {secret}"))
    on_error(secret, OSError("PATIENT01"))
    on_error(secret, ValueError("x"))
    assert counts == {"ValueError": 2, "OSError": 1}
    out = capsys.readouterr().out
    assert "error 3: ValueError" in out and "PATIENT01" not in out and "cannot read" not in out
    assert _common.format_counts(counts) == "{'OSError': 1, 'ValueError': 2}"
    assert _common.format_counts(type(counts)()) == "none"


def test_progress_line(capsys):
    _common.progress(2, 5, "studies")
    assert capsys.readouterr().out == "[2/5] studies\n"


def test_low_disk_space_warning_has_figures_only(tmp_path, monkeypatch, capsys):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "sub-PATIENT01.nii.gz").write_bytes(b"x" * 2048)
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(disk_space.shutil, "disk_usage", lambda path: usage(4096, 2048, 2048))
    _common.configure_output(quiet=True)  # the warning is printed even with --quiet
    _common.warn_if_low_disk_space(tmp_path / "in", tmp_path / "out")
    out = capsys.readouterr().out
    assert out.startswith("WARNING INSUFFICIENT_DISK_SPACE: estimated output 0.0 GiB, 0.0 GiB free")
    assert str(tmp_path) not in out and "PATIENT01" not in out
    monkeypatch.setattr(disk_space.shutil, "disk_usage", lambda path: usage(10**12, 0, 10**12))
    _common.warn_if_low_disk_space(tmp_path / "in", tmp_path / "out")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("argv", [["fake"], ["--bogus", "fake", "x"], ["fake", "x", "E:/data/sub-PATIENT01"], ["sub-PATIENT01"]])
def test_argparse_errors_print_a_fixed_message(fake, capsys, argv):
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "error: Invalid arguments (see --help)." in err and "PATIENT01" not in err and "bogus" not in err
