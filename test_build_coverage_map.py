import tempfile
from pathlib import Path
import unittest

from build_coverage_map import Recorder, build_index, symbols_for
from build_source_ranges import spans


class FakeCoverageData:
    def __init__(self, filename, contexts):
        self.filename = filename
        self.contexts = contexts

    def measured_files(self):
        return [self.filename]

    def contexts_by_lineno(self, filename):
        return self.contexts


class CoverageMapTests(unittest.TestCase):
    def test_symbol_spans_preserve_method_and_class_distinction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "module.py"
            path.write_text("class A:\n    def f(self):\n        return 1\n", encoding="utf-8")
            self.assertIn(["A", 1, 3, 1, "class"], spans(path))
            self.assertIn(["A.f", 2, 3, 2, "method"], spans(path))
            self.assertIn(("A.f", 2, 3), symbols_for(path))

    def test_contexts_are_separate_and_failed_reads_are_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sqlglot" / "module.py"
            source.parent.mkdir()
            source.write_text("def f():\n    return 1\n", encoding="utf-8")
            fixture = root / "tests" / "fixtures" / "x.sql"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("select 1", encoding="utf-8")
            test_id = "tests/test_a.py::A::test_one"
            manifest = {"tests": [{"number": 0, "id": test_id, "file": "tests/test_a.py"}]}
            recorder = Recorder(root, manifest, None)
            recorder.collected = {test_id}
            recorder.install_reads()
            try:
                with open(fixture) as handle:
                    handle.read()
                with self.assertRaises(FileNotFoundError):
                    open(fixture.with_name("missing.sql"))
            finally:
                recorder.uninstall_reads()
            data = FakeCoverageData(str(source), {1: ["collection"], 2: ["test:" + test_id]})
            index = build_index(root, manifest, recorder, data, 0, 0.1)
            self.assertEqual(index["line_index"]["sqlglot/module.py"]["2"], [0])
            self.assertEqual(index["collection_lines"]["sqlglot/module.py"], [1])
            self.assertEqual(list(index["fixture_reads"]), ["tests/fixtures/x.sql"])

    def test_child_lines_merge_only_into_their_official_test(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            source = root / "sqlglot" / "module.py"
            source.parent.mkdir()
            source.write_text("def f():\n    return 1\n", encoding="utf-8")
            ids = ("tests/test_a.py::A::test_one", "tests/test_a.py::A::test_two")
            manifest = {"tests": [{"number": number, "id": nodeid,
                                   "file": "tests/test_a.py"}
                                  for number, nodeid in enumerate(ids)]}
            recorder = Recorder(root, manifest, None)
            recorder.collected = set(ids)
            records = [
                {"context": "test:" + ids[0], "lineage": "one/1", "parent": "one",
                 "status": "ok", "lines": {"sqlglot/module.py": [1, 2]},
                 "cpu_seconds": 0.1},
                {"context": "collection", "lineage": "collection/1", "parent": "collection",
                 "status": "ok", "lines": {"sqlglot/module.py": [1]},
                 "cpu_seconds": 0.1},
                {"context": "unknown", "lineage": "unknown/1", "parent": "unknown",
                 "status": "ok", "lines": {"sqlglot/module.py": [2]},
                 "cpu_seconds": 0.1},
            ]
            data = FakeCoverageData(str(source), {})
            index = build_index(root, manifest, recorder, data, 0, 0.1, records,
                                ["unknown_parent:unknown/1"])
            self.assertEqual(index["line_index"]["sqlglot/module.py"]["2"], [0])
            self.assertEqual(index["collection_lines"]["sqlglot/module.py"], [1])
            self.assertEqual(index["child_coverage"]["attributed_tests"], [0])
            self.assertIn("unknown_parent:unknown/1", index["unresolved"])


if __name__ == "__main__":
    unittest.main()
