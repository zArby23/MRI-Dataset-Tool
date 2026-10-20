import logging
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path("config")

# Allowed keys per section; any other key is rejected. Schema: docs/architecture/config.md.
_SCHEMA: dict[str, set[str]] = {
    "logging": {"level"},
    "pipeline": {"steps"},
    "report": {"path"},
}
_STEP_KEYS = {"name", "params"}


def load_config(
    run_config: Path | None = None,
    *,
    environment: str | None = None,
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> dict[str, Any]:
    """Load the effective configuration.

    Precedence, key by key: ``config_dir/default.yaml`` < ``config_dir/<environment>.yaml``
    (only when *environment* is given) < *run_config*. Mappings are merged recursively;
    any other value (lists included) replaces the lower layer. Errors carry fixed
    messages: never paths, keys or file content.
    """
    layers = [(config_dir / "default.yaml", "Default configuration file not found.")]
    if environment is not None:
        layers.append((config_dir / f"{environment}.yaml", "Environment configuration file not found."))
    if run_config is not None:
        layers.append((run_config, "Run configuration file not found."))

    config: dict[str, Any] = {}
    for path, missing_message in layers:
        config = _deep_merge(config, _read_yaml(path, missing_message))
    _validate(config)
    return config


def _read_yaml(path: Path, missing_message: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(missing_message) from None
    except OSError:
        raise OSError("Configuration file could not be read.") from None  # the cause quotes the path
    except UnicodeDecodeError:
        raise ValueError("Invalid YAML configuration file.") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ValueError("Invalid YAML configuration file.") from None  # the cause quotes file content
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a mapping.")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate(config: dict[str, Any]) -> None:
    for section, values in config.items():
        if section not in _SCHEMA:
            raise ValueError("Unknown configuration key.")
        if not isinstance(values, dict):
            raise ValueError("Configuration section must be a mapping.")
        if not values.keys() <= _SCHEMA[section]:
            raise ValueError("Unknown configuration key.")

    level = config.get("logging", {}).get("level")
    if level is not None and (not isinstance(level, str) or level not in logging.getLevelNamesMapping()):
        raise ValueError("Invalid logging.level.")

    steps = config.get("pipeline", {}).get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("pipeline.steps must be a list.")
    for step in steps:
        if not isinstance(step, dict) or not step.keys() <= _STEP_KEYS:
            raise ValueError("Invalid pipeline step entry.")
        if not isinstance(step.get("name"), str) or not isinstance(step.get("params", {}), dict):
            raise ValueError("Invalid pipeline step entry.")

    path = config.get("report", {}).get("path")
    if path is not None and not isinstance(path, str):
        raise ValueError("report.path must be a string.")
