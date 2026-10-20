from pathlib import Path

import pytest

from mri_dataset_tool.infrastructure.config import loader
from mri_dataset_tool.infrastructure.config.loader import load_config

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "config"
    directory.mkdir()
    _write(
        directory / "default.yaml",
        "logging:\n  level: INFO\n"
        "pipeline:\n  steps:\n    - name: a\n      params: {x: 1}\n"
        "report:\n  path: out/default.json\n",
    )
    _write(directory / "development.yaml", "logging:\n  level: DEBUG\n")
    return directory


def test_repository_config_files_load() -> None:
    assert load_config(config_dir=REPO_CONFIG) == {
        "logging": {"level": "INFO"},
        "pipeline": {"steps": []},
        "report": {"path": "data/output/run_manifest.json"},
    }
    assert load_config(environment="development", config_dir=REPO_CONFIG)["logging"] == {"level": "DEBUG"}


def test_default_only(config_dir: Path) -> None:
    config = load_config(config_dir=config_dir)
    assert config["logging"] == {"level": "INFO"}
    assert config["report"] == {"path": "out/default.json"}


def test_precedence_is_key_by_key(config_dir: Path, tmp_path: Path) -> None:
    run = _write(tmp_path / "run.yaml", "report:\n  path: out/run.json\n")

    config = load_config(run, environment="development", config_dir=config_dir)

    assert config == {
        "logging": {"level": "DEBUG"},  # environment over default
        "pipeline": {"steps": [{"name": "a", "params": {"x": 1}}]},  # untouched default
        "report": {"path": "out/run.json"},  # run file over default
    }


def test_run_file_overrides_environment(config_dir: Path, tmp_path: Path) -> None:
    run = _write(tmp_path / "run.yaml", "logging:\n  level: WARNING\n")
    assert load_config(run, environment="development", config_dir=config_dir)["logging"]["level"] == "WARNING"


def test_lists_are_replaced_not_concatenated(config_dir: Path, tmp_path: Path) -> None:
    run = _write(tmp_path / "run.yaml", "pipeline:\n  steps:\n    - name: b\n")
    assert load_config(run, config_dir=config_dir)["pipeline"]["steps"] == [{"name": "b"}]


def test_empty_run_file_changes_nothing(config_dir: Path, tmp_path: Path) -> None:
    run = _write(tmp_path / "run.yaml", "")
    assert load_config(run, config_dir=config_dir) == load_config(config_dir=config_dir)


@pytest.mark.parametrize(
    "text",
    [
        "secret_section: {a: 1}\n",
        "logging:\n  secret_key: 1\n",
        "pipeline:\n  steps:\n    - name: a\n      secret_key: 1\n",
    ],
)
def test_unknown_key_raises_without_echoing_it(config_dir: Path, tmp_path: Path, text: str) -> None:
    run = _write(tmp_path / "run.yaml", text)
    with pytest.raises(ValueError) as info:
        load_config(run, config_dir=config_dir)
    assert "secret" not in str(info.value)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("logging: INFO\n", "section must be a mapping"),
        ("logging:\n  level: LOUD\n", "Invalid logging.level"),
        ("logging:\n  level: [x]\n", "Invalid logging.level"),
        ("logging:\n  level: {a: 1}\n", "Invalid logging.level"),
        ("pipeline:\n  steps: a\n", "must be a list"),
        ("pipeline:\n  steps:\n    - params: {}\n", "Invalid pipeline step"),
        ("pipeline:\n  steps:\n    - name: a\n      params: [1]\n", "Invalid pipeline step"),
        ("report:\n  path: 3\n", "report.path must be a string"),
        ("- just\n- a list\n", "must contain a mapping"),
    ],
)
def test_invalid_values_raise_value_error(config_dir: Path, tmp_path: Path, text: str, message: str) -> None:
    run = _write(tmp_path / "run.yaml", text)
    with pytest.raises(ValueError, match=message):
        load_config(run, config_dir=config_dir)


def test_invalid_yaml_raises_fixed_message_without_content(config_dir: Path, tmp_path: Path) -> None:
    run = _write(tmp_path / "run.yaml", "logging: [unclosed PATIENT_SECRET\n")
    with pytest.raises(ValueError, match="Invalid YAML") as info:
        load_config(run, config_dir=config_dir)
    assert "PATIENT_SECRET" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_non_utf8_file_raises_fixed_message(config_dir: Path, tmp_path: Path) -> None:
    run = tmp_path / "run.yaml"
    run.write_bytes(b"logging:\n  level: \xff\xfe\n")
    with pytest.raises(ValueError, match="Invalid YAML") as info:
        load_config(run, config_dir=config_dir)
    assert info.value.__suppress_context__ and info.value.__cause__ is None


def test_unreadable_run_config_raises_fixed_message_without_path(config_dir: Path, tmp_path: Path) -> None:
    run = tmp_path / "secret_dir"
    run.mkdir()
    with pytest.raises(OSError, match="could not be read") as info:
        load_config(run, config_dir=config_dir)
    assert "secret_dir" not in str(info.value)
    assert info.value.__suppress_context__


def test_python_object_tags_are_rejected(config_dir: Path, tmp_path: Path) -> None:
    run = _write(tmp_path / "run.yaml", "logging: !!python/object/apply:os.system ['echo hi']\n")
    with pytest.raises(ValueError, match="Invalid YAML"):
        load_config(run, config_dir=config_dir)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"run_config": Path("missing-run.yaml")}, "Run configuration file not found"),
        ({"environment": "staging"}, "Environment configuration file not found"),
    ],
)
def test_missing_files_raise_fixed_message(config_dir: Path, kwargs: dict, message: str) -> None:
    with pytest.raises(FileNotFoundError, match=message) as info:
        load_config(config_dir=config_dir, **kwargs)
    assert "missing-run" not in str(info.value) and "staging" not in str(info.value)


def test_missing_default_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Default configuration file not found"):
        load_config(config_dir=tmp_path)


def test_loader_never_uses_unsafe_yaml_load() -> None:
    source = Path(loader.__file__).read_text(encoding="utf-8")
    assert "yaml.load(" not in source and "safe_load" in source
