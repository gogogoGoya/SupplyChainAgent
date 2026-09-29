"""Deterministic external-environment events for long-horizon simulations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Tuple


class ExternalEnvironmentEvolution:
    """Apply configured cost, policy, and demand factors without compounding."""

    DEFAULT_FACTORS = {
        "external_material_price": 1.0,
        "production_conversion_cost": 1.0,
        "external_logistics_cost": 1.0,
        "external_demand_quantity": 1.0,
        "external_customer_price": 1.0,
    }

    def __init__(self, controller: Any, runtime_config: Optional[Dict[str, Any]] = None):
        self.controller = controller
        self.runtime_config = runtime_config or {}
        self._baseline_captured = False
        self._supplier_material_prices: List[Tuple[Dict[str, Any], float]] = []
        self._production_recipes: List[Tuple[Dict[str, Any], float, float]] = []
        self._baseline_demand_series: List[float] = []
        self._baseline_customer_price = 0.0
        self._baseline_logistics_multiplier = 1.0
        self._active_factors = dict(self.DEFAULT_FACTORS)
        self._applied_event_ids = set()
        self._event_history: List[Dict[str, Any]] = []

    def set_runtime_config(self, runtime_config: Optional[Dict[str, Any]]) -> None:
        self.runtime_config = runtime_config or {}

    def _policy(self) -> Dict[str, Any]:
        policy = self.runtime_config.get("external_environment_policy") or {}
        return policy if isinstance(policy, dict) else {}

    @staticmethod
    def _modules(enterprise: Any, module_type: str) -> Iterable[Any]:
        modules = (getattr(enterprise, "business_modules", {}) or {}).get(module_type) or []
        return modules if isinstance(modules, list) else [modules]

    def _capture_baseline(self) -> None:
        if self._baseline_captured:
            return
        policy = self._policy()
        targets = policy.get("targets") or {}
        material_targets = set(targets.get("external_material_enterprise_ids") or [])
        production_targets = set(targets.get("production_enterprise_ids") or [])
        material_ids = set(targets.get("material_ids") or [])

        for enterprise_id, enterprise in (getattr(self.controller, "enterprises", {}) or {}).items():
            if not material_targets or enterprise_id in material_targets:
                for module in self._modules(enterprise, "ProcurementManager"):
                    for supplier in (getattr(module, "suppliers", {}) or {}).values():
                        if str(supplier.get("supplier_type") or "") != "external":
                            continue
                        for material_id, material in (supplier.get("materials") or {}).items():
                            if material_ids and material_id not in material_ids:
                                continue
                            try:
                                price = float(material.get("unit_price") or 0.0)
                            except (TypeError, ValueError):
                                continue
                            self._supplier_material_prices.append((material, price))

            if not production_targets or enterprise_id in production_targets:
                for module in self._modules(enterprise, "ProductionManager"):
                    for recipe in (getattr(module, "product_recipes", {}) or {}).values():
                        try:
                            labor = float(recipe.get("labor_cost_per_unit") or 0.0)
                            equipment = float(recipe.get("equipment_cost_per_unit") or 0.0)
                        except (TypeError, ValueError):
                            continue
                        self._production_recipes.append((recipe, labor, equipment))

        market_manager = getattr(self.controller, "market_manager", None)
        if market_manager is not None:
            self._baseline_demand_series = [
                float(value) for value in (getattr(market_manager, "beer_game_demand_series", []) or [])
            ]
            self._baseline_customer_price = float(
                getattr(market_manager, "beer_game_unit_price", 0.0) or 0.0
            )

        top_tier_policy = self.runtime_config.get("top_tier_supply_policy") or {}
        self._baseline_logistics_multiplier = float(
            top_tier_policy.get("external_logistics_cost_multiplier", 1.0) or 1.0
        )
        self._baseline_captured = True

    @staticmethod
    def _public_event(event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in event.items()
            if key not in {"internal_notes"}
        }

    def _events_due(self, turn: int) -> List[Dict[str, Any]]:
        events = [
            event for event in (self._policy().get("events") or [])
            if isinstance(event, dict)
        ]
        return sorted(
            [event for event in events if int(event.get("turn", -1)) <= int(turn)],
            key=lambda event: int(event.get("turn", -1)),
        )

    def _update_active_factors(self, turn: int) -> List[Dict[str, Any]]:
        triggered = []
        for event in self._events_due(turn):
            event_id = str(event.get("event_id") or f"turn_{event.get('turn')}")
            if event_id in self._applied_event_ids:
                continue
            updates = event.get("factor_updates") or {}
            for key in self.DEFAULT_FACTORS:
                if key not in updates:
                    continue
                try:
                    self._active_factors[key] = max(0.0, float(updates[key]))
                except (TypeError, ValueError):
                    continue
            public_event = self._public_event(event)
            public_event["applied_turn"] = int(turn)
            self._event_history.append(public_event)
            self._applied_event_ids.add(event_id)
            triggered.append(public_event)
        return triggered

    def _apply_factors(self) -> None:
        material_factor = self._active_factors["external_material_price"]
        for material, baseline_price in self._supplier_material_prices:
            material["unit_price"] = round(baseline_price * material_factor, 6)

        conversion_factor = self._active_factors["production_conversion_cost"]
        for recipe, baseline_labor, baseline_equipment in self._production_recipes:
            recipe["labor_cost_per_unit"] = round(baseline_labor * conversion_factor, 6)
            recipe["equipment_cost_per_unit"] = round(baseline_equipment * conversion_factor, 6)

        top_tier_policy = self.runtime_config.get("top_tier_supply_policy") or {}
        top_tier_policy["external_logistics_cost_multiplier"] = round(
            self._baseline_logistics_multiplier
            * self._active_factors["external_logistics_cost"],
            6,
        )

        market_manager = getattr(self.controller, "market_manager", None)
        if market_manager is not None:
            demand_factor = self._active_factors["external_demand_quantity"]
            if self._baseline_demand_series:
                market_manager.beer_game_demand_series = [
                    round(value * demand_factor, 6)
                    for value in self._baseline_demand_series
                ]
            market_manager.beer_game_unit_price = round(
                self._baseline_customer_price
                * self._active_factors["external_customer_price"],
                6,
            )

    def _actual_values(self, turn: int) -> Dict[str, Any]:
        material_prices = sorted({
            round(float(material.get("unit_price") or 0.0), 6)
            for material, _ in self._supplier_material_prices
        })
        conversion_costs = [
            {
                "labor_cost_per_unit": recipe.get("labor_cost_per_unit"),
                "equipment_cost_per_unit": recipe.get("equipment_cost_per_unit"),
            }
            for recipe, _, _ in self._production_recipes
        ]
        market_manager = getattr(self.controller, "market_manager", None)
        demand_series = getattr(market_manager, "beer_game_demand_series", []) or []
        demand_quantity = demand_series[turn] if turn < len(demand_series) else (demand_series[-1] if demand_series else 0)
        return {
            "external_material_unit_prices": material_prices,
            "production_conversion_costs": conversion_costs,
            "external_logistics_cost_multiplier": (
                (self.runtime_config.get("top_tier_supply_policy") or {}).get(
                    "external_logistics_cost_multiplier"
                )
            ),
            "external_demand_quantity": demand_quantity,
            "external_customer_unit_price": getattr(
                market_manager, "beer_game_unit_price", None
            ),
        }

    def apply(self, turn: int) -> Dict[str, Any]:
        policy = self._policy()
        if not policy.get("enabled"):
            state: Dict[str, Any] = {"enabled": False}
            self.controller.external_environment_state = state
            return state

        self._capture_baseline()
        triggered = self._update_active_factors(turn)
        self._apply_factors()
        events = [
            self._public_event(event)
            for event in (policy.get("events") or [])
            if isinstance(event, dict)
        ]
        upcoming_turns = sorted({
            int(event.get("turn")) for event in events
            if int(event.get("turn", -1)) > int(turn)
        })
        latest_event = self._event_history[-1] if self._event_history else None
        state = {
            "schema_version": "external_environment_state.v1",
            "enabled": True,
            "scenario_family": policy.get("scenario_family") or "long_horizon_evolution",
            "current_turn": int(turn),
            "phase_index": 1 + sum(
                1 for event in events if int(event.get("turn", -1)) <= int(turn)
            ),
            "event_triggered_this_turn": bool(triggered),
            "triggered_events": triggered,
            "latest_event": latest_event,
            "recent_events": deepcopy(self._event_history[-4:]),
            "active_factors": deepcopy(self._active_factors),
            "actual_values": self._actual_values(int(turn)),
            "next_review_turn": upcoming_turns[0] if upcoming_turns else None,
            "interpretation_contract": (
                "Treat observed cost, policy, demand, and price changes as evidence. "
                "Re-evaluate margin, cash, inventory, service, procurement, and production decisions; "
                "do not chase volume or amplify stable demand without an operating reason."
            ),
        }
        self.controller.external_environment_state = state
        self.controller.external_environment_history = deepcopy(self._event_history)
        return state

