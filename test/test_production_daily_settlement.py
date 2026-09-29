from core.async_time_manager import AsyncTimeManager
from enterprise.enterprise import Enterprise


def _module(enterprise, module_type):
    return enterprise.business_modules[module_type][0]


def test_multi_day_production_plan_settles_once_per_day_until_complete():
    enterprise = Enterprise(
        {
            "enabled_functions": ["finance", "hr", "inventory", "production", "sales"],
            "initial_capital": 1_000_000,
        },
        id="Manufacturer",
    )
    time_manager = AsyncTimeManager()
    enterprise.set_time_manager(time_manager)
    enterprise.initialize_default_modules()

    hr = _module(enterprise, "HRManager")
    inventory = _module(enterprise, "InventoryManager")
    production = _module(enterprise, "ProductionManager")

    assert hr.initialize_staffing({"production": 6}).success
    assert inventory.set_capacity(10_000).success
    assert inventory.add_inventory("MATERIAL_1", 1000, 10, "raw_material").success
    assert production.initialize_production_line("small", ready_at_start=True).success
    assert production.set_product_recipe(
        "PRODUCT_1",
        {"MATERIAL_1": 2.0},
        production_time=1,
        labor_cost_per_unit=10,
        equipment_cost_per_unit=5,
    ).success

    created = production.create_production_plan(
        "PRODUCT_1",
        quantity=500,
        daily_capacity=250,
    )
    assert created.success

    time_manager.fast_forward_to_next_workday_start()
    day1 = production.check_completed_plans()
    assert day1.success
    assert day1.data["total_produced_today"] == 250
    assert inventory.inventory["MATERIAL_1"]["quantity"] == 500
    assert inventory.inventory["PRODUCT_1"]["quantity"] == 250

    time_manager.fast_forward_to_next_workday_start()
    day2 = production.check_completed_plans()
    assert day2.success
    assert day2.data["total_produced_today"] == 250
    assert inventory.inventory["MATERIAL_1"]["quantity"] == 0
    assert inventory.inventory["PRODUCT_1"]["quantity"] == 500
    assert production.production_plans[0]["status"] == "completed"
    assert production.production_plans[0]["progress"]["last_progress_day"] == 2


def test_cobweb_c1_internal_override_keeps_physical_checks_but_relaxes_missing_price_guard():
    enterprise = Enterprise(
        {
            "enabled_functions": ["finance", "hr", "inventory", "production", "sales"],
            "initial_capital": 1_000_000,
        },
        id="Manufacturer",
    )
    time_manager = AsyncTimeManager()
    enterprise.set_time_manager(time_manager)
    enterprise.initialize_default_modules()

    hr = _module(enterprise, "HRManager")
    inventory = _module(enterprise, "InventoryManager")
    production = _module(enterprise, "ProductionManager")

    assert hr.initialize_staffing({"production": 2}).success
    assert inventory.set_capacity(10_000).success
    assert inventory.add_inventory("Malt", 1000, 0.4, "raw_material").success
    assert production.initialize_production_line("small", ready_at_start=True).success
    assert production.set_product_recipe(
        "beer",
        {"Malt": 2.0},
        production_time=1,
        labor_cost_per_unit=0.1,
        equipment_cost_per_unit=0.05,
    ).success
    production._estimate_expected_sale_floor = lambda _product_id: {
        "expected_sale_unit_price": 0.0,
        "reference_price": 0.0,
        "landed_unit_cost": 0.0,
        "pricing_strategy": "test_missing_price_signal",
    }

    blocked = production.create_production_plan(
        "beer",
        quantity=50,
        daily_capacity=50,
    )
    assert blocked.success is False
    assert blocked.errors[0]["code"] == "MARGIN_GUARD_BLOCKED"

    created = production.create_production_plan(
        "beer",
        quantity=50,
        daily_capacity=50,
        _cobweb_scripted_formula_override=True,
    )
    assert created.success is True
    assert (
        created.data["margin_guard"]["enforcement"]
        == "diagnostic_only_for_cobweb_c1_scripted_formula"
    )
