import pytest

from config.simulation_preset_config import SCENARIO_CONFIGS
from network.exchange_manager import Exchange


ARCHITECTURE_SCENARIOS = [
    "architecture_linear_chain_short",
    "architecture_branching_assembly_short",
    "architecture_mesh_multi_source_short",
]


def _register_route(exchange, seller, buyer):
    exchange.register_upstream_enterprise(
        seller["id"],
        seller["name"],
        {
            "salable_products_idList": seller["salable_products_idList"],
            "purchasable_materials_idList": seller["purchasable_materials_idList"],
        },
    )
    exchange.register_downstream_enterprise(
        buyer["id"],
        buyer["name"],
        {
            "salable_products_idList": buyer["salable_products_idList"],
            "purchasable_materials_idList": buyer["purchasable_materials_idList"],
        },
    )


def _complete_explicit_order(exchange, seller, buyer, product_id, quantity=5):
    buy_request = exchange.submit_buy_request(
        buyer_company_id=buyer["id"],
        product_id=product_id,
        quantity=quantity,
        created_round=0,
        max_price=120,
        expected_due_round=1,
    )
    sell_request = exchange.submit_sell_request(
        seller_company_id=seller["id"],
        product_id=product_id,
        quantity=quantity,
        created_round=0,
        min_price=80,
        lead_time=1,
    )
    proposals = exchange.generate_proposals(round_id=0)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.buy_request_id == buy_request.request_id
    assert proposal.sell_request_id == sell_request.request_id
    assert proposal.proposed_price == 100

    exchange.handle_company_response(proposal.proposal_id, "accept", "buyer")
    exchange.handle_company_response(proposal.proposal_id, "accept", "seller")
    exchange.collect_proposal_responses()
    orders = exchange.confirm_orders()

    assert len(orders) == 1
    assert orders[0].status == "confirmed"
    return orders[0]


def test_order_remains_visible_until_both_sides_consume_it():
    seller = {
        "id": "Seller",
        "name": "Seller",
        "salable_products_idList": ["component"],
        "purchasable_materials_idList": [],
    }
    buyer = {
        "id": "Buyer",
        "name": "Buyer",
        "salable_products_idList": [],
        "purchasable_materials_idList": ["component"],
    }
    exchange = Exchange("fixture_exchange", ["Seller"], ["Buyer"])
    _register_route(exchange, seller, buyer)
    order = _complete_explicit_order(exchange, seller, buyer, "component")

    buyer_orders = exchange.get_confirm_orders_for_buyer("Buyer")
    assert [item.order_id for item in buyer_orders] == [order.order_id]
    assert order.status == "confirmed"

    seller_orders = exchange.get_confirm_orders_for_seller("Seller")
    assert [item.order_id for item in seller_orders] == [order.order_id]
    assert order.status == "delivered"
    assert exchange.get_confirm_orders_for_buyer("Buyer") == []
    assert exchange.get_confirm_orders_for_seller("Seller") == []


@pytest.mark.parametrize("scenario_id", ARCHITECTURE_SCENARIOS)
def test_every_configured_architecture_edge_can_complete_a_transaction(scenario_id):
    scenario = SCENARIO_CONFIGS[scenario_id]
    enterprises = {
        item["id"]: item for item in scenario["enterprise_configs"]
    }
    completed_edges = set()

    for buyer in scenario["enterprise_configs"]:
        for seller_id in buyer.get("supplier_name_list", []):
            seller = enterprises[seller_id]
            compatible_products = sorted(
                set(seller.get("salable_products_idList", []))
                & set(buyer.get("purchasable_materials_idList", []))
            )
            assert compatible_products, (
                f"{scenario_id}: no compatible product for {seller_id} -> {buyer['id']}"
            )

            exchange = Exchange(
                f"{seller_id}-{buyer['id']}",
                [seller_id],
                [buyer["id"]],
            )
            _register_route(exchange, seller, buyer)
            order = _complete_explicit_order(
                exchange,
                seller,
                buyer,
                compatible_products[0],
            )
            exchange.get_confirm_orders_for_buyer(buyer["id"])
            exchange.get_confirm_orders_for_seller(seller_id)

            assert order.status == "delivered"
            completed_edges.add((seller_id, buyer["id"]))

    expected_edges = {
        (seller_id, buyer["id"])
        for buyer in scenario["enterprise_configs"]
        for seller_id in buyer.get("supplier_name_list", [])
    }
    assert completed_edges == expected_edges

