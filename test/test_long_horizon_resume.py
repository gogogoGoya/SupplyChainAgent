import json
import pickle
from types import SimpleNamespace

from ccAgent.CCSDKAgent.MultiEnterpriseAgentManager import MultiEnterpriseClaudeManager
from ccAgent.CCSDKAgent.static_utils import StaticUtils
from message.message_manager import MessageManager
from network.exchange_manager import (
    get_next_id_counter_value,
    next_id,
    restore_next_id_counter_value,
)
from runtime.operations.service import OperationsService
from runtime.operations.runner_adapter import OperationsSimulationRunner
from runtime.operations.http_router import _last_sealed_round_from_artifact


class _MemoryRepository:
    def __init__(self):
        self.versions = {}
        self.jobs = {}
        self.runs = {}

    def save_version(self, version):
        self.versions[version["version_id"]] = dict(version)

    def get_version(self, version_id):
        return self.versions.get(version_id)

    def create_job(self, job):
        self.jobs[job["job_id"]] = dict(job)

    def update_job(self, job_id, changes):
        self.jobs[job_id].update(changes)

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def list_jobs(self, status=None, limit=None):
        jobs = list(self.jobs.values())
        if status:
            jobs = [job for job in jobs if job.get("status") == status]
        return jobs[:limit] if limit is not None else jobs

    def create_run(self, run):
        self.runs[run["run_id"]] = dict(run)

    def update_run(self, run_id, changes):
        self.runs.setdefault(run_id, {"run_id": run_id}).update(changes)

    def get_run(self, run_id):
        return self.runs.get(run_id)


def test_e1_resume_requeues_same_run_and_sealed_artifact(tmp_path):
    repository = _MemoryRepository()
    service = OperationsService(repository)
    job = service.create_experiment(
        scenario_id="long_horizon_evolution",
        scenario_config={},
        integration_profiles={},
        planned_total_steps=200,
        job_id="job-resume",
    )
    service.start_experiment(
        job["job_id"],
        run_id="run-resume",
        artifact_root=str(tmp_path),
    )
    service.record_checkpoint(
        job["job_id"],
        completed_steps=92,
        last_complete_round=91,
        checkpoint_uri=f"file://{tmp_path}",
        artifact_root=str(tmp_path),
    )
    service.mark_stopped(
        job["job_id"],
        completed_steps=92,
        last_complete_round=91,
        reason="manual stop",
    )

    resumed = service.resume_experiment(job["job_id"], target_total_steps=200)

    assert resumed["status"] == "queued"
    assert resumed["run_id"] == "run-resume"
    assert resumed["artifact_root"] == str(tmp_path)
    assert resumed["planned_total_steps"] == 200
    assert resumed["resume_context"]["last_complete_round"] == 91
    assert resumed["resume_context"]["completed_steps"] == 92


def test_archived_replay_prefers_recorded_success_params(tmp_path):
    action_path = tmp_path / "sales_action.json"
    result_path = tmp_path / "sales_result.json"
    action_path.write_text(json.dumps([{
        "action": {
            "action_name": "adjust_sales_demand",
            "action_param": {
                "product_id": "beer",
                "quantity": 70,
                "price": 520,
                "delivery_round": 2,
            },
        },
        "module_type": "SalesManager",
        "executor_id": "Manufacturer",
    }]), encoding="utf-8")
    result_path.write_text(json.dumps({
        "result": {
            "success": [{
                "success": True,
                "action_type": "adjust_sales_demand",
                "module_type": "SalesManager",
                "params": {
                    "product_id": "beer",
                    "quantity": 70,
                    "dry_run": False,
                },
            }]
        }
    }), encoding="utf-8")

    payload = StaticUtils._prepare_archived_action_payload(
        action_path,
        department="sales",
        enterprise_name="Manufacturer",
        round_id=1,
    )

    assert payload == [{
        "action": {
            "action_name": "adjust_sales_demand",
            "action_param": {"product_id": "beer", "quantity": 70},
        },
        "module_type": "SalesManager",
        "executor_id": "Manufacturer",
    }]


