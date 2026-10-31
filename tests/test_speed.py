"""The drive benchmark, run against a file instead of a stick.

It is destructive by design, so these tests point it at a temporary file: what
is checked is the arithmetic and the refusals, not the numbers a real drive
would produce.
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import speed_logic as S


class Measure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lufux-test-")
        self.addCleanup(self.tmp.cleanup)

    def measure(self, size):
        path = os.path.join(self.tmp.name, "target.img")
        with open(path, "wb") as f:
            f.truncate(size)
        fd = os.open(path, os.O_WRONLY | os.O_SYNC)
        try:
            return S.measure_fd(fd, False), os.path.getsize(path)
        finally:
            os.close(fd)

    def test_it_reports_two_positive_numbers(self):
        (seq_mbps, rand_iops), _ = self.measure(16 << 20)
        self.assertGreater(seq_mbps, 0)
        self.assertGreater(rand_iops, 0)

    def test_it_writes_only_within_the_target(self):
        _, size = self.measure(16 << 20)
        self.assertEqual(size, 16 << 20)

    def test_a_target_too_small_to_measure_is_refused(self):
        # a drive that cannot hold two sequential chunks would produce a figure
        # from one truncated write
        with self.assertRaises(ValueError):
            self.measure(S.SEQ_CHUNK)


if __name__ == "__main__":
    unittest.main()
