from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.update_manifest import (
    NoUpdateAvailableError,
    canonical_manifest_payload,
    is_newer_version,
    verify_release_manifest,
    download_release_manifest,
)
from core.config import Config


def _signed_document(private_key: Ed25519PrivateKey, **overrides):
    payload = {
        "version": "99.1.0",
        "artifact_url": "https://updates.example.com/app.exe",
        "sha256": "a" * 64,
        "size": 1234,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    payload.update(overrides)
    signature = private_key.sign(canonical_manifest_payload(payload))
    return {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def test_valid_signed_manifest_is_verified() -> None:
    private_key = Ed25519PrivateKey.generate()

    manifest = verify_release_manifest(
        _signed_document(private_key),
        public_key=_public_key(private_key),
        current_version="16.0.0",
    )

    assert manifest.version == "99.1.0"
    assert manifest.artifact_size == 1234


def test_tampered_and_wrong_key_manifests_are_rejected() -> None:
    signer = Ed25519PrivateKey.generate()
    document = _signed_document(signer)
    document["payload"]["size"] = 9999

    with pytest.raises(ValueError, match="signature"):
        verify_release_manifest(
            document,
            public_key=_public_key(signer),
            current_version="16.0.0",
        )
    with pytest.raises(ValueError, match="signature"):
        verify_release_manifest(
            _signed_document(signer),
            public_key=_public_key(Ed25519PrivateKey.generate()),
            current_version="16.0.0",
        )


def test_expired_downgrade_and_invalid_hash_manifests_are_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    for document, message in (
        (_signed_document(private_key, expires_at=expired), "expired"),
        (_signed_document(private_key, version="1.0.0"), "newer"),
        (_signed_document(private_key, sha256="not-a-hash"), "sha256"),
    ):
        with pytest.raises(ValueError, match=message):
            verify_release_manifest(
                document,
                public_key=_public_key(private_key),
                current_version="16.0.0",
            )


def test_unsigned_and_oversized_manifest_bytes_are_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="signature"):
        verify_release_manifest(
            {"payload": _signed_document(private_key)["payload"]},
            public_key=_public_key(private_key),
            current_version="16.0.0",
        )
    with pytest.raises(ValueError, match="size"):
        verify_release_manifest(
            json.dumps(_signed_document(private_key)).encode("utf-8"),
            public_key=_public_key(private_key),
            current_version="16.0.0",
            max_bytes=16,
        )


def test_version_comparison_is_numeric_and_requires_strict_upgrade() -> None:
    assert is_newer_version("16.10.0", "16.9.9") is True
    assert is_newer_version("16.9.9", "16.10.0") is False
    assert is_newer_version("16.10.0", "16.10.0") is False


def test_current_version_has_distinct_no_update_result() -> None:
    private_key = Ed25519PrivateKey.generate()

    with pytest.raises(NoUpdateAvailableError):
        verify_release_manifest(
            _signed_document(private_key, version="16.0.0"),
            public_key=_public_key(private_key),
            current_version="16.0.0",
        )


def test_manifest_download_rejects_redirect_to_http(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "http://updates.example.com/manifest.json"

        def read(self, _size):
            return b"{}"

    monkeypatch.setattr("core.update_manifest.urlopen", lambda *a, **k: Response())

    with pytest.raises(ValueError, match="HTTPS"):
        download_release_manifest("https://updates.example.com/manifest.json")


def test_release_update_channel_has_embedded_public_key() -> None:
    assert Config.UPDATE_MANIFEST_URL.startswith("https://")
    assert Config.UPDATE_RELEASES_URL.startswith("https://github.com/")
    assert len(base64.b64decode(Config.UPDATE_PUBLIC_KEY_B64, validate=True)) == 32
