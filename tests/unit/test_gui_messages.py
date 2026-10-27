"""GUI catalog: both languages have the same codes and the same placeholders."""

import re
import string
from pathlib import Path

import pytest

from mri_dataset_tool.presentation.gui import messages


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_languages_have_the_same_codes_and_placeholders():
    es, en = messages.CATALOG["es"], messages.CATALOG["en"]
    assert set(es) == set(en)
    assert {code: _fields(t) for code, t in es.items()} == {code: _fields(t) for code, t in en.items()}
    assert set(messages.CATALOG) == set(messages.LANGUAGES) and messages.DEFAULT_LANGUAGE == "es"


def test_text_fills_values_in_each_language():
    assert messages.text("STAGE_FAILED", stage="export", error_type="OSError") == "Falló la etapa «export» (OSError)."
    assert messages.text("STAGE_FAILED", "en", stage="export", error_type="OSError") == 'Stage "export" failed (OSError).'


def test_unknown_code_or_language_raises():
    with pytest.raises(KeyError):
        messages.text("NO_SUCH_CODE")
    with pytest.raises(KeyError):
        messages.text("BACK", "fr")


SERVICES = Path(__file__).resolve().parents[2] / "src" / "mri_dataset_tool" / "application" / "services"


def test_every_fixed_build_input_message_has_a_code_in_both_languages():
    found = set()
    for path in SERVICES.glob("*.py"):
        found |= set(re.findall(r'InvalidBuildInput\("([^"]+)"\)', path.read_text(encoding="utf-8")))
    assert found and found <= set(messages.FIXED_MESSAGES)
    for code in [*messages.FIXED_MESSAGES.values(), "INVALID_CONFIG", "MAPPING_PATHS_NOT_FOUND"]:
        assert code in messages.CATALOG["es"] and code in messages.CATALOG["en"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Invalid --classes.", ("INVALID_CLASSES", {})),
        ("Invalid config: YAMLError", ("INVALID_CONFIG", {"error_type": "YAMLError"})),
        ("Mapping paths not found in the input: 7.", ("MAPPING_PATHS_NOT_FOUND", {"count": 7})),
        ("Something /secret/PlantedPath", ("INVALID_INPUT", {"error_type": "ValueError"})),
    ],
)
def test_invalid_input_codes_never_carry_the_message(message, expected):
    assert messages.invalid_input(ValueError(message)) == expected


LABEL_SOURCES = [
    SERVICES / "labels.py", SERVICES / "labels_table.py",
    SERVICES.parents[1] / "infrastructure" / "dataset" / "labels.py",
]


def test_every_fixed_label_message_has_a_code_or_is_listed_as_not_reachable():
    found = set()
    for path in LABEL_SOURCES:
        found |= set(re.findall(r'raise \w+\("([^"]+)"\)', path.read_text(encoding="utf-8")))
    assert found and found <= set(messages.LABEL_MESSAGES) | set(messages.LABEL_MESSAGES_NOT_REACHABLE)
    for code in set(messages.LABEL_MESSAGES.values()) | {"LABELS_ERROR"}:
        assert code in messages.CATALOG["es"] and code in messages.CATALOG["en"]


EXPORT_SOURCES = [
    SERVICES / "dataset.py", SERVICES / "dataset_report.py", SERVICES / "dataset_outputs.py",
    *(SERVICES.parents[1] / "infrastructure" / "dataset" / name for name in ("index.py", "splits.py", "exporters.py")),
]


def test_every_fixed_export_message_has_a_code_or_is_listed_as_not_reachable():
    found = set()
    for path in EXPORT_SOURCES:
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r'raise \w+\("([^"]+)"\)', text)) | set(re.findall(r'= ValueError\("([^"]+)"\)', text))
    known = set(messages.EXPORT_MESSAGES) | set(messages.LABEL_MESSAGES) | set(messages.EXPORT_MESSAGES_NOT_REACHABLE)
    assert found and found <= known
    for code in set(messages.EXPORT_MESSAGES.values()) | {"EXPORT_ERROR"}:
        assert code in messages.CATALOG["es"] and code in messages.CATALOG["en"]
