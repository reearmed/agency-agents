"""Transport-boundary tests: only health is implemented; all writes remain disabled."""
from __future__ import annotations

from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from http_api import load_openapi_contract, make_handler
from identity_boundary import IdentityBoundary


ROOT = Path(__file__).resolve().parents[1]


class HttpApiTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = int(datetime.now(timezone.utc).timestamp())

        def verify(token):
            if token not in {"valid-test-token", "read-only-test-token"}:
                raise ValueError("invalid synthetic token")
            scopes = "business-os:read business-os:task:submit" if token == "valid-test-token" else "business-os:read"
            return {
                "iss": "https://issuer.example.test/",
                "sub": "operator-1",
                "aud": ["business-os-api"],
                "jti": "test-token-1",
                "iat": now,
                "exp": now + 300,
                "scope": scopes,
                "roles": [],
            }

        cls.identity = IdentityBoundary(
            token_verifier=verify,
            expected_issuer="https://issuer.example.test/",
            expected_audience="business-os-api",
        )
        cls.contract = load_openapi_contract(ROOT / "api" / "openapi.yaml")

    def setUp(self):
        handler = make_handler(contract=self.contract, identity=self.identity)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, *, method="GET", headers=None, body=None):
        request = Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_is_public_and_minimal(self):
        self.assertEqual(self.request("/healthz"), (200, {"status": "ok"}))

    def test_protected_route_rejects_missing_token(self):
        status, body = self.request("/tasks")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "unauthorized")

    def test_protected_route_rejects_invalid_token(self):
        status, _ = self.request("/tasks", headers={"Authorization": "Bearer invalid"})
        self.assertEqual(status, 403)

    def test_valid_identity_does_not_enable_unimplemented_operation(self):
        status, body = self.request(
            "/tasks", method="POST",
            headers={"Authorization": "Bearer valid-test-token", "Content-Type": "application/json"},
            body=b'{"objective":"Prepare a synthetic research brief","portfolio":"shared","risk_tier":"R0","task_type":"research"}',
        )
        self.assertEqual(status, 501)
        self.assertEqual(body["error"], "not_implemented")
        self.assertEqual(body["operation"], "submitTask")

    def test_authenticated_principal_without_required_scope_is_forbidden(self):
        status, body = self.request(
            "/tasks", method="POST",
            headers={"Authorization": "Bearer read-only-test-token", "Content-Type": "application/json"},
            body=b'{"objective":"Prepare a synthetic research brief","portfolio":"shared","risk_tier":"R0","task_type":"research"}',
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden")

    def test_task_read_is_authenticated_but_not_implemented(self):
        status, body = self.request(
            "/tasks/task-123", headers={"Authorization": "Bearer valid-test-token"}
        )
        self.assertEqual(status, 501)
        self.assertEqual(body["operation"], "getTask")

    def test_oversized_body_is_rejected_before_authentication(self):
        status, body = self.request(
            "/tasks", method="POST",
            headers={"Content-Type": "application/json", "Content-Length": str(65537)},
            body=b"x" * 65537,
        )
        self.assertEqual(status, 413)
        self.assertEqual(body["error"], "request_too_large")

    def test_unknown_route_is_not_dispatched(self):
        status, body = self.request("/admin")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "not_found")

    def test_query_parameters_are_rejected(self):
        status, body = self.request("/healthz?verbose=true")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "query_and_fragment_not_supported")


if __name__ == "__main__":
    unittest.main()
