"""V5 experimental JSONL selector; all diagnostics go to stderr."""

import gzip
import json
import math
import os
from pathlib import Path
import resource
import sys
import time

from impact_selector import FIXTURE_MODES, analyze_patch
from selector import best_schedule

DATA = Path("/data")
APP = Path("/app")


def read_gzip(name):
    with gzip.open(APP / name, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    start = time.process_time()
    fixture_mode = os.environ.get("V5_FIXTURE_MODE", "baseline")
    if fixture_mode not in FIXTURE_MODES:
        raise ValueError(f"unknown fixture mode: {fixture_mode}")
    manifest = json.loads((DATA / "tests.json").read_text(encoding="utf-8"))
    tests = manifest["tests"]
    coverage = read_gzip("coverage_index.json.gz")
    ranges = read_gzip("source_ranges.json.gz")
    dependencies = read_gzip("dependency-map.json.gz")
    schedules = {}
    for patch in sorted((DATA / "commits").glob("*.patch")):
        decision = analyze_patch(patch.read_text(encoding="utf-8"), manifest, coverage,
                                 ranges, dependencies, fixture_mode=fixture_mode)
        selected = decision.test_numbers
        if selected not in schedules:
            chosen = [tests[number] for number in selected]
            schedules[selected] = best_schedule(chosen)
        workers, cost = schedules[selected]
        print(json.dumps({"commit": patch.stem, "workers": workers}, separators=(",", ":")))
        print(json.dumps({"commit": patch.stem, "fixture_mode": fixture_mode,
                          "candidate_count": len(selected),
                          "selected_duration_ms": sum(math.floor(tests[n]["seconds"] * 1000 + 0.5)
                                                      for n in selected),
                          "workers": len(workers), "schedule_cost_ms": cost,
                          "fallback_required": decision.fallback_required,
                          "fallback_reasons": decision.fallback_reasons,
                          "uncertainty": decision.uncertainty}, separators=(",", ":")), file=sys.stderr)
    print(f"selector_cpu_ms={(time.process_time() - start) * 1000:.3f}", file=sys.stderr)
    print(f"selector_peak_rss_kib={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
