import copy
import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import nibabel
import numpy
import pydicom

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
                steps=[{"name": s["name"], "version": s["version"], "params": s["params"]} for s in data["steps"]],
                reports=[StudyReport.from_dict(report) for report in data["reports"]],
                timestamps=data["timestamps"],
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("Invalid run manifest.") from None  # the cause quotes keys or content

    def write(self, path: Path, overwrite: bool = False) -> Path:
        """Write the manifest as JSON to *path* (usually ``config["report"]["path"]``)."""
        # shortcut: not atomic (a crash mid-write leaves a partial file); use staging + os.replace if it matters
        try:
            with path.open("w" if overwrite else "x", encoding="utf-8") as file:
                file.write(self.to_json())
        except FileExistsError:
            raise FileExistsError("Run manifest file already exists.") from None
        except OSError:
            raise OSError("Run manifest file could not be written.") from None  # the cause quotes the path
        return path


def collect_versions() -> dict[str, str]:
    return {
        "mri_dataset_tool": version("mri-dataset-tool"),
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "nibabel": nibabel.__version__,
        "pydicom": pydicom.__version__,
    }


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
