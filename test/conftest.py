import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = ROOT / "ccAgent" / "CCSDKAgent"

for path in (ROOT, AGENT_ROOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

