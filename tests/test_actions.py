import json
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from process_manager.actions import (
    ProcessTarget,
    StopRequest,
    stop_process,
    validate_stop_request,
)
from process_manager.models import ProcessClassification, SystemReason


def _user_target(pid: int = 10, create_time: float = 20.0) -> ProcessTarget:
    return ProcessTarget(
        pid=pid,
        create_time=create_time,
        classification=ProcessClassification(
            is_system=False,
            reasons=(),
            protected=False,
        ),
    )


class StopPolicyTests(unittest.TestCase):
    def test_missing_fingerprint_is_rejected(self):
        result = validate_stop_request(
            StopRequest(pid=10, expected_create_time=None),
            _user_target(),
            manager_pid=999,
        )

        self.assertEqual(result.error_code, "missing_fingerprint")
        self.assertEqual(result.status, "rejected")

    def test_creation_time_mismatch_is_rejected(self):
        result = validate_stop_request(
            StopRequest(pid=10, expected_create_time=21.0),
            _user_target(create_time=20.0),
            manager_pid=999,
        )

        self.assertEqual(result.error_code, "pid_reused")

    def test_manager_process_is_rejected(self):
        result = validate_stop_request(
            StopRequest(pid=10, expected_create_time=20.0),
            _user_target(),
            manager_pid=10,
        )

        self.assertEqual(result.error_code, "manager_process")

    def test_protected_process_is_rejected(self):
        target = ProcessTarget(
            pid=1,
            create_time=20.0,
            classification=ProcessClassification(
                is_system=True,
                reasons=(SystemReason.PID1,),
                protected=True,
            ),
        )

        result = validate_stop_request(
            StopRequest(pid=1, expected_create_time=20.0, confirm_system=True),
            target,
            manager_pid=999,
        )

        self.assertEqual(result.error_code, "protected_process")

    def test_system_process_requires_explicit_confirmation(self):
        target = ProcessTarget(
            pid=10,
            create_time=20.0,
            classification=ProcessClassification(
                is_system=True,
                reasons=(SystemReason.ROOT,),
                protected=False,
            ),
        )

        result = validate_stop_request(
            StopRequest(pid=10, expected_create_time=20.0),
            target,
            manager_pid=999,
        )

        self.assertEqual(result.error_code, "system_confirmation_required")

    def test_real_child_receives_sigterm_and_audit_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            try:
                import psutil

                process = psutil.Process(child.pid)
                result = stop_process(
                    StopRequest(
                        pid=child.pid,
                        expected_create_time=process.create_time(),
                    ),
                    audit_path,
                )
                child.wait(timeout=3)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=3)

            self.assertTrue(result.ok)
            self.assertEqual(result.signal, signal.Signals.SIGTERM.name)
            entries = [json.loads(line) for line in audit_path.read_text().splitlines()]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["outcome"], "signal_sent")

    def test_force_kill_uses_sigkill_for_child_ignoring_sigterm(self):
        code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        child = subprocess.Popen([sys.executable, "-c", code])
        try:
            import psutil

            process = psutil.Process(child.pid)
            with tempfile.TemporaryDirectory() as tmp:
                result = stop_process(
                    StopRequest(
                        pid=child.pid,
                        expected_create_time=process.create_time(),
                        force=True,
                    ),
                    Path(tmp) / "audit.jsonl",
                )
            child.wait(timeout=3)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)

        self.assertTrue(result.ok)
        self.assertEqual(result.signal, signal.Signals.SIGKILL.name)

    def test_unwritable_audit_path_rejects_without_signaling(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            import psutil

            process = psutil.Process(child.pid)
            with tempfile.TemporaryDirectory() as tmp:
                not_a_directory = Path(tmp) / "audit-parent"
                not_a_directory.write_text("file", encoding="utf-8")
                result = stop_process(
                    StopRequest(
                        pid=child.pid,
                        expected_create_time=process.create_time(),
                    ),
                    not_a_directory / "audit.jsonl",
                )
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "audit_log_failure")
            self.assertIsNone(child.poll())
        finally:
            child.kill()
            child.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
