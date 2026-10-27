"""``session_key``: a new key per GUI session unless ``MRI_ANON_KEY`` is already usable."""

import logging
import os
import re

from mri_dataset_tool.application.services.session_key import ensure_session_key, key_is_set


def test_an_existing_key_is_kept(monkeypatch):
    monkeypatch.setenv("MRI_ANON_KEY", "k" * 40)
    assert ensure_session_key() is True
    assert os.environ["MRI_ANON_KEY"] == "k" * 40


def test_a_missing_or_short_key_is_replaced_by_a_new_one_each_time(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    keys = []
    for value in (None, "short"):
        if value is None:
            monkeypatch.delenv("MRI_ANON_KEY", raising=False)
        else:
            monkeypatch.setenv("MRI_ANON_KEY", value)
        assert not key_is_set()
        assert ensure_session_key() is False and key_is_set()
        keys.append(os.environ["MRI_ANON_KEY"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", key) for key in keys) and keys[0] != keys[1]
    assert not [key for key in keys if key in caplog.text]
