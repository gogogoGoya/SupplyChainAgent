import json
from pathlib import Path

import multi_tenant_utils
from multi_tenant_utils import MultiTenantUtils


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_pass_action(department):
    return [
        {
            "action": {
                "action_name": "action_pass",
                "action_param": {},
            },
            "module_type": department,
            "executor_id": f"{department}_manager",
            "action_reason": "No action is required for this contract fixture.",
        }
    ]


def _configure_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace_multi"
    enterprise_dir = workspace / "enterprises"
    monkeypatch.setattr(multi_tenant_utils, "WORKSPACE", workspace)
    monkeypatch.setattr(multi_tenant_utils.Config, "ENTERPRISE_DIR", enterprise_dir)
    monkeypatch.setattr(
        multi_tenant_utils.Config, "ENTERPRISE_IDS", ["Enterprise_A"]
    )
    _write_json(
        workspace / "run_meta.json",
        {
            "scenario_config": {
                "simulation": {"market_demand_mode": "beer_game"},
                "enterprise_configs": [
                    {
                        "id": "Enterprise_A",
                        "enabled_functions": ["sales", "finance"],
                    }
                ],
            }
        },
    )
    return workspace, enterprise_dir


def test_round_integrity_accepts_archive_analysis_and_pre_trade_action(
    monkeypatch, tmp_path
):
    workspace, enterprise_dir = _configure_workspace(monkeypatch, tmp_path)
    _write_json(
        enterprise_dir / "Enterprise_A" / "records" / "day0" / "analysis.json",
        {"summary": "valid"},
    )
    _write_json(
        enterprise_dir
        / "Enterprise_A"
        / "department"
        / "sales"
        / "day0"
        / "pre_sales_action.json",
        _valid_pass_action("sales"),
    )

    report_path = Path(MultiTenantUtils.write_round_integrity_summary(0))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report_path == workspace / "round_integrity" / "day0.json"
    assert report["ok"] is True
    assert report["totals"]["analysis_valid"] == 1
    assert report["totals"]["action_valid"] == 1
    assert report["totals"]["action_expected"] == 1


def test_round_integrity_rejects_missing_department_output(monkeypatch, tmp_path):
    _, enterprise_dir = _configure_workspace(monkeypatch, tmp_path)
    _write_json(
        enterprise_dir / "Enterprise_A" / "records" / "day0" / "analysis.json",
        {"summary": "valid"},
    )

    report_path = Path(MultiTenantUtils.write_round_integrity_summary(0))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["ok"] is False
    assert report["totals"]["action_missing"] == 1


def test_round_integrity_requires_agent_audit_when_profile_enables_it(
    monkeypatch, tmp_path
):
    workspace, enterprise_dir = _configure_workspace(monkeypatch, tmp_path)
    run_meta_path = workspace / "run_meta.json"
    run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    run_meta["integration_profiles"] = {
        "capabilities": {
            "skill": {
                "audit_enabled": True,
            }
        }
    }
    run_meta["scenario_config"]["enterprise_configs"][0]["agent_departments"] = [
        {
            "dept_id": "sales",
            "type": "Agent",
        }
    ]
    _write_json(run_meta_path, run_meta)
    _write_json(
        enterprise_dir / "Enterprise_A" / "records" / "day0" / "analysis.json",
        {"summary": "valid"},
    )
    day_dir = (
        enterprise_dir
        / "Enterprise_A"
        / "department"
        / "sales"
        / "day0"
    )
    _write_json(
        day_dir / "sales_action.json",
        _valid_pass_action("sales"),
    )

    missing_report = json.loads(
        Path(MultiTenantUtils.write_round_integrity_summary(0)).read_text(
            encoding="utf-8"
        )
    )
    assert missing_report["ok"] is False
    assert missing_report["totals"]["skill_audit_missing"] == 1

    _write_json(day_dir / "skill_execution_audit.json", {"success": True})
    valid_report = json.loads(
        Path(MultiTenantUtils.write_round_integrity_summary(0)).read_text(
            encoding="utf-8"
        )
    )
    assert valid_report["ok"] is True
    assert valid_report["totals"]["skill_audit_valid"] == 1


def test_round_integrity_requires_decision_and_trade_audits_for_trade_agents(
    monkeypatch, tmp_path
):
    workspace, enterprise_dir = _configure_workspace(monkeypatch, tmp_path)
    run_meta_path = workspace / "run_meta.json"
    run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    run_meta["integration_profiles"] = {
        "capabilities": {"skill": {"audit_enabled": True}}
    }
    run_meta["scenario_config"]["enterprise_configs"][0]["agent_departments"] = [
        {
            "dept_id": "sales",
            "type": "Agent",
            "need_trade": True,
        }
    ]
    _write_json(run_meta_path, run_meta)
    _write_json(
        enterprise_dir / "Enterprise_A" / "records" / "day0" / "analysis.json",
        {"summary": "valid"},
    )
    day_dir = (
        enterprise_dir
        / "Enterprise_A"
        / "department"
        / "sales"
        / "day0"
    )
    _write_json(day_dir / "sales_action.json", _valid_pass_action("sales"))
    _write_json(day_dir / "skill_execution_audit.json", {"success": True})

    missing_trade = json.loads(
        Path(MultiTenantUtils.write_round_integrity_summary(0)).read_text(
            encoding="utf-8"
        )
    )
    assert missing_trade["totals"]["skill_audit_expected"] == 2
    assert missing_trade["totals"]["skill_audit_missing"] == 1

    _write_json(
        day_dir / "trade_skill_execution_audit.json",
        {"success": True},
    )
    complete = json.loads(
        Path(MultiTenantUtils.write_round_integrity_summary(0)).read_text(
            encoding="utf-8"
        )
    )
    assert complete["ok"] is True
    assert complete["totals"]["skill_audit_valid"] == 2


