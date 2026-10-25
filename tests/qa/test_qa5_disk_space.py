"""QA5 (C7): the disk-space warning of the CLI, through ``main``.

The warning must appear when the estimate (input size) reaches 90 % of the free space of the
*output* drive, even with ``--quiet``; it holds only GiB figures (no paths), never changes the exit
code or the files written, and an unreadable output drive (missing letter, unreachable UNC share)
is silent. Free space is faked by patching ``shutil.disk_usage`` in the service.
"""

import os
import re
import string
import sys
from collections import namedtuple
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_qa5_cli import CONFIG, _bids, _cli, _digests, _env, _leaks  # noqa: E402, F401 (_env: key and cwd)

from mri_dataset_tool.application.services import disk_space  # noqa: E402
from mri_dataset_tool.application.services.disk_space import check_free_space, estimate_input_bytes  # noqa: E402

WARNING = re.compile(
    r"^WARNING INSUFFICIENT_DISK_SPACE: estimated output \d+\.\d GiB, \d+\.\d GiB free on the output drive; "
    r"consider another drive\.$",
    re.MULTILINE,
)
Usage = namedtuple("Usage", "total used free")


def _fake_free(monkeypatch, free: int, seen: list | None = None) -> None:
    def disk_usage(path):
        if seen is not None:
            seen.append(Path(path))
        return Usage(free * 2, free, free)

    monkeypatch.setattr(disk_space.shutil, "disk_usage", disk_usage)


def _argv(command: str, source: Path, out: Path) -> list:
    return {
        "convert": ["convert", "nifti-to-dicom", source, out],
        "anonymize": ["anonymize", source, out],
        "process": ["process", source, "--format", "bids", "--config", CONFIG, "--output-dir", out / "p",
                    "--manifest-path", out / "m.json"],
        "build": ["dataset", "build", source, "--output-dir", out / "b", "--config", CONFIG],
    }[command]


@pytest.mark.parametrize("command", ["convert", "anonymize", "process", "build"])
def test_warning_is_fixed_text_also_quiet_and_changes_nothing(tmp_path, monkeypatch, command) -> None:
    source = _bids(tmp_path)
    plain_code, plain_text = _cli("--quiet", *_argv(command, source, tmp_path / "plain"))
    assert not WARNING.search(plain_text)
    _fake_free(monkeypatch, 1)
    code, text = _cli("--quiet", *_argv(command, source, tmp_path / "warned"))
    assert code == plain_code
    assert len(WARNING.findall(text)) == 1, text
    assert not _leaks(text, str(tmp_path)), text
    assert _digests(tmp_path / "plain").keys() == _digests(tmp_path / "warned").keys()


def test_threshold_through_the_cli(tmp_path, monkeypatch) -> None:
    """Warn at estimate >= 90 % of the free space; silent just below it."""
    source = _bids(tmp_path)
    required = estimate_input_bytes(source)
    argv = lambda name: _argv("process", source, tmp_path / name)
    _fake_free(monkeypatch, int(required / 0.9) + 1000)
    assert not WARNING.search(_cli(*argv("below"))[1])
    _fake_free(monkeypatch, int(required / 0.9))
    assert WARNING.search(_cli(*argv("at"))[1])


def test_the_output_drive_is_checked_not_the_input_drive(tmp_path, monkeypatch) -> None:
    if not os.path.isdir("E:/"):
        pytest.skip("needs a second drive (E:)")
    source = _bids(tmp_path)
    out = Path("E:/qa5_tmp") / tmp_path.name / "deep" / "missing"
    seen: list[Path] = []
    _fake_free(monkeypatch, 10**12, seen)
    try:
        assert _cli("convert", "nifti-to-dicom", source, out)[0] == 0
    finally:
        import shutil

        shutil.rmtree(Path("E:/qa5_tmp") / tmp_path.name, ignore_errors=True)
    assert seen and all(p.drive.upper() == "E:" for p in seen), seen
    assert Path(tmp_path).drive.upper() != "E:"


def test_missing_drive_letter_is_silent_and_fails_cleanly(tmp_path) -> None:
    free_letters = [l for l in string.ascii_uppercase[3:] if not os.path.exists(f"{l}:/")]
    if os.name != "nt" or not free_letters:
        pytest.skip("Windows with an unused drive letter")
    out = Path(f"{free_letters[-1]}:/qa5/out")
    assert check_free_space(out, 10**15).free is None
    source = _bids(tmp_path)
    code, text = _cli("process", source, "--format", "bids", "--config", CONFIG, "--output-dir", out,
                      "--manifest-path", tmp_path / "m.json")
    assert code == 1 and not WARNING.search(text) and "Traceback" not in text
    assert text.strip().endswith("Run failed at process: FileNotFoundError"), text


@pytest.mark.skipif(os.name != "nt", reason="UNC paths are Windows-only")
def test_unreachable_unc_share_is_silent() -> None:
    check = check_free_space(Path("\\\\qa5-nohost.invalid\\share\\out"), 10**15)
    assert check.free is None and not check.insufficient


def test_symlinked_input_files_count_toward_the_estimate(tmp_path) -> None:
    target = tmp_path / "store" / "object"
    target.parent.mkdir()
    target.write_bytes(b"x" * 4096)
    source = tmp_path / "input"
    source.mkdir()
    try:
        (source / "sub-01_T1w.nii.gz").symlink_to(target)
    except OSError:
        pytest.skip("symlinks need privileges on this system")
    assert estimate_input_bytes(source) == 4096
