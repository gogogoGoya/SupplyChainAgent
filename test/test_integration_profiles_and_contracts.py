import pytest

from config.integration_profiles import (
    DEFAULT_INTEGRATION_PROFILES,
    get_scenario_integration_profiles,
    resolve_integration_profiles,
)
from core.integration_contracts import (
    AgentOutputEnvelope,
    MetricRecord,
    SimulationEvent,
)


def test_legacy_scenarios_resolve_to_behavior_preserving_profiles():
    profiles = get_scenario_integration_profiles("beer_game")

    assert profiles == DEFAULT_INTEGRATION_PROFILES
    assert profiles["simulation"]["profile"] == "multi_enterprise"
    assert profiles["infrastructure"]["storage"]["profile"] == "postgres_mirror"
    assert profiles["infrastructure"]["operations"]["enabled"] is True
    assert profiles["capabilities"]["coordination"]["blackboard_enabled"] is False


def test_profile_overrides_are_deep_merged_without_mutating_defaults():
    profiles = resolve_integration_profiles(
        {
            "integration_profiles": {
                "simulation": {"profile": "single_enterprise"},
                "capabilities": {
                    "analysis": {"profile": "historical_diagnosis"},
                    "coordination": {
                        "blackboard_enabled": True,
                        "two_phase_enabled": True,
                        "communication_validation": "strict",
                    },
                },
            }
        }
    )

    assert profiles["simulation"]["profile"] == "single_enterprise"
    assert profiles["capabilities"]["analysis"]["history_days"] == 5
    assert profiles["capabilities"]["coordination"]["two_phase_enabled"] is True
    assert DEFAULT_INTEGRATION_PROFILES["simulation"]["profile"] == "multi_enterprise"


def test_invalid_profile_combinations_fail_explicitly():
    with pytest.raises(ValueError, match="requires blackboard"):
        resolve_integration_profiles(
            {
                "integration_profiles": {
                    "capabilities": {
                        "coordination": {"two_phase_enabled": True}
                    }
                }
            }
        )

    with pytest.raises(ValueError, match="postgres_authoritative"):
        resolve_integration_profiles(
            {
                "integration_profiles": {
                    "infrastructure": {
                        "storage": {"profile": "postgres_authoritative"},
                        "operations": {"enabled": False},
                    }
                }
            }
        )

    with pytest.raises(ValueError, match="single_enterprise"):
        resolve_integration_profiles(
            {
                "integration_profiles": {
                    "capabilities": {
                        "coordination": {
                            "blackboard_enabled": True,
                            "communication_validation": "strict",
                            "semantic_rule_pack": "single_enterprise_case_v1",
                        }
                    }
                }
            }
        )


def test_single_enterprise_semantic_rule_pack_requires_explicit_coordination():
    profiles = resolve_integration_profiles(
        {
            "integration_profiles": {
                "simulation": {"profile": "single_enterprise"},
                "capabilities": {
                    "coordination": {
                        "blackboard_enabled": True,
                        "communication_validation": "strict",
                        "semantic_rule_pack": "single_enterprise_case_v1",
                        "semantic_auto_repair": False,
                    }
                },
            }
        }
    )

    assert (
        profiles["capabilities"]["coordination"]["semantic_rule_pack"]
        == "single_enterprise_case_v1"
    )
    assert profiles["capabilities"]["coordination"]["semantic_auto_repair"] is False

    with pytest.raises(ValueError, match="communication_validation"):
        resolve_integration_profiles(
            {
                "integration_profiles": {
                    "simulation": {"profile": "single_enterprise"},
                    "capabilities": {
                        "coordination": {
                            "blackboard_enabled": True,
                            "semantic_rule_pack": "single_enterprise_case_v1",
                        }
                    },
                }
            }
        )


def test_agent_envelope_rejects_executable_fallbacks():
    envelope = AgentOutputEnvelope(
        schema_version="1.0",
        run_id="run-1",
        enterprise_id="Enterprise_A",
        department="sales",
        day=0,
        status="fallback",
        actions=[{"action": "develop_market"}],
    )

    with pytest.raises(ValueError, match="fallback envelopes"):
        envelope.to_dict()


def test_event_and_metric_contracts_include_shared_identity_fields():
    event = SimulationEvent(
        schema_version="1.0",
        run_id="run-1",
        scenario_id="beer_game",
        simulation_profile="multi_enterprise",
        enterprise_id="Retailer",
        department="sales",
        day=1,
        event_type="order_created",
        payload={"order_id": "order-1"},
    ).to_dict()
    metric = MetricRecord(
        schema_version="1.0",
        run_id="run-1",
        scenario_id="beer_game",
        enterprise_id="Retailer",
        day=1,
        metric_name="cash",
        value=1000,
    ).to_dict()

    assert event["event_id"]
    assert event["enterprise_id"] == metric["enterprise_id"]
    assert event["run_id"] == metric["run_id"]
    assert event["day"] == metric["day"]
