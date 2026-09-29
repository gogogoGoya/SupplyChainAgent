import json
from pathlib import Path

from config.integration_profiles import resolve_integration_profiles
from core.skill_protocol import (
    adapt_legacy_actions,
    audit_context_files,
    audit_policy_context,
    filter_policy_context,
)


def _read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def test_scenario_policy_allowlist_rejects_inactive_or_wrong_department_fields():
    context = {
        "active_modes": {
            "cobweb": False,
            "shared_resource": True,
            "herding": True,
        },
        "relevant_policies": {
            "cobweb_model": {"enabled": True},
            "shared_resource": {"enabled": True},
            "herding_signal": {"enabled": True},
            "staffing_relaxation_policy": {"enabled": False},
        },
    }

    audit = audit_policy_context(context, "hr")
    filtered = filter_policy_context(context, "hr")

    assert audit.disallowed_policy_names == [
        "cobweb_model",
        "herding_signal",
        "shared_resource",
    ]
    assert set(filtered["relevant_policies"]) == {
        "staffing_relaxation_policy"
    }


def test_context_audit_checks_state_blackboard_and_trade_card(tmp_path):
    state_path = tmp_path / "sales.json"
    blackboard_path = tmp_path / "blackboard.json"
    trade_path = tmp_path / "trade_decision_card.json"
    state_path.write_text(
        json.dumps(
            {
                "policy_context": {
                    "active_modes": {"herding": True},
                    "relevant_policies": {"herding_signal": {}},
                }
            }
        ),
        encoding="utf-8",
    )
    blackboard_path.write_text(
        json.dumps(
            {
                "policy_context_by_department": {
                    "sales": {
                        "active_modes": {"cobweb": False},
                        "relevant_policies": {"cobweb_model": {}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    trade_path.write_text(
        json.dumps({"policy_context": {}}),
        encoding="utf-8",
    )

    audit = audit_context_files(
        department="sales",
        state_path=str(state_path),
        blackboard_path=str(blackboard_path),
        trade_decision_card_path=str(trade_path),
        read_json=_read_json,
    )

    assert audit.visible_policy_names == ["cobweb_model", "herding_signal"]
    assert audit.disallowed_policy_names == ["cobweb_model"]
    assert audit.missing_files == []


def test_legacy_action_adapter_preserves_actions_and_evidence():
    actions = [
        {
            "action": {
                "action_name": "develop_market",
                "action_param": {"market_type": "regional"},
            },
            "module_type": "SalesManager",
            "executor_id": "Retailer",
            "action_reason": "Demand is below target.",
            "evidence_ref": "sales.available_orders",
        }
    ]

    envelope = adapt_legacy_actions(
        run_id="run-1",
        enterprise_id="Retailer",
        department="sales",
        day=2,
        actions=actions,
        output_file="/tmp/sales_action.json",
    ).to_dict()

    assert envelope["status"] == "ok"
    assert envelope["actions"] == actions
    assert envelope["evidence_refs"] == ["sales.available_orders"]


def test_fallback_adapter_records_fallback_without_executable_actions():
    envelope = adapt_legacy_actions(
        run_id="run-1",
        enterprise_id="Retailer",
        department="sales",
        day=2,
        actions=[
            {
                "action": {
                    "action_name": "action_pass",
                    "action_param": "fallback",
                },
                "action_reason": "fallback",
                "module_type": "SalesManager",
                "executor_id": "Retailer",
            }
        ],
        output_file="/tmp/sales_action.json",
        fallback_used=True,
    ).to_dict()

    assert envelope["status"] == "fallback"
    assert envelope["actions"] == []
    assert envelope["warnings"]


def test_skill_audit_is_enabled_without_enabling_strict_validation():
    profile = resolve_integration_profiles({})
    skill = profile["capabilities"]["skill"]

    assert skill["audit_enabled"] is True
    assert skill["context_validation"] == "off"
    assert skill["output_validation"] == "off"
    assert skill["max_retries"] == 3
