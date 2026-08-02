import os
import unittest

from process_manager.collector import collect_processes, read_cgroup


class CollectorTests(unittest.TestCase):
    def test_collect_processes_includes_current_process_and_system_metadata(self):
        records = collect_processes(gpu_lookup={os.getpid(): 1234})
        current = next(record for record in records if record.pid == os.getpid())

        self.assertEqual(current.gpu_memory_bytes, 1234)
        self.assertIn(current.classification.is_system, (True, False))
        self.assertIsInstance(current.system_reasons, tuple)
        self.assertEqual(records, sorted(records, key=lambda record: record.pid))

    def test_collect_processes_skips_explicit_pid(self):
        records = collect_processes(skip_pids={os.getpid()})

        self.assertFalse(any(record.pid == os.getpid() for record in records))

    def test_read_cgroup_returns_empty_for_missing_path(self):
        self.assertEqual(read_cgroup("/definitely/not/a/real/cgroup-file"), "")


if __name__ == "__main__":
    unittest.main()
