"""Anonymization key of a GUI session (decision of the human, stage 5B).

Without ``MRI_ANON_KEY`` in the environment, a new key is generated each time the program starts
and set only in this process (``os.environ``): it is never returned, saved, shown or logged. As a
consequence the pseudonyms change between sessions (``docs/user_manual/gui.md``).
"""

import hashlib
import os
import secrets

from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR, MIN_KEY_LENGTH


def key_is_set() -> bool:
    """True if ``MRI_ANON_KEY`` is usable (at least 32 characters)."""
    return len(os.environ.get(KEY_ENV_VAR, "")) >= MIN_KEY_LENGTH


def ensure_session_key() -> bool:
    """Keep a usable ``MRI_ANON_KEY`` (returns ``True``: it was already defined) or set a new one
    for this process (returns ``False``)."""
    if key_is_set():
        return True
    os.environ[KEY_ENV_VAR] = hashlib.sha256(secrets.token_bytes(32)).hexdigest()  # 64 hex characters
    return False
