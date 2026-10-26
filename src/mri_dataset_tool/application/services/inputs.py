"""What the presentation layers (CLI and GUI) need from the infrastructure, so they import only
``application`` (Q8 of stage 5B). ``inspect`` still reads with the infrastructure readers (known debt).
"""

import re
from pathlib import Path
from typing import Any

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.services.dataset_build import check_build_args
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, load_key
from mri_dataset_tool.infrastructure.config.loader import DEFAULT_CONFIG_DIR, load_config
from mri_dataset_tool.infrastructure.dataset.splits import DEFAULT_RATIOS, DEFAULT_SEED, check_split_params
from mri_dataset_tool.infrastructure.nifti.reader import is_nifti_file

__all__ = [
    "DEFAULT_CONFIG_DIR", "DEFAULT_RATIOS", "DEFAULT_SEED", "KEY_ENV_VAR", "MEMORY_STEPS", "check_input_paths",
    "check_split_params", "is_nifti_file", "is_valid_folder_name", "load_config", "load_key", "project_config_dir",
    "with_memory_consent",
]

# Steps that check the available RAM and accept ``allow_insufficient_memory``.
MEMORY_STEPS = ("resample", "normalize")


_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10))}


def is_valid_folder_name(name: str) -> bool:
    """A plain folder name valid on Windows and Linux: no separators, ``..``, characters invalid on
    Windows, trailing dot or space, or reserved device name (``CON``, ``COM1``...)."""
    return (
        bool(name) and name not in (".", "..") and not _INVALID_NAME_CHARS.search(name)
        and not name.endswith((".", " ")) and name.split(".")[0].upper() not in _RESERVED_NAMES
    )


def project_config_dir() -> Path:
    """The ``config/`` folder the GUI reads (``default.yaml`` and the presets): the project's, next to
    ``src/``, whatever the working directory; ``config`` of the working directory if it is not there.
    The only place that locates it (the portable build, G9, points it to its bundled YAML files)."""
    bundled = Path(__file__).resolve().parents[4] / "config"
    return bundled if (bundled / "default.yaml").is_file() else DEFAULT_CONFIG_DIR


def check_input_paths(dataset_root: Path, output_dir: Path) -> None:
    """The input and output checks of ``check_build_args`` (same order and messages), for a step that
    has no config yet; the config is checked with everything else later."""
    # shortcut: this module file stands for an existing config file (check_build_args checks it before the
    # output); it does not exist if the package runs without .py files (zip, frozen build): G9 must check it.
    check_build_args(dataset_root, output_dir, Path(__file__))


def with_memory_consent(config: dict[str, Any]) -> tuple[dict[str, Any], Pipeline]:
    """*config* with ``allow_insufficient_memory: true`` in every ``resample``/``normalize`` step (the
    user's consent, recorded in the run manifest like a config file value) and its pipeline."""
    steps = [
        {**step, "params": {**step.get("params", {}), "allow_insufficient_memory": True}}
        if step["name"] in MEMORY_STEPS else step
        for step in config["pipeline"]["steps"]
    ]
    config = {**config, "pipeline": {**config["pipeline"], "steps": steps}}
    return config, pipeline_from_config(config)