def test_resume_equivalence_ignores_id_offset_and_tiny_maintenance_drift():
    left = {
        "proposal_id": "proposal_000016",
        "sell_request_id": "implicit_sell_buy_000087",
        "total_maintenance_cost": 118.491086,
        "inventory": 1879.0,
    }
    right = {
        "proposal_id": "proposal_000141",
        "sell_request_id": "implicit_sell_buy_000212",
        "total_maintenance_cost": 115.662736,
        "inventory": 1879.0,
    }

    assert MultiEnterpriseClaudeManager._resume_values_equivalent(
        MultiEnterpriseClaudeManager._canonicalize_resume_identifiers(left),
        MultiEnterpriseClaudeManager._canonicalize_resume_identifiers(right),
    )
    right["inventory"] = 1878.0
    assert not MultiEnterpriseClaudeManager._resume_values_equivalent(
        MultiEnterpriseClaudeManager._canonicalize_resume_identifiers(left),
        MultiEnterpriseClaudeManager._canonicalize_resume_identifiers(right),
    )


def test_message_manager_checkpoint_rebuilds_runtime_lock():
    manager = MessageManager()
    manager.message_history.append({"id": "message-1"})

    restored = pickle.loads(pickle.dumps(manager))

    assert restored.message_history == [{"id": "message-1"}]
    assert restored.subscribers == {}
    with restored.lock:
        restored.message_queue.append({"id": "message-2"})


def test_exchange_id_counter_can_resume_without_duplicate_ids():
    original_next = get_next_id_counter_value()
    try:
        restore_next_id_counter_value(500)
        checkpoint_next = get_next_id_counter_value()
        first = next_id("proposal")
        restore_next_id_counter_value(checkpoint_next)
        replayed = next_id("proposal")
        assert checkpoint_next == 500
        assert first == replayed == "proposal_000500"
    finally:
        restore_next_id_counter_value(original_next)


def test_normal_operations_run_does_not_pass_resume_only_keyword(tmp_path):
    calls = []

    class _Manager:
        def run(
            self,
            *,
            max_step,
            checkpoint_callback,
            operations_job_id,
            operations_run_id,
            operations_repository,
        ):
            calls.append({
                "max_step": max_step,
                "job_id": operations_job_id,
                "run_id": operations_run_id,
            })
            return {
                "status": "completed",
                "completed_steps": max_step,
                "last_complete_round": max_step - 1,
            }

    runner = OperationsSimulationRunner(
        client_dir=tmp_path,
        workspace_dir=tmp_path / "runs",
        manager_factory=lambda context: _Manager(),
    )

    result = runner({
        "job_id": "job-normal",
        "run_id": "run-normal",
        "scenario_id": "single_case_01_order_selection",
        "planned_total_steps": 2,
        "created_at": "2026-08-07T00:00:00",
    }, lambda **kwargs: kwargs)

    assert calls == [{
        "max_step": 2,
        "job_id": "job-normal",
        "run_id": "run-normal",
    }]
    assert result["completed_steps"] == 2


def test_artifact_only_e1_run_can_be_registered_and_queued(tmp_path):
    repository = _MemoryRepository()
    service = OperationsService(repository)
    run_meta = {
        "run_id": "run-imported",
        "job_id": "job-imported",
        "scenario_id": "long_horizon_evolution",
        "scenario_config": {"runtime_injection": {}},
        "integration_profiles": {},
        "started_at": "2026-08-06T20:11:46+08:00",
        "status": "stopped",
    }

    queued = service.import_resumable_experiment(
        artifact_root=str(tmp_path),
        run_meta=run_meta,
        last_complete_round=91,
        target_total_steps=200,
    )

    assert queued["status"] == "queued"
    assert queued["run_id"] == "run-imported"
    assert queued["resume_context"]["last_complete_round"] == 91
    assert repository.get_run("run-imported")["status"] == "queued"


def test_e1_resume_forces_fresh_analysis_on_first_resumed_round():
    patched = OperationsSimulationRunner._apply_e1_resume_runtime_compatibility(
        {
            "runtime_injection": {
                "analyst_policy": {
                    "full_analysis_interval_rounds": 5,
                    "force_on_rounds": [0, 40, 80, 120, 160],
                },
                "long_run_experiment_policy": {"enabled": True},
            },
        },
        resume_round=92,
    )

    assert patched["runtime_injection"]["analyst_policy"]["force_on_rounds"] == [
        0,
        40,
        80,
        92,
        120,
        160,
    ]
    assert patched["resume_compatibility"]["analyst_forced_on_resume_round"] == 92
    assert patched["runtime_injection"]["long_run_experiment_policy"][
        "agent_timeout_circuit_breaker"
    ]["enabled"] is True
    assert patched["resume_compatibility"][
        "agent_timeout_circuit_breaker_applied"
    ] is True


