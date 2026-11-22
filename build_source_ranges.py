"""Generate source symbol spans from the pinned SQLGlot checkout."""

import argparse
import ast
import gzip
import json
from pathlib import Path

PINNED_COMMIT = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


def spans(path: Path) -> list[list[object]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min((d.lineno for d in node.decorator_list), default=node.lineno)
            found.append([node.name, start, node.end_lineno, node.lineno,
                          "class" if isinstance(node, ast.ClassDef) else "function"])
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min((d.lineno for d in child.decorator_list), default=child.lineno)
                    found.append([f"{node.name}.{child.name}", start, child.end_lineno,
                                  child.lineno, "method"])
    return sorted(found, key=lambda item: (item[1], item[2], item[0]))


def build(root: Path):
    return {"schema": 1, "pinned_commit": PINNED_COMMIT,
            "symbols": {path.relative_to(root).as_posix(): spans(path)
                        for path in sorted((root / "sqlglot").rglob("*.py"))}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(build(args.source.resolve()), handle, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    main()
