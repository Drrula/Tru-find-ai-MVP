"""B.2.1 tests for app.core.crypto.

Verifies hash determinism + normalization + AES-GCM round-trip + tamper
detection. Uses the dev encryption key (auto-applied by Settings
validator when APP_ENV=development).
"""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag


# --- hash_for_lookup


def test_hash_for_lookup_deterministic() -> None:
    from app.core.crypto import hash_for_lookup

    a = hash_for_lookup("alice@example.com")
    b = hash_for_lookup("alice@example.com")
    assert a == b
    assert len(a) == 32  # sha256 = 32 bytes


def test_hash_for_lookup_normalizes_case() -> None:
    from app.core.crypto import hash_for_lookup

    assert hash_for_lookup("Alice@Example.com") == hash_for_lookup("alice@example.com")


def test_hash_for_lookup_normalizes_whitespace() -> None:
    from app.core.crypto import hash_for_lookup

    assert hash_for_lookup("  alice@example.com  ") == hash_for_lookup(
        "alice@example.com"
    )


def test_hash_for_lookup_distinguishes_distinct_inputs() -> None:
    from app.core.crypto import hash_for_lookup

    assert hash_for_lookup("alice@example.com") != hash_for_lookup("bob@example.com")


# --- encrypt / decrypt round-trip


def test_encrypt_decrypt_roundtrip() -> None:
    from app.core.crypto import decrypt, encrypt

    plaintext = "alice@example.com"
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext.encode("utf-8")  # actually encrypted
    assert decrypt(ciphertext) == plaintext


def test_encrypt_handles_unicode() -> None:
    from app.core.crypto import decrypt, encrypt

    plaintext = "alice@example.com — 日本語 — 🎉"
    assert decrypt(encrypt(plaintext)) == plaintext


def test_encrypt_produces_different_ciphertext_per_call() -> None:
    """AES-GCM nonces are random; same plaintext yields different ciphertext."""
    from app.core.crypto import encrypt

    a = encrypt("hello")
    b = encrypt("hello")
    assert a != b  # different random nonces


def test_encrypt_output_includes_nonce_prefix() -> None:
    """Output starts with a 12-byte nonce."""
    from app.core.crypto import encrypt

    out = encrypt("x")
    # nonce(12) + at-least(plaintext) + tag(16). Minimum length 12+1+16 = 29.
    assert len(out) >= 12 + 1 + 16


# --- tamper detection


def test_decrypt_tamper_detection() -> None:
    """Mutating any byte of the ciphertext (incl. tag region) raises InvalidTag."""
    from app.core.crypto import decrypt, encrypt

    ciphertext = bytearray(encrypt("alice@example.com"))
    ciphertext[-1] ^= 0xFF  # flip a bit in the tag
    with pytest.raises(InvalidTag):
        decrypt(bytes(ciphertext))


def test_decrypt_short_ciphertext_raises() -> None:
    from app.core.crypto import decrypt

    with pytest.raises(ValueError, match="too short"):
        decrypt(b"abc")
