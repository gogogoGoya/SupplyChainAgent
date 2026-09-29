import json
from types import SimpleNamespace

import pytest

import ccAgent.CCSDKAgent.multi_tenant_utils as multi_tenant_utils_module
from ccAgent.CCSDKAgent.policy_context import build_department_policy_context
from ccAgent.CCSDKAgent.EnterpriseRuntime import EnterpriseRuntime
from ccAgent.CCSDKAgent.skill_runner import SkillRunner
from ccAgent.CCSDKAgent.multi_tenant_utils import (
    Config as MultiTenantConfig,
    MultiTenantUtils,
)
from config.simulation_preset_config import get_scenario_config
from persistence.experiment_metric_contract import build_experiment_metric_contract
from persistence.run_metrics_projection import RunMetricsProjectionBuilder
from runtime.operations.facade import _validate_long_horizon_evolution_contract
from simulate.external_environment import ExternalEnvironmentEvolution


def test_long_horizon_scenario_is_independent_stable_200_turn_design():
    scenario = get_scenario_config("long_horizon_evolution")
    simulation = scenario["simulation"]
    runtime = scenario["runtime_injection"]
    design = scenario["experiment_design"]

    assert simulation["agent_run_steps"] == 200
    assert simulation["service_total_steps"] == 200
    assert len(simulation["beer_game_demand_series"]) == 200
    assert max(simulation["beer_game_demand_series"]) / min(
        simulation["beer_game_demand_series"]
    ) < 1.10
    assert design["experiment_group"] == "E1"
    assert design["decision_regime"] == "adaptive_long_horizon_agent"
    assert [event["turn"] for event in runtime["external_environment_policy"]["events"]] == [
        40,
        80,
        120,
        160,
    ]
    assert runtime["bullwhip_midstream_pass_through_mode"]["enabled"] is False
    assert runtime["bullwhip_proposal_conversion_acceleration"]["enabled"] is False
    assert runtime["bullwhip_manufacturer_upstream_amplification"]["enabled"] is False
    assert runtime["bullwhip_supplier_upstream_pull_through_mode"]["enabled"] is False
    assert runtime["long_run_experiment_policy"]["history_days"] == 12
    assert runtime["long_run_experiment_policy"]["event_follow_up_offsets"] == [
        0,
        2,
        5,
    ]
    assert runtime["long_run_experiment_policy"]["agent_context_compaction"] == {
        "enabled": True,
        "recent_history_items": 4,
        "max_open_records": 48,
        "preserve_full_state_for_archive": True,
    }
    assert runtime["analyst_policy"]["full_analysis_interval_rounds"] == 5
    assert simulation["beer_game_unit_price"] == 520
    assert runtime["long_horizon_profitability_policy"]["enabled"] is True
    assert runtime["long_run_experiment_policy"]["agent_timeout_policy"][
        "department_first_attempt_seconds"
    ] == 150
    assert runtime["long_run_experiment_policy"]["state_driven_fallback_policy"][
        "enabled"
    ] is True
    assert runtime["long_run_experiment_policy"]["agent_timeout_circuit_breaker"] == {
        "enabled": True,
        "consecutive_all_timeout_rounds": 2,
        "include_trade_phase": True,
        "include_analyst_phase": True,
        "minimum_expected_agent_calls": 8,
        "pause_after_complete_round": True,
    }
    assert runtime["long_run_experiment_policy"]["execution_guard"][
        "cap_manual_purchase_demand"
    ] is True
    assert runtime["long_run_experiment_policy"]["artifact_retention_policy"] == {
        "retain_end_of_day_state": True,
        "retain_intermediate_observer_state": False,
        "retain_intermediate_exchange_state": False,
        "deduplicate_end_of_day_exchange_alias": True,
        "retain_department_actions_and_results": True,
        "retain_raw_observations": True,
    }
    assert runtime["top_tier_supply_policy"]["external_logistics_cost_multiplier"] == 0.08
    assert runtime["long_horizon_profitability_policy"][
        "b2b_max_price_floor_by_role_tag"
    ] == {
        "finished_goods_manufacturer": 1.42,
        "intermediate_distributor": 1.38,
        "retail_market_node": 1.32,
    }
    assert runtime["long_horizon_cost_policy"] == {
        "enabled": True,
        "target_enterprise_ids": ["Supplier", "Manufacturer", "Distributor", "Retailer"],
        "salary_cost_multiplier": 0.85,
        "inventory_maintenance_cost_multiplier": 0.50,
        "warehouse_operating_cost_multiplier": 0.50,
        "warehouse_expansion_cost_multiplier": 0.65,
    }

    enterprise_ids = [item["enterprise_id"] for item in scenario["enterprise_specs"]]
    assert enterprise_ids == ["Supplier", "Manufacturer", "Distributor", "Retailer"]
    specs = {item["enterprise_id"]: item for item in scenario["enterprise_specs"]}
    assert specs["Supplier"]["initial_capacity"] == 50_000
    assert specs["Manufacturer"]["initial_capacity"] == 30_000
    assert specs["Distributor"]["initial_capacity"] == 1_500
    assert specs["Retailer"]["initial_capacity"] == 1_200
    assert specs["Manufacturer"]["production_recipe"]["labor_cost_per_unit"] == 3.5
    assert specs["Manufacturer"]["production_recipe"]["equipment_cost_per_unit"] == 1.5
    supplier_inventory_prices = {
        item["item_id"]: item["purchase_price"]
        for item in specs["Supplier"]["initial_inventory"]
    }
    supplier_catalog_prices = {
        item_id: item["unit_price"]
        for item_id, item in specs["Supplier"]["initial_suppliers"][0]["materials"].items()
    }
    assert supplier_inventory_prices == {"Malt": 0.24, "Hops": 1.45, "Yeast": 2.0}
    assert supplier_catalog_prices == supplier_inventory_prices


