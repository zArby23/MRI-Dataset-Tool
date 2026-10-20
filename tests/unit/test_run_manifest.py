import ast
import json
from importlib.metadata import PackageNotFoundError
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from mri_dataset_tool.application.pipeline import manifest as manifest_module
from mri_dataset_tool.application.pipeline.manifest import (
    RunManifest,
    collect_versions,
    pipeline_from_config,
    pipeline_from_manifest,
)
from mri_dataset_tool.application.pipeline.step import register_step
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.domain.models.transformation import StudyReport


@register_step("manifest.add")
@dataclass(frozen=True)
class AddStep:
    amount: float = 1.0
    name: ClassVar[str] = "manifest.add"
    version: ClassVar[str] = "1"

    @property
    def params(self) -> dict[str, Any]:
        return {"amount": self.amount}

    def apply(self, study: MRIStudy) -> MRIStudy:
        return replace(study, series=[replace(s, volume=s.volume + self.amount) for s in study.series])


@register_step("manifest.fail")
@dataclass(frozen=True)
class FailOnSubjectStep:
    subject_id: str
    name: ClassVar[str] = "manifest.fail"
    version: ClassVar[str] = "1"

    @property
    def params(self) -> dict[str, Any]:
        return {"subject_id": self.subject_id}

    def apply(self, study: MRIStudy) -> MRIStudy:
        if study.subject_id == self.subject_id:
            raise ValueError("PatientName=SECRET header value")
        return study


CONFIG = {
    "logging": {"level": "INFO"},
    "pipeline": {
        "steps": [
            {"name": "manifest.add", "params": {"amount": 2.0}},
            {"name": "manifest.fail", "params": {"subject_id": "02"}},
        ]
    },
    "report": {"path": "data/output/run_manifest.json"},
}


def _batch(tmp_path: Path):
    for subject in ("01", "02", "03"):
        series = MRISeries(files=[tmp_path / f"sub-{subject}_T1w.nii.gz"], volume=np.full((2, 2, 2), float(subject)))
        yield MRIStudy(study_uid=None, series=[series], subject_id=subject)


def _run(pipeline, tmp_path: Path) -> tuple[list[np.ndarray], list[StudyReport]]:
    volumes: list[np.ndarray] = []
    reports = pipeline.run(_batch(tmp_path), lambda s, r: volumes.append(s.series[0].volume), lambda p, e: None)
    return volumes, reports


def test_two_runs_from_the_same_manifest_are_identical(tmp_path: Path) -> None:
    first_pipeline = pipeline_from_config(CONFIG)
    first_volumes, first_reports = _run(first_pipeline, tmp_path)
    manifest = RunManifest.from_run(CONFIG, first_pipeline, first_reports)
    saved = RunManifest.from_json(manifest.to_json())

    runs = []
    for _ in range(2):
        pipeline = pipeline_from_manifest(saved)
        volumes, reports = _run(pipeline, tmp_path)
        runs.append((volumes, RunManifest.from_run(saved.config, pipeline, reports)))

    for volumes, rerun in runs:
        assert len(volumes) == len(first_volumes) == 2
        for got, expected in zip(volumes, first_volumes):
            np.testing.assert_array_equal(got, expected)
        assert rerun == manifest  # timestamps excluded from equality
        rerun_data, original_data = json.loads(rerun.to_json()), json.loads(manifest.to_json())
        del rerun_data["timestamps"], original_data["timestamps"]
        assert rerun_data == original_data


def test_manifest_contents(tmp_path: Path) -> None:
    pipeline = pipeline_from_config(CONFIG)
    _, reports = _run(pipeline, tmp_path)
    manifest = RunManifest.from_run(CONFIG, pipeline, reports)

    assert manifest.config == CONFIG and manifest.config is not CONFIG
    assert set(manifest.versions) == {"mri_dataset_tool", "python", "numpy", "nibabel", "pydicom"}
    assert manifest.versions == collect_versions()
    assert manifest.steps == [
        {"name": "manifest.add", "version": "1", "params": {"amount": 2.0}},
        {"name": "manifest.fail", "version": "1", "params": {"subject_id": "02"}},
    ]
    assert [r.steps[-1].status for r in manifest.reports] == ["ok", "failed", "ok"]
    assert "created_at" in manifest.timestamps


def test_json_has_no_exception_messages(tmp_path: Path) -> None:
    pipeline = pipeline_from_config(CONFIG)
    _, reports = _run(pipeline, tmp_path)
    text = RunManifest.from_run(CONFIG, pipeline, reports).to_json()

    assert "SECRET" not in text and "PatientName" not in text
    failed = json.loads(text)["reports"][1]
    assert failed["source_path"] == str(tmp_path / "sub-02_T1w.nii.gz")
    assert failed["steps"][-1] == {
        "name": "manifest.fail",
        "version": "1",
        "params": {"subject_id": "02"},
        "status": "failed",
        "error_type": "ValueError",
    }


