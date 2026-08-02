import unittest

from process_manager.models import ProcessRecord, SystemReason, classify_process


class ClassificationTests(unittest.TestCase):
    def test_root_process_is_system_and_exposes_reason_label(self):
        result = classify_process(
            pid=321,
            uid=0,
            name="model-server",
            cmdline=("model-server",),
            cgroup="",
        )

        self.assertTrue(result.is_system)
        self.assertFalse(result.protected)
        self.assertEqual(result.reasons, (SystemReason.ROOT,))
        self.assertEqual(result.reason_labels, ("root-owned process",))

    def test_pid_one_is_protected_system_process(self):
        result = classify_process(
            pid=1,
            uid=0,
            name="systemd",
            cmdline=("/sbin/init",),
            cgroup="0::/init.scope",
        )

        self.assertTrue(result.is_system)
        self.assertTrue(result.protected)
        self.assertEqual(
            result.reasons,
            (
                SystemReason.PID1,
                SystemReason.ROOT,
                SystemReason.SYSTEMD_SERVICE,
            ),
        )

    def test_kernel_thread_is_system_and_protected(self):
        result = classify_process(
            pid=42,
            uid=0,
            name="[kworker/0:0]",
            cmdline=(),
            cgroup="",
        )

        self.assertTrue(result.is_system)
        self.assertTrue(result.protected)
        self.assertEqual(
            result.reasons,
            (SystemReason.KERNEL_THREAD, SystemReason.ROOT),
        )

    def test_systemd_cgroup_marks_non_root_service_as_system(self):
        result = classify_process(
            pid=77,
            uid=1000,
            name="worker",
            cmdline=("worker",),
            cgroup="0::/system.slice/worker.service",
        )

        self.assertTrue(result.is_system)
        self.assertFalse(result.protected)
        self.assertEqual(result.reasons, (SystemReason.SYSTEMD_SERVICE,))

    def test_normal_user_process_is_not_system(self):
        result = classify_process(
            pid=88,
            uid=1000,
            name="python",
            cmdline=("python", "job.py"),
            cgroup="0::/user.slice/user-1000.slice/session-1.scope",
        )

        self.assertFalse(result.is_system)
        self.assertFalse(result.protected)
        self.assertEqual(result.reasons, ())

    def test_process_record_serializes_system_and_reason_fields(self):
        record = ProcessRecord(
            pid=99,
            ppid=1,
            uid=0,
            user="root",
            name="worker",
            cmdline="worker --serve",
            status="running",
            cpu_percent=12.5,
            rss_bytes=4096,
            gpu_memory_bytes=1024,
            create_time=123.5,
            pgid=99,
            classification=classify_process(
                pid=99,
                uid=0,
                name="worker",
                cmdline=("worker", "--serve"),
                cgroup="",
            ),
        )

        payload = record.to_dict()

        self.assertEqual(payload["classification"], "SYSTEM")
        self.assertEqual(payload["system_reasons"], ["root"])
        self.assertEqual(payload["system_reason_labels"], ["root-owned process"])
        self.assertTrue(payload["is_system"])
        self.assertFalse(payload["protected"])
        self.assertEqual(payload["gpu_memory_bytes"], 1024)


if __name__ == "__main__":
    unittest.main()
