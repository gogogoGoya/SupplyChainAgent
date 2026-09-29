from coordination.communication_protocol import CommunicationEntry
from coordination.semantic_rule_packs import (
    NO_SEMANTIC_RULE_PACK,
    SINGLE_ENTERPRISE_CASE_RULE_PACK,
    apply_semantic_rules,
    describe_source_routes,
)


def _entry(**overrides):
    payload = {
        "source_department": "sales",
        "to_department": "production",
        "message": "Demand has increased; please review production capacity.",
        "topic": "demand_signal",
        "priority": "high",
        "evidence_refs": ["sales.available_orders"],
        "round_id": 1,
    }
    payload.update(overrides)
    return CommunicationEntry(**payload)


def test_single_enterprise_rule_pack_accepts_valid_route_topic():
    entries, issues, repairs = apply_semantic_rules(
        entries=[_entry()],
        rule_pack_id=SINGLE_ENTERPRISE_CASE_RULE_PACK,
    )

    assert entries[0].topic == "demand_signal"
    assert issues == []
    assert repairs == []


def test_no_rule_pack_preserves_dynamic_multi_enterprise_message():
    entry = _entry(
        to_department="custom_operations",
        topic="custom_signal",
    )
    entries, issues, repairs = apply_semantic_rules(
        entries=[entry],
        rule_pack_id=NO_SEMANTIC_RULE_PACK,
    )

    assert entries == [entry]
    assert issues == []
    assert repairs == []


def test_rule_pack_rejects_invalid_topic_and_cross_function_action_name():
    _, issues, repairs = apply_semantic_rules(
        entries=[
            _entry(
                topic="material_budget",
                message="Demand increased. Execute build_production_line now.",
            )
        ],
        rule_pack_id=SINGLE_ENTERPRISE_CASE_RULE_PACK,
        auto_repair=False,
    )

    assert {item["code"] for item in issues} == {
        "invalid_topic",
        "cross_function_override",
    }
    assert repairs == []


def test_explicit_auto_repair_is_audited_and_not_silent():
    entries, issues, repairs = apply_semantic_rules(
        entries=[
            _entry(
                topic="capacity_allocation",
                message="Please build production line for confirmed demand.",
            )
        ],
        rule_pack_id=SINGLE_ENTERPRISE_CASE_RULE_PACK,
        auto_repair=True,
    )

    assert issues == []
    assert entries[0].topic == "production_planning"
    assert "review capacity expansion" in entries[0].message
    assert {item["code"] for item in repairs} == {
        "canonicalized_topic",
        "softened_cross_function_command",
    }


def test_prompt_route_description_is_scoped_to_source_department():
    description = describe_source_routes(
        SINGLE_ENTERPRISE_CASE_RULE_PACK,
        "procurement",
    )

    assert "production=[material_supply]" in description
    assert "sales=[delivery_alignment,supply_risk]" in description
    assert "procurement=" not in description


def test_strict_pack_does_not_silently_accept_custom_department_routes():
    _, issues, _ = apply_semantic_rules(
        entries=[
            _entry(
                to_department="legal",
                topic="risk_review",
            )
        ],
        rule_pack_id=SINGLE_ENTERPRISE_CASE_RULE_PACK,
    )

    assert issues[0]["code"] == "unsupported_semantic_route"
