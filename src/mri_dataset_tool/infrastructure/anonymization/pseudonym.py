"""Deterministic, self-verifying HMAC-SHA256 pseudonyms keyed by a secret from the environment.

A pseudonym is ``h || check`` with ``h = HMAC(key, kind, value)`` truncated and
``check = HMAC(key, kind, h)`` truncated. A value that already verifies under the key is a
pseudonym and is returned unchanged, so anonymizing twice equals anonymizing once. Without the
key nobody can build a value that verifies. There is no correspondence table.
"""

import hashlib
import hmac
import os
import re

KEY_ENV_VAR = "MRI_ANON_KEY"
MIN_KEY_LENGTH = 32

UID_ROOT = "2.25."  # UUID-derived OID root (PS3.5 B.2): "2.25." + a 128-bit integer
_UID_HASH_BYTES, _UID_CHECK_BYTES = 12, 4
_LABEL_HASH_BYTES, _LABEL_CHECK_BYTES = 5, 3  # 16 lowercase hex characters
_UID_PATTERN = re.compile(r"2\.25\.(0|[1-9][0-9]{0,38})")
_LABEL_PATTERN = re.compile(r"[0-9a-f]{16}")


def load_key() -> bytes:
    """Read the HMAC key from ``MRI_ANON_KEY``; missing, empty or short → fixed ``ValueError``."""
    key = os.environ.get(KEY_ENV_VAR, "")
    if len(key) < MIN_KEY_LENGTH:
        raise ValueError("Anonymization key is not set or too short.")
    return key.encode("utf-8")


def _mac(key: bytes, kind: str, data: bytes, size: int) -> bytes:
    # The kind separates domains: a subject and a UID with the same text get unrelated pseudonyms.
    return hmac.new(key, kind.encode("ascii") + b"\x00" + data, hashlib.sha256).digest()[:size]


def _token(key: bytes, kind: str, value: str, hash_size: int, check_size: int) -> bytes:
    digest = _mac(key, kind, value.encode("utf-8"), hash_size)
    return digest + _mac(key, kind + ".check", digest, check_size)


def _verifies(key: bytes, kind: str, token: bytes, hash_size: int) -> bool:
    digest, check = token[:hash_size], token[hash_size:]
    return hmac.compare_digest(check, _mac(key, kind + ".check", digest, len(check)))


def pseudonymize_uid(value: str, key: bytes) -> str:
    """Map a DICOM UID to ``2.25.<128-bit integer>`` (at most 44 characters, a valid UID)."""
    if _UID_PATTERN.fullmatch(value):
        number = int(value[len(UID_ROOT):])
        if number < 2**128 and _verifies(key, "uid", number.to_bytes(16, "big"), _UID_HASH_BYTES):
            return value
    token = _token(key, "uid", value, _UID_HASH_BYTES, _UID_CHECK_BYTES)
    return UID_ROOT + str(int.from_bytes(token, "big"))


def pseudonymize_label(value: str, kind: str, key: bytes) -> str:
    """Map an identifier label (``kind`` e.g. ``"subject"``) to 16 lowercase hex characters."""
    if _LABEL_PATTERN.fullmatch(value) and _verifies(key, kind, bytes.fromhex(value), _LABEL_HASH_BYTES):
        return value
    return _token(key, kind, value, _LABEL_HASH_BYTES, _LABEL_CHECK_BYTES).hex()
