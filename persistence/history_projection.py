"""History projection helpers for single-enterprise diagnosis and fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


HISTORY_PROJECTION_SCHEMA_VERSION = "history_projection.v1"
DEFAULT_DEPARTMENTS = (
    "finance",
    "sales",
    "procurement",
    "production",
    "inventory",
    "hr",
)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _extract_finance_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    self_state = _safe_dict(payload.get("self_state"))
    indicators = _safe_dict(self_state.get("financial_indicators"))
    cash_summary = _safe_dict(self_state.get("cash_summary"))
    return {
        "cash": _safe_number(
            cash_summary.get("current_cash", self_state.get("cash"))
        ),
        "total_revenue": _safe_number(self_state.get("total_revenue")),
        "total_cost": _safe_number(self_state.get("total_cost")),
        "net_profit": _safe_number(indicators.get("net_profit")),
    }


def _count_items(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def _count_status_items(status_map: Dict[str, Any], statuses: List[str]) -> int:
    return sum(_count_items(status_map.get(status)) for status in statuses)


def _extract_department_metrics(department: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    self_state = _safe_dict(payload.get("self_state"))
    blackboard = _safe_dict(payload.get("blackboard"))
    if department == "finance":
        return _extract_finance_metrics(payload)
    if department == "sales":
        sales_orders = _safe_dict(self_state.get("sales_orders"))
        sales_metrics = _safe_dict(self_state.get("sales_metrics"))
        service_summary = _safe_dict(self_state.get("service_level_summary"))
        total_demand = _safe_number(
            service_summary.get(
                "total_downstream_demand",
                sales_metrics.get("total_downstream_demand"),
            ),
            0.0,
        )
        fulfilled_demand = _safe_number(
            service_summary.get(
                "fulfilled_downstream_demand",
                sales_metrics.get("fulfilled_downstream_demand"),
            ),
            0.0,
        )
        fill_rate = _safe_number(service_summary.get("fill_rate"))
        if fill_rate is None and total_demand:
            fill_rate = fulfilled_demand / total_demand
        return {
            "available_orders": _count_status_items(
                sales_orders,
                ["available"],
            ),
            "confirmed_orders": _count_status_items(
                sales_orders,
                ["accepted", "confirmed", "in_progress"],
            ),
            "completed_orders": _count_status_items(
                sales_orders,
                ["completed", "fulfilled"],
            ),
            "breached_orders": _count_status_items(
                sales_orders,
                ["breached"],
            ),
            "rejected_orders": _count_status_items(
                sales_orders,
                ["rejected"],
            ),
            "total_orders": _safe_number(sales_metrics.get("total_orders")),
            "accepted_orders": _safe_number(
                sales_metrics.get("accepted_orders")
            ),
            "fulfilled_downstream_demand": fulfilled_demand,
            "total_downstream_demand": total_demand,
            "fill_rate": fill_rate,
            "confirmed_order_backlog_quantity": _safe_number(
                service_summary.get(
                    "confirmed_order_backlog_quantity",
                    sales_metrics.get("confirmed_order_backlog_quantity"),
                ),
                0.0,
            ),
            "lost_sales_quantity": _safe_number(
                service_summary.get(
                    "lost_sales_quantity",
                    sales_metrics.get("lost_sales_quantity"),
                ),
                0.0,
            ),
        }
    if department == "procurement":
        return {
            "pending_orders": _count_items(self_state.get("pending_orders")),
            "available_proposals": _count_items(self_state.get("available_proposals")),
            "supplier_count": _count_items(self_state.get("suppliers")),
        }
    if department == "production":
        production_plans = _safe_dict(self_state.get("production_plans"))
        production_lines = _safe_dict(self_state.get("production_lines"))
        production_metrics = _safe_dict(self_state.get("production_metrics"))
        cobweb_signal = _safe_dict(
            self_state.get("cobweb_decision_signal")
        )
        return {
            "active_plans": _count_status_items(
                production_plans,
                ["pending", "in_progress", "active", "paused"],
            ),
            "production_lines": _count_items(
                production_lines.get("details")
            ),
            "available_capacity": _safe_number(
                production_lines.get(
                    "available_capacity",
                    self_state.get("available_capacity"),
                )
            ),
            "total_capacity": _safe_number(
                production_lines.get(
                    "total_capacity",
                    self_state.get("total_capacity"),
                )
            ),
            "total_production": _safe_number(
                production_metrics.get("total_production")
            ),
            "total_planned": _safe_number(
                production_metrics.get("total_planned")
            ),
            "production_cost": _safe_number(
                production_metrics.get("total_cost")
            ),
            "cobweb_market_price": _safe_number(
                cobweb_signal.get("current_market_price")
            ),
            "cobweb_market_supply": _safe_number(
                cobweb_signal.get("market_supply_quantity")
            ),
            "cobweb_actual_supply": _safe_number(
                cobweb_signal.get("actual_supply_quantity")
            ),
            "cobweb_equilibrium_price": _safe_number(
                cobweb_signal.get("equilibrium_price")
            ),
            "cobweb_equilibrium_quantity": _safe_number(
                cobweb_signal.get("equilibrium_quantity")
            ),
            "cobweb_price_deviation": _safe_number(
                cobweb_signal.get("price_deviation_from_equilibrium")
            ),
            "cobweb_quantity_deviation": _safe_number(
                cobweb_signal.get("quantity_deviation_from_equilibrium")
            ),
            "cobweb_supply_source": cobweb_signal.get(
                "market_supply_source"
            ),
        }
    if department == "inventory":
        inventory_items = [
            item
            for item in (self_state.get("inventory_items") or [])
            if isinstance(item, dict)
        ]
        inventory_metrics = _safe_dict(self_state.get("inventory_metrics"))
        finished_goods_quantity = sum(
            _safe_number(item.get("quantity"), 0.0) or 0.0
            for item in inventory_items
            if item.get("item_type") == "product"
        )
        beer_item = next(
            (
                item
                for item in inventory_items
                if item.get("item_id") == "beer"
            ),
            {},
        )
        return {
            "used_capacity": _safe_number(self_state.get("used_capacity")),
            "warehouse_capacity": _safe_number(self_state.get("warehouse_capacity")),
            "warehouse_utilization": _safe_number(
                self_state.get("warehouse_utilization"),
                _safe_number(inventory_metrics.get("warehouse_utilization")),
            ),
            "finished_goods_quantity": finished_goods_quantity,
            "beer_quantity": _safe_number(beer_item.get("quantity")),
            "policy_alert_count": _count_items(
                _safe_dict(
                    _safe_dict(
                        blackboard.get("departments")
                    ).get("inventory")
                ).get("policy_alerts")
            ),
        }
    if department == "hr":
        employees = self_state.get("employees") or []
        return {
            "employee_groups": _count_items(employees),
            "available_workers": sum(
                max(
                    0,
                    int(_safe_number(item.get("count"), 0) or 0)
                    - int(_safe_number(item.get("allocated"), 0) or 0),
                )
                for item in employees
                if isinstance(item, dict)
            ),
        }
    return {}


def _metric_delta(rows: List[Dict[str, Any]], metric_path: List[str]) -> Optional[float]:
    values: List[float] = []
    for row in rows:
        value: Any = row
        for key in metric_path:
            value = _safe_dict(value).get(key)
        number = _safe_number(value)
        if number is not None:
            values.append(number)
    if len(values) < 2:
        return None
    return values[-1] - values[0]


def _metric_series_summary(
    rows: List[Dict[str, Any]],
    metric_path: List[str],
) -> Dict[str, Any]:
    values: List[float] = []
    for row in rows:
        value: Any = row
        for key in metric_path:
            value = _safe_dict(value).get(key)
        number = _safe_number(value)
        if number is not None:
            values.append(number)
    if not values:
        return {
            "count": 0,
            "latest": None,
            "mean": None,
            "minimum": None,
            "maximum": None,
            "delta": None,
            "mean_abs_change": None,
        }
    changes = [
        abs(values[index] - values[index - 1])
        for index in range(1, len(values))
    ]
    return {
        "count": len(values),
        "latest": values[-1],
        "mean": sum(values) / len(values),
        "minimum": min(values),
        "maximum": max(values),
        "delta": values[-1] - values[0] if len(values) >= 2 else None,
        "mean_abs_change": (
            sum(changes) / len(changes)
            if changes
            else None
        ),
    }


class HistoryProjectionBuilder:
    """Build bounded history windows without reading future days."""

    def __init__(
        self,
        read_json: Callable[[Path, Any], Any] = None,
        departments: List[str] = None,
    ):
        self.read_json = read_json or _read_json
        self.departments = tuple(departments or DEFAULT_DEPARTMENTS)

    def build_enterprise_day_projection(
        self,
        enterprise_dir: Path,
        enterprise_id: str,
        day: int,
    ) -> Dict[str, Any]:
        department_metrics: Dict[str, Any] = {}
        source_files: Dict[str, str] = {}
        for department in self.departments:
            path = (
                enterprise_dir
                / "department"
                / department
                / f"day{day}"
                / f"{department}.json"
            )
            payload = self.read_json(path, {})
            if payload:
                department_metrics[department] = _extract_department_metrics(
                    department,
                    _safe_dict(payload),
                )
                source_files[department] = str(path)

        analysis_path = enterprise_dir / "records" / f"day{day}" / "analysis.json"
        analysis = _safe_dict(self.read_json(analysis_path, {}))
        return {
            "day": day,
            "enterprise_id": enterprise_id,
            "department_metrics": department_metrics,
            "analysis_summary": analysis.get("enterprise_summarys", ""),
            "source_files": source_files,
        }

    def build_history_window(
        self,
        enterprise_dir: Path,
        enterprise_id: str,
        current_day: int,
        history_days: int,
    ) -> Dict[str, Any]:
        current_day = max(0, int(current_day))
        history_days = max(1, int(history_days))
        start_day = max(0, current_day - history_days + 1)
        rows = [
            self.build_enterprise_day_projection(
                enterprise_dir,
                enterprise_id,
                day,
            )
            for day in range(start_day, current_day + 1)
        ]
        operating_trends = {
            "cobweb_market_price": _metric_series_summary(
                rows,
                [
                    "department_metrics",
                    "production",
                    "cobweb_market_price",
                ],
            ),
            "cobweb_market_supply": _metric_series_summary(
                rows,
                [
                    "department_metrics",
                    "production",
                    "cobweb_market_supply",
                ],
            ),
            "total_production": _metric_series_summary(
                rows,
                ["department_metrics", "production", "total_production"],
            ),
            "confirmed_order_backlog_quantity": _metric_series_summary(
                rows,
                [
                    "department_metrics",
                    "sales",
                    "confirmed_order_backlog_quantity",
                ],
            ),
            "fill_rate": _metric_series_summary(
                rows,
                ["department_metrics", "sales", "fill_rate"],
            ),
            "finished_goods_quantity": _metric_series_summary(
                rows,
                [
                    "department_metrics",
                    "inventory",
                    "finished_goods_quantity",
                ],
            ),
        }
        return {
            "schema_version": HISTORY_PROJECTION_SCHEMA_VERSION,
            "enterprise_id": enterprise_id,
            "generated_for_day": current_day,
            "history_days": history_days,
            "source_day_range": {"start_day": start_day, "end_day": current_day},
            "no_future_data": all(row["day"] <= current_day for row in rows),
            "days": rows,
            "trends": {
                "cash_delta": _metric_delta(
                    rows,
                    ["department_metrics", "finance", "cash"],
                ),
                "revenue_delta": _metric_delta(
                    rows,
                    ["department_metrics", "finance", "total_revenue"],
                ),
                "net_profit_delta": _metric_delta(
                    rows,
                    ["department_metrics", "finance", "net_profit"],
                ),
                "available_capacity_delta": _metric_delta(
                    rows,
                    ["department_metrics", "production", "available_capacity"],
                ),
                "operating": operating_trends,
            },
        }


def write_history_projection(
    enterprise_dir: Path,
    enterprise_id: str,
    current_day: int,
    history_days: int,
    output_path: Path,
) -> Dict[str, Any]:
    payload = HistoryProjectionBuilder().build_history_window(
        enterprise_dir=enterprise_dir,
        enterprise_id=enterprise_id,
        current_day=current_day,
        history_days=history_days,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload
