"""Build observed per-test line and fixture evidence from the pinned SQLGlot tree.

The output records observations and unknowns; absence of a line is not an
exclusion proof. This build-only module is never imported by the selector.
"""

import argparse
import ast
import builtins
from collections import defaultdict
from contextlib import redirect_stdout
import gzip
import io
import json
import os
from pathlib import Path
import resource
import sys
import time

import coverage
import pytest
import subprocess_coverage as subprocess_trace


PINNED_COMMIT = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


class Recorder:
    def __init__(self, root: Path, manifest: dict, cov: coverage.Coverage):
        self.root = root.resolve()
        self.by_id = {t["id"]: t["number"] for t in manifest["tests"]}
        self.skipped_ids = set(manifest.get("skipped", ()))
        self.cov = cov
        self.current = "collection"
        self.collected = set()
        self.reported = defaultdict(set)
        self.fixture_reads = defaultdict(set)
        self._open = builtins.open
        self._io_open = io.open
        self._os_open = os.open
        self._path_open = Path.open
        self.trace_subprocesses = False

    def _read(self, path, method):
        if isinstance(path, int):
            return
        try:
            relative = Path(path).resolve().relative_to(self.root).as_posix()
        except (OSError, TypeError, ValueError):
            return
        if relative.startswith("tests/fixtures/"):
            frame = sys._getframe(2)
            try:
                site = f"{Path(frame.f_code.co_filename).resolve().relative_to(self.root).as_posix()}:{frame.f_lineno}"
            except ValueError:
                site = "external"
            self.fixture_reads[(self.current, relative)].add((method, site))

    def install_reads(self):
        recorder = self

        def open_file(path, mode="r", *args, **kwargs):
            handle = recorder._open(path, mode, *args, **kwargs)
            if "r" in mode or "+" in mode:
                recorder._read(path, "builtins.open")
            return handle

        def io_open(path, mode="r", *args, **kwargs):
            handle = recorder._io_open(path, mode, *args, **kwargs)
            if "r" in mode or "+" in mode:
                recorder._read(path, "io.open")
            return handle

        def os_open(path, flags, *args, **kwargs):
            fd = recorder._os_open(path, flags, *args, **kwargs)
            if flags & os.O_ACCMODE != os.O_WRONLY:
                recorder._read(path, "os.open")
            return fd

        def path_open(path, mode="r", *args, **kwargs):
            handle = recorder._path_open(path, mode, *args, **kwargs)
            if "r" in mode or "+" in mode:
                recorder._read(path, "Path.open")
            return handle

        builtins.open = open_file
        io.open = io_open
        os.open = os_open
        Path.open = path_open

    def uninstall_reads(self):
        builtins.open = self._open
        io.open = self._io_open
        os.open = self._os_open
        Path.open = self._path_open

    def pytest_collection_finish(self, session):
        self.collected = {item.nodeid for item in session.items}

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        self.current = item.nodeid
        self.cov.switch_context("test:" + item.nodeid)
        if self.trace_subprocesses:
            subprocess_trace.set_context("test:" + item.nodeid)
        yield
        self.cov.switch_context("collection")
        self.current = "collection"
        if self.trace_subprocesses:
            subprocess_trace.set_context("collection")

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.reported[report.nodeid].add("failed")
        elif report.skipped:
            self.reported[report.nodeid].add("skipped")
        elif report.when == "call" and report.passed:
            self.reported[report.nodeid].add("passed")


