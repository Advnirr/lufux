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
    def target(self, size):
        path = os.path.join(self.tmp.name, "target.img")
        with open(path, "wb") as f:
            f.truncate(size)
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lufux-test-")
        self.addCleanup(self.tmp.cleanup)

    def test_it_reports_two_positive_numbers(self):
        seq_mbps, rand_iops = S.measure(self.target(16 << 20))
        self.assertGreater(seq_mbps, 0)
        self.assertGreater(rand_iops, 0)

    def test_it_writes_only_within_the_target(self):
        size = 16 << 20
        path = self.target(size)
        S.measure(path)
        self.assertEqual(os.path.getsize(path), size)

    def test_a_target_too_small_to_measure_is_refused(self):
        # a drive that cannot hold two sequential chunks would produce a figure
        # from one truncated write
        with self.assertRaises(ValueError):
            S.measure(self.target(S.SEQ_CHUNK))

    def test_a_missing_target_raises_rather_than_returning_zero(self):
        with self.assertRaises(OSError):
            S.measure(os.path.join(self.tmp.name, "absent.img"))

    def test_the_caller_gets_a_failure_code_not_a_traceback(self):
        # main() swallows both, because a benchmark must never be the reason a
        # flash does not happen
        argv = sys.argv
        try:
            sys.argv = ["speed_logic.py", os.path.join(self.tmp.name, "absent.img")]
            self.assertEqual(S.main(), 1)
            sys.argv = ["speed_logic.py"]
            self.assertEqual(S.main(), 2)
        finally:
            sys.argv = argv


if __name__ == "__main__":
    unittest.main()
