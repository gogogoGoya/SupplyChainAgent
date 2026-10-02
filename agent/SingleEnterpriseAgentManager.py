"""CLI entry for single-enterprise diagnostic case runs."""

from pathlib import Path
import sys

import anyio


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.single_enterprise.orchestrator import main  # noqa: E402


if __name__ == "__main__":
    anyio.run(main)
