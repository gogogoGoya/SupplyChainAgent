from copy import deepcopy

import pytest

from config.simulation_preset_config import (
    DEFAULT_ACTIVE_SCENARIO_ID,
    MARKET_DEMAND_MODE_COBWEB,
    MARKET_DEMAND_MODE_HERDING,
    MARKET_DEMAND_MODE_SHARED_RESOURCE,
    SCENARIO_CONFIGS,
    get_scenario_config,
)


FROZEN_SCENARIO_IDS = {
    "baseline_current",
    "baseline_rebalanced",
    "beer_game",
    "beer_game_direct_distribution_experiment",
    "credit_constraint_experiment",
    "architecture_linear_chain_short",
    "architecture_branching_assembly_short",
    "architecture_mesh_multi_source_short",
    "herding_baseline_peer_visible",
    "herding_no_peer_visibility",
    "commons_mining_baseline",
    "commons_mining_collapse_baseline_uniform",
    "commons_mining_collapse_baseline_differentiated",
    "commons_mining_financial_damage_baseline",
    "commons_mining_collapse_baseline",
    "cobweb_convergent",
    "cobweb_neutral",
    "cobweb_divergent",
}

ARCHITECTURE_EDGES = {
    "architecture_linear_chain_short": {
        ("RawSupplier", "ComponentMaker"),
        ("ComponentMaker", "FinalAssembler"),
        ("FinalAssembler", "Retailer"),
    },
    "architecture_branching_assembly_short": {
        ("MaltSupplier", "BreweryAssembler"),
        ("BottleSupplier", "BreweryAssembler"),
        ("YeastSupplier", "BreweryAssembler"),
        ("BreweryAssembler", "Retailer"),
    },
    "architecture_mesh_multi_source_short": {
        ("GrainSupplier", "Brewery_A"),
        ("PackagingSupplier", "Brewery_A"),
        ("GrainSupplier", "Brewery_B"),
        ("FlavorSupplier", "Brewery_B"),
        ("Brewery_A", "DistributionHub"),
        ("Brewery_B", "DistributionHub"),
        ("DistributionHub", "Channel_A"),
        ("DistributionHub", "Channel_B"),
    },
}


def _enterprise_ids(items, field):
    return [str(item[field]) for item in items]


def test_frozen_scenario_inventory_and_default_are_preserved():
    assert FROZEN_SCENARIO_IDS <= set(SCENARIO_CONFIGS)
    assert DEFAULT_ACTIVE_SCENARIO_ID in FROZEN_SCENARIO_IDS


@pytest.mark.parametrize("scenario_id", sorted(FROZEN_SCENARIO_IDS))
def test_every_scenario_has_consistent_enterprise_and_runtime_contracts(scenario_id):
    scenario = SCENARIO_CONFIGS[scenario_id]
    required_sections = {
        "meta",
        "simulation",
        "experiment_design",
        "runtime_injection",
        "auto_policy",
        "enterprise_specs",
        "enterprise_configs",
        "agent_enterprise_layout",
        "initial_action_batches",
        "daily_actions",
    }

    assert required_sections <= set(scenario)
    assert scenario["meta"]["scenario_id"] == scenario_id
    assert scenario["meta"]["name"]
    assert scenario["meta"]["summary"]
    assert scenario["experiment_design"]["decision_regime"]
    assert scenario["experiment_design"]["experiment_group"]

    spec_ids = _enterprise_ids(scenario["enterprise_specs"], "enterprise_id")
    config_ids = _enterprise_ids(scenario["enterprise_configs"], "id")
    layout_ids = _enterprise_ids(scenario["agent_enterprise_layout"], "enterprise_id")
    assert spec_ids
    assert len(spec_ids) == len(set(spec_ids))
    assert spec_ids == config_ids == layout_ids

    simulation = scenario["simulation"]
    assert simulation["service_total_steps"] > 0
    assert simulation["agent_run_steps"] > 0
    assert simulation["max_enterprise_concurrency"] > 0
    assert simulation["max_department_concurrency"] > 0

    runtime = scenario["runtime_injection"]
    enterprise_ids = set(spec_ids)
    assert set(runtime["salary_payment_enterprise_ids"]) <= enterprise_ids
    assert set(runtime["inventory_cost_enterprise_ids"]) <= enterprise_ids
    assert "profit_objective_policy" in runtime


def test_market_modes_enable_only_their_matching_specialized_config():
    for scenario in SCENARIO_CONFIGS.values():
        simulation = scenario["simulation"]
        mode = simulation["market_demand_mode"]
        assert bool(simulation.get("cobweb_config", {}).get("enabled")) == (
            mode == MARKET_DEMAND_MODE_COBWEB
        )
        assert bool(simulation.get("shared_resource_config", {}).get("enabled")) == (
            mode == MARKET_DEMAND_MODE_SHARED_RESOURCE
        )
        assert bool(simulation.get("herding_config", {}).get("enabled")) == (
            mode == MARKET_DEMAND_MODE_HERDING
        )


@pytest.mark.parametrize("scenario_id,expected_edges", ARCHITECTURE_EDGES.items())
def test_architecture_supplier_edges_match_the_frozen_topology(
    scenario_id, expected_edges
):
    scenario = SCENARIO_CONFIGS[scenario_id]
    enterprise_ids = {
        item["id"] for item in scenario["enterprise_configs"]
    }
    actual_edges = {
        (supplier_id, item["id"])
        for item in scenario["enterprise_configs"]
        for supplier_id in item.get("supplier_name_list", [])
    }

    assert actual_edges == expected_edges
    assert all(
        supplier in enterprise_ids and customer in enterprise_ids
        for supplier, customer in actual_edges
    )


def test_scenario_config_returns_an_isolated_deep_copy():
    baseline = deepcopy(SCENARIO_CONFIGS["architecture_linear_chain_short"])
    candidate = get_scenario_config("architecture_linear_chain_short")
    candidate["meta"]["name"] = "mutated"
    candidate["enterprise_configs"][0]["enabled_functions"].append("fake_department")

    assert SCENARIO_CONFIGS["architecture_linear_chain_short"] == baseline


def test_unknown_scenario_fails_explicitly():
    with pytest.raises(KeyError, match="Unknown scenario_id"):
        get_scenario_config("architecture_linear_chain_shor")
