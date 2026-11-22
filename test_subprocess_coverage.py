"""Actual spawned-process probes for build-time coverage attribution."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
import runpy
import tempfile
import unittest

import subprocess_coverage as trace


def execute_probe(root, value):
    probe = runpy.run_path(str(Path(root) / "sqlglot" / "probe.py"))["probe"]
    return probe(value)


def nested_probe(root, value):
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
        return pool.submit(execute_probe, root, value).result()


class ReduceProbe:
    def __init__(self, root):
        self.root = root

    def __reduce__(self):
        execute_probe(self.root, 7)
        return int, (8,)


def return_reduce_probe(root):
    return ReduceProbe(root)


class SubprocessCoverageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source = self.root / "sqlglot" / "probe.py"
        source.parent.mkdir()
        source.write_text("def probe(value):\n    if value < 0:\n        raise ValueError('probe failure')\n    return value + 1\n",
                          encoding="utf-8")
        self.spool = self.root / "spool.tmp"
        self.spool.mkdir()
        trace.reset()
        trace.install(self.root, self.spool)
        self.addCleanup(trace.uninstall)

    def records(self):
        return trace.load_records(self.spool, trace.all_submissions())

    def test_one_spawned_task_has_exact_test_parent(self):
        trace.set_context("test:tests/test_a.py::A::test_one")
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            self.assertEqual(pool.submit(execute_probe, str(self.root), 4).result(), 5)
        records, unresolved = self.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["context"], "test:tests/test_a.py::A::test_one")
        self.assertIn("sqlglot/probe.py", records[0]["lines"])
        self.assertFalse(any(reason.startswith("missing_child_record:") for reason in unresolved))

    def test_multiple_and_nested_tasks_keep_parent_lineage(self):
        trace.set_context("test:tests/test_a.py::A::test_one")
        with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
            results = [pool.submit(execute_probe, str(self.root), value) for value in (1, 2)]
            results.append(pool.submit(nested_probe, str(self.root), 3))
            self.assertEqual([item.result() for item in results], [2, 3, 4])
        records, unresolved = self.records()
        self.assertEqual(len(records), 4)
        self.assertTrue(any(record["parent"].count("/") > 1 for record in records))
        self.assertFalse(any(reason.startswith("missing_child_record:") for reason in unresolved))

    def test_failure_is_recorded_without_losing_parent(self):
        trace.set_context("test:tests/test_a.py::A::test_one")
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            with self.assertRaises(ValueError):
                pool.submit(execute_probe, str(self.root), -1).result()
        records, _ = self.records()
        self.assertEqual(records[0]["status"], "error")
        self.assertEqual(records[0]["context"], "test:tests/test_a.py::A::test_one")

    def test_result_serialization_is_traced_to_the_originating_test(self):
        trace.set_context("test:tests/test_a.py::A::test_one")
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            self.assertEqual(pool.submit(return_reduce_probe, str(self.root)).result(), 8)
        records, _ = self.records()
        self.assertIn("sqlglot/probe.py", records[0]["lines"])

    def test_unknown_parent_and_collection_are_separate(self):
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            trace.set_context("collection")
            self.assertEqual(pool.submit(execute_probe, str(self.root), 1).result(), 2)
            trace.set_context(None)
            self.assertEqual(pool.submit(execute_probe, str(self.root), 2).result(), 3)
        records, unresolved = self.records()
        self.assertEqual([item["context"] for item in records], ["collection", "unknown"])
        self.assertTrue(any(reason.startswith("unknown_parent:") for reason in unresolved))

    def test_import_time_pool_is_recorded_as_collection(self):
        module = self.root / "import_probe.py"
        module.write_text(
            "from concurrent.futures import ProcessPoolExecutor\n"
            "from multiprocessing import get_context\n"
            "from test_subprocess_coverage import execute_probe\n"
            f"with ProcessPoolExecutor(max_workers=1, mp_context=get_context('spawn')) as pool:\n"
            f"    RESULT = pool.submit(execute_probe, {str(self.root)!r}, 2).result()\n",
            encoding="utf-8")
        trace.set_context("collection")
        self.assertEqual(runpy.run_path(str(module))["RESULT"], 3)
        records, _ = self.records()
        self.assertEqual([record["context"] for record in records], ["collection"])

    def test_reused_worker_does_not_mix_two_test_methods(self):
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            trace.set_context("test:tests/test_a.py::A::test_one")
            self.assertEqual(pool.submit(execute_probe, str(self.root), 1).result(), 2)
            trace.set_context("test:tests/test_a.py::A::test_two")
            self.assertEqual(pool.submit(execute_probe, str(self.root), 2).result(), 3)
        records, _ = self.records()
        self.assertEqual({item["context"] for item in records}, {
            "test:tests/test_a.py::A::test_one", "test:tests/test_a.py::A::test_two"})
        self.assertEqual(len({item["lineage"] for item in records}), 2)

    def test_record_contents_are_deterministic_except_measured_cpu(self):
        trace.set_context("test:tests/test_a.py::A::test_one")
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            self.assertEqual(pool.submit(execute_probe, str(self.root), 1).result(), 2)
        first, _ = self.records()
        trace.reset()
        second_spool = self.root / "second.tmp"
        second_spool.mkdir()
        trace.install(self.root, second_spool)
        trace.set_context("test:tests/test_a.py::A::test_one")
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            self.assertEqual(pool.submit(execute_probe, str(self.root), 1).result(), 2)
        second, _ = trace.load_records(second_spool, trace.all_submissions())
        for record in first + second:
            record.pop("cpu_seconds")
        self.assertEqual(first, second)

    def test_missing_record_and_unsupported_launchers_are_explicit(self):
        records, unresolved = trace.load_records(self.spool, (
            {"context": "test:tests/test_a.py::A::test_one", "lineage": "missing/1", "parent": "missing"},))
        self.assertEqual(records, [])
        self.assertIn("missing_child_record:missing/1", unresolved)
        self.assertIn("other_python_process_launchers_not_instrumented", unresolved)


if __name__ == "__main__":
    unittest.main()
