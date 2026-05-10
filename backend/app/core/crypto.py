"""AES-256-GCM encryption + sha256 hashing for PII.

Per ADR-013. Two layers:

- `hash_for_lookup(value)` — deterministic sha256 for indexed lookup
  columns (`email_hash`, `phone_hash`). Same input -> same hash across
  environments (no per-env salt) so the same email maps to the same
  hash everywhere.

- `encrypt(plaintext)` / `decrypt(ciphertext)` — AES-256-GCM using the
  ENCRYPTION_KEY env var. Output: nonce(12) + ciphertext + tag.
  Random nonce per call, so the same plaintext produces different
  ciphertext on each call (confidentiality + tamper-detection).

Key handling:
- Settings.encryption_key is a base64-encoded 32-byte key (resolved by
  the config.py validator: dev default in dev; required in non-dev).
- The dev default is a 32-byte zero key — cryptographically WEAK by
  design, marked DEV ONLY. Non-dev validators reject it.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_NONCE_SIZE = 12  # AES-GCM standard nonce length


def _load_key() -> bytes:
    """Load + decode the AES key from Settings. Validates length is 32 bytes."""
    settings = get_settings()
    raw = settings.encryption_key
    assert raw is not None  # validator guarantees this
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise ValueError(
            f"ENCRYPTION_KEY must be a base64-encoded 32-byte key; "
            f"got {len(key)} bytes after decode."
        )
    return key


def hash_for_lookup(value: str) -> bytes:
    """Deterministic sha256 for indexed PII columns.

    Used for `email_hash`, `phone_hash`, etc. — see ADR-013. Stable across
    environments (no per-env salt) so the same email maps to the same hash
    for cross-env data migration purposes.
    """
    normalized = value.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).digest()


def encrypt(plaintext: str) -> bytes:
    """AES-256-GCM encrypt a string. Output: nonce(12) + ciphertext + 16-byte tag."""
    key = _load_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_SIZE)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return nonce + ct_with_tag


def decrypt(ciphertext: bytes) -> str:
    """AES-256-GCM decrypt. Raises `cryptography.exceptions.InvalidTag` on tamper."""
    if len(ciphertext) < _NONCE_SIZE:
        raise ValueError(
            f"ciphertext too short to contain a nonce; got {len(ciphertext)} bytes, "
            f"need at least {_NONCE_SIZE}."
        )
    key = _load_key()
    aesgcm = AESGCM(key)
    nonce = ciphertext[:_NONCE_SIZE]
    ct_with_tag = ciphertext[_NONCE_SIZE:]
    plaintext_bytes = aesgcm.decrypt(nonce, ct_with_tag, associated_data=None)
    return plaintext_bytes.decode("utf-8")
