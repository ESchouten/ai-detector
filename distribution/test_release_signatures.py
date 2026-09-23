"""Cross-language release signing fixtures, using a public RFC 8032 test key."""

import base64
import json
import unittest
from pathlib import Path

from cryptography.exceptions import InvalidSignature

from fixtures.keys import PRIVATE_KEY, PUBLIC_KEY
from release_signatures import sign_feed, verify_feed


class SignatureTest(unittest.TestCase):
    def test_matches_the_fixture_verified_by_the_windows_client(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures/signed-update.json").read_text()
        )
        envelope = json.dumps(fixture["envelope"]).encode()
        payload = verify_feed(envelope, PUBLIC_KEY)
        self.assertEqual(
            json.loads(sign_feed(payload, PRIVATE_KEY, PUBLIC_KEY)), fixture["envelope"]
        )

    def test_changed_payload_and_wrong_key_are_rejected(self):
        signed = json.loads(sign_feed(b'{"Assets":[]}', PRIVATE_KEY, PUBLIC_KEY))
        signed["payload"] = base64.b64encode(b'{"Assets":[{}]}').decode()
        with self.assertRaises(InvalidSignature):
            verify_feed(json.dumps(signed).encode(), PUBLIC_KEY)
        with self.assertRaises(InvalidSignature):
            verify_feed(
                sign_feed(b"feed", PRIVATE_KEY, PUBLIC_KEY),
                base64.b64encode(bytes(32)).decode(),
            )

    def test_unsigned_metadata_and_mismatched_signing_key_are_rejected(self):
        with self.assertRaises(KeyError):
            verify_feed(b'{"Assets":[]}', PUBLIC_KEY)
        with self.assertRaisesRegex(ValueError, "does not match"):
            sign_feed(b"feed", PRIVATE_KEY, base64.b64encode(bytes(32)).decode())
