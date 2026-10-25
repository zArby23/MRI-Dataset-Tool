"""``disk_space`` service (input size estimate and the 90 % free-space threshold)."""

import logging
import shutil
from collections import namedtuple
from pathlib import Path

import pytest

from mri_dataset_tool.application.services import disk_space
from mri_dataset_tool.application.services.disk_space import check_free_space, estimate_input_bytes

Usage = namedtuple("Usage", "total used free")


@pytest.fixture
def free(monkeypatch):
    """Set the free bytes that ``shutil.disk_usage`` reports; records the paths it was asked about."""
    asked: list[Path] = []

    def set_free(value: int) -> list[Path]:
        def fake(path):
            asked.append(Path(path))
            return Usage(10 * value, 9 * value, value)

        monkeypatch.setattr(disk_space.shutil, "disk_usage", fake)
        return asked

    return set_free


def test_estimate_sums_regular_files_and_skips_hidden(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.nii.gz").write_bytes(b"1" * 100)
    (tmp_path / "y.dcm").write_bytes(b"2" * 50)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "pack").write_bytes(b"3" * 1000)
    (tmp_path / ".hidden.nii").write_bytes(b"4" * 1000)
    assert estimate_input_bytes(tmp_path) == 150
    assert estimate_input_bytes(tmp_path / "y.dcm") == 50


def test_estimate_of_an_empty_input_is_zero(tmp_path, free):
    assert estimate_input_bytes(tmp_path) == 0
    free(1000)
    assert not check_free_space(tmp_path, 0).insufficient


@pytest.mark.parametrize(("required", "insufficient"), [(890, False), (899, False), (900, True), (1000, True), (5000, True)])
def test_threshold_is_ninety_percent_of_the_free_space(tmp_path, free, required, insufficient):
    free(1000)
    check = check_free_space(tmp_path, required)
    assert (check.required, check.free, check.insufficient) == (required, 1000, insufficient)


def test_custom_margin(tmp_path, free):
    free(1000)
    assert not check_free_space(tmp_path, 990, margin=0.0).insufficient
    assert check_free_space(tmp_path, 1000, margin=0.0).insufficient


def test_missing_output_uses_the_first_existing_ancestor(tmp_path, free):
    asked = free(1000)
    check_free_space(tmp_path / "new" / "deeper" / "out", 10)
    assert asked == [tmp_path]


def test_oserror_reports_nothing_and_logs_only_the_type(tmp_path, monkeypatch, caplog):
    def broken(path):
        raise PermissionError(f"denied: {path}")

    monkeypatch.setattr(disk_space.shutil, "disk_usage", broken)
    caplog.set_level(logging.DEBUG)
    check = check_free_space(tmp_path / "sub-SECRET", 10**12)
    assert (check.free, check.insufficient) == (None, False)
    assert "PermissionError" in caplog.text and str(tmp_path) not in caplog.text


def test_real_disk_usage_is_read(tmp_path):
    check = check_free_space(tmp_path, 1)
    assert check.free is not None and check.free <= shutil.disk_usage(tmp_path).total


def _symlink_or_skip(link: Path, target: Path, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:  # Windows without the symlink privilege (Developer Mode off)
        pytest.skip("symlinks cannot be created here")


def test_symlinks_to_files_count_their_target(tmp_path):
    store = tmp_path / ".git" / "annex"  # hidden: never walked, but reached through the links
    store.mkdir(parents=True)
    (store / "blob").write_bytes(b"x" * 300)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "outside").write_bytes(b"y" * 40)
    root = tmp_path / "ds"
    root.mkdir()
    _symlink_or_skip(root / "sub-01_T1w.nii.gz", store / "blob")
    _symlink_or_skip(root / "broken.nii.gz", store / "missing")
    _symlink_or_skip(root / "linked_dir", tmp_path / "data", directory=True)
    _symlink_or_skip(root / "loop", root, directory=True)
    assert estimate_input_bytes(root) == 300  # file link only: not the broken one, not linked directories


def test_symlinks_logic_with_patched_stat(tmp_path, monkeypatch):
    """Same rules without real symlinks (runs on Windows too)."""
    root = tmp_path / "ds"
    root.mkdir()
    Info = namedtuple("Info", "st_mode st_size")
    infos = {"annexed.nii.gz": Info(0o100644, 300), "fifo": Info(0o010644, 999)}

    def fake_walk(path):
        yield str(root), ["linked_dir", ".datalad"], ["annexed.nii.gz", "broken.nii.gz", "fifo", ".hidden"]

    def fake_stat(path):
        name = Path(path).name
        if name not in infos:
            raise FileNotFoundError(name)  # broken link
        return infos[name]

    monkeypatch.setattr(disk_space.os, "walk", fake_walk)
    monkeypatch.setattr(disk_space.os, "stat", fake_stat)
    assert estimate_input_bytes(root) == 300
