"""Fail-closed HTTP transport shell for the Business OS control plane.

Only GET /healthz is implemented. All other documented operations are
authenticated and authorized against the server-owned OpenAPI contract, then
return 501 until a reviewed handler is explicitly registered. Bind to loopback
behind an independently configured TLS reverse proxy; this module provides no
TLS, persistence wiring, tenant data access, or external adapters.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import yaml

if __package__:
    from .identity_boundary import IdentityBoundary, IdentityError
    from .route_authorization import authorize_operation
else:
    from identity_boundary import IdentityBoundary, IdentityError
    from route_authorization import authorize_operation


MAX_REQUEST_BYTES = 64 * 1024


class ContractError(RuntimeError):
    pass


def load_openapi_contract(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate the trusted, local OpenAPI document."""
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise ContractError("OpenAPI contract must contain a paths object")
    if not isinstance(document.get("security"), list):
        raise ContractError("OpenAPI default security policy is required")
    for route, path_item in document["paths"].items():
        if not isinstance(route, str) or not route.startswith("/") or not isinstance(path_item, dict):
            raise ContractError("malformed OpenAPI path entry")
        for method, operation in path_item.items():
            if method.lower() in {"get", "post", "put", "patch", "delete"} and not isinstance(operation, dict):
                raise ContractError("malformed OpenAPI operation")
    return document


def _route_pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[A-Za-z_][A-Za-z0-9_]*\})", template)
    expression = "".join(
        r"[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
        for part in parts
    )
    return re.compile("^" + expression + "$")


def _match_operation(document: dict[str, Any], method: str, path: str) -> dict[str, Any] | None:
    for template, path_item in document["paths"].items():
        if _route_pattern(template).fullmatch(path):
            operation = path_item.get(method.lower())
            if operation is None:
                return None
            return operation
    return None


def make_handler(
    *,
    contract: dict[str, Any],
    identity: IdentityBoundary,
    max_body_bytes: int = MAX_REQUEST_BYTES,
) -> type[BaseHTTPRequestHandler]:
    if not isinstance(max_body_bytes, int) or isinstance(max_body_bytes, bool) or not 1 <= max_body_bytes <= MAX_REQUEST_BYTES:
        raise ValueError("max_body_bytes must be between 1 and 65536")

    class Handler(BaseHTTPRequestHandler):
        server_version = "BusinessOS"
        sys_version = ""

        def log_message(self, _format: str, *_args: Any) -> None:
            # Do not log request paths, bearer headers, or user-supplied values.
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _body_is_bounded_json(self) -> bool:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self._send(411, {"error": "content_length_required"})
                return False
            if not raw_length.isascii() or not raw_length.isdecimal():
                self._send(400, {"error": "invalid_content_length"})
                return False
            length = int(raw_length)
            if length > max_body_bytes:
                self._send(413, {"error": "request_too_large"})
                return False
            if self.headers.get("Transfer-Encoding") is not None:
                self._send(400, {"error": "transfer_encoding_not_supported"})
                return False
            if self.headers.get_content_type() != "application/json":
                self._send(415, {"error": "application_json_required"})
                return False
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self._send(400, {"error": "incomplete_request_body"})
                    return False
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, dict):
                    self._send(400, {"error": "json_object_required"})
                    return False
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(400, {"error": "invalid_json"})
                return False
            return True

        def _dispatch(self, method: str) -> None:
            path = urlsplit(self.path)
            if path.query or path.fragment or path.path != self.path:
                self._send(400, {"error": "query_and_fragment_not_supported"})
                return
            operation = _match_operation(contract, method, path.path)
            if operation is None:
                self._send(404, {"error": "not_found"})
                return

            # Bound and parse body before identity work; no request content is
            # acted upon by this transport shell.
            if method in {"POST", "PUT", "PATCH"} and not self._body_is_bounded_json():
                return

            if operation.get("security", contract["security"]) == []:
                principal = None
            else:
                try:
                    principal = identity.authenticate(
                        self.headers.get("Authorization", "")
                    )
                except IdentityError:
                    self._send(401, {"error": "unauthorized"})
                    return
            try:
                authorize_operation(
                    principal, operation, default_security=contract["security"]
                )
            except IdentityError:
                self._send(403, {"error": "forbidden"})
                return

            operation_id = operation.get("operationId")
            if method == "GET" and path.path == "/healthz" and operation_id == "healthCheck":
                self._send(200, {"status": "ok"})
                return

            # Deliberately do not imply that OpenAPI operations are implemented.
            self._send(501, {"error": "not_implemented", "operation": operation_id})

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_PATCH(self) -> None:
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

    return Handler


def serve(
    *,
    contract_path: str | Path,
    identity: IdentityBoundary,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run the transport shell on loopback only; TLS must terminate upstream."""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("HTTP shell may bind only to loopback")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    contract = load_openapi_contract(contract_path)
    server = ThreadingHTTPServer((host, port), make_handler(contract=contract, identity=identity))
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