def _write_timeout_audit(day_dir, *, phase="decision", timed_out=True):
    day_dir.mkdir(parents=True, exist_ok=True)
    audit_name = (
        "trade_skill_execution_audit.json"
        if phase == "trade"
        else "skill_execution_audit.json"
    )
    raw_name = (
        "trade_skill_raw_messages.json"
        if phase == "trade"
        else "skill_raw_messages.json"
    )
    (day_dir / audit_name).write_text(
        json.dumps({
            "attempts": 2,
            "success": True,
            "fallback_used": timed_out,
        }),
        encoding="utf-8",
    )
    messages = (
        [
            {"content": "[Timeout] retry=0"},
            {"content": "[Timeout] retry=1"},
        ]
        if timed_out
        else [{"content": "Agent produced a valid action"}]
    )
    (day_dir / raw_name).write_text(json.dumps(messages), encoding="utf-8")


def test_agent_timeout_round_health_requires_every_expected_call_to_timeout(tmp_path):
    manager = MultiEnterpriseClaudeManager.__new__(MultiEnterpriseClaudeManager)
    manager.workspace_dir = tmp_path
    manager.runtimes = {}
    manager.enterprise_specs = {
        "Supplier": SimpleNamespace(
            enterprise_id="Supplier",
            enterprise_name="Supplier",
            departments=[
                SimpleNamespace(
                    dept_id="procurement",
                    enabled=True,
                    need_trade=True,
                ),
                SimpleNamespace(
                    dept_id="inventory",
                    enabled=True,
                    need_trade=False,
                ),
            ],
        )
    }
    procurement_day = (
        tmp_path / "enterprises" / "Supplier" / "department" / "procurement" / "day10"
    )
    inventory_day = (
        tmp_path / "enterprises" / "Supplier" / "department" / "inventory" / "day10"
    )
    _write_timeout_audit(procurement_day, phase="decision")
    _write_timeout_audit(procurement_day, phase="trade")
    _write_timeout_audit(inventory_day, phase="decision")

    policy = {
        "include_trade_phase": True,
        "minimum_expected_agent_calls": 3,
    }
    all_timeout = manager._build_agent_timeout_round_health(10, policy)

    assert all_timeout["expected_agent_calls"] == 3
    assert all_timeout["timeout_exhausted_calls"] == 3
    assert all_timeout["all_agent_calls_timed_out"] is True

    _write_timeout_audit(inventory_day, phase="decision", timed_out=False)
    mixed = manager._build_agent_timeout_round_health(10, policy)

    assert mixed["timeout_exhausted_calls"] == 2
    assert mixed["non_timeout_calls"] == 1
    assert mixed["all_agent_calls_timed_out"] is False


def test_last_sealed_round_requires_all_enterprises_and_exchange(tmp_path):
    run_meta = {"enterprise_ids": ["Supplier", "Manufacturer"]}
    for round_id in (90, 91):
        observer = tmp_path / "public" / "observer_state" / f"day{round_id}" / "end_of_day"
        exchange = tmp_path / "public" / "exchange" / f"day{round_id}" / "end_of_day"
        observer.mkdir(parents=True)
        exchange.mkdir(parents=True)
        (observer / "Supplier.json").write_text("{}", encoding="utf-8")
        (exchange / "exchange.json").write_text("{}", encoding="utf-8")
    (tmp_path / "public" / "observer_state" / "day90" / "end_of_day" / "Manufacturer.json").write_text(
        "{}",
        encoding="utf-8",
    )

    assert _last_sealed_round_from_artifact(tmp_path, run_meta) == 90


def test_partial_post_checkpoint_turn_is_quarantined(tmp_path):
    complete = tmp_path / "enterprises" / "Supplier" / "department" / "sales" / "day91"
    partial = tmp_path / "enterprises" / "Supplier" / "department" / "sales" / "day92"
    integrity = tmp_path / "round_integrity" / "day92.json"
    complete.mkdir(parents=True)
    partial.mkdir(parents=True)
    integrity.parent.mkdir(parents=True)
    (complete / "sales_action.json").write_text("[]", encoding="utf-8")
    (partial / "sales_action.json").write_text("[]", encoding="utf-8")
    integrity.write_text("{}", encoding="utf-8")

    moved = MultiEnterpriseClaudeManager._quarantine_incomplete_resume_artifacts(
        tmp_path,
        91,
    )

    assert moved == 2
    assert complete.exists()
    assert not partial.exists()
    assert not integrity.exists()
    quarantine = tmp_path / "_resume_incomplete_attempts"
    assert len(list(quarantine.rglob("day92"))) == 1
    assert len(list(quarantine.rglob("day92.json"))) == 1
