"""C3: ``anonymize`` needs the key, never overwrites a report and prints only labels and counts."""

import logging
from collections import namedtuple

import pytest

from mri_dataset_tool.application.services import disk_space
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main
from test_anonymize_dicom_tree import KEY, PLANTED, write_synthetic_series


@pytest.fixture(autouse=True)
def _reset_output():
    root = logging.getLogger()
    level = root.level
    yield
    _common.configure_output()
    root.setLevel(level)


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    write_synthetic_series(tmp_path / "in" / "series")
    (tmp_path / "in" / "README").write_text("not dicom", encoding="utf-8")
    return tmp_path / "in"


def _clean(text: str, tmp_path) -> bool:
    return not [secret for secret in [*PLANTED, KEY, str(tmp_path)] if secret in text]


def test_anonymize_prints_counts_and_actions_only(tmp_path, source, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    assert main(["--verbose", "anonymize", str(source), str(tmp_path / "out")]) == 0
    captured = capsys.readouterr()
    assert "Files written: 3  failed: 1  policy: v1" in captured.out
    assert "Actions (" in captured.out and "'removed': " in captured.out
    assert "Errors by type: {'InvalidDicomError': 1}" in captured.out
    assert (tmp_path / "out" / "anonymization_report.json").is_file()
    for text in (captured.out, captured.err, caplog.text):
        assert _clean(text, tmp_path)


def test_existing_report_exits_one(tmp_path, source, capsys):
    assert main(["anonymize", str(source), str(tmp_path / "out")]) == 0
    before = sorted((tmp_path / "out").rglob("*"))
    assert main(["anonymize", str(source), str(tmp_path / "out")]) == 1
    assert "Anonymization report already exists" in capsys.readouterr().out
    assert sorted((tmp_path / "out").rglob("*")) == before


@pytest.mark.parametrize("key", [None, "short"])
def test_missing_key_exits_two_before_anything(tmp_path, source, monkeypatch, capsys, key):
    if key is None:
        monkeypatch.delenv("MRI_ANON_KEY")
    else:
        monkeypatch.setenv("MRI_ANON_KEY", key)
    assert main(["anonymize", str(source), str(tmp_path / "out")]) == 2
    assert not (tmp_path / "out").exists()
    assert "MRI_ANON_KEY is not set" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("input_name", "output_name"), [("missing", "out"), ("in", "in/out"), ("in", "in"), ("in", "file_out")]
)
def test_invalid_paths_exit_two(tmp_path, source, capsys, input_name, output_name):
    (tmp_path / "file_out").write_text("x", encoding="utf-8")
    assert main(["anonymize", str(tmp_path / input_name), str(tmp_path / output_name)]) == 2
    assert not (tmp_path / "out").exists() and not (source / "out").exists()
    assert _clean(capsys.readouterr().out, tmp_path)


@pytest.mark.parametrize(("free", "warned"), [(10, True), (10**15, False)])
def test_low_disk_space_warns_without_changing_the_exit_code(tmp_path, source, monkeypatch, capsys, free, warned):
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(disk_space.shutil, "disk_usage", lambda path: usage(free, 0, free))
    assert main(["anonymize", str(source), str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert ("WARNING INSUFFICIENT_DISK_SPACE" in out) == warned
    assert "drive C:" not in out
    assert _clean(out, tmp_path)
