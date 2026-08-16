from __future__ import annotations

import argparse
import base64
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import Config
from core.update_manifest import canonical_manifest_payload, verify_release_manifest


def verify_release_keypair(private_key_b64: str, public_key_b64: str) -> None:
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(private_key_b64, validate=True)
        )
        configured_public_key = base64.b64decode(public_key_b64, validate=True)
    except Exception as exc:
        raise ValueError("Update signing keys must be valid base64 Ed25519 keys") from exc
    derived_public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    if configured_public_key != derived_public_key:
        raise ValueError("Update signing private key does not match the embedded public key")

    payload = {
        "version": "999.0.0",
        "artifact_url": "https://example.invalid/korea-assembly-cc.exe",
        "sha256": "0" * 64,
        "size": 1,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5))
        .replace(microsecond=0)
        .isoformat(),
    }
    document = {
        "payload": payload,
        "signature": base64.b64encode(
            private_key.sign(canonical_manifest_payload(payload))
        ).decode("ascii"),
    }
    verify_release_manifest(
        document,
        public_key=public_key_b64,
        current_version="0.0.0",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify updater signing keys")
    parser.add_argument("--private-key-env", default="KACC_UPDATE_PRIVATE_KEY_B64")
    parser.add_argument("--public-key-env", default="KACC_UPDATE_PUBLIC_KEY_B64")
    args = parser.parse_args(argv)
    private_key_b64 = os.environ.get(args.private_key_env, "").strip()
    if not private_key_b64:
        raise ValueError(f"Required environment variable is not set: {args.private_key_env}")
    configured_public_key = os.environ.get(args.public_key_env, "").strip()
    if configured_public_key != Config.UPDATE_PUBLIC_KEY_B64_DEFAULT:
        raise ValueError("Release public-key secret does not match the embedded public key")
    verify_release_keypair(private_key_b64, Config.UPDATE_PUBLIC_KEY_B64_DEFAULT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
