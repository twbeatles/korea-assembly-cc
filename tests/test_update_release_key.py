from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.verify_update_release_key import verify_release_keypair


def test_release_keypair_verification_accepts_matching_keys() -> None:
    private_key = Ed25519PrivateKey.generate()
    private_b64 = base64.b64encode(
        private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    ).decode("ascii")
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode("ascii")

    verify_release_keypair(private_b64, public_b64)


def test_release_keypair_verification_rejects_mismatch() -> None:
    private_key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()
    private_b64 = base64.b64encode(
        private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    ).decode("ascii")
    public_b64 = base64.b64encode(
        other_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode("ascii")

    with pytest.raises(ValueError, match="does not match"):
        verify_release_keypair(private_b64, public_b64)
