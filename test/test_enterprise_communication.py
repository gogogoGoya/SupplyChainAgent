import json
from pathlib import Path

from coordination.communication_protocol import (
    deduplicate_entries,
    validate_communications,
)
from coordination.enterprise_communication import (
    EnterpriseCommunicationCoordinator,
)


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_dynamic_structural_validation_and_deduplication():
    result = validate_communications(
        source_department="sales",
        payload={
            "messages": [
                {
                    "to_department": "production",
                    "message": "Demand increased.",
                    "topic": "demand_signal",
                    "priority": "high",
                    "evidence_refs": ["sales.orders"],
                    "round_id": 2,
                },
                {
                    "to_department": "production",
                    "message": "Demand increased.",
                    "topic": "demand_signal",
                    "priority": "high",
                    "evidence_refs": ["sales.orders"],
                    "round_id": 2,
                },
            ]
        },
        enabled_departments={"sales", "production", "finance"},
        round_id=2,
        mode="warn",
    )
    unique, duplicates = deduplicate_entries(result.entries)

    assert result.ok is True
    assert result.issues == []
    assert len(unique) == 1
    assert len(duplicates) == 1


def test_strict_validation_rejects_unknown_self_and_cross_enterprise_targets():
    result = validate_communications(
        source_department="sales",
        payload={
            "messages": [
                {"to_department": "sales", "message": "self"},
                {"to_department": "OtherEnterprise:production", "message": "cross"},
                {"to_department": "legal", "message": "unknown"},
            ]
        },
        enabled_departments={"sales", "production"},
        round_id=0,
        mode="strict",
    )

    assert result.ok is False
    assert {item["code"] for item in result.issues} == {
        "self_route",
        "invalid_target",
    }


def test_coordinator_extends_existing_blackboard_and_skill_audit(tmp_path):
    workspace = tmp_path / "Enterprise_A"
    blackboard_path = (
        workspace / "department" / "blackboard" / "day0" / "blackboard.json"
    )
    _write_json(
        blackboard_path,
        {
            "round_id": 0,
            "departments": {"sales": {}, "production": {}},
        },
    )
    sales_dir = workspace / "department" / "sales" / "day0"
    _write_json(
        sales_dir / "sales_communication.json",
        {
            "messages": [
                {
                    "to_department": "production",
                    "message": "Prepare for confirmed demand.",
                    "topic": "demand_signal",
                    "priority": "high",
                    "evidence_refs": ["sales.available_orders"],
                    "round_id": 0,
                }
            ]
        },
    )
    _write_json(
        sales_dir / "skill_execution_audit.json",
        {"success": True},
    )

    report = EnterpriseCommunicationCoordinator(
        enterprise_workspace=workspace,
        enabled_departments={"sales", "production", "hr"},
        source_departments={"sales"},
        validation_mode="strict",
    ).merge_round(0)
    blackboard = json.loads(blackboard_path.read_text(encoding="utf-8"))
    skill_audit = json.loads(
        (sales_dir / "skill_execution_audit.json").read_text(encoding="utf-8")
    )

    assert report["ok"] is True
    assert report["entry_count"] == 1
    assert blackboard["departments"] == {"sales": {}, "production": {}}
    assert blackboard["coordination"]["entries_by_target"]["production"]
    assert skill_audit["communication_validation"]["ok"] is True


def test_strict_coordinator_reports_missing_agent_sidecar(tmp_path):
    workspace = tmp_path / "Enterprise_A"
    _write_json(
        workspace / "department" / "blackboard" / "day0" / "blackboard.json",
        {"round_id": 0},
    )

    report = EnterpriseCommunicationCoordinator(
        enterprise_workspace=workspace,
        enabled_departments={"sales", "production"},
        source_departments={"sales"},
        validation_mode="strict",
    ).merge_round(0)

    assert report["ok"] is False
    assert report["missing_sidecars"] == ["sales"]


