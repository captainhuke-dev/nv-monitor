import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from process_manager.server import create_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server(
            "127.0.0.1",
            0,
            token="test-token",
            audit_log_path=Path(self.temp_dir.name) / "audit.jsonl",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp_dir.cleanup()

    def _request(self, path, *, method="GET", payload=None, token=None):
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read()), response.headers
        except HTTPError as error:
            return error.code, json.loads(error.read()), error.headers

    def test_healthz_is_available_without_authentication(self):
        status, payload, _ = self._request("/healthz")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})

    def test_process_list_requires_bearer_token(self):
        status, payload, _ = self._request("/api/processes")

        self.assertEqual(status, 401)
        self.assertEqual(payload["error_code"], "unauthorized")

    def test_authenticated_process_list_labels_pid_one_as_system(self):
        status, payload, headers = self._request(
            "/api/processes",
            token="test-token",
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        pid_one = next(process for process in payload["processes"] if process["pid"] == 1)
        self.assertEqual(pid_one["classification"], "SYSTEM")
        self.assertIn("pid1", pid_one["system_reasons"])
        self.assertIn("system_reason_labels", pid_one)

    def test_stop_requires_creation_time_fingerprint(self):
        status, payload, _ = self._request(
            "/api/processes/999999/stop",
            method="POST",
            payload={},
            token="test-token",
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error_code"], "missing_fingerprint")

    def test_root_page_contains_system_and_user_column_labels(self):
        request = Request(f"{self.base_url}/")
        with urlopen(request, timeout=5) as response:
            page = response.read().decode()

        self.assertEqual(response.status, 200)
        self.assertIn("SYSTEM", page)
        self.assertIn("USER", page)
        self.assertIn("REASON", page)
        self.assertIn('id="group-mode"', page)
        self.assertIn('data-sort="cpu"', page)
        self.assertIn('data-sort="gpu"', page)
        self.assertIn("function toggleSort", page)
        self.assertIn("function toggleGroup", page)
        self.assertIn('id="category-tags"', page)
        self.assertIn("category-tag", page)
        self.assertIn("aria-pressed", page)

    def test_wildcard_bind_requires_explicit_override(self):
        with self.assertRaises(ValueError):
            create_server(
                "0.0.0.0",
                0,
                token="test-token",
                audit_log_path=Path(self.temp_dir.name) / "audit.jsonl",
            )

    def test_empty_token_is_rejected_before_binding(self):
        with self.assertRaises(ValueError):
            create_server(
                "127.0.0.1",
                0,
                token="",
                audit_log_path=Path(self.temp_dir.name) / "audit.jsonl",
            )


if __name__ == "__main__":
    unittest.main()