def symbols_for(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    result = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append((node.name, node.lineno, node.end_lineno))
        elif isinstance(node, ast.ClassDef):
            result.append((node.name, node.lineno, node.end_lineno))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result.append((f"{node.name}.{child.name}", child.lineno, child.end_lineno))
    return result


def build_index(root: Path, manifest: dict, recorder: Recorder, data, exit_code: int,
                elapsed: float, child_records=(), child_unresolved=(), parent_cpu=0.0):
    by_id = recorder.by_id
    line_index = defaultdict(lambda: defaultdict(set))
    collection_lines = defaultdict(set)
    for filename in data.measured_files():
        try:
            relative = Path(filename).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if not relative.startswith("sqlglot/"):
            continue
        for lineno, contexts in data.contexts_by_lineno(filename).items():
            for context in contexts:
                if context == "collection":
                    collection_lines[relative].add(lineno)
                elif context.startswith("test:") and context[5:] in by_id:
                    line_index[relative][lineno].add(by_id[context[5:]])
    for record in child_records:
        context = record["context"]
        for relative, numbers in record["lines"].items():
            if context == "collection":
                collection_lines[relative].update(numbers)
            elif context.startswith("test:") and context[5:] in by_id:
                for lineno in numbers:
                    line_index[relative][lineno].add(by_id[context[5:]])
    symbol_index = {}
    unparsed = []
    for relative, lines in sorted(line_index.items()):
        symbols = symbols_for(root / relative)
        if symbols is None:
            unparsed.append(relative)
            continue
        found = {}
        for name, start, end in symbols:
            ids = set().union(*(ids for line, ids in lines.items() if start <= line <= end))
            if ids:
                found[name] = sorted(ids)
        symbol_index[relative] = found
    fixture_reads = defaultdict(lambda: defaultdict(list))
    for (context, path), evidence in recorder.fixture_reads.items():
        fixture_reads[path][context] = [list(item) for item in sorted(evidence)]
    absent = sorted(set(by_id) - recorder.collected)
    unresolved = ["coverage_observation_is_not_dependency_completeness"]
    if child_records:
        unresolved.extend(child_unresolved)
        unresolved.append("native_code_coverage_not_attributed_to_parent_test")
    else:
        unresolved.append("subprocess_and_native_code_coverage_not_attributed_to_parent_test")
    if exit_code:
        unresolved.append("pytest_run_not_clean")
    if absent:
        unresolved.append("official_tests_not_collected")
    if unparsed:
        unresolved.append("source_parse_failure")
    return {
        "schema": 1, "pinned_commit": PINNED_COMMIT,
        "manifest_count": len(by_id), "collected_count": len(recorder.collected),
        "missing_ids": absent, "extra_ids": sorted(recorder.collected - set(by_id) - recorder.skipped_ids),
        "pytest_exit_code": exit_code,
        "statuses": {test: sorted(status) for test, status in sorted(recorder.reported.items())},
        "line_index": {p: {str(n): sorted(ids) for n, ids in sorted(lines.items())}
                       for p, lines in sorted(line_index.items())},
        "collection_lines": {p: sorted(lines) for p, lines in sorted(collection_lines.items())},
        "symbol_index": symbol_index,
        "fixture_reads": {p: dict(contexts) for p, contexts in sorted(fixture_reads.items())},
        "unparsed_source": unparsed, "unresolved": sorted(set(unresolved)),
        "child_coverage": {
            "recorded_tasks": len(child_records),
            "child_cpu_seconds": round(sum(record["cpu_seconds"] for record in child_records), 3),
            "attributed_tests": sorted({by_id[record["context"][5:]]
                                        for record in child_records
                                        if record["context"].startswith("test:")
                                        and record["context"][5:] in by_id}),
            "relationships": [{key: record[key] for key in ("context", "lineage", "parent", "status")}
                              for record in child_records],
            "unresolved": list(child_unresolved),
        },
        "elapsed_seconds": round(elapsed, 3),
        "parent_cpu_seconds": round(parent_cpu, 3),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test", action="append", default=[])
    parser.add_argument("--subprocess-spool", type=Path)
    args = parser.parse_args()
    root = args.source.resolve()
    with args.manifest.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    ids = [t["id"] for t in manifest["tests"]]
    if len(ids) != len(set(ids)) or [t["number"] for t in manifest["tests"]] != list(range(len(ids))):
        raise ValueError("invalid official test manifest")
    if any(test not in ids for test in args.test):
        raise ValueError("requested test is not registered")
    cov = coverage.Coverage(data_file=None, include=[str(root / "sqlglot" / "*")], config_file=False)
    recorder = Recorder(root, manifest, cov)
    if args.subprocess_spool:
        args.subprocess_spool.mkdir(parents=True, exist_ok=False)
        subprocess_trace.reset()
        subprocess_trace.install(root, args.subprocess_spool)
        subprocess_trace.set_context("collection")
        recorder.trace_subprocesses = True
    sys.path.insert(0, str(root))
    os.chdir(root)
    started = time.perf_counter()
    started_cpu = time.process_time()
    recorder.install_reads()
    cov.start()
    cov.switch_context("collection")
    try:
        suite = args.test or ["tests"]
        with redirect_stdout(sys.stderr):
            exit_code = int(pytest.main(["-q", "-p", "no:cacheprovider", *suite], plugins=[recorder]))
    finally:
        cov.stop()
        recorder.uninstall_reads()
        if args.subprocess_spool:
            subprocess_trace.uninstall()
    child_records, child_unresolved = (subprocess_trace.load_records(
        args.subprocess_spool, subprocess_trace.all_submissions())
        if args.subprocess_spool else ([], []))
    index = build_index(root, manifest, recorder, cov.get_data(), exit_code,
                        time.perf_counter() - started, child_records, child_unresolved,
                        time.process_time() - started_cpu)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(index, handle, sort_keys=True, separators=(",", ":"))
    print(f"coverage: {len(recorder.collected)} collected, exit {exit_code}, "
          f"{index['elapsed_seconds']} s, {args.output.stat().st_size} bytes", file=sys.stderr)
    if exit_code or index["extra_ids"] or (not args.test and index["missing_ids"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
