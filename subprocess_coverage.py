"""Build-time ProcessPoolExecutor attribution for observed SQLGlot execution.

Each submitted task carries its current pytest node ID. A worker traces one
task at a time, including serialization of its result, and writes an isolated
record. Import-time child startup and other process launchers remain unknown.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import coverage
import hashlib
import json
import os
from pathlib import Path
import pickle
import time


_original_submit = ProcessPoolExecutor.submit
_root: Path | None = None
_spool: Path | None = None
_context: str | None = None
_lineage: str | None = None
_counters: dict[str, int] = {}
_submissions: list[dict] = []
_all_submissions: list[dict] = []


def set_context(context: str | None, lineage: str | None = None) -> None:
    """Start a fresh per-test submission sequence; None means unknown parent."""
    global _context, _lineage, _submissions
    _context = context
    _lineage = lineage if lineage is not None else context
    _submissions = []


def submissions() -> tuple[dict, ...]:
    return tuple(_submissions)


def all_submissions() -> tuple[dict, ...]:
    return tuple(_all_submissions)


def reset() -> None:
    """Clear one build's submission ledger before installing instrumentation."""
    global _counters, _all_submissions
    _counters = {}
    _all_submissions = []
    set_context(None)


def install(root: Path, spool: Path) -> None:
    global _root, _spool
    _root, _spool = root.resolve(), spool.resolve()
    ProcessPoolExecutor.submit = _traced_submit


def uninstall() -> None:
    ProcessPoolExecutor.submit = _original_submit
    set_context(None)


def _traced_submit(self, fn, /, *args, **kwargs):
    if _root is None or _spool is None:
        raise RuntimeError("subprocess coverage was not configured")
    context = _context or "unknown"
    parent = _lineage or context
    _counters[parent] = _counters.get(parent, 0) + 1
    lineage = f"{parent}/{_counters[parent]}"
    future = _original_submit(self, traced_task, context, lineage, parent,
                              str(_root), str(_spool), fn, args, kwargs)
    item = {"context": context, "lineage": lineage, "parent": parent}
    _submissions.append(item)
    _all_submissions.append(item)
    return future


class _SerializedResult:
    def __init__(self, data: bytes):
        self.data = data

    def __reduce__(self):
        return pickle.loads, (self.data,)


def _record_path(spool: Path, lineage: str) -> Path:
    return spool / (hashlib.sha256(lineage.encode("utf-8")).hexdigest() + ".json")


def traced_task(context: str, lineage: str, parent: str, root_name: str,
                spool_name: str, fn, args, kwargs):
    """Execute one pool task with an isolated trace and exact parent context."""
    root, spool = Path(root_name), Path(spool_name)
    install(root, spool)
    set_context(context, lineage)
    cov = coverage.Coverage(data_file=None, include=[str(root / "sqlglot" / "*")],
                            config_file=False)
    status = "ok"
    started = time.process_time()
    cov.start()
    try:
        value = fn(*args, **kwargs)
        # Serialization normally happens after the callable returns. Do it
        # under this task's trace, then hand the bytes to the pool unchanged.
        return _SerializedResult(pickle.dumps(value))
    except BaseException:
        status = "error"
        raise
    finally:
        cov.stop()
        lines = {}
        for name in cov.get_data().measured_files():
            try:
                relative = Path(name).resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if relative.startswith("sqlglot/"):
                lines[relative] = sorted(cov.get_data().lines(name) or ())
        record = {"context": context, "lineage": lineage, "parent": parent,
                  "status": status, "lines": dict(sorted(lines.items())),
                  "submissions": sorted(submissions(), key=lambda item: item["lineage"]),
                  "cpu_seconds": round(time.process_time() - started, 6),
                  "child_import_time_unattributed": True}
        path = _record_path(spool, lineage)
        with path.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True, separators=(",", ":"))
        set_context(None)


def load_records(spool: Path, roots: tuple[dict, ...]) -> tuple[list[dict], list[str]]:
    """Read task records and expose missing or ambiguous parentage."""
    records = [json.loads(path.read_text(encoding="utf-8"))
               for path in sorted(spool.glob("*.json"))]
    expected = {item["lineage"] for item in roots}
    expected.update(child["lineage"] for record in records
                    for child in record["submissions"])
    recorded = {record["lineage"] for record in records}
    unresolved = ["child_import_time_unattributed",
                  "other_python_process_launchers_not_instrumented"]
    unresolved.extend(f"missing_child_record:{lineage}" for lineage in sorted(expected - recorded))
    unresolved.extend(f"unsubmitted_child_record:{lineage}" for lineage in sorted(recorded - expected))
    unresolved.extend(f"unknown_parent:{record['lineage']}" for record in records
                      if record["context"] == "unknown")
    return sorted(records, key=lambda record: record["lineage"]), sorted(set(unresolved))
