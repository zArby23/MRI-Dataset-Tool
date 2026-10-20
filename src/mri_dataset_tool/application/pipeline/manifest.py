import copy
import json
import os
import platform
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.pipeline.step import build_step
from mri_dataset_tool.domain.models.transformation import StudyReport


@dataclass(frozen=True)
class RunManifest:
    """Everything needed to reproduce a pipeline run (RF15, RNF11).

    ``config`` is the effective configuration (``load_config``), ``steps`` the steps as
    executed (``name``, ``version``, ``params``) and ``reports`` one ``StudyReport`` per
    study. ``timestamps`` are not deterministic and are excluded from equality.
    """

    config: dict[str, Any]
    versions: dict[str, str]
    steps: list[dict[str, Any]]
    reports: list[StudyReport]
    timestamps: dict[str, str] = field(default_factory=dict, compare=False)

    @classmethod
    def from_run(cls, config: dict[str, Any], pipeline: Pipeline, reports: list[StudyReport]) -> "RunManifest":
        return cls(
            config=copy.deepcopy(config),
            versions=collect_versions(),
            steps=[
                {"name": step.name, "version": step.version, "params": copy.deepcopy(step.params)}
                for step in pipeline.steps
            ],
            reports=list(reports),
            timestamps={"created_at": datetime.now(UTC).isoformat()},
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RunManifest":
        try:
            data = json.loads(text)
            return cls(
                config=data["config"],
                versions=data["versions"],
                steps=[_parse_step(step) for step in data["steps"]],
                reports=[StudyReport.from_dict(report) for report in data["reports"]],
                timestamps=data["timestamps"],
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("Invalid run manifest.") from None  # the cause quotes keys or content

    def write(self, path: Path, overwrite: bool = False) -> Path:
        """Write the manifest as JSON to *path* (usually ``config["report"]["path"]``).

        Atomic: written to a temporary file in the same directory and moved with
        ``os.replace``, so a failure never leaves a truncated manifest or temporaries.
        The parent directory must exist.
        """
        if path.exists() and not overwrite:
            raise FileExistsError("Run manifest file already exists.")
        text = self.to_json()
        tmp = path.with_name(f".{path.name}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise OSError("Run manifest file could not be written.") from None  # the cause quotes the path
        return path


def collect_versions() -> dict[str, str]:
    return {
        "mri_dataset_tool": _distribution_version("mri-dataset-tool"),
        "python": platform.python_version(),
        "numpy": _distribution_version("numpy"),
        "nibabel": _distribution_version("nibabel"),
        "pydicom": _distribution_version("pydicom"),
    }


def _distribution_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _parse_step(data: dict[str, Any]) -> dict[str, Any]:
    step = {"name": data["name"], "version": data["version"], "params": data["params"]}
    if not (isinstance(step["name"], str) and isinstance(step["version"], str) and isinstance(step["params"], dict)):
        raise ValueError("Invalid run manifest step.")  # replaced by the fixed from_json message
    return step


def pipeline_from_config(config: dict[str, Any]) -> Pipeline:
    return Pipeline([build_step(step["name"], step.get("params")) for step in config["pipeline"]["steps"]])


def pipeline_from_manifest(manifest: RunManifest) -> Pipeline:
    """Rebuild the exact pipeline of *manifest*; unknown steps or changed versions raise ``ValueError``."""
    steps = []
    for recorded in manifest.steps:
        step = build_step(recorded["name"], recorded["params"])
        if step.version != recorded["version"]:
            raise ValueError("Processing step version differs from the run manifest.")
        steps.append(step)
    return Pipeline(steps)
