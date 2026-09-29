"""Optional semantic rule packs for strict single-enterprise coordination."""

import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Tuple

from coordination.communication_protocol import CommunicationEntry


NO_SEMANTIC_RULE_PACK = "none"
SINGLE_ENTERPRISE_CASE_RULE_PACK = "single_enterprise_case_v1"
SEMANTIC_RULE_PACKS = {
    NO_SEMANTIC_RULE_PACK,
    SINGLE_ENTERPRISE_CASE_RULE_PACK,
}

DEPARTMENT_OWNED_ACTIONS = {
    "finance": {
        "calculate_profit",
        "generate_balance_sheet",
        "pay_accounts_payable",
        "record_asset_addition",
        "record_asset_depreciation",
        "record_asset_disposal",
    },
    "hr": {
        "handle_recruitment",
        "process_employee_attrition",
    },
    "inventory": {
        "expand_warehouse",
    },
    "procurement": {
        "cancel_order",
        "create_purchase_order",
    },
    "production": {
        "build_production_line",
        "cancel_production_plan",
        "create_production_plan",
        "interrupt_production_plan",
        "resume_production_plan",
    },
    "sales": {
        "accept_order",
        "adjust_market_workers",
        "develop_market",
        "reject_order",
    },
}

ACTION_COLLABORATION_REPLACEMENTS = {
    "accept_order": "evaluate order acceptance",
    "adjust_market_workers": "review market staffing",
    "build_production_line": "review capacity expansion",
    "calculate_profit": "update profitability assessment",
    "cancel_order": "review supplier commitments",
    "cancel_production_plan": "revise production scheduling",
    "create_production_plan": "coordinate production scheduling",
    "create_purchase_order": "secure material supply",
    "develop_market": "review market expansion",
    "expand_warehouse": "review warehouse capacity",
    "generate_balance_sheet": "update balance-sheet visibility",
    "handle_recruitment": "review staffing",
    "interrupt_production_plan": "adjust active production scheduling",
    "pay_accounts_payable": "review payable settlement",
    "process_employee_attrition": "review staffing reduction",
    "record_asset_addition": "review asset addition",
    "record_asset_depreciation": "review asset depreciation",
    "record_asset_disposal": "review asset disposal",
    "reject_order": "evaluate order rejection",
    "resume_production_plan": "continue eligible production scheduling",
}


def _routes(
    finance: Iterable[str],
    hr: Iterable[str],
    inventory: Iterable[str],
    procurement: Iterable[str],
    production: Iterable[str],
    sales: Iterable[str],
) -> Dict[str, List[str]]:
    return {
        "finance": sorted(set(finance)),
        "hr": sorted(set(hr)),
        "inventory": sorted(set(inventory)),
        "procurement": sorted(set(procurement)),
        "production": sorted(set(production)),
        "sales": sorted(set(sales)),
    }


SINGLE_ENTERPRISE_CASE_V1 = {
    "route_topics": {
        "finance": _routes(
            finance=[],
            hr={"budget_control", "labor_cost", "staffing"},
            inventory={"budget_control", "warehouse_investment", "working_capital"},
            procurement={"material_budget", "supplier_payment", "working_capital"},
            production={"budget_control", "capex_gate", "working_capital"},
            sales={"budget_control", "market_investment", "revenue_quality", "revenue_signal"},
        ),
        "hr": _routes(
            finance={"labor_cost", "staffing"},
            hr=[],
            inventory={"staffing"},
            procurement={"staffing"},
            production={"staffing"},
            sales={"staffing"},
        ),
        "inventory": _routes(
            finance={"inventory_carrying_cost", "warehouse_investment", "working_capital"},
            hr={"staffing"},
            inventory=[],
            procurement={"material_arrival", "material_availability", "material_supply", "warehouse_capacity"},
            production={"inventory_status", "material_availability", "warehouse_capacity"},
            sales={"fulfillment", "inventory_status"},
        ),
        "procurement": _routes(
            finance={"material_budget", "supplier_payment", "working_capital"},
            hr={"staffing"},
            inventory={"material_arrival", "material_availability", "material_inventory", "material_supply", "warehouse_capacity"},
            procurement=[],
            production={"material_supply"},
            sales={"delivery_alignment", "supply_risk"},
        ),
        "production": _routes(
            finance={"capex_request", "cost_pressure", "working_capital"},
            hr={"staffing"},
            inventory={"fulfillment_support", "inventory_tracking", "material_flow"},
            procurement={"material_supply"},
            production=[],
            sales={"delivery_alignment", "production_status"},
        ),
        "sales": _routes(
            finance={"cash_forecast", "market_investment", "revenue_signal"},
            hr={"staffing"},
            inventory={"fulfillment", "inventory_status"},
            procurement={"demand_signal", "material_supply", "replenishment"},
            production={"delivery_alignment", "demand_signal", "production_planning"},
            sales=[],
        ),
    },
    "topic_aliases": {
        "finance": {
            "production": {"production_status": "budget_control"},
            "procurement": {"budget_control": "working_capital"},
        },
        "inventory": {
            "production": {"fulfillment": "inventory_status"},
            "procurement": {"material_flow": "material_supply"},
        },
        "procurement": {
            "inventory": {"material_flow": "material_supply"},
        },
        "production": {
            "inventory": {
                "fulfillment": "fulfillment_support",
                "inventory_status": "inventory_tracking",
                "material_arrival": "material_flow",
            },
            "procurement": {"production_planning": "material_supply"},
            "sales": {"production_pause": "production_status"},
        },
        "sales": {
            "finance": {
                "budget_allocation": "market_investment",
                "revenue_quality": "revenue_signal",
            },
            "inventory": {"material_availability": "inventory_status"},
            "production": {
                "capacity_allocation": "production_planning",
                "fulfillment": "delivery_alignment",
            },
        },
    },
}


