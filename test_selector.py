import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import score
import selector
from selector import MAX_WORKERS, WORKER_COST_MS, best_schedule, ordered_tests, split


def tests_with_seconds(*seconds):
    return [{"number": number, "seconds": value} for number, value in enumerate(seconds)]


class SchedulingTests(unittest.TestCase):
    def test_every_candidate_has_each_test_once_and_no_more_than_eight_workers(self):
        tests = tests_with_seconds(*([0.001] * 17))
        ordered = ordered_tests(tests)
        for count in range(1, MAX_WORKERS + 1):
            with self.subTest(workers=count):
                workers, _ = split(ordered, count)
                self.assertEqual(sorted(n for worker in workers for n in worker), list(range(17)))
                self.assertEqual(len(workers), count)

    def test_cost_uses_milliseconds_and_selects_minimum(self):
        tests = tests_with_seconds(5.000, 5.000, 5.000, 5.000)
        workers, cost = best_schedule(tests)
        self.assertEqual((len(workers), cost), (4, 13_000))
        self.assertEqual(sorted(n for worker in workers for n in worker), list(range(4)))
        ordered = ordered_tests(tests)
        for count in range(1, 5):
            candidate, candidate_cost = split(ordered, count)
            loads = [sum(score._duration_milliseconds(tests[n]["seconds"]) for n in worker) for worker in candidate]
            self.assertEqual(candidate_cost, max(loads) + WORKER_COST_MS * count)
            self.assertGreaterEqual(candidate_cost, cost)

    def test_eight_workers_can_be_cheapest(self):
        workers, cost = best_schedule(tests_with_seconds(*([10.0] * 8)))
        self.assertEqual((len(workers), cost), (8, 26_000))
        self.assertEqual(sorted(n for worker in workers for n in worker), list(range(8)))

    def test_tie_prefers_fewer_workers(self):
        workers, cost = best_schedule(tests_with_seconds(2.000, 2.000))
        self.assertEqual((len(workers), cost), (1, 6_000))

    def test_empty_and_single_test(self):
        self.assertEqual(best_schedule([]), ([], 0))
        self.assertEqual(best_schedule(tests_with_seconds(0.031)), ([[0]], 2_031))

    def test_duration_conversion_matches_official_scorer(self):
        values = (0.0, 0.0005, 0.0015, 0.031, 1.2345)
        tests = tests_with_seconds(*values)
        self.assertEqual(
            dict(ordered_tests(tests)),
            {number: score._duration_milliseconds(seconds) for number, seconds in enumerate(values)},
        )

    def test_equal_durations_have_deterministic_order(self):
        tests = [
            {"number": 7, "seconds": 0.010},
            {"number": 2, "seconds": 0.010},
            {"number": 4, "seconds": 0.010},
        ]
        self.assertEqual(ordered_tests(tests), [(2, 10), (4, 10), (7, 10)])
        self.assertEqual(best_schedule(tests), best_schedule(list(reversed(tests))))

    def test_main_emits_only_jsonl_on_stdout_and_diagnostics_on_stderr(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            data = Path(directory)
            (data / "commits").mkdir()
            (data / "commits" / "b.patch").write_text("", encoding="utf-8")
            (data / "commits" / "a.patch").write_text("", encoding="utf-8")
            tests = tests_with_seconds(0.010, 0.020, 0.030)
            (data / "tests.json").write_text(json.dumps({"tests": tests}), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(selector, "DATA", data), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                selector.main()
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(stdout.getvalue().endswith("\n"))
        parsed = [json.loads(line) for line in lines]
        self.assertEqual([item["commit"] for item in parsed], ["a", "b"])
        for item in parsed:
            self.assertEqual(set(item), {"commit", "workers"})
            workers = item["workers"]
            self.assertLessEqual(len(workers), MAX_WORKERS)
            self.assertEqual(sorted(n for worker in workers for n in worker), [0, 1, 2])
        self.assertIn("selected 3 tests", stderr.getvalue())
        self.assertNotIn("selected", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
