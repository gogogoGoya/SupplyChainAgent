#!/usr/bin/env python3
"""Reject host-specific home paths in runtime source and active Agent Skills."""

from __future__ import annotations

import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOME_PATH_PATTERN = re.compile(r"/(?:home|Users)/[^/\s]+/")
SOURCE_SUFFIXES = {".env", ".js", ".jsx", ".json", ".md", ".py", ".sh"}
RUNTIME_ROOTS = (
    "config",
    "core",
    "enterprise",
    "persistence",
    "runtime",
    "scripts",
    "simulate",
    "visualization/src",
)
ACTIVE_SKILLS_ROOT = PROJECT_ROOT / "ccAgent" / "CCSDKAgent" / ".claude" / "skills"


def _runtime_files():
    for relative_root in RUNTIME_ROOTS:
        root = PROJECT_ROOT / relative_root
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in SOURCE_SUFFIXES:
                yield path
    vite_config = PROJECT_ROOT / "visualization" / "vite.config.js"
    if vite_config.is_file():
        yield vite_config
    if ACTIVE_SKILLS_ROOT.is_dir():
        yield from ACTIVE_SKILLS_ROOT.glob("*/SKILL.md")


def main() -> int:
    violations = []
    for path in sorted(set(_runtime_files())):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if HOME_PATH_PATTERN.search(line):
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{line_number}: {line.strip()}"
                )

    if violations:
        print("Host-specific paths found in runtime files:", file=sys.stderr)
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("Portable path check passed: no host-specific runtime paths found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