def test_coordinator_restores_sidecar_after_blackboard_refresh(tmp_path):
    workspace = tmp_path / "Enterprise_A"
    blackboard_path = (
        workspace / "department" / "blackboard" / "day0" / "blackboard.json"
    )
    communication_path = (
        workspace
        / "department"
        / "sales"
        / "day0"
        / "sales_communication.json"
    )
    _write_json(blackboard_path, {"round_id": 0, "snapshot": "decision"})
    _write_json(
        communication_path,
        {
            "messages": [
                {
                    "to_department": "production",
                    "message": "Use the confirmed demand signal.",
                    "round_id": 0,
                }
            ]
        },
    )
    coordinator = EnterpriseCommunicationCoordinator(
        enterprise_workspace=workspace,
        enabled_departments={"sales", "production"},
        source_departments={"sales"},
        validation_mode="warn",
    )
    coordinator.merge_round(0)

    _write_json(blackboard_path, {"round_id": 0, "snapshot": "trade"})
    report = coordinator.merge_round(0)
    blackboard = json.loads(blackboard_path.read_text(encoding="utf-8"))

    assert report["entry_count"] == 1
    assert blackboard["snapshot"] == "trade"
    assert blackboard["coordination"]["entries"][0]["to_department"] == "production"

    repeated_report = coordinator.merge_round(0)
    assert repeated_report["base_snapshot_hash"] == report["base_snapshot_hash"]
    assert repeated_report["coordination_hash"] == report["coordination_hash"]


def test_strict_semantic_rule_pack_fails_and_updates_skill_audit(tmp_path):
    workspace = tmp_path / "Enterprise_A"
    _write_json(
        workspace / "department" / "blackboard" / "day0" / "blackboard.json",
        {"round_id": 0},
    )
    sales_dir = workspace / "department" / "sales" / "day0"
    _write_json(
        sales_dir / "sales_communication.json",
        {
            "messages": [
                {
                    "to_department": "production",
                    "message": "Execute build_production_line immediately.",
                    "topic": "demand_signal",
                    "round_id": 0,
                }
            ]
        },
    )
    _write_json(sales_dir / "skill_execution_audit.json", {"success": True})

    report = EnterpriseCommunicationCoordinator(
        enterprise_workspace=workspace,
        enabled_departments={"sales", "production"},
        source_departments={"sales"},
        validation_mode="strict",
        semantic_rule_pack="single_enterprise_case_v1",
    ).merge_round(0)
    audit = json.loads(
        (sales_dir / "skill_execution_audit.json").read_text(encoding="utf-8")
    )

    assert report["ok"] is False
    assert report["entry_count"] == 0
    assert report["semantic_rule_pack"] == "single_enterprise_case_v1"
    assert audit["communication_validation"]["ok"] is False
    assert audit["communication_validation"]["semantic_issues"][0]["code"] == (
        "cross_function_override"
    )


def test_warn_semantic_rule_pack_records_issue_without_failing_merge(tmp_path):
    workspace = tmp_path / "Enterprise_A"
    _write_json(
        workspace / "department" / "blackboard" / "day0" / "blackboard.json",
        {"round_id": 0},
    )
    _write_json(
        workspace
        / "department"
        / "sales"
        / "day0"
        / "sales_communication.json",
        {
            "messages": [
                {
                    "to_department": "production",
                    "message": "Execute build_production_line immediately.",
                    "topic": "demand_signal",
                    "round_id": 0,
                }
            ]
        },
    )

    report = EnterpriseCommunicationCoordinator(
        enterprise_workspace=workspace,
        enabled_departments={"sales", "production"},
        source_departments={"sales"},
        validation_mode="warn",
        semantic_rule_pack="single_enterprise_case_v1",
    ).merge_round(0)

    assert report["ok"] is True
    assert report["issue_count"] == 1
    assert report["entry_count"] == 1