def test_long_horizon_metric_contract_uses_evolution_family_and_gates():
    scenario = get_scenario_config("long_horizon_evolution")
    contract = build_experiment_metric_contract(
        scenario_id="long_horizon_evolution",
        experiment_design=scenario["experiment_design"],
    )

    assert contract["family"] == "long_horizon_evolution"
    assert contract["experiment_group"] == "E1"
    assert "event_detection_latency_turns" in contract["primary_metrics"]
    assert contract["group_specific_gates"] == [
        "external_environment_policy_enabled",
        "long_run_policy_enabled",
        "future_event_content_hidden",
    ]


def test_e1_exchange_root_alias_reuses_end_of_day_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(multi_tenant_utils_module, "WORKSPACE", tmp_path)
    source = tmp_path / "public" / "exchange" / "day7" / "end_of_day" / "exchange.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"round": 7}', encoding="utf-8")

    MultiTenantUtils.materialize_exchange_root_alias(7)

    alias = tmp_path / "public" / "exchange" / "day7" / "exchange.json"
    assert alias.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert alias.stat().st_ino == source.stat().st_ino


def test_operations_launch_contract_rejects_e1_drift():
    scenario = get_scenario_config("long_horizon_evolution")
    _validate_long_horizon_evolution_contract(scenario, planned_total_steps=200)

    drifted = get_scenario_config("long_horizon_evolution")
    drifted["simulation"]["agent_run_steps"] = 40
    drifted["runtime_injection"]["scripted_rule_policy"]["enabled"] = True
    with pytest.raises(ValueError, match="agent_run_steps must be 200"):
        _validate_long_horizon_evolution_contract(
            drifted,
            planned_total_steps=40,
        )

    missing_compaction = get_scenario_config("long_horizon_evolution")
    missing_compaction["runtime_injection"]["long_run_experiment_policy"][
        "agent_context_compaction"
    ]["enabled"] = False
    with pytest.raises(ValueError, match="agent_context_compaction.enabled must be true"):
        _validate_long_horizon_evolution_contract(
            missing_compaction,
            planned_total_steps=200,
        )

    missing_cost_policy = get_scenario_config("long_horizon_evolution")
    missing_cost_policy["runtime_injection"]["long_horizon_cost_policy"][
        "enabled"
    ] = False
    with pytest.raises(ValueError, match="long_horizon_cost_policy.enabled must be true"):
        _validate_long_horizon_evolution_contract(
            missing_cost_policy,
            planned_total_steps=200,
        )


