"""Authenticate Windows release metadata with the same Ed25519 key used by Sparkle."""

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# Keep signatures specific to this application, platform, channel and format.
CONTEXT = b"AI Detector Windows updates v1\n"


def verify_feed(envelope: bytes, public_key: str) -> bytes:
    signed = json.loads(envelope)
    payload = base64.b64decode(signed["payload"], validate=True)
    signature = base64.b64decode(signed["signature"], validate=True)
    key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(public_key, validate=True)
    )
    key.verify(signature, CONTEXT + payload)
    return payload


def sign_feed(payload: bytes, private_key: str, public_key: str) -> bytes:
    key = Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(private_key, validate=True)
    )
    if key.public_key().public_bytes_raw() != base64.b64decode(
        public_key, validate=True
    ):
        raise ValueError("The update signing key does not match the bundled public key")
    return (
        json.dumps(
            {
                "payload": base64.b64encode(payload).decode(),
                "signature": base64.b64encode(key.sign(CONTEXT + payload)).decode(),
            }
        )
        + "\n"
    ).encode()
