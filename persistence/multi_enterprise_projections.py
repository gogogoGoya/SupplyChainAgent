"""Multi-enterprise projections for SQL mirror and parity checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


ORDER_LIFECYCLE_PROJECTION_SCHEMA_VERSION = "order_lifecycle_projection.v1"
TOPOLOGY_PROJECTION_SCHEMA_VERSION = "topology_projection.v1"
ENTERPRISE_DAILY_METRICS_PROJECTION_SCHEMA_VERSION = (
    "enterprise_daily_metrics_projection.v1"
)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _safe_number(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def _count_by_status(items: List[Dict[str, Any]], status_field: str = "status") -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        status = str(item.get(status_field) or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _extract_exchange_payload(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _safe_dict(raw_payload.get("data"))
    return data if data else raw_payload


def _extract_observer_finance_metrics(observer_state: Dict[str, Any]) -> Dict[str, Any]:
    observation = _safe_dict(observer_state.get("observation"))
    finance = _safe_dict(observation.get("finance"))
    indicators = _safe_dict(finance.get("financial_indicators"))
    cash_summary = _safe_dict(finance.get("cash_summary"))
    return {
        "cash": _safe_number(cash_summary.get("current_cash", finance.get("cash"))),
        "total_revenue": _safe_number(finance.get("total_revenue")),
        "total_cost": _safe_number(finance.get("total_cost")),
        "net_profit": _safe_number(indicators.get("net_profit")),
    }


class OrderLifecycleProjectionBuilder:
    """Build a compact order lifecycle projection from saved exchange JSON."""

    def __init__(self, read_json: Callable[[Path, Any], Any] = None):
        self.read_json = read_json or _read_json

    def build(self, *, workspace_dir: Path, round_id: int) -> Dict[str, Any]:
        workspace_dir = Path(workspace_dir)
        run_meta = _safe_dict(self.read_json(workspace_dir / "run_meta.json", {}))
        exchange_path = (
            workspace_dir
            / "public"
            / "exchange"
            / f"day{round_id}"
            / "exchange.json"
        )
        exchange_payload = _extract_exchange_payload(
            _safe_dict(self.read_json(exchange_path, {}))
        )
        exchanges = _safe_dict(exchange_payload.get("exchanges"))
        exchange_records: Dict[str, Any] = {}
        totals = {
            "buy_request_count": 0,
            "sell_request_count": 0,
            "proposal_count": 0,
            "order_count": 0,
            "order_quantity": 0.0,
            "order_value": 0.0,
        }
        order_edges: List[Dict[str, Any]] = []

        for exchange_id, exchange_info in sorted(exchanges.items()):
            buy_requests = _safe_list(_safe_dict(exchange_info.get("buy_requests")).get("list"))
            sell_requests = _safe_list(_safe_dict(exchange_info.get("sell_requests")).get("list"))
            proposals = _safe_list(_safe_dict(exchange_info.get("proposals")).get("list"))
            orders = _safe_list(_safe_dict(exchange_info.get("orders")).get("list"))
            totals["buy_request_count"] += len(buy_requests)
            totals["sell_request_count"] += len(sell_requests)
            totals["proposal_count"] += len(proposals)
            totals["order_count"] += len(orders)
            for order in orders:
                quantity = _safe_number(order.get("quantity"), 0.0) or 0.0
                price = _safe_number(order.get("agreed_price"), 0.0) or 0.0
                totals["order_quantity"] += quantity
                totals["order_value"] += quantity * price
                order_edges.append(
                    {
                        "exchange_id": exchange_id,
                        "order_id": order.get("order_id"),
                        "seller_id": order.get("seller_company_id"),
                        "buyer_id": order.get("buyer_company_id"),
                        "product_id": order.get("product_id"),
                        "quantity": quantity,
                        "value": quantity * price,
                        "status": order.get("status"),
                        "planned_delivery_round": order.get("planned_delivery_round"),
                    }
                )
            exchange_records[exchange_id] = {
                "exchange_id": exchange_id,
                "trading_mode": exchange_info.get("trading_mode"),
                "upstream_layers": exchange_info.get("upstream_layers") or [],
                "downstream_layers": exchange_info.get("downstream_layers") or [],
                "buy_request_status_counts": _count_by_status(
                    [item for item in buy_requests if isinstance(item, dict)],
                    "lifecycle_status",
                ),
                "sell_request_status_counts": _count_by_status(
                    [item for item in sell_requests if isinstance(item, dict)],
                    "lifecycle_status",
                ),
                "proposal_status_counts": _count_by_status(
                    [item for item in proposals if isinstance(item, dict)]
                ),
                "order_status_counts": _count_by_status(
                    [item for item in orders if isinstance(item, dict)]
                ),
                "orders": orders,
            }

        return {
            "schema_version": ORDER_LIFECYCLE_PROJECTION_SCHEMA_VERSION,
            "run_id": str(run_meta.get("run_id") or "workspace_unarchived"),
            "scenario_id": str(run_meta.get("scenario_id") or ""),
            "round_id": int(round_id),
            "source_file": str(exchange_path),
            "source_available": bool(exchanges),
            "totals": totals,
            "order_edges": order_edges,
            "exchanges": exchange_records,
        }


class TopologyProjectionBuilder:
    """Build supplier-customer topology from the scenario config snapshot."""

    def __init__(self, read_json: Callable[[Path, Any], Any] = None):
        self.read_json = read_json or _read_json

    def build(self, *, workspace_dir: Path, round_id: int) -> Dict[str, Any]:
        workspace_dir = Path(workspace_dir)
        run_meta = _safe_dict(self.read_json(workspace_dir / "run_meta.json", {}))
        scenario_config = _safe_dict(run_meta.get("scenario_config"))
        enterprise_configs = _safe_list(scenario_config.get("enterprise_configs"))
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        enterprise_ids = {
            str(item.get("id"))
            for item in enterprise_configs
            if isinstance(item, dict) and item.get("id")
        }
        for item in enterprise_configs:
            if not isinstance(item, dict):
                continue
            enterprise_id = str(item.get("id") or "")
            if not enterprise_id:
                continue
            nodes.append(
                {
                    "enterprise_id": enterprise_id,
                    "name": item.get("name"),
                    "tier": item.get("tier"),
                    "role_tags": item.get("role_tags") or [],
                    "salable_products_idList": item.get("salable_products_idList") or [],
                    "purchasable_materials_idList": item.get("purchasable_materials_idList") or [],
                }
            )
            for supplier_id in item.get("supplier_name_list") or []:
                edges.append(
                    {
                        "supplier_id": supplier_id,
                        "customer_id": enterprise_id,
                        "valid": supplier_id in enterprise_ids,
                        "compatible_products": sorted(
                            set(
                                _safe_dict(
                                    next(
                                        (
                                            supplier
                                            for supplier in enterprise_configs
                                            if isinstance(supplier, dict)
                                            and supplier.get("id") == supplier_id
                                        ),
                                        {},
                                    )
                                ).get("salable_products_idList")
                                or []
                            )
                            & set(item.get("purchasable_materials_idList") or [])
                        ),
                    }
                )

        return {
            "schema_version": TOPOLOGY_PROJECTION_SCHEMA_VERSION,
            "run_id": str(run_meta.get("run_id") or "workspace_unarchived"),
            "scenario_id": str(run_meta.get("scenario_id") or ""),
            "round_id": int(round_id),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "invalid_edge_count": len([edge for edge in edges if not edge["valid"]]),
            "nodes": nodes,
            "edges": edges,
        }


class EnterpriseDailyMetricsProjectionBuilder:
    """Build enterprise/day metrics from history projections and order edges."""

    def __init__(self, read_json: Callable[[Path, Any], Any] = None):
        self.read_json = read_json or _read_json

    def build(self, *, workspace_dir: Path, round_id: int) -> Dict[str, Any]:
        workspace_dir = Path(workspace_dir)
        run_meta = _safe_dict(self.read_json(workspace_dir / "run_meta.json", {}))
        enterprise_ids = [
            str(item)
            for item in run_meta.get("enterprise_ids", [])
            if str(item or "").strip()
        ]
        order_projection = OrderLifecycleProjectionBuilder(
            read_json=self.read_json
        ).build(workspace_dir=workspace_dir, round_id=round_id)
        order_edges = _safe_list(order_projection.get("order_edges"))
        enterprise_metrics: Dict[str, Any] = {}
        for enterprise_id in enterprise_ids:
            history_projection = _safe_dict(
                self.read_json(
                    workspace_dir
                    / "projections"
                    / "history"
                    / f"day{round_id}"
                    / enterprise_id
                    / "history_projection.json",
                    {},
                )
            )
            days = _safe_list(history_projection.get("days"))
            latest_day = _safe_dict(days[-1]) if days else {}
            department_metrics = _safe_dict(latest_day.get("department_metrics"))
            finance_metrics = _safe_dict(department_metrics.get("finance"))
            finance_source = "history_projection"
            observer_state_available = False
            if not finance_metrics:
                observer_state = _safe_dict(
                    self.read_json(
                        workspace_dir
                        / "public"
                        / "observer_state"
                        / f"day{round_id}"
                        / "end_of_day"
                        / f"{enterprise_id}.json",
                        {},
                    )
                )
                observer_state_available = bool(observer_state)
                observer_finance = _extract_observer_finance_metrics(observer_state)
                if any(value is not None for value in observer_finance.values()):
                    finance_metrics = observer_finance
                    department_metrics = {
                        **department_metrics,
                        "finance": observer_finance,
                    }
                    finance_source = "observer_state_end_of_day"
                else:
                    finance_source = "unavailable"
            bought_orders = [
                edge for edge in order_edges if edge.get("buyer_id") == enterprise_id
            ]
            sold_orders = [
                edge for edge in order_edges if edge.get("seller_id") == enterprise_id
            ]
            enterprise_metrics[enterprise_id] = {
                "history_projection_available": bool(history_projection),
                "observer_state_available": observer_state_available,
                "department_metrics": department_metrics,
                "finance": finance_metrics,
                "finance_source": finance_source,
                "order_participation": {
                    "bought_order_count": len(bought_orders),
                    "sold_order_count": len(sold_orders),
                    "bought_quantity": sum(
                        _safe_number(edge.get("quantity"), 0.0) or 0.0
                        for edge in bought_orders
                    ),
                    "sold_quantity": sum(
                        _safe_number(edge.get("quantity"), 0.0) or 0.0
                        for edge in sold_orders
                    ),
                    "bought_value": sum(
                        _safe_number(edge.get("value"), 0.0) or 0.0
                        for edge in bought_orders
                    ),
                    "sold_value": sum(
                        _safe_number(edge.get("value"), 0.0) or 0.0
                        for edge in sold_orders
                    ),
                },
            }

        return {
            "schema_version": ENTERPRISE_DAILY_METRICS_PROJECTION_SCHEMA_VERSION,
            "run_id": str(run_meta.get("run_id") or "workspace_unarchived"),
            "scenario_id": str(run_meta.get("scenario_id") or ""),
            "round_id": int(round_id),
            "enterprise_count": len(enterprise_ids),
            "enterprise_metrics": enterprise_metrics,
        }


def _write_projection(output_path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def write_order_lifecycle_projection(
    *,
    workspace_dir: Path,
    round_id: int,
    output_path: Path,
) -> Dict[str, Any]:
    return _write_projection(
        output_path,
        OrderLifecycleProjectionBuilder().build(
            workspace_dir=workspace_dir,
            round_id=round_id,
        ),
    )


def write_topology_projection(
    *,
    workspace_dir: Path,
    round_id: int,
    output_path: Path,
) -> Dict[str, Any]:
    return _write_projection(
        output_path,
        TopologyProjectionBuilder().build(
            workspace_dir=workspace_dir,
            round_id=round_id,
        ),
    )


def write_enterprise_daily_metrics_projection(
    *,
    workspace_dir: Path,
    round_id: int,
    output_path: Path,
) -> Dict[str, Any]:
    return _write_projection(
        output_path,
        EnterpriseDailyMetricsProjectionBuilder().build(
            workspace_dir=workspace_dir,
            round_id=round_id,
        ),
    )
