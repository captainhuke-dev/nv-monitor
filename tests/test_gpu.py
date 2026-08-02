import unittest

from process_manager.gpu import parse_gpu_memory_csv


class GpuParserTests(unittest.TestCase):
    def test_parse_gpu_memory_csv_sums_duplicate_pid_and_ignores_bad_rows(self):
        text = "\n".join(
            (
                "101, 1024",
                "202, 0",
                "303, [N/A]",
                "101, 512",
                "not-a-pid, 64",
                "404",
                "",
            )
        )

        self.assertEqual(
            parse_gpu_memory_csv(text),
            {
                101: 1536 * 1024 * 1024,
                202: 0,
            },
        )

    def test_parse_gpu_memory_csv_accepts_units_when_driver_ignores_nounits(self):
        self.assertEqual(
            parse_gpu_memory_csv("505, 1 MiB\n"),
            {505: 1024 * 1024},
        )


if __name__ == "__main__":
    unittest.main()
