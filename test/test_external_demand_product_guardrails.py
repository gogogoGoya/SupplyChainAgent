from core.market_manager import MarketManager
from config.simulation_preset_config import get_default_simulation_config, get_scenario_config


class _ModuleState:
    def __init__(self, data):
        self.data = data


class _SalesModule:
    def __init__(self, salable_products):
        self.salable_products = salable_products

    def get_state(self):
        return _ModuleState({"salable_products_idList": self.salable_products})


class _ProductionModule:
    def __init__(self, production_plans=None):
        self.production_plans = list(production_plans or [])


class _Enterprise:
    def __init__(self, enterprise_id, salable_products, production_plans=None):
        self.id = enterprise_id
        self.production_module = _ProductionModule(production_plans)
        self.business_modules = {
            "SalesManager": [_SalesModule(salable_products)],
            "ProductionManager": [self.production_module],
        }


def test_scheduled_external_demand_product_falls_back_to_target_salable_product():
    enterprises = {"Retailer": _Enterprise("Retailer", ["beer"])}
    manager = MarketManager(
        lambda enterprise_id: enterprises.get(enterprise_id),
        demand_mode="scheduled_external_demand",
        beer_game_demand_series=[40],
        beer_game_unit_price=280,
        beer_game_product_id="smart_device",
    )

    orders = manager.generate_external_orders("Retailer", current_day=0)

    assert orders[0]["product_id"] == "beer"
    assert orders[0]["external_demand_id"] == "Retailer:scheduled_external_demand:0:beer"
    assert manager.get_external_demand_history("Retailer")[0]["product_id"] == "beer"
    assert manager.get_config()["beer_game_product_id"] == "beer"


def test_scheduled_external_demand_keeps_configured_product_when_salable():
    enterprises = {"Retailer": _Enterprise("Retailer", ["smart_device"])}
    manager = MarketManager(
        lambda enterprise_id: enterprises.get(enterprise_id),
        demand_mode="scheduled_external_demand",
        beer_game_demand_series=[40],
        beer_game_unit_price=280,
        beer_game_product_id="smart_device",
    )

    orders = manager.generate_external_orders("Retailer", current_day=0)

    assert orders[0]["product_id"] == "smart_device"
    assert manager.get_external_demand_history("Retailer")[0]["product_id"] == "smart_device"


def test_default_simulation_config_includes_beer_game_product_id():
    config = get_default_simulation_config(total_steps=3)

    assert config["environment_config"]["beer_game_product_id"]


def test_cobweb_scripted_formula_uses_lagged_scripted_plan_after_cold_start():
    scenario = get_scenario_config("cobweb_divergent_scripted")
    enterprise = _Enterprise("Manufacturer", ["beer"])
    manager = MarketManager(
        lambda enterprise_id: enterprise if enterprise_id == "Manufacturer" else None,
        total_steps=40,
        demand_mode="cobweb",
        cobweb_config=scenario["simulation"]["cobweb_config"],
    )

    manager.generate_external_orders("Manufacturer", current_day=0)
    cold_start = manager.cobweb_history[-1]
    assert cold_start["market_supply_quantity"] == 188.0
    assert cold_start["market_supply_source"] == "no_lagged_scripted_supply"

    enterprise.production_module.production_plans.append({
        "plan_id": "scripted-plan-day0",
        "product_id": "beer",
        "created_time": 0,
        "quantity": 44.0,
    })
    manager.generate_external_orders("Manufacturer", current_day=1)
    next_round = manager.cobweb_history[-1]

    assert next_round["market_supply_quantity"] == 44.0
    assert next_round["actual_supply_quantity"] == 44.0
    assert next_round["market_supply_source"] == "scripted_production_plan_created"
    assert next_round["unit_price"] == 504.0


def test_cobweb_agent_missing_plan_only_uses_theoretical_supply_for_cold_start():
    scenario = get_scenario_config("cobweb_divergent")
    enterprise = _Enterprise("Manufacturer", ["beer"])
    manager = MarketManager(
        lambda enterprise_id: enterprise if enterprise_id == "Manufacturer" else None,
        total_steps=40,
        demand_mode="cobweb",
        cobweb_config=scenario["simulation"]["cobweb_config"],
    )

    manager.generate_external_orders("Manufacturer", current_day=0)
    cold_start = manager.cobweb_history[-1]
    assert cold_start["market_supply_quantity"] == 188.0
    assert cold_start["market_supply_source"] == "no_lagged_agent_supply"
    assert cold_start["market_supply_source_detail"]["effective_fallback"] == (
        "theoretical_lagged_supply"
    )

    manager.generate_external_orders("Manufacturer", current_day=1)
    missing_plan = manager.cobweb_history[-1]
    assert missing_plan["market_supply_quantity"] == 1.0
    assert missing_plan["market_supply_source"] == "no_agent_supply_for_round"
    assert missing_plan["market_supply_source_detail"]["effective_fallback"] == "quantity_floor"