def test_from_json_round_trip(tmp_path: Path) -> None:
    pipeline = pipeline_from_config(CONFIG)
    _, reports = _run(pipeline, tmp_path)
    manifest = RunManifest.from_run(CONFIG, pipeline, reports)

    rebuilt = RunManifest.from_json(manifest.to_json())

    assert rebuilt == manifest
    assert rebuilt.timestamps == manifest.timestamps
    assert all(isinstance(r, StudyReport) for r in rebuilt.reports)


def _manifest_with_step(name: str, version: str = "1") -> RunManifest:
    return RunManifest(config={}, versions={}, steps=[{"name": name, "version": version, "params": {}}], reports=[])


def test_unknown_step_in_manifest_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown processing step"):
        pipeline_from_manifest(_manifest_with_step("manifest.missing"))


def test_changed_step_version_raises_value_error() -> None:
    with pytest.raises(ValueError, match="version differs"):
        pipeline_from_manifest(_manifest_with_step("manifest.add", version="99"))


@pytest.mark.parametrize(
    "text",
    [
        "not json SECRET",
        "[1, 2]",
        '{"config": {}}',
        '{"config": {}, "versions": {}, "steps": [{"name": "x"}], "reports": [], "timestamps": {}}',
        '{"config": {}, "versions": {}, "steps": [], "reports": [{"index": 1}], "timestamps": {}}',
        '{"config": {}, "versions": {}, "steps": [], "reports": [1], "timestamps": {}}',
        '{"config": {}, "versions": {}, "steps": [], "timestamps": {}, "reports":'
        ' [{"index": 1, "source_path": null, "steps": [{"name": "a", "version": "1", "params": {},'
        ' "status": "SECRET", "error_type": null}]}]}',
        '{"config": {}, "versions": {}, "steps": [{"name": ["x"], "version": "1", "params": {}}],'
        ' "reports": [], "timestamps": {}}',
        '{"config": {}, "versions": {}, "steps": [{"name": "x", "version": 1, "params": {}}],'
        ' "reports": [], "timestamps": {}}',
        '{"config": {}, "versions": {}, "steps": [{"name": "x", "version": "1", "params": [1]}],'
        ' "reports": [], "timestamps": {}}',
    ],
)
def test_malformed_json_raises_fixed_value_error(text: str) -> None:
    with pytest.raises(ValueError) as info:
        RunManifest.from_json(text)
    assert str(info.value) == "Invalid run manifest."
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_write_uses_report_path_and_refuses_overwrite(tmp_path: Path) -> None:
    manifest = _manifest_with_step("manifest.add")
    path = tmp_path / "secret_run.json"

    assert manifest.write(path) == path
    assert RunManifest.from_json(path.read_text(encoding="utf-8")) == manifest

    with pytest.raises(FileExistsError) as info:
        manifest.write(path)
    assert "secret_run" not in str(info.value)

    manifest.write(path, overwrite=True)


def test_write_to_missing_directory_raises_fixed_message(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="could not be written") as info:
        _manifest_with_step("manifest.add").write(tmp_path / "secret_dir" / "run.json")
    assert "secret_dir" not in str(info.value)


def test_overwrite_replaces_atomically(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text("old", encoding="utf-8")
    manifest = _manifest_with_step("manifest.add")

    manifest.write(path, overwrite=True)

    assert RunManifest.from_json(path.read_text(encoding="utf-8")) == manifest
    assert [p.name for p in tmp_path.iterdir()] == ["run.json"]


def test_failed_write_keeps_previous_file_and_leaves_no_temporaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "secret_run.json"
    path.write_text("old", encoding="utf-8")

    def failing_replace(src: Path, dst: Path) -> None:
        raise PermissionError(f"cannot replace {dst}")

    monkeypatch.setattr(manifest_module.os, "replace", failing_replace)
    with pytest.raises(OSError, match="could not be written") as info:
        _manifest_with_step("manifest.add").write(path, overwrite=True)

    assert "secret_run" not in str(info.value)
    assert path.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["secret_run.json"]


def test_missing_distribution_version_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(manifest_module, "version", missing)
    versions = collect_versions()
    assert versions["mri_dataset_tool"] == versions["numpy"] == "unknown"
    assert versions["python"]


def test_manifest_module_imports_no_format_or_array_libraries() -> None:
    tree = ast.parse(Path(manifest_module.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported.isdisjoint({"numpy", "pydicom", "nibabel"})
