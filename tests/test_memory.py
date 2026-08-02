import unittest
from types import SimpleNamespace

from process_manager.memory import build_memory_summary, parse_meminfo


GIB = 1024**3


class MemorySummaryTests(unittest.TestCase):
    def test_parse_meminfo_converts_kernel_values_to_bytes(self):
        parsed = parse_meminfo(
            "MemTotal:       16384 kB\n"
            "MemFree:          4096 kB\n"
            "MemAvailable:     6144 kB\n"
            "HugePages_Total:      2\n"
        )

        self.assertEqual(parsed["MemTotal"], 16384 * 1024)
        self.assertEqual(parsed["MemFree"], 4096 * 1024)
        self.assertEqual(parsed["MemAvailable"], 6144 * 1024)
        self.assertEqual(parsed["HugePages_Total"], 2)

    def test_summary_matches_dashboard_active_and_cache_breakdown(self):
        processes = [
            SimpleNamespace(pid=10, rss_bytes=5 * GIB, gpu_memory_bytes=4 * GIB),
            SimpleNamespace(pid=11, rss_bytes=2 * GIB, gpu_memory_bytes=1 * GIB),
            SimpleNamespace(pid=12, rss_bytes=1 * GIB, gpu_memory_bytes=0),
        ]

        summary = build_memory_summary(
            {
                "MemTotal": 16 * GIB,
                "MemFree": 4 * GIB,
                "MemAvailable": 6 * GIB,
            },
            processes,
        )

        self.assertEqual(summary["total_mb"], 16384)
        self.assertEqual(summary["used_bytes"], 10 * GIB)
        self.assertEqual(summary["cache_bytes"], 2 * GIB)
        self.assertEqual(summary["gpu_alloc_bytes"], 5 * GIB)
        self.assertEqual(summary["model_rss_bytes"], 8 * GIB)
        self.assertEqual(summary["active_other_bytes"], 5 * GIB)
        self.assertEqual(summary["model_rss_pids"], [10, 11, 12])

    def test_model_rss_matches_dashboard_top_ten_processes(self):
        processes = [
            SimpleNamespace(pid=pid, rss_bytes=pid * 1024, gpu_memory_bytes=0)
            for pid in range(1, 13)
        ]

        summary = build_memory_summary(
            {"MemTotal": 64 * GIB, "MemFree": 8 * GIB, "MemAvailable": 32 * GIB},
            processes,
        )

        self.assertEqual(summary["model_rss_pids"], list(range(12, 2, -1)))
        self.assertEqual(summary["model_rss_process_count"], 10)
        self.assertEqual(summary["model_rss_bytes"], sum(pid * 1024 for pid in range(3, 13)))


if __name__ == "__main__":
    unittest.main()