def test_cobweb_agent_integrity_rejects_current_and_prior_skill_fallbacks(
    monkeypatch,
    tmp_path,
):
    workspace, enterprise_dir = _configure_workspace(monkeypatch, tmp_path)
    run_meta_path = workspace / "run_meta.json"
    run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    run_meta["experiment_design"] = {"experiment_group": "C2"}
    run_meta["integration_profiles"] = {
        "capabilities": {"skill": {"audit_enabled": True}}
    }
    run_meta["scenario_config"].update({
        "simulation": {
            "market_demand_mode": "cobweb",
            "cobweb_config": {
                "enabled": True,
                "production_response_mode": "agent_endogenous",
            },
        },
        "runtime_injection": {
            "scripted_rule_policy": {"enabled": False},
        },
        "experiment_design": {"experiment_group": "C2"},
        "enterprise_configs": [{
            "id": "Enterprise_A",
            "enabled_functions": ["production"],
        }],
        "agent_enterprise_layout": [{
            "enterprise_id": "Enterprise_A",
            "departments": [{
                "dept_id": "production",
                "type": "Agent",
            }],
        }],
    })
    _write_json(run_meta_path, run_meta)

    for day, fallback_used in ((0, True), (1, False)):
        _write_json(
            enterprise_dir
            / "Enterprise_A"
            / "records"
            / f"day{day}"
            / "analysis.json",
            {"summary": "valid"},
        )
        day_dir = (
            enterprise_dir
            / "Enterprise_A"
            / "department"
            / "production"
            / f"day{day}"
        )
        _write_json(
            day_dir / "production_action.json",
            _valid_pass_action("production"),
        )
        _write_json(
            day_dir / "skill_execution_audit.json",
            {
                "success": True,
                "fallback_used": fallback_used,
            },
        )

    day0_report = json.loads(
        Path(MultiTenantUtils.write_round_integrity_summary(0)).read_text(
            encoding="utf-8"
        )
    )
    assert day0_report["ok"] is False
    assert day0_report["totals"]["skill_audit_expected"] == 1
    assert day0_report["totals"]["skill_audit_fallback"] == 1
    assert (
        day0_report["totals"][
            "cobweb_agent_execution_failures_cumulative"
        ]
        == 1
    )

    day1_report = json.loads(
        Path(MultiTenantUtils.write_round_integrity_summary(1)).read_text(
            encoding="utf-8"
        )
    )
    assert day1_report["totals"]["skill_audit_fallback"] == 0
    assert (
        day1_report["totals"][
            "cobweb_agent_execution_failures_cumulative"
        ]
        == 1
    )
    assert day1_report["ok"] is False
    assert day1_report["cobweb_agent_quality"]["strict_gate_enabled"] is True


def test_round_integrity_requires_coordination_report_when_enabled(
    monkeypatch, tmp_path
):
    workspace, enterprise_dir = _configure_workspace(monkeypatch, tmp_path)
    run_meta_path = workspace / "run_meta.json"
    run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    run_meta["integration_profiles"] = {
        "capabilities": {
            "coordination": {
                "blackboard_enabled": True,
                "communication_validation": "strict",
            }
        }
    }
    _write_json(run_meta_path, run_meta)
    _write_json(
        enterprise_dir / "Enterprise_A" / "records" / "day0" / "analysis.json",
        {"summary": "valid"},
    )
    _write_json(
        enterprise_dir
        / "Enterprise_A"
        / "department"
        / "sales"
        / "day0"
        / "sales_action.json",
        _valid_pass_action("sales"),
    )

    missing = json.loads(
        Path(MultiTenantUtils.write_round_integrity_summary(0)).read_text(
            encoding="utf-8"
        )
    )
    assert missing["ok"] is False
    assert missing["totals"]["coordination_report_missing"] == 1

    _write_json(
        enterprise_dir
        / "Enterprise_A"
        / "department"
        / "blackboard"
        / "day0"
        / "communication_merge_report.json",
        {"ok": True},
    )
    complete = json.loads(
        Path(MultiTenantUtils.write_round_integrity_summary(0)).read_text(
            encoding="utf-8"
        )
    )
    assert complete["ok"] is True
    assert complete["totals"]["coordination_report_valid"] == 1
