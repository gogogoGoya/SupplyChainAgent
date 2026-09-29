"""Experiment metric contracts for paper-facing C1/C2/C3 evaluation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List


EXPERIMENT_METRIC_CONTRACT_SCHEMA_VERSION = "experiment_metric_contract.v1"

CORE_PAPER_FAMILIES = ("bullwhip", "herding", "commons", "cobweb")
DECISION_GROUPS = ("C1", "C2", "C3")


FAMILY_METRIC_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "bullwhip": {
        "name": "牛鞭效应",
        "research_question": "订单、库存和缺货压力是否沿供应链纵向放大，以及开放利润目标是否缓冲放大。",
        "headline_metrics": [
            "mechanism_strength",
            "operating_performance",
            "decision_quality",
        ],
        "primary_metrics": [
            "bullwhip_ratio",
            "tier_order_quantity",
            "fill_rate",
            "confirmed_backlog",
            "inventory_position",
            "net_profit",
        ],
        "secondary_metrics": [
            "external_demand",
            "material_shortage",
            "cash",
            "total_revenue",
            "total_cost",
        ],
        "expected_direction": {
            "C1": "固定规则应产生可解释的订单放大或履约压力轨迹。",
            "C2": "约束 Agent 应在库存、履约和补货语境中表达机制性放大。",
            "C3": "盈利目标 Agent 可以降低无利润补货、平滑需求或牺牲部分服务水平换取现金安全。",
        },
    },
    "herding": {
        "name": "羊群效应",
        "research_question": "同业可见性是否提高同步扩产和过度生产，盈利目标是否削弱无效跟随。",
        "headline_metrics": [
            "mechanism_strength",
            "operating_performance",
            "decision_quality",
        ],
        "primary_metrics": [
            "peer_visibility_enabled",
            "synchronization_index",
            "herding_index",
            "overproduction_ratio",
            "inventory_pressure",
            "net_profit",
        ],
        "secondary_metrics": [
            "true_demand",
            "market_heat",
            "planned_quantity",
            "total_planned_quantity",
            "cash",
        ],
        "expected_direction": {
            "C1": "固定同业跟随规则应使 peer-visible 组高于 no-peer 组。",
            "C2": "约束 Agent 在同业摘要可见时更容易同步计划或放大市场热度。",
            "C3": "盈利目标 Agent 可以忽略低收益同业信号，降低同步度或过度生产。",
        },
    },
    "commons": {
        "name": "公地悲剧",
        "research_question": "共享资源局部获取是否导致资源退化和财务反噬，长期利润目标是否促成克制。",
        "headline_metrics": [
            "mechanism_strength",
            "operating_performance",
            "decision_quality",
        ],
        "primary_metrics": [
            "resource_stock_quantity",
            "resource_quality",
            "actual_acquisition_quantity",
            "sustainable_acquisition_per_round",
            "cash",
            "net_profit",
        ],
        "secondary_metrics": [
            "planned_acquisition_quantity",
            "resource_state",
            "production_failure_due_to_cash",
            "inventory_pressure",
        ],
        "expected_direction": {
            "C1": "固定局部收益规则应能验证资源退化和获取折损方程。",
            "C2": "约束 Agent 在共享资源语境中应展示过度获取、质量下降或现金反噬。",
            "C3": "盈利目标 Agent 可以降低短期获取强度，延缓资源退化或改善长期利润。",
        },
    },
    "cobweb": {
        "name": "蛛网模型",
        "research_question": (
            "滞后价格和产量决策是否产生预设稳定性轨迹，以及盈利目标 Agent "
            "能否在发散压力下改善经营稳定性。"
        ),
        "headline_metrics": [
            "mechanism_strength",
            "operating_performance",
            "decision_quality",
        ],
        "primary_metrics": [
            "market_price",
            "actual_supply_quantity",
            "production_plan_quantity",
            "price_deviation_from_equilibrium",
            "supply_deviation_from_equilibrium",
            "late_to_early_price_deviation_ratio",
            "late_to_early_supply_deviation_ratio",
            "production_adjustment_magnitude",
            "equilibrium_price",
            "net_profit",
            "cash",
            "fill_rate",
        ],
        "secondary_metrics": [
            "theoretical_planned_supply_quantity",
            "equilibrium_quantity",
            "supply_source",
            "inventory_position",
            "confirmed_backlog",
            "action_failure_count",
        ],
        "expected_direction": {
            "C1": "理论供给函数应分别复现收敛、近似等幅和有界发散轨迹。",
            "C2": "发散压力下，约束 Agent 应主要根据价格与蛛网信号内生形成供给计划。",
            "C3": "发散压力下，盈利目标 Agent 应将价格视为经营证据，并在利润、现金、服务和生产调整风险之间权衡。",
        },
    },
    "financial_constraint": {
        "name": "财务约束传导",
        "research_question": "现金、授信和采购失败是否向履约链路传导。",
        "headline_metrics": [
            "mechanism_strength",
            "operating_performance",
            "decision_quality",
        ],
        "primary_metrics": [
            "fill_rate",
            "net_profit",
            "cash",
            "cash_guard_failure",
            "confirmed_backlog",
            "procurement_failure",
        ],
        "secondary_metrics": [
            "credit_balance",
            "inventory_position",
            "lost_sales_quantity",
        ],
        "expected_direction": {
            "C1": "固定规则叠加预算约束应触发可解释的履约阻断。",
            "C2": "约束 Agent 应在现金和授信语境下调整采购和销售。",
            "C3": "盈利目标 Agent 可以主动缩单、延后采购或调整组合。",
        },
    },
    "topology": {
        "name": "复杂拓扑",
        "research_question": "链状、分支和网状结构下交易边、履约和结算是否稳定。",
        "headline_metrics": [
            "mechanism_strength",
            "operating_performance",
            "decision_quality",
        ],
        "primary_metrics": [
            "trade_edge_coverage",
            "order_count",
            "gross_transaction_value",
            "fill_rate",
            "net_profit",
        ],
        "secondary_metrics": [
            "multi_source_split",
            "supplier_reliability",
            "on_time_delivery_rate",
        ],
        "expected_direction": {
            "C1": "固定路由应验证拓扑交易和结算链路。",
            "C2": "约束 Agent 应能在拓扑结构内完成稳定交易。",
            "C3": "盈利目标 Agent 可选更可靠或更高利润交易边。",
        },
    },
    "single_enterprise": {
        "name": "单企业理性能力校验",
        "research_question": "Agent 是否能识别单企业经营问题并采取合理纠偏动作。",
        "headline_metrics": [
            "diagnostic_accuracy",
            "corrective_action_quality",
            "recovery_performance",
        ],
        "primary_metrics": [
            "issue_identified",
            "primary_department_actioned",
            "preferred_action_taken",
            "discouraged_action_taken",
            "recovery_metric",
        ],
        "secondary_metrics": [
            "handoff_day",
            "takeover_rounds",
            "cash",
            "inventory_position",
            "fill_rate",
        ],
        "expected_direction": {
            "S0": "Agent 应匹配主责部门、避免不鼓励动作，并在接管窗口改善 case-specific 指标。",
        },
    },
    "long_horizon_evolution": {
        "name": "多企业持续演变长跑",
        "research_question": (
            "四级供应链企业能否识别分阶段外部成本、贸易和需求变化，"
            "并在不制造无依据需求放大的前提下维持利润、现金与履约韧性。"
        ),
        "headline_metrics": [
            "change_detection_and_response",
            "operating_resilience",
            "decision_quality",
        ],
        "primary_metrics": [
            "event_detection_latency_turns",
            "response_action_latency_turns",
            "phase_net_profit",
            "phase_cash_change",
            "fill_rate",
            "confirmed_backlog",
            "inventory_turnover_proxy",
            "procurement_unit_cost",
            "production_unit_cost",
            "order_variance_ratio",
            "agent_fallback_rate",
        ],
        "secondary_metrics": [
            "external_material_price_factor",
            "production_conversion_cost_factor",
            "external_logistics_cost_factor",
            "external_demand_quantity_factor",
            "external_customer_price_factor",
            "total_revenue",
            "total_cost",
            "cash",
        ],
        "expected_direction": {
            "E1": (
                "Agent 应在每次可观测环境变化后及时调整采购、生产、库存和销售决策，"
                "缩短经营指标恢复时间，并避免将平稳终端需求无依据地向上游放大。"
            ),
        },
    },
    "general": {
        "name": "通用多企业运行",
        "research_question": "运行是否具备可纳入论文统计的基础标注和质量信息。",
        "headline_metrics": [
            "operating_performance",
            "decision_quality",
            "sample_quality",
        ],
        "primary_metrics": [
            "net_profit",
            "cash",
            "fill_rate",
            "round_integrity",
            "fallback_triggered",
        ],
        "secondary_metrics": [
            "total_revenue",
            "total_cost",
            "completed_steps",
            "enterprise_count",
        ],
        "expected_direction": {},
    },
}


def infer_experiment_family(scenario_id: str) -> str:
    """Infer the paper mechanism family from a scenario id."""
    value = str(scenario_id or "").lower()
    if value == "long_horizon_evolution" or "long_horizon_evolution" in value:
        return "long_horizon_evolution"
    if value.startswith("single_case_"):
        return "single_enterprise"
    if "herding" in value:
        return "herding"
    if "commons" in value or "mining" in value:
        return "commons"
    if "cobweb" in value:
        return "cobweb"
    if "credit_constraint" in value or "financial" in value:
        return "financial_constraint"
    if "architecture" in value or "topology" in value:
        return "topology"
    if "beer_game" in value or value.startswith("baseline_"):
        return "bullwhip"
    return "general"


def build_experiment_metric_contract(
    *,
    scenario_id: str,
    experiment_design: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Return the expected metrics and quality gates for a scenario/run."""
    experiment_design = experiment_design or {}
    experiment_group = experiment_design.get("experiment_group")
    family = infer_experiment_family(scenario_id)
    family_contract = deepcopy(
        FAMILY_METRIC_CONTRACTS.get(family) or FAMILY_METRIC_CONTRACTS["general"]
    )
    expected_direction = family_contract.pop("expected_direction", {})
    group_expected_direction = expected_direction.get(
        experiment_group,
        expected_direction.get("C2", ""),
    )
    return {
        "schema_version": EXPERIMENT_METRIC_CONTRACT_SCHEMA_VERSION,
        "phase": "phase2_expected_metrics",
        "scenario_id": str(scenario_id or ""),
        "experiment_group": experiment_group,
        "decision_regime": experiment_design.get("decision_regime"),
        "agent_objective_profile": experiment_design.get("agent_objective_profile"),
        "constraint_level": experiment_design.get("constraint_level"),
        "family": family,
        **family_contract,
        "expected_direction_for_group": group_expected_direction,
        "quality_gates": [
            "run_status_eligible",
            "round_integrity_ok",
            "decision_regime_labeled",
            "config_snapshot_available",
        ],
        "group_specific_gates": _group_specific_gates(experiment_group),
    }