def test_long_run_agent_projection_bounds_history_but_keeps_current_actions():
    received_orders = [
        {"order_id": f"PO_{index}", "quantity": index}
        for index in range(80)
    ]
    replenishment_history = [
        {"round_id": index, "material_id": "MATERIAL_1", "quantity": index}
        for index in range(100)
    ]
    procurement_payload = {
        "department": "procurement",
        "round_id": 91,
        "agent_decision_brief": {"decision_scope": "procurement"},
        "policy_context": {"active_modes": {"long_run_experiment": True}},
        "simulation_context": {
            "total_steps": 200,
            "external_environment": {"current_turn": 91},
            "shared_resource_config": {"unused": "x" * 1000},
        },
        "self_state": {
            "purchasable_materials_idList": ["Malt"],
            "supplier_candidates": [{"supplier_name": "Supplier_A"}],
            "materials_suppliers_matrix": {
                "Malt": [{"supplier_name": "Supplier_A"}],
                "MATERIAL_1": [{"supplier_name": "Stale_S0_Supplier"}],
            },
            "orders": {
                "pending": [{"order_id": "OPEN_PO", "quantity": 10}],
                "received": received_orders,
            },
            "replenishment": {
                "pending_by_material": {"MATERIAL_1": 10},
                "history": replenishment_history,
            },
        },
    }
    projection = SkillRunner._build_long_run_department_context_projection(
        procurement_payload,
        "procurement",
        91,
        {"recent_history_items": 4, "max_open_records": 48},
    )
    state = projection["self_state"]

    assert state["orders"]["pending"][0]["order_id"] == "OPEN_PO"
    assert list(state["materials_suppliers_matrix"]) == ["Malt"]
    assert state["orders"]["history_summary"]["received"] == 80
    assert len(state["orders"]["recent_received"]) == 4
    assert state["replenishment"]["pending_by_material"]["MATERIAL_1"] == 10
    assert state["replenishment"]["history_summary"]["history"] == 100
    assert len(state["replenishment"]["recent_history"]) == 4
    assert "shared_resource_config" not in projection["simulation_context"]
    assert len(procurement_payload["self_state"]["orders"]["received"]) == 80


def test_long_run_sales_projection_removes_expired_available_orders_only():
    payload = {
        "department": "sales",
        "round_id": 91,
        "agent_decision_brief": {"decision_scope": "sales"},
        "policy_context": {},
        "simulation_context": {},
        "self_state": {
            "sales_orders": {
                "available": [
                    {"order_id": "CURRENT", "offer_expiry_day": 92},
                    {"order_id": "EXPIRED", "offer_expiry_day": 90},
                ],
                "completed": [
                    {"order_id": f"DONE_{index}"}
                    for index in range(30)
                ],
            },
            "demand_backlog": {
                "by_product": {"beer": 5},
                "received_demand_history": list(range(50)),
            },
            "proposals_list": [{"proposal_id": "P1"}],
        },
    }
    projection = SkillRunner._build_long_run_department_context_projection(
        payload,
        "sales",
        91,
        {"recent_history_items": 4, "max_open_records": 48},
    )
    state = projection["self_state"]

    assert [item["order_id"] for item in state["sales_orders"]["available"]] == [
        "CURRENT"
    ]
    assert state["sales_orders"]["filtered_non_actionable_summary"]["available"] == 1
    assert state["sales_orders"]["history_summary"]["completed"] == 30
    assert len(state["sales_orders"]["recent_completed"]) == 4
    assert state["demand_backlog"]["by_product"] == {"beer": 5}
    assert state["demand_backlog"]["history_summary"][
        "received_demand_history"
    ] == 50


