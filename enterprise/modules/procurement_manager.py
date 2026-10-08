"""
Procurement management module

Responsible for enterprise raw materials procurement to support traditional external vendor procurement and enterprise B2B staggered procurement
"""

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional
from config.project_paths import AGENT_ROOT, WORKSPACE_JOBS_ROOT, resolve_project_path
from enterprise.modules import hr_manager
from enterprise.modules.base_business_module import EnhancedBaseModule
from enterprise.modules.response_model import ModuleResponse, ResponseStatus
from enterprise.modules.decorators import with_response, validate_positive, skip_dry_run_validation
from config.module_config import ProcurementConfig
from config.simulation_preset_config import get_runtime_injection_config
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from math import ceil, isfinite
from network.trade_entities import (
    OrderProposal,
    Order
)

class ProcurementManager(EnhancedBaseModule):
    """
    Procurement Manager Category
    Processing all business logic related to enterprise procurement
        """

    def __init__(self, enterprise, module_id=None, config: ProcurementConfig = None):
        """
        Initialization Procurement Manager

        Args:
            Enterprise: Examples of enterprise
            parameter: Only identification of modules (optional)
            Config: Procurement Configuration Object (optional, default use of ProjectConfig())
                """
        # Use configuration or default configuration
        self.config = config or ProcurementConfig()

        # Call Parent Initialisation Method
        super().__init__(
            enterprise,
            module_id or f"procurement_{enterprise.id}",
            self.config
        )

        # Vendor management
        self.suppliers: Dict[str, Dict] = {}  # Vendor information {supplier_id: supplier_data}
        self.next_supplier_id = 1  # Next supplier ID
        self.supplier_selection_events: List[Dict] = []

        # Procurement order management
        self.purchase_orders: List[Dict] = []  # List of purchase orders
        self.next_order_id = 1  # Next order ID

        # B2B consultations (optional functions)
        self.negotiations: Dict[str, Dict] = {}  # Proceedings of the consultation {negotiation_id: negotiation_data}
        self.next_negotiation_id = 1  # Next consultation ID

        self.proposals_list: List[OrderProposal] = []  # Inboxes of proposals still pending department
        self.proposal_history: List[OrderProposal] = []  # See the history of the proposal (including response/completed)
        self.replenishment_history: List[Dict] = []
        self.upstream_order_history: List[Dict] = []

        # Procurement indicators
        self.procurement_metrics = {
            "total_orders": 0,              # Total orders
            "completed_orders": 0,          # Orders completed
            "rejected_orders": 0,          # Number of orders rejected
            "total_cost": 0.0,             # Total procurement cost
            "total_quantity": 0.0,         # Total procurement
            "on_time_delivery_count": 0,   # Timely arrival
            "procurement_cost_rate": 0.0,  # Procurement cost rate
            "on_time_rate": 0.0,           # Timely arrival rate
            # total_negotiations: 0, # General consultations (for calculation of success rate)
            # successful_negotiations: 0, # successful consultations (for calculation of success rate)
            # "negotiation_success_rate: 0.0 # Consultation success rate
        }

        # Procurement incident log
        self.procurement_events: List[Dict] = []

        # Module Type Identification
        self.module_type = "ProcurementManager"

    def _get_current_day(self) -> int:
        return self.enterprise.time_manager.get_day() if hasattr(self.enterprise, "time_manager") else 0

    def _safe_number(self, value, default: float = 0.0) -> float:
        """Safe conversion of values that are likely to be empty or illegal to float to avoid disruption of the state aggregation phase by dirty values."""
        try:
            if value is None or value == "":
                return default
            numeric_value = float(value)
            if not isfinite(numeric_value):
                fallback = float(default) if default is not None else 0.0
                return fallback if isfinite(fallback) else 0.0
            return numeric_value
        except (TypeError, ValueError):
            fallback = float(default) if default is not None else 0.0
            return fallback if isfinite(fallback) else 0.0

    def _get_reference_purchase_price(self, material_id: str) -> float:
        stock = self._get_inventory_item(material_id)
        reference_price = float(stock.get("unit_price", 0) or 0)
        if reference_price <= 0:
            reference_price = float(self.config.B2B_PRICE_REFERENCE_FALLBACK)
        return reference_price

    def _long_horizon_b2b_max_price_floor_multiplier(self) -> float:
        runtime_config = self._get_active_runtime_injection_config()
        policy = (runtime_config or {}).get("long_horizon_profitability_policy") or {}
        target_ids = set(policy.get("target_enterprise_ids") or [])
        if not policy.get("enabled") or (
            target_ids and getattr(self.enterprise, "id", None) not in target_ids
        ):
            return 0.0

        role_multipliers = policy.get("b2b_max_price_floor_by_role_tag") or {}
        enterprise_tags = set(getattr(self.enterprise, "role_tags", []) or [])
        multipliers = []
        for role_tag, value in role_multipliers.items():
            if role_tag not in enterprise_tags:
                continue
            try:
                multipliers.append(float(value))
            except (TypeError, ValueError):
                continue
        return max(multipliers, default=0.0)

    def _resolve_b2b_max_price(
        self,
        material_id: str,
        explicit_max_price: Optional[float] = None,
        expected_due_round: Optional[int] = None,
    ) -> Dict[str, float]:
        reference_price = self._get_reference_purchase_price(material_id)
        configured_floor = self._long_horizon_b2b_max_price_floor_multiplier()
        if explicit_max_price is not None:
            explicit_multiplier = float(explicit_max_price) / max(reference_price, 1e-9)
            multiplier = max(explicit_multiplier, configured_floor)
            return {
                "reference_price": reference_price,
                "max_price": reference_price * multiplier,
                "multiplier": multiplier,
                "strategy": (
                    "agent_explicit_max_price_with_trade_floor"
                    if configured_floor > explicit_multiplier
                    else "agent_explicit_max_price"
                ),
            }

        stock = self._get_inventory_item(material_id)
        current_day = self._get_current_day()
        reorder_point = float(stock.get("reorder_point", 0) or 0)
        safety_stock = float(stock.get("safety_stock", 0) or 0)
        on_hand_quantity = self._get_on_hand_quantity(material_id)

        multiplier = float(self.config.B2B_BASE_MAX_PRICE_MULTIPLIER)
        strategy = "base_band"

        if expected_due_round is not None and int(expected_due_round) <= current_day + 1:
            multiplier = max(multiplier, float(self.config.B2B_URGENT_MAX_PRICE_MULTIPLIER))
            strategy = "urgent_band"

        policy_floor = max(reorder_point, safety_stock)
        if policy_floor > 0 and on_hand_quantity <= policy_floor:
            multiplier = max(multiplier, float(self.config.B2B_LOW_STOCK_MAX_PRICE_MULTIPLIER))
            strategy = "low_stock_band"

        if configured_floor > multiplier:
            multiplier = configured_floor
            strategy = f"{strategy}_with_trade_floor"

        return {
            "reference_price": reference_price,
            "max_price": reference_price * multiplier,
            "multiplier": multiplier,
            "strategy": strategy,
        }

    def _serialize_proposals(self, proposals: Optional[List[OrderProposal]] = None) -> List[Dict]:
        serialized = []
        for proposal in proposals if proposals is not None else self.proposals_list:
            if is_dataclass(proposal):
                serialized.append(asdict(proposal))
            elif isinstance(proposal, dict):
                serialized.append(proposal)
            else:
                serialized.append(getattr(proposal, "__dict__", {"value": str(proposal)}))
        return serialized

    def _is_relevant_proposal(self, proposal: OrderProposal) -> bool:
        return getattr(proposal, "buyer_company_id", None) == self.enterprise.id

    def _is_waiting_for_local_response(self, proposal: OrderProposal) -> bool:
        return proposal.status == "pending" and proposal.buyer_response is None

    def _get_exchange(self):
        return getattr(self.enterprise, "upstream_exchange", None)

    def _ingest_proposals(self, proposals: List[OrderProposal]) -> None:
        history_ids = {proposal.proposal_id for proposal in self.proposal_history}
        inbox_ids = {proposal.proposal_id for proposal in self.proposals_list}
        for proposal in proposals:
            if not self._is_relevant_proposal(proposal):
                continue
            if proposal.proposal_id not in history_ids:
                self.proposal_history.append(proposal)
                history_ids.add(proposal.proposal_id)
            if self._is_waiting_for_local_response(proposal) and proposal.proposal_id not in inbox_ids:
                self.proposals_list.append(proposal)
                inbox_ids.add(proposal.proposal_id)

    def _prune_proposal_views(self) -> None:
        self.proposal_history = [
            proposal for proposal in self.proposal_history
            if self._is_relevant_proposal(proposal)
        ]
        self.proposals_list = [
            proposal for proposal in self.proposals_list
            if self._is_relevant_proposal(proposal) and self._is_waiting_for_local_response(proposal)
        ]

    def _refresh_proposal_views(self) -> None:
        """
        Rebuilds the response proposal inbox using exchange the latest dispatch result and syncs the historical view.
                """
        exchange = self._get_exchange()
        if not exchange:
            self._prune_proposal_views()
            return

        pending_inbox = [
            proposal
            for proposal in exchange.dispatch_proposals()
            if self._is_relevant_proposal(proposal) and self._is_waiting_for_local_response(proposal)
        ]
        pending_by_id = {proposal.proposal_id: proposal for proposal in pending_inbox}
        history_by_id = {
            proposal.proposal_id: proposal
            for proposal in self.proposal_history
            if self._is_relevant_proposal(proposal)
        }
        history_by_id.update(pending_by_id)
        self.proposal_history = list(history_by_id.values())
        self.proposals_list = list(pending_by_id.values())
        self._prune_proposal_views()

    def _get_exchange_proposal(self, proposal_id: str) -> Optional[OrderProposal]:
        exchange = self._get_exchange()
        if exchange and hasattr(exchange, "get_proposal"):
            return exchange.get_proposal(proposal_id)
        return self._find_relevant_proposal(proposal_id)

    def _find_pending_proposal(self, proposal_id: str) -> Optional[OrderProposal]:
        for proposal in self.proposals_list:
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def _find_relevant_proposal(self, proposal_id: str) -> Optional[OrderProposal]:
        self._prune_proposal_views()
        for proposal in self.proposal_history:
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def _get_inventory_item(self, material_id: str) -> Dict:
        inventory_manager = super().get_module_by_type("InventoryManager")
        if not inventory_manager:
            return {}
        detail_result = inventory_manager.get_inventory_detail(material_id)
        if getattr(detail_result, "success", False) and isinstance(detail_result.data, dict):
            return detail_result.data
        inventory_overview = inventory_manager.get_inventory_overview()
        stocks = inventory_overview.data.get("stocks", [])
        return next(
            (
                p for p in stocks
                if p.get("id") == material_id or p.get("item_id") == material_id
            ),
            {}
        ) or {}

    def _get_on_hand_quantity(self, material_id: str) -> float:
        stock = self._get_inventory_item(material_id)
        return stock.get("quantity", stock.get("su_quantity", 0)) or 0

    def _get_exchange_pipeline_quantity(self, material_id: str) -> float:
        exchange = getattr(self.enterprise, "upstream_exchange", None)
        if not exchange:
            return 0.0

        linked_order_ids = {
            order.get("exchange_order_id")
            for order in self.purchase_orders
            if order.get("exchange_order_id")
        }
        linked_proposal_ids = {
            order.get("proposal_id")
            for order in self.purchase_orders
            if order.get("proposal_id")
        }

        pipeline_quantity = 0.0

        # Only officially confirmed exchange chain orders are considered reliable in transit.
        # Sending potential / active buy request should not be equated with upcoming inventory,
        # Otherwise, new replenishment requirements will be erroneously lowered when stock is bottomed.
        for proposal in getattr(exchange, "proposals", []):
            if (
                proposal.buyer_company_id != self.enterprise.id
                or proposal.product_id != material_id
                or proposal.proposal_id in linked_proposal_ids
                or proposal.status != "accepted"
            ):
                continue
            pipeline_quantity += proposal.quantity or 0

        for order in getattr(exchange, "orders", []):
            if (
                order.buyer_company_id != self.enterprise.id
                or order.product_id != material_id
                or order.order_id in linked_order_ids
                or order.status != "confirmed"
            ):
                continue
            pipeline_quantity += order.quantity or 0

        return pipeline_quantity

    def _get_pending_quantity(self, material_id: str) -> float:
        local_pending_quantity = sum(
            order.get("quantity", 0) or 0
            for order in self.purchase_orders
            if order.get("material_id") == material_id and order.get("status") == "pending"
        )
        return local_pending_quantity + self._get_exchange_pipeline_quantity(material_id)

    def _get_sales_demand_signal(self, material_id: str) -> Dict:
        sales_modules = self.enterprise.business_modules.get("SalesManager", [])
        if not sales_modules:
            return {
                "recent_average_demand": 0.0,
                "backlog_quantity": 0.0,
                "history_window": [],
                "derived_from_recipe": False,
                "source_products": [],
            }
        sales_manager = sales_modules[0]
        demand_status = sales_manager._get_demand_backlog_status()
        product_status = demand_status.get("by_product", {}).get(material_id, {})
        created_events = [
            event for event in demand_status.get("received_demand_history", [])
            if event.get("product_id") == material_id and event.get("event_type") == "created"
        ]
        if not created_events:
            production_modules = self.enterprise.business_modules.get("ProductionManager", [])
            if production_modules:
                production_manager = production_modules[0]
                production_state = production_manager.get_state()
                production_data = production_state.data if getattr(production_state, "success", False) else {}
                recipes = production_data.get("product_recipes") or []
                converted_events = []
                converted_backlog = 0.0
                source_products = set()
                for recipe in recipes:
                    raw_materials = recipe.get("raw_materials") or {}
                    if material_id not in raw_materials:
                        continue
                    product_id = recipe.get("product_id")
                    if product_id:
                        source_products.add(product_id)
                    units_per_product = raw_materials.get(material_id, 0) or 0
                    product_events = [
                        event for event in demand_status.get("received_demand_history", [])
                        if event.get("product_id") == product_id and event.get("event_type") == "created"
                    ]
                    for event in product_events:
                        converted = event.copy()
                        converted["product_id"] = material_id
                        converted["source_product_id"] = product_id
                        converted["quantity"] = (event.get("quantity", 0) or 0) * units_per_product
                        converted_events.append(converted)
                    product_status_for_recipe = demand_status.get("by_product", {}).get(product_id, {})
                    converted_backlog += (
                        product_status_for_recipe.get("backlog_quantity", 0) or 0
                    ) * units_per_product
                if converted_events:
                    created_events = converted_events
                    product_status = {
                        "backlog_quantity": converted_backlog
                    }
                    derived_from_recipe = True
                else:
                    derived_from_recipe = False
                    source_products = set()
            else:
                derived_from_recipe = False
                source_products = set()
        else:
            derived_from_recipe = False
            source_products = set()
        history_window = created_events[-5:]
        recent_average = (
            sum(event.get("quantity", 0) or 0 for event in history_window) / len(history_window)
            if history_window else 0.0
        )
        return {
            "recent_average_demand": recent_average,
            "backlog_quantity": product_status.get("backlog_quantity", 0) or 0,
            "history_window": history_window,
            "derived_from_recipe": derived_from_recipe,
            "source_products": sorted(source_products),
        }

    def _get_recipe_recovery_signal(self, material_id: str) -> Dict[str, Any]:
        """
        Creates a "synchronous recovery replenishment signal for raw material based on production.recovery_guard and formulations.

        The objective is not to replace conventional replenishment, but to avoid being sensitive to only one of the most scarce items of the time when manufacturing enterprise enters the production recovery phase,
        This allows Malt / Hops / Yeast to synchronize replenishment with the same finished target.
                """
        production_modules = self.enterprise.business_modules.get("ProductionManager", [])
        if not production_modules:
            return {
                "enabled": False,
                "linked_products": [],
                "recovery_target_material_quantity": 0.0,
                "recipe_daily_demand_equivalent": 0.0,
                "critical_bottleneck_products": [],
                "reason_codes": [],
            }

        production_manager = production_modules[0]
        production_state = production_manager.get_state()
        production_data = production_state.data if getattr(production_state, "success", False) else {}
        recovery_guard = production_data.get("recovery_guard") or {}
        candidates = recovery_guard.get("candidates") or []
        recipes = {
            recipe.get("product_id"): recipe
            for recipe in (production_data.get("product_recipes") or [])
            if recipe.get("product_id")
        }

        linked_products: List[str] = []
        critical_bottleneck_products: List[str] = []
        reason_codes = set()
        recovery_target_material_quantity = 0.0
        amplification_mode = self._get_bullwhip_manufacturer_upstream_amplification()
        amplification_enabled = self._is_runtime_switch_enabled_for_current_enterprise(amplification_mode)
        proposal_signal_weight = float(self.config.RECOVERY_PROPOSAL_SIGNAL_WEIGHT or 0.25)
        if amplification_enabled:
            proposal_signal_weight *= self._safe_number(
                amplification_mode.get("proposal_signal_weight_multiplier"),
                1.0,
            )
        recovery_target_multiplier = (
            self._safe_number(amplification_mode.get("recovery_target_quantity_multiplier"), 1.0)
            if amplification_enabled else 1.0
        )
        bottleneck_quantity_multiplier = (
            self._safe_number(amplification_mode.get("bottleneck_quantity_multiplier"), 1.0)
            if amplification_enabled else 1.0
        )

        for candidate in candidates:
            product_id = candidate.get("product_id")
            recipe = recipes.get(product_id)
            if not recipe:
                continue
            units_per_product = float((recipe.get("raw_materials") or {}).get(material_id, 0) or 0)
            if units_per_product <= 0:
                continue

            linked_products.append(product_id)
            on_hand_finished = float(candidate.get("on_hand", 0) or 0)
            policy_floor = float(candidate.get("policy_floor", 0) or 0)
            confirmed_backlog_quantity = float(candidate.get("confirmed_order_backlog_quantity", 0) or 0)
            demand_backlog_quantity = float(candidate.get("demand_backlog_quantity", 0) or 0)
            stale_backlog_quantity = float(candidate.get("stale_backlog_quantity", 0) or 0)
            proposal_backlog_quantity = float(candidate.get("proposal_backlog_quantity", 0) or 0)
            inventory_gap_units = max(0.0, policy_floor - on_hand_finished)
            recovery_target_units = max(
                confirmed_backlog_quantity,
                demand_backlog_quantity,
                stale_backlog_quantity,
                inventory_gap_units,
                proposal_backlog_quantity * proposal_signal_weight,
            )

            if any(
                shortage.get("material_id") == material_id
                for shortage in (candidate.get("material_shortages") or [])
            ):
                recovery_target_units *= bottleneck_quantity_multiplier
                critical_bottleneck_products.append(product_id)
                reason_codes.add("RECIPE_BOTTLENECK")
                if amplification_enabled:
                    reason_codes.add("UPSTREAM_AMPLIFICATION_ENABLED")
            recovery_target_units *= recovery_target_multiplier
            recovery_target_material_quantity += recovery_target_units * units_per_product
            if confirmed_backlog_quantity > 0:
                reason_codes.add("CONFIRMED_ORDER_RECOVERY")
            if stale_backlog_quantity > 0:
                reason_codes.add("STALE_ORDER_RECOVERY")
            if inventory_gap_units > 0:
                reason_codes.add("FINISHED_GOODS_POLICY_GAP")

        recipe_target_days = max(1, int(self.config.RECIPE_RECOVERY_DEFAULT_TARGET_DAYS or 2))
        recipe_daily_demand_equivalent = recovery_target_material_quantity / recipe_target_days

        return {
            "enabled": recovery_target_material_quantity > 0,
            "linked_products": sorted(set(linked_products)),
            "recovery_target_material_quantity": recovery_target_material_quantity,
            "recipe_daily_demand_equivalent": recipe_daily_demand_equivalent,
            "critical_bottleneck_products": sorted(set(critical_bottleneck_products)),
            "reason_codes": sorted(reason_codes),
            "amplification_enabled": amplification_enabled,
            "proposal_signal_weight": proposal_signal_weight,
        }

    def _get_recent_consumption_signal(self, material_id: str, lookback_rounds: int = 3) -> Dict[str, float]:
        inventory_manager = super().get_module_by_type("InventoryManager")
        if not inventory_manager:
            return {
                "recent_average_consumption": 0.0,
                "recent_peak_consumption": 0.0,
                "consumption_days": 0
            }

        history_result = inventory_manager.get_inventory_history(material_id, limit=100)
        history_payload = history_result.data if getattr(history_result, "success", False) else {}
        history = history_payload.get("history") or []
        if not history:
            return {
                "recent_average_consumption": 0.0,
                "recent_peak_consumption": 0.0,
                "consumption_days": 0
            }

        original_unit = None
        if hasattr(inventory_manager, "_get_item_original_unit"):
            original_unit = inventory_manager._get_item_original_unit(material_id)

        current_round = self._get_current_day()
        by_round = defaultdict(float)
        for record in history:
            if record.get("type") != "outbound":
                continue
            round_id = int(record.get("time_step", 0) or 0)
            if round_id < current_round - max(1, int(lookback_rounds)) + 1:
                continue
            quantity_change = abs(record.get("quantity_change", 0) or 0)
            if hasattr(inventory_manager, "_from_su_quantity"):
                quantity_change = inventory_manager._from_su_quantity(quantity_change, original_unit)
            by_round[round_id] += quantity_change

        if not by_round:
            return {
                "recent_average_consumption": 0.0,
                "recent_peak_consumption": 0.0,
                "consumption_days": 0
            }

        values = list(by_round.values())
        return {
            "recent_average_consumption": sum(values) / len(values),
            "recent_peak_consumption": max(values),
            "consumption_days": len(values)
        }

    def _get_cash_summary(self) -> Dict:
        finance_manager = super().get_module_by_type("FinanceManager")
        if not finance_manager:
            return {
                "current_cash": 0.0,
                "warning_threshold": 0.0,
                "critical_threshold": 0.0,
                "available_after_warning_buffer": 0.0,
                "cash_level": "unknown",
                "has_warning_buffer": False,
                "accounts_payable_balance": 0.0,
            }
        finance_state = finance_manager.get_state()
        finance_data = finance_state.data if getattr(finance_state, "success", False) else {}
        return finance_data.get("cash_summary") or {
            "current_cash": float(finance_data.get("cash", 0) or 0),
            "warning_threshold": 0.0,
            "critical_threshold": 0.0,
            "available_after_warning_buffer": float(finance_data.get("cash", 0) or 0),
            "cash_level": "unknown",
            "has_warning_buffer": True,
            "accounts_payable_balance": 0.0,
        }

    def _get_top_tier_supply_policy(self) -> Dict:
        runtime_config = self._get_active_runtime_injection_config()
        return runtime_config.get("top_tier_supply_policy") or {
            "enabled": False,
            "enterprise_ids": [],
            "credit_enabled_supplier_types": [],
            "external_credit_limit": 0.0,
            "payable_delay_rounds": 0,
            "max_single_order_share": 1.0,
            "external_logistics_cost_multiplier": 1.0,
            "allow_direct_external_replenishment_without_exchange": False,
        }

    def _get_active_runtime_injection_config(self) -> Dict:
        """Prefer the current job workspace config over global defaults.

        Operations-mode jobs can run scenarios that differ from the process-level
        default scenario. Procurement decisions must therefore read the active
        workspace run_meta first, otherwise single-enterprise jobs may miss
        per-run top-tier external supply switches.
        """
        for runtime_config in (
            getattr(self.enterprise, "runtime_injection_config", None),
            getattr(getattr(self.enterprise, "controller", None), "runtime_injection_config", None),
            getattr(self.enterprise, "config", {}).get("runtime_injection_config")
            if isinstance(getattr(self.enterprise, "config", None), dict)
            else None,
        ):
            if isinstance(runtime_config, dict) and runtime_config:
                return runtime_config

        workspace_candidates: List[Path] = []
        env_workspace = os.getenv("SIMULATION_WORKSPACE_DIR") or os.getenv("SIMULATION_ACTIVE_WORKSPACE")
        if env_workspace:
            workspace_candidates.append(
                resolve_project_path(env_workspace, relative_to=AGENT_ROOT)
            )

        for import_path, attr_name in (
            ("multi_tenant_utils", "WORKSPACE"),
            ("static_utils", "Config"),
            ("agent.static_utils", "Config"),
            ("agent.multi_tenant_utils", "WORKSPACE"),
        ):
            try:
                module = sys.modules.get(import_path)
                if module is None:
                    module = __import__(import_path, fromlist=[attr_name])
                value = getattr(module, attr_name, None)
                if attr_name == "Config":
                    value = getattr(value, "WORKSPACE", None)
                if value:
                    workspace_candidates.append(Path(value))
            except Exception:
                continue

        seen = set()
        for workspace in workspace_candidates:
            try:
                workspace = workspace.resolve()
            except Exception:
                workspace = Path(workspace)
            if str(workspace) in seen:
                continue
            seen.add(str(workspace))
            run_meta_path = workspace / "run_meta.json"
            if not run_meta_path.exists():
                continue
            try:
                run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            scenario_config = run_meta.get("scenario_config") or {}
            runtime_config = scenario_config.get("runtime_injection") or run_meta.get("runtime_injection") or {}
            if isinstance(runtime_config, dict) and runtime_config:
                return runtime_config

        return get_runtime_injection_config()

    def _runtime_injection_config_from_workspace(self, workspace: Optional[Path]) -> Dict[str, Any]:
        if not workspace:
            return {}
        try:
            workspace = Path(workspace).resolve()
        except Exception:
            workspace = Path(workspace)
        run_meta_path = workspace / "run_meta.json"
        if not run_meta_path.exists():
            return {}
        try:
            run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        scenario_config = run_meta.get("scenario_config") or {}
        runtime_config = (
            scenario_config.get("runtime_injection")
            or run_meta.get("runtime_injection")
            or {}
        )
        return runtime_config if isinstance(runtime_config, dict) else {}

    def _runtime_config_has_supplier_selection_candidates(self, runtime_config: Dict[str, Any]) -> bool:
        policy = (runtime_config or {}).get("single_enterprise_supplier_selection_policy") or {}
        if not self._is_runtime_switch_enabled_for_current_enterprise(policy):
            return False
        return any(isinstance(item, dict) for item in (policy.get("candidate_suppliers") or []))

    def _recent_workspace_supplier_selection_runtime_config(self) -> Dict[str, Any]:
        """Recover per-run candidate supplier catalogs for isolated operations jobs.

        Action execution can happen in a process that does not share the
        client-side Config.WORKSPACE value. For single-enterprise supplier
        selection, the run_meta catalog is authoritative, so use the latest
        matching workspace_jobs run only as a narrow fallback.
        """
        cached = getattr(self, "_supplier_selection_runtime_config_cache", None)
        if isinstance(cached, dict) and self._runtime_config_has_supplier_selection_candidates(cached):
            return cached

        jobs_roots = []
        for root in (WORKSPACE_JOBS_ROOT, AGENT_ROOT / "workspace_jobs"):
            try:
                resolved = Path(root).resolve()
            except Exception:
                resolved = Path(root)
            if resolved not in jobs_roots:
                jobs_roots.append(resolved)

        run_meta_paths: List[Path] = []
        for jobs_root in jobs_roots:
            if not jobs_root.exists():
                continue
            try:
                run_meta_paths.extend(jobs_root.glob("run_*/run_meta.json"))
            except OSError:
                continue

        def _mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        for run_meta_path in sorted(run_meta_paths, key=_mtime, reverse=True)[:50]:
            runtime_config = self._runtime_injection_config_from_workspace(run_meta_path.parent)
            if self._runtime_config_has_supplier_selection_candidates(runtime_config):
                self._supplier_selection_runtime_config_cache = runtime_config
                return runtime_config
        return {}

    def _direct_external_replenishment_enabled(self) -> bool:
        policy = self._get_top_tier_supply_policy()
        if not policy.get("allow_direct_external_replenishment_without_exchange"):
            return False
        target_enterprise_ids = set(policy.get("enterprise_ids") or [])
        target_role_tags = set(policy.get("target_role_tags") or [])
        enterprise_match = (not target_enterprise_ids) or self.enterprise.id in target_enterprise_ids
        role_match = (not target_role_tags) or bool(
            set(getattr(self.enterprise, "role_tags", []) or []) & target_role_tags
        )
        return bool(policy.get("enabled")) and enterprise_match and role_match

    def _select_external_supplier_for_material(self, material_id: str) -> Optional[Dict]:
        candidates = []
        for supplier_id, supplier in (self.suppliers or {}).items():
            if supplier.get("supplier_type") != "external":
                continue
            material_info = (supplier.get("materials") or {}).get(material_id)
            if not material_info:
                continue
            candidates.append((supplier_id, supplier, material_info))
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                self._safe_number((item[2] or {}).get("unit_price")),
                -self._safe_number(item[1].get("reliability_score"), 0.0),
            )
        )
        supplier_id, supplier, material_info = candidates[0]
        return {
            "supplier_id": supplier_id,
            "supplier_name": supplier.get("supplier_name"),
            "material_info": material_info,
        }

    def _has_role_tag(self, tag: str) -> bool:
        return tag in set(getattr(self.enterprise, "role_tags", []) or [])

    def _has_policy_tag(self, tag: str) -> bool:
        return tag in set(getattr(self.enterprise, "policy_tags", []) or [])

    def _is_runtime_switch_enabled_for_current_enterprise(self, switch_payload: Optional[Dict]) -> bool:
        switch_payload = switch_payload or {}
        if not switch_payload.get("enabled"):
            return False
        target_enterprise_ids = set(
            switch_payload.get("target_enterprise_ids")
            or switch_payload.get("enterprise_ids")
            or []
        )
        target_role_tags = set(switch_payload.get("target_role_tags") or [])
        enterprise_match = (not target_enterprise_ids) or self.enterprise.id in target_enterprise_ids
        role_match = (not target_role_tags) or bool(set(getattr(self.enterprise, "role_tags", []) or []) & target_role_tags)
        return enterprise_match and role_match

    def _get_supplier_selection_policy(self) -> Dict[str, Any]:
        policy = (
            self._get_active_runtime_injection_config().get(
                "single_enterprise_supplier_selection_policy"
            )
            or {}
        )
        if (
            not self._is_runtime_switch_enabled_for_current_enterprise(policy)
            or not any(isinstance(item, dict) for item in (policy.get("candidate_suppliers") or []))
        ):
            fallback_policy = (
                self._recent_workspace_supplier_selection_runtime_config().get(
                    "single_enterprise_supplier_selection_policy"
                )
                or {}
            )
            if fallback_policy:
                policy = fallback_policy
        if not self._is_runtime_switch_enabled_for_current_enterprise(policy):
            return {}
        return policy

    def _get_supplier_candidates(self) -> List[Dict[str, Any]]:
        candidates = self._get_supplier_selection_policy().get("candidate_suppliers") or []
        return [deepcopy(item) for item in candidates if isinstance(item, dict)]

    def _find_supplier_candidate_by_name(self, supplier_name: str) -> Optional[Dict[str, Any]]:
        target = str(supplier_name or "").strip().lower()
        if not target:
            return None
        for candidate in self._get_supplier_candidates():
            if str(candidate.get("supplier_name") or "").strip().lower() == target:
                return candidate
        return None

    def _supplier_candidate_observation(self) -> List[Dict[str, Any]]:
        current_day = self._get_current_day()
        registered_names = {
            str(item.get("supplier_name") or "").strip().lower()
            for item in self.suppliers.values()
        }
        rows = []
        for candidate in self._get_supplier_candidates():
            supplier_name = candidate.get("supplier_name")
            processing_time = int(candidate.get("processing_time", 0) or 0)
            logistics_options = {}
            for mode, config in self.config.LOGISTICS_CONFIGS.items():
                transit_time = int(config.get("transit_time", 0) or 0)
                logistics_options[mode] = {
                    "base_fee": config.get("base_fee", 0),
                    "unit_fee": config.get("unit_fee", 0),
                    "transit_time": transit_time,
                    "total_delivery_time": processing_time + transit_time,
                    "estimated_arrival_round": current_day + processing_time + transit_time,
                }
            rows.append({
                **candidate,
                "registration_status": (
                    "registered"
                    if str(supplier_name or "").strip().lower() in registered_names
                    else "candidate"
                ),
                "logistics_options": logistics_options,
            })
        return rows

    def _get_bullwhip_manufacturer_upstream_amplification(self) -> Dict:
        runtime_config = self._get_active_runtime_injection_config()
        return runtime_config.get("bullwhip_manufacturer_upstream_amplification") or {
            "enabled": False,
            "target_enterprise_ids": [],
            "proposal_signal_weight_multiplier": 1.0,
            "recovery_target_quantity_multiplier": 1.0,
            "bottleneck_quantity_multiplier": 1.0,
            "replenishment_soft_cap_multiplier": 1.0,
        }

    def _get_bullwhip_supplier_upstream_pull_through_mode(self) -> Dict:
        runtime_config = self._get_active_runtime_injection_config()
        return runtime_config.get("bullwhip_supplier_upstream_pull_through_mode") or {
            "enabled": False,
            "target_enterprise_ids": [],
            "ignore_inventory_headroom_skip": False,
            "package_coverage_target_rounds_multiplier": 1.0,
            "package_quantity_multiplier": 1.0,
            "bottleneck_priority_boost_multiplier": 1.0,
            "package_priority_boost_multiplier": 1.0,
            "backlog_pull_through_multiplier": 1.0,
        }

    def _get_profit_objective_policy(self) -> Dict:
        runtime_config = self._get_active_runtime_injection_config()
        return runtime_config.get("profit_objective_policy") or {"enabled": False}

    def _get_long_run_experiment_policy(self) -> Dict:
        runtime_config = self._get_active_runtime_injection_config()
        return runtime_config.get("long_run_experiment_policy") or {"enabled": False}

    def _get_long_run_execution_guard(self) -> Dict[str, Any]:
        long_run_policy = self._get_long_run_experiment_policy()
        if not self._is_runtime_switch_enabled_for_current_enterprise(long_run_policy):
            return {}
        guard = long_run_policy.get("execution_guard") or {}
        return guard if isinstance(guard, dict) else {}

    def _profit_long_run_replenishment_guard_enabled(self) -> bool:
        profit_policy = self._get_profit_objective_policy()
        long_run_policy = self._get_long_run_experiment_policy()
        return (
            self._is_runtime_switch_enabled_for_current_enterprise(profit_policy)
            and self._is_runtime_switch_enabled_for_current_enterprise(long_run_policy)
        )

    def _apply_profit_long_run_replenishment_guard(
        self,
        *,
        material_id: str,
        raw_suggested_order_quantity: float,
        on_hand_quantity: float,
        incoming_quantity: float,
        backlog_quantity: float,
        forecast_daily_demand: float,
        expected_daily_demand: Optional[float],
        sales_recent_average: float,
        consumption_recent_average: float,
        effective_safety_stock: float,
        reorder_point: float,
    ) -> Dict[str, Any]:
        """Cap C3 long-run recovery orders so tail rounds do not dump all backlog at once."""
        if not self._profit_long_run_replenishment_guard_enabled():
            return {
                "applied": False,
                "quantity": raw_suggested_order_quantity,
            }

        long_run_policy = self._get_long_run_experiment_policy()
        guard = long_run_policy.get("execution_guard") or {}
        if not guard.get("cap_terminal_replenishment_recovery", True):
            return {
                "applied": False,
                "quantity": raw_suggested_order_quantity,
            }

        recommended_total_steps = int(long_run_policy.get("recommended_total_steps") or 0)
        exclude_tail_rounds = int(long_run_policy.get("exclude_tail_rounds") or 0)
        current_day = self._get_current_day()
        is_tail_round = bool(
            recommended_total_steps > 0
            and exclude_tail_rounds > 0
            and current_day >= max(0, recommended_total_steps - exclude_tail_rounds)
        )
        if is_tail_round:
            backlog_share = self._safe_number(
                guard.get("tail_replenishment_backlog_recovery_share"),
                0.25,
            )
            max_forecast_days = max(1.0, self._safe_number(
                guard.get("tail_replenishment_max_forecast_days"),
                1.0,
            ))
        else:
            backlog_share = self._safe_number(
                guard.get("normal_replenishment_backlog_recovery_share"),
                0.60,
            )
            max_forecast_days = max(1.0, self._safe_number(
                guard.get("normal_replenishment_max_forecast_days"),
                2.0,
            ))

        explicit_daily = self._safe_number(expected_daily_demand, 0.0)
        baseline_daily_demand = max(
            explicit_daily,
            self._safe_number(sales_recent_average),
            self._safe_number(consumption_recent_average),
        )
        if baseline_daily_demand <= 0:
            baseline_daily_demand = self._safe_number(forecast_daily_demand)
        guarded_target_inventory = max(reorder_point, effective_safety_stock) + (
            baseline_daily_demand * max_forecast_days
        ) + max(0.0, backlog_quantity) * max(0.0, min(backlog_share, 1.0))
        guarded_quantity_cap = max(
            0.0,
            guarded_target_inventory - (on_hand_quantity + incoming_quantity),
        )
        guarded_quantity = min(raw_suggested_order_quantity, guarded_quantity_cap)
        return {
            "applied": guarded_quantity < raw_suggested_order_quantity,
            "quantity": guarded_quantity,
            "material_id": material_id,
            "is_tail_round": is_tail_round,
            "current_day": current_day,
            "backlog_recovery_share": backlog_share,
            "max_forecast_days": max_forecast_days,
            "baseline_daily_demand": baseline_daily_demand,
            "guarded_quantity_cap": guarded_quantity_cap,
            "raw_suggested_order_quantity": raw_suggested_order_quantity,
        }

    def _cap_long_run_manual_purchase_demand(
        self,
        material_id: str,
        requested_quantity: float,
    ) -> Dict[str, Any]:
        guard = self._get_long_run_execution_guard()
        if not guard.get("cap_manual_purchase_demand"):
            return {
                "applied": False,
                "requested_quantity": requested_quantity,
                "quantity": requested_quantity,
            }
        calculation_response = self.calculate_replenishment_quantity(
            material_id=material_id,
            target_inventory_days=2,
        )
        calculation = (
            calculation_response.data
            if getattr(calculation_response, "success", False)
            and isinstance(calculation_response.data, dict)
            else {}
        )
        suggested_quantity = max(
            0.0,
            self._safe_number(calculation.get("suggested_order_quantity")),
        )
        multiplier = max(
            0.0,
            self._safe_number(
                guard.get("manual_purchase_demand_cap_multiplier"),
                1.20,
            ),
        )
        quantity_cap = suggested_quantity * multiplier
        guarded_quantity = min(max(0.0, requested_quantity), quantity_cap)
        return {
            "applied": guarded_quantity < requested_quantity,
            "requested_quantity": requested_quantity,
            "quantity": guarded_quantity,
            "suggested_quantity": suggested_quantity,
            "quantity_cap": quantity_cap,
            "cap_multiplier": multiplier,
            "calculation": calculation,
        }

    def _get_top_tier_logistics_cost_multiplier(self, supplier: Optional[Dict]) -> float:
        policy = self._get_top_tier_supply_policy()
        if not self._is_top_tier_credit_enabled_for_supplier(supplier):
            return 1.0
        multiplier = float(policy.get("external_logistics_cost_multiplier", 1.0) or 1.0)
        return max(0.0, multiplier)

    def _apply_top_tier_logistics_cost_adjustment(self, logistics_cost: float, supplier: Optional[Dict]) -> float:
        return float(logistics_cost or 0.0) * self._get_top_tier_logistics_cost_multiplier(supplier)

    def _is_top_tier_credit_enabled_for_supplier(self, supplier: Optional[Dict]) -> bool:
        policy = self._get_top_tier_supply_policy()
        if not policy.get("enabled"):
            return False
        target_enterprise_ids = set(policy.get("enterprise_ids") or [])
        target_role_tags = set(policy.get("target_role_tags") or [])
        if target_enterprise_ids and self.enterprise.id not in target_enterprise_ids:
            return False
        if target_role_tags and not (set(getattr(self.enterprise, "role_tags", []) or []) & target_role_tags):
            return False
        if not supplier:
            return False
        allowed_types = set(policy.get("credit_enabled_supplier_types") or [])
        if allowed_types and supplier.get("supplier_type") not in allowed_types:
            return False
        return True

    def _get_pending_credit_commitment(self) -> float:
        return sum(
            float(order.get("total_cost", 0) or 0)
            for order in self.purchase_orders
            if order.get("status") == "pending" and order.get("payment_mode") == "accounts_payable"
        )

    def _get_top_tier_supply_guard_status(self) -> Dict:
        policy = self._get_top_tier_supply_policy()
        target_enterprise_ids = set(policy.get("enterprise_ids") or [])
        target_role_tags = set(policy.get("target_role_tags") or [])
        enterprise_match = (not target_enterprise_ids) or self.enterprise.id in target_enterprise_ids
        role_match = (not target_role_tags) or bool(set(getattr(self.enterprise, "role_tags", []) or []) & target_role_tags)
        enabled = bool(policy.get("enabled")) and enterprise_match and role_match
        external_credit_limit = float(policy.get("external_credit_limit", 0) or 0)
        max_single_order_share = float(policy.get("max_single_order_share", 1.0) or 1.0)
        max_single_order_share = min(max(max_single_order_share, 0.0), 1.0)
        max_single_order_amount = external_credit_limit * max_single_order_share
        cash_summary = self._get_cash_summary()
        accounts_payable_balance = float(cash_summary.get("accounts_payable_balance", 0) or 0)
        pending_credit_commitment = self._get_pending_credit_commitment()
        current_credit_exposure = accounts_payable_balance + pending_credit_commitment
        available_credit = max(0.0, external_credit_limit - current_credit_exposure)
        current_day = self._get_current_day()
        due_amount = 0.0
        overdue_amount = 0.0
        for order in self.purchase_orders:
            if order.get("payment_mode") != "accounts_payable":
                continue
            if order.get("status") != "received":
                continue
            if order.get("payable_status") == "paid":
                continue
            order_amount = float(order.get("total_cost", 0) or 0)
            payable_due_round = order.get("payable_due_round")
            if payable_due_round is None:
                continue
            if int(payable_due_round) < current_day:
                overdue_amount += order_amount
            elif int(payable_due_round) == current_day:
                due_amount += order_amount

        if not enabled:
            guard_level = "disabled"
        elif available_credit <= 0:
            guard_level = "critical"
        elif overdue_amount > 0:
            guard_level = "warning"
        elif available_credit <= external_credit_limit * 0.2:
            guard_level = "warning"
        else:
            guard_level = "healthy"

        return {
            "enabled": enabled,
            "payment_mode": "accounts_payable" if enabled else "cash",
            "external_credit_limit": external_credit_limit,
            "max_single_order_share": max_single_order_share,
            "max_single_order_amount": max_single_order_amount,
            "external_logistics_cost_multiplier": float(policy.get("external_logistics_cost_multiplier", 1.0) or 1.0),
            "accounts_payable_balance": accounts_payable_balance,
            "pending_credit_commitment": pending_credit_commitment,
            "current_credit_exposure": current_credit_exposure,
            "available_credit": available_credit,
            "payable_delay_rounds": int(policy.get("payable_delay_rounds", 0) or 0),
            "due_this_round_amount": due_amount,
            "overdue_payable_amount": overdue_amount,
            "guard_level": guard_level,
            "has_credit_headroom": available_credit > 0,
        }

    def _evaluate_top_tier_credit_commitment(self, estimated_cost: float) -> Dict:
        guard = self._get_top_tier_supply_guard_status()
        max_single_order_amount = float(guard.get("max_single_order_amount", 0) or 0)
        available_credit = float(guard.get("available_credit", 0) or 0)
        external_credit_limit = float(guard.get("external_credit_limit", 0) or 0)
        projected_available_credit = available_credit - float(estimated_cost or 0)
        if not guard.get("enabled"):
            level = "disabled"
            hard_block_reason = "credit_policy_disabled"
        elif max_single_order_amount > 0 and float(estimated_cost or 0) > max_single_order_amount:
            level = "critical"
            hard_block_reason = "single_order_limit_exceeded"
        elif projected_available_credit < 0:
            level = "critical"
            hard_block_reason = "credit_limit_exceeded"
        elif projected_available_credit <= external_credit_limit * 0.15:
            level = "warning"
            hard_block_reason = None
        else:
            level = "healthy"
            hard_block_reason = None

        return {
            "guard": guard,
            "estimated_cost": float(estimated_cost or 0),
            "projected_available_credit": projected_available_credit,
            "commitment_level": level,
            "is_hard_blocked": level == "critical",
            "hard_block_reason": hard_block_reason,
            "payment_mode": guard.get("payment_mode"),
        }

    def _round_up_to_moq(self, quantity: float, min_order_quantity: float) -> float:
        quantity = float(quantity or 0)
        min_order_quantity = float(min_order_quantity or 0)
        if quantity <= 0:
            return 0.0
        if min_order_quantity <= 0:
            return quantity
        return float(ceil(quantity / min_order_quantity) * min_order_quantity)

    def _get_downstream_enterprise_instances(self) -> List[object]:
        """Read the example of enterprise from enterprise downstream at exchange for upstream protection of real recovery objectives."""
        exchange = getattr(self.enterprise, "downstream_exchange", None)
        message_manager = getattr(self.enterprise, "message_manager", None)
        if not exchange or not message_manager:
            return []
        enterprises = getattr(message_manager, "enterprises", {}) or {}
        instances = []
        for enterprise_id in (exchange.downstream_enterprises or {}).keys():
            instance = enterprises.get(enterprise_id)
            if instance is not None:
                instances.append(instance)
        return instances

    def _build_top_tier_package_supply_bundles(self) -> List[Dict]:
        """
        Generate a "package of recipes" proposal for upstream Supplier.

        Core objectives:
        - Instead of just sorting things on a case-by-case basis, it is a real restorative production candidate for downstream manufacturers,
          A minimum set of raw material startable packages for the same finished formulation.
        - This would also make it easier to complete, as a matter of priority, a set of available formulations, rather than a single raw material, in the case of stress.
                """
        bundles = []
        pull_through_mode = self._get_bullwhip_supplier_upstream_pull_through_mode()
        pull_through_enabled = self._is_runtime_switch_enabled_for_current_enterprise(pull_through_mode)
        coverage_target_rounds = self._safe_number(self.config.TOP_TIER_PACKAGE_COVERAGE_TARGET_ROUNDS, 2.0)
        if pull_through_enabled:
            coverage_target_rounds *= self._safe_number(
                pull_through_mode.get("package_coverage_target_rounds_multiplier"),
                1.0,
            )
        package_quantity_multiplier = (
            self._safe_number(pull_through_mode.get("package_quantity_multiplier"), 1.0)
            if pull_through_enabled else 1.0
        )
        for downstream_enterprise in self._get_downstream_enterprise_instances():
            production_modules = getattr(downstream_enterprise, "business_modules", {}).get("ProductionManager", [])
            if not production_modules:
                continue
            production_manager = production_modules[0]
            production_state = production_manager.get_state()
            production_data = production_state.data if getattr(production_state, "success", False) else {}
            recovery_guard = production_data.get("recovery_guard") or {}
            recipes = {
                recipe.get("product_id"): recipe
                for recipe in (production_data.get("product_recipes") or [])
                if recipe.get("product_id")
            }

            for candidate in recovery_guard.get("candidates") or []:
                product_id = candidate.get("product_id")
                recipe = recipes.get(product_id) or {}
                raw_materials = recipe.get("raw_materials") or {}
                if not raw_materials:
                    continue

                package_target_units = self._safe_number(candidate.get("recommended_plan_quantity"))
                if package_target_units <= 0:
                    continue
                package_target_units *= package_quantity_multiplier

                materials = {}
                bundle_credit_feasible = True
                bundle_estimated_total_cost = 0.0
                bundle_priority_score = 0.0
                bundle_reason_codes = set()
                bundle_coverage_sufficient = True

                for material_id, units_per_product in raw_materials.items():
                    if material_id not in getattr(self.enterprise, "purchasable_materials_idList", []):
                        continue
                    units_per_product = self._safe_number(units_per_product)
                    if units_per_product <= 0:
                        continue
                    supplier_candidates = (self.suppliers or {}).values()
                    best_supplier = None
                    best_material_info = None
                    for supplier in supplier_candidates:
                        material_info = (supplier.get("materials") or {}).get(material_id)
                        if material_info is None:
                            continue
                        if best_material_info is None or self._safe_number(material_info.get("unit_price")) < self._safe_number(best_material_info.get("unit_price")):
                            best_supplier = supplier
                            best_material_info = material_info
                    if best_material_info is None:
                        continue

                    min_order_quantity = self._safe_number(best_material_info.get("min_order_quantity"))
                    package_quantity = self._round_up_to_moq(package_target_units * units_per_product, min_order_quantity)
                    own_stock = self._get_inventory_item(material_id)
                    own_on_hand = self._safe_number(own_stock.get("quantity"))
                    own_incoming = self._safe_number(self._get_pending_quantity(material_id))
                    own_inventory_position = own_on_hand + own_incoming
                    package_coverage_rounds = (
                        own_inventory_position / package_quantity
                        if package_quantity > 0
                        else (coverage_target_rounds if own_inventory_position > 0 else 0.0)
                    )
                    package_coverage_sufficient = bool(
                        package_quantity > 0 and package_coverage_rounds >= coverage_target_rounds
                    )
                    if not package_coverage_sufficient:
                        bundle_coverage_sufficient = False
                    preferred_logistics_mode = self.config.TOP_TIER_CRITICAL_LOGISTICS_MODE
                    logistics_result = self.calculate_logistics_cost(preferred_logistics_mode, package_quantity)
                    raw_logistics_cost = 0.0
                    if getattr(logistics_result, "success", False):
                        if isinstance(logistics_result.data, dict):
                            raw_logistics_cost = self._safe_number(logistics_result.data.get("cost"))
                        else:
                            raw_logistics_cost = self._safe_number(logistics_result.data)
                    logistics_cost = self._apply_top_tier_logistics_cost_adjustment(raw_logistics_cost, best_supplier)
                    estimated_total_cost = self._safe_number(best_material_info.get("unit_price")) * package_quantity + logistics_cost
                    credit_guard = self._evaluate_top_tier_credit_commitment(estimated_total_cost)
                    credit_feasible = not credit_guard.get("is_hard_blocked")
                    if not credit_feasible:
                        bundle_credit_feasible = False
                    bundle_estimated_total_cost += estimated_total_cost

                    materials[material_id] = {
                        "required_per_product": units_per_product,
                        "recommended_quantity": package_quantity,
                        "own_on_hand": own_on_hand,
                        "own_incoming": own_incoming,
                        "own_inventory_position": own_inventory_position,
                        "coverage_rounds": package_coverage_rounds,
                        "coverage_target_rounds": coverage_target_rounds,
                        "coverage_sufficient": package_coverage_sufficient,
                        "min_order_quantity": min_order_quantity,
                        "supplier_name": best_supplier.get("supplier_name") if best_supplier else None,
                        "preferred_logistics_mode": preferred_logistics_mode,
                        "raw_logistics_cost": raw_logistics_cost,
                        "estimated_total_cost": estimated_total_cost,
                        "credit_feasible": credit_feasible,
                    }

                if not materials:
                    continue

                confirmed_backlog = self._safe_number(candidate.get("confirmed_order_backlog_quantity"))
                stale_backlog = self._safe_number(candidate.get("stale_backlog_quantity"))
                proposal_backlog = self._safe_number(candidate.get("proposal_backlog_quantity"))
                bundle_priority_score += confirmed_backlog + stale_backlog + proposal_backlog * 0.25
                if candidate.get("should_recover_now"):
                    bundle_priority_score += self._safe_number(self.config.TOP_TIER_PACKAGE_PRIORITY_BOOST, 3000.0)
                    bundle_reason_codes.add("PACKAGE_RECOVERY_TARGET")
                if confirmed_backlog > 0:
                    bundle_reason_codes.add("CONFIRMED_ORDER_RECOVERY")
                if stale_backlog > 0:
                    bundle_reason_codes.add("STALE_ORDER_RECOVERY")

                bundles.append({
                    "downstream_enterprise_id": getattr(downstream_enterprise, "id", None),
                    "downstream_enterprise_name": getattr(downstream_enterprise, "name", None),
                    "product_id": product_id,
                    "target_product_units": package_target_units,
                    "priority_score": bundle_priority_score,
                    "credit_feasible": bundle_credit_feasible,
                    "coverage_target_rounds": coverage_target_rounds,
                    "coverage_sufficient": bundle_coverage_sufficient,
                    "estimated_total_cost": bundle_estimated_total_cost,
                    "reason_codes": sorted(bundle_reason_codes),
                    "materials": materials,
                    "pull_through_enabled": pull_through_enabled,
                })

        bundles.sort(
            key=lambda item: (
                not item.get("credit_feasible"),
                -(self._safe_number(item.get("priority_score"))),
                -(self._safe_number(item.get("target_product_units"))),
            )
        )
        return bundles

    def _build_top_tier_supply_plan(self) -> Dict:
        """Generate a key raw material security plan for the upstream Suplier, emphasizing the priority of missing materials rather than unlimited supplies."""
        guard = self._get_top_tier_supply_guard_status()
        if not guard.get("enabled"):
            return {
                "enabled": False,
                "priority_materials": [],
                "recommended_actions": [],
                "downstream_bottleneck_materials": [],
                "package_supply_bundles": [],
            }

        materials_matrix = defaultdict(list)
        for supplier_id, supplier in self.suppliers.items():
            for material_id, material_info in (supplier.get("materials") or {}).items():
                materials_matrix[material_id].append({
                    "supplier_id": supplier_id,
                    "supplier_name": supplier.get("supplier_name"),
                    "supplier_type": supplier.get("supplier_type"),
                    "unit_price": material_info.get("unit_price", 0),
                    "min_order_quantity": material_info.get("min_order_quantity", 0),
                    "quality_level": supplier.get("quality_level"),
                    "reliability_score": supplier.get("reliability_score"),
                    "processing_time": supplier.get("processing_time"),
                })
        for material_id in materials_matrix:
            materials_matrix[material_id].sort(key=lambda item: item.get("unit_price", 0))

        package_supply_bundles = self._build_top_tier_package_supply_bundles()
        pull_through_mode = self._get_bullwhip_supplier_upstream_pull_through_mode()
        pull_through_enabled = self._is_runtime_switch_enabled_for_current_enterprise(pull_through_mode)
        package_priority_boost_multiplier = (
            self._safe_number(pull_through_mode.get("package_priority_boost_multiplier"), 1.0)
            if pull_through_enabled else 1.0
        )
        bottleneck_priority_boost_multiplier = (
            self._safe_number(pull_through_mode.get("bottleneck_priority_boost_multiplier"), 1.0)
            if pull_through_enabled else 1.0
        )
        backlog_pull_through_multiplier = (
            self._safe_number(pull_through_mode.get("backlog_pull_through_multiplier"), 1.0)
            if pull_through_enabled else 1.0
        )
        ignore_inventory_headroom_skip = bool(
            pull_through_enabled and pull_through_mode.get("ignore_inventory_headroom_skip")
        )
        package_quantity_targets = defaultdict(float)
        package_priority_materials = set()
        package_coverage_map = {}
        default_package_coverage_target_rounds = self._safe_number(
            self.config.TOP_TIER_PACKAGE_COVERAGE_TARGET_ROUNDS,
            2.0,
        )
        for bundle in package_supply_bundles:
            for material_id, material_payload in (bundle.get("materials") or {}).items():
                package_quantity_targets[material_id] = max(
                    package_quantity_targets[material_id],
                    self._safe_number(material_payload.get("recommended_quantity"))
                )
                package_priority_materials.add(material_id)
                existing_rounds = self._safe_number(
                    (package_coverage_map.get(material_id) or {}).get("coverage_rounds"),
                    default_package_coverage_target_rounds,
                )
                current_rounds = self._safe_number(
                    material_payload.get("coverage_rounds"),
                    default_package_coverage_target_rounds,
                )
                if material_id not in package_coverage_map or current_rounds < existing_rounds:
                    package_coverage_map[material_id] = {
                        "coverage_rounds": current_rounds,
                        "coverage_target_rounds": self._safe_number(material_payload.get("coverage_target_rounds"), 0.0),
                        "coverage_sufficient": bool(material_payload.get("coverage_sufficient", False)),
                    }

        recommended_actions = []
        downstream_bottleneck_materials = []
        for material_id in self.enterprise.purchasable_materials_idList:
            stock = self._get_inventory_item(material_id)
            on_hand = float(stock.get("quantity", 0) or 0)
            incoming = self._get_pending_quantity(material_id)
            sales_signal = self._get_sales_demand_signal(material_id)
            backlog = float(sales_signal.get("backlog_quantity", 0) or 0)
            reorder_point = float(stock.get("reorder_point", 0) or 0)
            safety_stock = float(stock.get("safety_stock", 0) or 0)
            inventory_position = on_hand + incoming - backlog
            is_downstream_recovery_bottleneck = bool(
                backlog > 0 and inventory_position <= 0 and on_hand <= safety_stock
            )
            shortage_to_reorder = max(0.0, reorder_point - (on_hand + incoming))
            backlog_gap = max(0.0, backlog - incoming)
            effective_backlog_gap = backlog_gap * backlog_pull_through_multiplier
            base_recommended_quantity = max(shortage_to_reorder, effective_backlog_gap)

            supplier_candidates = materials_matrix.get(material_id) or []
            supplier_info = supplier_candidates[0] if supplier_candidates else {}
            min_order_quantity = float(supplier_info.get("min_order_quantity", 0) or 0)
            unit_price = float(supplier_info.get("unit_price", 0) or 0)
            recommended_quantity = self._round_up_to_moq(base_recommended_quantity, min_order_quantity)
            package_recommended_quantity = self._safe_number(package_quantity_targets.get(material_id))
            package_coverage_payload = package_coverage_map.get(material_id) or {}
            package_coverage_rounds = self._safe_number(
                package_coverage_payload.get("coverage_rounds"),
                self._safe_number(self.config.TOP_TIER_PACKAGE_COVERAGE_TARGET_ROUNDS, 2.0),
            )
            package_coverage_target_rounds = self._safe_number(
                package_coverage_payload.get("coverage_target_rounds"),
                self._safe_number(self.config.TOP_TIER_PACKAGE_COVERAGE_TARGET_ROUNDS, 2.0),
            )
            package_coverage_sufficient = bool(package_coverage_payload.get("coverage_sufficient", False))
            skip_due_to_inventory_headroom = bool(package_coverage_sufficient and base_recommended_quantity <= 0)
            if ignore_inventory_headroom_skip and material_id in package_priority_materials:
                skip_due_to_inventory_headroom = False
            if package_recommended_quantity > recommended_quantity and not skip_due_to_inventory_headroom:
                recommended_quantity = self._round_up_to_moq(package_recommended_quantity, min_order_quantity)
            preferred_logistics_mode = (
                self.config.TOP_TIER_CRITICAL_LOGISTICS_MODE
                if (is_downstream_recovery_bottleneck or (material_id in package_priority_materials and not skip_due_to_inventory_headroom))
                else ("air" if (backlog > 0 or on_hand <= 0) else "road")
            )
            logistics_result = self.calculate_logistics_cost(preferred_logistics_mode, recommended_quantity)
            raw_logistics_cost = 0.0
            if getattr(logistics_result, "success", False):
                if isinstance(logistics_result.data, dict):
                    raw_logistics_cost = float(logistics_result.data.get("cost", 0) or 0)
                else:
                    raw_logistics_cost = float(logistics_result.data or 0)
            logistics_cost = self._apply_top_tier_logistics_cost_adjustment(raw_logistics_cost, supplier_info)
            estimated_total_cost = unit_price * recommended_quantity + logistics_cost
            credit_feasible = (
                recommended_quantity > 0
                and estimated_total_cost <= float(guard.get("available_credit", 0) or 0)
                and estimated_total_cost <= float(guard.get("max_single_order_amount", 0) or 0)
            )

            priority_score = 0.0
            reason_codes = []
            if backlog > 0:
                priority_score += backlog
                reason_codes.append("DOWNSTREAM_BACKLOG")
            if inventory_position < 0:
                priority_score += abs(inventory_position)
                reason_codes.append("NEGATIVE_INVENTORY_POSITION")
            if on_hand <= 0:
                priority_score += max(reorder_point, safety_stock, 1.0)
                reason_codes.append("STOCKOUT")
            if is_downstream_recovery_bottleneck:
                priority_score += (
                    float(self.config.TOP_TIER_BOTTLENECK_PRIORITY_BOOST or 0.0)
                    * bottleneck_priority_boost_multiplier
                )
                reason_codes.append("DOWNSTREAM_RECOVERY_BOTTLENECK")
                downstream_bottleneck_materials.append(material_id)
            if material_id in package_priority_materials and not skip_due_to_inventory_headroom:
                priority_score += (
                    float(self.config.TOP_TIER_PACKAGE_PRIORITY_BOOST or 0.0)
                    * package_priority_boost_multiplier
                )
                reason_codes.append("PACKAGE_SUPPLY_COHORT")
            elif material_id in package_priority_materials and skip_due_to_inventory_headroom:
                reason_codes.append("PACKAGE_HEADROOM_SUFFICIENT")
            if shortage_to_reorder > 0:
                reason_codes.append("BELOW_REORDER_POINT")
            if safety_stock > 0 and on_hand < safety_stock:
                reason_codes.append("LOW_SAFETY_BUFFER")

            recommended_actions.append({
                "material_id": material_id,
                "supplier_name": supplier_info.get("supplier_name"),
                "on_hand": on_hand,
                "incoming": incoming,
                "backlog_quantity": backlog,
                "inventory_position": inventory_position,
                "reorder_point": reorder_point,
                "safety_stock": safety_stock,
                "min_order_quantity": min_order_quantity,
                "recommended_quantity": recommended_quantity,
                "preferred_logistics_mode": preferred_logistics_mode,
                "raw_logistics_cost": raw_logistics_cost,
                "estimated_total_cost": estimated_total_cost,
                "credit_feasible": credit_feasible,
                "priority_score": priority_score,
                "reason_codes": reason_codes,
                "logistics_cost_multiplier": self._get_top_tier_logistics_cost_multiplier(supplier_info),
                "package_recommended_quantity": package_recommended_quantity,
                "package_priority": material_id in package_priority_materials,
                "package_coverage_rounds": package_coverage_rounds,
                "package_coverage_target_rounds": package_coverage_target_rounds,
                "package_coverage_sufficient": package_coverage_sufficient,
                "skip_due_to_inventory_headroom": skip_due_to_inventory_headroom,
                "pull_through_enabled": pull_through_enabled,
            })

        recommended_actions.sort(key=lambda item: (item["priority_score"], item["recommended_quantity"]), reverse=True)
        priority_materials = [item["material_id"] for item in recommended_actions if item["priority_score"] > 0][:3]
        return {
            "enabled": True,
            "priority_materials": priority_materials,
            "recommended_actions": recommended_actions[:5],
            "downstream_bottleneck_materials": sorted(set(downstream_bottleneck_materials)),
            "package_supply_bundles": package_supply_bundles[:3],
            "pull_through_enabled": pull_through_enabled,
            "backlog_pull_through_multiplier": backlog_pull_through_multiplier,
        }

    def _get_pending_commitment_cost(self) -> float:
        pending_local_cost = sum(
            float(order.get("total_cost", 0) or 0)
            for order in self.purchase_orders
            if order.get("status") == "pending" and order.get("payment_mode") != "accounts_payable"
        )

        linked_proposal_ids = {
            order.get("proposal_id")
            for order in self.purchase_orders
            if order.get("proposal_id")
        }
        exchange = self._get_exchange()
        pending_proposal_cost = 0.0
        if exchange:
            for proposal in getattr(exchange, "proposals", []):
                if (
                    proposal.buyer_company_id != self.enterprise.id
                    or proposal.proposal_id in linked_proposal_ids
                    or proposal.status != "accepted"
                ):
                    continue
                pending_proposal_cost += float(proposal.quantity or 0) * float(proposal.proposed_price or 0)
        return pending_local_cost + pending_proposal_cost

    def _get_cash_guard_status(self) -> Dict:
        cash_summary = self._get_cash_summary()
        current_cash = float(cash_summary.get("current_cash", 0) or 0)
        warning_threshold = float(cash_summary.get("warning_threshold", 0) or 0)
        committed_pending_cost = self._get_pending_commitment_cost()
        remaining_after_commitments = current_cash - committed_pending_cost
        available_procurement_budget = max(0.0, remaining_after_commitments - warning_threshold)

        if remaining_after_commitments <= float(cash_summary.get("critical_threshold", 0) or 0):
            guard_level = "critical"
        elif remaining_after_commitments <= warning_threshold:
            guard_level = "warning"
        else:
            guard_level = "healthy"

        return {
            "cash_summary": cash_summary,
            "committed_pending_cost": committed_pending_cost,
            "remaining_cash_after_commitments": remaining_after_commitments,
            "available_procurement_budget": available_procurement_budget,
            "guard_level": guard_level,
            "should_reduce_order_size": guard_level in {"warning", "critical"},
        }

    def _evaluate_cash_commitment(self, estimated_cost: float) -> Dict:
        cash_guard = self._get_cash_guard_status()
        remaining_after_commitments = float(cash_guard.get("remaining_cash_after_commitments", 0) or 0)
        warning_threshold = float((cash_guard.get("cash_summary") or {}).get("warning_threshold", 0) or 0)
        projected_remaining = remaining_after_commitments - float(estimated_cost or 0)
        if projected_remaining < 0:
            level = "critical"
        elif projected_remaining < warning_threshold:
            level = "warning"
        else:
            level = "healthy"
        execution_guard = self._get_long_run_execution_guard()
        max_pending_share = self._safe_number(
            execution_guard.get("max_pending_procurement_cash_share"),
            0.0,
        )
        current_cash = self._safe_number(
            (cash_guard.get("cash_summary") or {}).get("current_cash"),
            0.0,
        )
        minimum_budget = self._safe_number(
            execution_guard.get("minimum_procurement_commitment_budget"),
            0.0,
        )
        policy_budget = (
            max(minimum_budget, current_cash * max_pending_share)
            if max_pending_share > 0
            else 0.0
        )
        projected_pending_commitment = (
            self._safe_number(cash_guard.get("committed_pending_cost"), 0.0)
            + float(estimated_cost or 0)
        )
        policy_hard_blocked = bool(
            policy_budget > 0 and projected_pending_commitment > policy_budget
        )
        return {
            "estimated_cost": float(estimated_cost or 0),
            "projected_remaining_cash": projected_remaining,
            "commitment_level": level,
            "is_hard_blocked": projected_remaining < 0 or policy_hard_blocked,
            "is_soft_warning": projected_remaining >= 0 and projected_remaining < warning_threshold,
            "long_run_commitment_guard": {
                "enabled": policy_budget > 0,
                "policy_budget": policy_budget,
                "projected_pending_commitment": projected_pending_commitment,
                "is_hard_blocked": policy_hard_blocked,
            },
            "cash_guard": cash_guard,
        }

    @with_response("initialize_suppliers")
    def initialize_suppliers(self, suppliers_data: List[Dict], dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        List of initialifiers

        Args:
            suppliers_data: list of supplier data, each element containing information such as subplier name, supplier_type, materials
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified response object for initialised results
                """
                # Check department personnel
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="procurement")
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_REGISTER_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法注册供应商。至少需要: {self.config.MIN_REGISTER_STAFF}"
            )
        for supplier_info in suppliers_data:
            supplier_type = supplier_info['supplier_type']
            if supplier_type not in ["external", "enterprise"]:
                return self.error_response(
                response,
                "INVALID_SUPPLIER_TYPE",
                "供应商类型必须为 'external' 或 'enterprise'"
            )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        if not suppliers_data:
            return self.success_response(
                response,
                "没有供应商数据需要初始化",
                {"registered": 0}
            )

        registered_count = 0
        failed_count = 0
        errors = []

        for supplier_info in suppliers_data:
            # Validate Required Fields
            if not all(key in supplier_info for key in ['supplier_name', 'supplier_type', 'materials']):
                failed_count += 1
                errors.append(f"供应商数据不完整: {supplier_info}")
                continue

            # Registered vendors
            result = self.register_supplier(
                supplier_name=supplier_info['supplier_name'],
                supplier_type=supplier_info['supplier_type'],
                materials=supplier_info['materials'],
                processing_time=supplier_info.get('processing_time', 0),
                quality_level=supplier_info.get('quality_level', 'standard'),
                reliability_score=supplier_info.get('reliability_score', 1.0)
            )

            # Addressing different types of return
            if hasattr(result, "success"):
                if result.success:
                    registered_count += 1
                else:
                    failed_count += 1
                    # Extract detailed error information
                    error_detail = result.message
                    if hasattr(result, 'errors') and result.errors:
                        if isinstance(result.errors, list) and len(result.errors) > 0:
                            error_detail = result.errors[0].get('message', error_detail)
                    errors.append(f"注册供应商失败: {supplier_info['supplier_name']}, 错误: {error_detail}")
            else:
                if result['success']:
                    registered_count += 1
                else:
                    failed_count += 1
                    errors.append(f"注册供应商失败: {supplier_info['supplier_name']}, 错误: {result.get('error', '未知错误')}")

        # Set Response Status and Message
        if failed_count == 0:
            response.set_status(ResponseStatus.SUCCESS)
        else:
            response.set_status(ResponseStatus.PARTIAL)

        response.set_message(f"供应商初始化完成: 成功注册{registered_count}个，失败{failed_count}个")
        response.data = {
            "registered": registered_count,
            "failed": failed_count,
            "errors": errors
        }

        return response
    



    def receive_proposals(self):
        """
        Receive exchange distribution of potential orders and create list of pending orders
                """
        self._refresh_proposal_views()

    def build_orders_from_exchange(self):
        """
        Establishment of purchase orders
                """
        exchange = self._get_exchange()
        if exchange is None:
            return
        hr_manager = super().get_module_by_type("HRManager")
        existing_exchange_order_ids = {
            order.get("exchange_order_id")
            for order in self.purchase_orders
            if order.get("exchange_order_id")
        }
        orders:List[Order] = exchange.get_confirm_orders_for_buyer(self.enterprise.id)
        for accepted_order in orders:
            if accepted_order.order_id in existing_exchange_order_ids:
                continue
            order_id = f"PROCUREMENT_ORDER_{self.next_order_id}"
            self.next_order_id += 1
            current_time = self.enterprise.time_manager.get_day()
            assigned_workers = self.config.MIN_PROCUREMENT_STAFF
            purchase_order = {
                "order_id": order_id,
                "material_id": accepted_order.product_id,
                "quantity": accepted_order.quantity,
                "supplier_id": accepted_order.seller_company_id,
                "unit_price": accepted_order.agreed_price,
                # "material_cost": material_cost,
                # "logistics_mode": logistics_mode,
                # "logistics_cost": logistics_cost,
                "total_cost": accepted_order.agreed_price * accepted_order.quantity,
                "order_time": current_time,
                "delivery_time": accepted_order.planned_delivery_round - current_time,
                "arrival_time": accepted_order.planned_delivery_round,
                "exchange_order_id": accepted_order.order_id,
                "proposal_id": accepted_order.proposal_id,
                "status": "pending",  # Wait for the goods.
                "actual_arrival_time": None,
                "on_time": None,
                "assigned_workers": 0
            }

            assign_result = hr_manager.assign_workers(
                'procurement',
                order_id,
                self.config.MIN_PROCUREMENT_STAFF
            )
            if getattr(assign_result, "success", True):
                purchase_order["assigned_workers"] = assigned_workers
            else:
                self._log_event({
                    "type": "order_assignment_pending",
                    "order_id": order_id,
                    "material_id": accepted_order.product_id,
                    "reason": getattr(assign_result, "message", "采购订单创建后暂未成功分配工人")
                })

            self.purchase_orders.append(purchase_order)
            self.procurement_metrics["total_orders"] += 1

            self._log_event({
                "type": "order_created",
                "order_id": order_id,
                "material_id": accepted_order.product_id,
                "quantity": accepted_order.quantity,
                "total_cost": accepted_order.agreed_price * accepted_order.quantity
            })
            existing_exchange_order_ids.add(accepted_order.order_id)


    @with_response("accept_proposal_order")
    def accept_proposal_order(self, proposal_id: str, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Acceptance of purchase orders

        Args:
            parameter: Order ID
            respond to objects
                """
        self._refresh_proposal_views()

        # 1. Find currently pending purchase side responses inbox
        proposal = self._find_pending_proposal(proposal_id)
        if not proposal:
            exchange_proposal = self._get_exchange_proposal(proposal_id)
            if not exchange_proposal or not self._is_relevant_proposal(exchange_proposal):
                return self.error_response(response, "ORDER_NOT_FOUND", f"订单 {proposal_id} 不存在")
            if exchange_proposal.status != "pending":
                return self.error_response(response, "INVALID_ORDER_STATUS", f"订单状态为 {exchange_proposal.status}，无法接受")
            return self.error_response(response, "PROPOSAL_ALREADY_RESPONDED", f"订单 {proposal_id} 已完成采购侧响应")

        estimated_cost = float(proposal.quantity or 0) * float(proposal.proposed_price or 0)
        cash_commitment = self._evaluate_cash_commitment(estimated_cost)
        if cash_commitment["is_hard_blocked"]:
            long_run_guard = cash_commitment.get("long_run_commitment_guard") or {}
            if long_run_guard.get("is_hard_blocked"):
                return self.error_response(
                    response,
                    "LONG_RUN_COMMITMENT_LIMIT",
                    (
                        "接受提案将使未结采购承诺超出长跑现金预算。"
                        f"预计承诺 ¥{long_run_guard.get('projected_pending_commitment', 0):,.2f}，"
                        f"预算上限 ¥{long_run_guard.get('policy_budget', 0):,.2f}"
                    ),
                )
            return self.error_response(
                response,
                "INSUFFICIENT_FUNDS",
                (
                    f"接受提案后预计现金将低于 0。提案成本约 ¥{estimated_cost:,.2f}，"
                    f"待履约承诺后剩余现金约 ¥{cash_commitment['projected_remaining_cash']:,.2f}"
                )
            )
        
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "proposal_id": proposal_id,
                    "estimated_cost": estimated_cost,
                    "cash_commitment": cash_commitment,
                }
            )
        
        # 3. Updating the order status
        self.enterprise.upstream_exchange.handle_company_response(
            proposal_id,
            "accept",
            "buyer"
        )
        self._refresh_proposal_views()
        return self.success_response(
            response,
            f"订单 {proposal_id} 已接受, 等待上游",
            {
                "proposal_id": proposal_id,
                "estimated_cost": estimated_cost,
                "cash_commitment": cash_commitment,
            }
        )

    @with_response("reject_proposal_order")
    def reject_proposal_order(self, proposal_id: str, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Rejected purchase orders

        Args:
            parameter: Order ID
            respond to objects
                """
        self._refresh_proposal_views()

        # 1. Find currently pending purchase side responses inbox
        proposal = self._find_pending_proposal(proposal_id)
        if not proposal:
            exchange_proposal = self._get_exchange_proposal(proposal_id)
            if not exchange_proposal or not self._is_relevant_proposal(exchange_proposal):
                return self.error_response(response, "ORDER_NOT_FOUND", f"订单 {proposal_id} 不存在")
            if exchange_proposal.status != "pending":
                return self.error_response(response, "INVALID_ORDER_STATUS", f"订单状态为 {exchange_proposal.status}，无法拒绝")
            return self.error_response(response, "PROPOSAL_ALREADY_RESPONDED", f"订单 {proposal_id} 已完成采购侧响应")
        
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        
        # 3. Updating the order status
        self.enterprise.upstream_exchange.handle_company_response(
            proposal_id,
            "reject",
            "buyer"
        )
        self._refresh_proposal_views()
        return self.success_response(
            response,
            f"订单 {proposal_id} 已拒绝",
            {
                "proposal_id": proposal_id,
            }
        )


    @with_response("create_purchase_demand")
    @validate_positive("quantity")
    def create_purchase_demand(self, material_id: str, quantity: float,
                             supplier_name: str = "", logistics_mode: str = "road", 
                             dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        if material_id not in getattr(self.enterprise, "purchasable_materials_idList", []):
            return self.error_response(
                response,
                "MATERIAL_NOT_PURCHASABLE",
                f"企业 {self.enterprise.id} 不允许采购物料 {material_id}。可采购物料: {getattr(self.enterprise, 'purchasable_materials_idList', [])}"
            )

        # Check department personnel
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="procurement")       
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_PROCUREMENT_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法创建采购订单。至少需要: {self.config.MIN_PROCUREMENT_STAFF}"
            )
        quantity_guard = self._cap_long_run_manual_purchase_demand(
            material_id,
            float(quantity),
        )
        quantity = float(quantity_guard.get("quantity", quantity) or 0)
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {"quantity_guard": quantity_guard},
            )
        current_time = self.enterprise.time_manager.get_day()
        inventory_manager = super().get_module_by_type("InventoryManager")
        detail_result = inventory_manager.get_inventory_detail(material_id)
        if not getattr(detail_result, "success", False):
            return self.error_response(response, "PRODUCT_NOT_FOUND", f"产品 {material_id} 不存在")
        if quantity <= 0:
            history_item = {
                "round": current_time,
                "request_id": None,
                "material_id": material_id,
                "quantity": 0,
                "requested_quantity": quantity_guard.get("requested_quantity"),
                "created_request": False,
                "reason": "long_run_inventory_coverage_sufficient",
                "quantity_guard": quantity_guard,
            }
            self.upstream_order_history.append(history_item)
            return self.success_response(
                response,
                f"{material_id} 当前库存与在途覆盖充足，未重复建立采购需求",
                history_item,
            )
        stock = detail_result.data if isinstance(detail_result.data, dict) else {}
        pricing = self._resolve_b2b_max_price(
            material_id=material_id,
            expected_due_round=current_time + 1,
        )
        data = self.enterprise.upstream_exchange.submit_buy_request(
            buyer_company_id = self.enterprise.id,
            product_id = material_id,
            quantity = quantity,
            created_round = current_time,
            max_price = pricing["max_price"],
            expected_due_round = current_time + 1,
        ) 
        self.upstream_order_history.append({
            "round": current_time,
            "request_id": data.request_id,
            "material_id": material_id,
            "quantity": quantity,
            "expected_due_round": current_time + 1,
            "reason": "manual_purchase_demand",
            "pricing_strategy": pricing,
        })
        payload = asdict(data)
        payload["pricing_strategy"] = pricing
        payload["quantity_guard"] = quantity_guard
        return self.success_response(response, f"已在交易所建立采购需求，等待上游企业响应", payload)

    @with_response("calculate_replenishment_quantity")
    def calculate_replenishment_quantity(
        self,
        material_id: str,
        target_inventory_days: int = 2,
        safety_stock: float = 0,
        expected_daily_demand: Optional[float] = None,
        response: ModuleResponse = None
    ) -> ModuleResponse:
        sales_signal = self._get_sales_demand_signal(material_id)
        consumption_signal = self._get_recent_consumption_signal(material_id)
        stock = self._get_inventory_item(material_id)
        on_hand_quantity = self._get_on_hand_quantity(material_id)
        incoming_quantity = self._get_pending_quantity(material_id)
        backlog_quantity = sales_signal.get("backlog_quantity", 0) or 0
        history_window = sales_signal.get("history_window", []) or []
        sales_recent_average = float(sales_signal.get("recent_average_demand", 0) or 0)
        sales_recent_peak = max((float(event.get("quantity", 0) or 0) for event in history_window), default=0.0)
        backlog_daily_equivalent = backlog_quantity / max(1, int(target_inventory_days))
        recipe_recovery_signal = self._get_recipe_recovery_signal(material_id)
        configured_safety_stock = float(stock.get("safety_stock", 0) or 0)
        effective_safety_stock = max(float(safety_stock or 0), configured_safety_stock)
        reorder_point = float(stock.get("reorder_point", 0) or 0)

        if sales_signal.get("derived_from_recipe") and recipe_recovery_signal.get("enabled"):
            demand_candidates = [
                float(expected_daily_demand) if expected_daily_demand is not None else 0.0,
                float(recipe_recovery_signal.get("recipe_daily_demand_equivalent", 0) or 0),
                float(consumption_signal.get("recent_average_consumption", 0) or 0),
                float(consumption_signal.get("recent_peak_consumption", 0) or 0),
                backlog_daily_equivalent,
            ]
        else:
            demand_candidates = [
                float(expected_daily_demand) if expected_daily_demand is not None else 0.0,
                sales_recent_average,
                sales_recent_peak,
                float(consumption_signal.get("recent_average_consumption", 0) or 0),
                float(consumption_signal.get("recent_peak_consumption", 0) or 0),
                backlog_daily_equivalent,
            ]
        forecast_daily_demand = max(demand_candidates)

        demand_cover_inventory = forecast_daily_demand * max(1, int(target_inventory_days)) + effective_safety_stock
        policy_floor_inventory = max(reorder_point, effective_safety_stock)
        target_inventory = max(demand_cover_inventory, policy_floor_inventory)
        inventory_position = on_hand_quantity + incoming_quantity - backlog_quantity
        raw_suggested_order_quantity = max(0, target_inventory - inventory_position)
        recipe_recovery_target_quantity = float(recipe_recovery_signal.get("recovery_target_material_quantity", 0) or 0)
        recipe_recovery_gap_quantity = max(0.0, recipe_recovery_target_quantity - (on_hand_quantity + incoming_quantity))
        if recipe_recovery_signal.get("enabled"):
            raw_suggested_order_quantity = max(raw_suggested_order_quantity, recipe_recovery_gap_quantity)
            replenishment_soft_cap = max(
                recipe_recovery_gap_quantity * float(self.config.RECIPE_RECOVERY_SOFT_CAP_MULTIPLIER or 1.0)
                + effective_safety_stock * float(self.config.RECIPE_RECOVERY_SAFETY_BUFFER_SHARE or 1.0),
                max(0.0, reorder_point - on_hand_quantity) + effective_safety_stock,
            )
            amplification_mode = self._get_bullwhip_manufacturer_upstream_amplification()
            if self._is_runtime_switch_enabled_for_current_enterprise(amplification_mode):
                replenishment_soft_cap = max(
                    replenishment_soft_cap,
                    recipe_recovery_gap_quantity * self._safe_number(
                        amplification_mode.get("replenishment_soft_cap_multiplier"),
                        1.0,
                    ) + effective_safety_stock,
                )
        else:
            replenishment_soft_cap = max(
                backlog_quantity + forecast_daily_demand * max(1, int(target_inventory_days)) + effective_safety_stock,
                max(0.0, reorder_point - on_hand_quantity) + effective_safety_stock,
            )
        suggested_order_quantity = (
            min(raw_suggested_order_quantity, replenishment_soft_cap)
            if replenishment_soft_cap > 0
            else raw_suggested_order_quantity
        )
        profit_long_run_guard = self._apply_profit_long_run_replenishment_guard(
            material_id=material_id,
            raw_suggested_order_quantity=suggested_order_quantity,
            on_hand_quantity=on_hand_quantity,
            incoming_quantity=incoming_quantity,
            backlog_quantity=backlog_quantity,
            forecast_daily_demand=forecast_daily_demand,
            expected_daily_demand=expected_daily_demand,
            sales_recent_average=sales_recent_average,
            consumption_recent_average=float(consumption_signal.get("recent_average_consumption", 0) or 0),
            effective_safety_stock=effective_safety_stock,
            reorder_point=reorder_point,
        )
        suggested_order_quantity = profit_long_run_guard.get("quantity", suggested_order_quantity)
        result = {
            "material_id": material_id,
            "round": self._get_current_day(),
            "on_hand_quantity": on_hand_quantity,
            "incoming_quantity": incoming_quantity,
            "backlog_quantity": backlog_quantity,
            "forecast_daily_demand": forecast_daily_demand,
            "target_inventory_days": target_inventory_days,
            "safety_stock": effective_safety_stock,
            "reorder_point": reorder_point,
            "target_inventory": target_inventory,
            "inventory_position": inventory_position,
            "suggested_order_quantity": suggested_order_quantity,
            "raw_suggested_order_quantity": raw_suggested_order_quantity,
            "replenishment_soft_cap": replenishment_soft_cap,
            "profit_long_run_replenishment_guard": profit_long_run_guard,
            "recipe_recovery_signal": recipe_recovery_signal,
            "recipe_recovery_gap_quantity": recipe_recovery_gap_quantity,
            "history_window": history_window,
            "demand_signal_breakdown": {
                "input_expected_daily_demand": float(expected_daily_demand) if expected_daily_demand is not None else 0.0,
                "sales_recent_average_demand": sales_recent_average,
                "sales_recent_peak_demand": sales_recent_peak,
                "recent_average_consumption": float(consumption_signal.get("recent_average_consumption", 0) or 0),
                "recent_peak_consumption": float(consumption_signal.get("recent_peak_consumption", 0) or 0),
                "backlog_daily_equivalent": backlog_daily_equivalent,
                "policy_floor_inventory": policy_floor_inventory,
                "replenishment_soft_cap": replenishment_soft_cap,
                "derived_from_recipe": bool(sales_signal.get("derived_from_recipe")),
                "recipe_recovery_target_material_quantity": recipe_recovery_target_quantity,
                "recipe_recovery_gap_quantity": recipe_recovery_gap_quantity,
            }
        }
        return self.success_response(
            response,
            f"已计算 {material_id} 的补货建议",
            result
        )

    @with_response("create_replenishment_order")
    def create_replenishment_order(
        self,
        material_id: str,
        target_inventory_days: int = 2,
        quantity: int = 100,
        safety_stock: float = 0,
        expected_daily_demand: Optional[float] = None,
        max_price: Optional[float] = None,
        expected_due_round: Optional[int] = None,
        dry_run: bool = False,
        response: ModuleResponse = None
    ) -> ModuleResponse:
        if material_id not in getattr(self.enterprise, "purchasable_materials_idList", []):
            return self.error_response(
                response,
                "MATERIAL_NOT_PURCHASABLE",
                f"企业 {self.enterprise.id} 不允许采购物料 {material_id}。可采购物料: {getattr(self.enterprise, 'purchasable_materials_idList', [])}"
            )

        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="procurement")
        employee_count = hr_result.data.get("count", 0)
        if employee_count < self.config.MIN_PROCUREMENT_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法创建补货订单。至少需要: {self.config.MIN_PROCUREMENT_STAFF}"
            )

        calculation = self.calculate_replenishment_quantity(
            material_id=material_id,
            target_inventory_days=target_inventory_days,
            safety_stock=safety_stock,
            expected_daily_demand=expected_daily_demand
        ).data

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", calculation)

        suggested_order_quantity = calculation.get("suggested_order_quantity", 0) or 0
        if suggested_order_quantity <= 0:
            history_item = {
                **calculation,
                "request_id": None,
                "created_request": False,
                "expected_due_round": expected_due_round,
                "max_price": max_price,
                "requested_quantity": 0,
                "fallback_quantity": quantity,
            }
            self.replenishment_history.append(history_item)
            return self.success_response(
                response,
                f"{material_id} 当前无需补货，未创建采购请求",
                history_item
            )

        current_time = self._get_current_day()
        resolved_expected_due_round = expected_due_round
        if resolved_expected_due_round is None:
            resolved_expected_due_round = current_time + 1
        else:
            resolved_expected_due_round = max(current_time + 1, int(resolved_expected_due_round))
        pricing = self._resolve_b2b_max_price(
            material_id=material_id,
            explicit_max_price=max_price,
            expected_due_round=resolved_expected_due_round,
        )
        effective_max_price = pricing["max_price"]
        if getattr(self.enterprise, "upstream_exchange", None) is None:
            if not self._direct_external_replenishment_enabled():
                return self.error_response(
                    response,
                    "UPSTREAM_EXCHANGE_UNAVAILABLE",
                    "当前企业未连接上游交易所，且未启用直接外部补给 fallback",
                )
            supplier = self._select_external_supplier_for_material(material_id)
            if supplier is None:
                return self.error_response(
                    response,
                    "EXTERNAL_SUPPLIER_NOT_FOUND",
                    f"未找到可提供 {material_id} 的外部供应商",
                )
            material_info = supplier.get("material_info") or {}
            direct_quantity = self._round_up_to_moq(
                suggested_order_quantity,
                self._safe_number(material_info.get("min_order_quantity")),
            )
            purchase_result = self.create_purchase_order(
                material_id=material_id,
                quantity=direct_quantity,
                supplier_name=supplier.get("supplier_name"),
                logistics_mode=self.config.TOP_TIER_CRITICAL_LOGISTICS_MODE,
            )
            if not getattr(purchase_result, "success", False):
                return purchase_result
            purchase_data = purchase_result.data if isinstance(purchase_result.data, dict) else {}
            order = purchase_data.get("order") or {}
            history_item = {
                **calculation,
                "request_id": order.get("order_id"),
                "created_request": True,
                "request_channel": "direct_external_supplier",
                "expected_due_round": order.get("arrival_time"),
                "max_price": effective_max_price,
                "pricing_strategy": pricing,
                "requested_quantity": direct_quantity,
                "fallback_quantity": quantity,
                "supplier_name": supplier.get("supplier_name"),
            }
            self.replenishment_history.append(history_item)
            self.upstream_order_history.append({
                "round": current_time,
                "request_id": order.get("order_id"),
                "material_id": material_id,
                "quantity": direct_quantity,
                "expected_due_round": order.get("arrival_time"),
                "reason": "direct_external_replenishment_fallback",
            })
            return self.success_response(
                response,
                f"已通过外部供应商 {supplier.get('supplier_name')} 为 {material_id} 建立直接补货订单",
                history_item,
            )

        data = self.enterprise.upstream_exchange.submit_buy_request(
            buyer_company_id=self.enterprise.id,
            product_id=material_id,
            quantity=suggested_order_quantity,
            created_round=current_time,
            max_price=effective_max_price,
            expected_due_round=resolved_expected_due_round
        )
        history_item = {
            **calculation,
            "request_id": data.request_id,
            "created_request": True,
            "expected_due_round": resolved_expected_due_round,
            "max_price": effective_max_price,
            "pricing_strategy": pricing,
            "requested_quantity": suggested_order_quantity,
            "fallback_quantity": quantity,
        }
        self.replenishment_history.append(history_item)
        self.upstream_order_history.append({
            "round": current_time,
            "request_id": data.request_id,
            "material_id": material_id,
            "quantity": suggested_order_quantity,
            "expected_due_round": resolved_expected_due_round,
            "reason": "replenishment_policy"
        })
        return self.success_response(
            response,
            f"已按补货策略为 {material_id} 建立采购需求",
            history_item
        )

    @with_response("create_purchase_order")
    @validate_positive("quantity")
    def create_purchase_order(self, material_id: str, quantity: float,
                             supplier_name, logistics_mode: str = "road", 
                             dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Create purchase order

        Args:
            parameter: MaterialsID
            Number of purchases
            parameter: Name of supplier
            < x17/ > : Logistics Mode ( "Road", "rail", "air")
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Create a unified response to the result
                """
        # Check department personnel
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="procurement")       
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_PROCUREMENT_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法创建采购订单。至少需要: {self.config.MIN_PROCUREMENT_STAFF}"
            )
        if logistics_mode not in self.config.LOGISTICS_CONFIGS:
            return self.error_response(
                response,
                "INVALID_LOGISTICS_MODE",
                f"无效的物流方式，请选择 'road', 'rail', 或 'air'"
            )

        # Validation of supply Business
        supplier = None
        selected_candidate = None
        supplier_id = self._get_supplier_id_by_name(supplier_name)
        if supplier_id:
            for s_id, supplier in self.suppliers.items():
                if s_id == supplier_id:
                    supplier = self.suppliers[s_id]
                    break
        if supplier is None:
            selected_candidate = self._find_supplier_candidate_by_name(supplier_name)
            if selected_candidate is None:
                return self.error_response(
                    response,
                    "SUPPLIER_NOT_FOUND",
                    f"供应商 {supplier_name} 不存在，也不在可选供应商目录中"
                )
            supplier = selected_candidate
        # 3. Certification of the supplier ' s supply of the material
        if material_id not in supplier["materials"]:
            return self.error_response(
                response,
                "MATERIAL_NOT_AVAILABLE",
                f"供应商 {supplier_name} 不提供材料 {material_id}"
            )

        material_info = supplier["materials"][material_id]

        # 4. Check for minimum start-up
        min_order_qty = material_info.get("min_order_quantity", 0)
        if quantity < min_order_qty:
            return self.error_response(
                response,
                "MIN_ORDER_NOT_MET",
                f"未满足最小起订量。需要: {min_order_qty}, 当前: {quantity}"
            )

        # 5. Costing
        unit_price = material_info["unit_price"]
        material_cost = unit_price * quantity

        # Calculating Logistics Costs (Return ModeuleResponse)
        logistics_result = self.calculate_logistics_cost(logistics_mode, quantity)
        if not logistics_result.success:
            return self.error_response(
                response,
                "LOGISTICS_COST_ERROR",
                f"物流成本计算失败: {logistics_result.message}"
            )

        # Recovery of logistics costs and processing of different types of return
        if isinstance(logistics_result.data, dict):
            raw_logistics_cost = logistics_result.data.get("cost", 0)
        elif isinstance(logistics_result.data, (int, float)):
            raw_logistics_cost = logistics_result.data
        else:
            raw_logistics_cost = 0

        logistics_cost = self._apply_top_tier_logistics_cost_adjustment(raw_logistics_cost, supplier)

        total_cost = material_cost + logistics_cost

        supplier_type = supplier["supplier_type"]
        top_tier_credit_enabled = self._is_top_tier_credit_enabled_for_supplier(supplier)

        # 6. Inspection of funds or top credit lines
        finance_manager = super().get_module_by_type("FinanceManager")
        balance_result = finance_manager.get_balance()
        if isinstance(balance_result, (int, float)):
            balance_value = balance_result
        elif hasattr(balance_result, 'data'):
            balance_value = balance_result.data.get("balance", 0) if isinstance(balance_result.data, dict) else 0
        elif isinstance(balance_result, dict):
            balance_value = balance_result.get("balance", 0)
        else:
            balance_value = 0

        cash_commitment = None
        credit_commitment = None
        payment_mode = "cash"
        payable_due_round = None
        if top_tier_credit_enabled:
            credit_commitment = self._evaluate_top_tier_credit_commitment(total_cost)
            if credit_commitment["is_hard_blocked"]:
                reason = credit_commitment.get("hard_block_reason")
                if reason == "single_order_limit_exceeded":
                    return self.error_response(
                        response,
                        "EXTERNAL_CREDIT_SINGLE_ORDER_LIMIT_EXCEEDED",
                        (
                            "单笔外部采购金额超出顶层授信单笔上限。"
                            f" 需要: ¥{total_cost:,.2f}, 上限: ¥{credit_commitment['guard'].get('max_single_order_amount', 0):,.2f}"
                        )
                    )
                return self.error_response(
                    response,
                    "EXTERNAL_CREDIT_LIMIT_EXCEEDED",
                    (
                        "顶层外部授信额度不足。"
                        f" 需要: ¥{total_cost:,.2f}, 可用额度: ¥{credit_commitment['guard'].get('available_credit', 0):,.2f}"
                    )
                )
            payment_mode = "accounts_payable"
        else:
            if balance_value < total_cost:
                return self.error_response(
                    response,
                    "INSUFFICIENT_FUNDS",
                    f"资金不足，需要 ¥{total_cost:,.2f}"
                )
            cash_commitment = self._evaluate_cash_commitment(total_cost)

        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "material_id": material_id,
                    "quantity": quantity,
                    "supplier_name": supplier_name,
                    "supplier_registration_status": (
                        "candidate" if selected_candidate is not None else "registered"
                    ),
                    "logistics_mode": logistics_mode,
                    "raw_logistics_cost": raw_logistics_cost,
                    "estimated_total_cost": total_cost,
                    "cash_commitment": cash_commitment,
                    "credit_commitment": credit_commitment,
                    "payment_mode": payment_mode,
                    "logistics_cost_multiplier": self._get_top_tier_logistics_cost_multiplier(supplier),
                }
            )

        # Distinguishing between external and enterprise procurement
        if supplier_type == "external":
            # Direct external procurement
            # 8. Calculation of delivery cycle
            logistics_config = self.config.LOGISTICS_CONFIGS[logistics_mode]
            supplier_processing_time = supplier.get("processing_time", 0)
            delivery_time = logistics_config["transit_time"] + supplier_processing_time
            order_time = self.enterprise.time_manager.get_day()
            arrival_time = order_time + delivery_time

            # 9. Creation of order records
            order_id = f"PROCUREMENT_ORDER_{self.next_order_id}"
            self.next_order_id += 1
            assigned_workers = self.config.MIN_PROCUREMENT_STAFF
            purchase_order = {
                "order_id": order_id,
                "material_id": material_id,
                "quantity": quantity,
                "supplier_id": supplier_id,
                "unit_price": unit_price,
                "material_cost": material_cost,
                "logistics_mode": logistics_mode,
                "raw_logistics_cost": raw_logistics_cost,
                "logistics_cost": logistics_cost,
                "total_cost": total_cost,
                "order_time": order_time,
                "delivery_time": delivery_time,
                "arrival_time": arrival_time,
                "status": "pending",  # Wait for the goods.
                "payment_mode": payment_mode,
                "payable_due_round": (
                    arrival_time + int((credit_commitment.get("guard") or {}).get("payable_delay_rounds", 0) or 0)
                    if payment_mode == "accounts_payable"
                    else None
                ),
                "payable_status": "not_recorded" if payment_mode == "accounts_payable" else None,
                "credit_policy_applied": top_tier_credit_enabled,
                "credit_limit_snapshot": (
                    (credit_commitment.get("guard") or {}).get("external_credit_limit")
                    if credit_commitment else None
                ),
                "logistics_cost_multiplier": self._get_top_tier_logistics_cost_multiplier(supplier),
                "actual_arrival_time": None,
                "on_time": None,
                "assigned_workers": assigned_workers
            }

            assign_result = hr_manager.assign_workers(
                'procurement',
                order_id,
                self.config.MIN_PROCUREMENT_STAFF
            )
            if not getattr(assign_result, "success", True):
                return self.error_response(
                    response,
                    "ASSIGN_WORKERS_ERROR",
                    getattr(assign_result, "message", "采购订单人手分配失败")
                )

            selected_on_order = selected_candidate is not None
            if selected_on_order:
                supplier_id = f"SUPPLIER_{self.next_supplier_id}"
                self.next_supplier_id += 1
                self.suppliers[supplier_id] = {
                    "supplier_id": supplier_id,
                    "supplier_name": selected_candidate["supplier_name"],
                    "supplier_type": selected_candidate["supplier_type"],
                    "materials": deepcopy(selected_candidate["materials"]),
                    "processing_time": selected_candidate.get("processing_time", 0),
                    "quality_level": selected_candidate.get("quality_level", "standard"),
                    "reliability_score": selected_candidate.get("reliability_score", 1.0),
                    "total_orders": 0,
                    "on_time_deliveries": 0,
                }
                supplier = self.suppliers[supplier_id]
                supplier_name_list = getattr(self.enterprise, "supplier_name_list", None)
                if isinstance(supplier_name_list, list) and supplier["supplier_name"] not in supplier_name_list:
                    supplier_name_list.append(supplier["supplier_name"])
                selection_event = {
                    "type": "supplier_selected",
                    "round": order_time,
                    "supplier_id": supplier_id,
                    "supplier_name": supplier.get("supplier_name"),
                    "material_id": material_id,
                    "quantity": quantity,
                    "logistics_mode": logistics_mode,
                    "expected_arrival_round": arrival_time,
                    "selection_mode": "register_on_first_purchase",
                }
                self.supplier_selection_events.append(selection_event)
                self._log_event(selection_event)

            purchase_order["supplier_id"] = supplier_id
            purchase_order["supplier_name"] = supplier.get("supplier_name")
            purchase_order["supplier_selected_on_order"] = selected_on_order

            self.purchase_orders.append(purchase_order)
            self.procurement_metrics["total_orders"] += 1
            self.procurement_metrics["total_cost"] += total_cost
            self.procurement_metrics["total_quantity"] += quantity

            # 10. Recording events
            self._log_event({
                "type": "order_created",
                "order_id": order_id,
                "material_id": material_id,
                "quantity": quantity,
                "total_cost": total_cost,
                "cash_commitment_level": cash_commitment.get("commitment_level") if cash_commitment else None,
                "credit_commitment_level": credit_commitment.get("commitment_level") if credit_commitment else None,
                "payment_mode": payment_mode,
                "supplier_name": supplier.get("supplier_name"),
                "supplier_selected_on_order": selected_on_order,
            })
            # Setup Successful Response
            return self.success_response(
                response,
                f"采购订单 {order_id} 已创建,根据所选物流,至少需要等待{delivery_time}个工作日才能收到采购货物",
                {
                    "order_id": order_id,
                    "arrival_time": arrival_time,
                    "total_cost": total_cost,
                    "cash_commitment": cash_commitment,
                    "credit_commitment": credit_commitment,
                    "payment_mode": payment_mode,
                    "order": purchase_order
                }
            )
    @skip_dry_run_validation
    @with_response("check_arrived_orders")
    def check_arrived_orders(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Check and process arrival orders (call at the beginning of each step)

        Args:
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified response object with arrival information list
                """
            
        arrived_materials = []
        hr_manager = super().get_module_by_type("HRManager")
        for order in self.purchase_orders:
            if (order["status"] == "pending" and
                self.enterprise.time_manager.get_day() >= order["arrival_time"]):
                
                # Update order status
                order["status"] = "received"
                order["actual_arrival_time"] = self.enterprise.time_manager.get_day()
                order["on_time"] = (order["actual_arrival_time"] <= order["arrival_time"])

                # Deduction of funds
                finance_manager = super().get_module_by_type("FinanceManager")
                use_accounts_payable = order.get("payment_mode") == "accounts_payable"
                cost_result = finance_manager.add_cost(
                    order["total_cost"],
                    "procurement_cost",
                    accounts_payable=use_accounts_payable
                )
                if use_accounts_payable:
                    order["payable_status"] = "open"
                    order["payable_recorded_round"] = self.enterprise.time_manager.get_day()

                # Updating of inventories
                inventory_manager = super().get_module_by_type("InventoryManager")
                inventory_manager.add_inventory(order["material_id"], order["quantity"],order["unit_price"],"raw_material")

                # Update of vendor statistics
                if order["supplier_id"] in self.suppliers:
                    supplier = self.suppliers[order["supplier_id"]]
                    supplier["total_orders"] += 1
                    if order["on_time"]:
                        supplier["on_time_deliveries"] += 1

                # Update indicators
                self.procurement_metrics["completed_orders"] += 1
                if order["on_time"]:
                    self.procurement_metrics["on_time_delivery_count"] += 1

                # Update on-time arrival rate
                if self.procurement_metrics["completed_orders"] > 0:
                    self.procurement_metrics["on_time_rate"] = (
                        self.procurement_metrics["on_time_delivery_count"] /
                        self.procurement_metrics["completed_orders"]
                    )

                # Can not open message
                arrival_info = {
                    "order_id": order["order_id"],
                    "material_id": order["material_id"],
                    "quantity": order["quantity"],
                    "unit_price": order["unit_price"],
                    "total_value": order.get("material_cost", order.get("total_cost", 0)),
                    "on_time": order["on_time"]
                }

                # Release the staff.
                if order.get("assigned_workers", 0) > 0:
                    hr_manager.release_workers(
                        'procurement',
                        order["order_id"],
                        order["assigned_workers"],
                        "completed"
                    )

                # Record Events
                self._log_event({
                    "type": "order_arrived",
                    "order_id": order["order_id"],
                    "material_id": order["material_id"],
                    "quantity": order["quantity"],
                    "on_time": order["on_time"]
                })

                arrived_materials.append(arrival_info)

        # Setup Successful Response
        return self.success_response(
            response,
            f"成功处理 {len(arrived_materials)} 个到货订单",
            {
                "arrived_materials": arrived_materials,
                "total_arrived": len(arrived_materials)
            }
        )

    @with_response("settle_external_payables")
    def settle_external_payables(self, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """Carry-over of the most upward award of accounts payable after maturity and maintain real financial discipline."""
        finance_manager = super().get_module_by_type("FinanceManager")
        current_day = self._get_current_day()
        due_orders = []
        overdue_orders = []
        for order in self.purchase_orders:
            if order.get("payment_mode") != "accounts_payable":
                continue
            if order.get("status") != "received":
                continue
            if order.get("payable_status") == "paid":
                continue
            payable_due_round = order.get("payable_due_round")
            if payable_due_round is None:
                continue
            if int(payable_due_round) <= current_day:
                if int(payable_due_round) < current_day:
                    overdue_orders.append(order)
                due_orders.append(order)

        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "due_order_count": len(due_orders),
                    "due_amount": sum(float(order.get("total_cost", 0) or 0) for order in due_orders),
                    "overdue_order_count": len(overdue_orders),
                }
            )

        settled_orders = []
        blocked_orders = []
        for order in sorted(due_orders, key=lambda item: item.get("payable_due_round", current_day)):
            amount = float(order.get("total_cost", 0) or 0)
            if int(order.get("payable_due_round", current_day)) < current_day:
                order["payable_status"] = "overdue"
            settle_result = finance_manager.pay_accounts_payable(
                amount,
                description=f"settle external procurement payable for {order['order_id']}"
            )
            if getattr(settle_result, "success", False):
                order["payable_status"] = "paid"
                order["payable_paid_round"] = current_day
                settled_orders.append({
                    "order_id": order["order_id"],
                    "amount": amount,
                })
                self._log_event({
                    "type": "external_payable_settled",
                    "order_id": order["order_id"],
                    "amount": amount,
                })
            else:
                order["payable_status"] = "overdue"
                blocked_orders.append({
                    "order_id": order["order_id"],
                    "amount": amount,
                    "message": getattr(settle_result, "message", "payable settlement failed"),
                })

        return self.success_response(
            response,
            f"已处理 {len(settled_orders)} 笔顶层外采应付账款结算",
            {
                "settled_orders": settled_orders,
                "blocked_orders": blocked_orders,
                "due_order_count": len(due_orders),
            }
        )

    @with_response("cancel_order")
    def cancel_order(self, order_id: str, reason: str = "", 
                     dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Cancellation of purchase orders (on arrival orders only)

        Args:
            parameter: Order ID
            Reason for cancellation
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unanimous object for cancelled result
                """
        # Check department personnel
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="procurement")
        employee_count = hr_result.data.get("count", 0) 

        if employee_count < self.config.MIN_CANCEL_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法取消采购订单。至少需要: {self.config.MIN_CANCEL_STAFF}"
            )

        order = self._find_order(order_id)
        if not order:
            return self.error_response(
                response,
                "ORDER_NOT_FOUND",
                f"订单 {order_id} 不存在"
            )

        if order["status"] != "pending":
            return self.error_response(
                response,
                "INVALID_STATUS",
                f"订单状态为 {order['status']}，无法取消"
            )

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        # Update order status
        order["status"] = "cancelled"
        self.procurement_metrics["cancelled_orders"] += 1

        # Refund (simplified version: full refund)
        finance_manager = super().get_module_by_type("FinanceManager")
        finance_manager.add_cost(
            order["total_cost"],
            "other_cost",
            "order_cancellation_refund"
        )

        # Record Events
        self._log_event({
            "type": "order_cancelled",
            "order_id": order_id,
            "reason": reason
        })

        if order.get("assigned_workers", 0) > 0:
            hr_manager.release_workers(
                'procurement',
                order_id,
                order["assigned_workers"],
                "cancelled"
            )


        # Setup Successful Response
        return self.success_response(
            response,
            f"订单 {order_id} 已取消，退款 ¥{order['total_cost']:,.2f}",
            {
                "order_id": order_id,
                "refund_amount": order["total_cost"],
                "order": order
            }
        )

    @with_response("get_order_detail")
    def get_order_detail(self, order_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Get order details

        Args:
            parameter: Order ID
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified responder with order details
                """
        order = self._find_order(order_id)

        if order:
            return self.success_response(
                response,
                f"成功获取订单 {order_id} 详情",
                {
                    "order_id": order_id,
                    "order": order
                }
            )
        else:
            return self.error_response(
                response,
                "ORDER_NOT_FOUND",
                f"订单 {order_id} 不存在"
            )

    @with_response("get_all_orders")
    def get_all_orders(self, status_filter: Optional[str] = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        Get all orders

        Args:
            parameter: Status filter (optional)
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModeuleResponse: Unified response object with order list
                """
        if status_filter:
            orders = [order for order in self.purchase_orders if order["status"] == status_filter]
        else:
            orders = self.purchase_orders.copy()

        return self.success_response(
            response,
            f"成功获取 {len(orders)} 个订单",
            {
                "orders": orders,
                "total_orders": len(orders),
                "status_filter": status_filter
            }
        )

    @with_response("get_pending_orders")
    def get_pending_orders(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Retrieving pending orders

        Args:
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified response object with list of pending orders
                """
        # Direct call to get all orders, which has been updated to return ModeuleResponse
        result = self.get_all_orders(status_filter="pending")

        # As Get all orders has returned to ModeuleResponse, we can return directly. It's...
        # But in order to keep the signature consistent, we can repackage or return directly.
        return result


    @with_response("register_supplier")
    def register_supplier(self, supplier_name: str, supplier_type: str,
                         materials: Dict[str, Dict], processing_time: int = 0,
                         quality_level: str = "standard", reliability_score: float = 1.0,
                         dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Registered vendors

        Args:
            parameter: Name of supplier
            supplier_type: Vendor Type ("external" or "interprise")
            Materiels: Materials provided
            processing_time: processing time (time steps)
            < x17/>: Quality level ( "low", "standard", "high")
            reliability_score: Reliability rating (0.0-1.0)
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unanimous respondents to registration results
                """
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "supplier_name": supplier_name,
                    "supplier_type": supplier_type,
                    "materials": list((materials or {}).keys())
                }
            )
        supplier_id = f"SUPPLIER_{self.next_supplier_id}"
        self.next_supplier_id += 1

        self.suppliers[supplier_id] = {
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "supplier_type": supplier_type,
            "materials": materials,
            "processing_time": processing_time,
            "quality_level": quality_level,
            "reliability_score": reliability_score,
            "total_orders": 0,           # Statistics on total orders
            "on_time_deliveries": 0      # Statistics on timely delivery
        }

        return self.success_response(
            response,
            f"供应商 {supplier_name} 已注册",
            {
                "supplier_id": supplier_id,
                "supplier_name": supplier_name
            }
        )

    @with_response("get_supplier_info")
    def get_supplier_info(self, supplier_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access to vendor information

        Args:
            parameter: Vendor ID
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModeuleResponse: Unified responder with supplier information
                """
        supplier = self.suppliers.get(supplier_id)

        if supplier:
            return self.success_response(
                response,
                f"成功获取供应商 {supplier_id} 信息",
                {
                    "supplier_id": supplier_id,
                    "supplier": supplier
                }
            )
        else:
            return self.error_response(
                response,
                "SUPPLIER_NOT_FOUND",
                f"供应商 {supplier_id} 不存在"
            )

    @with_response("get_all_suppliers")
    def get_all_suppliers(self, supplier_type: Optional[str] = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access to all suppliers

        Args:
            supplier_type: Vendor type filter (optional)
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModeuleResponse: Unified responder with supplier list
                """
        # Get list of suppliers
        if supplier_type:
            suppliers_list = [s for s in self.suppliers.values() if s["supplier_type"] == supplier_type]
        else:
            suppliers_list = list(self.suppliers.values())

        return self.success_response(
            response,
            f"成功获取供应商列表，共 {len(suppliers_list)} 个供应商",
            {
                "suppliers": suppliers_list,
                "total_suppliers": len(suppliers_list),
                "supplier_type_filter": supplier_type
            }
        )

    @with_response("query_suppliers_by_material")
    def query_suppliers_by_material(self, material_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Query of suppliers providing specific materials

        Args:
            parameter: MaterialsID
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModeuleResponse: Unified responder with supplier list
                """
        suppliers_with_material = []

        for supplier in self.suppliers.values():
            if material_id in supplier["materials"]:
                material_info = supplier["materials"][material_id]
                suppliers_with_material.append({
                    "supplier_id": supplier["supplier_id"],
                    "supplier_name": supplier["supplier_name"],
                    "supplier_type": supplier["supplier_type"],
                    "unit_price": material_info["unit_price"],
                    "min_order_quantity": material_info.get("min_order_quantity", 0),
                    "quality_level": supplier["quality_level"],
                    "reliability_score": supplier["reliability_score"],
                    "processing_time": supplier["processing_time"]
                })

        # Sort by price
        suppliers_with_material.sort(key=lambda x: x["unit_price"])

        return self.success_response(
            response,
            f"成功查询到 {len(suppliers_with_material)} 个提供材料 {material_id} 的供应商",
            {
                "suppliers": suppliers_with_material,
                "total_suppliers": len(suppliers_with_material),
                "material_id": material_id,
                "sorted_by": "unit_price"
            }
        )


    @with_response("calculate_logistics_cost")
    @validate_positive("quantity")
    def calculate_logistics_cost(self, logistics_mode: str, quantity: float, response: ModuleResponse = None) -> ModuleResponse:
        """
        Calculation of logistics costs

        Args:
            < x17/ > : Logistics Mode ( "Road", "rail", "air")
            Number
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Harmonized target audience with logistics costs
                """
        if logistics_mode not in self.config.LOGISTICS_CONFIGS:
            return self.error_response(
                response,
                "INVALID_LOGISTICS_MODE",
                f"未知的物流方式: {logistics_mode}"
            )

        config = self.config.LOGISTICS_CONFIGS[logistics_mode]
        logistics_cost = config["base_fee"] + config["unit_fee"] * quantity

        return self.success_response(
            response,
            "成功计算物流成本",
            {
                "logistics_mode": logistics_mode,
                "quantity": quantity,
                "cost": logistics_cost,
                "base_fee": config["base_fee"],
                "unit_fee": config["unit_fee"],
                "logistics_name": config["name"],
                "transit_time": config["transit_time"]
            }
        )

    @with_response("calculate_total_cost")
    @validate_positive("quantity")
    def calculate_total_cost(self, material_id: str, quantity: float,
                           supplier_name: str, logistics_mode: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Calculating total procurement costs (unrealized billing, only for cost estimation)

        Args:
            parameter: MaterialsID
            Number of purchases
            parameter: Name of supplier
            parameter: logistics approach
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified response object with costing results
                """
        # Validation of supply Business
        supplier_id = self._get_supplier_id_by_name(supplier_name)
        if supplier_id is None:
            return self.error_response(
                response,
                "SUPPLIER_NOT_FOUND",
                f"供应商 {supplier_name} 不存在"
            )

        supplier = self.suppliers[supplier_id]

        # 2. Validation materials
        if material_id not in supplier["materials"]:
            return self.error_response(
                response,
                "MATERIAL_NOT_PROVIDED",
                f"供应商 {supplier_name} 不提供材料 {material_id}"
            )

        # 3. Costing of materials
        unit_price = supplier["materials"][material_id]["unit_price"]
        material_cost = unit_price * quantity

        # 4. Calculation of logistics costs (note: now the method returns to ModeuleResponse)
        logistics_result = self.calculate_logistics_cost(logistics_mode, quantity)

        # Check the success of logistics costing
        if not logistics_result.success:
            return self.error_response(
                response,
                "LOGISTICS_COST_ERROR",
                "物流成本计算失败"
            )

        # Recovery of logistics costs and processing of different types of return
        if isinstance(logistics_result.data, dict):
            raw_logistics_cost = logistics_result.data.get("cost", 0)
        elif isinstance(logistics_result.data, (int, float)):
            raw_logistics_cost = logistics_result.data
        else:
            raw_logistics_cost = 0

        logistics_cost = self._apply_top_tier_logistics_cost_adjustment(raw_logistics_cost, supplier)

        # 5. Calculation of total costs
        total_cost = material_cost + logistics_cost

        return self.success_response(
            response,
            "成功计算总采购成本",
            {
                "material_id": material_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "material_cost": material_cost,
                "logistics_mode": logistics_mode,
                "raw_logistics_cost": raw_logistics_cost,
                "logistics_cost": logistics_cost,
                "total_cost": total_cost,
                "unit_total_cost": total_cost / quantity if quantity > 0 else 0,
                "supplier_name": supplier_name,
                "supplier_id": supplier_id,
                "logistics_cost_multiplier": self._get_top_tier_logistics_cost_multiplier(supplier),
            }
        )

    @with_response("get_logistics_info")
    def get_logistics_info(self, logistics_mode: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access to logistics information

        Args:
            parameter: logistics approach
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Harmonized Response Object with Logistics Information
                """
        # Access logistics configuration
        logistics_config = self.config.LOGISTICS_CONFIGS.get(logistics_mode)

        if logistics_config:
            return self.success_response(
                response,
                f"成功获取物流方式 {logistics_mode} 的信息",
                {
                    "logistics_mode": logistics_mode,
                    "logistics_info": logistics_config
                }
            )
        else:
            return self.error_response(
                response,
                "LOGISTICS_MODE_NOT_FOUND",
                f"未知的物流方式: {logistics_mode}"
            )


    @with_response("initiate_negotiation")
    @validate_positive("quantity")
    @validate_positive("target_price")
    @validate_positive("max_acceptable_price")
    def initiate_negotiation(self, target_enterprise_id: str, product_id: str,
                           quantity: float, target_price: float,
                           max_acceptable_price: float, response: ModuleResponse = None) -> ModuleResponse:
        """
        B2B consultations initiated (simplified version, information system support actually required)

        Args:
            target_enterprise_id: TargetenterpriseID
            product_id: Product ID
            Number
            parameter: Target price
            max_acceptable_price: Maximum acceptable price
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified response to the outcome of the consultation
                """
        negotiation_id = f"negotiation_{self.next_negotiation_id}"
        self.next_negotiation_id += 1

        negotiation = {
            "negotiation_id": negotiation_id,
            "target_enterprise_id": target_enterprise_id,
            "product_id": product_id,
            "quantity": quantity,
            "target_price": target_price,
            "max_acceptable_price": max_acceptable_price,
            "status": "pending",  # pending, accepted, rejected, failed
            "created_time": self.enterprise.time_manager.get_day(),
            "rounds": 0,
            "current_offer": None,
            "final_price": None
        }

        self.negotiations[negotiation_id] = negotiation

        # Updating of consultation indicators
        # self.procurement_metrics["total_negotiations"] += 1

        # Record Events
        self._log_event({
            "type": "negotiation_initiated",
            "negotiation_id": negotiation_id,
            "target_enterprise_id": target_enterprise_id,
            "product_id": product_id,
            "quantity": quantity
        })

        result = self.enterprise.send_message(
            recipient_id=target_enterprise_id,
            message_type="Procurement",
            content={
                'action_type': 'negotiation_initiated',
                "negotiation_id": negotiation_id,
                "product_id": product_id,
                "quantity": quantity,
                "target_price": target_price,
                "max_acceptable_price": max_acceptable_price,
                "speaker": self.enterprise.id,
                "receiver": target_enterprise_id
            }
        )

        if result.success:
            return self.success_response(
                response,
                "协商已发起",
                {
                    "negotiation_id": negotiation_id
                }
            )
        else:
            return self.error_response(
                response,
                "NEGOTIATION_SEND_FAILED",
                "协商发起失败"
            )

    @with_response("respond_to_offer")
    def respond_to_offer(self, negotiation_id: str, action: str, counter_price: Optional[float] = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        Response to quotations (simplified version)

        Args:
            negotiation_id: Consultation ID
            Action: Actions
            parameter : Accept price or return price
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unique Response to Results
                """
        # Validate whether consultations exist
        if negotiation_id not in self.negotiations:
            return self.error_response(
                response,
                "NEGOTIATION_NOT_FOUND",
                f"协商 {negotiation_id} 不存在"
            )

        negotiation = self.negotiations[negotiation_id]

        # Execute the corresponding logic according to the action type
        try:
            if action == "offer_accept":
                # Acceptance of quotations
                negotiation["status"] = "accepted"
                negotiation["final_price"] = counter_price if counter_price is not None else negotiation["target_price"]
                negotiation["action_type"] = "respond_to_accept"

                # Send messages to each other.
                result = self.enterprise.send_message(
                    recipient_id=negotiation["speaker"],
                    message_type="Procurement",
                    content=negotiation
                )

                if result.success:
                    return self.success_response(
                        response,
                        "报价已接受",
                        {
                            "negotiation_id": negotiation_id,
                            "status": "accepted",
                            "final_price": negotiation["final_price"]
                        }
                    )
                else:
                    return self.error_response(
                        response,
                        "MESSAGE_SEND_FAILED",
                        "报价接受消息发送失败"
                    )
            elif action == "reject":
                # Rejected quotations
                negotiation["status"] = "rejected"
                return self.success_response(
                    response,
                    "报价已拒绝，协商终止",
                    {
                        "negotiation_id": negotiation_id,
                        "status": "rejected"
                    }
                )
            elif action == "counter":
                # Fight.
                if counter_price is None:
                    return self.error_response(
                        response,
                        "MISSING_COUNTER_PRICE",
                        "还价需要提供 counter_price"
                    )

                negotiation["rounds"] += 1
                return self.success_response(
                    response,
                    f"已发送还价 ¥{counter_price:.2f}（简化版，实际需要消息系统）",
                    {
                        "negotiation_id": negotiation_id,
                        "status": "countered",
                        "counter_price": counter_price,
                        "rounds": negotiation["rounds"]
                    }
                )
            elif action == "respond_to_accept":
                # Respond to the other side's acceptance.
                if counter_price and counter_price <= negotiation["max_acceptable_price"]:
                    negotiation["status"] = "accepted"
                    negotiation["final_price"] = counter_price
                    negotiation["action_type"] = "accept"
                    result = self.enterprise.send_message(
                        recipient_id=negotiation["target_enterprise_id"],
                        message_type="Procurement",
                        content=negotiation
                    )
                    if result.success:
                        self.create_purchase_order(negotiation["product_id"],negotiation["quantity"],negotiation["target_enterprise_id"],logistics_mode="air")
                        return self.success_response(
                            response,
                            "报价已接受",
                            {
                                "negotiation_id": negotiation_id,
                                "status": "accepted",
                                "final_price": counter_price
                            }
                        )
                    else:
                        return self.error_response(
                            response,
                            "MESSAGE_SEND_FAILED",
                            "报价接受消息发送失败"
                        )
                else:
                    return self.error_response(
                        response,
                        "PRICE_EXCEEDS_LIMIT",
                        "还价价格超出最大可接受范围"
                    )
            else:
                # Unknown Action Type
                return self.error_response(
                    response,
                    "INVALID_ACTION",
                    f"未知的动作类型: {action}"
                )
        except Exception as e:
            # Addressing anomalies
            return self.error_response(
                response,
                "UNKNOWN_ERROR",
                f"处理报价响应时发生异常: {e}"
            )


    @with_response("get_procurement_status")
    def get_procurement_status(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Get procurement status overview

        Args:
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified responder with procurement status information
                """
        try:
            # Statistical order status
            orders_by_status = {
                "pending": 0,
                "received": 0,
                "cancelled": 0
            }

            for order in self.purchase_orders:
                status = order["status"]
                orders_by_status[status] = orders_by_status.get(status, 0) + 1

            # Updated procurement cost rates
            if self.procurement_metrics["total_quantity"] > 0:
                self.procurement_metrics["procurement_cost_rate"] = (
                    self.procurement_metrics["total_cost"] /
                    self.procurement_metrics["total_quantity"]
                )

            # Build detailed list of suppliers
            suppliers_detail = []
            for supplier_id, supplier in self.suppliers.items():
                # Calculation of timely delivery rates
                on_time_rate = 0.0
                if supplier["total_orders"] > 0:
                    on_time_rate = supplier["on_time_deliveries"] / supplier["total_orders"]

                suppliers_detail.append({
                    "supplier_id": supplier_id,
                    "supplier_name": supplier["supplier_name"],
                    "supplier_type": supplier["supplier_type"],
                    "quality_level": supplier["quality_level"],
                    "reliability_score": supplier["reliability_score"],
                    "processing_time": supplier["processing_time"],
                    "materials_offered": list(supplier["materials"].keys()),
                    "total_orders": supplier["total_orders"],
                    "on_time_deliveries": supplier["on_time_deliveries"],
                    "on_time_rate": on_time_rate
                })

            # Build material-supplier matrix (show all available suppliers by material group)
            materials_suppliers_matrix = {}
            all_materials = set()

            # Collect all material
            for supplier in self.suppliers.values():
                all_materials.update(supplier["materials"].keys())

            # Build a list of suppliers for each material
            for material_id in all_materials:
                material_suppliers = []
                for supplier_id, supplier in self.suppliers.items():
                    if material_id in supplier["materials"]:
                        material_info = supplier["materials"][material_id]
                        material_suppliers.append({
                            "supplier_id": supplier_id,
                            "supplier_name": supplier["supplier_name"],
                            "supplier_type": supplier["supplier_type"],
                            "unit_price": material_info.get("unit_price", 0),
                            "min_order_quantity": material_info.get("min_order_quantity", 0),
                            "quality_level": supplier["quality_level"],
                            "reliability_score": supplier["reliability_score"],
                            "processing_time": supplier["processing_time"]
                        })

                # Price by price (low priority)
                material_suppliers.sort(key=lambda x: x["unit_price"])
                materials_suppliers_matrix[material_id] = material_suppliers
            supplier_candidates = self._supplier_candidate_observation()
            for candidate in supplier_candidates:
                for material_id, material_info in (candidate.get("materials") or {}).items():
                    row = {
                        "supplier_name": candidate.get("supplier_name"),
                        "supplier_type": candidate.get("supplier_type"),
                        "unit_price": material_info.get("unit_price", 0),
                        "available_quantity": material_info.get("quantity", 0),
                        "min_order_quantity": material_info.get("min_order_quantity", 0),
                        "quality_level": candidate.get("quality_level"),
                        "reliability_score": candidate.get("reliability_score"),
                        "processing_time": candidate.get("processing_time"),
                        "registration_status": candidate.get("registration_status"),
                        "logistics_options": deepcopy(candidate.get("logistics_options") or {}),
                    }
                    existing_names = {
                        item.get("supplier_name")
                        for item in materials_suppliers_matrix.setdefault(material_id, [])
                    }
                    if row["supplier_name"] not in existing_names:
                        materials_suppliers_matrix[material_id].append(row)
            grouped = defaultdict(list)
            for order in self.purchase_orders:
                status = order.get("status", "unknown")
                grouped[status].append(order)
            status_orders = dict(grouped)
            # Build Response Data
            status_data = {
                "orders": status_orders,
                "suppliers": {
                    "total": len(self.suppliers),
                    "external": len([s for s in self.suppliers.values() if s["supplier_type"] == "external"]),
                    "enterprise": len([s for s in self.suppliers.values() if s["supplier_type"] == "enterprise"]),
                    "candidate": len([
                        item for item in supplier_candidates
                        if item.get("registration_status") == "candidate"
                    ]),
                },
                "suppliers_detail": suppliers_detail,
                "supplier_candidates": supplier_candidates,
                "supplier_selection_events": list(self.supplier_selection_events),
                "materials_suppliers_matrix": materials_suppliers_matrix,
                "replenishment": {
                    "history": self.replenishment_history,
                    "upstream_order_history": self.upstream_order_history,
                    "pending_by_material": {
                        material_id: self._get_pending_quantity(material_id)
                        for material_id in self.enterprise.purchasable_materials_idList
                    }
                },
                "cash_guard": self._get_cash_guard_status(),
                "top_tier_supply_guard": self._get_top_tier_supply_guard_status(),
                "top_tier_supply_plan": self._build_top_tier_supply_plan(),
                "recipe_recovery_signal_by_material": {
                    material_id: self._get_recipe_recovery_signal(material_id)
                    for material_id in self.enterprise.purchasable_materials_idList
                },
                # "negotiations": {
                #     "total": len(self.negotiations),
                #     "active": len([n for n in self.negotiations.values() if n["status"] == "pending"])
                # },
                "procurement_metrics": self.procurement_metrics
            }

            return self.success_response(
                response,
                "成功获取采购状态总览",
                status_data
            )
        except Exception as e:
            # Deal with anomalies and record details of errors.
            import traceback
            import logging

            logger = logging.getLogger(__name__)
            error_detail = f"获取采购状态失败: {e}"
            stack_trace = traceback.format_exc()

            # Log to Log
            logger.error(f"{error_detail}\n{stack_trace}")

            # Returns error response
            return self.error_response(
                response,
                "STATUS_CALCULATION_ERROR",
                error_detail
            )

    @with_response("get_supplier_performance")
    def get_supplier_performance(self, supplier_name: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Acquisition of supplier performance

        Args:
            parameter: Name of supplier
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified target audience with supplier performance information
                """
        # Acquisition of supplier ID
        supplier_id = self._get_supplier_id_by_name(supplier_name)
        if supplier_id is None:
            return self.error_response(
                response,
                "SUPPLIER_NOT_FOUND",
                f"供应商 {supplier_name} 不存在"
            )

        supplier = self.suppliers[supplier_id]

        # Statistics of the supplier ' s order
        supplier_orders = [o for o in self.purchase_orders if o["supplier_id"] == supplier_id]
        completed_orders = [o for o in supplier_orders if o["status"] == "received"]
        on_time_orders = [o for o in completed_orders if o.get("on_time", False)]

        total_cost = sum(o["total_cost"] for o in completed_orders)
        total_quantity = sum(o["quantity"] for o in completed_orders)

        # Calculation of indicators of achievement
        on_time_rate = len(on_time_orders) / len(completed_orders) if completed_orders else 0
        avg_cost_per_unit = total_cost / total_quantity if total_quantity > 0 else 0

        # Build performance data
        performance_data = {
            "supplier_id": supplier_id,
            "supplier_name": supplier["supplier_name"],
            "total_orders": len(supplier_orders),
            "completed_orders": len(completed_orders),
            "on_time_orders": len(on_time_orders),
            "on_time_rate": on_time_rate,
            "total_cost": total_cost,
            "total_quantity": total_quantity,
            "avg_cost_per_unit": avg_cost_per_unit
        }

        return self.success_response(
            response,
            f"成功获取供应商 {supplier_name} 的绩效信息",
            performance_data
        )

    @with_response("get_state")
    def get_state(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Get Current Module Status

        Args:
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unified response object with modular status
                """
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Get procurement status overview (this method should have returned to ModeuleResponse)
            procurement_status_result = self.get_procurement_status()

            # Check parameter success
            if not procurement_status_result.success:
                logger.error(f"get_procurement_status 失败: {procurement_status_result.message}")
                logger.error(f"errors: {procurement_status_result.errors}")

                # If you fail, return basic information.
                state_data = {
                    # "module_id": self.module_id,
                    "module_type": self.module_type,
                    "error": procurement_status_result.message,
                    "error_code": procurement_status_result.errors[0].get('code') if procurement_status_result.errors else None
                }
                return self.success_response(response, "获取采购模块状态（部分失败）", state_data)

            # Ensure correct extraction of data
            if hasattr(procurement_status_result, 'data'):
                procurement_status = procurement_status_result.data if isinstance(procurement_status_result.data, dict) else {}
            elif isinstance(procurement_status_result, dict):
                procurement_status = procurement_status_result
            else:
                procurement_status = {}
                logger.warning(f"意外的 procurement_status_result 类型: {type(procurement_status_result)}")

            self._refresh_proposal_views()

            # Build Status Data
            state_data = {
                "module_id": self.module_id,
                "module_type": self.module_type,
                "supplier_name_list": self.enterprise.supplier_name_list,
                "purchasable_materials_idList": self.enterprise.purchasable_materials_idList,
                "pending_proposals_count": len(self.proposals_list),
                "proposals_list": self._serialize_proposals(),
                "proposal_history": self._serialize_proposals(self.proposal_history),
                **procurement_status
            }

            return self.success_response(
                response,
                "成功获取采购模块状态",
                state_data
            )
        except Exception as e:
            # Deal with anomalies and record detailed errors
            import traceback
            error_detail = f"获取模块状态失败: {e}"
            stack_trace = traceback.format_exc()

            logger.error(f"{error_detail}\n{stack_trace}")

            # Returns error containing basic information Response
            state_data = {
                "module_id": self.module_id,
                "module_type": self.module_type,
                "error": error_detail
            }

            return self.error_response(
                response,
                "STATE_GET_ERROR",
                error_detail,
                state_data
            )
    
    def _update_procurement_metrics(self):
        """
        Updated procurement indicators
                """
        # Recosting of procurement costs
        if self.procurement_metrics["total_quantity"] > 0:
            self.procurement_metrics["procurement_cost_rate"] = (
                self.procurement_metrics["total_cost"] /
                self.procurement_metrics["total_quantity"]
            )
        
        # Recalculate the arrival rate on time
        if self.procurement_metrics["completed_orders"] > 0:
            self.procurement_metrics["on_time_rate"] = (
                self.procurement_metrics["on_time_delivery_count"] /
                self.procurement_metrics["completed_orders"]
            )
        
        # Recalculating the success rate of consultations
        # if self.procurement_metrics["total_negotiations"] > 0:
        #     self.procurement_metrics["negotiation_success_rate"] = (
        #         self.procurement_metrics["successful_negotiations"] /
        #         self.procurement_metrics["total_negotiations"]
        #     )

    @with_response("message_handle")
    def message_handle(self, message: Dict, response: ModuleResponse = None) -> ModuleResponse:
        """
        Process messages from other modules or external systems

        Args:
            message: Dictionary with message content, at least " type" and "content" keys
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: Unique Response to Process Results
                """
        # Processing procurement-related information
        content = message.get("content")
        action_type = content.get("action_type")
        if action_type == "negotiation_initiated":
            negotiation_id = content.get("negotiation_id")
            self.negotiations[negotiation_id] = content
        elif action_type == "respond_to_accept" or action_type == "accept":
            negotiation_id = content.get("negotiation_id")
            self.respond_to_offer(negotiation_id, action_type, content.get("final_price"))

        return self.success_response(
            response,
            f"消息已处理: {message.get('content', 'No content')}",
            {}
        )
    

    def _get_supplier_id_by_name(self, supplier_name: str) -> Optional[str]:
        """Acquisition of supplier ID by name of supplier"""
        for supplier_id, supplier in self.suppliers.items():
            if supplier["supplier_name"] == supplier_name:
                return supplier_id
        return None

    def _find_order(self, order_id: str) -> Optional[Dict]:
        """Find Orders"""
        for order in self.purchase_orders:
            if order["order_id"] == order_id:
                return order
        return None

    def _log_event(self, event: Dict):
        """Record procurement incidents"""
        event["time_step"] = self.enterprise.time_manager.get_day()
        self.procurement_events.append(event)
        
    @with_response("generate_purchase_analysis")
    def generate_purchase_analysis(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Generate purchase order analysis JSON

        Args:
            Response: respond to objects, automatically injected by decorator

        Returns:
            ModuleResponse: A unified response to include an analysis of the purchase order
                """
        try:
            # Order status analysis
            orders_by_status = {}
            for order in self.purchase_orders:
                status = order.get("status", "unknown")
                if status not in orders_by_status:
                    orders_by_status[status] = []
                orders_by_status[status].append(order)

            # Vendor performance analysis
            supplier_performance = {}
            for supplier_id, supplier in self.suppliers.items():
                supplier_orders = [o for o in self.purchase_orders if o.get("supplier_id") == supplier_id]
                completed_orders = [o for o in supplier_orders if o.get("status") == "received"]
                on_time_orders = [o for o in completed_orders if o.get("on_time", False)]
                
                total_cost = sum(o.get("total_cost", 0) for o in completed_orders)
                total_quantity = sum(o.get("quantity", 0) for o in completed_orders)
                
                on_time_rate = len(on_time_orders) / len(completed_orders) if completed_orders else 0
                avg_cost_per_unit = total_cost / total_quantity if total_quantity > 0 else 0
                
                supplier_performance[supplier_id] = {
                    "supplier_name": supplier.get("supplier_name"),
                    "total_orders": len(supplier_orders),
                    "completed_orders": len(completed_orders),
                    "on_time_orders": len(on_time_orders),
                    "on_time_rate": on_time_rate,
                    "total_cost": total_cost,
                    "total_quantity": total_quantity,
                    "avg_cost_per_unit": avg_cost_per_unit
                }

            # Cost analysis
            total_cost_by_material = {}
            total_cost_by_logistics = {}
            for order in self.purchase_orders:
                material_id = order.get("material_id")
                if material_id:
                    if material_id not in total_cost_by_material:
                        total_cost_by_material[material_id] = 0
                    total_cost_by_material[material_id] += order.get("total_cost", 0)
                
                logistics_mode = order.get("logistics_mode")
                if logistics_mode:
                    if logistics_mode not in total_cost_by_logistics:
                        total_cost_by_logistics[logistics_mode] = 0
                    total_cost_by_logistics[logistics_mode] += order.get("logistics_cost", 0)

            # Analysis of time trends
            orders_by_time = {}
            for order in self.purchase_orders:
                order_time = order.get("order_time")
                if order_time:
                    if order_time not in orders_by_time:
                        orders_by_time[order_time] = []
                    orders_by_time[order_time].append(order)

            # Get Current Time
            try:
                timestamp = self.enterprise.time_manager.get_day() if hasattr(self.enterprise, 'time_manager') else 0
            except Exception:
                timestamp = 0

            # Build AnalysisJSON
            analysis_json = {
                "analysis_type": "采购订单分析",
                "timestamp": timestamp,
                "metrics": self.procurement_metrics,
                "order_analysis": {
                    "by_status": {
                        status: {
                            "count": len(orders),
                            "total_cost": sum(o.get("total_cost", 0) for o in orders),
                            "avg_cost": sum(o.get("total_cost", 0) for o in orders) / len(orders) if orders else 0
                        }
                        for status, orders in orders_by_status.items()
                    },
                    "by_time": {
                        time_step: {
                            "count": len(orders),
                            "total_cost": sum(o.get("total_cost", 0) for o in orders)
                        }
                        for time_step, orders in orders_by_time.items()
                    }
                },
                "supplier_analysis": supplier_performance,
                "cost_analysis": {
                    "by_material": total_cost_by_material,
                    "by_logistics": total_cost_by_logistics,
                    "total_purchase_cost": self.procurement_metrics.get("total_cost", 0)
                },
                "insights": [
                    f"总采购订单数: {self.procurement_metrics.get('total_orders', 0)}",
                    f"完成订单数: {self.procurement_metrics.get('completed_orders', 0)}",
                    f"准时到货率: {self.procurement_metrics.get('on_time_rate', 0):.2f}",
                    f"总采购成本: ¥{self.procurement_metrics.get('total_cost', 0):,.2f}",
                    f"采购成本率: {self.procurement_metrics.get('procurement_cost_rate', 0):.2f}"
                ]
            }

            return self.success_response(
                response,
                "成功生成采购订单分析",
                {
                    "analysis": analysis_json
                }
            )
        except Exception as e:
            return self.error_response(
                response,
                "ANALYSIS_ERROR",
                f"生成采购订单分析失败: {e}"
            )