def _group_specific_gates(experiment_group: str) -> List[str]:
    if experiment_group == "C1":
        return ["scripted_rule_policy_enabled", "agent_open_reasoning_disabled"]
    if experiment_group == "C2":
        return ["profit_objective_disabled", "mechanism_policy_context_visible"]
    if experiment_group == "C3":
        return ["profit_objective_enabled", "objective_function_available"]
    if experiment_group == "S0":
        return ["single_enterprise_case_policy_enabled", "case_manifest_available"]
    if experiment_group == "E1":
        return [
            "external_environment_policy_enabled",
            "long_run_policy_enabled",
            "future_event_content_hidden",
        ]
    return []


def assess_phase1_readiness(
    scenarios: Iterable[Dict[str, Any]],
    *,
    core_families: Iterable[str] = CORE_PAPER_FAMILIES,
) -> Dict[str, Any]:
    """Assess whether C1/C2/C3 run-preparation assets are present."""
    matrix: Dict[str, Dict[str, List[str]]] = {
        family: {group: [] for group in DECISION_GROUPS}
        for family in core_families
    }
    group_counts = {group: 0 for group in DECISION_GROUPS}
    failures: List[str] = []

    for scenario in scenarios:
        scenario_id = str(scenario.get("scenario_id") or "")
        experiment_design = scenario.get("experiment_design") or {}
        group = experiment_design.get("experiment_group")
        family = infer_experiment_family(scenario_id)
        if group in group_counts:
            group_counts[group] += 1
        if family in matrix and group in matrix[family]:
            matrix[family][group].append(scenario_id)

        runtime = scenario.get("runtime_injection") or {}
        scripted_policy = runtime.get("scripted_rule_policy") or {}
        profit_policy = runtime.get("profit_objective_policy") or {}
        decision_regime = experiment_design.get("decision_regime")
        if group == "C1" and not scripted_policy.get("enabled"):
            failures.append(f"{scenario_id}: C1 missing scripted_rule_policy.enabled")
        if group == "C2" and decision_regime != "constrained_agent":
            failures.append(f"{scenario_id}: C2 decision_regime mismatch")
        if group == "C3" and not profit_policy.get("enabled"):
            failures.append(f"{scenario_id}: C3 missing profit_objective_policy.enabled")
        if group == "C3" and decision_regime != "profit_seeking_agent":
            failures.append(f"{scenario_id}: C3 decision_regime mismatch")

    missing_groups = [
        group for group, count in group_counts.items()
        if count <= 0
    ]
    missing_core_cells = [
        f"{family}:{group}"
        for family, groups in matrix.items()
        for group, scenario_ids in groups.items()
        if not scenario_ids
    ]
    complete = not failures and not missing_groups and not missing_core_cells
    return {
        "schema_version": EXPERIMENT_METRIC_CONTRACT_SCHEMA_VERSION,
        "phase": "phase1_run_preparation_readiness",
        "complete": complete,
        "group_counts": group_counts,
        "core_family_matrix": matrix,
        "missing_groups": missing_groups,
        "missing_core_cells": missing_core_cells,
        "failures": failures,
    }
