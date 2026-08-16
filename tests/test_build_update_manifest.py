from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.update_manifest import verify_release_manifest
from scripts.build_update_manifest import build_manifest


def test_build_manifest_signs_artifact_metadata(tmp_path) -> None:
    artifact = tmp_path / "korea-assembly-cc-v99.0.0.exe"
    artifact.write_bytes(b"signed artifact fixture")
    private_key = Ed25519PrivateKey.generate()

    document = build_manifest(
        version="99.0.0",
        artifact=artifact,
        artifact_url="https://github.com/twbeatles/korea-assembly-cc/releases/download/v99.0.0/app.exe",
        private_key=private_key,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )

    manifest = verify_release_manifest(
        document,
        public_key=base64.b64encode(public_key).decode("ascii"),
        current_version="98.0.0",
    )

    assert manifest.version == "99.0.0"
    assert manifest.artifact_size == artifact.stat().st_size
