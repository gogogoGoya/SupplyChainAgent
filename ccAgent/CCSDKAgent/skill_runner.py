from __future__ import annotations

import asyncio
import ast
import json
import math
import re
import time
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional

from data_config import DepartmentSpec, EnterpriseSpec
from multi_tenant_utils import MultiTenantUtils
from GlobalDepartmentLockManager import GlobalDepartmentLockManager
from scripted_rule_runner import ScriptedRuleRunner
from long_horizon_hybrid_replay import LongHorizonHybridReplayRunner
from claude_agent_sdk import query
from claude_agent_sdk._errors import ProcessError

from SessionRegistry import SessionRegistry

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from config.environment_config import EnvironmentConfig
from config.integration_profiles import resolve_integration_profiles
from config.simulation_preset_config import get_active_scenario_id
from core.skill_protocol import (
    SkillExecutionAudit,
    adapt_legacy_actions,
    adapt_legacy_analysis,
    audit_context_files,
)
from coordination.semantic_rule_packs import describe_source_routes

@dataclass
class SkillRunSpec:
    role: str
    name: str
    skill_name: str
    skill_args: str
    output_file_name: str
    output_file_path: str
    analysis_path: str
    state_path: str
    blackboard_path: str
    trade_decision_card_path: Optional[str]
    communication_file_path: str
    action_template_dir: str
    compact_context: bool = False


@dataclass
class RunInspection:
    skill_called: bool
    skill_args_ok: bool
    read_analysis: bool
    read_state: bool
    read_blackboard: bool
    read_trade_decision_card: bool
    write_called: bool
    write_target_ok: bool
    read_output_called: bool
    has_json_block: bool
    json_block: Optional[str]
    failure_type: str

@dataclass
class AnalystRunSpec:
    role: str
    skill_name: str
    skill_args: str
    output_file_name: str
    output_file_path: str
    observation_path: str
    compact_observation_enabled: bool
    history_projection_path: str
    history_projection_day: int
    compact_observation_kind: str = ""
    chart_export_path: str = ""
    chart_export_enabled: bool = False


@dataclass
class AnalystRunInspection:
    skill_called: bool
    skill_args_ok: bool
    write_called: bool
    write_target_ok: bool
    read_output_called: bool
    has_json_block: bool
    json_block: Optional[str]
    failure_type: str


