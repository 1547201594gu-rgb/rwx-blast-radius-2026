import unittest

from impact_selector import PINNED_COMMIT, analyze_patch, resolve_fixture_readers


def edit(path, old="old", new="new", line=3):
    return (f"diff --git a/{path} b/{path}\n"
            "index 1111111..2222222 100644\n"
            f"--- a/{path}\n+++ b/{path}\n"
            f"@@ -{line},1 +{line},1 @@\n-{old}\n+{new}\n")


class ImpactSelectorTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"tests": [
            {"number": 0, "id": "tests/test_a.py::A::test_one", "file": "tests/test_a.py", "seconds": 0.1},
            {"number": 1, "id": "tests/test_b.py::B::test_two", "file": "tests/test_b.py", "seconds": 0.2},
        ]}
        self.coverage = {"pinned_commit": PINNED_COMMIT, "manifest_count": 2,
                         "missing_ids": [], "extra_ids": [], "pytest_exit_code": 0,
                         "symbol_index": {"sqlglot/foo.py": {"Foo.method": [0]}},
                         "collection_lines": {},
                         "fixture_reads": {"tests/fixtures/a.sql": {
                             "test:tests/test_b.py::B::test_two": [["builtins.open", "tests/helpers.py:44"]]}}}
        self.ranges = {"pinned_commit": PINNED_COMMIT,
                       "symbols": {"sqlglot/foo.py": [["Foo", 1, 8, 1, "class"],
                                                       ["Foo.method", 2, 5, 2, "method"]]}}
        self.graph = {"commit": PINNED_COMMIT, "direct_dependencies": {}}

    def analyze(self, text):
        return analyze_patch(text, self.manifest, self.coverage, self.ranges, self.graph)

    def test_method_body_uses_positive_coverage(self):
        result = self.analyze(edit("sqlglot/foo.py"))
        self.assertEqual(result.test_numbers, (0,))
        self.assertFalse(result.fallback_required)
        self.assertTrue(result.uncertainty)

    def test_import_change_runs_full_suite(self):
        result = self.analyze(edit("sqlglot/foo.py", "import x", "import y"))
        self.assertEqual(result.test_numbers, (0, 1))
        self.assertTrue(result.fallback_required)

    def test_class_definition_runs_full_suite(self):
        result = self.analyze(edit("sqlglot/foo.py", "class Foo:", "class Foo(Bar):", line=1))
        self.assertEqual(result.test_numbers, (0, 1))
        self.assertTrue(result.fallback_required)

    def test_fixture_read_uses_observed_reader(self):
        result = self.analyze(edit("tests/fixtures/a.sql"))
        self.assertEqual(result.test_numbers, (0, 1))
        self.assertTrue(result.fallback_required)
        self.assertEqual(result.reasons[1], ("full_suite_fallback", "observed_fixture_read:tests/fixtures/a.sql"))
        self.assertIn("fixture_impact_completeness_unproved:tests/fixtures/a.sql", result.fallback_reasons)
        self.assertFalse(any(reason.startswith("fixture_reader_unresolved") for reason in result.fallback_reasons))

    def test_unknown_fixture_runs_full_suite(self):
        result = self.analyze(edit("tests/fixtures/missing.sql"))
        self.assertEqual(result.test_numbers, (0, 1))
        self.assertTrue(result.fallback_required)

    def test_direct_test_file(self):
        result = self.analyze(edit("tests/test_a.py"))
        self.assertEqual(result.test_numbers, (0,))

    def test_multiple_files_union(self):
        result = self.analyze(edit("sqlglot/foo.py") + edit("tests/fixtures/a.sql"))
        self.assertEqual(result.test_numbers, (0, 1))
        self.assertTrue(result.fallback_required)

    def test_raw_and_prefixed_reader_ids_resolve_once(self):
        raw = "tests/test_b.py::B::test_two"
        result = resolve_fixture_readers((raw, "test:" + raw), self.manifest)
        self.assertEqual(result.numbers, (1,))
        self.assertEqual(result.resolved, (("test:" + raw, 1), (raw, 1)))
        self.assertEqual(result.unresolved, ())

    def test_raw_reader_is_used_by_patch_analysis(self):
        self.coverage["fixture_reads"]["tests/fixtures/a.sql"] = {
            "tests/test_b.py::B::test_two": [["builtins.open", "tests/helpers.py:44"]]}
        result = self.analyze(edit("tests/fixtures/a.sql"))
        self.assertIn("observed_fixture_read:tests/fixtures/a.sql", result.reasons[1])
        self.assertTrue(result.fallback_required)

    def test_multiple_readers_and_stable_order(self):
        a = "tests/test_a.py::A::test_one"
        b = "tests/test_b.py::B::test_two"
        first = resolve_fixture_readers((b, a, b), self.manifest)
        second = resolve_fixture_readers((a, b), self.manifest)
        self.assertEqual(first, second)
        self.assertEqual(first.numbers, (0, 1))

    def test_unknown_reader_is_reported_and_falls_back(self):
        self.coverage["fixture_reads"]["tests/fixtures/a.sql"]["tests/test_missing.py::test_unknown"] = []
        result = self.analyze(edit("tests/fixtures/a.sql"))
        self.assertTrue(result.fallback_required)
        self.assertIn("fixture_reader_unresolved:tests/fixtures/a.sql:tests/test_missing.py::test_unknown",
                      result.fallback_reasons)

    def test_ambiguous_short_name_is_not_guessed(self):
        manifest = {"tests": [
            {"number": 0, "id": "tests/test_a.py::A::test_same", "file": "tests/test_a.py"},
            {"number": 1, "id": "tests/test_b.py::B::test_same", "file": "tests/test_b.py"}]}
        result = resolve_fixture_readers(("test_same",), manifest)
        self.assertEqual(result.numbers, ())
        self.assertEqual(result.ambiguous, ("test_same",))

    def test_ambiguous_reader_causes_full_suite_fallback(self):
        self.manifest["tests"][0]["id"] = "tests/test_a.py::A::test_same"
        self.manifest["tests"][1]["id"] = "tests/test_b.py::B::test_same"
        self.coverage["fixture_reads"]["tests/fixtures/a.sql"] = {"test_same": []}
        result = self.analyze(edit("tests/fixtures/a.sql"))
        self.assertEqual(result.test_numbers, (0, 1))
        self.assertIn("fixture_reader_ambiguous:tests/fixtures/a.sql:test_same", result.fallback_reasons)

    def test_parameterized_base_is_ambiguous_but_exact_id_resolves(self):
        manifest = {"tests": [
            {"number": 0, "id": "tests/test_a.py::test_x[a]", "file": "tests/test_a.py"},
            {"number": 1, "id": "tests/test_a.py::test_x[b]", "file": "tests/test_a.py"}]}
        result = resolve_fixture_readers(("tests/test_a.py::test_x", "tests/test_a.py::test_x[a]"), manifest)
        self.assertEqual(result.numbers, (0,))
        self.assertEqual(result.ambiguous, ("tests/test_a.py::test_x",))

    def test_missing_and_invalid_ids_are_explicit(self):
        result = resolve_fixture_readers(("", "test:test:tests/test_a.py::A::test_one", None), self.manifest)
        self.assertEqual(result.numbers, ())
        self.assertEqual(len(result.unresolved), 3)

    def test_invalid_manifest_ids_are_rejected(self):
        for change in (
            {"id": ""}, {"id": "tests/test_other.py::test_one"},
            {"number": 2}, {"number": -1}, {"number": True},
        ):
            with self.subTest(change=change):
                manifest = {"tests": [dict(self.manifest["tests"][0], **change),
                                      self.manifest["tests"][1]]}
                with self.assertRaises(ValueError):
                    resolve_fixture_readers((), manifest)
        duplicate = {"tests": [self.manifest["tests"][0],
                               dict(self.manifest["tests"][0], number=1)]}
        with self.assertRaises(ValueError):
            resolve_fixture_readers((), duplicate)
        for path in ("tests/../tests/test_a.py", "tests//test_a.py", "tests\\test_a.py"):
            with self.subTest(path=path):
                manifest = {"tests": [dict(self.manifest["tests"][0], file=path,
                                          id=path + "::A::test_one"), self.manifest["tests"][1]]}
                with self.assertRaises(ValueError):
                    resolve_fixture_readers((), manifest)
        with self.assertRaises(ValueError):
            resolve_fixture_readers((), {"tests": [{"number": 0, "file": "tests/test_a.py"}]})

    def test_collection_read_remains_unresolved(self):
        self.coverage["fixture_reads"]["tests/fixtures/a.sql"]["collection"] = []
        result = self.analyze(edit("tests/fixtures/a.sql"))
        self.assertIn("fixture_collection_read:tests/fixtures/a.sql", result.fallback_reasons)
        self.assertTrue(result.fallback_required)

    def test_invalid_patch_runs_full_suite(self):
        result = self.analyze("not a unified diff")
        self.assertEqual(result.test_numbers, (0, 1))
        self.assertTrue(result.fallback_required)

    def test_incomplete_map_is_rejected(self):
        self.coverage["missing_ids"] = ["tests/test_a.py::A::test_one"]
        with self.assertRaises(ValueError):
            self.analyze(edit("sqlglot/foo.py"))


if __name__ == "__main__":
    unittest.main()
