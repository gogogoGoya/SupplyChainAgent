#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Any


DEPARTMENTS = ["finance", "production", "sales", "inventory", "procurement", "hr"]
TERMINAL_ORDER_STATUSES = {
    "completed",
    "delivered",
    "rejected",
    "cancelled",
    "canceled",
    "breached",
    "failed",
}
COMMITTED_ORDER_STATUSES = {
    "accepted",
    "in_progress",
    "backlog",
    "confirmed",
}
ORDER_STATUS_LABELS = {
    "available": "待接收",
    "accepted": "已接受待履约",
    "in_progress": "履约中",
    "completed": "已完成",
    "delivered": "已交付",
    "rejected": "已拒绝",
    "breached": "已违约",
    "cancelled": "已取消",
    "canceled": "已取消",
    "failed": "失败",
    "unknown": "未知状态",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def detect_available_days(workspace_dir: Path) -> list[int]:
    observations_dir = workspace_dir / "observations"
    available_days: list[int] = []

    for observation_path in sorted(observations_dir.glob("observation_day*.txt")):
        match = re.fullmatch(r"observation_day(\d+)\.txt", observation_path.name)
        if not match:
            continue
        try:
            load_json(observation_path)
        except json.JSONDecodeError:
            continue

        available_days.append(int(match.group(1)))

    return sorted(available_days)


def load_observations(workspace_dir: Path, available_days: list[int]) -> dict[int, dict[str, Any]]:
    observations_dir = workspace_dir / "observations"
    all_data: dict[int, dict[str, Any]] = {}
    for day in available_days:
        all_data[day] = load_json(observations_dir / f"observation_day{day}.txt")
    return all_data


def get_department_day_dir(workspace_dir: Path, dept: str, day: int) -> Path:
    return workspace_dir / "department" / dept / f"day{day}"


def sort_artifact_paths(paths: list[Path]) -> list[Path]:
    def sort_key(path: Path) -> tuple[int, str]:
        try:
            modified_ns = path.stat().st_mtime_ns
        except OSError:
            modified_ns = 0
        return modified_ns, path.name

    return sorted(paths, key=sort_key)


def collect_department_artifacts(
    workspace_dir: Path,
    dept: str,
    day: int,
    artifact_suffix: str,
) -> list[Path]:
    dept_dir = get_department_day_dir(workspace_dir, dept, day)
    if not dept_dir.exists():
        return []

    candidates = [
        dept_dir / f"{dept}{artifact_suffix}.json",
        *sorted(dept_dir.glob(f"{dept}{artifact_suffix}_*.json")),
        *sorted(dept_dir.glob(f"*{artifact_suffix}.json")),
        *sorted(dept_dir.glob(f"*{artifact_suffix}_*.json")),
    ]
    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        unique_paths.append(candidate)
    return sort_artifact_paths(unique_paths)


def normalize_action_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        if len(payload) == 1 and isinstance(payload[0], list):
            payload = payload[0]
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for nested_key in ("workflow", "actions", "action_records", "items"):
            nested_payload = payload.get(nested_key)
            if isinstance(nested_payload, list):
                return normalize_action_payload(nested_payload)
        return [payload]
    return []


def load_action_records_from_path(action_path: Path) -> list[dict[str, Any]]:
    if not action_path.exists():
        return []
    try:
        return normalize_action_payload(load_json(action_path))
    except Exception:
        return []


def get_action_path_for_result(result_path: Path) -> Path | None:
    name = result_path.name
    if "_result" not in name:
        return None
    return result_path.with_name(name.replace("_result", "_action", 1))


def extract_action_name(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    for key in ("action_type", "action_name", "type", "name"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    action = record.get("action")
    if isinstance(action, dict):
        for key in ("action_name", "action_type", "type", "name"):
            value = action.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if record.get("pass_reason"):
        return "action_pass"
    return ""


def is_pass_action_name(action_name: str) -> bool:
    return str(action_name or "").strip() == "action_pass"


def load_department_result_files(
    workspace_dir: Path,
    dept: str,
    day: int,
) -> list[tuple[Path, dict[str, Any]]]:
    results: list[tuple[Path, dict[str, Any]]] = []
    for result_path in collect_department_artifacts(workspace_dir, dept, day, "_result"):
        try:
            payload = load_json(result_path)
        except Exception:
            continue
        if isinstance(payload, dict):
            results.append((result_path, payload))
    return results


def load_department_result(workspace_dir: Path, dept: str, day: int) -> dict[str, Any]:
    result_files = load_department_result_files(workspace_dir, dept, day)
    if result_files:
        return result_files[0][1]
    return {}


def load_department_actions(workspace_dir: Path, dept: str, day: int) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for candidate in collect_department_artifacts(workspace_dir, dept, day, "_action"):
        actions.extend(load_action_records_from_path(candidate))
    return actions


def find_run_meta(workspace_dir: Path) -> dict[str, Any]:
    for parent in [workspace_dir, *workspace_dir.parents]:
        candidate = parent / "run_meta.json"
        if candidate.exists():
            try:
                return load_json(candidate)
            except Exception:
                return {}
    return {}


def is_single_case_prewarm_day(run_meta: dict[str, Any], day: int) -> bool:
    if str(run_meta.get("orchestrator") or "") != "single_enterprise":
        return False
    case_policy = run_meta.get("single_enterprise_case") or {}
    if not isinstance(case_policy, dict) or not case_policy.get("enabled"):
        return False
    try:
        handoff_day = int(
            case_policy.get("handoff_day")
            or run_meta.get("handoff_day")
            or case_policy.get("prewarm_rounds")
            or run_meta.get("prewarm_rounds")
            or 0
        )
    except (TypeError, ValueError):
        return False
    return handoff_day > 0 and int(day) < handoff_day


def is_single_case_run(run_meta: dict[str, Any]) -> bool:
    if str(run_meta.get("orchestrator") or "") == "single_enterprise":
        return True
    case_policy = run_meta.get("single_enterprise_case") or {}
    return isinstance(case_policy, dict) and bool(case_policy.get("enabled"))


def load_prewarm_execution_summary(workspace_dir: Path) -> dict[str, Any]:
    for parent in [workspace_dir, *workspace_dir.parents]:
        candidate = (
            parent
            / "projections"
            / "single_case_prewarm"
            / "prewarm_execution_summary.json"
        )
        if candidate.exists():
            try:
                return load_json(candidate)
            except Exception:
                return {}
    return {}


def load_department_errors(workspace_dir: Path, dept: str, day: int) -> list[Any]:
    error_files: list[Any] = []
    for error_path in collect_department_artifacts(workspace_dir, dept, day, "_error"):
        try:
            error_files.append(load_json(error_path))
        except Exception:
            continue

    return error_files


def build_inventory_items(all_data: dict[int, dict[str, Any]], available_days: list[int]) -> dict[str, Any]:
    inventory_items: dict[str, Any] = {}

    for index, day in enumerate(available_days):
        day_inventory = all_data[day].get("inventory", {})
        for item in day_inventory.get("inventory_items", []):
            item_id = item["item_id"]
            if item_id not in inventory_items:
                inventory_items[item_id] = {
                    "item_type": item.get("item_type"),
                    "data": [0] * len(available_days),
                }
            inventory_items[item_id]["data"][index] = item.get("quantity", 0)

    return inventory_items


def to_number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_order_status(status: Any) -> str:
    normalized = str(status or "unknown").strip().lower()
    return normalized or "unknown"


def order_status_label(status: Any) -> str:
    normalized = normalize_order_status(status)
    return ORDER_STATUS_LABELS.get(normalized, str(status or "未知状态"))


def has_order_deadline(order: dict[str, Any]) -> bool:
    return order.get("delivery_deadline") not in (None, "")


def should_track_order_deadline(order: dict[str, Any]) -> bool:
    status = normalize_order_status(order.get("status"))
    return (
        status not in TERMINAL_ORDER_STATUSES
        and has_order_deadline(order)
        and to_number(order.get("quantity")) > 0
    )


def build_orders_summary_from_orders(
    orders: list[dict[str, Any]],
    source_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for order in orders:
        status = normalize_order_status(order.get("status"))
        by_status[status] = by_status.get(status, 0) + 1
    summary = dict(source_summary or {})
    summary["total"] = len(orders) if orders else int(to_number(summary.get("total"), 0))
    summary["by_status"] = by_status or summary.get("by_status", {})
    return summary


def deep_get(payload: dict[str, Any], path: list[str], default: Any = None) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def cumulative_to_period_values(values: list[float]) -> list[float]:
    period_values: list[float] = []
    previous = 0.0
    for value in values:
        period_values.append(value - previous)
        previous = value
    return period_values


def flatten_sales_orders(observation: dict[str, Any]) -> list[dict[str, Any]]:
    sales_orders = observation.get("sales", {}).get("sales_orders", {})
    if isinstance(sales_orders, list):
        return [order for order in sales_orders if isinstance(order, dict)]
    orders: list[dict[str, Any]] = []
    if isinstance(sales_orders, dict):
        for status, status_orders in sales_orders.items():
            if not isinstance(status_orders, list):
                continue
            for order in status_orders:
                if isinstance(order, dict):
                    enriched = dict(order)
                    enriched.setdefault("status", status)
                    orders.append(enriched)
    return orders


def flatten_status_bucket(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows: list[dict[str, Any]] = []
        for status, bucket in payload.items():
            if not isinstance(bucket, list):
                continue
            for item in bucket:
                if not isinstance(item, dict):
                    continue
                enriched = dict(item)
                enriched.setdefault("status", status)
                rows.append(enriched)
        return rows
    return []


def latest_inventory_items(observation: dict[str, Any]) -> list[dict[str, Any]]:
    items = observation.get("inventory", {}).get("inventory_items", [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def finished_stock_by_product(observation: dict[str, Any]) -> dict[str, float]:
    stock: dict[str, float] = {}
    for item in latest_inventory_items(observation):
        item_type = str(item.get("item_type") or "").lower()
        if item_type in {
            "product",
            "finished_product",
            "finished_good",
            "produce_daily",
            "produce_completed",
        }:
            product_id = str(item.get("item_id") or "product")
            stock[product_id] = stock.get(product_id, 0.0) + to_number(item.get("quantity"))
    return stock


def recipe_materials_by_product(observation: dict[str, Any]) -> dict[str, dict[str, float]]:
    recipes = observation.get("production", {}).get("product_recipes") or []
    recipe_map: dict[str, dict[str, float]] = {}
    if isinstance(recipes, dict):
        iterable = []
        for product_id, recipe in recipes.items():
            if isinstance(recipe, dict):
                enriched = dict(recipe)
                enriched.setdefault("product_id", product_id)
                iterable.append(enriched)
    elif isinstance(recipes, list):
        iterable = [recipe for recipe in recipes if isinstance(recipe, dict)]
    else:
        iterable = []

    for recipe in iterable:
        product_id = recipe.get("product_id")
        raw_materials = recipe.get("raw_materials")
        if not product_id or not isinstance(raw_materials, dict):
            continue
        material_map = {
            str(material_id): to_number(quantity)
            for material_id, quantity in raw_materials.items()
            if to_number(quantity) > 0
        }
        if material_map:
            recipe_map[str(product_id)] = material_map
    return recipe_map


def infer_product_ids(observation: dict[str, Any]) -> list[str]:
    product_ids: set[str] = set()
    production = observation.get("production", {})
    for product_id in production.get("products_idList") or []:
        if product_id:
            product_ids.add(str(product_id))
    recipes = production.get("product_recipes") or []
    if isinstance(recipes, dict):
        product_ids.update(str(product_id) for product_id in recipes if product_id)
    else:
        for recipe in recipes:
            if isinstance(recipe, dict) and recipe.get("product_id"):
                product_ids.add(str(recipe["product_id"]))
    for order in flatten_sales_orders(observation):
        if order.get("product_id"):
            product_ids.add(str(order["product_id"]))
    for item in latest_inventory_items(observation):
        item_type = str(item.get("item_type") or "").lower()
        if item_type in {
            "product",
            "finished_product",
            "finished_good",
            "produce_daily",
            "produce_completed",
        } and item.get("item_id"):
            product_ids.add(str(item["item_id"]))
    return sorted(product_ids) or ["product"]


def flatten_production_plans(observation: dict[str, Any]) -> list[dict[str, Any]]:
    return flatten_status_bucket(observation.get("production", {}).get("production_plans", {}))


def is_active_production_plan(plan: dict[str, Any]) -> bool:
    status = str(plan.get("status") or "").lower()
    if status in {"completed", "finished", "failed", "cancelled", "canceled"}:
        return False
    quantity = to_number(plan.get("quantity"))
    produced = to_number(deep_get(plan, ["progress", "quantity_produced"], 0.0))
    return quantity <= 0 or produced < quantity


def forecast_plan_daily_rows(
    observation: dict[str, Any],
    current_day: int,
    horizon: int,
) -> list[tuple[int, dict[str, Any], float]]:
    """Return (future_day, plan, output_quantity) rows for known active plans."""
    rows: list[tuple[int, dict[str, Any], float]] = []
    for plan in flatten_production_plans(observation):
        if not is_active_production_plan(plan):
            continue
        quantity = to_number(plan.get("quantity"))
        produced = to_number(deep_get(plan, ["progress", "quantity_produced"], 0.0))
        remaining = max(0.0, quantity - produced)
        if remaining <= 0:
            continue
        daily_capacity = to_number(plan.get("daily_capacity"), remaining)
        if daily_capacity <= 0:
            daily_capacity = remaining
        start_day = int(to_number(plan.get("start_time"), current_day + 1))
        completion_day = int(to_number(plan.get("completion_time"), current_day + 1))
        first_day = max(current_day + 1, start_day)
        last_day = min(current_day + horizon, max(first_day, completion_day))
        for future_day in range(first_day, last_day + 1):
            if remaining <= 0:
                break
            output = min(daily_capacity, remaining)
            rows.append((future_day, plan, output))
            remaining -= output
    return rows


def forecast_planned_output_by_day_product(
    observation: dict[str, Any],
    current_day: int,
    horizon: int,
) -> dict[tuple[int, str], float]:
    planned_output: dict[tuple[int, str], float] = {}
    default_product = infer_product_ids(observation)[0]
    for future_day, plan, output in forecast_plan_daily_rows(observation, current_day, horizon):
        product_id = str(plan.get("product_id") or default_product)
        planned_output[(future_day, product_id)] = (
            planned_output.get((future_day, product_id), 0.0) + output
        )
    return planned_output


def forecast_material_consumption_by_day_material(
    observation: dict[str, Any],
    current_day: int,
    horizon: int,
) -> dict[tuple[int, str], float]:
    consumption: dict[tuple[int, str], float] = {}
    for plan in flatten_production_plans(observation):
        if not is_active_production_plan(plan):
            continue
        quantity = to_number(plan.get("quantity"))
        produced = to_number(deep_get(plan, ["progress", "quantity_produced"], 0.0))
        remaining_output = max(0.0, quantity - produced)
        if remaining_output <= 0:
            continue
        daily_capacity = to_number(plan.get("daily_capacity"), remaining_output)
        if daily_capacity <= 0:
            daily_capacity = remaining_output
        start_day = int(to_number(plan.get("start_time"), current_day + 1))
        completion_day = int(to_number(plan.get("completion_time"), current_day + 1))
        first_day = max(current_day + 1, start_day)
        last_day = min(current_day + horizon, max(first_day, completion_day))

        daily_materials = plan.get("daily_materials") if isinstance(plan.get("daily_materials"), dict) else {}
        materials_needed = (
            plan.get("materials_needed")
            if isinstance(plan.get("materials_needed"), dict)
            else {}
        )
        materials_consumed = deep_get(plan, ["progress", "materials_consumed"], {})
        if not isinstance(materials_consumed, dict):
            materials_consumed = {}
        if not daily_materials and materials_needed:
            quantity = max(1.0, to_number(plan.get("quantity"), remaining_output))
            daily_materials = {
                material_id: to_number(required) * daily_capacity / quantity
                for material_id, required in materials_needed.items()
            }
        remaining_materials = {
            str(material_id): max(
                0.0,
                to_number(required_quantity) - to_number(materials_consumed.get(material_id)),
            )
            for material_id, required_quantity in materials_needed.items()
        }

        for future_day in range(first_day, last_day + 1):
            if remaining_output <= 0:
                break
            output = min(daily_capacity, remaining_output)
            output_ratio = output / daily_capacity if daily_capacity > 0 else 1.0
            for material_id, daily_quantity in daily_materials.items():
                material_key = str(material_id)
                planned_quantity = to_number(daily_quantity) * output_ratio
                if materials_needed:
                    planned_quantity = min(planned_quantity, remaining_materials.get(material_key, 0.0))
                if planned_quantity <= 0:
                    continue
                if materials_needed:
                    remaining_materials[material_key] = max(
                        0.0,
                        remaining_materials.get(material_key, 0.0) - planned_quantity,
                    )
                key = (future_day, material_key)
                consumption[key] = consumption.get(key, 0.0) + planned_quantity
            remaining_output -= output
    return consumption


def forecast_unplanned_order_material_demand_by_day(
    observation: dict[str, Any],
    current_day: int,
    horizon: int,
) -> dict[tuple[int, str], float]:
    """Estimate material needs for order demand not covered by stock or active plans."""
    recipe_map = recipe_materials_by_product(observation)
    if not recipe_map:
        return {}

    planned_output = forecast_planned_output_by_day_product(
        observation,
        current_day,
        horizon,
    )
    projected_supply = finished_stock_by_product(observation)
    demand_by_day_product: dict[tuple[int, str], float] = {}
    for order in flatten_sales_orders(observation):
        status = str(order.get("status") or "").lower()
        if status not in COMMITTED_ORDER_STATUSES:
            continue
        product_id = str(order.get("product_id") or "")
        if not product_id or product_id not in recipe_map:
            continue
        deadline = int(to_number(order.get("delivery_deadline"), current_day))
        if current_day < deadline <= current_day + horizon:
            demand_by_day_product[(deadline, product_id)] = (
                demand_by_day_product.get((deadline, product_id), 0.0)
                + to_number(order.get("quantity"))
            )

    material_demand: dict[tuple[int, str], float] = {}
    for future_day in range(current_day + 1, current_day + horizon + 1):
        product_ids = {
            product_id
            for day, product_id in demand_by_day_product
            if day == future_day
        } | {
            product_id
            for day, product_id in planned_output
            if day == future_day
        }
        for product_id in sorted(product_ids):
            projected_supply[product_id] = (
                projected_supply.get(product_id, 0.0)
                + planned_output.get((future_day, product_id), 0.0)
            )
            due_quantity = demand_by_day_product.get((future_day, product_id), 0.0)
            if due_quantity <= 0:
                continue
            shortage = max(0.0, due_quantity - projected_supply.get(product_id, 0.0))
            projected_supply[product_id] = max(
                0.0,
                projected_supply.get(product_id, 0.0) - due_quantity,
            )
            if shortage <= 0:
                continue
            for material_id, per_unit in recipe_map.get(product_id, {}).items():
                key = (future_day, material_id)
                material_demand[key] = material_demand.get(key, 0.0) + shortage * per_unit
    return material_demand


def forecast_inbound_material_by_day(
    observation: dict[str, Any],
    current_day: int,
    horizon: int,
) -> dict[tuple[int, str], float]:
    inbound: dict[tuple[int, str], float] = {}
    orders = flatten_status_bucket(observation.get("procurement", {}).get("orders", {}))
    for order in orders:
        status = str(order.get("status") or "").lower()
        if status in {"received", "completed", "cancelled", "canceled", "failed"}:
            continue
        material_id = order.get("material_id")
        if not material_id:
            continue
        arrival_day = int(
            to_number(
                order.get("actual_arrival_time")
                or order.get("arrival_time")
                or order.get("delivery_time"),
                -1,
            )
        )
        if current_day < arrival_day <= current_day + horizon:
            key = (arrival_day, str(material_id))
            inbound[key] = inbound.get(key, 0.0) + to_number(order.get("quantity"))
    return inbound


def forecast_committed_delivery_by_day_product(
    observation: dict[str, Any],
    current_day: int,
    horizon: int,
) -> dict[tuple[int, str], float]:
    deliveries: dict[tuple[int, str], float] = {}
    for order in flatten_sales_orders(observation):
        status = str(order.get("status") or "").lower()
        if status not in {"accepted", "in_progress"}:
            continue
        product_id = str(order.get("product_id") or "product")
        deadline = int(to_number(order.get("delivery_deadline"), current_day))
        if current_day < deadline <= current_day + horizon:
            key = (deadline, product_id)
            deliveries[key] = deliveries.get(key, 0.0) + to_number(order.get("quantity"))
    return deliveries


def build_order_fulfillment_coverage(
    observation: dict[str, Any],
    current_day: int,
    horizon: int = 7,
) -> dict[str, Any]:
    orders = flatten_sales_orders(observation)
    planned_output = forecast_planned_output_by_day_product(observation, current_day, horizon)
    finished_stock = finished_stock_by_product(observation)

    demand_by_day_product: dict[tuple[int, str], float] = {}
    product_ids = set(infer_product_ids(observation)) | set(finished_stock)
    for order in orders:
        status = normalize_order_status(order.get("status"))
        if status not in COMMITTED_ORDER_STATUSES:
            continue
        product_id = str(order.get("product_id") or "product")
        product_ids.add(product_id)
        deadline = int(to_number(order.get("delivery_deadline"), current_day))
        if current_day <= deadline <= current_day + horizon:
            demand_by_day_product[(deadline, product_id)] = (
                demand_by_day_product.get((deadline, product_id), 0.0)
                + to_number(order.get("quantity"))
            )

    if not product_ids:
        product_ids.add(str(deep_get(observation, ["production", "product_id"], "product")))

    rows: list[dict[str, Any]] = []
    for product_id in sorted(product_ids):
        cumulative_demand = 0.0
        cumulative_planned_output = 0.0
        opening_stock = finished_stock.get(product_id, 0.0)
        for offset in range(1, horizon + 1):
            future_day = current_day + offset
            cumulative_demand += demand_by_day_product.get((future_day, product_id), 0.0)
            cumulative_planned_output += planned_output.get((future_day, product_id), 0.0)
            cumulative_supply = opening_stock + cumulative_planned_output
            rows.append(
                {
                    "future_day": future_day,
                    "product_id": product_id,
                    "daily_delivery_demand": demand_by_day_product.get(
                        (future_day, product_id),
                        0.0,
                    ),
                    "cumulative_supply": cumulative_supply,
                    "cumulative_demand": cumulative_demand,
                    "coverage_gap": cumulative_supply - cumulative_demand,
                }
            )
    return {
        "title": "订单履约覆盖图",
        "latest_day_only": True,
        "current_day": current_day,
        "rows": rows,
    }


def build_raw_material_coverage(
    observation: dict[str, Any],
    current_day: int,
    horizon: int = 7,
) -> dict[str, Any]:
    planned_consumption = forecast_material_consumption_by_day_material(
        observation,
        current_day,
        horizon,
    )
    unplanned_order_demand = forecast_unplanned_order_material_demand_by_day(
        observation,
        current_day,
        horizon,
    )
    inbound_arrivals = forecast_inbound_material_by_day(observation, current_day, horizon)
    material_items = [
        item for item in latest_inventory_items(observation)
        if str(item.get("item_type") or "").lower() in {"material", "raw_material"}
    ]
    if not material_items:
        material_items = [
            item for item in latest_inventory_items(observation)
            if str(item.get("item_type") or "").lower() not in {"product", "produce_daily", "produce_completed"}
        ]
    rows: list[dict[str, Any]] = []
    for item in material_items:
        material_id = str(item.get("item_id") or "material")
        projected_stock = to_number(item.get("quantity"))
        for offset in range(1, horizon + 1):
            future_day = current_day + offset
            inbound_arrival = inbound_arrivals.get((future_day, material_id), 0.0)
            planned_use = planned_consumption.get((future_day, material_id), 0.0)
            latent_order_need = unplanned_order_demand.get((future_day, material_id), 0.0)
            total_requirement = planned_use + latent_order_need
            projected_stock += inbound_arrival - total_requirement
            rows.append(
                {
                    "future_day": future_day,
                    "material_id": material_id,
                    "projected_stock": projected_stock,
                    "inbound_arrival": inbound_arrival,
                    "planned_consumption": planned_use,
                    "latent_order_material_demand": latent_order_need,
                    "total_material_requirement": total_requirement,
                    "coverage_gap": projected_stock,
                }
            )
    return {
        "title": "原料覆盖天数/到货覆盖图",
        "latest_day_only": True,
        "current_day": current_day,
        "rows": rows,
    }


def build_warehouse_capacity_pressure(
    observation: dict[str, Any],
    current_day: int,
    horizon: int = 7,
) -> dict[str, Any]:
    inventory = observation.get("inventory", {})
    capacity = to_number(inventory.get("warehouse_capacity"))
    used_capacity = to_number(inventory.get("used_capacity"))
    if capacity <= 0:
        used_capacity = sum(to_number(item.get("quantity")) for item in latest_inventory_items(observation))
        capacity = max(used_capacity, 1.0)

    inbound_arrivals = forecast_inbound_material_by_day(observation, current_day, horizon)
    planned_output = forecast_planned_output_by_day_product(observation, current_day, horizon)
    planned_consumption = forecast_material_consumption_by_day_material(
        observation,
        current_day,
        horizon,
    )
    committed_deliveries = forecast_committed_delivery_by_day_product(
        observation,
        current_day,
        horizon,
    )
    projected_product_stock = finished_stock_by_product(observation)
    projected_used_capacity = used_capacity
    rows = []
    for offset in range(1, horizon + 1):
        future_day = current_day + offset
        inbound_total = sum(
            quantity
            for (day, _material_id), quantity in inbound_arrivals.items()
            if day == future_day
        )
        planned_output_total = sum(
            quantity
            for (day, _product_id), quantity in planned_output.items()
            if day == future_day
        )
        planned_consumption_total = sum(
            quantity
            for (day, _material_id), quantity in planned_consumption.items()
            if day == future_day
        )
        delivered_total = 0.0
        product_ids = {
            product_id
            for day, product_id in planned_output
            if day == future_day
        } | {
            product_id
            for day, product_id in committed_deliveries
            if day == future_day
        }
        for product_id in product_ids:
            projected_product_stock[product_id] = (
                projected_product_stock.get(product_id, 0.0)
                + planned_output.get((future_day, product_id), 0.0)
            )
            committed_quantity = committed_deliveries.get((future_day, product_id), 0.0)
            delivered_quantity = min(projected_product_stock.get(product_id, 0.0), committed_quantity)
            projected_product_stock[product_id] = max(
                0.0,
                projected_product_stock.get(product_id, 0.0) - delivered_quantity,
            )
            delivered_total += delivered_quantity

        projected_used_capacity += (
            inbound_total
            + planned_output_total
            - planned_consumption_total
            - delivered_total
        )
        projected_used_capacity = max(0.0, projected_used_capacity)
        rows.append(
            {
                "future_day": future_day,
                "warehouse_capacity": capacity,
                "projected_used_capacity": projected_used_capacity,
                "inbound_arrival": inbound_total,
                "planned_output": planned_output_total,
                "planned_material_consumption": planned_consumption_total,
                "committed_delivery": delivered_total,
                "capacity_gap": capacity - projected_used_capacity,
            }
        )
    return {
        "title": "仓容压力预测图",
        "latest_day_only": True,
        "current_day": current_day,
        "rows": rows,
    }


def build_cash_pressure_structure(
    all_data: dict[int, dict[str, Any]],
    available_days: list[int],
) -> dict[str, Any]:
    trend = []
    previous = None
    for day in available_days:
        finance = all_data[day].get("finance", {})
        row = {
            "day": day,
            "cash": to_number(finance.get("cash")),
            "revenue": to_number(finance.get("total_revenue")),
            "total_cost_proxy": to_number(finance.get("total_cost")),
            "net_profit": to_number(
                deep_get(finance, ["financial_indicators", "net_profit"], 0.0)
            ),
        }
        if previous is None:
            row.update({
                "cash_change": 0.0,
                "revenue_change": 0.0,
                "total_cost_change": 0.0,
                "net_profit_change": 0.0,
            })
        else:
            row.update({
                "cash_change": row["cash"] - previous["cash"],
                "revenue_change": row["revenue"] - previous["revenue"],
                "total_cost_change": row["total_cost_proxy"] - previous["total_cost_proxy"],
                "net_profit_change": row["net_profit"] - previous["net_profit"],
            })
        trend.append(row)
        previous = row
    latest_finance = all_data[available_days[-1]].get("finance", {})
    cost_structure = []
    total_cost = to_number(latest_finance.get("total_cost"))
    if total_cost:
        cost_structure.append({"category": "total_cost", "amount": total_cost})
    return {
        "title": "现金压力结构图",
        "latest_day_only": False,
        "historical_trend": trend,
        "current_state": trend[-1] if trend else {},
        "cost_structure": cost_structure,
    }


def build_demand_capacity_gap(
    observation: dict[str, Any],
    current_day: int,
    horizon: int = 7,
) -> dict[str, Any]:
    orders = flatten_sales_orders(observation)
    product_ids = set(infer_product_ids(observation))
    planned_output = forecast_planned_output_by_day_product(observation, current_day, horizon)
    demand_by_day_product: dict[tuple[int, str], float] = {}
    for order in orders:
        status = normalize_order_status(order.get("status"))
        if status not in COMMITTED_ORDER_STATUSES:
            continue
        product_id = str(order.get("product_id") or next(iter(product_ids), "product"))
        product_ids.add(product_id)
        deadline = int(to_number(order.get("delivery_deadline"), current_day))
        if current_day <= deadline <= current_day + horizon:
            demand_by_day_product[(deadline, product_id)] = (
                demand_by_day_product.get((deadline, product_id), 0.0)
                + to_number(order.get("quantity"))
            )
    available_capacity_raw = deep_get(
        observation,
        ["production", "production_lines", "available_capacity"],
        None,
    )
    free_output = to_number(available_capacity_raw, None)
    if free_output is None:
        free_output = to_number(
            deep_get(observation, ["production", "production_lines", "total_capacity"], 0.0)
        )
    rows = []
    for product_id in sorted(product_ids):
        cumulative_gap = 0.0
        for offset in range(1, horizon + 1):
            future_day = current_day + offset
            required_output = demand_by_day_product.get((future_day, product_id), 0.0)
            planned_quantity = planned_output.get((future_day, product_id), 0.0)
            capacity_gap = required_output - (planned_quantity + free_output)
            cumulative_gap += max(0.0, capacity_gap)
            rows.append(
                {
                    "future_day": future_day,
                    "product_id": product_id,
                    "required_output": required_output,
                    "planned_output": planned_quantity,
                    "free_output_equiv": free_output,
                    "optional_cumulative_gap": cumulative_gap,
                    "capacity_gap": capacity_gap,
                }
            )
    return {
        "title": "需求—产能缺口图",
        "latest_day_only": True,
        "current_day": current_day,
        "rows": rows,
    }


def deadline_bucket(days_to_deadline: int) -> str:
    if days_to_deadline < 0:
        return "overdue"
    if days_to_deadline == 0:
        return "due_today"
    if days_to_deadline <= 2:
        return "due_in_1_2_days"
    if days_to_deadline <= 5:
        return "due_in_3_5_days"
    return "due_after_5_days"


def build_order_funnel_and_aging(
    observation: dict[str, Any],
    current_day: int,
) -> dict[str, Any]:
    orders = flatten_sales_orders(observation)
    funnel: dict[str, dict[str, float]] = {}
    deadline_rows: dict[tuple[str, str], dict[str, float]] = {}
    for order in orders:
        status = normalize_order_status(order.get("status"))
        metrics = funnel.setdefault(status, {"order_count": 0, "total_quantity": 0.0})
        metrics["order_count"] += 1
        metrics["total_quantity"] += to_number(order.get("quantity"))
        if should_track_order_deadline(order):
            bucket = deadline_bucket(
                int(to_number(order.get("delivery_deadline"), current_day)) - current_day
            )
            deadline_metrics = deadline_rows.setdefault(
                (status, bucket),
                {"order_count": 0, "total_quantity": 0.0},
            )
            deadline_metrics["order_count"] += 1
            deadline_metrics["total_quantity"] += to_number(order.get("quantity"))
    source_summary = observation.get("sales", {}).get("orders_summary", {})
    return {
        "title": "订单漏斗与到期结构图",
        "latest_day_only": True,
        "current_day": current_day,
        "funnel": [
            {"status": status, "status_label": order_status_label(status), **metrics}
            for status, metrics in sorted(funnel.items())
        ],
        "commitment_deadline_distribution": [
            {
                "status": status,
                "status_label": order_status_label(status),
                "deadline_bucket": bucket,
                **metrics,
            }
            for (status, bucket), metrics in sorted(deadline_rows.items())
        ],
        "orders_summary": build_orders_summary_from_orders(orders, source_summary),
    }


def build_orders(all_data: dict[int, dict[str, Any]], available_days: list[int]) -> list[dict[str, Any]]:
    latest_day = max(available_days)
    latest_sales_data = all_data[latest_day].get("sales", {})
    sales_orders = latest_sales_data.get("sales_orders", {})
    orders: list[dict[str, Any]] = []

    for status, status_orders in sales_orders.items():
        if not isinstance(status_orders, list):
            continue
        for order in status_orders:
            orders.append(
                {
                    "order_id": order.get("order_id"),
                    "status": status,
                    "created_time": order.get("created_time"),
                    "accepted_time": order.get("accepted_time"),
                    "delivered_time": order.get("delivered_time"),
                    "product_id": order.get("product_id"),
                    "quantity": order.get("quantity"),
                    "total_amount": order.get("total_amount"),
                }
            )

    return orders


def aggregate_action_data(workspace_dir: Path, available_days: list[int]) -> dict[str, Any]:
    run_meta = find_run_meta(workspace_dir)
    single_case_run = is_single_case_run(run_meta)
    action_data: dict[str, Any] = {
        "days": [f"Day {day}" for day in available_days],
        "departments": DEPARTMENTS,
        "data": {},
        "details": {},
    }

    for day in available_days:
        action_data["data"][str(day)] = {}
        action_data["details"][str(day)] = {}

        for dept in DEPARTMENTS:
            count = 0
            details: list[dict[str, Any]] = []
            result_files = load_department_result_files(workspace_dir, dept, day)
            saw_result_file = bool(result_files)
            saw_result_action_payload = False

            for result_path, result in result_files:
                raw_result_payload = result.get("result", {})
                if isinstance(raw_result_payload, dict):
                    result_payload = raw_result_payload
                    success_actions = result_payload.get("success", [])
                    failed_actions = result_payload.get("failed", [])
                    error_actions = result_payload.get("error", [])
                else:
                    result_payload = {}
                    success_actions = []
                    failed_actions = [{
                        "message": str(raw_result_payload),
                    }]
                    error_actions = []
                action_path = get_action_path_for_result(result_path)
                action_name_fallbacks = [
                    extract_action_name(record)
                    for record in (
                        load_action_records_from_path(action_path)
                        if action_path is not None
                        else []
                    )
                ]
                action_index = 0

                if isinstance(success_actions, list):
                    for action in success_actions:
                        saw_result_action_payload = True
                        action_name = (
                            extract_action_name(action)
                            or (
                                action_name_fallbacks[action_index]
                                if action_index < len(action_name_fallbacks)
                                else ""
                            )
                            or "未知动作"
                        )
                        action_index += 1
                        if is_pass_action_name(action_name):
                            continue
                        count += 1
                        details.append(
                            {
                                "actionType": action_name,
                                "success": True,
                                "message": action.get("message", "") if isinstance(action, dict) else "",
                            }
                        )

                if isinstance(failed_actions, list):
                    for action in failed_actions:
                        saw_result_action_payload = True
                        action_name = (
                            extract_action_name(action)
                            or (
                                action_name_fallbacks[action_index]
                                if action_index < len(action_name_fallbacks)
                                else ""
                            )
                            or "未知动作"
                        )
                        action_index += 1
                        if is_pass_action_name(action_name):
                            continue
                        count += 1
                        message = ""
                        if isinstance(action, dict):
                            message = action.get("message") or action.get("error", "")
                        details.append(
                            {
                                "actionType": action_name,
                                "success": False,
                                "message": message,
                            }
                        )

                if isinstance(error_actions, list):
                    for action in error_actions:
                        saw_result_action_payload = True
                        action_name = (
                            extract_action_name(action)
                            or (
                                action_name_fallbacks[action_index]
                                if action_index < len(action_name_fallbacks)
                                else ""
                            )
                            or "未知动作"
                        )
                        action_index += 1
                        if is_pass_action_name(action_name):
                            continue
                        count += 1
                        message = ""
                        if isinstance(action, dict):
                            errors = action.get("errors")
                            if isinstance(errors, list) and errors:
                                message = json.dumps(errors, ensure_ascii=False)
                            else:
                                message = action.get("message") or action.get("error", "")
                        details.append(
                            {
                                "actionType": action_name,
                                "success": False,
                                "message": message,
                            }
                        )

            should_fallback_to_action_file = (
                single_case_run
                and count == 0
                and (
                    is_single_case_prewarm_day(run_meta, day)
                    or not saw_result_file
                    or not saw_result_action_payload
                )
            )
            if should_fallback_to_action_file:
                action_records = load_department_actions(workspace_dir, dept, day)
                error_records = load_department_errors(workspace_dir, dept, day)
                has_error = bool(error_records)
                is_prewarm = is_single_case_prewarm_day(run_meta, day)
                for record in action_records:
                    action_name = extract_action_name(record)
                    if is_pass_action_name(action_name):
                        continue
                    count += 1
                    details.append(
                        {
                            "actionType": action_name or "未知动作",
                            "success": (not has_error) if is_prewarm else False,
                            "message": "" if is_prewarm else "动作已输出但执行结果缺失",
                        }
                    )

            action_data["data"][str(day)][dept] = count
            action_data["details"][str(day)][dept] = details

    return action_data


def aggregate_error_data(workspace_dir: Path, available_days: list[int]) -> dict[str, int]:
    error_counts: dict[str, int] = {}

    for day in available_days:
        for dept in DEPARTMENTS:
            errors = load_department_errors(workspace_dir, dept, day)
            if errors:
                error_counts[dept] = error_counts.get(dept, 0) + len(errors)

    return error_counts


def build_export_payload(workspace_dir: Path) -> dict[str, Any]:
    available_days = detect_available_days(workspace_dir)
    if not available_days:
        raise RuntimeError("没有检测到可用的模拟日数据")

    all_data = load_observations(workspace_dir, available_days)
    day_labels = [f"Day {day}" for day in available_days]
    latest_day = max(available_days)
    latest_observation = all_data[latest_day]
    finance_revenue_daily = cumulative_to_period_values(
        [to_number(deep_get(all_data[day], ["finance", "total_revenue"], 0.0)) for day in available_days]
    )
    finance_profit_daily = cumulative_to_period_values(
        [
            to_number(
                deep_get(all_data[day], ["finance", "financial_indicators", "net_profit"], 0.0)
            )
            for day in available_days
        ]
    )
    sales_revenue_daily = cumulative_to_period_values(
        [
            to_number(
                deep_get(all_data[day], ["sales", "sales_metrics", "total_revenue"], 0.0)
            )
            for day in available_days
        ]
    )

    payload = {
        "meta": {
            "workspace_dir": str(workspace_dir),
            "available_days": available_days,
            "latest_day": latest_day,
            "source_html": str(workspace_dir / "visualization" / "index.html"),
        },
        "charts": {
            "financial_trend": {
                "title": "财务指标趋势（收入/利润为当日新增）",
                "days": day_labels,
                "unit": "百万元",
                "series": {
                    "cash": [
                        to_number(deep_get(all_data[day], ["finance", "cash"], 0.0)) / 1_000_000
                        for day in available_days
                    ],
                    "revenue": [value / 1_000_000 for value in finance_revenue_daily],
                    "profit": [
                        value / 1_000_000 for value in finance_profit_daily
                    ],
                },
            },
            "production_sales_trend": {
                "title": "生产与销售趋势（销售收入为当日新增）",
                "days": day_labels,
                "series": {
                    "production": [
                        to_number(
                            deep_get(all_data[day], ["production", "production_metrics", "total_production"], 0.0)
                        )
                        for day in available_days
                    ],
                    "sales_revenue_million": [
                        value / 1_000_000 for value in sales_revenue_daily
                    ],
                },
            },
            "capacity_utilization_analysis": {
                "title": "产能与利用率分析",
                "days": day_labels,
                "series": {
                    "total_capacity": [
                        to_number(
                            deep_get(all_data[day], ["production", "production_lines", "total_capacity"], 0.0)
                        )
                        for day in available_days
                    ],
                    "occupied_capacity": [
                        to_number(
                            deep_get(all_data[day], ["production", "production_lines", "occupied_capacity"], 0.0)
                        )
                        for day in available_days
                    ],
                    "available_capacity": [
                        to_number(
                            deep_get(all_data[day], ["production", "production_lines", "available_capacity"], 0.0)
                        )
                        for day in available_days
                    ],
                    "capacity_utilization_percent": [
                        to_number(
                            deep_get(all_data[day], ["production", "production_metrics", "capacity_utilization"], 0.0)
                        ) * 100
                        for day in available_days
                    ],
                },
            },
            "production_efficiency_analysis": {
                "title": "生产效率与产量分析",
                "days": day_labels,
                "series": {
                    "production_efficiency_percent": [
                        to_number(
                            deep_get(all_data[day], ["production", "production_metrics", "production_efficiency"], 0.0)
                        ) * 100
                        for day in available_days
                    ],
                    "total_production": [
                        to_number(
                            deep_get(all_data[day], ["production", "production_metrics", "total_production"], 0.0)
                        )
                        for day in available_days
                    ],
                    "total_planned": [
                        to_number(
                            deep_get(all_data[day], ["production", "production_metrics", "total_planned"], 0.0)
                        )
                        for day in available_days
                    ],
                },
            },
            "inventory_quantity_change": {
                "title": "库存数量变化",
                "days": day_labels,
                "items": build_inventory_items(all_data, available_days),
            },
            "order_tracking": {
                "title": "订单追踪",
                "latest_day_only": True,
                "latest_day": latest_day,
                "orders": build_orders(all_data, available_days),
            },
            "order_fulfillment_coverage": build_order_fulfillment_coverage(
                latest_observation,
                latest_day,
            ),
            "raw_material_coverage": build_raw_material_coverage(
                latest_observation,
                latest_day,
            ),
            "warehouse_capacity_pressure": build_warehouse_capacity_pressure(
                latest_observation,
                latest_day,
            ),
            "cash_pressure_structure": build_cash_pressure_structure(
                all_data,
                available_days,
            ),
            "demand_capacity_gap": build_demand_capacity_gap(
                latest_observation,
                latest_day,
            ),
            "order_funnel_and_aging": build_order_funnel_and_aging(
                latest_observation,
                latest_day,
            ),
            "department_action_statistics": {
                "title": "部门执行动作统计",
                **aggregate_action_data(workspace_dir, available_days),
            },
            "single_case_prewarm_execution": load_prewarm_execution_summary(workspace_dir),
            "department_error_statistics": {
                "title": "部门失败记录统计",
                "counts": aggregate_error_data(workspace_dir, available_days),
            },
        },
    }
    return payload


def export_chart_data_file(workspace_dir: Path, output_path: Path) -> dict[str, Any]:
    workspace_dir = workspace_dir.resolve()
    output_path = output_path.resolve()
    payload = build_export_payload(workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    default_workspace_dir = script_dir / "workspace"
    default_output = default_workspace_dir / "visualization" / "charts_data_export.json"

    parser = argparse.ArgumentParser(description="导出 workspace/visualization/index.html 中图表对应的 JSON 数据")
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=default_workspace_dir,
        help="CCSDKAgent workspace 根目录，默认使用当前脚本目录下的 workspace",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help="导出的 JSON 文件路径",
    )
    args = parser.parse_args()

    payload = export_chart_data_file(args.workspace_dir, args.output)

    print(f"导出完成: {args.output.resolve()}")
    print(f"模拟日数量: {len(payload['meta']['available_days'])}")


if __name__ == "__main__":
    main()