class SkillRunner:

    def __init__(
        self,
        enterprise_spec: EnterpriseSpec,
        session_registry: SessionRegistry,
        build_options: Callable,
        client_dir: str,
        workspace_dir: Optional[Path] = None,
    ):
        self.enterprise_spec = enterprise_spec
        self.global_department_lock_manager = GlobalDepartmentLockManager()
        self.session_registry = session_registry
        self.build_options = build_options
        self.client_dir = Path(client_dir)
        self.workspace_dir = Path(workspace_dir) if workspace_dir else (
            self.client_dir / "workspace_multi"
        )
        self.scripted_rule_runner = ScriptedRuleRunner(
            self.client_dir,
            self.enterprise_spec,
            workspace_dir=self.workspace_dir,
        )
        self.hybrid_replay_runner = LongHorizonHybridReplayRunner(
            self.workspace_dir,
            self.enterprise_spec,
            self.scripted_rule_runner,
        )

    def _workspace_root(self) -> Path:
        workspace_dir = getattr(self, "workspace_dir", None)
        if workspace_dir is not None:
            return Path(workspace_dir)
        return Path(self.client_dir) / "workspace_multi"

    def _runtime_contract(self) -> Dict[str, Any]:
        run_meta = MultiTenantUtils._read_json_if_exists(
            self._workspace_root() / "run_meta.json",
            {},
        )
        scenario_config = run_meta.get("scenario_config") or {}
        profiles = run_meta.get("integration_profiles")
        if not isinstance(profiles, dict):
            profiles = resolve_integration_profiles(scenario_config)
        return {
            "run_id": str(run_meta.get("run_id") or "workspace_unarchived"),
            "scenario_id": str(
                run_meta.get("scenario_id")
                or (scenario_config.get("meta") or {}).get("scenario_id")
                or get_active_scenario_id()
            ),
            "scenario_config": scenario_config,
            "profiles": profiles,
            "run_meta": run_meta,
        }

    def _skill_profile(self) -> Dict[str, Any]:
        contract = self._runtime_contract()
        return (
            ((contract["profiles"].get("capabilities") or {}).get("skill"))
            or {}
        )

    def _analysis_profile(self) -> Dict[str, Any]:
        contract = self._runtime_contract()
        return (
            ((contract["profiles"].get("capabilities") or {}).get("analysis"))
            or {}
        )

    def _long_run_agent_failure_continuation_enabled(self) -> bool:
        contract = self._runtime_contract()
        runtime_injection = (
            (contract.get("scenario_config") or {}).get("runtime_injection") or {}
        )
        policy = runtime_injection.get("long_run_experiment_policy") or {}
        return bool(
            policy.get("enabled")
            and policy.get("continue_on_agent_failure")
            and str((contract.get("run_meta") or {}).get("orchestrator") or "multi_enterprise")
            == "multi_enterprise"
        )

    def _long_run_experiment_policy(self) -> Dict[str, Any]:
        contract = self._runtime_contract()
        runtime_injection = (
            (contract.get("scenario_config") or {}).get("runtime_injection") or {}
        )
        policy = runtime_injection.get("long_run_experiment_policy") or {}
        if not isinstance(policy, dict) or not policy.get("enabled"):
            return {}
        if str(contract.get("scenario_id") or "") != "long_horizon_evolution":
            return {}
        return policy

    def _long_run_agent_timeout_seconds(
        self,
        *,
        role: str,
        round_id: int,
        retry_index: int,
        default_seconds: int,
        analyst: bool = False,
    ) -> int:
        policy = self._long_run_experiment_policy()
        timeout_policy = policy.get("agent_timeout_policy") or {}
        if not timeout_policy.get("enabled"):
            return max(1, int(default_seconds))
        if analyst:
            event_turns = {int(item) for item in policy.get("event_turns") or []}
            follow_up_offsets = {
                int(item) for item in policy.get("event_follow_up_offsets") or []
            }
            event_review_rounds = {
                event_turn + offset
                for event_turn in event_turns
                for offset in follow_up_offsets
            }
            if retry_index > 0:
                configured = timeout_policy.get("analyst_retry_seconds")
            elif int(round_id) in event_review_rounds:
                configured = timeout_policy.get("analyst_event_attempt_seconds")
            else:
                configured = timeout_policy.get("analyst_first_attempt_seconds")
        elif retry_index > 0:
            configured = timeout_policy.get("department_retry_seconds")
        else:
            configured = timeout_policy.get("department_first_attempt_seconds")
        try:
            resolved = int(configured)
        except (TypeError, ValueError):
            resolved = int(default_seconds)
        try:
            hard_max = int(timeout_policy.get("hard_max_seconds") or resolved)
        except (TypeError, ValueError):
            hard_max = resolved
        return max(1, min(resolved, max(1, hard_max)))

    def _long_run_agent_context_compaction_policy(self) -> Dict[str, Any]:
        """Return the E1-only bounded Agent input policy from the run snapshot."""
        contract = self._runtime_contract()
        scenario_config = contract.get("scenario_config") or {}
        runtime_injection = scenario_config.get("runtime_injection") or {}
        long_run_policy = runtime_injection.get("long_run_experiment_policy") or {}
        compaction = long_run_policy.get("agent_context_compaction") or {}
        run_meta = contract.get("run_meta") or {}
        is_e1 = bool(
            str(contract.get("scenario_id") or "") == "long_horizon_evolution"
            or str(
                ((scenario_config.get("experiment_design") or {}).get("experiment_group"))
                or ""
            ).upper() == "E1"
        )
        if not (
            is_e1
            and long_run_policy.get("enabled") is True
            and compaction.get("enabled") is True
            and str(run_meta.get("orchestrator") or "multi_enterprise")
            == "multi_enterprise"
        ):
            return {}
        return compaction

    @staticmethod
    def _bounded_records(records: Any, limit: int, *, keep_tail: bool = False) -> List[Any]:
        if not isinstance(records, list):
            return []
        bounded_limit = max(0, int(limit))
        if bounded_limit == 0:
            return []
        return records[-bounded_limit:] if keep_tail else records[:bounded_limit]

    @staticmethod
    def _order_is_currently_actionable(order: Any, round_id: int) -> bool:
        if not isinstance(order, dict):
            return False
        for field in ("offer_expiry_day", "delivery_deadline"):
            value = order.get(field)
            try:
                if value not in (None, "") and int(round_id) > int(value):
                    return False
            except (TypeError, ValueError):
                continue
        return True

    @classmethod
    def _compact_long_run_procurement_state(
        cls,
        self_state: Dict[str, Any],
        *,
        recent_history_items: int,
        max_open_records: int,
    ) -> Dict[str, Any]:
        compacted = {
            key: value
            for key, value in self_state.items()
            if key not in {"orders", "replenishment", "supplier_selection_events"}
        }
        events = self_state.get("supplier_selection_events") or []
        compacted["supplier_selection_events"] = cls._bounded_records(
            events,
            recent_history_items,
            keep_tail=True,
        )
        explicit_material_ids = {
            str(item)
            for item in (self_state.get("purchasable_materials_idList") or [])
            if item not in (None, "")
        }
        if explicit_material_ids:
            matrix = self_state.get("materials_suppliers_matrix") or {}
            compacted["materials_suppliers_matrix"] = {
                str(material_id): suppliers
                for material_id, suppliers in matrix.items()
                if str(material_id) in explicit_material_ids
            }
            filtered_candidates = []
            for candidate in self_state.get("supplier_candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                materials = candidate.get("materials") or {}
                candidate_material_ids = (
                    {str(item) for item in materials.keys()}
                    if isinstance(materials, dict)
                    else {str(item) for item in materials or []}
                )
                if candidate_material_ids & explicit_material_ids:
                    filtered_candidates.append(candidate)
            compacted["supplier_candidates"] = filtered_candidates

        open_buckets = {
            "available",
            "created",
            "confirmed",
            "open",
            "ordered",
            "pending",
            "in_progress",
            "in_transit",
        }
        compact_orders: Dict[str, Any] = {}
        order_history_summary: Dict[str, int] = {}
        open_records_summary: Dict[str, Dict[str, int]] = {}
        for bucket, records in (self_state.get("orders") or {}).items():
            if not isinstance(records, list):
                compact_orders[bucket] = records
                continue
            if str(bucket).lower() in open_buckets:
                compact_orders[bucket] = cls._bounded_records(
                    records,
                    max_open_records,
                )
                open_records_summary[bucket] = {
                    "total": len(records),
                    "included": len(compact_orders[bucket]),
                }
            else:
                order_history_summary[bucket] = len(records)
                if records:
                    compact_orders[f"recent_{bucket}"] = cls._bounded_records(
                        records,
                        recent_history_items,
                        keep_tail=True,
                    )
        compact_orders["history_summary"] = order_history_summary
        compact_orders["open_records_summary"] = open_records_summary
        compacted["orders"] = compact_orders

        replenishment = self_state.get("replenishment") or {}
        compact_replenishment: Dict[str, Any] = {}
        replenishment_history_summary: Dict[str, int] = {}
        for key, value in replenishment.items():
            if isinstance(value, list):
                replenishment_history_summary[key] = len(value)
                compact_replenishment[f"recent_{key}"] = cls._bounded_records(
                    value,
                    recent_history_items,
                    keep_tail=True,
                )
            else:
                compact_replenishment[key] = value
        compact_replenishment["history_summary"] = replenishment_history_summary
        compacted["replenishment"] = compact_replenishment
        return compacted

    @classmethod
    def _compact_long_run_sales_state(
        cls,
        self_state: Dict[str, Any],
        *,
        round_id: int,
        recent_history_items: int,
        max_open_records: int,
    ) -> Dict[str, Any]:
        compacted = {
            key: value
            for key, value in self_state.items()
            if key not in {"sales_orders", "demand_backlog", "proposals_list"}
        }
        open_buckets = {
            "available",
            "accepted",
            "backlog",
            "in_progress",
            "open",
            "pending",
        }
        compact_orders: Dict[str, Any] = {}
        order_history_summary: Dict[str, int] = {}
        open_records_summary: Dict[str, Dict[str, int]] = {}
        filtered_non_actionable: Dict[str, int] = {}
        for bucket, records in (self_state.get("sales_orders") or {}).items():
            if not isinstance(records, list):
                compact_orders[bucket] = records
                continue
            bucket_name = str(bucket).lower()
            if bucket_name in open_buckets:
                current_records = records
                if bucket_name == "available":
                    current_records = [
                        order
                        for order in records
                        if cls._order_is_currently_actionable(order, round_id)
                    ]
                    filtered_non_actionable[bucket] = len(records) - len(current_records)
                compact_orders[bucket] = cls._bounded_records(
                    current_records,
                    max_open_records,
                )
                open_records_summary[bucket] = {
                    "total": len(current_records),
                    "included": len(compact_orders[bucket]),
                }
            else:
                order_history_summary[bucket] = len(records)
                if records:
                    compact_orders[f"recent_{bucket}"] = cls._bounded_records(
                        records,
                        recent_history_items,
                        keep_tail=True,
                    )
        compact_orders["history_summary"] = order_history_summary
        compact_orders["open_records_summary"] = open_records_summary
        compact_orders["filtered_non_actionable_summary"] = filtered_non_actionable
        compacted["sales_orders"] = compact_orders

        demand_backlog = self_state.get("demand_backlog") or {}
        compact_demand: Dict[str, Any] = {}
        demand_history_summary: Dict[str, int] = {}
        for key, value in demand_backlog.items():
            if isinstance(value, list):
                demand_history_summary[key] = len(value)
                compact_demand[f"recent_{key}"] = cls._bounded_records(
                    value,
                    recent_history_items,
                    keep_tail=True,
                )
            else:
                compact_demand[key] = value
        compact_demand["history_summary"] = demand_history_summary
        compacted["demand_backlog"] = compact_demand

        proposals = self_state.get("proposals_list") or []
        compacted["proposals_list"] = cls._bounded_records(
            proposals,
            max_open_records,
        )
        compacted["proposals_summary"] = {
            "total": len(proposals) if isinstance(proposals, list) else 0,
            "included": len(compacted["proposals_list"]),
        }
        return compacted

    @staticmethod
    def _compact_long_run_simulation_context(context: Any) -> Dict[str, Any]:
        if not isinstance(context, dict):
            return {}
        fields = (
            "total_steps",
            "final_round",
            "market_demand_mode",
            "trade_mode",
            "is_scheduled_external_demand_mode",
            "is_beer_game_mode",
            "is_cobweb_mode",
            "is_shared_resource_mode",
            "is_herding_mode",
            "external_environment",
            "context_scope",
        )
        return {field: context.get(field) for field in fields if field in context}

    def _build_long_run_external_change_review(
        self,
        simulation_context: Dict[str, Any],
        round_id: int,
    ) -> Dict[str, Any]:
        """Build a compact, non-prescriptive E1 event comparison for the Analyst."""
        current = (
            (simulation_context or {}).get("external_environment") or {}
        )
        if not isinstance(current, dict) or not current.get("enabled"):
            return {"enabled": False, "current_turn": int(round_id)}

        previous: Dict[str, Any] = {}
        if int(round_id) > 0:
            previous_root = (
                self.workspace_dir
                / "public"
                / "exchange"
                / f"day{int(round_id) - 1}"
            )
            previous = MultiTenantUtils._read_json_if_exists(
                previous_root / "end_of_day" / "external_environment.json",
                {},
            ) or MultiTenantUtils._read_json_if_exists(
                previous_root / "external_environment.json",
                {},
            )

        active_factors = current.get("active_factors") or {}
        previous_factors = (
            previous.get("active_factors") or {}
            if isinstance(previous, dict)
            else {}
        )
        factor_comparison: Dict[str, Any] = {}
        for factor, value in active_factors.items():
            try:
                observed = float(value)
            except (TypeError, ValueError):
                continue
            try:
                prior = float(previous_factors.get(factor, 1.0))
            except (TypeError, ValueError):
                prior = 1.0
            factor_comparison[str(factor)] = {
                "baseline": 1.0,
                "previous_turn": prior,
                "current_turn": observed,
                "change_from_previous": observed - prior,
                "deviation_from_baseline": observed - 1.0,
                "changed_this_turn": not math.isclose(observed, prior),
                "active_deviation": not math.isclose(observed, 1.0),
            }

        latest_event = current.get("latest_event") or {}
        event_turn = latest_event.get("turn")
        try:
            turns_since_event = max(0, int(round_id) - int(event_turn))
        except (TypeError, ValueError):
            turns_since_event = None
        triggered = bool(current.get("event_triggered_this_turn"))
        active_deviations = [
            factor
            for factor, comparison in factor_comparison.items()
            if comparison.get("active_deviation")
        ]
        return {
            "schema_version": "long_horizon_external_change_review.v1",
            "enabled": True,
            "current_turn": int(round_id),
            "review_status": (
                "event_triggered_now"
                if triggered
                else "post_event_follow_up"
                if latest_event and turns_since_event is not None and turns_since_event <= 5
                else "active_change_monitoring"
                if active_deviations
                else "baseline_monitoring"
            ),
            "event_triggered_this_turn": triggered,
            "triggered_events": current.get("triggered_events") or [],
            "latest_event": latest_event,
            "recent_events": current.get("recent_events") or [],
            "turns_since_latest_event": turns_since_event,
            "factor_comparison": factor_comparison,
            "active_deviating_factors": active_deviations,
            "actual_values": current.get("actual_values") or {},
            "analysis_contract": {
                "use_local_operating_evidence": True,
                "distinguish_event_effect_from_backlog_or_demand_pressure": True,
                "compare_margin_cash_service_inventory_and_capacity": True,
                "do_not_treat_factor_change_as_an_action_command": True,
                "define_review_criteria_for_the_next_2_to_5_turns": True,
            },
        }

    @classmethod
    def _build_long_run_department_context_projection(
        cls,
        payload: Dict[str, Any],
        department: str,
        round_id: int,
        policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        recent_history_items = max(1, int(policy.get("recent_history_items") or 4))
        max_open_records = max(8, int(policy.get("max_open_records") or 48))
        self_state = payload.get("self_state") or {}
        if department == "procurement":
            self_state = cls._compact_long_run_procurement_state(
                self_state,
                recent_history_items=recent_history_items,
                max_open_records=max_open_records,
            )
        elif department == "sales":
            self_state = cls._compact_long_run_sales_state(
                self_state,
                round_id=round_id,
                recent_history_items=recent_history_items,
                max_open_records=max_open_records,
            )

        projection = {
            "agent_context_projection": {
                "schema_version": "long_run_agent_context.v1",
                "enabled": True,
                "authoritative_for_agent_decision": True,
                "full_state_retained_for_execution_and_visualization": True,
                "recent_history_items": recent_history_items,
                "max_open_records": max_open_records,
            },
            "department": payload.get("department", department),
            "round_id": payload.get("round_id", round_id),
            "agent_decision_brief": payload.get("agent_decision_brief") or {},
            "policy_context": payload.get("policy_context") or {},
            "self_state": self_state,
            "simulation_context": cls._compact_long_run_simulation_context(
                payload.get("simulation_context")
            ),
            "target": payload.get("target"),
            "target_reason": payload.get("target_reason"),
            "evaluation": payload.get("evaluation"),
        }
        return projection

    @classmethod
    def _build_long_run_blackboard_projection(
        cls,
        payload: Dict[str, Any],
        department: str,
    ) -> Dict[str, Any]:
        return {
            "agent_context_projection": {
                "schema_version": "long_run_blackboard_context.v1",
                "enabled": True,
                "policy_context_source": "department_state.policy_context",
                "department": department,
            },
            "round_id": payload.get("round_id"),
            "simulation_context": cls._compact_long_run_simulation_context(
                payload.get("simulation_context")
            ),
            "departments": payload.get("departments") or {},
        }

    def _materialize_long_run_agent_context(
        self,
        *,
        state_path: Path,
        blackboard_path: Path,
        department: str,
        round_id: int,
    ) -> tuple[Path, Path, bool]:
        policy = self._long_run_agent_context_compaction_policy()
        if not policy:
            return state_path, blackboard_path, False
        try:
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            blackboard_payload = json.loads(blackboard_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return state_path, blackboard_path, False

        projection_dir = (
            self.workspace_dir
            / "projections"
            / "agent_context"
            / f"day{round_id}"
            / self.enterprise_spec.enterprise_name
            / department
        )
        projection_dir.mkdir(parents=True, exist_ok=True)
        projected_state_path = projection_dir / f"{department}.json"
        projected_blackboard_path = projection_dir / "blackboard.json"
        projected_state_path.write_text(
            json.dumps(
                self._build_long_run_department_context_projection(
                    state_payload,
                    department,
                    round_id,
                    policy,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        projected_blackboard_path.write_text(
            json.dumps(
                self._build_long_run_blackboard_projection(
                    blackboard_payload,
                    department,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return projected_state_path, projected_blackboard_path, True

    def _coordination_profile(self) -> Dict[str, Any]:
        contract = self._runtime_contract()
        return (
            ((contract["profiles"].get("capabilities") or {}).get("coordination"))
            or {}
        )

    def _communication_enabled(self) -> bool:
        profile = self._coordination_profile()
        return bool(
            profile.get("blackboard_enabled")
            or str(profile.get("communication_validation") or "off") != "off"
        )

    def _history_projection_day(self, round_id: int) -> int:
        return max(0, int(round_id) - 1)

    def _history_projection_path(self, round_id: int) -> Path:
        return (
            self.workspace_dir
            / "projections"
            / "history"
            / f"day{self._history_projection_day(round_id)}"
            / self.enterprise_spec.enterprise_name
            / "history_projection.json"
        )

    def _history_projection_expected(self) -> bool:
        return self._analysis_profile().get("profile") == "historical_diagnosis"

    def _cobweb_profit_objective_contract(self) -> Dict[str, Any]:
        contract = self._runtime_contract()
        scenario_config = contract.get("scenario_config") or {}
        simulation = scenario_config.get("simulation") or {}
        cobweb_config = simulation.get("cobweb_config") or {}
        runtime_injection = scenario_config.get("runtime_injection") or {}
        profit_policy = runtime_injection.get("profit_objective_policy") or {}
        if not (
            (
                simulation.get("market_demand_mode") == "cobweb"
                or cobweb_config.get("enabled") is True
            )
            and cobweb_config.get("production_response_mode")
            == "agent_endogenous"
            and cobweb_config.get("decision_profile") == "profit_balanced"
            and profit_policy.get("enabled") is True
        ):
            return {}
        return {
            "cobweb_config": cobweb_config,
            "profit_policy": profit_policy,
            "long_run_policy": runtime_injection.get(
                "long_run_experiment_policy"
            )
            or {},
        }

    def cobweb_profit_objective_enabled(self) -> bool:
        return bool(self._cobweb_profit_objective_contract())

    @staticmethod
    def _select_mapping_fields(
        payload: Any,
        fields: List[str],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        return {
            field: payload.get(field)
            for field in fields
            if field in payload
        }

    @staticmethod
    def _num(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sum_order_quantity(orders: Any, *, round_id: int) -> float:
        total = 0.0
        if not isinstance(orders, list):
            return total
        for order in orders:
            if not isinstance(order, dict):
                continue
            quantity = SkillRunner._num(order.get("quantity"), 0.0)
            if quantity <= 0:
                continue
            deadline = order.get("delivery_deadline")
            try:
                if deadline not in (None, "") and int(round_id) > int(deadline):
                    continue
            except (TypeError, ValueError):
                pass
            total += quantity
        return total

    @staticmethod
    def _inventory_quantity(observation: Dict[str, Any], item_id: str) -> float:
        inventory = observation.get("inventory") or {}
        for item in inventory.get("inventory_items") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("item_id") or "") == str(item_id):
                return SkillRunner._num(item.get("quantity"), 0.0)
        return 0.0

    @staticmethod
    def _line_status_count(production_lines: Dict[str, Any], statuses: set[str]) -> float:
        by_status = production_lines.get("by_status") or {}
        if isinstance(by_status, dict):
            total = sum(
                SkillRunner._num(by_status.get(status), 0.0)
                for status in statuses
            )
            if total > 0:
                return total
        count = 0.0
        for line in production_lines.get("details") or []:
            if not isinstance(line, dict):
                continue
            if str(line.get("status") or "").lower() in statuses:
                count += 1.0
        return count

    @staticmethod
    def _build_single_enterprise_capacity_expansion_signal(
        observation: Dict[str, Any],
        chart_export: Dict[str, Any],
        *,
        round_id: int,
    ) -> Dict[str, Any]:
        production = observation.get("production") or {}
        sales = observation.get("sales") or {}
        production_lines = production.get("production_lines") or {}
        if not isinstance(production_lines, dict):
            production_lines = {}

        charts = chart_export.get("charts") or {}
        capacity_chart = charts.get("capacity_utilization_analysis") or {}
        series = capacity_chart.get("series") or {}
        utilization_history = [
            SkillRunner._num(value, 0.0)
            for value in (series.get("capacity_utilization_percent") or [])[-3:]
        ]
        total_capacity_history = [
            SkillRunner._num(value, 0.0)
            for value in (series.get("total_capacity") or [])[-3:]
        ]
        available_capacity_history = [
            SkillRunner._num(value, 0.0)
            for value in (series.get("available_capacity") or [])[-3:]
        ]

        total_capacity = SkillRunner._num(
            production_lines.get("total_capacity"),
            SkillRunner._num(production.get("total_capacity"), 0.0),
        )
        available_capacity = SkillRunner._num(
            production_lines.get("available_capacity"),
            SkillRunner._num(production.get("available_capacity"), total_capacity),
        )
        occupied_capacity = SkillRunner._num(
            production_lines.get("occupied_capacity"),
            max(0.0, total_capacity - available_capacity),
        )
        current_utilization_percent = SkillRunner._num(
            (production.get("production_metrics") or {}).get("capacity_utilization"),
            0.0,
        )
        if current_utilization_percent <= 1.5:
            current_utilization_percent *= 100
        if total_capacity > 0 and current_utilization_percent <= 0:
            current_utilization_percent = min(
                100.0,
                max(0.0, occupied_capacity / max(total_capacity, 1.0) * 100),
            )
        if not utilization_history and current_utilization_percent > 0:
            utilization_history = [current_utilization_percent]
        if not total_capacity_history:
            total_capacity_history = [total_capacity]
        if not available_capacity_history:
            available_capacity_history = [available_capacity]

        recent_high_utilization_rounds = sum(
            1 for value in utilization_history if value >= 85.0
        )
        recent_zero_available_rounds = sum(
            1 for value in available_capacity_history if value <= 0.0
        )
        avg_recent_utilization = (
            sum(utilization_history) / len(utilization_history)
            if utilization_history
            else current_utilization_percent
        )
        low_total_capacity = total_capacity <= 500.0

        sales_orders = sales.get("sales_orders") or {}
        committed_order_quantity = 0.0
        valid_available_order_quantity = 0.0
        if isinstance(sales_orders, dict):
            for bucket in ("accepted", "in_progress", "backlog"):
                committed_order_quantity += SkillRunner._sum_order_quantity(
                    sales_orders.get(bucket) or [],
                    round_id=round_id,
                )
            valid_available_order_quantity = SkillRunner._sum_order_quantity(
                sales_orders.get("available") or [],
                round_id=round_id,
            )
        demand_backlog = sales.get("demand_backlog") or {}
        committed_order_quantity += SkillRunner._num(
            demand_backlog.get("total_backlog_quantity"),
            0.0,
        )
        sales_metrics = sales.get("sales_metrics") or {}
        committed_order_quantity += SkillRunner._num(
            sales_metrics.get("confirmed_order_backlog_quantity"),
            0.0,
        )
        lost_sales_quantity = SkillRunner._num(
            sales_metrics.get("lost_sales_quantity"),
            0.0,
        )
        total_downstream_demand = SkillRunner._num(
            sales_metrics.get("total_downstream_demand"),
            0.0,
        )
        product_inventory = SkillRunner._inventory_quantity(
            observation,
            "PRODUCT_1",
        )
        low_stock_with_demand_signal = (
            product_inventory < 60.0
            and (
                lost_sales_quantity > 0
                or total_downstream_demand > 0
                or committed_order_quantity > 0
                or valid_available_order_quantity > 0
            )
        )
        demand_or_stock_pressure = (
            committed_order_quantity > 0
            or valid_available_order_quantity > 0
            or low_stock_with_demand_signal
        )

        ready_lines = SkillRunner._line_status_count(
            production_lines,
            {"idle", "ready", "available"},
        )
        building_lines = SkillRunner._line_status_count(
            production_lines,
            {"under_construction", "building", "pending", "planned"},
        )
        total_lines = SkillRunner._num(
            production_lines.get("total"),
            float(len(production_lines.get("details") or [])),
        )
        cash_guard = production.get("cash_guard") or {}
        cash_hard_blocked = str(cash_guard.get("guard_level") or "").lower() in {
            "hard_blocked",
            "blocked",
            "critical",
        }
        history_pressure = (
            recent_high_utilization_rounds >= 2
            or recent_zero_available_rounds >= 2
            or avg_recent_utilization >= 80.0
        )
        no_current_capacity = available_capacity <= 0 or ready_lines <= 0
        should_prioritize = bool(
            low_total_capacity
            and demand_or_stock_pressure
            and building_lines <= 0
            and not cash_hard_blocked
            and (history_pressure or no_current_capacity or total_lines <= 0)
        )
        reason_parts = []
        if should_prioritize:
            reason_parts.append("低总产能且近期产能压力持续")
        if demand_or_stock_pressure:
            reason_parts.append("存在订单/可接需求或成品库存低位")
        if no_current_capacity:
            reason_parts.append("当前无可用产能或可用产线")
        if building_lines > 0:
            reason_parts.append("已有产线在建，避免重复扩线")
        if cash_hard_blocked:
            reason_parts.append("现金硬阻断，不能优先扩线")
        return {
            "enabled": True,
            "should_prioritize_build_line_review": should_prioritize,
            "recommended_action_when_feasible": (
                "build_production_line" if should_prioritize else None
            ),
            "reason": "；".join(reason_parts) or "未形成明确扩线优先信号",
            "thresholds": {
                "high_utilization_percent": 85,
                "avg_recent_utilization_percent": 80,
                "low_total_capacity_threshold": 500,
                "low_finished_goods_threshold": 60,
            },
            "evidence": {
                "round_id": round_id,
                "recent_utilization_percent": utilization_history,
                "recent_total_capacity": total_capacity_history,
                "recent_available_capacity": available_capacity_history,
                "recent_high_utilization_rounds": recent_high_utilization_rounds,
                "recent_zero_available_rounds": recent_zero_available_rounds,
                "avg_recent_utilization_percent": round(avg_recent_utilization, 2),
                "current_total_capacity": total_capacity,
                "current_available_capacity": available_capacity,
                "ready_line_count": ready_lines,
                "building_line_count": building_lines,
                "total_line_count": total_lines,
                "committed_order_quantity": committed_order_quantity,
                "valid_available_order_quantity": valid_available_order_quantity,
                "product_inventory": product_inventory,
                "lost_sales_quantity": lost_sales_quantity,
                "total_downstream_demand": total_downstream_demand,
                "cash_guard_level": cash_guard.get("guard_level"),
            },
        }

    @staticmethod
    def _compact_cobweb_order(
        order: Any,
        round_id: int,
    ) -> Dict[str, Any]:
        if not isinstance(order, dict):
            return {}
        compact = SkillRunner._select_mapping_fields(
            order,
            [
                "order_id",
                "product_id",
                "quantity",
                "unit_price",
                "total_amount",
                "source_type",
                "created_time",
                "delivery_deadline",
                "offer_expiry_day",
                "breach_penalty_enabled",
                "breach_penalty_per_unit",
                "status",
            ],
        )
        created_time = order.get("created_time")
        deadline = order.get("delivery_deadline")
        try:
            compact["age_rounds"] = max(0, int(round_id) - int(created_time))
        except (TypeError, ValueError):
            compact["age_rounds"] = None
        try:
            compact["deadline_status"] = (
                "expired" if int(round_id) > int(deadline) else "open"
            )
        except (TypeError, ValueError):
            compact["deadline_status"] = "unknown"
        return compact

    def _raw_analyst_observation_path(self, round_id: int) -> Path:
        return (
            self.workspace_dir
            / "enterprises"
            / self.enterprise_spec.enterprise_name
            / "observations"
            / f"observation_day{round_id}.txt"
        )

    def _compact_cobweb_analyst_observation_path(self, round_id: int) -> Path:
        return (
            self.workspace_dir
            / "projections"
            / "agent_context"
            / f"day{round_id}"
            / self.enterprise_spec.enterprise_name
            / "cobweb_c3_analyst_observation.json"
        )

    def _compact_long_run_analyst_observation_path(self, round_id: int) -> Path:
        return (
            self.workspace_dir
            / "projections"
            / "agent_context"
            / f"day{round_id}"
            / self.enterprise_spec.enterprise_name
            / "long_horizon_analyst_observation.json"
        )

    def _build_long_run_analyst_observation(
        self,
        observation: Dict[str, Any],
        history_projection: Dict[str, Any],
        round_id: int,
    ) -> Dict[str, Any]:
        policy = self._long_run_agent_context_compaction_policy()
        if not policy:
            return observation
        recent_limit = max(1, int(policy.get("recent_history_items") or 4))
        open_limit = max(8, int(policy.get("max_open_records") or 48))

        procurement_raw = observation.get("procurement") or {}
        procurement = self._compact_long_run_procurement_state(
            procurement_raw,
            recent_history_items=recent_limit,
            max_open_records=open_limit,
        )
        proposal_history = procurement_raw.get("proposal_history") or []
        procurement["proposals_list"] = self._bounded_records(
            procurement_raw.get("proposals_list") or [],
            open_limit,
        )
        procurement["proposal_history_summary"] = {
            "total": len(proposal_history) if isinstance(proposal_history, list) else 0,
        }
        procurement["recent_proposal_history"] = self._bounded_records(
            proposal_history,
            recent_limit,
            keep_tail=True,
        )
        procurement.pop("proposal_history", None)

        sales_raw = observation.get("sales") or {}
        sales = self._compact_long_run_sales_state(
            sales_raw,
            round_id=round_id,
            recent_history_items=recent_limit,
            max_open_records=open_limit,
        )
        sales_proposal_history = sales_raw.get("proposal_history") or []
        sales["proposal_history_summary"] = {
            "total": (
                len(sales_proposal_history)
                if isinstance(sales_proposal_history, list)
                else 0
            ),
        }
        sales["recent_proposal_history"] = self._bounded_records(
            sales_proposal_history,
            recent_limit,
            keep_tail=True,
        )
        sales.pop("proposal_history", None)

        production_raw = observation.get("production") or {}
        production = {
            key: value
            for key, value in production_raw.items()
            if key != "production_plans"
        }
        compact_plans: Dict[str, Any] = {}
        plan_history_summary: Dict[str, int] = {}
        open_plan_buckets = {"created", "pending", "in_progress", "active"}
        for bucket, records in (production_raw.get("production_plans") or {}).items():
            if not isinstance(records, list):
                compact_plans[bucket] = records
            elif str(bucket).lower() in open_plan_buckets:
                compact_plans[bucket] = self._bounded_records(records, open_limit)
            else:
                plan_history_summary[bucket] = len(records)
                if records:
                    compact_plans[f"recent_{bucket}"] = self._bounded_records(
                        records,
                        recent_limit,
                        keep_tail=True,
                    )
        compact_plans["history_summary"] = plan_history_summary
        production["production_plans"] = compact_plans

        hr_raw = observation.get("hr") or {}
        hr = dict(hr_raw)
        employees = hr_raw.get("employees") or []
        hr["employees"] = self._bounded_records(employees, open_limit)
        hr["employees_summary"] = {
            "total": len(employees) if isinstance(employees, list) else 0,
            "included": len(hr["employees"]),
        }

        history_days = history_projection.get("days") or []
        recent_history_days = []
        for day in history_days[-recent_limit:]:
            if isinstance(day, dict):
                recent_history_days.append({
                    "round_id": day.get("round_id", day.get("day")),
                    "department_metrics": day.get("department_metrics") or {},
                })

        enterprise_policy = observation.get("enterprise_policy_context") or {}
        department_policies = observation.get("policy_context_by_department") or {}
        representative_policy = (
            department_policies.get("finance")
            or department_policies.get("production")
            or next(iter(department_policies.values()), {})
        )
        return {
            "schema_version": "long_horizon_analyst_observation.v1",
            "enterprise_id": observation.get("enterprise_id"),
            "round_id": int(round_id),
            "input_contract": {
                "scope": "E1_long_horizon_agent_analysis",
                "raw_observation_archived": True,
                "raw_observation_must_not_be_read_by_agent": True,
                "full_state_retained_for_execution_and_visualization": True,
                "recent_history_items": recent_limit,
                "max_open_records_per_bucket": open_limit,
            },
            "finance": observation.get("finance") or {},
            "production": production,
            "procurement": procurement,
            "inventory": observation.get("inventory") or {},
            "sales": sales,
            "hr": hr,
            "simulation_context": self._compact_long_run_simulation_context(
                observation.get("simulation_context")
            ),
            "external_change_review": self._build_long_run_external_change_review(
                observation.get("simulation_context") or {},
                round_id,
            ),
            "policy_context": {
                "schema_version": enterprise_policy.get("schema_version"),
                "scenario_id": enterprise_policy.get("scenario_id"),
                "enabled_modes": enterprise_policy.get("enabled_modes") or [],
                "analyst_contract": enterprise_policy.get("analyst_contract"),
                "active_modes": representative_policy.get("active_modes") or {},
                "decision_weights": representative_policy.get("decision_weights") or {},
                "priority_rules": representative_policy.get("priority_rules") or [],
            },
            "recent_history": {
                "source_day_range": history_projection.get("source_day_range"),
                "no_future_data": history_projection.get("no_future_data"),
                "trends": history_projection.get("trends") or {},
                "latest_days": recent_history_days,
            },
        }

    def _prepare_long_run_analyst_observation(self, round_id: int) -> Path:
        raw_path = self._raw_analyst_observation_path(round_id)
        if not raw_path.exists():
            raise FileNotFoundError(f"E1 analyst observation missing: {raw_path}")
        observation = MultiTenantUtils._read_json_if_exists(raw_path, {})
        if not isinstance(observation, dict) or not observation:
            raise ValueError(f"E1 analyst observation is invalid: {raw_path}")
        history_projection = MultiTenantUtils._read_json_if_exists(
            self._history_projection_path(round_id),
            {},
        )
        compact_path = self._compact_long_run_analyst_observation_path(round_id)
        MultiTenantUtils._write_json(
            compact_path,
            self._build_long_run_analyst_observation(
                observation,
                history_projection,
                round_id,
            ),
        )
        return compact_path

    def _build_cobweb_profit_analyst_observation(
        self,
        observation: Dict[str, Any],
        history_projection: Dict[str, Any],
        round_id: int,
    ) -> Dict[str, Any]:
        objective_contract = self._cobweb_profit_objective_contract()
        if not objective_contract:
            return observation

        finance = observation.get("finance") or {}
        production = observation.get("production") or {}
        sales = observation.get("sales") or {}
        inventory = observation.get("inventory") or {}
        hr = observation.get("hr") or {}
        production_lines = production.get("production_lines") or {}
        sales_orders = sales.get("sales_orders") or {}
        demand_backlog = sales.get("demand_backlog") or {}
        production_plans = production.get("production_plans") or {}
        if not isinstance(production_lines, dict):
            production_lines = {}
        if not isinstance(production_plans, dict):
            production_plans = {}
        if not isinstance(sales_orders, dict):
            sales_orders = {}
        if not isinstance(demand_backlog, dict):
            demand_backlog = {}

        available_orders = [
            self._compact_cobweb_order(order, round_id)
            for order in (sales_orders.get("available") or [])
            if isinstance(order, dict)
        ]
        available_orders = [
            order for order in available_orders if order.get("order_id")
        ]

        safe_recovery_candidates = []
        for candidate in (
            (production.get("recovery_guard") or {}).get("candidates") or []
        ):
            compact = self._select_mapping_fields(
                candidate,
                [
                    "product_id",
                    "on_hand",
                    "demand_backlog_quantity",
                    "confirmed_order_backlog_quantity",
                    "stale_backlog_quantity",
                    "material_feasible_quantity",
                    "capacity_feasible_quantity",
                    "blocking_reasons",
                    "material_shortages",
                ],
            )
            if compact:
                safe_recovery_candidates.append(compact)

        safe_margin_candidates = []
        for candidate in (
            (production.get("margin_guard") or {}).get("candidates") or []
        ):
            compact = self._select_mapping_fields(
                candidate,
                [
                    "product_id",
                    "estimated_sale_unit_price",
                    "estimated_unit_cost",
                    "estimated_unit_margin",
                    "projected_revenue",
                    "projected_total_cost",
                    "projected_gross_profit",
                    "margin_ratio",
                    "cash_feasible",
                    "material_feasible",
                    "capacity_feasible",
                    "hard_blocked",
                    "blocking_reasons",
                ],
            )
            if compact:
                safe_margin_candidates.append(compact)

        history_days = history_projection.get("days") or []
        recent_history_days = []
        for day in history_days[-3:]:
            if not isinstance(day, dict):
                continue
            recent_history_days.append({
                "round_id": day.get("round_id", day.get("day")),
                "department_metrics": day.get("department_metrics") or {},
            })

        profit_policy = objective_contract["profit_policy"]
        return {
            "schema_version": "cobweb_c3_analyst_observation.v1",
            "enterprise_name": self.enterprise_spec.enterprise_name,
            "enterprise_id": observation.get("enterprise_id")
            or getattr(
                self.enterprise_spec,
                "enterprise_id",
                self.enterprise_spec.enterprise_name,
            ),
            "round_id": round_id,
            "input_contract": {
                "scope": "cobweb_c3_profit_objective_only",
                "raw_observation_archived": True,
                "raw_observation_must_not_be_read_by_agent": True,
                "prescriptive_quantity_fields_removed": True,
                "completed_order_histories_summarized": True,
                "analysis_must_use_current_round": True,
            },
            "objective_policy": {
                "planning_horizon_rounds": profit_policy.get(
                    "planning_horizon_rounds",
                    8,
                ),
                "objective_weights": profit_policy.get("objective_weights") or {},
                "decision_contract": profit_policy.get("decision_contract") or {},
            },
            "finance_state": self._select_mapping_fields(
                finance,
                [
                    "cash",
                    "total_revenue",
                    "total_cost",
                    "financial_indicators",
                    "cash_summary",
                ],
            ),
            "market_state": self._select_mapping_fields(
                production.get("cobweb_decision_signal")
                or observation.get("cobweb_decision_signal")
                or {},
                [
                    "round_id",
                    "product_id",
                    "current_market_price",
                    "lagged_price",
                    "planned_supply_quantity",
                    "market_supply_quantity",
                    "actual_supply_quantity",
                    "external_order_quantity",
                    "equilibrium_price",
                    "equilibrium_quantity",
                    "price_deviation_from_equilibrium",
                    "quantity_deviation_from_equilibrium",
                    "suggested_supply_direction",
                    "market_supply_source",
                    "stability_label",
                ],
            ),
            "production_state": {
                "products": production.get("products_idList") or [],
                "lines": {
                    **self._select_mapping_fields(
                        production_lines,
                        [
                            "total",
                            "by_status",
                            "total_capacity",
                            "available_capacity",
                            "occupied_capacity",
                        ],
                    ),
                    "details": [
                        self._select_mapping_fields(
                            item,
                            [
                                "line_id",
                                "line_type",
                                "capacity",
                                "remaining_capacity",
                                "total_produced",
                            ],
                        )
                        for item in (production_lines.get("details") or [])[:8]
                        if isinstance(item, dict)
                    ],
                },
                "metrics": production.get("production_metrics") or {},
                "plan_status_counts": {
                    key: len(value) if isinstance(value, list) else 0
                    for key, value in production_plans.items()
                },
                "cash_guard": self._select_mapping_fields(
                    production.get("cash_guard") or {},
                    [
                        "guard_level",
                        "available_conversion_budget",
                        "current_cash",
                        "warning_threshold",
                        "hard_blocked",
                    ],
                ),
                "recovery_feasibility": safe_recovery_candidates,
                "unit_economics": safe_margin_candidates,
            },
            "sales_state": {
                "order_status_counts": {
                    key: len(value) if isinstance(value, list) else 0
                    for key, value in sales_orders.items()
                },
                "available_orders": available_orders,
                "metrics": sales.get("sales_metrics") or {},
                "backlog_by_product": demand_backlog.get("by_product") or {},
            },
            "inventory_state": {
                "items": [
                    self._select_mapping_fields(
                        item,
                        [
                            "item_id",
                            "item_type",
                            "quantity",
                            "unit_price",
                            "total_value",
                            "safety_stock",
                            "reorder_point",
                            "is_low_stock",
                            "is_below_reorder_point",
                        ],
                    )
                    for item in (inventory.get("inventory_items") or [])
                    if isinstance(item, dict)
                ],
                "metrics": inventory.get("inventory_metrics") or {},
                "warehouse_capacity": inventory.get("warehouse_capacity"),
                "used_capacity": inventory.get("used_capacity"),
                "warehouse_utilization": inventory.get(
                    "warehouse_utilization"
                ),
            },
            "staffing_state": {
                "department_staffing": hr.get("department_staffing") or {},
                "total_payroll": hr.get("total_payroll"),
                "recruitment_status": hr.get("recruitment_status"),
            },
            "recent_history": {
                "source_day_range": history_projection.get("source_day_range"),
                "no_future_data": history_projection.get("no_future_data"),
                "trends": history_projection.get("trends") or {},
                "latest_days": recent_history_days,
            },
        }

    def _prepare_cobweb_profit_analyst_observation(
        self,
        round_id: int,
    ) -> Path:
        raw_path = self._raw_analyst_observation_path(round_id)
        if not raw_path.exists():
            raise FileNotFoundError(
                f"Cobweb C3 analyst observation missing: {raw_path}"
            )
        observation = MultiTenantUtils._read_json_if_exists(raw_path, {})
        if not isinstance(observation, dict) or not observation:
            raise ValueError(
                f"Cobweb C3 analyst observation is invalid: {raw_path}"
            )
        history_path = self._history_projection_path(round_id)
        history_projection = MultiTenantUtils._read_json_if_exists(
            history_path,
            {},
        )
        compact_payload = self._build_cobweb_profit_analyst_observation(
            observation,
            history_projection,
            round_id,
        )
        compact_path = self._compact_cobweb_analyst_observation_path(round_id)
        MultiTenantUtils._write_json(compact_path, compact_payload)
        return compact_path

    def _build_cobweb_profit_objective_analyst_prompt(self) -> str:
        objective_contract = self._cobweb_profit_objective_contract()
        if not objective_contract:
            return ""
        profit_policy = objective_contract["profit_policy"]
        objective_weights = profit_policy.get("objective_weights") or {}
        return f"""

蛛网C3盈利目标分析约束：
- 当前不是机制复现任务。价格方向只能作为市场风险证据，不得写成“高价必须扩产、低价必须停产”的命令。
- 使用最近已封口历史投影中的价格、供给、利润、履约、库存和生产调整趋势，识别未来2到3轮的经营问题；整体规划窗口为 {profit_policy.get("planning_horizon_rounds", 8)} 轮。
- 目标权重为 {json.dumps(objective_weights, ensure_ascii=False)}。阶段目标必须同时说明利润/边际收益、现金安全、服务水平以及生产调整或价格边界风险。
- 不给生产部门指定唯一精确产量；使用可解释的范围、阈值或比较条件，让生产部门结合当轮 cobweb_operating_economics 自主选择。
- 不得把理论均衡供给、recovery_guard数量或当前backlog直接当作生产答案，也不得把复现发散轨迹作为成功标准。
- 生产目标必须至少覆盖利润/成本、现金、履约/积压、稳定性/价格风险四类目标中的三类，并明确它们之间的权衡。
""".rstrip()

    def _single_enterprise_chart_export_policy(self) -> Dict[str, Any]:
        run_meta = self._read_json_file(self.workspace_dir / "run_meta.json", {})
        scenario_config = run_meta.get("scenario_config") or {}
        runtime_injection = scenario_config.get("runtime_injection") or {}
        return runtime_injection.get("single_enterprise_chart_export_policy") or {}

    def _chart_export_path(self) -> Path:
        return (
            self.workspace_dir
            / "enterprises"
            / self.enterprise_spec.enterprise_name
            / "charts_data_export.json"
        )

    def _single_enterprise_analyst_input_dir(self, round_id: int) -> Path:
        return (
            self.workspace_dir
            / "enterprises"
            / self.enterprise_spec.enterprise_name
            / "analyst_inputs"
            / f"day{round_id}"
        )

    def _prepare_single_enterprise_analyst_observation(self, round_id: int) -> Path:
        source_path = self._raw_analyst_observation_path(round_id)
        target_dir = self._single_enterprise_analyst_input_dir(round_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "observation_compact.json"
        source = MultiTenantUtils._read_json_if_exists(source_path, {})
        if not isinstance(source, dict):
            MultiTenantUtils._write_json(target_path, {})
            return target_path

        compact: Dict[str, Any] = {
            "schema_version": "single_enterprise_analyst_observation_compact.v1",
            "source_observation": str(source_path),
            "enterprise_id": source.get("enterprise_id"),
            "finance": source.get("finance") or {},
            "production": source.get("production") or {},
            "procurement": source.get("procurement") or {},
            "inventory": source.get("inventory") or {},
            "sales": source.get("sales") or {},
            "hr": source.get("hr") or {},
            "simulation_context": source.get("simulation_context") or {},
            "policy_context_summary": {},
        }
        chart_export = MultiTenantUtils._read_json_if_exists(self._chart_export_path(), {})
        if not isinstance(chart_export, dict):
            chart_export = {}
        compact["capacity_expansion_signal"] = (
            self._build_single_enterprise_capacity_expansion_signal(
                source,
                chart_export,
                round_id=round_id,
            )
        )
        if isinstance(compact.get("production"), dict):
            compact["production"]["capacity_expansion_signal"] = compact[
                "capacity_expansion_signal"
            ]
        enterprise_policy = source.get("enterprise_policy_context") or {}
        if isinstance(enterprise_policy, dict):
            compact["policy_context_summary"] = {
                "active_modes": enterprise_policy.get("active_modes") or {},
                "single_enterprise_diagnostic_policy": (
                    enterprise_policy.get("single_enterprise_diagnostic_policy") or {}
                ),
                "priority_rules": enterprise_policy.get("priority_rules") or [],
            }
        MultiTenantUtils._write_json(target_path, compact)
        return target_path

    def _prepare_single_enterprise_analyst_chart_export(self, round_id: int) -> Path:
        source_path = self._chart_export_path()
        target_dir = self._single_enterprise_analyst_input_dir(round_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "charts_data_export_compact.json"
        source = MultiTenantUtils._read_json_if_exists(source_path, {})
        if not isinstance(source, dict):
            MultiTenantUtils._write_json(target_path, {})
            return target_path

        charts = source.get("charts") or {}
        compact_charts = {}
        if isinstance(charts, dict):
            excluded = {
                "single_case_prewarm_execution",
                "department_action_statistics",
            }
            compact_charts = {
                key: value
                for key, value in charts.items()
                if key not in excluded
            }
        compact = {
            "schema_version": "single_enterprise_analyst_chart_compact.v1",
            "source_chart_export": str(source_path),
            "meta": source.get("meta") or {},
            "charts": compact_charts,
            "excluded_charts": [
                "single_case_prewarm_execution",
                "department_action_statistics",
            ],
        }
        MultiTenantUtils._write_json(target_path, compact)
        return target_path

    def _chart_export_injected_to_analyst(self) -> bool:
        policy = self._single_enterprise_chart_export_policy()
        return bool(policy.get("enabled") and policy.get("inject_to_analyst", True))

    def _single_enterprise_case_policy_for_prompt(self) -> Dict[str, Any]:
        run_meta = self._read_json_file(self.workspace_dir / "run_meta.json", {})
        mode_markers = " ".join(
            str(run_meta.get(key) or "")
            for key in (
                "orchestrator",
                "decision_regime",
                "agent_objective_profile",
                "experiment_group",
            )
        ).lower()
        if "scripted" in mode_markers:
            return {}
        scenario_config = run_meta.get("scenario_config") or {}
        runtime_injection = scenario_config.get("runtime_injection") or {}
        policy = (
            run_meta.get("single_enterprise_case")
            or scenario_config.get("single_enterprise_case")
            or runtime_injection.get("single_enterprise_case_policy")
            or {}
        )
        if not isinstance(policy, dict) or not policy.get("enabled"):
            return {}
        if (
            "single_enterprise" not in mode_markers
            and policy.get("family") != "single_enterprise_diagnostic"
        ):
            return {}
        return policy

    def _single_enterprise_agent_run_active(self) -> bool:
        return bool(self._single_enterprise_case_policy_for_prompt())

    @staticmethod
    def _agent_transport_error_summary(messages: List[dict]) -> str:
        markers = (
            "API Error:",
            "ProcessError",
            "UnexpectedQueryError",
            "Command failed with exit code",
            "Connection refused",
            "ECONNREFUSED",
        )
        snippets: List[str] = []
        for message in messages or []:
            content = str((message or {}).get("content") or "")
            if not content or not any(marker in content for marker in markers):
                continue
            compact = " ".join(content.split())
            if compact and compact not in snippets:
                snippets.append(compact[:500])
            if len(snippets) >= 3:
                break
        return " | ".join(snippets)

    def _agent_runtime_env_summary(self) -> Dict[str, str]:
        keys = (
            "ANTHROPIC_BASE_URL",
            "AGENT_GATEWAY_BASE_URL",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_MODEL_LIST",
            "NO_PROXY",
            "no_proxy",
        )
        summary: Dict[str, str] = {}
        for key in keys:
            value = os.environ.get(key)
            if value:
                summary[key] = value
        return summary

    def _claude_stderr_tail(self, role: str, max_lines: int = 8) -> List[str]:
        log_dir = self.client_dir.parent / "logs"
        if not log_dir.exists():
            return []
        paths = sorted(
            log_dir.glob("claude_stderr_*.log"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        snippets: List[str] = []
        role_marker = f"role={role}"
        for path in paths[:2]:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for line in reversed(lines):
                if role_marker not in line:
                    continue
                compact = " ".join(line.split())
                if compact and compact not in snippets:
                    snippets.append(compact[-700:])
                if len(snippets) >= max_lines:
                    return list(reversed(snippets))
        return list(reversed(snippets))

    def _single_enterprise_agent_transport_failure(
        self,
        *,
        role: str,
        round_id: int,
        messages: List[dict],
    ) -> Optional[Dict[str, Any]]:
        if not self._single_enterprise_agent_run_active():
            return None
        summary = self._agent_transport_error_summary(messages)
        if not summary:
            return None
        stderr_tail = self._claude_stderr_tail(role)
        stderr_hint = ""
        if stderr_tail:
            stderr_hint = " Stderr tail: " + " | ".join(stderr_tail[-3:])
        return {
            "status": "error",
            "message": (
                "Single-enterprise Agent Skill invocation failed before producing "
                f"a valid decision: role={role}, round={round_id}. "
                "Check ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, ANTHROPIC_MODEL_LIST "
                f"and auth token. Raw error: {summary}{stderr_hint}"
            ),
            "error_type": "agent_transport_error",
            "role": role,
            "round_id": round_id,
            "runtime_agent_env": self._agent_runtime_env_summary(),
            "claude_stderr_tail": stderr_tail,
        }

    def _build_single_enterprise_analyst_prompt(self) -> str:
        policy = self._single_enterprise_case_policy_for_prompt()
        if not policy:
            return ""

        return f"""

单企业 S0 诊断运行时补充规则：
- 当前运行已识别为单企业 Agent 诊断模式；Agent 必须只依据运行时企业数据完成诊断。
- 这些规则只在本次单企业诊断运行中生效，不属于通用 Analyst Skill 文档，也不应用于多企业场景。
- 所有单企业诊断运行使用同一套综合诊断框架；不得根据任何内部实验元信息、预设答案或部门优先级改变分析路径。
- 不得在 enterprise_summarys、department_targets 或 reason 中引用任何不来自 observation、charts_data_export、history_projection 或部门状态文件的实验元信息，也不要使用实验类别、部门优先级或预设矛盾等表述。
- 若启动提示提供 charts_data_export.json 或 history_projection.json，它们是单企业诊断的重点输入：先用其中的履约覆盖、原料覆盖、仓容压力、现金压力、需求产能缺口、订单漏斗、历史趋势来定位瓶颈，再回到 observation 和部门状态核实动作可行性。
- 不要把通用 Skill 文档中的多企业链路、企业间交易、同业聚合、共享资源治理或蛛网机制复现要求套到单企业 S0；除非 observation 的真实字段明确显示这些机制在本单企业运行中启用，否则只按单企业内部经营诊断处理。
- 必须按统一顺序全面检查：市场/真实需求、订单漏斗与履约老化、生产计划/产能/产线、原料库存位点与在途补货、采购供应商与预算、人力空闲/利用/待招聘、现金/净利润/收入成本变化/回款、库存与仓容压力。
- 若 observation.production.capacity_expansion_signal 或顶层 capacity_expansion_signal 显示 should_prioritize_build_line_review=true，必须把它作为产能诊断的优先证据：先核对近期产能占用/可用产能、当前总产能、在建产线、订单或低库存、现金和人手，再在 department_targets.production 中明确建议优先评估 build_production_line；不得仅因还能建立小批量生产计划就忽略扩线瓶颈。
- enterprise_summarys 应按证据链说明当前最主要的 1 到 3 个经营约束，并说明它们之间的因果关系，例如“市场需求不足导致订单入口偏弱”“原料覆盖不足限制排产”“产能或人手阻断履约”“现金压力限制新增支出”。
- 每个部门目标必须按本部门真实状态与职能写：有合法候选动作就给出可执行目标；没有候选动作就说明具体状态原因，例如“原料覆盖已足够”“暂无真实非零订单”“现金水平不支持新增支出”“已有待招聘覆盖缺口”。
- Sales：从真实订单、需求、金额、交期、市场覆盖、库存/近期待产和现金影响判断是否应推动 market development、accept/reject order 或保持静默；quantity<=0 或 total_amount<=0 的订单只能视为无效/占位信号。
- Procurement：从 MATERIAL_1 库存位点、生产配方需求、订单/backlog、供应商、在途补货、预算与交期判断是否采购；只把仍未到货的 pending/in_transit/ordered 采购和真实 incoming 视为补货覆盖，不要把已 received 且可能已被生产消耗的历史订单当作当前覆盖。
- Procurement 首笔恢复采购与后续滚动采购要区分：当关键原料 on_hand/inventory_position 很低、存在已接受订单/backlog 或近期待产、且没有开放在途覆盖时，优先保证最早可用到货；恢复稳定后再转向低成本补库存。
- Production：从真实订单/backlog、原料可行量、空闲产能、产线状态和可用生产人手判断是否排产或扩线；缺少任一硬条件时说明具体阻断。
- HR：从员工数量、空闲人数、利用率、待招聘和上一轮人员不足失败判断是否招聘；不要因为场景标签招聘或静默。
- Finance/Inventory：从现金、净利润、收入/成本历史变化、库存占用、仓容和履约风险判断是否需要在企业摘要中作为约束或风险写入。
- 输出仍需保留 department_targets.sales、department_targets.procurement、department_targets.production、department_targets.hr；若某部门无动作，原因必须是本部门状态原因。
""".rstrip()

    def _build_single_enterprise_department_decision_prompt(self, role: str) -> str:
        policy = self._single_enterprise_case_policy_for_prompt()
        if not policy:
            return ""

        role_key = str(role or "").strip().lower()
        if role_key not in {"procurement", "production", "sales", "hr"}:
            return ""

        lines = [
            "",
            "单企业 S0 部门决策阶段化补充：",
            "- 这段补充只适用于当前单企业 Agent 诊断运行；不要迁移到多企业判断。",
            "- 禁止在 action_reason 中引用任何不来自部门状态、blackboard 或 analysis 数据证据的实验元信息，也不要声称自己知道当前实验类型。",
            "- 只根据本部门状态文件、blackboard、analysis 中的数据证据、动作模板和可行性约束判断是否行动。",
        ]

        if role_key == "procurement":
            lines.extend([
                "- 若 MATERIAL_1 或关键原料的库存位点、真实在途补货和供应商覆盖不足以支持已接受订单/backlog/近期待产，应创建必要采购；可以在同一 JSON 中输出多个互不冲突的采购动作。",
                "- 若 self_state.supplier_candidates 或 materials_suppliers_matrix 中存在尚未注册的候选供应商，必须比较单价、起订量、processing_time、reliability_score 与物流 transit_time；supplier_name 只能选择其中真实名称。首次合法采购会建立合作关系，无需另行虚构注册动作。",
                "- 供应商处理时间与物流运输时间必须相加得到预计到货时间；先筛选能覆盖最早未满足生产/履约期限的组合，再在可行组合中比较落地总成本和可靠性。",
                "- 物流方式必须按真实紧急程度选择：road=公路，基础费100、单位费2、运输3天；rail=铁路，基础费200、单位费1.5、运输2天；air=航空，基础费500、单位费5、运输1天。原料为 0、库存位点为负、或首笔恢复采购会影响近期排产/履约时优先最快可到货组合；中等缺口用 rail；普通补库存才用 road。",
                "- 不要把历史 received 采购订单总量当作当前覆盖；只有 replenishment.pending_by_material、operational_summary.incoming 或 orders 中 pending/ordered/in_transit/confirmed/created 的开放订单可阻止重复采购。",
                "- 若已有开放在途覆盖当前缺口，不要继续重复采购；若库存位点已被生产消耗到 0 或负数且开放在途不足，即使历史上曾采购成功，也应重新采购。",
                "- 若 agent_decision_brief.procurement_recovery_signal 存在，应优先按其中的 recovery_stage、recommended_urgency、incoming_or_open_order_quantity、supplier_option_ranking 和 suggested_quantity_band 决定是否采购、采购多少、选哪个供应商和物流。",
                "- 预计到货必须能在当前可见的订单/backlog/近期待产窗口内产生作用；若慢速物流到货过晚，应选择更快组合，或在没有有效经营作用时 action_pass。",
                "- 采购数量必须能由库存位点、配方需求、订单/backlog 或生产恢复需求解释。",
            ])
        elif role_key == "production":
            lines.extend([
                "- 若 agent_decision_brief.capacity_expansion_signal.should_prioritize_build_line_review=true，应优先核对 build_production_line 模板并输出一条可执行扩线动作；只有在已有产线在建、现金/人手硬阻断、或信号证据与实时状态冲突时才 action_pass。",
                "- 产能扩线判断应使用最近几轮 capacity_expansion_signal.evidence.recent_utilization_percent / recent_available_capacity 与当前 total_capacity/available_capacity；连续高占用、零可用产能或总产能很低时，不要只尝试 create_production_plan。",
                "- 若存在真实订单/backlog、原料可行、生产人手可用且有空闲产能，优先创建 bounded PRODUCT_1 生产计划。",
                "- 若没有空闲/可用产线，且成品库存低于低库存阈值、无法覆盖真实订单/backlog、或明显低于安全缓冲，同时现金和人手没有硬阻断，应优先考虑 build_production_line。",
                "- 若已有产线在建、已有可用产能，或主要阻断来自原料/人手/现金，则不得重复扩线；扩线参数只能来自模板允许字段。",
                "- 若原料、人手或产能任一硬条件不足，应 action_pass 并在 reason 中写清具体数据阻断。",
            ])
        elif role_key == "sales":
            lines.extend([
                "- 只能接受真实非零、未过期、且可由成品库存或明确近期待产覆盖的订单；不可履约订单应 reject_order 或 action_pass。",
                "- 若有多个真实 available_orders，应比较 unit_price、quantity、offer_expiry_day、delivery_deadline、违约成本和资源占用；按预计贡献与履约可行性选择组合，而不是机械接受全部订单。",
                "- 若 agent_decision_brief.order_quality_reviews 存在，必须把其中 estimated_unit_margin、estimated_gross_margin、breach_penalty_exposure、days_to_deadline、days_to_expiry、quantity_to_uncommitted_inventory_ratio 和 risk_flags 作为订单组合筛选依据。",
                "- 当 order_quality_reviews 与通用“available 订单优先接受”规则冲突时，以 order_quality_reviews 的组合质量证据为准。",
                "- 低毛利、高违约暴露、短交期且大量占用未承诺库存/近期待产能力的订单，即使状态为 available，也应优先 reject_order 或暂不接受；高单价但会导致违约的订单也不是优质订单。",
                "- 输出多个 accept_order 时，必须按组合质量从高到低排序：先写高单位毛利/低风险/低资源占用订单，再写低质量或大占用订单；不要让低质量大单先占用库存和产能预算。",
                "- 可以在同一 JSON 中输出多个 accept_order 或 reject_order；没有“一轮只能接一个订单”的规则，但组合后的累计承诺也必须可履约。",
                "- 若 market_growth_signal.recommendation_mode=evidence_only，不存在预先计算的市场开发答案；必须比较活跃/在建市场、最近订单入口、未承诺库存、确认积压、开发成本与时长后自行判断。其它模式下才可参考 should_develop_market。市场覆盖率只能作为弱参考。",
                "- 若同轮仍有可履约 available_orders，可在 develop_market 后继续接受所有真实可履约订单；不要因存量订单长期存在而忽略市场开发。",
                "- 接受多个订单时要按已承诺库存和截止日前可完成产能逐单递减预算，不能把同一批库存或同一段产能重复用于多个订单；高收入但会导致违约的订单不属于有利订单。",
            ])
        elif role_key == "hr":
            lines.extend([
                "- 若生产、销售、采购或仓储存在人员可用数为 0、高利用率、待处理人员不足失败，且 pending recruitment 未覆盖缺口，应输出 handle_recruitment；多个部门同时有未覆盖硬缺口时可输出多个招聘动作。",
                "- 招聘部门必须来自真实人员阻断所在部门；采购执行被人手阻断写 PROCUREMENT，生产执行被人手阻断写 PRODUCTION，销售/仓储同理。",
                "- 招聘记录通常在发起后的下一工作日由每日固定结算检查到岗；若已有 pending recruitment 覆盖缺口，不要重复招聘。",
                "- 若员工数量、空闲人数、待招聘和失败记录均未显示人员硬阻断，应 action_pass。",
            ])

        return "\n".join(lines).rstrip()

    def _build_communication_prompt(
        self,
        spec: SkillRunSpec,
        round_id: int,
    ) -> str:
        if not self._communication_enabled():
            return ""
        validation_mode = str(
            self._coordination_profile().get("communication_validation")
            or "off"
        )
        requirement = (
            "必须写入，即使 messages 为空"
            if validation_mode == "strict"
            else "如需向其它部门传递信息则写入"
        )
        semantic_rule_pack = str(
            self._coordination_profile().get("semantic_rule_pack") or "none"
        )
        semantic_prompt = ""
        if semantic_rule_pack != "none":
            routes = describe_source_routes(
                semantic_rule_pack,
                spec.role.lower(),
            )
            semantic_prompt = f"""
- 当前语义规则包：{semantic_rule_pack}。
- topic 必须从对应目标允许值中选择：{routes}
- 只传递事实、约束、建议和协作请求；不得在消息中直接写入目标部门专属 action_name。
""".rstrip()
        return f"""

企业内部通信 sidecar：
- 路径：{spec.communication_file_path}
- {requirement}。
- 格式：{{"schema_version":"enterprise_communication.v1","messages":[{{"to_department":"sales","message":"...","topic":"general","priority":"medium","evidence_refs":[],"round_id":{round_id}}}]}}
- to_department 只能是本企业已启用部门；不得填写企业 ID，不得把企业内部建议伪装成外部订单或交易事件。
{semantic_prompt}
""".rstrip()

    def _read_json_file(self, path: Path, default=None) -> Any:
        return MultiTenantUtils._read_json_if_exists(path, default)

    def _build_context_audit(
        self,
        spec: SkillRunSpec,
        department: str,
        phase: str,
        round_id: int,
    ) -> Dict[str, Any]:
        audit = audit_context_files(
            department=department,
            state_path=spec.state_path,
            blackboard_path=spec.blackboard_path,
            trade_decision_card_path=spec.trade_decision_card_path,
            history_projection_path=(
                str(self._history_projection_path(round_id))
                if self._history_projection_expected()
                else None
            ),
            read_json=self._read_json_file,
        )
        payload = audit.to_dict()
        prefix = "trade_" if phase == "trade" else ""
        target = (
            Path(spec.output_file_path).parent
            / f"{prefix}skill_context_audit.json"
        )
        MultiTenantUtils._write_json(target, payload)
        payload["artifact"] = str(target)
        return payload

    def _write_skill_execution_audit(
        self,
        *,
        role: str,
        department: str,
        round_id: int,
        output_file_path: str,
        all_messages: List[dict],
        attempts: int,
        success: bool,
        fallback_used: bool,
        elapsed_seconds: float,
        context_audit: Dict[str, Any],
        execution_result: Optional[Dict[str, Any]],
        phase: str,
        analyst: bool = False,
    ) -> str:
        contract = self._runtime_contract()
        profile = self._skill_profile()
        validation_mode = str(profile.get("output_validation") or "off")
        context_validation_mode = str(
            profile.get("context_validation") or "off"
        )
        audit_dir = Path(output_file_path).parent
        if analyst:
            audit_dir = (
                audit_dir
                / "department"
                / "analyst"
                / f"day{round_id}"
            )
            audit_dir.mkdir(parents=True, exist_ok=True)
        if analyst:
            raw_messages_name = "analyst_raw_messages.json"
        elif phase == "trade":
            raw_messages_name = "trade_skill_raw_messages.json"
        else:
            raw_messages_name = "skill_raw_messages.json"
        raw_messages_path = audit_dir / raw_messages_name
        MultiTenantUtils._write_json(raw_messages_path, all_messages)

        output_payload = self._read_json_file(Path(output_file_path), {})
        if analyst:
            envelope = adapt_legacy_analysis(
                run_id=contract["run_id"],
                enterprise_id=self.enterprise_spec.enterprise_id,
                day=round_id,
                analysis=output_payload,
                output_file=output_file_path,
            )
        else:
            communications = []
            if phase == "decision":
                communication_payload = self._read_json_file(
                    Path(output_file_path).with_name(
                        f"{department}_communication.json"
                    ),
                    {},
                )
                if isinstance(communication_payload, dict):
                    communications = communication_payload.get("messages") or []
                elif isinstance(communication_payload, list):
                    communications = communication_payload
            envelope = adapt_legacy_actions(
                run_id=contract["run_id"],
                enterprise_id=self.enterprise_spec.enterprise_id,
                department=department,
                day=round_id,
                actions=output_payload,
                output_file=output_file_path,
                fallback_used=fallback_used,
                communications=communications,
            )

        validation_errors = envelope.validation_errors()
        if not Path(output_file_path).exists():
            validation_errors.append("output file is missing")
        if analyst:
            analysis_validation_error = getattr(
                self,
                "_last_analysis_validation_error",
                "",
            )
            if analysis_validation_error:
                validation_errors.append(
                    "analysis validation failed before cleanup: "
                    + analysis_validation_error
                )
        validation_warnings = []
        if validation_mode == "warn":
            validation_warnings.extend(validation_errors)
        if context_audit.get("disallowed_policy_names"):
            validation_warnings.append(
                "Context contained disallowed scenario policies: "
                + ", ".join(context_audit["disallowed_policy_names"])
            )
        if context_audit.get("missing_files"):
            validation_warnings.append(
                "Context files were missing: "
                + ", ".join(context_audit["missing_files"])
            )

        normalized_envelope = None
        if not validation_errors:
            normalized_envelope = envelope.to_dict()

        audit = SkillExecutionAudit(
            schema_version="skill_audit.v1",
            run_id=contract["run_id"],
            scenario_id=contract["scenario_id"],
            enterprise_id=self.enterprise_spec.enterprise_id,
            department=department,
            phase=phase,
            day=round_id,
            context_validation_mode=context_validation_mode,
            validation_mode=validation_mode,
            attempts=attempts,
            success=success,
            fallback_used=fallback_used,
            elapsed_seconds=round(float(elapsed_seconds), 6),
            output_file=output_file_path,
            raw_messages_artifacts=[str(raw_messages_path)],
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
            context_audit=context_audit,
            normalized_envelope=normalized_envelope,
            execution_result=execution_result,
        )
        if analyst:
            target_name = "analyst_execution_audit.json"
        elif phase == "trade":
            target_name = "trade_skill_execution_audit.json"
        else:
            target_name = "skill_execution_audit.json"
        target = audit_dir / target_name
        MultiTenantUtils._write_json(target, audit.to_dict())
        return str(target)

    def _strict_context_failure(self, context_audit: Dict[str, Any]) -> Optional[str]:
        if str(self._skill_profile().get("context_validation") or "off") != "strict":
            return None
        problems = []
        if context_audit.get("disallowed_policy_names"):
            problems.append(
                "disallowed policies="
                + ",".join(context_audit["disallowed_policy_names"])
            )
        if context_audit.get("missing_files"):
            problems.append(
                "missing files=" + ",".join(context_audit["missing_files"])
            )
        return "; ".join(problems) if problems else None

    # =========================
    # helper: spec / prompt
    # =========================

    def _build_analyst_run_spec(
        self,
        round_id: int,
    ) -> AnalystRunSpec:
        enterprise_name = self.enterprise_spec.enterprise_name
        skill_name = self.enterprise_spec.analyst_skill_name

        skill_args = f"--round_id {round_id} --enterprise_name {enterprise_name}"

        output_file_name = "analysis.json"
        output_file_path = str(
            self.workspace_dir
            / "enterprises"
            / enterprise_name
            / "analysis.json"
        )
        history_projection_day = self._history_projection_day(round_id)
        history_projection_path = str(self._history_projection_path(round_id))
        cobweb_compaction_enabled = self.cobweb_profit_objective_enabled()
        long_run_compaction_enabled = bool(
            self._long_run_agent_context_compaction_policy()
        )
        compact_observation_kind = (
            "cobweb_c3"
            if cobweb_compaction_enabled
            else "long_horizon_e1"
            if long_run_compaction_enabled
            else ""
        )
        compact_observation_enabled = bool(compact_observation_kind)
        single_case_active = bool(self._single_enterprise_case_policy_for_prompt())
        observation_path = (
            self._prepare_cobweb_profit_analyst_observation(round_id)
            if cobweb_compaction_enabled
            else self._prepare_long_run_analyst_observation(round_id)
            if long_run_compaction_enabled
            else self._prepare_single_enterprise_analyst_observation(round_id)
            if single_case_active
            else self._raw_analyst_observation_path(round_id)
        )
        if compact_observation_enabled or single_case_active:
            skill_args += f" --observation_path {observation_path}"
        chart_export_enabled = self._chart_export_injected_to_analyst()
        chart_export_path = (
            self._prepare_single_enterprise_analyst_chart_export(round_id)
            if chart_export_enabled and single_case_active
            else self._chart_export_path()
        )

        return AnalystRunSpec(
            role="Analyst",
            skill_name=skill_name,
            skill_args=skill_args,
            output_file_name=output_file_name,
            output_file_path=output_file_path,
            observation_path=str(observation_path),
            compact_observation_enabled=compact_observation_enabled,
            history_projection_path=history_projection_path,
            history_projection_day=history_projection_day,
            compact_observation_kind=compact_observation_kind,
            chart_export_path=str(chart_export_path),
            chart_export_enabled=chart_export_enabled,
        )

    def _build_analyst_launch_prompt(
        self,
        spec: AnalystRunSpec,
        round_id: int,
    ) -> str:
        single_case_prompt = self._build_single_enterprise_analyst_prompt()
        single_case_active = bool(single_case_prompt)
        cobweb_profit_prompt = (
            self._build_cobweb_profit_objective_analyst_prompt()
        )
        long_horizon_response_prompt = (
            """

E1 外部变化分析契约：
- 必须优先读取 external_change_review，而不是只复述 external_environment 的事件描述。
- 用 factor_comparison 区分“本轮新变化”“持续生效的历史变化”和“无变化”，并结合本企业最近历史判断影响来自成本变化、订单/积压压力还是二者共同作用。
- 不得把成本因子变化直接翻译成固定采购量、固定排产量或无条件调价；必须结合单位经济性、现金、库存覆盖、服务与产能说明权衡。
- analysis.json 必须额外写入顶层 external_environment_response，结构如下：
  {
    "observed_event_ids": ["已实际观察到的 event_id；没有则为空数组"],
    "active_factor_assessment": {
      "实际偏离基线的因子名": {
        "observed_value": 1.0,
        "business_implication": "对本企业的可验证影响"
      }
    },
    "impact_assessment": "用本企业经营证据说明影响及可能的混杂因素",
    "response_strategy": "未来2到3轮的条件式响应方向，不写死唯一动作",
    "review_criteria": "未来2到5轮用利润/现金/履约/库存/产能中的可量化指标复核"
  }
- department_targets 中受影响部门的 target/evaluation/reason 必须与该响应契约一致；无须动作时也要说明保持不动如何避免成本、现金或履约风险。
""".rstrip()
            if spec.compact_observation_kind == "long_horizon_e1"
            else ""
        )
        observation_prompt = (
            f"""

蛛网C3专属输入：
- 当前 observation 已裁剪为 {spec.observation_path}。
- 该文件已包含本轮经营状态和最近历史投影；它覆盖 Skill 文档中的通用 observation 示例路径。
- 只允许读取该紧凑文件，不得再读取原始 observation_day{round_id}.txt、完整订单历史或完整蛛网历史。
""".rstrip()
            if spec.compact_observation_kind == "cobweb_c3"
            else f"""

E1 长跑有界分析输入：
- 当前 observation 已投影为 {spec.observation_path}。
- 该文件保留当前可执行订单、提案、库存、产能、现金、人员和外部环境状态，并将无界历史压缩为计数、趋势及最近记录。
- 只允许读取该有界文件，不得再读取原始 observation_day{round_id}.txt、完整订单历史或完整提案历史。
- 原始完整 observation 仍用于执行、可视化与审计，不得因投影内容较少而推断真实状态缺失。
""".rstrip()
            if spec.compact_observation_kind == "long_horizon_e1"
            else ""
        )
        history_prompt = (
            """
历史诊断输入：
- 最近已封口历史已嵌入当前紧凑 observation 的 recent_history 字段。
- 不要再读取独立 history_projection 文件。
""".rstrip()
            if spec.compact_observation_enabled
            else f"""
单企业 S0 历史诊断输入（重点）：
- 最近已封口历史投影 day{spec.history_projection_day}: {spec.history_projection_path}
- 若该文件存在，必须优先读取其中的趋势字段，用于判断市场需求、订单履约、库存/原料、产能、人手、现金和采购在最近几轮的变化。
- 该历史文件只代表当前单企业自身的封口历史；不得从中推断多企业供应链、同业行为或外部企业动作。
- 若该文件不存在，说明当前轮次没有可用历史窗口，不要尝试读取未来 projection，也不要编造历史趋势。
""".rstrip()
            if single_case_active
            else f"""
历史诊断输入：
- 最近已封口历史投影 day{spec.history_projection_day}: {spec.history_projection_path}
- 若该文件存在，必须优先用其中的趋势字段辅助判断阶段问题。
- 若该文件不存在，说明当前轮次没有可用历史窗口，不要尝试读取未来 projection，也不要编造历史趋势。
""".rstrip()
        )
        chart_export_prompt = ""
        if spec.chart_export_enabled:
            chart_export_prompt = (
                f"""

单企业 S0 图表诊断输入（重点）：
- 当前轮已导出的 charts_data_export.json: {spec.chart_export_path}
- 若该文件存在，必须读取一次，并把其中 charts 下的履约覆盖、原料覆盖、仓容压力、现金压力、需求产能缺口、订单漏斗与积压老化作为主要诊断证据。
- 图表用于帮助你识别当前单企业内部的经营瓶颈与趋势；不要把它解释成多企业链路、企业间交易、同业聚合或机制复现实验。
- 先用图表定位异常，再用 observation/department 状态核实订单、库存、产能、人手、现金、供应商和动作可行性。
- 若文件不存在，不要编造图表数据，继续基于 observation/history_projection 完成单企业诊断。
""".rstrip()
                if single_case_active
                else f"""

旧单企业图表诊断输入：
- 当前轮已导出的 charts_data_export.json: {spec.chart_export_path}
- 若该文件存在，必须读取一次，并将其中 charts 下的履约覆盖、原料覆盖、仓容压力、现金压力、需求产能缺口、订单漏斗等字段作为辅助诊断输入。
- 它是配置开关启用后的兼容输入；若文件不存在，不要编造图表数据，继续基于 observation/history_projection 完成分析。
""".rstrip()
            )

        return f"""
现在是第{round_id}个模拟轮次。
你是企业 {self.enterprise_spec.enterprise_name} 的分析师，负责输出低频战略分析报告。

你的职责不是逐轮替各部门下实时操作命令，而是：
1. 识别当前企业的结构性问题、关键瓶颈与阶段机会；
2. 基于当前 observation，为未来 2 到 3 轮生成稳定、可执行的部门阶段目标；
3. 避免输出当前动作体系无法直接执行的目标；
4. 避免用过强的单轮数值锚定去放大局部波动。
5. 若 observation.simulation_context.external_environment.enabled=true，必须读取 current_turn、
   triggered_events、active_factors 和 actual_values；在事件发生轮明确识别变化，并用近期历史判断
   成本、现金、服务、库存、采购和生产是否需要调整。不得推测未公开的未来事件。
{single_case_prompt}
{cobweb_profit_prompt}
{long_horizon_response_prompt}
{observation_prompt}
{history_prompt}
{chart_export_prompt}

本次运行的真实文件路径：
- 当前 observation: {spec.observation_path}
- 最终 analysis.json 输出: {spec.output_file_path}
- 如果 Skill 文档中的示例路径仍指向 workspace_multi，应以这里列出的真实路径为准。

你必须立即调用 Skill 工具，并严格使用下面这一条，不允许省略 args，也不允许改写格式：
Skill(skill="{spec.skill_name}", args="{spec.skill_args}")

调用 skill 后，必须在 skill 内继续执行，直到成功写入 {spec.output_file_name}。
禁止只输出解释或 JSON 文本代替写文件。
""".strip()

    def _build_analyst_same_session_resume_prompt(
        self,
        spec: AnalystRunSpec,
        round_id: int,
        reason: str,
    ) -> str:
        single_case_prompt = self._build_single_enterprise_analyst_prompt()
        single_case_active = bool(single_case_prompt)
        cobweb_profit_prompt = (
            self._build_cobweb_profit_objective_analyst_prompt()
        )
        long_horizon_response_prompt = (
            """

E1 外部变化分析契约仍然有效：完成 external_environment_response，必须包含 observed_event_ids、
active_factor_assessment、impact_assessment、response_strategy、review_criteria；按 external_change_review
中的真实因子和本企业证据修正，不得写成固定动作答案。
""".rstrip()
            if spec.compact_observation_kind == "long_horizon_e1"
            else ""
        )
        observation_prompt = (
            f"""

蛛网C3专属输入仍为 {spec.observation_path}。只允许沿用该紧凑输入；
不得改读原始 observation_day{round_id}.txt、完整订单历史或完整蛛网历史。
""".rstrip()
            if spec.compact_observation_kind == "cobweb_c3"
            else f"""

E1 长跑有界分析输入仍为 {spec.observation_path}。只允许沿用该投影；
不得改读原始 observation_day{round_id}.txt、完整订单历史或完整提案历史。
""".rstrip()
            if spec.compact_observation_kind == "long_horizon_e1"
            else ""
        )
        history_prompt = (
            """
历史诊断输入：
- 最近已封口历史已嵌入紧凑 observation 的 recent_history 字段，不得读取独立 history_projection 文件。
""".rstrip()
            if spec.compact_observation_enabled
            else f"""
单企业 S0 历史诊断输入仍为重点：
- 最近已封口历史投影 day{spec.history_projection_day}: {spec.history_projection_path}
- 若文件存在，可用于补齐本企业市场需求、履约、库存/原料、产能、人手、现金和采购趋势判断；不得读取未来 projection。
- 不要把该历史输入解释成多企业链路、企业间交易或同业行为。
""".rstrip()
            if single_case_active
            else f"""
历史诊断输入：
- 最近已封口历史投影 day{spec.history_projection_day}: {spec.history_projection_path}
- 若文件存在，可用于补齐趋势判断；若不存在，不要读取未来 projection。
""".rstrip()
        )
        chart_export_prompt = ""
        if spec.chart_export_enabled:
            chart_export_prompt = (
                f"""

单企业 S0 图表诊断输入仍为重点：
- 当前轮 charts_data_export.json: {spec.chart_export_path}
- 若文件存在，必须读取一次，用于补齐履约覆盖、原料覆盖、仓容压力、现金压力、需求产能缺口、订单漏斗与积压老化判断。
- 图表只服务于当前单企业内部诊断，不要混入多企业机制、企业间交易或同业聚合解释。
""".rstrip()
                if single_case_active
                else f"""

旧单企业图表诊断输入：
- 当前轮 charts_data_export.json: {spec.chart_export_path}
- 若文件存在，必须读取一次，用于补齐履约覆盖、原料覆盖、仓容压力、现金压力、需求产能缺口、订单漏斗等判断。
""".rstrip()
            )

        return f"""
现在是第{round_id}个模拟轮次。
你仍然是企业 {self.enterprise_spec.enterprise_name} 的分析师。

你上一轮在同一个 session 中未完成目标文件写入。
失败原因：{reason}

请继续保持 analyst 的角色边界：
- 只输出低频战略背景与未来 2 到 3 轮的阶段目标；
- 不要把 analysis 写成逐轮微操命令；
- 不要输出当前动作体系不可执行的目标；
- 若 observation 无法支撑过大的精确数值，就使用更稳的阈值、区间或方向性量化指标。
{single_case_prompt}
{cobweb_profit_prompt}
{long_horizon_response_prompt}
{observation_prompt}

不要从头解释，不要输出 Markdown 代码块，不要重新做长篇分析。
优先沿用你上一轮已经完成的读取和推理结果，在当前 session 中直接补完最后缺失的步骤。

你必须继续确保以下调用规范仍然有效：
Skill(skill="{spec.skill_name}", args="{spec.skill_args}")

{history_prompt}
{chart_export_prompt}

本次运行的真实文件路径：
- 当前 observation: {spec.observation_path}
- 最终 analysis.json 输出: {spec.output_file_path}
- 如果 Skill 文档中的示例路径仍指向 workspace_multi，应以这里列出的真实路径为准。

现在只允许做与完成 {spec.output_file_name} 有关的必要操作：
1. 若最终 JSON 已经确定，则直接调用 Write 写入 {spec.output_file_name}
2. 写入后立即 Read 回读 {spec.output_file_name}
3. 若上一轮尚未完成必要读取，则补齐必要读取后立即完成写入
4. 禁止只输出解释或 JSON 文本代替写文件
""".strip()

    def _inspect_analyst_messages(
        self,
        messages: List[dict],
        spec: AnalystRunSpec,
    ) -> AnalystRunInspection:
        text = "\n".join(m["content"] for m in messages)

        skill_called = f"name='Skill'" in text and f"'skill': '{spec.skill_name}'" in text
        skill_args_ok = spec.skill_args in text

        write_called = "name='Write'" in text or 'name="Write"' in text
        write_target_ok = spec.output_file_path in text or spec.output_file_name in text

        read_output_called = (
            ("name='Read'" in text or 'name="Read"' in text)
            and spec.output_file_path in text
        )

        json_block = self._extract_last_json_block(text)
        has_json_block = json_block is not None

        if not skill_called:
            failure_type = "skill_not_called"
        elif not skill_args_ok:
            failure_type = "skill_args_missing_or_wrong"
        elif has_json_block and not write_called:
            failure_type = "json_printed_but_not_written"
        elif write_called and not write_target_ok:
            failure_type = "write_wrong_target"
        elif write_called and not read_output_called:
            failure_type = "written_but_not_readback"
        elif not write_called:
            failure_type = "stopped_before_write"
        else:
            failure_type = "unknown"

        return AnalystRunInspection(
            skill_called=skill_called,
            skill_args_ok=skill_args_ok,
            write_called=write_called,
            write_target_ok=write_target_ok,
            read_output_called=read_output_called,
            has_json_block=has_json_block,
            json_block=json_block,
            failure_type=failure_type,
        )

    def _next_analyst_prompt_by_failure(
        self,
        spec: AnalystRunSpec,
        round_id: int,
        inspection: AnalystRunInspection,
    ) -> str:
        validation_error = getattr(self, "_last_analysis_validation_error", "")
        mapping = {
            "skill_not_called": "你上一轮没有真正调用 Skill 工具。现在立即严格按指定格式调用 Skill，并在同一 session 中继续完成写文件。",
            "skill_args_missing_or_wrong": f"你上一轮调用 Skill 时缺少或改错了 args。必须严格使用 args=\"{spec.skill_args}\"。",
            "json_printed_but_not_written": f"你上一轮已经给出了最终 JSON，但没有调用 Write。不要重新分析，直接把刚才确定的 JSON 写入 {spec.output_file_name} 并回读。",
            "write_wrong_target": f"你上一轮调用了 Write，但目标路径不正确。现在把最终 JSON 写入正确文件 {spec.output_file_name} 并回读。",
            "written_but_not_readback": f"你上一轮已经写入 {spec.output_file_name}，但没有回读校验。现在立即 Read 回读目标文件并完成校验。",
            "stopped_before_write": f"你上一轮在写文件前中断了。不要重新做长篇分析，继续完成 {spec.output_file_name} 的 Write 和回读。",
            "unknown": f"你上一轮未完成 {spec.output_file_name}。不要重新开始，优先沿用已有结果完成 Write 和回读。",
        }
        if validation_error:
            mapping["unknown"] = (
                f"你上一轮写入的 {spec.output_file_name} 未通过结构/语义校验，原因："
                f"{validation_error}。必须按该原因修正后重新 Write，并立即 Read 回读校验。"
            )
        return self._build_analyst_same_session_resume_prompt(
            spec,
            round_id,
            mapping.get(inspection.failure_type, mapping["unknown"]),
        )

    def _is_valid_json_file(self, file_path: str) -> bool:
        try:
            path = Path(file_path)
            if not path.exists():
                return False
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return False
            data = json.loads(content)
            if path.name == "analysis.json":
                return self._is_valid_analysis_payload(data)
            return True
        except Exception:
            return False

    def _is_placeholder_text(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        text = value.strip()
        if not text:
            return True
        lowered = text.lower()
        return (
            lowered in {"string", "todo", "tbd", "none", "null"}
            or text in {"<...>", "...", "示例", "待填写"}
            or (text.startswith("<") and text.endswith(">"))
        )

    def _set_analysis_validation_error(self, message: str) -> bool:
        self._last_analysis_validation_error = message
        return False

    def _flatten_analysis_target_text(self, target: Dict[str, Any]) -> str:
        if not isinstance(target, dict):
            return ""
        return " ".join(
            str(target.get(field) or "")
            for field in ("target", "evaluation", "reason")
        )

    def _contains_unnegated_term(self, text: str, terms: List[str]) -> bool:
        lowered = text.lower()
        negations = (
            "不", "不得", "不要", "禁止", "避免", "暂停", "保持静默",
            "不新增", "不执行", "不启动", "不接受", "不得输出",
            "do not", "avoid", "no ", "without", "pass", "not ",
            "discourage", "discouraged", "discourages",
            "discouraged_action", "discouraged_actions",
            "against", "constraint against",
        )
        for term in terms:
            term_lower = term.lower()
            start = 0
            while True:
                idx = lowered.find(term_lower, start)
                if idx < 0:
                    break
                window = lowered[max(0, idx - 40):idx]
                after_window = lowered[idx + len(term_lower):idx + len(term_lower) + 56]
                if not any(
                    neg.lower() in window or neg.lower() in after_window
                    for neg in negations
                ):
                    return True
                start = idx + len(term_lower)
        return False

    def _validate_single_enterprise_analysis_payload(self, data: Dict[str, Any]) -> bool:
        policy = self._single_enterprise_case_policy_for_prompt()
        if not policy:
            return True

        # Hidden single-case answer keys are kept out of analysis validation.
        # This guard only prevents metadata leakage and checks output shape;
        # action preferences must come from live orders/inventory/cash/staff/
        # capacity/supplier evidence, not from case labels.
        primary_issue = ""
        discouraged_actions = set()
        targets = data.get("department_targets") or {}
        all_target_text = "\n".join(
            self._flatten_analysis_target_text(target)
            for target in targets.values()
            if isinstance(target, dict)
        )
        visible_analysis_text = "\n".join([
            str(data.get("enterprise_summarys") or ""),
            all_target_text,
        ])
        if re.search(
            r"(single_case[_\w-]*|source_primary_contradiction|primary_issue|case_id|case0[1-9]|case\s*['\"]?\s*single_case|"
            r"\b(market_insufficient|market_shortage|raw_material_shortage|material_shortage|capacity_bottleneck|staff_shortage|cash_pressure)\b|"
            r"预期主矛盾|主责部门|非主责部门)",
            visible_analysis_text,
            re.IGNORECASE,
        ):
            return self._set_analysis_validation_error(
                "analysis.json 不得引用不来自运行状态的实验元信息或部门身份优先级；请只基于订单、库存、原料、产能、人手、现金和供应商状态重新表达诊断。"
            )

        if "hr" not in targets:
            return self._set_analysis_validation_error(
                "单企业诊断需要输出 department_targets.hr，并基于真实员工、空闲人数、待招聘和人员不足失败记录评估人力动作。"
            )

        for action in sorted(discouraged_actions):
            if action and self._contains_unnegated_term(all_target_text, [action]):
                return self._set_analysis_validation_error(
                    "单企业诊断目标包含与当前状态边界不匹配的动作，请改为基于真实库存、订单、现金、产能、人员状态设定目标。"
                )

        if primary_issue in {"market_shortage", "market_insufficient"}:
            sales_text = self._flatten_analysis_target_text(targets.get("sales") or {})
            sales_text_lower = sales_text.lower()
            market_terms = ["develop_market", "开发市场", "市场开发", "市场覆盖", "真实非零需求"]
            invalid_order_terms = [
                "invalid_quantity", "quantity=0", "quantity <= 0", "零数量",
                "数量为0", "无效", "占位",
            ]
            accept_terms = [
                "accept_order", "接受订单", "接收订单", "接单",
                "orders_received", "accepted", "available状态订单被系统接收",
            ]
            if self._contains_unnegated_term(sales_text, accept_terms) and not any(
                term.lower() in sales_text_lower
                for term in market_terms
            ) and not any(
                term.lower() in sales_text_lower
                for term in invalid_order_terms
            ):
                return self._set_analysis_validation_error(
                    "Sales 目标不能把接收无效或占位订单作为增长目标；若真实非零需求不足，应基于市场覆盖、需求形成或等待真实订单来设定目标。"
                )

        if primary_issue == "cash_pressure":
            forbidden_positive_terms = [
                "create_production_plan", "build_production_line", "create_purchase_order",
                "handle_recruitment", "develop_market", "expand_warehouse",
                "生产计划", "执行首个生产", "制造", "入库", "采购补货",
                "采购订单", "招聘", "扩仓", "市场开发", "开发市场",
            ]
            if self._contains_unnegated_term(all_target_text, forbidden_positive_terms):
                return self._set_analysis_validation_error(
                    "当前现金状态不支持把生产启动、采购、招聘、扩仓或市场开发写成正向目标；请先基于现金、库存和可履约订单判断低风险动作。"
                )

        return True

    def _validate_cobweb_profit_analysis_payload(
        self,
        data: Dict[str, Any],
    ) -> bool:
        if not self.cobweb_profit_objective_enabled():
            return True

        expected_round = getattr(self, "_active_analyst_round_id", None)
        if expected_round is not None:
            try:
                payload_round = int(data.get("round_id"))
            except (TypeError, ValueError):
                return self._set_analysis_validation_error(
                    "蛛网C3 analysis.round_id 必须是当前轮次整数。"
                )
            if payload_round != int(expected_round):
                return self._set_analysis_validation_error(
                    "蛛网C3 analysis.json 必须由当轮分析生成，"
                    f"期望 round_id={expected_round}，实际为 {payload_round}。"
                )

        serialized = json.dumps(data, ensure_ascii=False).lower()
        forbidden_evidence = [
            "recommended_plan_quantity",
            "recommended_daily_capacity",
            "affordable_recovery_candidates",
        ]
        leaked_fields = [
            field for field in forbidden_evidence if field in serialized
        ]
        if leaked_fields:
            return self._set_analysis_validation_error(
                "蛛网C3分析引用了已禁止的处方式数量字段："
                + ", ".join(leaked_fields)
                + "。请改用利润、现金、履约和稳定性证据形成区间或阈值。"
            )

        production_target = (
            (data.get("department_targets") or {}).get("production") or {}
        )
        production_text = self._flatten_analysis_target_text(
            production_target
        )
        exact_quantity_patterns = [
            r"(?:生产计划数量|生产数量|计划产量|排产量)\s*"
            r"(?:等于|为|设为|固定为|必须达到|=)\s*\d+(?:\.\d+)?\s*"
            r"(?:单位|件|瓶|箱)?",
            r"(?:production|plan)\s+quantity\s*(?:is|=|at)\s*"
            r"\d+(?:\.\d+)?\s*(?:units?)?",
            r"exactly\s+\d+(?:\.\d+)?\s*(?:units?)?",
        ]
        if any(
            re.search(pattern, production_text, flags=re.IGNORECASE)
            for pattern in exact_quantity_patterns
        ):
            return self._set_analysis_validation_error(
                "蛛网C3生产阶段目标不能指定唯一精确产量；"
                "请改为范围、阈值或带条件的比较规则。"
            )

        objective_groups = [
            ("利润", "毛利", "边际", "成本", "收入", "profit", "margin", "cost", "revenue"),
            ("现金", "资金", "cash", "liquidity"),
            ("履约", "服务", "积压", "订单", "fill", "service", "backlog", "order"),
            ("稳定", "调整", "波动", "边界", "价格风险", "stability", "adjustment", "volatility", "price risk"),
        ]
        lowered = production_text.lower()
        covered_groups = sum(
            any(term.lower() in lowered for term in group)
            for group in objective_groups
        )
        if covered_groups < 3:
            return self._set_analysis_validation_error(
                "蛛网C3生产目标至少要同时覆盖三类经营证据："
                "利润/成本、现金、履约/积压、稳定性/价格风险。"
            )
        return True

    def _validate_long_horizon_analysis_payload(
        self,
        data: Dict[str, Any],
    ) -> bool:
        if not self._long_run_agent_context_compaction_policy():
            return True

        expected_round = getattr(self, "_active_analyst_round_id", None)
        if expected_round is not None:
            try:
                payload_round = int(data.get("round_id"))
            except (TypeError, ValueError):
                return self._set_analysis_validation_error(
                    "E1 analysis.round_id 必须是当前轮次整数。"
                )
            if payload_round != int(expected_round):
                return self._set_analysis_validation_error(
                    "E1 analysis.json 必须由当轮分析生成，"
                    f"期望 round_id={expected_round}，实际为 {payload_round}。"
                )

        response = data.get("external_environment_response")
        if not isinstance(response, dict):
            return self._set_analysis_validation_error(
                "E1 analysis.json 缺少 external_environment_response 对象。"
            )
        for field in (
            "impact_assessment",
            "response_strategy",
            "review_criteria",
        ):
            if (
                not isinstance(response.get(field), str)
                or self._is_placeholder_text(response.get(field))
            ):
                return self._set_analysis_validation_error(
                    f"external_environment_response.{field} 缺失或为占位文本。"
                )
        observed_event_ids = response.get("observed_event_ids")
        if not isinstance(observed_event_ids, list):
            return self._set_analysis_validation_error(
                "external_environment_response.observed_event_ids 必须是数组。"
            )
        factor_assessment = response.get("active_factor_assessment")
        if not isinstance(factor_assessment, dict):
            return self._set_analysis_validation_error(
                "external_environment_response.active_factor_assessment 必须是对象。"
            )

        review: Dict[str, Any] = {}
        if expected_round is not None:
            compact_observation = MultiTenantUtils._read_json_if_exists(
                self._compact_long_run_analyst_observation_path(
                    int(expected_round)
                ),
                {},
            )
            review = compact_observation.get("external_change_review") or {}
        latest_event = review.get("latest_event") or {}
        latest_event_id = str(latest_event.get("event_id") or "")
        if latest_event_id and latest_event_id not in {
            str(item) for item in observed_event_ids
        }:
            return self._set_analysis_validation_error(
                "external_environment_response.observed_event_ids 必须包含"
                f"当前已公开且持续相关的事件 {latest_event_id}。"
            )

        for factor in review.get("active_deviating_factors") or []:
            assessment = factor_assessment.get(str(factor))
            if not isinstance(assessment, dict):
                return self._set_analysis_validation_error(
                    "external_environment_response.active_factor_assessment "
                    f"缺少当前偏离基线的因子 {factor}。"
                )
            if (
                not isinstance(assessment.get("business_implication"), str)
                or self._is_placeholder_text(
                    assessment.get("business_implication")
                )
            ):
                return self._set_analysis_validation_error(
                    f"因子 {factor} 缺少基于本企业状态的 business_implication。"
                )
            observed_value = assessment.get("observed_value")
            if observed_value is None:
                return self._set_analysis_validation_error(
                    f"因子 {factor} 缺少 observed_value。"
                )
            try:
                float(observed_value)
            except (TypeError, ValueError):
                return self._set_analysis_validation_error(
                    f"因子 {factor} 的 observed_value 必须是数值。"
                )
        return True

    def _is_valid_analysis_payload(self, data: Any) -> bool:
        self._last_analysis_validation_error = ""
        if not isinstance(data, dict):
            return self._set_analysis_validation_error("analysis.json 顶层必须是对象。")
        for key in ("enterprise_name", "round_id", "enterprise_summarys", "department_targets"):
            if key not in data:
                return self._set_analysis_validation_error(f"analysis.json 缺少顶层字段: {key}")
        if self._is_placeholder_text(data.get("enterprise_name")):
            return self._set_analysis_validation_error("enterprise_name 为空或占位文本。")
        if self._is_placeholder_text(str(data.get("round_id"))):
            return self._set_analysis_validation_error("round_id 为空或占位文本。")
        if self._is_placeholder_text(data.get("enterprise_summarys")):
            return self._set_analysis_validation_error("enterprise_summarys 为空或占位文本。")
        targets = data.get("department_targets")
        if not isinstance(targets, dict):
            return self._set_analysis_validation_error("department_targets 必须是对象。")
        for dept in ("sales", "procurement"):
            if dept not in targets:
                return self._set_analysis_validation_error(f"department_targets 缺少 {dept}。")
        if self.enterprise_spec.enterprise_name == "Manufacturer" and "production" not in targets:
            return self._set_analysis_validation_error("Manufacturer 的 department_targets 缺少 production。")
        for dept, target in targets.items():
            if not isinstance(target, dict):
                return self._set_analysis_validation_error(f"department_targets.{dept} 必须是对象。")
            for field in ("target", "evaluation", "reason"):
                if field not in target or self._is_placeholder_text(target.get(field)):
                    return self._set_analysis_validation_error(
                        f"department_targets.{dept}.{field} 缺失或为占位文本。"
                    )
        if not self._validate_cobweb_profit_analysis_payload(data):
            return False
        if not self._validate_long_horizon_analysis_payload(data):
            return False
        return self._validate_single_enterprise_analysis_payload(data)

    def _remove_stale_output_file(self, file_path: str) -> None:
        path = Path(file_path)
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

    def _read_python_string_literal(self, text: str, start_idx: int) -> Optional[str]:
        if start_idx >= len(text) or text[start_idx] not in ("'", '"'):
            return None

        quote = text[start_idx]
        escaped = False
        for idx in range(start_idx + 1, len(text)):
            char = text[idx]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote:
                try:
                    value = ast.literal_eval(text[start_idx:idx + 1])
                    return value if isinstance(value, str) else None
                except Exception:
                    return None
        return None

    def _extract_json_blocks(self, text: str) -> List[str]:
        """提取所有 fenced JSON 块，兼容 transcript 中的转义换行。"""
        if not isinstance(text, str):
            return []
        variants = [text]
        try:
            decoded = text.encode("utf-8").decode("unicode_escape")
            if decoded != text:
                variants.append(decoded)
        except Exception:
            pass

        payloads: List[str] = []
        seen = set()
        for variant in variants:
            for pattern in (r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"):
                for match in re.finditer(pattern, variant, flags=re.DOTALL | re.IGNORECASE):
                    candidate = match.group(1).strip()
                    if not (candidate.startswith("[") or candidate.startswith("{")):
                        continue
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    payloads.append(candidate)
        return payloads

    def _extract_balanced_json_candidates(self, text: str) -> List[str]:
        """从普通文本中兜底提取完整 JSON 数组/对象。"""
        if not isinstance(text, str):
            return []
        candidates: List[str] = []
        stack: List[str] = []
        start_idx: Optional[int] = None
        in_string = False
        escaped = False
        pairs = {"[": "]", "{": "}"}

        for idx, char in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char in pairs:
                if not stack:
                    start_idx = idx
                stack.append(pairs[char])
                continue
            if stack and char == stack[-1]:
                stack.pop()
                if not stack and start_idx is not None:
                    candidate = text[start_idx:idx + 1].strip()
                    if len(candidate) >= 2:
                        candidates.append(candidate)
                    start_idx = None
        return candidates

    def _extract_json_payloads_from_messages(self, messages: List[dict]) -> List[str]:
        text = "\n".join(m.get("content", "") for m in messages)
        payloads: List[str] = []

        payloads.extend(self._extract_json_blocks(text))

        for marker in ("TextBlock(text=", "result=", "'content': ", '"content": '):
            search_from = 0
            while True:
                marker_idx = text.find(marker, search_from)
                if marker_idx < 0:
                    break

                literal_start = marker_idx + len(marker)
                payload = self._read_python_string_literal(text, literal_start)
                if payload:
                    payloads.append(payload)
                    payloads.extend(self._extract_json_blocks(payload))
                    payloads.extend(self._extract_balanced_json_candidates(payload))

                search_from = literal_start + 1

        payloads.extend(self._extract_balanced_json_candidates(text))
        return payloads

    def _is_valid_recovered_output_payload(self, data: Any, output_file_path: str) -> bool:
        output_name = Path(output_file_path).name
        if output_name == "analysis.json":
            return self._is_valid_analysis_payload(data)
        if output_name == "finance_advice.json":
            return isinstance(data, dict)
        if output_name.startswith("pre_"):
            output_name = output_name[4:]
        if output_name.endswith("_action.json"):
            dept = output_name.removesuffix("_action.json")
            return MultiTenantUtils._is_valid_action_payload(data, dept)
        return isinstance(data, (list, dict))

    def _normalize_recovered_output_payload(self, data: Any, output_file_path: str) -> Any:
        output_name = Path(output_file_path).name
        if output_name.startswith("pre_"):
            output_name = output_name[4:]
        if output_name.endswith("_action.json"):
            return MultiTenantUtils._normalize_action_payload_shape(data)
        return data

    def _extract_payload_from_printed_write_call(self, data: Any, output_file_path: str) -> Any:
        """
        兼容模型把 Write 工具调用打印成 JSON 文本而没有真正调用工具的情况。

        只接受目标路径匹配当前输出文件的 Write payload，避免误恢复其它文件内容。
        """
        if not isinstance(data, dict) or data.get("name") != "Write":
            return data

        arguments = data.get("arguments") or data.get("input") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                return data
        if not isinstance(arguments, dict):
            return data

        target_path = str(arguments.get("file_path") or "")
        expected_path = str(output_file_path)
        if target_path and target_path != expected_path and Path(target_path).name != Path(expected_path).name:
            return data

        content = arguments.get("content")
        if not isinstance(content, str) or not content.strip():
            return data
        try:
            return json.loads(content)
        except Exception:
            return data

    def _recover_output_file_from_messages(
        self,
        messages: List[dict],
        output_file_path: str,
    ) -> bool:
        for payload in reversed(self._extract_json_payloads_from_messages(messages)):
            try:
                data = json.loads(payload)
            except Exception:
                continue
            data = self._extract_payload_from_printed_write_call(data, output_file_path)
            if not isinstance(data, (list, dict)):
                continue
            if not self._is_valid_recovered_output_payload(data, output_file_path):
                continue
            data = self._normalize_recovered_output_payload(data, output_file_path)

            try:
                path = Path(output_file_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return True
            except Exception:
                return False

        return False

    def _legacy_analyst_output_path(self, enterprise_name: str) -> Path:
        return (
            self.client_dir
            / "workspace_multi"
            / "enterprises"
            / enterprise_name
            / "analysis.json"
        )

    def _recover_analyst_output_from_legacy_path(
        self,
        spec: AnalystRunSpec,
        attempt_messages: List[dict],
        attempt_started_at: float,
    ) -> Optional[str]:
        """
        Recover analyst output when a skill follows legacy workspace_multi paths
        while the active run uses an isolated workspace_jobs/run_* directory.
        """
        expected_path = Path(spec.output_file_path)
        if expected_path.exists():
            return None

        legacy_path = self._legacy_analyst_output_path(
            self.enterprise_spec.enterprise_name
        )
        if legacy_path == expected_path or not legacy_path.exists():
            return None

        text = "\n".join(str(m.get("content") or "") for m in attempt_messages)
        if str(legacy_path) not in text:
            return None

        try:
            if legacy_path.stat().st_mtime < attempt_started_at - 1.0:
                return None
            data = self._read_json_file(legacy_path, None)
            if not self._is_valid_recovered_output_payload(data, spec.output_file_path):
                return None

            expected_path.parent.mkdir(parents=True, exist_ok=True)
            expected_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return str(legacy_path)
        except Exception:
            return None

    def _write_action_pass_file(self, spec: SkillRunSpec, dept_id: str, reason: str) -> None:
        module_type_map = {
            "sales": "SalesManager",
            "procurement": "ProcurementManager",
            "production": "ProductionManager",
            "hr": "HRManager",
            "inventory": "InventoryManager",
        }
        payload = [
            {
                "action": {
                    "action_name": "action_pass",
                    "action_param": reason,
                },
                "action_reason": reason,
                "module_type": module_type_map.get(dept_id, ""),
                "executor_id": self.enterprise_spec.enterprise_name,
            }
        ]
        path = Path(spec.output_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _sanitize_long_run_fallback_text(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = re.sub(r"(?i)scripted(?:[_ -]?rules?)?", "状态决策", value)
        cleaned = re.sub(r"规则算法[：:]?", "", cleaned)
        cleaned = re.sub(r"脚本(?:规则)?[：:]?", "", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @classmethod
    def _sanitize_long_run_fallback_payload(cls, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {
                key: cls._sanitize_long_run_fallback_payload(value)
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [cls._sanitize_long_run_fallback_payload(value) for value in payload]
        return cls._sanitize_long_run_fallback_text(payload)

    def _write_long_run_state_driven_fallback_file(
        self,
        spec: SkillRunSpec,
        dept_id: str,
        round_id: int,
        *,
        need_trade: bool,
    ) -> bool:
        policy = self._long_run_experiment_policy()
        fallback_policy = policy.get("state_driven_fallback_policy") or {}
        if not (
            self._long_run_agent_failure_continuation_enabled()
            and fallback_policy.get("enabled")
            and fallback_policy.get("trigger_after_exhausted_agent_attempts", True)
        ):
            return False
        try:
            payload = self.scripted_rule_runner._build_department_action(
                dept_id,
                round_id,
                need_trade,
            )
        except Exception:
            return False
        if not isinstance(payload, list) or not payload:
            return False

        payload = self._sanitize_long_run_fallback_payload(payload)
        prefix = self._sanitize_long_run_fallback_text(
            fallback_policy.get("visible_reason_prefix")
            or "超时思考，调用兜底逻辑链路"
        )
        evidence_reason = (
            f"{prefix}：基于当前订单、库存、现金、产能、人员和履约状态形成可执行决策。"
        )
        for item in payload:
            if not isinstance(item, dict):
                continue
            original_reason = self._sanitize_long_run_fallback_text(
                item.get("action_reason") or ""
            )
            item["action_reason"] = (
                f"{evidence_reason} {original_reason}".strip()
                if original_reason
                else evidence_reason
            )
            action = item.get("action") or {}
            action_param = action.get("action_param")
            if action.get("action_name") == "action_pass" and isinstance(action_param, str):
                action["action_param"] = item["action_reason"]

        path = Path(spec.output_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        MultiTenantUtils._normalize_action_file_if_possible(path, dept_id)
        return MultiTenantUtils._is_valid_action_file(path, dept_id)

    def _write_hr_staffing_fallback_file(
        self,
        spec: SkillRunSpec,
        reason: str,
    ) -> bool:
        state = self._read_json_file(Path(spec.state_path), {}) or {}
        self_state = state.get("self_state") or {}
        department_staffing = self_state.get("department_staffing") or {}
        def safe_int(value: Any, default: int = 0) -> int:
            try:
                if value is None or value == "":
                    return default
                return int(float(value))
            except (TypeError, ValueError):
                return default

        department_aliases = {
            "PROCUREMENT": {"PROCUREMENT", "procurement", "采购", "采购部门"},
            "PRODUCTION": {"PRODUCTION", "production", "生产", "生产部门"},
            "SALES": {"SALES", "sales", "销售", "销售部门"},
            "INVENTORY": {"INVENTORY", "inventory", "仓储", "仓储部门", "库存", "库存部门"},
            "HR": {"HR", "hr", "human_resources", "人力", "人力资源", "人力资源部门"},
            "FINANCE": {"FINANCE", "finance", "财务", "财务管理", "财务管理部门"},
        }
        department_minimums = {
            "PROCUREMENT": 1,
            "PRODUCTION": 2,
            "SALES": 1,
            "INVENTORY": 1,
            "HR": 1,
            "FINANCE": 1,
        }
        department_priority = ["PROCUREMENT", "PRODUCTION", "SALES", "INVENTORY", "HR", "FINANCE"]

        def alias_key(value: Any) -> str:
            return str(value or "").strip().lower()

        def aliases_for(department_code: str) -> set:
            return {alias_key(item) for item in department_aliases.get(department_code, {department_code})}

        def read_staffing(department_code: str) -> Dict[str, Any]:
            aliases = aliases_for(department_code)
            staffing = {
                "count": 0,
                "allocated": 0,
                "available": 0,
                "pending": 0,
                "seen": False,
            }

            def apply_entry(entry: Any) -> None:
                if not isinstance(entry, dict):
                    return
                staffing["seen"] = True
                count = safe_int(entry.get("count"), staffing["count"])
                allocated = safe_int(entry.get("allocated"), staffing["allocated"])
                available = safe_int(entry.get("available"), max(0, count - allocated))
                staffing["count"] = max(staffing["count"], count)
                staffing["allocated"] = max(staffing["allocated"], allocated)
                staffing["available"] = max(staffing["available"], available)
                staffing["pending"] = max(
                    staffing["pending"],
                    safe_int(entry.get("pending_recruits"), staffing["pending"]),
                )

            if isinstance(department_staffing, dict):
                for key, entry in department_staffing.items():
                    if alias_key(key) in aliases:
                        apply_entry(entry)
            for employee in self_state.get("employees") or []:
                if isinstance(employee, dict) and alias_key(employee.get("department")) in aliases:
                    apply_entry(employee)
            pending_map = (
                (self_state.get("recruitment_status") or {}).get("pending_by_department")
                or {}
            )
            if isinstance(pending_map, dict):
                for key, value in pending_map.items():
                    if alias_key(key) in aliases:
                        staffing["pending"] = max(staffing["pending"], safe_int(value))
            return staffing

        target_text = " ".join(
            str(item or "")
            for item in (
                (state.get("agent_decision_brief") or {}).get("target"),
                state.get("target"),
                state.get("evaluation"),
                json.dumps(self_state.get("recent_failures") or {}, ensure_ascii=False),
                json.dumps(self_state.get("department_staffing") or {}, ensure_ascii=False),
            )
        ).lower()
        low_staff_signal = any(
            token in target_text
            for token in (
                "人员不足",
                "人手不足",
                "available_workers",
                "\"available\": 0",
                "\"available\":0",
                "\"count\": 0",
                "\"count\":0",
                "insufficient_staff",
            )
        )
        candidates = []
        for department_code in department_priority:
            staffing = read_staffing(department_code)
            if staffing["pending"] > 0:
                continue
            minimum = department_minimums[department_code]
            if staffing["count"] >= minimum and staffing["available"] >= minimum:
                continue
            aliases = aliases_for(department_code)
            has_department_evidence = any(alias in target_text for alias in aliases)
            if low_staff_signal or has_department_evidence:
                shortage = max(
                    1,
                    minimum - staffing["count"],
                    minimum - staffing["available"],
                )
                candidates.append((department_code, shortage, staffing))
        if not candidates:
            return False

        department_code, shortage, staffing = candidates[0]

        recruit_people = 2
        match = re.search(r"(?:at least|至少|补员|招聘)\s*(\d+)", target_text)
        if match:
            recruit_people = int(match.group(1))
        recruit_people = max(1, min(10, max(recruit_people, shortage)))

        payload = [
            {
                "action": {
                    "action_name": "handle_recruitment",
                    "action_param": {
                        "department": department_code,
                        "num_people": recruit_people,
                    },
                },
                "action_reason": (
                    "HR Skill 多次未写出合法文件，但当前 HR 状态显示存在真实部门人手缺口；"
                    f"写入保底招聘动作以恢复 {department_code} 人手。"
                    f"当前人数 {staffing.get('count', 0)}，可用人数 {staffing.get('available', 0)}。"
                    f"原失败原因：{reason}"
                ),
                "module_type": "HRManager",
                "executor_id": self.enterprise_spec.enterprise_name,
            }
        ]
        path = Path(spec.output_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True

    def _write_advisory_fallback_file(self, spec: SkillRunSpec, reason: str) -> None:
        payload = {
            "schema_version": "finance_advice.v1",
            "status": "fallback",
            "risk_summary": reason,
            "cash_position": "unknown",
            "budget_constraints": [],
            "recommended_controls": ["action_pass"],
            "evidence_refs": [],
        }
        path = Path(spec.output_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_empty_communication_sidecar(
        self,
        spec: SkillRunSpec,
        reason: str,
    ) -> None:
        path = Path(spec.communication_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "enterprise_communication.v1",
                    "messages": [],
                    "reason": reason,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )



    def _build_skill_run_spec(
        self,
        dept: DepartmentSpec,
        round_id: int,
    ) -> SkillRunSpec:
        role = dept.role
        name = dept.name
        skill_name = dept.skill_name
        enterprise_name = self.enterprise_spec.enterprise_name

        skill_args = f"--round_id {round_id} --enterprise_name {enterprise_name}"
        if dept.dept_id == "finance":
            output_file_name = "finance_advice.json"
        else:
            output_file_name = role.lower() + "_action.json"
        state_file_name = role.lower() + ".json"
        dept_dir_name = role.lower()

        enterprise_workspace = self.workspace_dir / "enterprises" / enterprise_name
        analysis_path = str(enterprise_workspace / "analysis.json")
        raw_state_path = (
            enterprise_workspace
            / "department"
            / dept_dir_name
            / f"day{round_id}"
            / state_file_name
        )
        raw_blackboard_path = (
            enterprise_workspace
            / "department"
            / "blackboard"
            / f"day{round_id}"
            / "blackboard.json"
        )
        state_path, blackboard_path, compact_context = (
            self._materialize_long_run_agent_context(
                state_path=raw_state_path,
                blackboard_path=raw_blackboard_path,
                department=dept_dir_name,
                round_id=round_id,
            )
        )
        trade_decision_card_path = None
        if dept_dir_name in {"procurement", "sales"}:
            trade_decision_card_path = str(
                enterprise_workspace
                / "department"
                / dept_dir_name
                / f"day{round_id}"
                / "trade_decision_card.json"
            )
        output_file_path = str(
            enterprise_workspace
            / "department"
            / dept_dir_name
            / f"day{round_id}"
            / output_file_name
        )
        communication_file_path = str(
            enterprise_workspace
            / "department"
            / dept_dir_name
            / f"day{round_id}"
            / f"{dept_dir_name}_communication.json"
        )
        action_template_dir = str(
            self.client_dir / ".claude" / "skills" / skill_name / "actions"
        )

        return SkillRunSpec(
            role=role,
            name=name,
            skill_name=skill_name,
            skill_args=skill_args,
            output_file_name=output_file_name,
            output_file_path=output_file_path,
            analysis_path=analysis_path,
            state_path=str(state_path),
            blackboard_path=str(blackboard_path),
            trade_decision_card_path=trade_decision_card_path,
            communication_file_path=communication_file_path,
            action_template_dir=action_template_dir,
            compact_context=compact_context,
        )

    def _is_advisory_department(self, dept: DepartmentSpec) -> bool:
        return str(dept.dept_id).lower() == "finance"

    def _build_long_horizon_department_response_prompt(self, role: str) -> str:
        if not self._long_run_agent_context_compaction_policy():
            return ""
        evidence_by_role = {
            "Procurement": "比较到岸单位成本、库存覆盖、在途数量、批量与现金占用",
            "Production": "比较增量转换成本、订单边际、产能利用、原料覆盖与库存周转",
            "Sales": "比较可履约订单边际、报价空间、服务风险与成品库存",
            "Inventory": "比较安全库存覆盖、持有成本、缺货风险与周转",
            "Finance": "比较单轮与阶段利润、现金变化、应付压力和服务风险",
            "HR": "仅在变化造成可验证工作负载或执行瓶颈时评估人员调整",
        }
        role_evidence = evidence_by_role.get(
            role,
            "比较成本、现金、库存、履约和可执行能力",
        )
        operating_guard_by_role = {
            "Procurement": (
                "优先使用 calculate_replenishment_quantity/create_replenishment_order 的覆盖建议；"
                "库存与在途已覆盖时不得重复发布采购需求，单轮新增承诺不得挤占后续现金安全垫"
            ),
            "Production": (
                "只为已确认需求和合理安全库存排产；成本上涨时先核对单位贡献，"
                "不得用扩大产量掩盖利润下降"
            ),
            "Sales": (
                "接受或响应订单前必须核对落地单位成本和正向贡献，"
                "对外部成本上涨应保护毛利但不得承诺无法履约的数量"
            ),
            "Inventory": "以周转和服务覆盖为目标，避免无需求支撑的扩仓或库存增长",
            "Finance": "同时核对累计净利润、阶段现金变化、未结采购承诺和单位贡献",
            "HR": "只有可验证工作负载持续阻断经营时才补员，避免固定成本无依据扩张",
        }
        operating_guard = operating_guard_by_role.get(
            role,
            "动作必须保持正向单位贡献并控制新增现金承诺",
        )
        return f"""
E1 外部变化响应约束：
- 必须读取 policy_context.relevant_policies.external_environment.state，并把 analysis.json.external_environment_response 作为阶段假设；实时部门状态仍是动作依据。
- 当前部门应{role_evidence}，区分外部变化影响与普通订单/积压压力。
- 事件发生或复核窗口内，action_reason 必须引用至少一个真实变化因子和一个本部门经营证据；不得只复述事件标签。
- 若证据不支持本轮动作，可以 action_pass，但要说明保持不动如何控制利润、现金、库存或履约风险。
- 不得因成本上涨机械扩大采购、补货或生产，也不得因成本上涨无条件停摆；动作方向和数量必须通过本轮可执行数据解释。
- 长跑盈利执行边界：{operating_guard}。
""".rstrip()

    def _build_launch_prompt(
        self,
        spec: SkillRunSpec,
        round_id: int,
        need_trade: bool = False
    ) -> str:
        trade_prompt = ""
        if need_trade:
            trade_prompt = "本次是 trade 二阶段：优先处理交易卡中的 proposal，在 accept_proposal_order / reject_proposal_order 中选择有效动作。"
        extra_input_prompt = ""
        if spec.trade_decision_card_path:
            extra_input_prompt = f"\n3. trade_decision_card.json: {spec.trade_decision_card_path}\n优先读取，用 action_candidates / review_queue / new_or_updated_proposals / pressure_changes 决策。"
        action_prompt = ""
        long_horizon_response_prompt = (
            self._build_long_horizon_department_response_prompt(spec.role)
        )
        compact_context_prompt = ""
        if spec.compact_context:
            compact_context_prompt = """
E1 长跑上下文约束：
- 本提示中的部门状态和 blackboard 是系统生成的当轮权威紧凑投影，完整归档仍由执行器和可视化保留。
- 必须直接使用投影中的 agent_decision_brief、policy_context、当前开放记录、近期历史摘要和跨部门摘要完成决策。
- 禁止搜索或分页读取同轮完整部门归档、累计订单历史、累计补货历史；这些历史不会提供额外可执行对象。
- 当前候选记录按 max_open_records 给出有界决策窗口，open_records_summary/filtered_non_actionable_summary 会说明覆盖范围；history_summary/recent_* 只用于趋势核对，不得据此虚构订单或 proposal id。
""".rstrip()
        if spec.role in {"Production", "Sales", "Procurement", "HR"}:
            action_prompt = f"""

{spec.role} 部门附加硬约束：
- 禁止向用户提问、请求确认或只输出 Markdown/代码块。
- 读取部门状态文件和 blackboard 后，若字段足以决策，应立即写入 {spec.output_file_name}；不要反复读取 analysis.json 或历史文件。
- 部门状态文件顶部的 agent_decision_brief 是本轮快速决策索引；优先读 offset=0 的前段内容，不要为了读取 simulation_context / herding_history / blackboard 尾部而分页通读大文件。
- 若最终 JSON 已经形成，必须直接调用 Write；系统会拒绝只打印 JSON 文本的完成方式。
""".rstrip()
        if spec.role == "Production":
            action_prompt += """
- 若处于 herding_market，空 raw_materials 是有效配置，不得围绕 recipe 补全展开长篇推理。
- 若处于 herding_market，只在 create_production_plan 与 action_pass 中选择；除非需要操作已有 plan_id，否则不要读取生产动作模板。
""".rstrip()
            runtime_contract = self._runtime_contract()
            simulation_config = (
                (runtime_contract.get("scenario_config") or {}).get("simulation")
                or {}
            )
            cobweb_config = simulation_config.get("cobweb_config") or {}
            if (
                simulation_config.get("market_demand_mode") == "cobweb"
                or cobweb_config.get("enabled") is True
            ):
                runtime_injection = (
                    (runtime_contract.get("scenario_config") or {}).get(
                        "runtime_injection"
                    )
                    or {}
                )
                profit_objective_enabled = bool(
                    (runtime_injection.get("profit_objective_policy") or {}).get(
                        "enabled"
                    )
                )
                action_prompt += """
- 蛛网模式下，production.json 顶部的 agent_decision_brief.cobweb_signal 是当轮价格信号的权威摘要；只需再核对紧随其后的 policy_context 与 self_state 可行性字段。
- simulation_context.cobweb_history 已是近期精简窗口，禁止为了寻找完整历史继续分页；全程历史只用于实验归档，不是完成本轮动作的前置条件。
- 价格方向、真实 product_id、可用产能、原料和现金足以形成动作后，立即写入 production_action.json。
""".rstrip()
                if profit_objective_enabled:
                    action_prompt += """
- 当前为盈利目标蛛网模式：价格方向只作为市场证据，不是扩产/缩产命令；必须按 objective_mode 综合利润、现金、履约、库存和调整风险形成数量。
""".rstrip()
        if spec.role == "HR":
            action_prompt += """
- 若 hr.json/analysis/blackboard 显示某部门存在真实人员缺口、可用人数为 0、高利用率、待处理人员不足失败，且 pending recruitment 未覆盖缺口，诊断窗口内必须优先输出 handle_recruitment；不要因为普通阈值未触发而 action_pass。
- handle_recruitment.action_param.department 必须写真实受阻部门；采购执行被人手阻断写 PROCUREMENT，生产执行被人手阻断写 PRODUCTION。num_people 使用状态目标或保守默认 2。
- 若没有合法招聘动作，直接按标准结构写入 action_pass；不要读取不存在的 action_pass 模板，不要输出旧版 pass_reason 顶层结构。
""".rstrip()
        if spec.role == "Sales":
            if self._cobweb_profit_objective_contract():
                action_prompt += """
- 当前为蛛网C3盈利目标模式。agent_decision_brief.available_orders 中的 unit_price、total_amount、quantity 和 deadline 是订单经济性证据，不得仅因订单 available 就自动接受。
- 若现有成品库存足以履约，正价格订单可贡献增量收入；若接受订单需要新增生产，则必须比较订单单价、估算增量生产成本、现金、交付风险与服务压力。
- deadline_status=expired 的残留订单不得接受；若有未过期订单，优先处理其中经济性和时效最合理的一项，否则用 reject_order 清理逾期残留。
- 在 accept_order / reject_order / action_pass 中选择，并在 action_reason 中说明利润或边际收益、库存覆盖和服务影响。价格方向不是接单命令。
- agent_decision_brief、精简后的 self_state.sales_orders 和 sales_metrics 足以完成本轮决策；禁止分页追读已完成订单历史或 demand_backlog 历史。
""".rstrip()
            else:
                action_prompt += """
- 若 market_growth_signal.recommendation_mode=evidence_only，应根据其中的市场数、订单入口、未承诺库存、积压、开发成本和时长自行判断是否 develop_market；不得假设系统已经给出推荐动作。其它模式下若 should_develop_market=true，才优先执行最小有效市场开发。
- 否则若 agent_decision_brief.available_orders 非空，应按价格、数量、报价有效期、交期、预计贡献和累计履约覆盖选择一个或多个订单；积极处理有利可履约订单，同时拒绝明显亏损、被其它订单支配或会造成超额承诺的订单。不要误认为一轮只能接收一个订单。
""".rstrip()
        if spec.role in {"Sales", "Procurement"} and spec.trade_decision_card_path:
            action_prompt += """
- 只能从 trade_decision_card.action_candidates 或仍处于可操作状态的 review_queue 选择 proposal；filtered_proposals 仅供审计，禁止 accept/reject。
- 若 action_candidates 为空，优先输出 action_pass，不要处理 expired、superseded、fulfilled、rejected 或已响应 proposal。
""".rstrip()
        single_case_department_prompt = self._build_single_enterprise_department_decision_prompt(spec.role)
        if spec.role == "Finance":
            history_projection_path = self._history_projection_path(round_id)
            history_projection_day = self._history_projection_day(round_id)
            action_prompt += f"""
Finance advisory 附加硬约束：
- 你只输出财务诊断 sidecar，不输出可执行动作。
- 最终输出文件必须是 {spec.output_file_path}，不是 finance_action.json。
- 如存在最近已封口历史投影 day{history_projection_day}，可读取：{history_projection_path}
- 若该文件不存在，不要读取未来 projection，也不要编造历史趋势。
- recommended_controls 只能写自然语言控制建议，不得填写 action JSON 或要求其它部门直接执行 action_name。
""".rstrip()
        communication_prompt = (
            self._build_communication_prompt(spec, round_id)
            if not need_trade
            else ""
        )
        return f"""
现在是第{round_id}个工作日。
你是企业 {self.enterprise_spec.enterprise_name} 的 {spec.role} 部门负责人。

你必须立即调用 Skill 工具，并严格使用下面这一条，不允许省略 args，也不允许改写格式：
Skill(skill="{spec.skill_name}", args="{spec.skill_args}")
{trade_prompt}

真实文件路径：
1. 部门状态文件: {spec.state_path}
2. blackboard.json: {spec.blackboard_path}
{extra_input_prompt}
{4 if not spec.trade_decision_card_path else 5}. analysis.json（低频战略背景，仅在需要长期目标或跨部门解释时参考）: {spec.analysis_path}
{5 if not spec.trade_decision_card_path else 6}. 最终输出文件: {spec.output_file_path}
{6 if not spec.trade_decision_card_path else 7}. 动作模板目录: {spec.action_template_dir}

Skill 文档中的路径若是符号路径或旧 workspace_multi 示例，必须以本启动提示中的真实绝对路径为准。动作模板按 `<动作模板目录>/<action_name>.json` 读取。

权威顺序：policy_context + 实时状态文件 / blackboard / trade_decision_card 高于 analysis.json 和自然语言通用规则。
持续演变附加规则：若 policy_context.active_modes.external_environment_evolution=true，先读取
policy_context.relevant_policies.external_environment.state 的当轮事件、当前因子和实际数值，再结合本部门
真实订单、成本、库存、现金和产能决定动作；稳定需求下不得无依据扩大订单、补货或生产波动。
{long_horizon_response_prompt}
单企业 S0 诊断附加规则：
- 若部门状态文件中的 policy_context.single_enterprise_diagnostic_policy.enabled = true，仅把它理解为“当前为单企业诊断运行”的开关；不得寻找、推断或引用内部实验编号、预设场景标签、部门优先级或预设矛盾。
- 诊断窗口内，不得为了普通经营扩张输出与当前状态相冲突的动作；是否 action_pass 只能基于本部门真实状态、动作模板和可行性约束判断。
- 禁止在 action_reason 中使用部门身份优先级作为动作或 pass 的理由。
- Sales 不得仅因为 available_orders 非空就持续 accept_order；必须先确认订单真实非零、未过期、可履约，且不会扩大当前由库存、产能、人手或现金形成的经营压力。
{single_case_department_prompt}
{compact_context_prompt}
{action_prompt}
{communication_prompt}

调用 skill 后，必须在 skill 内继续执行，直到成功写入 {spec.output_file_name}。
禁止只输出解释或 JSON 文本代替写文件。
""".strip()

    def _build_same_session_resume_prompt(
        self,
        spec: SkillRunSpec,
        round_id: int,
        reason: str,
        need_trade: bool = False,
    ) -> str:
        extra_input_prompt = ""
        if spec.trade_decision_card_path:
            extra_input_prompt = f"\n3. trade_decision_card.json: {spec.trade_decision_card_path}\n未读则补读；已读则沿用 review_queue / pressure_changes 完成交易决策。"
        communication_prompt = (
            self._build_communication_prompt(spec, round_id)
            if not need_trade
            else ""
        )
        single_case_department_prompt = self._build_single_enterprise_department_decision_prompt(spec.role)
        long_horizon_response_prompt = (
            self._build_long_horizon_department_response_prompt(spec.role)
        )
        return f"""
现在是第{round_id}个工作日。
你仍然是企业 {self.enterprise_spec.enterprise_name} 的 {spec.role} 部门负责人。

你上一轮在同一个 session 中未完成目标文件写入。
失败原因：{reason}

不要从头解释，不要输出 Markdown 代码块，不要重新做长篇分析。
优先沿用你上一轮已经完成的读取和决策结果，在当前 session 中直接补完最后缺失的步骤。

你必须继续确保以下调用规范仍然有效：
Skill(skill="{spec.skill_name}", args="{spec.skill_args}")

真实文件路径：
1. 部门状态文件: {spec.state_path}
2. blackboard.json: {spec.blackboard_path}
{extra_input_prompt}
{4 if not spec.trade_decision_card_path else 5}. analysis.json（低频战略背景，仅在需要长期目标或跨部门解释时参考）: {spec.analysis_path}
{5 if not spec.trade_decision_card_path else 6}. 最终输出文件: {spec.output_file_path}
{6 if not spec.trade_decision_card_path else 7}. 动作模板目录: {spec.action_template_dir}

Skill 文档中的路径若是符号路径或旧 workspace_multi 示例，必须以本启动提示中的真实绝对路径为准。动作模板按 `<动作模板目录>/<action_name>.json` 读取。

权威顺序：policy_context + 实时状态文件 / blackboard / trade_decision_card 高于 analysis.json 和自然语言通用规则。
{long_horizon_response_prompt}
单企业 S0 诊断附加规则仍然有效：若 policy_context.single_enterprise_diagnostic_policy.enabled = true，只把它理解为单企业诊断运行开关；是否 action_pass 只能基于本部门真实状态、动作模板和可行性约束判断，禁止用部门身份优先级或内部实验标签作为理由。
{single_case_department_prompt}
{communication_prompt}

现在只允许做与完成 {spec.output_file_name} 有关的必要操作：
1. 若最终 JSON 已经确定，则直接调用 Write 写入 {spec.output_file_name}
2. 写入后立即 Read 回读 {spec.output_file_name}
3. 若上一轮已读取部门状态文件顶部 agent_decision_brief 或关键订单/生产信号，不要继续分页读取大文件，直接完成写入
4. 若上一轮尚未读完必要文件，只补读 offset=0 的关键前段后立即完成写入
5. 禁止只输出解释或 JSON 文本代替写文件
""".strip()

    def _build_business_repair_prompt(
        self,
        spec: SkillRunSpec,
        round_id: int,
        error_file: str,
        need_trade: bool = False,
    ) -> str:
        extra_input_prompt = ""
        if spec.trade_decision_card_path:
            extra_input_prompt = f"\n3. trade_decision_card.json: {spec.trade_decision_card_path}\n修复时优先参考 review_queue / recommended_action，避免重复处理历史 proposal。"
        communication_prompt = (
            self._build_communication_prompt(spec, round_id)
            if not need_trade
            else ""
        )
        single_case_department_prompt = self._build_single_enterprise_department_decision_prompt(spec.role)
        long_horizon_response_prompt = (
            self._build_long_horizon_department_response_prompt(spec.role)
        )
        return f"""
现在是第{round_id}个工作日。
你仍然是企业 {self.enterprise_spec.enterprise_name} 的 {spec.role} 部门负责人。

你上一轮已经生成过 {spec.output_file_name}，但业务执行失败。
错误信息文件路径：/{error_file}

不要从头重做，不要长篇解释。
请在同一个 session 中仅修复错误，并重新生成正确的 {spec.output_file_name}。

你必须继续确保以下调用规范仍然有效：
Skill(skill="{spec.skill_name}", args="{spec.skill_args}")

真实文件路径：
1. 部门状态文件: {spec.state_path}
2. blackboard.json: {spec.blackboard_path}
{extra_input_prompt}
{4 if not spec.trade_decision_card_path else 5}. analysis.json（低频战略背景，仅在需要长期目标或跨部门解释时参考）: {spec.analysis_path}
{5 if not spec.trade_decision_card_path else 6}. 最终输出文件: {spec.output_file_path}
{6 if not spec.trade_decision_card_path else 7}. 动作模板目录: {spec.action_template_dir}

Skill 文档中的路径若是符号路径或旧 workspace_multi 示例，必须以本启动提示中的真实绝对路径为准。动作模板按 `<动作模板目录>/<action_name>.json` 读取。

权威顺序：policy_context + 实时状态文件 / blackboard / trade_decision_card 高于 analysis.json 和自然语言通用规则。
{long_horizon_response_prompt}
单企业 S0 诊断附加规则仍然有效：若 policy_context.single_enterprise_diagnostic_policy.enabled = true，只把它理解为单企业诊断运行开关；不要用普通经营扩张覆盖当前状态边界，也不要用部门身份优先级或内部实验标签解释动作或 pass。
{single_case_department_prompt}
{communication_prompt}

完成后，必须：
1. 调用 Write 写入新的 {spec.output_file_name}
2. 立即 Read 回读校验
3. 禁止只输出解释或 JSON 文本代替写文件
""".strip()

    # =========================
    # helper: options / session
    # =========================

    def _is_recoverable_session_error(self, error: Exception) -> bool:
        text = str(error).lower()
        return "session" in text or "resume" in text

    def _bind_session_to_options(self, options: Any, session_id: Optional[str]) -> Any:
        """
        把已有会话绑定为“恢复会话”。

        Claude CLI 的 --session-id 不是 resume 语义；在当前 SDK 中如果同时传入
        --session-id 且没有 --fork-session，会触发 CLI 参数错误。因此这里统一使用
        resume 字段，并清理历史兼容字段，避免生成错误参数组合。
        """
        if not session_id:
            return options

        # dict 型 options
        if isinstance(options, dict):
            options["resume"] = session_id
            options.pop("session_id", None)
            options.pop("resume_session_id", None)
            options.pop("conversation_id", None)
            return options

        # 对象型 options
        if hasattr(options, "resume"):
            try:
                setattr(options, "resume", session_id)
            except Exception:
                pass

        for attr in ("resume_session_id", "session_id", "conversation_id"):
            if hasattr(options, attr):
                try:
                    setattr(options, attr, None)
                except Exception:
                    pass

        # 某些 SDK 的 options 可能支持 model_copy/update
        if hasattr(options, "model_copy"):
            try:
                return options.model_copy(
                    update={
                        "resume": session_id,
                        "session_id": None,
                        "resume_session_id": None,
                        "conversation_id": None,
                    }
                )
            except Exception:
                pass

        return options

    # =========================
    # helper: transcript inspect
    # =========================

    def _extract_last_json_block(self, text: str) -> Optional[str]:
        """
        优先提取最后一个 ```json ... ``` 代码块。
        """
        blocks = self._extract_json_blocks(text)
        return blocks[-1] if blocks else None

    def _inspect_messages(
        self,
        messages: List[dict],
        spec: SkillRunSpec,
    ) -> RunInspection:
        text = "\n".join(m["content"] for m in messages)

        skill_called = f"name='Skill'" in text and f"'skill': '{spec.skill_name}'" in text
        skill_args_ok = spec.skill_args in text

        read_analysis = spec.analysis_path in text or Path(spec.analysis_path).name in text
        read_state = spec.state_path in text or Path(spec.state_path).name in text
        read_blackboard = spec.blackboard_path in text or Path(spec.blackboard_path).name in text
        read_trade_decision_card = (
            not spec.trade_decision_card_path
            or spec.trade_decision_card_path in text
            or Path(spec.trade_decision_card_path).name in text
        )

        write_called = "name='Write'" in text or 'name="Write"' in text
        write_target_ok = spec.output_file_path in text or spec.output_file_name in text

        # 输出文件的回读
        read_output_called = (
            ("name='Read'" in text or 'name="Read"' in text)
            and spec.output_file_path in text
        )

        json_block = self._extract_last_json_block(text)
        has_json_block = json_block is not None

        # failure type 诊断
        if not skill_called:
            failure_type = "skill_not_called"
        elif not skill_args_ok:
            failure_type = "skill_args_missing_or_wrong"
        elif not read_state or not read_blackboard or not read_trade_decision_card:
            failure_type = "required_reads_incomplete"
        elif has_json_block and not write_called:
            failure_type = "json_printed_but_not_written"
        elif write_called and not write_target_ok:
            failure_type = "write_wrong_target"
        elif write_called and not read_output_called:
            failure_type = "written_but_not_readback"
        elif not write_called:
            failure_type = "stopped_before_write"
        else:
            failure_type = "unknown"

        return RunInspection(
            skill_called=skill_called,
            skill_args_ok=skill_args_ok,
            read_analysis=read_analysis,
            read_state=read_state,
            read_blackboard=read_blackboard,
            read_trade_decision_card=read_trade_decision_card,
            write_called=write_called,
            write_target_ok=write_target_ok,
            read_output_called=read_output_called,
            has_json_block=has_json_block,
            json_block=json_block,
            failure_type=failure_type,
        )

    # =========================
    # helper: attempt logging
    # =========================

    def _dump_attempt_messages(
        self,
        enterprise_name: str,
        role: str,
        round_id: int,
        attempt_idx: int,
        messages: List[dict],
    ) -> None:
        messages_dir = (
            self.workspace_dir
            / "debug_messages"
            / enterprise_name
        )
        messages_dir.mkdir(parents=True, exist_ok=True)
        messages_file = messages_dir / f"{role}_action_messages_{attempt_idx}-{round_id}.json"
        messages_file.write_text(
            json.dumps(messages, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # =========================
    # helper: prompt routing by failure type
    # =========================

    def _next_prompt_by_failure(
        self,
        spec: SkillRunSpec,
        round_id: int,
        inspection: RunInspection,
        *,
        error_file: Optional[str] = None,
        need_trade: bool = False,
    ) -> str:
        if error_file:
            return self._build_business_repair_prompt(
                spec,
                round_id,
                error_file,
                need_trade=need_trade,
            )

        mapping = {
            "skill_not_called": "你上一轮没有真正调用 Skill 工具。现在立即严格按指定格式调用 Skill，并在同一 session 中继续完成写文件。",
            "skill_args_missing_or_wrong": f"你上一轮调用 Skill 时缺少或改错了 args。必须严格使用 args=\"{spec.skill_args}\"。",
            "required_reads_incomplete": "你上一轮没有读完必要的核心文件。请补齐必要读取后立即完成写文件，不要输出解释。",
            "json_printed_but_not_written": f"你上一轮已经给出了最终 JSON，但没有调用 Write。不要重新分析，直接把刚才确定的 JSON 写入 {spec.output_file_name} 并回读。",
            "write_wrong_target": f"你上一轮调用了 Write，但目标路径不正确。现在把最终 JSON 写入正确文件 {spec.output_file_name} 并回读。",
            "written_but_not_readback": f"你上一轮已经写入 {spec.output_file_name}，但没有回读校验。现在立即 Read 回读目标文件并完成校验。",
            "stopped_before_write": f"你上一轮在写文件前中断了。不要重新做长篇分析，继续完成 {spec.output_file_name} 的 Write 和回读。",
            "unknown": f"你上一轮未完成 {spec.output_file_name}。不要重新开始，优先沿用已有结果完成 Write 和回读。",
        }
        return self._build_same_session_resume_prompt(
            spec,
            round_id,
            mapping.get(inspection.failure_type, mapping["unknown"]),
            need_trade=need_trade,
        )

    # =========================
    # main: refactored controller
    # =========================

    async def run_department(
        self,
        dept: DepartmentSpec,
        round_id: int,
        need_trade: bool = False
    ) -> List[dict]:
        role = dept.role
        dept_type = dept.type

        global_lock_manager = GlobalDepartmentLockManager()

        hybrid_messages = self.hybrid_replay_runner.run_department(
            dept,
            round_id,
            need_trade=need_trade,
        )
        if hybrid_messages is not None:
            return hybrid_messages

        if self.scripted_rule_runner.department_enabled(dept.dept_id):
            messages = self.scripted_rule_runner.write_department_action(
                dept.dept_id,
                round_id,
                need_trade=need_trade,
            )
            if dept.dept_id != "finance":
                MultiTenantUtils.execute_enterprise_dept_action(
                    round_id,
                    0,
                    dept.dept_id,
                    self.enterprise_spec.enterprise_name,
                )
            return messages

        if dept_type == "Auto":
            MultiTenantUtils.generate_dept_auto_action(
                dept.dept_id,
                self.enterprise_spec.enterprise_name,
                round_id,
            )
            return []

        if dept_type == "Scripted":
            messages = self.scripted_rule_runner.write_department_action(
                dept.dept_id,
                round_id,
                need_trade=need_trade,
            )
            MultiTenantUtils.execute_enterprise_dept_action(
                round_id,
                0,
                dept.dept_id,
                self.enterprise_spec.enterprise_name,
            )
            return messages

        spec = self._build_skill_run_spec(dept, round_id)
        advisory_only = self._is_advisory_department(dept)
        self._remove_stale_output_file(spec.output_file_path)
        if self._communication_enabled() and not need_trade:
            self._remove_stale_output_file(spec.communication_file_path)
        phase = "trade" if need_trade else "decision"
        context_audit = self._build_context_audit(spec, dept.dept_id, phase, round_id)
        strict_context_failure = self._strict_context_failure(context_audit)

        success = False
        retry_time = 0
        all_messages: List[dict] = []
        prompt = self._build_launch_prompt(spec, round_id, need_trade)
        skill_profile = self._skill_profile()
        context_validation_mode = str(
            skill_profile.get("context_validation") or "off"
        )
        if context_validation_mode in {"warn", "strict"}:
            prompt += (
                "\n\n结构化上下文边界审计文件："
                f"{context_audit.get('artifact')}。"
                "不得引用其中标记为 disallowed 的场景专项字段。"
            )
        run_started_at = time.time()
        execution_result: Optional[Dict[str, Any]] = None

        if strict_context_failure:
            fallback_reason = (
                "strict context validation blocked Agent execution: "
                f"{strict_context_failure}"
            )
            if advisory_only:
                self._write_advisory_fallback_file(spec, fallback_reason)
                execution_result = {
                    "status": "success",
                    "advisory_only": True,
                    "reason": fallback_reason,
                }
            else:
                self._write_action_pass_file(spec, dept.dept_id, fallback_reason)
            if self._communication_enabled() and not need_trade:
                self._write_empty_communication_sidecar(
                    spec,
                    fallback_reason,
                )
            if not advisory_only:
                execution_result = MultiTenantUtils.execute_enterprise_dept_action(
                    round_id=round_id,
                    retry_time=1,
                    dept=dept.dept_id,
                    enterprise_name=self.enterprise_spec.enterprise_name,
                )
            self._write_skill_execution_audit(
                role=role,
                department=dept.dept_id,
                round_id=round_id,
                output_file_path=spec.output_file_path,
                all_messages=all_messages,
                attempts=0,
                success=execution_result.get("status") == "success",
                fallback_used=True,
                elapsed_seconds=time.time() - run_started_at,
                context_audit=context_audit,
                execution_result=execution_result,
                phase=phase,
            )
            return all_messages

        # 只在本次任务的重试中复用 session，避免跨轮次/跨运行继承旧 cwd 与旧上下文。
        resume_session_id: Optional[str] = None

        max_retry = max(1, int(skill_profile.get("max_retries", 3) or 0))
        default_timeout = max(1, int(dept.timeout or 120))

        while not success and retry_time < max_retry:
            # await global_lock_manager.acquire_department_lock(role)
            time_start = time.time()

            attempt_messages: List[dict] = []
            session_id_found: str = resume_session_id or ""
            recover_from_session_error = False
            timeout = self._long_run_agent_timeout_seconds(
                role=role,
                round_id=round_id,
                retry_index=retry_time,
                default_seconds=default_timeout,
            )

            print(f"START-{retry_time} {self.enterprise_spec.enterprise_id} {dept.name}")

            # 每一轮都先 build_options，再尝试绑定 session
            options = self.build_options(role)
            options = self._bind_session_to_options(options, resume_session_id)

            try:
                async def stream() -> None:
                    nonlocal session_id_found

                    async for message in query(prompt=prompt, options=options):
                        record = {
                            "enterprise_id": self.enterprise_spec.enterprise_id,
                            "enterprise_name": self.enterprise_spec.enterprise_name,
                            "role": role,
                            "content": str(message),
                        }
                        attempt_messages.append(record)
                        all_messages.append(record)

                        msg_session_id = getattr(message, "data", {}).get("session_id")
                        if msg_session_id:
                            session_id_found = msg_session_id

                await asyncio.wait_for(stream(), timeout=timeout)

            except asyncio.TimeoutError:
                attempt_messages.append({
                    "enterprise_id": self.enterprise_spec.enterprise_id,
                    "enterprise_name": self.enterprise_spec.enterprise_name,
                    "role": role,
                    "content": (
                        f"[Timeout] role={role}, retry={retry_time}, "
                        f"timeout_seconds={timeout}"
                    ),
                })
                all_messages.extend(attempt_messages[-1:])
                self.session_registry.clear(self.enterprise_spec.enterprise_id, role)
                resume_session_id = ""
                session_id_found = ""
                timeout_output_path = Path(spec.output_file_path)
                if timeout_output_path.exists() and not advisory_only:
                    MultiTenantUtils._normalize_action_file_if_possible(
                        timeout_output_path,
                        dept.dept_id,
                    )
                timeout_output_valid = (
                    MultiTenantUtils._is_valid_json_file(timeout_output_path)
                    if advisory_only and timeout_output_path.exists()
                    else MultiTenantUtils._is_valid_action_file(
                        timeout_output_path,
                        dept.dept_id,
                    )
                    if timeout_output_path.exists()
                    else False
                )
                # The CLI can finish Write just before its result stream reaches the
                # timeout. Preserve and execute that valid action instead of discarding
                # it and paying for another full Agent attempt.
                recover_from_session_error = not timeout_output_valid
            except ProcessError as e:
                error_record = {
                    "enterprise_id": self.enterprise_spec.enterprise_id,
                    "enterprise_name": self.enterprise_spec.enterprise_name,
                    "role": role,
                    "content": f"[ProcessError] role={role}, retry={retry_time}, error={e}",
                }
                attempt_messages.append(error_record)
                all_messages.append(error_record)
                self.session_registry.clear(self.enterprise_spec.enterprise_id, role)
                resume_session_id = ""
                session_id_found = ""
                recover_from_session_error = True
            except Exception as e:
                error_record = {
                    "enterprise_id": self.enterprise_spec.enterprise_id,
                    "enterprise_name": self.enterprise_spec.enterprise_name,
                    "role": role,
                    "content": (
                        f"[UnexpectedQueryError] role={role}, retry={retry_time}, "
                        f"error_type={type(e).__name__}, error={e}"
                    ),
                }
                attempt_messages.append(error_record)
                all_messages.append(error_record)
                self.session_registry.clear(self.enterprise_spec.enterprise_id, role)
                resume_session_id = ""
                session_id_found = ""
                recover_from_session_error = True

            finally:
                pass
                # global_lock_manager.release_department_lock(role)

            if recover_from_session_error:
                self._dump_attempt_messages(
                    self.enterprise_spec.enterprise_name,
                    role,
                    round_id,
                    retry_time + 1,
                    attempt_messages,
                )
                prompt = self._build_launch_prompt(spec, round_id, need_trade)
                retry_time += 1
                time_end = time.time()
                print(
                    f"END-{retry_time} {self.enterprise_spec.enterprise_id} "
                    f"{dept.name} 耗时: {time_end - time_start}"
                )
                continue

            # 保存本轮 session_id
            if session_id_found:
                resume_session_id = session_id_found

            # 先看文件有没有生成
            if advisory_only:
                has_file = Path(spec.output_file_path).exists()
            else:
                has_file = MultiTenantUtils.file_check_department(
                    self.enterprise_spec.enterprise_name,
                    dept.dept_id,
                    round_id,
                )
            if not has_file:
                self._recover_output_file_from_messages(attempt_messages, spec.output_file_path)
                has_file = (
                    Path(spec.output_file_path).exists()
                    if advisory_only
                    else MultiTenantUtils.file_check_department(
                        self.enterprise_spec.enterprise_name,
                        dept.dept_id,
                        round_id,
                    )
                )
            if has_file and not advisory_only:
                MultiTenantUtils._normalize_action_file_if_possible(
                    Path(spec.output_file_path),
                    dept.dept_id,
                )
            valid_file = (
                MultiTenantUtils._is_valid_json_file(Path(spec.output_file_path))
                if advisory_only
                else MultiTenantUtils._is_valid_action_file(Path(spec.output_file_path), dept.dept_id)
                if has_file
                else False
            )

            if has_file and valid_file:
                if advisory_only:
                    success = True
                    execution_result = {
                        "status": "success",
                        "advisory_only": True,
                        "output_file": spec.output_file_path,
                    }
                else:
                    result = MultiTenantUtils.execute_enterprise_dept_action(
                        round_id=round_id,
                        retry_time=retry_time + 1,
                        dept=dept.dept_id,
                        enterprise_name=self.enterprise_spec.enterprise_name,
                    )
                    execution_result = result

                    if result.get("status") == "success":
                        success = True
                    else:
                        error_file = result.get("file_path", "")
                        prompt = self._next_prompt_by_failure(
                            spec,
                            round_id,
                            RunInspection(
                                skill_called=True,
                                skill_args_ok=True,
                                read_analysis=True,
                                read_state=True,
                                read_blackboard=True,
                                read_trade_decision_card=True,
                                write_called=True,
                                write_target_ok=True,
                                read_output_called=True,
                                has_json_block=False,
                                json_block=None,
                                failure_type="unknown",
                            ),
                            error_file=error_file,
                            need_trade=need_trade,
                        )
                        self._remove_stale_output_file(spec.output_file_path)
            else:
                # 文件没生成或动作 schema 不合法：根据 transcript 判断失败类型，然后在同一 session 里继续修复
                inspection = self._inspect_messages(attempt_messages, spec)
                prompt = self._next_prompt_by_failure(
                    spec,
                    round_id,
                    inspection,
                    need_trade=need_trade,
                )
                if has_file:
                    self._remove_stale_output_file(spec.output_file_path)

                # 记录未输出时的消息，便于排错
                self._dump_attempt_messages(
                    self.enterprise_spec.enterprise_name,
                    role,
                    round_id,
                    retry_time + 1,
                    attempt_messages,
                )

            retry_time += 1
            time_end = time.time()
            print(
                f"END-{retry_time} {self.enterprise_spec.enterprise_id} "
                f"{dept.name} 耗时: {time_end - time_start}"
            )

        if not success:
            transport_failure = self._single_enterprise_agent_transport_failure(
                role=role,
                round_id=round_id,
                messages=all_messages,
            )
            if transport_failure:
                if bool(skill_profile.get("audit_enabled", True)):
                    self._write_skill_execution_audit(
                        role=role,
                        department=dept.dept_id,
                        round_id=round_id,
                        output_file_path=spec.output_file_path,
                        all_messages=all_messages,
                        attempts=retry_time,
                        success=False,
                        fallback_used=False,
                        elapsed_seconds=time.time() - run_started_at,
                        context_audit=context_audit,
                        execution_result=transport_failure,
                        phase=phase,
                    )
                raise RuntimeError(transport_failure["message"])

            fallback_reason = (
                "超时思考，调用兜底逻辑链路："
                "基于当前订单、库存、现金、产能、人员和履约状态继续本轮经营。"
            )
            if advisory_only:
                self._write_advisory_fallback_file(spec, fallback_reason)
            else:
                fallback_written = self._write_long_run_state_driven_fallback_file(
                    spec,
                    dept.dept_id,
                    round_id,
                    need_trade=need_trade,
                )
                if not fallback_written and dept.dept_id == "hr":
                    fallback_written = self._write_hr_staffing_fallback_file(
                        spec,
                        fallback_reason,
                    )
                if not fallback_written:
                    self._write_action_pass_file(spec, dept.dept_id, fallback_reason)
            if self._communication_enabled() and not need_trade:
                self._write_empty_communication_sidecar(
                    spec,
                    fallback_reason,
                )
            if advisory_only:
                execution_result = {
                    "status": "success",
                    "advisory_only": True,
                    "fallback": True,
                    "output_file": spec.output_file_path,
                }
            else:
                result = MultiTenantUtils.execute_enterprise_dept_action(
                    round_id=round_id,
                    retry_time=max_retry + 1,
                    dept=dept.dept_id,
                    enterprise_name=self.enterprise_spec.enterprise_name,
                )
                execution_result = result
            if execution_result.get("status") != "success":
                all_messages.append({
                    "enterprise_id": self.enterprise_spec.enterprise_id,
                    "enterprise_name": self.enterprise_spec.enterprise_name,
                    "role": role,
                    "content": f"[StateDrivenFallbackFailed] {execution_result}",
                })
                if not advisory_only:
                    self._write_action_pass_file(
                        spec,
                        dept.dept_id,
                        (
                            "超时思考，调用兜底逻辑链路：当轮状态动作未通过执行校验，"
                            "为保持账务和状态一致性，本轮不新增经营承诺。"
                        ),
                    )
                    execution_result = MultiTenantUtils.execute_enterprise_dept_action(
                        round_id=round_id,
                        retry_time=max_retry + 2,
                        dept=dept.dept_id,
                        enterprise_name=self.enterprise_spec.enterprise_name,
                    )

        if bool(skill_profile.get("audit_enabled", True)):
            self._write_skill_execution_audit(
                role=role,
                department=dept.dept_id,
                round_id=round_id,
                output_file_path=spec.output_file_path,
                all_messages=all_messages,
                attempts=retry_time,
                success=(
                    success
                    or bool(
                        execution_result
                        and execution_result.get("status") == "success"
                    )
                ),
                fallback_used=not success,
                elapsed_seconds=time.time() - run_started_at,
                context_audit=context_audit,
                execution_result=execution_result,
                phase=phase,
            )

        return all_messages

    async def run_analyst(self, round_id: int) -> List[dict]:
        hybrid_messages = self.hybrid_replay_runner.write_analysis(round_id)
        if hybrid_messages is not None:
            return hybrid_messages
        spec = self._build_analyst_run_spec(round_id)
        self._active_analyst_round_id = round_id
        self._remove_stale_output_file(spec.output_file_path)

        success = False
        retry_time = 0
        all_messages: List[dict] = []
        prompt = self._build_analyst_launch_prompt(spec, round_id)
        skill_profile = self._skill_profile()

        # 只在本次任务的重试中复用 session，避免跨轮次/跨运行继承旧 cwd 与旧上下文。
        resume_session_id: Optional[str] = None

        default_timeout = 240 if self._single_enterprise_agent_run_active() else 120
        max_retry = max(1, int(skill_profile.get("max_retries", 3) or 0))

        print(f"START- {self.enterprise_spec.enterprise_id} Analyst")
        time_start = time.time()

        while not success and retry_time < max_retry:
            attempt_messages: List[dict] = []
            session_id_found: str = resume_session_id or ""
            recover_from_session_error = False
            attempt_started_at = time.time()
            timeout = self._long_run_agent_timeout_seconds(
                role="Analyst",
                round_id=round_id,
                retry_index=retry_time,
                default_seconds=default_timeout,
                analyst=True,
            )

            options = self.build_options("Analyst")
            options = self._bind_session_to_options(options, resume_session_id)

            try:
                async def stream() -> None:
                    nonlocal session_id_found

                    async for message in query(prompt=prompt, options=options):
                        record = {
                            "enterprise_id": self.enterprise_spec.enterprise_id,
                            "enterprise_name": self.enterprise_spec.enterprise_name,
                            "role": "Analyst",
                            "content": str(message),
                        }
                        attempt_messages.append(record)
                        all_messages.append(record)

                        msg_session_id = getattr(message, "data", {}).get("session_id")
                        if msg_session_id:
                            session_id_found = msg_session_id

                await asyncio.wait_for(stream(), timeout=timeout)

            except asyncio.TimeoutError:
                timeout_record = {
                    "enterprise_id": self.enterprise_spec.enterprise_id,
                    "enterprise_name": self.enterprise_spec.enterprise_name,
                    "role": "Analyst",
                    "content": (
                        f"[Timeout] role=Analyst, retry={retry_time}, "
                        f"timeout_seconds={timeout}"
                    ),
                }
                attempt_messages.append(timeout_record)
                all_messages.append(timeout_record)
                self.session_registry.clear(self.enterprise_spec.enterprise_id, "Analyst")
                resume_session_id = ""
                session_id_found = ""
                recover_from_session_error = True
            except ProcessError as e:
                error_record = {
                    "enterprise_id": self.enterprise_spec.enterprise_id,
                    "enterprise_name": self.enterprise_spec.enterprise_name,
                    "role": "Analyst",
                    "content": f"[ProcessError] role=Analyst, retry={retry_time}, error={e}",
                }
                attempt_messages.append(error_record)
                all_messages.append(error_record)
                self.session_registry.clear(self.enterprise_spec.enterprise_id, "Analyst")
                resume_session_id = ""
                session_id_found = ""
                recover_from_session_error = True
            except Exception as e:
                error_record = {
                    "enterprise_id": self.enterprise_spec.enterprise_id,
                    "enterprise_name": self.enterprise_spec.enterprise_name,
                    "role": "Analyst",
                    "content": (
                        f"[UnexpectedQueryError] role=Analyst, retry={retry_time}, "
                        f"error_type={type(e).__name__}, error={e}"
                    ),
                }
                attempt_messages.append(error_record)
                all_messages.append(error_record)
                self.session_registry.clear(self.enterprise_spec.enterprise_id, "Analyst")
                resume_session_id = ""
                session_id_found = ""
                recover_from_session_error = True

            if recover_from_session_error:
                self._dump_attempt_messages(
                    self.enterprise_spec.enterprise_name,
                    "Analyst",
                    round_id,
                    retry_time + 1,
                    attempt_messages,
                )
                prompt = self._build_analyst_launch_prompt(spec, round_id)
                retry_time += 1
                continue

            # 保存 session_id，后续优先同 session 继续
            if session_id_found:
                resume_session_id = session_id_found

            # 判断 analysis.json 是否已生成且合法
            output_path = Path(spec.output_file_path)
            has_file = output_path.exists()
            if not has_file:
                self._recover_output_file_from_messages(attempt_messages, spec.output_file_path)
                has_file = output_path.exists()
            if not has_file:
                legacy_source = self._recover_analyst_output_from_legacy_path(
                    spec,
                    attempt_messages,
                    attempt_started_at,
                )
                if legacy_source:
                    recovery_record = {
                        "enterprise_id": self.enterprise_spec.enterprise_id,
                        "enterprise_name": self.enterprise_spec.enterprise_name,
                        "role": "Analyst",
                        "content": (
                            "[RecoveredAnalysisFromLegacyPath] "
                            f"source={legacy_source}, target={spec.output_file_path}"
                        ),
                    }
                    attempt_messages.append(recovery_record)
                    all_messages.append(recovery_record)
                has_file = output_path.exists()
            valid_file = self._is_valid_json_file(spec.output_file_path) if has_file else False

            if has_file and valid_file:
                success = True
            else:
                validation_error = getattr(
                    self,
                    "_last_analysis_validation_error",
                    "",
                )
                if has_file and validation_error:
                    validation_record = {
                        "enterprise_id": self.enterprise_spec.enterprise_id,
                        "enterprise_name": self.enterprise_spec.enterprise_name,
                        "role": "Analyst",
                        "content": (
                            "[AnalysisValidationFailed] "
                            f"{validation_error}"
                        ),
                    }
                    attempt_messages.append(validation_record)
                    all_messages.append(validation_record)
                inspection = self._inspect_analyst_messages(attempt_messages, spec)
                prompt = self._next_analyst_prompt_by_failure(spec, round_id, inspection)
                if has_file:
                    self._remove_stale_output_file(spec.output_file_path)

                # 每轮失败都落地消息，便于排错
                self._dump_attempt_messages(
                    self.enterprise_spec.enterprise_name,
                    "Analyst",
                    round_id,
                    retry_time + 1,
                    attempt_messages,
                )

            retry_time += 1

        time_end = time.time()
        print(f"END- {self.enterprise_spec.enterprise_id} Analyst--- {time_end - time_start}")
        transport_failure = None
        fallback_used = False
        if not success:
            transport_failure = self._single_enterprise_agent_transport_failure(
                role="Analyst",
                round_id=round_id,
                messages=all_messages,
            )
            if (
                transport_failure is None
                and self._long_run_agent_failure_continuation_enabled()
            ):
                fallback_used = MultiTenantUtils._write_fallback_enterprise_analysis(
                    self.enterprise_spec.enterprise_name,
                    round_id,
                )
                if fallback_used:
                    all_messages.append({
                        "enterprise_id": self.enterprise_spec.enterprise_id,
                        "enterprise_name": self.enterprise_spec.enterprise_name,
                        "role": "Analyst",
                        "content": (
                            "[LongRunFallbackAnalysis] Agent analysis unavailable; "
                            "continued from current observation state."
                        ),
                    })

        if bool(skill_profile.get("audit_enabled", True)):
            self._write_skill_execution_audit(
                role="Analyst",
                department="analyst",
                round_id=round_id,
                output_file_path=spec.output_file_path,
                all_messages=all_messages,
                attempts=retry_time,
                success=success,
                fallback_used=fallback_used,
                elapsed_seconds=time_end - time_start,
                context_audit={
                    "department": "analyst",
                    "ok": True,
                    "source_files": {
                        "analysis": spec.output_file_path,
                        "observation": spec.observation_path,
                        "history_projection": spec.history_projection_path,
                    },
                    "active_modes": {
                        "cobweb_profit_objective": (
                            spec.compact_observation_kind == "cobweb_c3"
                        ),
                        "long_horizon_context_compaction": (
                            spec.compact_observation_kind == "long_horizon_e1"
                        ),
                    },
                    "visible_policy_names": [],
                    "disallowed_policy_names": [],
                    "missing_files": [],
                },
                execution_result=transport_failure,
                phase="analyst",
                analyst=True,
            )

        self._active_analyst_round_id = None
        if transport_failure:
            raise RuntimeError(transport_failure["message"])
        return all_messages
