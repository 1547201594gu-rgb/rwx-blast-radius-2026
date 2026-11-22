"""Package only pinned SQLGlot Python source for runtime AST comparison."""

import argparse
import gzip
import json
from pathlib import Path

PINNED_COMMIT = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


def build(root: Path) -> dict:
    return {"schema": 1, "pinned_commit": PINNED_COMMIT,
            "sources": {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
                        for path in sorted((root / "sqlglot").rglob("*.py"))}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(build(args.source.resolve()), handle, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    main()
