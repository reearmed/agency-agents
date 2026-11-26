"""Strict parsing tests for the untrusted approval-grant routing hint."""
import base64
import json
import unittest

from durable_execution import DurableExecutionError, DurableMockExecutionGateway


class GrantTokenRoutingHintTests(unittest.TestCase):
    def _token(self, grant):
        encoded = base64.urlsafe_b64encode(
            json.dumps(grant, separators=(",", ":")).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        return encoded + "." + ("a" * 64)

    def test_extracts_only_a_well_formed_routing_identifier(self):
        token = self._token({"version": 1, "grant_id": "A" * 32})
        self.assertEqual(
            DurableMockExecutionGateway._grant_id_from_token(token),
            "A" * 32,
        )

    def test_rejects_non_string_and_oversized_tokens(self):
        for token in (None, b"not-a-token", "x" * 16450):
            with self.subTest(token_type=type(token).__name__):
                with self.assertRaises(DurableExecutionError):
                    DurableMockExecutionGateway._grant_id_from_token(token)

    def test_rejects_bad_token_structure_and_signature_encoding(self):
        for token in ("", "one-part", "a.b.c", "a." + "z" * 64, "a." + "a" * 63):
            with self.subTest(token=token[:20]):
                with self.assertRaises(DurableExecutionError):
                    DurableMockExecutionGateway._grant_id_from_token(token)

    def test_rejects_invalid_base64_and_json(self):
        for token in ("%%%." + "a" * 64, "bm90LWpzb24." + "a" * 64):
            with self.subTest(token=token[:20]):
                with self.assertRaises(DurableExecutionError):
                    DurableMockExecutionGateway._grant_id_from_token(token)

    def test_rejects_wrong_schema_or_malformed_grant_identifier(self):
        invalid = (
            {"version": 2, "grant_id": "A" * 32},
            {"version": 1},
            {"version": 1, "grant_id": ""},
            {"version": 1, "grant_id": "short"},
            {"version": 1, "grant_id": "A" * 16 + "."},
            [],
        )
        for grant in invalid:
            with self.subTest(grant=grant):
                with self.assertRaises(DurableExecutionError):
                    DurableMockExecutionGateway._grant_id_from_token(self._token(grant))


if __name__ == "__main__":
    unittest.main()
