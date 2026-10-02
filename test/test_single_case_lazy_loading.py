import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_with_missing_single_case_assets(body: str) -> subprocess.CompletedProcess:
    script = f"""
from pathlib import Path

original_exists = Path.exists

def exists_without_single_case_assets(path):
    if "agent/static_commands/single_enterprise" in path.as_posix():
        return False
    return original_exists(path)

Path.exists = exists_without_single_case_assets
{body}
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_simulation_server_import_does_not_require_single_case_assets():
    result = _run_with_missing_single_case_assets(
        'import simulate.simulation_server; print("server-import-ok")'
    )

    assert result.returncode == 0, result.stderr
    assert "server-import-ok" in result.stdout


def test_single_case_assets_are_checked_when_scenario_is_requested():
    result = _run_with_missing_single_case_assets(
        """
from config.simulation_preset_config import get_scenario_config

try:
    get_scenario_config("single_case_01_order_selection")
except FileNotFoundError as exc:
    print(exc)
else:
    raise AssertionError("single-case lookup unexpectedly succeeded")
"""
    )

    assert result.returncode == 0, result.stderr
    assert "Missing single-enterprise source file" in result.stdout
