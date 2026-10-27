"""``inputs``: what the presentation layers take from the infrastructure (Q8 of stage 5B)."""

import ast
import os
from pathlib import Path

import pytest

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput, check_build_args
from mri_dataset_tool.application.services.inputs import (
    check_input_paths,
    is_valid_folder_name,
    new_folders_valid,
    with_memory_consent,
)

PRESENTATION = Path(__file__).resolve().parents[2] / "src" / "mri_dataset_tool" / "presentation"


def test_presentation_imports_no_infrastructure_but_inspect():
    offenders = []
    for path in PRESENTATION.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            if any(name.startswith("mri_dataset_tool.infrastructure") for name in names):
                offenders.append(path.relative_to(PRESENTATION).as_posix())
    assert sorted(set(offenders)) == ["cli/commands/inspect.py"]  # known debt (D4)


def test_memory_consent_is_set_only_in_resample_and_normalize(monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", "k" * 40)
    config = {"pipeline": {"steps": [
        {"name": "validate"}, {"name": "anonymize"},
        {"name": "resample", "params": {"spacing": [2.0, 2.0, 2.0]}}, {"name": "normalize"},
    ]}, "logging": {"level": "INFO"}}
    consented, pipeline = with_memory_consent(config)
    assert [step.params.get("allow_insufficient_memory") for step in pipeline.steps] == [None, None, True, True]
    assert pipeline.steps[2].params["spacing"] == [2.0, 2.0, 2.0]
    assert consented["logging"] == {"level": "INFO"}
    assert "params" not in config["pipeline"]["steps"][3]  # the input config is not modified
    assert pipeline_from_config(consented).steps[3].params == pipeline.steps[3].params


@pytest.mark.parametrize("case", ["missing input", "output inside", "output exists"])
def test_input_paths_fail_as_check_build_args(tmp_path, case):
    source, config = tmp_path / "in", tmp_path / "run.yaml"
    config.write_text("pipeline: {}\n", encoding="utf-8")
    output = {"missing input": tmp_path / "out", "output inside": source / "out", "output exists": tmp_path}[case]
    if case != "missing input":
        source.mkdir()
    if case == "output exists":
        source, output = tmp_path / "in", tmp_path / "taken"
        output.mkdir()
        (output / ".hidden").write_text("", encoding="utf-8")  # any entry: not an empty folder
    errors = []
    for check in (lambda: check_input_paths(source, output), lambda: check_build_args(source, output, config)):
        with pytest.raises((InvalidBuildInput, FileExistsError)) as raised:
            check()
        errors.append((type(raised.value), str(raised.value)))
    assert errors[0] == errors[1]
    assert not (tmp_path / "out").exists()


def test_valid_input_paths_create_nothing(tmp_path):
    (tmp_path / "in").mkdir()
    assert check_input_paths(tmp_path / "in", tmp_path / "out") is None
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("name", ["run1", "my run", "ok.v2", "café", "dataset-2026_10", "y" * 255, "ñ" * 127])
def test_valid_folder_names(name):
    assert is_valid_folder_name(name)


@pytest.mark.parametrize(
    "name", ["", ".", "..", "a/b", "a\\b", "a:b", "a*b", 'a"b', "a<b", "a|b", "a?b", "x.", "x ", "CON", "con.txt",
             "Com1", "LPT9", "a\x01b", "\x00", "y" * 256, "ñ" * 128],  # 255 bytes at most (QA7-02)
)
def test_invalid_folder_names(name):
    assert not is_valid_folder_name(name)


def test_new_folders_of_an_output_path(tmp_path):
    """QA7-02: only the folders a run would create are judged, and the drive must exist."""
    assert new_folders_valid(tmp_path / "x" / "y") and new_folders_valid(tmp_path)
    assert not new_folders_valid(tmp_path / "x" / ("y" * 256))
    assert not new_folders_valid(tmp_path / "x" / "CON" / "y")
    if os.name == "nt":
        assert not new_folders_valid(Path(f"{tmp_path}/x/a:b"))  # an NTFS stream
        assert not new_folders_valid(Path("a:b"))  # drive A:, relative: a drive that is not there
