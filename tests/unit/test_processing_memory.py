import logging
from types import SimpleNamespace

import numpy as np
import psutil
import pytest

from mri_dataset_tool.infrastructure.processing.memory import (
    check_allow_insufficient_memory,
    check_available_memory,
)
from mri_dataset_tool.infrastructure.processing.resample import resample

GIB = 2**30


def _available(monkeypatch, available: int) -> None:
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=available))


def test_enough_memory_passes(monkeypatch) -> None:
    _available(monkeypatch, 8 * GIB)
    check_available_memory(8 * GIB)


def test_insufficient_memory_is_rejected_with_fixed_message(monkeypatch) -> None:
    _available(monkeypatch, 3 * GIB)
    with pytest.raises(ValueError, match="^Insufficient available memory for the resampled volume.$"):
        check_available_memory(3 * GIB + 1)


def test_consent_lets_it_pass_and_logs_no_figures(monkeypatch, caplog) -> None:
    _available(monkeypatch, 3 * GIB)
    with caplog.at_level(logging.WARNING):
        check_available_memory(5 * GIB, allow_insufficient=True)
    messages = [record.getMessage() for record in caplog.records]
    assert messages and not any(ch.isdigit() for message in messages for ch in message)


def test_psutil_failure_does_not_block(monkeypatch, caplog) -> None:
    def broken():
        raise OSError("no /proc/meminfo")

    monkeypatch.setattr(psutil, "virtual_memory", broken)
    with caplog.at_level(logging.WARNING):
        check_available_memory(10**15)
    assert "OSError" in caplog.text and "meminfo" not in caplog.text


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false"])
def test_consent_must_be_a_strict_bool(value) -> None:
    with pytest.raises(ValueError, match="^Allow insufficient memory must be a boolean.$"):
        check_allow_insufficient_memory(value)
    with pytest.raises(ValueError, match="^Allow insufficient memory must be a boolean.$"):
        resample(np.zeros((2, 2, 2)), np.eye(4), [1, 1, 1], allow_insufficient_memory=value)


def test_resample_checks_memory_before_allocating(monkeypatch) -> None:
    _available(monkeypatch, 1024)  # less than the 4x4x4x2 float32 output plus working copies
    volume = np.ones((4, 4, 4, 2))
    with pytest.raises(ValueError, match="^Insufficient available memory for the resampled volume.$"):
        resample(volume, np.eye(4), [1, 1, 1])
    out, _ = resample(volume, np.eye(4), [1, 1, 1], allow_insufficient_memory=True)
    assert out.shape == (4, 4, 4, 2)
