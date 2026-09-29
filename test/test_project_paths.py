import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from config.project_paths import AGENT_ROOT, PROJECT_ROOT, resolve_project_path
from persistence.sql_mirror_runtime import get_default_sqlite_mirror_path


def test_relative_runtime_path_resolves_from_project_root():
    resolved = resolve_project_path(
        "ccAgent/CCSDKAgent/workspace_jobs/run_example"
    )

    assert resolved == AGENT_ROOT / "workspace_jobs" / "run_example"


def test_stale_agent_artifact_path_is_rebased_to_current_checkout():
    resolved = resolve_project_path(
        "/srv/legacy/SupplyChainAgent/ccAgent/CCSDKAgent/"
        "workspace_jobs/run_example"
    )

    assert resolved == AGENT_ROOT / "workspace_jobs" / "run_example"


def test_stale_project_path_is_rebased_to_current_checkout():
    resolved = resolve_project_path(
        "/srv/previous/SupplyChainAgent/config/scenario.json"
    )

    assert resolved == PROJECT_ROOT / "config" / "scenario.json"


def test_existing_absolute_path_is_preserved(tmp_path):
    existing = tmp_path / "external.sqlite"
    existing.touch()

    assert resolve_project_path(existing) == existing.resolve()


def test_sqlite_mirror_accepts_project_relative_path(monkeypatch):
    monkeypatch.setenv(
        "SIMULATION_SQL_MIRROR_PATH",
        "ccAgent/CCSDKAgent/workspace_jobs/_operations/test.sqlite",
    )

    assert get_default_sqlite_mirror_path() == (
        AGENT_ROOT / "workspace_jobs" / "_operations" / "test.sqlite"
    )


def test_root_environment_overrides_are_resolved_in_fresh_process(tmp_path):
    project_root = tmp_path / "portable-checkout"
    agent_root = project_root / "runtime-agent"
    agent_root.mkdir(parents=True)
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT),
            "SUPPLY_CHAIN_PROJECT_ROOT": str(project_root),
            "CCSDKAGENT_ROOT": "runtime-agent",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from config.project_paths import PROJECT_ROOT, AGENT_ROOT; "
                "print(PROJECT_ROOT); print(AGENT_ROOT)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [str(project_root), str(agent_root)]


def test_operations_subprocess_dispatch_uses_portable_project_root(
    monkeypatch,
    tmp_path,
):
    import runtime.operations.api as operations_api_module

    popen_calls = []

    class Repository:
        def update_job(self, job_id, updates):
            self.job_id = job_id
            self.updates = updates

    def fake_popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return SimpleNamespace(pid=3210)

    monkeypatch.setattr(
        operations_api_module,
        "WORKSPACE_JOBS_ROOT",
        tmp_path,
    )
    monkeypatch.setattr(operations_api_module.subprocess, "Popen", fake_popen)
    repository = Repository()
    api = operations_api_module.OperationsAPI(repository=repository)

    result = api._dispatch_subprocess(
        repository,
        {"job_id": "job-portable", "scenario_id": "single_case_01"},
        scenario_id=None,
        worker_id=None,
        client_dir=None,
        workspace_dir=None,
        execution_mode="scripted",
    )

    assert result["process_pid"] == 3210
    assert popen_calls[0][1]["cwd"] == str(PROJECT_ROOT)
    assert str(PROJECT_ROOT) in popen_calls[0][1]["env"]["PYTHONPATH"].split(
        os.pathsep
    )
