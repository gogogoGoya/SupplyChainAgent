"""Pure evaluation helpers for single-enterprise diagnostic cases."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

from config.simulation_preset_config import (
    SINGLE_ENTERPRISE_CASE_IDS,
    get_single_enterprise_case_config,
)


def _iter_actions(action_records: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    for record in action_records:
        payload = record.get("actions", record)
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield item
        elif isinstance(payload, dict):
            yield payload


def _action_name(item: Dict[str, Any]) -> str:
    action = item.get("action")
    if isinstance(action, dict):
        return str(action.get("action_name") or "")
    return str(item.get("action_name") or "")


def _record_failed(record: Dict[str, Any]) -> bool:
    return bool(record.get("execution_failed"))


def build_case_gold_snapshot(case_id: str) -> Dict[str, Any]:
    scenario = get_single_enterprise_case_config(case_id)
    policy = scenario["single_enterprise_case"]
    return {
        "schema_version": "single_case_gold.v1",
        "case_id": case_id,
        "primary_issue": policy["primary_issue"],
        "expected_primary_departments": list(policy["expected_primary_departments"]),
        "preferred_actions": list(policy["preferred_actions"]),
        "discouraged_actions": list(policy["discouraged_actions"]),
        "recommended_total_steps": policy.get(
            "recommended_total_steps",
            scenario["simulation"]["agent_run_steps"],
        ),
        "diagnostic_evaluation_rounds": list(policy.get("diagnostic_evaluation_rounds", [0])),
        "evaluation_mode": policy.get("evaluation_mode", "diagnostic_window"),
        "evidence_focus": list(policy.get("evidence_focus") or []),
        "trajectory_success_signals": dict(policy.get("trajectory_success_signals") or {}),
        "minimum_observation_rounds": min(3, scenario["simulation"]["agent_run_steps"]),
        "agent_run_steps": scenario["simulation"]["agent_run_steps"],
    }


def build_all_case_gold_snapshots() -> List[Dict[str, Any]]:
    return [build_case_gold_snapshot(case_id) for case_id in SINGLE_ENTERPRISE_CASE_IDS]


def evaluate_case_action_records(
    case_id: str,
    action_records_by_department: Dict[str, List[Dict[str, Any]]],
    *,
    allow_stable_noop_round: bool = False,
    stable_noop_reason: str = "",
) -> Dict[str, Any]:
    gold = build_case_gold_snapshot(case_id)
    expected_departments: Set[str] = set(gold["expected_primary_departments"])
    preferred_actions: Set[str] = set(gold["preferred_actions"])
    discouraged_actions: Set[str] = set(gold["discouraged_actions"])

    preferred_hits: List[Dict[str, Any]] = []
    preferred_primary_hits: List[Dict[str, Any]] = []
    discouraged_hits: List[Dict[str, Any]] = []
    primary_department_action_count = 0
    execution_failed_departments: List[str] = []
    total_action_count = 0

    for department, records in action_records_by_department.items():
        if any(_record_failed(record) for record in records):
            execution_failed_departments.append(department)
        for item in _iter_actions(records):
            name = _action_name(item)
            if not name:
                continue
            total_action_count += 1
            if department in expected_departments and name != "action_pass":
                primary_department_action_count += 1
            hit = {"department": department, "action_name": name}
            if name in preferred_actions:
                preferred_hits.append(hit)
                if department in expected_departments and name != "action_pass":
                    preferred_primary_hits.append(hit)
            if name in discouraged_actions:
                discouraged_hits.append(hit)

    required_preferred_actions = preferred_actions - {"action_pass"}
    if required_preferred_actions and expected_departments:
        required_satisfied = any(
            hit["action_name"] in required_preferred_actions
            for hit in preferred_primary_hits
        ) or primary_department_action_count > 0
    elif required_preferred_actions:
        # Cases without a primary department can intentionally model conservative
        # operation, where action_pass is the primary acceptable action and
        # other non-pass actions are only secondary acceptable alternatives.
        required_satisfied = bool(preferred_hits)
    else:
        required_satisfied = bool(preferred_hits) or total_action_count > 0

    relaxed_stable_noop = (
        allow_stable_noop_round
        and total_action_count > 0
        and not execution_failed_departments
        and not required_satisfied
    )
    passed = (
        total_action_count > 0
        and not execution_failed_departments
        and (required_satisfied or relaxed_stable_noop)
    )
    return {
        "schema_version": "single_case_evaluation.v1",
        "case_id": case_id,
        "primary_issue": gold["primary_issue"],
        "passed": passed,
        "evaluation_contract": "state_driven_actions_v2",
        "discouraged_actions_are_legacy_warnings": True,
        "preferred_hit_count": len(preferred_hits),
        "preferred_primary_hit_count": len(preferred_primary_hits),
        "discouraged_hit_count": len(discouraged_hits),
        "execution_failed_count": len(execution_failed_departments),
        "primary_department_action_count": primary_department_action_count,
        "total_action_count": total_action_count,
        "relaxed_stable_noop": relaxed_stable_noop,
        "stable_noop_reason": stable_noop_reason if relaxed_stable_noop else "",
        "preferred_hits": preferred_hits,
        "preferred_primary_hits": preferred_primary_hits,
        "discouraged_hits": discouraged_hits,
        "execution_failed_departments": execution_failed_departments,
    }
