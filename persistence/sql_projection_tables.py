"""Physical read-model rows derived from SQL mirror projections."""

from __future__ import annotations

from typing import Any, Dict, List


ORDER_LIFECYCLE_ORDERS_TABLE = "order_lifecycle_orders"
TOPOLOGY_NODES_TABLE = "topology_nodes"
TOPOLOGY_EDGES_TABLE = "topology_edges"
ENTERPRISE_DAILY_METRICS_TABLE = "enterprise_daily_metrics"

PHYSICAL_PROJECTION_TABLES = {
    ORDER_LIFECYCLE_ORDERS_TABLE,
    TOPOLOGY_NODES_TABLE,
    TOPOLOGY_EDGES_TABLE,
    ENTERPRISE_DAILY_METRICS_TABLE,
}


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _identity(payload: Dict[str, Any], key: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": str(payload.get("run_id") or key.get("run_id") or ""),
        "scenario_id": str(payload.get("scenario_id") or key.get("scenario_id") or ""),
        "round_id": int(payload.get("round_id", key.get("round_id", 0))),
    }


def build_physical_projection_rows(
    projection_name: str,
    key: Dict[str, Any],
    payload: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    if projection_name == "order_lifecycle_projection":
        return {
            ORDER_LIFECYCLE_ORDERS_TABLE: _build_order_rows(key, payload),
        }
    if projection_name == "topology_projection":
        return {
            TOPOLOGY_NODES_TABLE: _build_topology_node_rows(key, payload),
            TOPOLOGY_EDGES_TABLE: _build_topology_edge_rows(key, payload),
        }
    if projection_name == "enterprise_daily_metrics_projection":
        return {
            ENTERPRISE_DAILY_METRICS_TABLE: _build_enterprise_metric_rows(
                key,
                payload,
            ),
        }
    return {}


def _build_order_rows(
    key: Dict[str, Any],
    payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    identity = _identity(payload, key)
    rows: List[Dict[str, Any]] = []
    for order in payload.get("order_edges") or []:
        if not isinstance(order, dict):
            continue
        rows.append(
            {
                **identity,
                "exchange_id": str(order.get("exchange_id") or ""),
                "order_id": str(order.get("order_id") or ""),
                "seller_id": str(order.get("seller_id") or ""),
                "buyer_id": str(order.get("buyer_id") or ""),
                "product_id": str(order.get("product_id") or ""),
                "quantity": _safe_number(order.get("quantity")),
                "value": _safe_number(order.get("value")),
                "status": str(order.get("status") or ""),
                "planned_delivery_round": order.get("planned_delivery_round"),
                "payload": order,
            }
        )
    return rows


def _build_topology_node_rows(
    key: Dict[str, Any],
    payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    identity = _identity(payload, key)
    rows: List[Dict[str, Any]] = []
    for node in payload.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        rows.append(
            {
                **identity,
                "enterprise_id": str(node.get("enterprise_id") or ""),
                "name": str(node.get("name") or ""),
                "tier": node.get("tier"),
                "role_tags": node.get("role_tags") or [],
                "payload": node,
            }
        )
    return rows


def _build_topology_edge_rows(
    key: Dict[str, Any],
    payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    identity = _identity(payload, key)
    rows: List[Dict[str, Any]] = []
    for edge in payload.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        rows.append(
            {
                **identity,
                "supplier_id": str(edge.get("supplier_id") or ""),
                "customer_id": str(edge.get("customer_id") or ""),
                "valid": bool(edge.get("valid")),
                "compatible_products": edge.get("compatible_products") or [],
                "payload": edge,
            }
        )
    return rows


def _build_enterprise_metric_rows(
    key: Dict[str, Any],
    payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    identity = _identity(payload, key)
    rows: List[Dict[str, Any]] = []
    for enterprise_id, metrics in _safe_dict(payload.get("enterprise_metrics")).items():
        metrics = _safe_dict(metrics)
        finance = _safe_dict(metrics.get("finance"))
        participation = _safe_dict(metrics.get("order_participation"))
        rows.append(
            {
                **identity,
                "enterprise_id": str(enterprise_id),
                "cash": finance.get("cash"),
                "net_profit": finance.get("net_profit"),
                "bought_order_count": int(participation.get("bought_order_count") or 0),
                "sold_order_count": int(participation.get("sold_order_count") or 0),
                "bought_quantity": _safe_number(participation.get("bought_quantity")),
                "sold_quantity": _safe_number(participation.get("sold_quantity")),
                "bought_value": _safe_number(participation.get("bought_value")),
                "sold_value": _safe_number(participation.get("sold_value")),
                "payload": metrics,
            }
        )
    return rows
