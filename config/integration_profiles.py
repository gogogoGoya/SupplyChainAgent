"""Compatibility-first profiles for the unified simulation platform."""

from copy import deepcopy
from typing import Any, Dict, Iterable


SIMULATION_PROFILES = {"single_enterprise", "multi_enterprise"}
ANALYSIS_PROFILES = {"none", "historical_diagnosis"}
COMMUNICATION_VALIDATION_MODES = {"off", "warn", "strict"}
COMMUNICATION_SEMANTIC_RULE_PACKS = {
    "none",
    "single_enterprise_case_v1",
}
OUTPUT_VALIDATION_MODES = {"off", "warn", "strict"}
STORAGE_PROFILES = {
    "filesystem",
    "postgres_mirror",
    "postgres_checkpoint",
    "postgres_authoritative",
}

DEFAULT_INTEGRATION_PROFILES: Dict[str, Any] = {
    "simulation": {
        "profile": "multi_enterprise",
    },
    "capabilities": {
        "analysis": {
            "profile": "none",
            "history_days": 5,
        },
        "coordination": {
            "blackboard_enabled": False,
            "two_phase_enabled": False,
            "communication_validation": "off",
            "semantic_rule_pack": "none",
            "semantic_auto_repair": False,
        },
        "skill": {
            "context_validation": "off",
            "output_validation": "off",
            "max_retries": 3,
            "audit_enabled": True,
        },
        "departments": {
            "finance_enabled": False,
        },
    },
    "infrastructure": {
        "storage": {
            "profile": "postgres_mirror",
        },
        "operations": {
            "enabled": True,
        },
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _require_choice(value: str, allowed: Iterable[str], field_name: str) -> None:
    if value not in allowed:
        raise ValueError(
            f"Invalid {field_name}: {value!r}; expected one of {sorted(allowed)}"
        )


def validate_integration_profiles(profiles: Dict[str, Any]) -> None:
    """Raise a concrete error when a resolved profile contract is invalid."""
    simulation = profiles["simulation"]
    capabilities = profiles["capabilities"]
    infrastructure = profiles["infrastructure"]

    _require_choice(
        simulation["profile"],
        SIMULATION_PROFILES,
        "simulation.profile",
    )
    _require_choice(
        capabilities["analysis"]["profile"],
        ANALYSIS_PROFILES,
        "capabilities.analysis.profile",
    )
    _require_choice(
        capabilities["coordination"]["communication_validation"],
        COMMUNICATION_VALIDATION_MODES,
        "capabilities.coordination.communication_validation",
    )
    _require_choice(
        capabilities["coordination"]["semantic_rule_pack"],
        COMMUNICATION_SEMANTIC_RULE_PACKS,
        "capabilities.coordination.semantic_rule_pack",
    )
    _require_choice(
        capabilities["skill"]["context_validation"],
        OUTPUT_VALIDATION_MODES,
        "capabilities.skill.context_validation",
    )
    _require_choice(
        capabilities["skill"]["output_validation"],
        OUTPUT_VALIDATION_MODES,
        "capabilities.skill.output_validation",
    )
    _require_choice(
        infrastructure["storage"]["profile"],
        STORAGE_PROFILES,
        "infrastructure.storage.profile",
    )

    if int(capabilities["analysis"]["history_days"]) <= 0:
        raise ValueError("capabilities.analysis.history_days must be > 0")
    if int(capabilities["skill"]["max_retries"]) < 0:
        raise ValueError("capabilities.skill.max_retries must be >= 0")
    if not isinstance(capabilities["skill"]["audit_enabled"], bool):
        raise ValueError("capabilities.skill.audit_enabled must be boolean")

    if (
        capabilities["coordination"]["two_phase_enabled"]
        and not capabilities["coordination"]["blackboard_enabled"]
    ):
        raise ValueError(
            "two-phase coordination requires blackboard_enabled=true"
        )
    semantic_rule_pack = capabilities["coordination"]["semantic_rule_pack"]
    if semantic_rule_pack != "none":
        if simulation["profile"] != "single_enterprise":
            raise ValueError(
                "communication semantic rule packs require "
                "simulation.profile=single_enterprise"
            )
        if not capabilities["coordination"]["blackboard_enabled"]:
            raise ValueError(
                "communication semantic rule packs require "
                "blackboard_enabled=true"
            )
        if capabilities["coordination"]["communication_validation"] == "off":
            raise ValueError(
                "communication semantic rule packs require "
                "communication_validation=warn or strict"
            )
    if not isinstance(
        capabilities["coordination"]["semantic_auto_repair"],
        bool,
    ):
        raise ValueError(
            "capabilities.coordination.semantic_auto_repair must be boolean"
        )
    if not isinstance(capabilities["departments"]["finance_enabled"], bool):
        raise ValueError(
            "capabilities.departments.finance_enabled must be boolean"
        )
    if (
        capabilities["departments"]["finance_enabled"]
        and simulation["profile"] != "single_enterprise"
    ):
        raise ValueError(
            "Finance Agent profile currently requires "
            "simulation.profile=single_enterprise"
        )
    if (
        infrastructure["storage"]["profile"] == "postgres_authoritative"
        and not infrastructure["operations"]["enabled"]
    ):
        raise ValueError(
            "postgres_authoritative requires operations.enabled=true"
        )


def resolve_integration_profiles(
    scenario_config: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Resolve optional integration profiles without mutating legacy scenarios.

    Existing scenarios do not contain ``integration_profiles`` and therefore
    retain the current multi-enterprise behavior while using the default
    filesystem + SQL mirror persistence layer.
    """
    overrides = (scenario_config or {}).get("integration_profiles") or {}
    profiles = _deep_merge(DEFAULT_INTEGRATION_PROFILES, overrides)
    validate_integration_profiles(profiles)
    return profiles


def get_scenario_integration_profiles(scenario_id: str = None) -> Dict[str, Any]:
    """Resolve profiles for a registered scenario while avoiding import cycles."""
    from config.simulation_preset_config import get_scenario_config

    return resolve_integration_profiles(get_scenario_config(scenario_id))
