from types import SimpleNamespace

from config.simulation_preset_config import get_scenario_config
from simulate.SimulationEnvAdapter import SimulationEnvAdapter


def _case01_adapter(active_market_ids):
    recorded = []
    market_manager = SimpleNamespace(
        get_order_source_market_ids=lambda enterprise_id: list(active_market_ids),
        record_external_demand_order=lambda enterprise_id, day, order, demand_mode: (
            recorded.append((enterprise_id, day, dict(order), demand_mode))
        ),
    )
    adapter = SimulationEnvAdapter.__new__(SimulationEnvAdapter)
    adapter.sim = SimpleNamespace(
        controller=SimpleNamespace(
            enterprises={"Manufacturer": object()},
            market_manager=market_manager,
        )
    )
    adapter._cap_external_order_deadline = lambda order: order
    return adapter, recorded


def test_market_bound_schedule_reaches_sales_actions_without_field_loss():
    scenario = get_scenario_config("single_case_01_order_selection")
    runtime_config = scenario["runtime_injection"]
    adapter, recorded = _case01_adapter(["market_1"])

    workflow = []
    adapter._append_external_market_orders(workflow, runtime_config, time_day=10)

    assert len(workflow) == 1
    assert len(recorded) == 1
    action = workflow[0]["action"]
    params = action["action_param"]
    assert action["action_name"] == "create_order"
    assert workflow[0]["executor_id"] == "Manufacturer"
    assert params["product_id"] == "PRODUCT_1"
    assert params["unit_price"] > 0
    assert params["delivery_deadline"] >= 10
    assert params["offer_expiry_day"] == 11
    assert params["breach_penalty_enabled"] is True
    assert params["breach_penalty_per_unit"] == 180
    assert params["source_id"] == "market_1"
    assert params["source_type"] == "market"
    assert params["external_demand_id"].startswith(
        "Manufacturer:market_bound_fixed_demand:10:1:market_1:"
    )


def test_market_bound_schedule_requires_corresponding_active_market_slot():
    scenario = get_scenario_config("single_case_01_order_selection")
    runtime_config = scenario["runtime_injection"]

    one_market_adapter, _ = _case01_adapter(["market_1"])
    one_market_workflow = []
    one_market_adapter._append_external_market_orders(
        one_market_workflow,
        runtime_config,
        time_day=13,
    )
    assert len(one_market_workflow) == 2
    assert {
        item["action"]["action_param"]["source_id"]
        for item in one_market_workflow
    } == {"market_1"}

    two_market_adapter, _ = _case01_adapter(["market_1", "market_2"])
    two_market_workflow = []
    two_market_adapter._append_external_market_orders(
        two_market_workflow,
        runtime_config,
        time_day=13,
    )
    assert len(two_market_workflow) == 3
    assert {
        item["action"]["action_param"]["source_id"]
        for item in two_market_workflow
    } == {"market_1", "market_2"}

    no_market_adapter, _ = _case01_adapter([])
    no_market_workflow = []
    no_market_adapter._append_external_market_orders(
        no_market_workflow,
        runtime_config,
        time_day=13,
    )
    assert no_market_workflow == []


def test_market_bound_schedule_does_not_emit_outside_formal_window():
    scenario = get_scenario_config("single_case_01_order_selection")
    runtime_config = scenario["runtime_injection"]
    adapter, _ = _case01_adapter(["market_1"])

    workflow = []
    adapter._append_external_market_orders(workflow, runtime_config, time_day=9)

    assert workflow == []


def test_legacy_fixed_schedule_remains_independent_of_active_markets():
    runtime_config = {
        "external_market_order_policy": {
            "enabled": True,
            "mode": "fixed_schedule",
            "target_enterprise_ids": ["Manufacturer"],
            "start_day": 3,
            "end_day": 3,
            "orders_by_day": {
                "3": [
                    {
                        "product_id": "PRODUCT_1",
                        "quantity": 10,
                        "unit_price": 800,
                        "source_id": "legacy_external_market",
                        "source_type": "external_market",
                        "delivery_deadline": 4,
                    }
                ]
            },
        }
    }
    recorded = []
    adapter = SimulationEnvAdapter.__new__(SimulationEnvAdapter)
    adapter.sim = SimpleNamespace(
        controller=SimpleNamespace(
            enterprises={"Manufacturer": object()},
            market_manager=SimpleNamespace(
                record_external_demand_order=(
                    lambda enterprise_id, day, order, demand_mode: recorded.append(
                        (enterprise_id, day, dict(order), demand_mode)
                    )
                )
            ),
        )
    )
    adapter._cap_external_order_deadline = lambda order: order

    workflow = []
    adapter._append_external_market_orders(workflow, runtime_config, time_day=3)

    assert len(workflow) == 1
    assert recorded[0][3] == "fixed_schedule"
    assert workflow[0]["action"]["action_param"]["source_id"] == (
        "legacy_external_market"
    )


def test_market_bound_order_mode_is_isolated_to_single_case01():
    for scenario_id in (
        "single_case_02_material_shortage",
        "single_case_03_capacity_bottleneck",
        "single_case_04_staff_shortage",
        "single_case_05_cash_pressure",
    ):
        for candidate in (scenario_id, f"{scenario_id}_scripted"):
            policy = get_scenario_config(candidate)["runtime_injection"][
                "external_market_order_policy"
            ]
            assert policy["mode"] != "market_bound_fixed_schedule"