def get_semantic_rule_pack(rule_pack_id: str) -> Dict[str, Any]:
    if rule_pack_id == NO_SEMANTIC_RULE_PACK:
        return {}
    if rule_pack_id == SINGLE_ENTERPRISE_CASE_RULE_PACK:
        return deepcopy(SINGLE_ENTERPRISE_CASE_V1)
    raise ValueError(f"Unknown communication semantic rule pack: {rule_pack_id}")


def describe_source_routes(rule_pack_id: str, source_department: str) -> str:
    pack = get_semantic_rule_pack(rule_pack_id)
    routes = (pack.get("route_topics") or {}).get(source_department, {})
    parts = [
        f"{target}=[{','.join(topics)}]"
        for target, topics in sorted(routes.items())
        if topics
    ]
    return "; ".join(parts)


def _action_pattern(action_name: str) -> re.Pattern:
    words = [re.escape(part) for part in action_name.split("_")]
    return re.compile(r"\b" + r"[_ ]".join(words) + r"\b", re.IGNORECASE)


def apply_semantic_rules(
    *,
    entries: Iterable[CommunicationEntry],
    rule_pack_id: str,
    auto_repair: bool = False,
) -> Tuple[List[CommunicationEntry], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply auditable topic and action-ownership rules to valid entries."""
    if rule_pack_id == NO_SEMANTIC_RULE_PACK:
        return list(entries), [], []

    pack = get_semantic_rule_pack(rule_pack_id)
    route_topics = pack.get("route_topics") or {}
    topic_aliases = pack.get("topic_aliases") or {}
    normalized_entries = []
    issues = []
    repairs = []

    for index, source_entry in enumerate(entries):
        entry = CommunicationEntry(**source_entry.to_dict())
        source_routes = route_topics.get(entry.source_department, {})
        if not source_routes:
            issues.append(
                {
                    "code": "unsupported_semantic_source",
                    "entry_index": index,
                    "source_department": entry.source_department,
                    "rule_pack": rule_pack_id,
                }
            )
            normalized_entries.append(entry)
            continue
        if entry.to_department not in source_routes:
            issues.append(
                {
                    "code": "unsupported_semantic_route",
                    "entry_index": index,
                    "source_department": entry.source_department,
                    "to_department": entry.to_department,
                    "allowed_targets": sorted(
                        target
                        for target, topics in source_routes.items()
                        if topics
                    ),
                }
            )
            normalized_entries.append(entry)
            continue
        allowed_topics = set(source_routes.get(entry.to_department) or [])
        aliases = (
            topic_aliases.get(entry.source_department, {})
            .get(entry.to_department, {})
        )
        canonical_topic = aliases.get(entry.topic, entry.topic)
        if canonical_topic != entry.topic:
            if auto_repair:
                repairs.append(
                    {
                        "code": "canonicalized_topic",
                        "entry_index": index,
                        "source_department": entry.source_department,
                        "to_department": entry.to_department,
                        "from": entry.topic,
                        "to": canonical_topic,
                    }
                )
                entry.topic = canonical_topic
            else:
                issues.append(
                    {
                        "code": "topic_alias_requires_repair",
                        "entry_index": index,
                        "source_department": entry.source_department,
                        "to_department": entry.to_department,
                        "topic": entry.topic,
                        "canonical_topic": canonical_topic,
                    }
                )

        if allowed_topics and entry.topic not in allowed_topics:
            issues.append(
                {
                    "code": "invalid_topic",
                    "entry_index": index,
                    "source_department": entry.source_department,
                    "to_department": entry.to_department,
                    "topic": entry.topic,
                    "allowed_topics": sorted(allowed_topics),
                }
            )

        for owner, action_names in DEPARTMENT_OWNED_ACTIONS.items():
            if owner != entry.to_department:
                continue
            for action_name in sorted(action_names):
                pattern = _action_pattern(action_name)
                if not pattern.search(entry.message):
                    continue
                if auto_repair:
                    replacement = ACTION_COLLABORATION_REPLACEMENTS[action_name]
                    entry.message = pattern.sub(replacement, entry.message)
                    repairs.append(
                        {
                            "code": "softened_cross_function_command",
                            "entry_index": index,
                            "source_department": entry.source_department,
                            "to_department": entry.to_department,
                            "action_name": action_name,
                            "replacement": replacement,
                        }
                    )
                else:
                    issues.append(
                        {
                            "code": "cross_function_override",
                            "entry_index": index,
                            "source_department": entry.source_department,
                            "to_department": entry.to_department,
                            "action_name": action_name,
                        }
                    )

        normalized_entries.append(entry)

    return normalized_entries, issues, repairs