def _fake_controller_and_runtime():
    supplier_materials = {
        "Malt": {"unit_price": 2.0},
        "Hops": {"unit_price": 4.0},
        "Yeast": {"unit_price": 6.0},
    }
    supplier_module = SimpleNamespace(
        suppliers={
            "External": {
                "supplier_type": "external",
                "materials": supplier_materials,
            }
        }
    )
    manufacturer_module = SimpleNamespace(
        product_recipes={
            "beer": {
                "labor_cost_per_unit": 5.0,
                "equipment_cost_per_unit": 3.0,
            }
        }
    )
    controller = SimpleNamespace(
        enterprises={
            "Supplier": SimpleNamespace(
                business_modules={"ProcurementManager": [supplier_module]}
            ),
            "Manufacturer": SimpleNamespace(
                business_modules={"ProductionManager": [manufacturer_module]}
            ),
        },
        market_manager=SimpleNamespace(
            beer_game_demand_series=[100.0] * 200,
            beer_game_unit_price=300.0,
        ),
    )
    scenario = get_scenario_config("long_horizon_evolution")
    runtime = scenario["runtime_injection"]
    return controller, runtime, supplier_materials, manufacturer_module.product_recipes["beer"]


def test_external_environment_events_apply_absolute_factors_idempotently():
    controller, runtime, materials, recipe = _fake_controller_and_runtime()
    logistics_baseline = runtime["top_tier_supply_policy"][
        "external_logistics_cost_multiplier"
    ]
    evolution = ExternalEnvironmentEvolution(controller, runtime)

    baseline = evolution.apply(0)
    assert baseline["active_factors"]["external_material_price"] == 1.0
    assert materials["Malt"]["unit_price"] == 2.0

    turn_40 = evolution.apply(40)
    evolution.apply(40)
    assert materials["Malt"]["unit_price"] == 2.5
    assert len(turn_40["triggered_events"]) == 1
    assert len(controller.external_environment_history) == 1

    evolution.apply(80)
    evolution.apply(80)
    assert recipe["labor_cost_per_unit"] == 9.0
    assert recipe["equipment_cost_per_unit"] == 5.4

    evolution.apply(120)
    evolution.apply(120)
    assert runtime["top_tier_supply_policy"]["external_logistics_cost_multiplier"] == pytest.approx(
        logistics_baseline * 2.4
    )

    final_state = evolution.apply(160)
    evolution.apply(160)
    assert materials["Malt"]["unit_price"] == pytest.approx(2.2)
    assert recipe["labor_cost_per_unit"] == pytest.approx(5.6)
    assert runtime["top_tier_supply_policy"]["external_logistics_cost_multiplier"] == pytest.approx(
        logistics_baseline * 1.55
    )
    assert controller.market_manager.beer_game_demand_series[160] == pytest.approx(86.0)
    assert controller.market_manager.beer_game_unit_price == pytest.approx(288.0)
    assert len(controller.external_environment_history) == 4
    assert final_state["next_review_turn"] is None


def test_agent_policy_context_hides_future_event_schedule():
    scenario = get_scenario_config("long_horizon_evolution")
    runtime = scenario["runtime_injection"]
    current_state = {
        "enabled": True,
        "current_turn": 40,
        "event_triggered_this_turn": True,
        "latest_event": {
            "event_id": "upstream_material_price_surge",
            "turn": 40,
            "label": "上游原料价格上涨",
        },
        "recent_events": [
            {
                "event_id": "upstream_material_price_surge",
                "turn": 40,
                "label": "上游原料价格上涨",
            }
        ],
        "active_factors": {"external_material_price": 1.25},
        "actual_values": {"external_material_unit_prices": [0.375, 2.25, 3.125]},
        "next_review_turn": 80,
    }
    context = build_department_policy_context(
        dept="procurement",
        round_id=40,
        enterprise_id="Supplier",
        enterprise_spec={
            "role_tags": ["top_tier_supplier"],
            "policy_tags": ["external_procurement_enabled"],
            "enabled_functions": ["procurement"],
        },
        agent_simulation_context={
            "market_demand_mode": "scheduled_external",
            "trade_mode": "scheduled_external",
            "external_environment": current_state,
        },
        runtime_injection_config=runtime,
        scenario_id="long_horizon_evolution",
    )
    serialized = json.dumps(context, ensure_ascii=False)

    assert context["active_modes"]["external_environment_evolution"] is True
    assert "upstream_material_price_surge" in serialized
    assert "manufacturing_conversion_cost_surge" not in serialized
    assert "import_trade_logistics_tightening" not in serialized
    assert "events" not in context["relevant_policies"]["external_environment_policy"]["params"]


