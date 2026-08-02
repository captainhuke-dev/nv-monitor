"""Authenticated HTTP API and browser UI for the process manager."""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .actions import StopRequest, stop_process
from .collector import collect_processes


MAX_REQUEST_BYTES = 64 * 1024
WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]"}
STATIC_INDEX = Path(__file__).with_name("static") / "index.html"


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _error_status(error_code: str | None) -> int:
    if error_code == "unauthorized":
        return HTTPStatus.UNAUTHORIZED
    if error_code in {"protected_process", "manager_process", "system_confirmation_required"}:
        return HTTPStatus.FORBIDDEN
    if error_code in {"process_gone", "pid_reused"}:
        return HTTPStatus.CONFLICT
    return HTTPStatus.BAD_REQUEST


class ProcessManagerHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        token: str,
        audit_log_path: str | Path,
    ) -> None:
        if not token:
            raise ValueError("a non-empty bearer token is required")
        host, _ = server_address
        if host in WILDCARD_HOSTS and os.environ.get("PROCESS_MANAGER_ALLOW_WILDCARD") != "1":
            raise ValueError("wildcard bind requires PROCESS_MANAGER_ALLOW_WILDCARD=1")
        self.token = token
        self.audit_log_path = Path(audit_log_path)
        self.manager_pid = os.getpid()
        super().__init__(server_address, ProcessManagerHandler)


class ProcessManagerHandler(BaseHTTPRequestHandler):
    server: ProcessManagerHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # The audit log records actions; avoid duplicating every polling request.
        return

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.token}"
        return hmac.compare_digest(supplied, expected)

    def _send_json(self, status: int, payload: object) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, error_code: str, message: str) -> None:
        self._send_json(
            status,
            {"error_code": error_code, "message": message},
        )

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._send_error(
            HTTPStatus.UNAUTHORIZED,
            "unauthorized",
            "Bearer authentication is required",
        )
        return False

    def _read_json(self) -> dict[str, object] | None:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_body", "invalid Content-Length")
            return None
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large", "request body is too large")
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_body", "request body must be JSON")
            return None
        if not isinstance(payload, dict):
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_body", "request body must be an object")
            return None
        return payload

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        if path == "/":
            try:
                body = STATIC_INDEX.read_bytes()
            except OSError:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "ui_unavailable", "UI file is unavailable")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/processes":
            if not self._require_auth():
                return
            records = collect_processes()
            self._send_json(
                HTTPStatus.OK,
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "processes": [record.to_dict() for record in records],
                },
            )
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not_found", "route not found")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._require_auth():
            return
        path_parts = [part for part in urlsplit(self.path).path.split("/") if part]
        if len(path_parts) != 4 or path_parts[:2] != ["api", "processes"] or path_parts[3] != "stop":
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        try:
            pid = int(path_parts[2])
        except ValueError:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_pid", "PID must be an integer")
            return
        payload = self._read_json()
        if payload is None:
            return
        expected = payload.get("expected_create_time")
        if expected is not None and not isinstance(expected, (int, float)):
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_fingerprint", "creation time must be numeric")
            return
        request = StopRequest(
            pid=pid,
            expected_create_time=float(expected) if expected is not None else None,
            confirm_system=payload.get("confirm_system") is True,
            force=payload.get("force") is True,
        )
        result = stop_process(
            request,
            self.server.audit_log_path,
            manager_pid=self.server.manager_pid,
        )
        self._send_json(HTTPStatus.OK if result.ok else _error_status(result.error_code), result.to_dict())


def create_server(
    host: str,
    port: int,
    *,
    token: str,
    audit_log_path: str | Path,
) -> ProcessManagerHTTPServer:
    return ProcessManagerHTTPServer((host, port), token, audit_log_path)