def test_resilient_multi_enterprise_run_can_generate_auditable_fallback_analysis(
    monkeypatch,
    tmp_path,
):
    workspace = tmp_path / "workspace_multi"
    enterprise_dir = workspace / "enterprises" / "Supplier"
    observations = enterprise_dir / "observations"
    observations.mkdir(parents=True)
    (workspace / "run_meta.json").write_text(
        json.dumps({
            "orchestrator": "multi_enterprise",
            "scenario_config": {
                "runtime_injection": {
                    "long_run_experiment_policy": {
                        "enabled": True,
                        "continue_on_agent_failure": True,
                    }
                }
            },
        }),
        encoding="utf-8",
    )
    (observations / "observation_day0.txt").write_text(
        json.dumps({
            "finance": {"cash": 1_000_000},
            "sales": {"sales_orders": {"available": [], "accepted": [], "backlog": []}},
            "procurement": {},
            "production": {},
            "hr": {},
            "inventory": {"inventory_items": []},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(MultiTenantConfig, "ENTERPRISE_DIR", workspace / "enterprises")
    monkeypatch.setattr(
        "ccAgent.CCSDKAgent.multi_tenant_utils.WORKSPACE",
        workspace,
    )

    assert MultiTenantUtils._write_fallback_enterprise_analysis("Supplier", 0) is True
    payload = json.loads((enterprise_dir / "analysis.json").read_text(encoding="utf-8"))
    assert payload["round_id"] == 0
    assert payload["fallback_analysis"]["enabled"] is True


def test_enterprise_runtime_reads_analyst_schedule_from_run_snapshot(tmp_path):
    workspace = tmp_path / "workspace_multi"
    workspace.mkdir()
    (workspace / "run_meta.json").write_text(
        json.dumps({
            "scenario_config": {
                "runtime_injection": {
                    "analyst_policy": {
                        "full_analysis_interval_rounds": 5,
                        "force_on_rounds": [0, 40, 80, 120, 160],
                    }
                }
            }
        }),
        encoding="utf-8",
    )
    runtime = EnterpriseRuntime.__new__(EnterpriseRuntime)
    runtime.workspace_dir = workspace

    assert runtime._get_analyst_policy()["force_on_rounds"] == [0, 40, 80, 120, 160]
    assert runtime._should_run_analyst(40) is True
    assert runtime._should_run_analyst(41) is False


def test_long_horizon_event_follow_up_forces_analyst_review(tmp_path):
    workspace = tmp_path / "workspace_multi"
    workspace.mkdir()
    (workspace / "run_meta.json").write_text(
        json.dumps({
            "scenario_config": {
                "runtime_injection": {
                    "analyst_policy": {
                        "full_analysis_interval_rounds": 5,
                        "force_on_rounds": [0, 40, 80, 120, 160],
                    },
                    "long_run_experiment_policy": {
                        "enabled": True,
                        "event_turns": [40, 80, 120, 160],
                        "event_follow_up_offsets": [0, 2, 5],
                    },
                }
            }
        }),
        encoding="utf-8",
    )
    runtime = EnterpriseRuntime.__new__(EnterpriseRuntime)
    runtime.workspace_dir = workspace

    assert runtime._should_run_analyst(42) is True
    assert runtime._should_run_analyst(43) is False
    assert runtime._should_run_analyst(45) is True


def test_long_horizon_external_change_review_compares_previous_turn(tmp_path):
    runner = SkillRunner.__new__(SkillRunner)
    runner.workspace_dir = tmp_path
    previous_dir = tmp_path / "public" / "exchange" / "day39" / "end_of_day"
    previous_dir.mkdir(parents=True)
    (previous_dir / "external_environment.json").write_text(
        json.dumps({
            "active_factors": {
                "external_material_price": 1.0,
                "production_conversion_cost": 1.0,
            }
        }),
        encoding="utf-8",
    )
    review = runner._build_long_run_external_change_review(
        {
            "external_environment": {
                "enabled": True,
                "event_triggered_this_turn": True,
                "active_factors": {
                    "external_material_price": 1.25,
                    "production_conversion_cost": 1.0,
                },
                "latest_event": {
                    "event_id": "upstream_material_price_surge",
                    "turn": 40,
                },
            }
        },
        40,
    )

    factor = review["factor_comparison"]["external_material_price"]
    assert review["review_status"] == "event_triggered_now"
    assert factor["previous_turn"] == 1.0
    assert factor["current_turn"] == 1.25
    assert factor["changed_this_turn"] is True
    assert review["active_deviating_factors"] == ["external_material_price"]


def test_run_metrics_projection_carries_external_environment_state(tmp_path):
    scenario = get_scenario_config("long_horizon_evolution")
    (tmp_path / "run_meta.json").write_text(
        json.dumps({
            "run_id": "run-e1-test",
            "status": "running",
            "scenario_id": "long_horizon_evolution",
            "scenario_config": scenario,
            "experiment_design": scenario["experiment_design"],
            "enterprise_ids": [],
        }),
        encoding="utf-8",
    )
    exchange_dir = tmp_path / "public" / "exchange" / "day40" / "end_of_day"
    exchange_dir.mkdir(parents=True)
    (exchange_dir / "external_environment.json").write_text(
        json.dumps({
            "enabled": True,
            "current_turn": 40,
            "latest_event": {"event_id": "upstream_material_price_surge"},
        }),
        encoding="utf-8",
    )

    projection = RunMetricsProjectionBuilder().build(
        workspace_dir=tmp_path,
        round_id=40,
    )

    assert projection["external_environment"]["current_turn"] == 40
    assert projection["external_environment"]["latest_event"]["event_id"] == (
        "upstream_material_price_surge"
    )


def test_run_metrics_projection_exposes_event_detection_and_actions(tmp_path):
    scenario = get_scenario_config("long_horizon_evolution")
    (tmp_path / "run_meta.json").write_text(
        json.dumps({
            "run_id": "run-e1-observable",
            "status": "running",
            "scenario_id": "long_horizon_evolution",
            "scenario_config": scenario,
            "experiment_design": scenario["experiment_design"],
            "enterprise_ids": ["Supplier"],
        }),
        encoding="utf-8",
    )
    exchange_dir = tmp_path / "public" / "exchange" / "day40" / "end_of_day"
    exchange_dir.mkdir(parents=True)
    (exchange_dir / "external_environment.json").write_text(
        json.dumps({
            "enabled": True,
            "current_turn": 40,
            "event_triggered_this_turn": True,
            "latest_event": {
                "event_id": "upstream_material_price_surge",
                "turn": 40,
            },
        }),
        encoding="utf-8",
    )
    analysis_dir = tmp_path / "enterprises" / "Supplier" / "records" / "day40"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "analysis.json").write_text(
        json.dumps({
            "external_environment_response": {
                "observed_event_ids": ["upstream_material_price_surge"],
                "active_factor_assessment": {},
                "impact_assessment": "成本影响",
                "response_strategy": "条件式采购",
                "review_criteria": "现金与单位成本",
            }
        }),
        encoding="utf-8",
    )
    action_dir = (
        tmp_path
        / "enterprises"
        / "Supplier"
        / "department"
        / "procurement"
        / "day40"
    )
    action_dir.mkdir(parents=True)
    (action_dir / "procurement_action.json").write_text(
        json.dumps([{
            "action": {
                "action_name": "create_purchase_order",
                "action_param": {"quantity": 1250},
            }
        }]),
        encoding="utf-8",
    )

    projection = RunMetricsProjectionBuilder().build(
        workspace_dir=tmp_path,
        round_id=40,
    )
    observable = projection["external_response_observability"]

    assert observable["event_detection"]["upstream_material_price_surge"][
        "detection_latency_by_enterprise"
    ]["Supplier"] == 0
    assert observable["round_actions"]["by_enterprise"]["Supplier"][
        "action_quantities"
    ]["create_purchase_order"] == 1250
