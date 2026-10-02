import requests
import os
import sys
import json
import logging
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any, List, Dict, Optional
from agent.static_utils import StaticUtils

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.environment_config import EnvironmentConfig
from config.simulation_preset_config import (
    get_active_enterprise_configs,
    get_auto_policy_config,
    get_runtime_injection_config,
    get_static_command_payloads,
)
from persistence.case_evaluation_projection import write_case_evaluation_projection
from persistence.history_projection import write_history_projection
from persistence.multi_enterprise_projections import (
    write_enterprise_daily_metrics_projection,
    write_order_lifecycle_projection,
    write_topology_projection,
)
from persistence.run_metrics_projection import write_run_metrics_projection
from persistence.sql_mirror import (
    mirror_case_evaluation_projection,
    mirror_enterprise_daily_metrics_projection,
    mirror_history_projection,
    mirror_order_lifecycle_projection,
    mirror_run_metrics_projection,
    mirror_topology_projection,
)
from persistence.sql_mirror_runtime import get_sql_mirror_repository
from agent.export_chart_data import export_chart_data_file
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR
STATIC_COMMANDS_DIR = ROOT_DIR / "static_commands"
WORKSPACE = ROOT_DIR / "workspace_multi"
SIMULATION_RUNS_DIR = ROOT_DIR / "simulation_runs"
JSON = "action_json"
ACTIVE_ENTERPRISE_IDS = [item["id"] for item in get_active_enterprise_configs()]
logger = logging.getLogger(__name__)
ACTION_DEPARTMENTS = {"procurement", "sales", "production", "inventory", "hr"}
TRADE_DEPARTMENTS = {"procurement", "sales"}


class Config:
    BASE_URL = EnvironmentConfig.SIMULATION_API_BASE_URL
    INIT_ACTION_1 = STATIC_COMMANDS_DIR / "init_action_1.json"
    INIT_ACTION_2 = STATIC_COMMANDS_DIR / "init_action_2.json"
    INIT_ACTION_3 = STATIC_COMMANDS_DIR / "init_action_3.json"
    INIT_RESULT_1 = STATIC_COMMANDS_DIR / "init_result_1.json"
    INIT_RESULT_2 = STATIC_COMMANDS_DIR / "init_result_2.json"
    INIT_RESULT_3 = STATIC_COMMANDS_DIR / "init_result_3.json"
    DAILY_ACTION = STATIC_COMMANDS_DIR / "daily_action.json"
    DAILY_RESULT = STATIC_COMMANDS_DIR / "daily_result.json"
    DAILY_ERROR = STATIC_COMMANDS_DIR / "daily_error.json"
    TEST_ACTION = STATIC_COMMANDS_DIR / "test_action.json"
    TEST_RESULT = STATIC_COMMANDS_DIR / "test_result.json"
    TEST_ERROR = STATIC_COMMANDS_DIR / "test_error.json"

    ENTERPRISE_DIR = WORKSPACE / "enterprises"
    ENTERPRISE_IDS = list(ACTIVE_ENTERPRISE_IDS)
    SIMULATION_RUNS_DIR = SIMULATION_RUNS_DIR


class MultiTenantUtils:
    @staticmethod
    def configure_workspace(workspace_dir: Path) -> None:
        """Point legacy module globals at a per-job workspace directory."""
        global WORKSPACE
        WORKSPACE = Path(workspace_dir)
        command_dir = WORKSPACE / "_static_commands"
        Config.INIT_ACTION_1 = command_dir / "init_action_1.json"
        Config.INIT_ACTION_2 = command_dir / "init_action_2.json"
        Config.INIT_ACTION_3 = command_dir / "init_action_3.json"
        Config.INIT_RESULT_1 = command_dir / "init_result_1.json"
        Config.INIT_RESULT_2 = command_dir / "init_result_2.json"
        Config.INIT_RESULT_3 = command_dir / "init_result_3.json"
        Config.DAILY_ACTION = command_dir / "daily_action.json"
        Config.DAILY_RESULT = command_dir / "daily_result.json"
        Config.DAILY_ERROR = command_dir / "daily_error.json"
        Config.TEST_ACTION = command_dir / "test_action.json"
        Config.TEST_RESULT = command_dir / "test_result.json"
        Config.TEST_ERROR = command_dir / "test_error.json"
        Config.ENTERPRISE_DIR = WORKSPACE / "enterprises"
        Config.ENTERPRISE_IDS = [
            item["id"] for item in get_active_enterprise_configs()
        ]
        Config.SIMULATION_RUNS_DIR = SIMULATION_RUNS_DIR
        StaticUtils.configure_workspace(WORKSPACE)

    @staticmethod
    def _find_latest_observation_file(enterprise_name: str, max_round_id: Optional[int] = None) -> Optional[Path]:
        observation_dir = MultiTenantUtils._get_observation_dir(enterprise_name)
        if not observation_dir.exists():
            return None

        latest_round = -1
        latest_path: Optional[Path] = None
        for path in observation_dir.glob("observation_day*.txt"):
            stem = path.stem
            try:
                round_id = int(stem.replace("observation_day", ""))
            except ValueError:
                continue
            if max_round_id is not None and round_id > max_round_id:
                continue
            if round_id > latest_round:
                latest_round = round_id
                latest_path = path
        return latest_path

    @staticmethod
    def get_safety_stop_policy() -> Dict[str, Any]:
        runtime_config = get_runtime_injection_config()
        return runtime_config.get("safety_stop_policy") or {"enabled": False}

    @staticmethod
    def generate_next_run_id(prefix: str = "run") -> str:
        Config.SIMULATION_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        base_name = f"{prefix}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        candidate = base_name
        suffix = 1
        while (Config.SIMULATION_RUNS_DIR / candidate).exists():
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def write_workspace_run_metadata(metadata: Dict) -> str:
        target_path = WORKSPACE / "run_meta.json"
        MultiTenantUtils._write_json(target_path, metadata)
        return str(target_path)

    @staticmethod
    def clear_workspace_stop_report() -> None:
        target_path = WORKSPACE / "stop_report.json"
        try:
            if target_path.exists():
                target_path.unlink()
        except Exception:
            pass

    @staticmethod
    def write_workspace_stop_report(payload: Dict[str, Any]) -> str:
        target_path = WORKSPACE / "stop_report.json"
        MultiTenantUtils._write_json(target_path, payload)
        return str(target_path)

    @staticmethod
    def archive_current_run_snapshot(run_id: str = None, metadata: Dict = None) -> str:
        Config.SIMULATION_RUNS_DIR.mkdir(parents=True, exist_ok=True)

        base_name = run_id or datetime.now().strftime("run_%Y-%m-%d_%H%M%S")
        target_dir = Config.SIMULATION_RUNS_DIR / base_name

        suffix = 1
        while target_dir.exists():
            target_dir = Config.SIMULATION_RUNS_DIR / f"{base_name}_{suffix}"
            suffix += 1

        shutil.copytree(WORKSPACE, target_dir)

        run_meta = {
            "run_id": target_dir.name,
            "archived_at": datetime.now().isoformat(timespec="seconds"),
        }
        if metadata:
            run_meta.update(metadata)

        MultiTenantUtils._write_json(target_dir / "run_meta.json", run_meta)
        return str(target_dir)

    @staticmethod
    def is_workspace_jobs_workspace(workspace_dir: Optional[Path] = None) -> bool:
        target = Path(workspace_dir or WORKSPACE)
        try:
            return target.resolve().parent == (ROOT_DIR / "workspace_jobs").resolve()
        except Exception:
            return False

    @staticmethod
    def _get_observation_dir(enterprise_name: str) -> Path:
        return Config.ENTERPRISE_DIR / enterprise_name / "observations"

    @staticmethod
    def _write_json(path: Path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)

    @staticmethod
    def _read_json_if_exists(path: Path, default=None):
        if not path.exists():
            return {} if default is None else default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _is_valid_json_file(path: Path) -> bool:
        if not path.exists():
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)
            return True
        except (OSError, json.JSONDecodeError):
            return False

    @staticmethod
    def _safe_number(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sum_orders_quantity(sales_state: Dict[str, Any]) -> Dict[str, float]:
        orders = sales_state.get("sales_orders") or {}
        result = {"available": 0.0, "accepted": 0.0, "backlog": 0.0}
        if not isinstance(orders, dict):
            return result
        for bucket in result:
            total = 0.0
            for order in orders.get(bucket) or []:
                if isinstance(order, dict):
                    total += MultiTenantUtils._safe_number(order.get("quantity"))
            result[bucket] = total
        return result

    @staticmethod
    def _load_observation_for_analysis_fallback(
        enterprise_name: str,
        round_id: Optional[int],
    ) -> Dict[str, Any]:
        observation_path = None
        if round_id is not None:
            observation_path = (
                Config.ENTERPRISE_DIR
                / enterprise_name
                / "observations"
                / f"observation_day{round_id}.txt"
            )
        if observation_path is None or not observation_path.exists():
            observation_path = MultiTenantUtils._find_latest_observation_file(
                enterprise_name,
                max_round_id=round_id,
            )
        if observation_path is None or not observation_path.exists():
            return {}
        try:
            with open(observation_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _build_minimal_analysis_from_observation(
        enterprise_name: str,
        round_id: Optional[int],
        observation: Dict[str, Any],
    ) -> Dict[str, Any]:
        finance = observation.get("finance") or {}
        sales = observation.get("sales") or {}
        procurement = observation.get("procurement") or {}
        production = observation.get("production") or {}
        hr = observation.get("hr") or {}
        inventory = observation.get("inventory") or {}

        cash_summary = finance.get("cash_summary") or {}
        cash = MultiTenantUtils._safe_number(
            cash_summary.get("current_cash"),
            MultiTenantUtils._safe_number(finance.get("cash")),
        )
        cash_level = cash_summary.get("cash_level") or "unknown"
        order_qty = MultiTenantUtils._sum_orders_quantity(sales)
        demand_backlog = sales.get("demand_backlog") or {}
        backlog_quantity = (
            MultiTenantUtils._safe_number(demand_backlog.get("total_backlog_quantity"))
            or order_qty.get("backlog", 0.0)
            or order_qty.get("accepted", 0.0)
        )

        production_lines = production.get("production_lines") or {}
        available_capacity = MultiTenantUtils._safe_number(
            production_lines.get("available_capacity"),
            MultiTenantUtils._safe_number(production.get("available_capacity")),
        )
        total_capacity = MultiTenantUtils._safe_number(
            production_lines.get("total_capacity"),
            MultiTenantUtils._safe_number(production.get("total_capacity")),
        )

        operational_summary = procurement.get("operational_summary") or {}
        material_positions = operational_summary.get("inventory_position_by_material") or {}
        material_1_position = material_positions.get("MATERIAL_1") or {}
        material_1_available = MultiTenantUtils._safe_number(
            material_1_position.get("inventory_position"),
            MultiTenantUtils._safe_number(material_1_position.get("available")),
        )
        replenishment = procurement.get("replenishment") or {}
        pending_material_1 = MultiTenantUtils._safe_number(
            (replenishment.get("pending_by_material") or {}).get("MATERIAL_1")
        )

        department_staffing = hr.get("department_staffing") or {}
        production_staff = department_staffing.get("PRODUCTION") or department_staffing.get("production") or {}
        production_available_staff = MultiTenantUtils._safe_number(
            production_staff.get("available"),
            MultiTenantUtils._safe_number(production_staff.get("count"))
            - MultiTenantUtils._safe_number(production_staff.get("allocated")),
        )
        pending_recruitment = (
            (hr.get("recruitment_status") or {}).get("pending_by_department")
            or {}
        )
        pending_production_recruitment = MultiTenantUtils._safe_number(
            pending_recruitment.get("PRODUCTION"),
            MultiTenantUtils._safe_number(pending_recruitment.get("production")),
        )

        inventory_items = inventory.get("inventory_items") or []
        finished_goods_total = 0.0
        raw_material_total = 0.0
        for item in inventory_items if isinstance(inventory_items, list) else []:
            if not isinstance(item, dict):
                continue
            qty = MultiTenantUtils._safe_number(item.get("quantity"))
            if item.get("item_type") == "product":
                finished_goods_total += qty
            elif item.get("item_type") == "raw_material":
                raw_material_total += qty

        summary = (
            "根据当前运行状态生成保底低频分析："
            f"现金={cash:.2f}({cash_level})；"
            f"可用订单量={order_qty.get('available', 0.0):.2f}，已接/积压需求={backlog_quantity:.2f}；"
            f"MATERIAL_1库存位点={material_1_available:.2f}，在途={pending_material_1:.2f}；"
            f"可用产能={available_capacity:.2f}/总产能={total_capacity:.2f}；"
            f"PRODUCTION可用人手={production_available_staff:.2f}，待招聘={pending_production_recruitment:.2f}；"
            f"成品库存={finished_goods_total:.2f}，原料库存={raw_material_total:.2f}。"
        )

        return {
            "enterprise_name": enterprise_name,
            "round_id": int(round_id or 0),
            "enterprise_summarys": summary,
            "department_targets": {
                "sales": {
                    "target": "基于真实非零订单、交期、成品库存和近期待产判断是否接单；若需求不足且现金与履约能力允许，再考虑市场开发。",
                    "evaluation": "sales_action.json 必须引用真实订单或说明当前无可履约真实需求；不得把零数量或无金额订单当作增长目标。",
                    "reason": "销售动作应由订单真实性、库存覆盖、交付期限和现金影响共同决定。",
                },
                "procurement": {
                    "target": "基于 MATERIAL_1 库存位点、在途补货、配方需求和已接订单/backlog 判断是否采购；已有覆盖时避免重复采购。",
                    "evaluation": "procurement_action.json 的采购数量、物料和物流方式必须可由库存位点、供应商、在途记录或生产恢复需求解释。",
                    "reason": "采购动作应解决真实原料覆盖缺口，而不是无条件补货。",
                },
                "production": {
                    "target": "基于真实订单/backlog、原料可行量、可用产能、产线状态和可用生产人手判断是否排产或扩线。",
                    "evaluation": "production_action.json 必须说明原料、人手和产能均支持动作；若任一硬条件不足，应说明阻断并等待。",
                    "reason": "生产动作需要同时满足需求、原料、人手和产能约束。",
                },
                "hr": {
                    "target": "基于各部门员工数量、空闲人数、利用率、待招聘和人员不足失败记录判断是否招聘。",
                    "evaluation": "hr_action.json 只有在真实人员缺口或执行失败显示人手阻断时输出招聘；已有待招聘覆盖时避免重复招聘。",
                    "reason": "HR 动作应由真实人员状态触发。",
                },
            },
            "fallback_analysis": {
                "enabled": True,
                "source": "observation_state",
                "generated_reason": "analyst output unavailable; generated minimal state-based analysis",
            },
        }

    @staticmethod
    def _write_fallback_enterprise_analysis(
        enterprise_name: str,
        round_id: Optional[int] = None,
    ) -> bool:
        run_meta = MultiTenantUtils._read_json_if_exists(WORKSPACE / "run_meta.json", {})
        scenario_config = run_meta.get("scenario_config") or {}
        runtime_injection = scenario_config.get("runtime_injection") or {}
        single_case_policy = (
            run_meta.get("single_enterprise_case")
            or scenario_config.get("single_enterprise_case")
            or runtime_injection.get("single_enterprise_case_policy")
            or {}
        )
        single_enterprise_run = (
            str(run_meta.get("orchestrator") or "") == "single_enterprise"
            or (
                isinstance(single_case_policy, dict)
                and bool(single_case_policy.get("enabled"))
            )
        )
        long_run_policy = runtime_injection.get("long_run_experiment_policy") or {}
        resilient_multi_enterprise_run = bool(
            str(run_meta.get("orchestrator") or "multi_enterprise") == "multi_enterprise"
            and long_run_policy.get("enabled")
            and long_run_policy.get("continue_on_agent_failure")
        )
        if not single_enterprise_run and not resilient_multi_enterprise_run:
            return False
        observation = MultiTenantUtils._load_observation_for_analysis_fallback(
            enterprise_name,
            round_id,
        )
        if not observation:
            return False
        payload = MultiTenantUtils._build_minimal_analysis_from_observation(
            enterprise_name,
            round_id,
            observation,
        )
        analysis_file = Config.ENTERPRISE_DIR / enterprise_name / "analysis.json"
        MultiTenantUtils._write_json(analysis_file, payload)
        logger.warning(
            "Generated fallback analysis.json for %s at round %s from observation state "
            "(single_enterprise=%s, resilient_multi_enterprise=%s).",
            enterprise_name,
            round_id,
            single_enterprise_run,
            resilient_multi_enterprise_run,
        )
        return True

    @staticmethod
    def _expected_action_names_for_dept(dept: str) -> set:
        common = {"action_pass"}
        mapping = {
            "production": common
            | {
                "build_production_line",
                "create_production_plan",
                "interrupt_production_plan",
                "resume_production_plan",
                "cancel_production_plan",
            },
            "sales": common
            | {
                "accept_order",
                "reject_order",
                "accept_proposal_order",
                "reject_proposal_order",
                "develop_market",
                "adjust_sales_demand",
            },
            "procurement": common
            | {
                "create_purchase_order",
                "create_replenishment_order",
                "create_purchase_demand",
                "accept_proposal_order",
                "reject_proposal_order",
                "cancel_order",
            },
            "inventory": common | {"expand_warehouse"},
            "hr": common | {"handle_recruitment"},
        }
        return mapping.get(dept, common)

    @staticmethod
    def _has_any_param(action_param: Dict[str, Any], keys: List[str]) -> bool:
        return any(action_param.get(key) not in (None, "") for key in keys)

    @staticmethod
    def _action_has_required_params(action_name: str, action_param: Any) -> bool:
        if action_name == "action_pass":
            return isinstance(action_param, (dict, str))
        if not isinstance(action_param, dict):
            return False

        required_by_action = {
            "accept_order": ["order_id"],
            "reject_order": ["order_id"],
            "accept_proposal_order": ["proposal_id"],
            "reject_proposal_order": ["proposal_id"],
            "create_production_plan": ["product_id", "quantity", "daily_capacity"],
            "build_production_line": ["line_type"],
            "develop_market": ["market_type"],
            "adjust_sales_demand": ["product_id", "quantity"],
            "create_purchase_order": ["material_id", "quantity"],
            "create_replenishment_order": ["material_id"],
            "create_purchase_demand": ["material_id", "quantity"],
            "cancel_order": ["order_id"],
            "handle_recruitment": ["department", "num_people"],
            "expand_warehouse": ["size"],
        }
        for key in required_by_action.get(action_name, []):
            if action_param.get(key) in (None, ""):
                return False

        if action_name in {
            "interrupt_production_plan",
            "resume_production_plan",
            "cancel_production_plan",
        }:
            return MultiTenantUtils._has_any_param(
                action_param,
                ["plan_id", "production_plan_id", "production_id"],
            )
        return True

    @staticmethod
    def _normalize_action_payload_shape(payload: Any) -> Any:
        if isinstance(payload, dict) and isinstance(payload.get("action"), dict):
            return [payload]
        return payload

    @staticmethod
    def _is_valid_action_payload(payload: Any, dept: str) -> bool:
        payload = MultiTenantUtils._normalize_action_payload_shape(payload)
        if not isinstance(payload, list) or not payload:
            return False

        allowed_actions = MultiTenantUtils._expected_action_names_for_dept(dept)
        for item in payload:
            if not isinstance(item, dict):
                return False

            action = item.get("action")
            if not isinstance(action, dict):
                return False

            action_name = action.get("action_name")
            if not isinstance(action_name, str) or not action_name.strip():
                return False
            if action_name not in allowed_actions:
                return False

            if not isinstance(item.get("module_type"), str) or not item.get("module_type").strip():
                return False
            if not isinstance(item.get("executor_id"), str) or not item.get("executor_id").strip():
                return False
            if not isinstance(item.get("action_reason"), str) or not item.get("action_reason").strip():
                return False
            if not MultiTenantUtils._action_has_required_params(action_name, action.get("action_param")):
                return False

        return True

    @staticmethod
    def _is_valid_action_file(path: Path, dept: str) -> bool:
        if not path.exists():
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            return MultiTenantUtils._is_valid_action_payload(payload, dept)
        except (OSError, json.JSONDecodeError):
            return False

    @staticmethod
    def _normalize_action_file_if_possible(path: Path, dept: str) -> bool:
        if not path.exists():
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False

        normalized = MultiTenantUtils._normalize_action_payload_shape(payload)
        if normalized is payload:
            return MultiTenantUtils._is_valid_action_payload(payload, dept)
        if not MultiTenantUtils._is_valid_action_payload(normalized, dept):
            return False

        MultiTenantUtils._write_json(path, normalized)
        return True

    @staticmethod
    def _summarize_error_files(
        error_files: List[str],
        *,
        final_action_valid: bool,
        final_result_present: bool,
    ) -> Dict[str, Any]:
        """Classify error artifacts without weakening the strict integrity gate."""
        recoverable_files: List[str] = []
        stale_trade_files: List[str] = []
        validation_failed_files: List[str] = []
        for file_path in error_files:
            path = Path(file_path)
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                content = ""
            lowered = content.lower()
            if "validation_failed" in lowered or "validation failed" in lowered:
                validation_failed_files.append(file_path)
            if (
                "expired" in lowered
                or "superseded" in lowered
                or "已完成采购侧响应" in content
                or "已完成销售侧响应" in content
                or "已完成" in content and "响应" in content
            ):
                stale_trade_files.append(file_path)
            if final_action_valid and final_result_present:
                recoverable_files.append(file_path)
        return {
            "total": len(error_files),
            "recoverable_count": len(recoverable_files),
            "stale_trade_count": len(stale_trade_files),
            "validation_failed_count": len(validation_failed_files),
            "recoverable_files": recoverable_files,
            "stale_trade_files": stale_trade_files,
            "validation_failed_files": validation_failed_files,
            "strict_gate_note": "round_integrity.ok still requires error_files == 0.",
        }

    @staticmethod
    def _get_enterprise_order_count(round_id: int, enterprise_id: str) -> int:
        exchange_path = WORKSPACE / "public" / "exchange" / f"day{round_id}" / "exchange.json"
        payload = MultiTenantUtils._read_json_if_exists(exchange_path, {})
        exchanges = ((payload.get("data") or {}).get("exchanges") or {})
        order_count = 0
        for exchange_info in exchanges.values():
            for order in (((exchange_info.get("orders") or {}).get("list")) or []):
                buyer = order.get("buyer_company_id")
                seller = order.get("seller_company_id")
                if buyer == enterprise_id or seller == enterprise_id:
                    order_count += 1
        return order_count

    @staticmethod
    def _get_enterprise_metric(round_id: int, enterprise_id: str, metric_name: str) -> Optional[float]:
        finance_path = (
            WORKSPACE
            / "enterprises"
            / enterprise_id
            / "department"
            / "finance"
            / f"day{round_id}"
            / "finance.json"
        )
        payload = MultiTenantUtils._read_json_if_exists(finance_path, {})
        self_state = payload.get("self_state") or {}
        financial_indicators = self_state.get("financial_indicators") or {}
        value = financial_indicators.get(metric_name)
        if value is None:
            value = self_state.get(metric_name)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def build_safety_stop_reason(round_id: int, enterprise_ids: List[str]) -> Optional[Dict[str, Any]]:
        policy = MultiTenantUtils.get_safety_stop_policy()
        if not policy.get("enabled"):
            return None

        min_round = int(policy.get("min_round_to_evaluate", 0) or 0)
        if round_id < min_round:
            return None

        no_order_window = max(1, int(policy.get("consecutive_no_order_rounds", 1) or 1))
        decline_window = max(1, int(policy.get("consecutive_decline_rounds", 1) or 1))
        metric_name = str(policy.get("economic_metric") or "net_profit")
        require_negative_metric = bool(policy.get("require_negative_metric", True))
        metric_floor = float(policy.get("metric_floor", 0.0) or 0.0)
        target_enterprises = list(policy.get("target_enterprise_ids") or enterprise_ids)

        earliest_round = round_id - max(no_order_window, decline_window)
        if earliest_round < 0:
            return None

        for enterprise_id in target_enterprises:
            order_history = []
            for day in range(round_id - no_order_window + 1, round_id + 1):
                order_history.append(
                    {
                        "round_id": day,
                        "order_count": MultiTenantUtils._get_enterprise_order_count(day, enterprise_id),
                    }
                )
            no_order_streak = all(item["order_count"] <= 0 for item in order_history)
            if not no_order_streak:
                continue

            metric_history = []
            metric_missing = False
            for day in range(round_id - decline_window, round_id + 1):
                metric_value = MultiTenantUtils._get_enterprise_metric(day, enterprise_id, metric_name)
                if metric_value is None:
                    metric_missing = True
                    break
                metric_history.append({"round_id": day, "value": metric_value})
            if metric_missing or len(metric_history) < decline_window + 1:
                continue

            metric_declining = all(
                metric_history[idx]["value"] > metric_history[idx + 1]["value"]
                for idx in range(len(metric_history) - 1)
            )
            if not metric_declining:
                continue

            current_metric = metric_history[-1]["value"]
            if require_negative_metric and current_metric > metric_floor:
                continue

            return {
                "triggered": True,
                "round_id": round_id,
                "enterprise_id": enterprise_id,
                "reason_code": "NO_ORDER_AND_ECONOMIC_DECLINE",
                "message": (
                    f"{enterprise_id} 已连续 {no_order_window} 轮未获得交易订单，且 {metric_name} 连续 "
                    f"{decline_window} 轮下滑，当前值 {current_metric:.2f}。"
                ),
                "policy": policy,
                "order_history": order_history,
                "metric_history": metric_history,
            }

        return None

    @staticmethod
    def _safe_number(value, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _count_insufficient_staff_failures(enterprise_name: str, dept: str, round_id: int) -> int:
        if round_id <= 0:
            return 0
        error_dir = Config.ENTERPRISE_DIR / enterprise_name / "department" / dept / f"day{round_id - 1}"
        if not error_dir.exists():
            return 0

        count = 0
        for error_file in error_dir.glob(f"{dept}_error*.json"):
            payload = MultiTenantUtils._read_json_if_exists(error_file, {})
            flattened = json.dumps(payload, ensure_ascii=False)
            if "INSUFFICIENT_STAFF" in flattened or "人手不足" in flattened:
                count += 1
        return count

    @staticmethod
    def sync_static_command_files():
        payloads = get_static_command_payloads()
        command_path_map = {
            "init_action_1": Config.INIT_ACTION_1,
            "init_action_2": Config.INIT_ACTION_2,
            "init_action_3": Config.INIT_ACTION_3,
            "daily_action": Config.DAILY_ACTION,
        }
        for key, path in command_path_map.items():
            MultiTenantUtils._write_json(path, payloads[key])

    @staticmethod
    def handle_enterprises_init() -> str:
        """
        执行所有企业的基础信息初始化动作
        """
        MultiTenantUtils.sync_static_command_files()
        # 分批执行，要先注册员工，再执行后续初始化操作
        StaticUtils.execute_action(Config.INIT_ACTION_1, Config.INIT_RESULT_1, "init")
        StaticUtils.execute_action(Config.INIT_ACTION_2, Config.INIT_RESULT_2, "init")
        StaticUtils.execute_action(Config.INIT_ACTION_3, Config.INIT_RESULT_3, "init")


    @staticmethod
    def handle_test() -> str:
        """
        执行所有企业的测试动作
        """
        StaticUtils.execute_action(Config.TEST_ACTION, Config.TEST_RESULT, "test", Config.TEST_ERROR,department="Procurement")

    @staticmethod
    def handle_enterprise_daily() -> str:
        """
        执行所有企业的日常动作
        """
        MultiTenantUtils.sync_static_command_files()
        StaticUtils.execute_action(Config.DAILY_ACTION, Config.DAILY_RESULT, "daily", Config.DAILY_ERROR)

    @staticmethod
    def save_enterprise_observations(enterprise_name: str = None) -> str:
        """
        执行企业的全局状态信息
        """
        target_enterprises = Config.ENTERPRISE_IDS if enterprise_name is None else [enterprise_name]
        for current_enterprise_name in target_enterprises:
            if current_enterprise_name not in Config.ENTERPRISE_IDS:
                continue
            StaticUtils.save_observation(
                MultiTenantUtils._get_observation_dir(current_enterprise_name),
                current_enterprise_name,
            )
        
    @staticmethod
    def handle_enterprises_observations(round_id: int, enterprise_name: str) -> str:
        """
        执行所有企业的全局状态信息处理
        """
        filename = f"observation_day{round_id}.txt"
        observation_path = WORKSPACE / "enterprises" / enterprise_name / "observations" / filename
        if not observation_path.exists():
            MultiTenantUtils.save_enterprise_observations(enterprise_name)
            observation_path = WORKSPACE / "enterprises" / enterprise_name / "observations" / filename
        if not observation_path.exists():
            fallback_path = MultiTenantUtils._find_latest_observation_file(
                enterprise_name,
                max_round_id=round_id - 1,
            )
            if fallback_path is not None:
                logging.getLogger(__name__).warning(
                    "Observation file missing for %s day%s, fallback to %s",
                    enterprise_name,
                    round_id,
                    fallback_path.name,
                )
                observation_path = fallback_path
            else:
                raise FileNotFoundError(
                    f"Observation file not found for {enterprise_name} day{round_id}, and no fallback observation is available."
                )
        analysis_file =f"enterprises/{enterprise_name}/analysis.json"
        output_file = f"enterprises/{enterprise_name}/department"
        StaticUtils.handle_observation(input_file=observation_path, output_file = output_file, workspace = WORKSPACE, analysis_file = analysis_file, round_id=round_id)

    @staticmethod
    def execute_enterprise_dept_action(round_id: int, retry_time: int, dept: str, enterprise_name: str):
        input_file = Config.ENTERPRISE_DIR / enterprise_name / "department" / dept / f"day{round_id}" / f"{dept}_action.json"
        output_file = Config.ENTERPRISE_DIR / enterprise_name / "department" / dept / f"day{round_id}" / f"{dept}_result.json"
        error_file = Config.ENTERPRISE_DIR / enterprise_name / "department" / dept / f"day{round_id}" / f"{dept}_error.json"
        blackboard_path = Config.ENTERPRISE_DIR / enterprise_name / "department" / "blackboard" / f"day{round_id}" / "blackboard.json"
        result = StaticUtils.execute_dept_action(
            input_file = input_file,
            output_file = output_file,
            error_file = error_file,
            department = dept,
            round_id=round_id,
            retry_time=retry_time,
            enterprise_name= enterprise_name,
            blackboard_path = blackboard_path
        )
        return result

    @staticmethod
    def generate_dept_auto_action(dept: str, enterprise_name: str, round_id: int):
        # TODO 整合数据库后根据上一轮在共享黑板中收到的需求来确认动作 
        if dept == "hr":
            MultiTenantUtils.generate_hr_action(enterprise_name,round_id)
        elif dept == "inventory":
            MultiTenantUtils.generate_inventory_action(enterprise_name,round_id)
        MultiTenantUtils.execute_enterprise_dept_action(round_id, 0, dept, enterprise_name)
        
    @staticmethod
    def generate_hr_action(enterprise_name: str, round_id: int):
        input_file = Config.ENTERPRISE_DIR / enterprise_name / "department" / "hr" / f"day{round_id}" / f"hr.json"
        output_file = Config.ENTERPRISE_DIR / enterprise_name / "department" / "hr" / f"day{round_id}" / f"hr_action.json"
        policy = get_auto_policy_config()["hr"]
        hr_data = MultiTenantUtils._read_json_if_exists(input_file, {})
        blackboard_path = Config.ENTERPRISE_DIR / enterprise_name / "department" / "blackboard" / f"day{round_id}" / "blackboard.json"
        blackboard = MultiTenantUtils._read_json_if_exists(blackboard_path, {})

        self_state = hr_data.get("self_state") or {}
        staffing_map = {}
        for employee in self_state.get("employees") or []:
            department = employee.get("department")
            if not department:
                continue
            count = int(employee.get("count", 0) or 0)
            allocated = int(employee.get("allocated", 0) or 0)
            available = max(0, count - allocated)
            utilization = MultiTenantUtils._safe_number(employee.get("utilization"))
            staffing_map[department] = {
                "count": count,
                "allocated": allocated,
                "available": available,
                "utilization": utilization,
            }

        detailed_staffing = self_state.get("department_staffing") or {}
        for department, data in detailed_staffing.items():
            if department not in staffing_map:
                count = int(data.get("count", 0) or 0)
                allocated = int(data.get("allocated", 0) or 0)
                staffing_map[department] = {
                    "count": count,
                    "allocated": allocated,
                    "available": max(0, int(data.get("available", count - allocated) or 0)),
                    "utilization": MultiTenantUtils._safe_number(data.get("utilization")),
                }

        pending_by_department = (
            (self_state.get("recruitment_status") or {}).get("pending_by_department")
            or {}
        )
        blackboard_departments = (blackboard.get("departments") or {})

        def calc_procurement_pressure() -> Dict[str, object]:
            procurement = blackboard_departments.get("procurement") or {}
            inventory_positions = procurement.get("inventory_position_by_material") or {}
            negative_items = [
                item_id
                for item_id, item in inventory_positions.items()
                if MultiTenantUtils._safe_number(item.get("inventory_position")) < 0
            ]
            pending_total = sum(
                MultiTenantUtils._safe_number(quantity)
                for quantity in (procurement.get("pending_by_material") or {}).values()
            )
            trigger = bool(negative_items) or pending_total > policy["procurement_pending_quantity_trigger"]
            return {
                "trigger": trigger,
                "severity": len(negative_items) + (1 if pending_total > policy["procurement_pending_quantity_trigger"] else 0),
                "reason": f"负库存位物料 {len(negative_items)} 个, 在途待收总量 {int(pending_total)}"
            }

        def calc_sales_pressure() -> Dict[str, object]:
            sales = blackboard_departments.get("sales") or {}
            backlog_total = sum(
                MultiTenantUtils._safe_number(item.get("backlog_quantity"))
                for item in (sales.get("backlog_by_product") or {}).values()
            )
            fill_rate = MultiTenantUtils._safe_number(sales.get("fill_rate"), 1.0)
            trigger = backlog_total > policy["sales_backlog_trigger"] or fill_rate < policy["sales_fill_rate_trigger"]
            return {
                "trigger": trigger,
                "severity": (1 if backlog_total > policy["sales_backlog_trigger"] else 0) + (1 if fill_rate < policy["sales_fill_rate_trigger"] else 0),
                "reason": f"backlog={int(backlog_total)}, fill_rate={fill_rate:.2f}"
            }

        def calc_production_pressure() -> Dict[str, object]:
            production = blackboard_departments.get("production") or {}
            total_plans = int(production.get("total_production_plans", 0) or 0)
            available_capacity = MultiTenantUtils._safe_number(production.get("available_capacity"))
            trigger = total_plans >= policy["production_plan_trigger"] and available_capacity <= 0
            return {
                "trigger": trigger,
                "severity": total_plans if trigger else 0,
                "reason": f"在制计划 {total_plans} 条, 可用产能 {available_capacity:.0f}"
            }

        def calc_inventory_pressure() -> Dict[str, object]:
            inventory = blackboard_departments.get("inventory") or {}
            capacity_utilization = MultiTenantUtils._safe_number(inventory.get("capacity_utilization"))
            alert_count = len((inventory.get("policy_alerts") or {}).get("below_reorder_point_items") or [])
            trigger = (
                capacity_utilization >= policy["inventory_support_threshold"]
                or alert_count >= policy["inventory_alert_count_trigger"]
            )
            return {
                "trigger": trigger,
                "severity": alert_count + (1 if capacity_utilization >= policy["inventory_support_threshold"] else 0),
                "reason": f"仓容利用率 {capacity_utilization:.2f}, 库存告警 {alert_count} 项"
            }

        pressure_by_department = {
            "PROCUREMENT": calc_procurement_pressure(),
            "SALES": calc_sales_pressure(),
            "PRODUCTION": calc_production_pressure(),
            "INVENTORY": calc_inventory_pressure(),
        }

        actions = []
        for dept, staffing in staffing_map.items():
            if dept == "HR" or dept == "FINANCE":
                continue

            count = staffing.get("count", 0)
            available = staffing.get("available", 0)
            utilization = staffing.get("utilization", 0.0)
            pending_recruits = int(pending_by_department.get(dept, 0) or 0)
            prior_failures = MultiTenantUtils._count_insufficient_staff_failures(enterprise_name, dept.lower(), round_id)
            pressure = pressure_by_department.get(dept, {"trigger": False, "severity": 0, "reason": "无额外压力"})

            recruit_need = 0
            reason_codes = []
            if utilization >= policy["recruit_trigger_threshold"]:
                recruit_need = max(
                    recruit_need,
                    max(policy["min_recruit"], int(max(count, 1) * policy["recruit_ratio"]))
                )
                reason_codes.append(f"UTILIZATION_HIGH:{utilization:.2f}")

            if utilization >= policy["severe_utilization_threshold"]:
                recruit_need = max(recruit_need, policy["min_recruit"] + 1)
                reason_codes.append(f"UTILIZATION_SEVERE:{utilization:.2f}")

            if pressure.get("trigger") and available <= policy["available_worker_floor"]:
                recruit_need = max(
                    recruit_need,
                    policy["min_recruit"] + int(pressure.get("severity", 0) > 1)
                )
                reason_codes.append(f"FORWARD_PRESSURE:{pressure.get('reason')}")

            if prior_failures > 0:
                recruit_need = max(
                    recruit_need,
                    policy["min_recruit"] + min(prior_failures, policy["failure_recruit_boost"])
                )
                reason_codes.append(f"PREV_STAFF_FAILURES:{prior_failures}")

            recruit_need = max(0, recruit_need - pending_recruits)
            recruit_need = min(policy["max_recruit"], recruit_need)

            if recruit_need <= 0:
                continue

            actions.append({
                "action": {
                    "action_name": "handle_recruitment",
                    "action_param": {
                        "department": dept,
                        "num_people": recruit_need
                    }
                },
                "action_reason": (
                    f"{dept}部门触发前视化招聘，建议补员 {recruit_need} 人；"
                    f"当前人数={count}，空闲={available}，利用率={utilization:.2f}；"
                    f"原因={', '.join(reason_codes) if reason_codes else pressure.get('reason', '无')}"
                ),
                "module_type": "HRManager",
                "executor_id": enterprise_name
            })
        
        if not actions:
            actions.append({
                "action": {
                    "action_name": "action_pass",
                    "action_param": "当前无显著用工压力，暂无新增招聘"
                },
                "action_reason": "当前利用率、压力信号和上一轮人手失败记录均未触发招聘阈值",
                "module_type": "HRManager",
                "executor_id": enterprise_name
        })
        
        hr_action = actions
        # 确保输出目录存在
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入 output_file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(hr_action, f, indent=2, ensure_ascii=False)

    @staticmethod
    def generate_inventory_action(enterprise_name: str, round_id: int):
        input_file = Config.ENTERPRISE_DIR / enterprise_name / "department" / "inventory" / f"day{round_id}" / f"inventory.json"
        output_file = Config.ENTERPRISE_DIR / enterprise_name / "department" / "inventory" / f"day{round_id}" / f"inventory_action.json"
        
        with open(input_file, 'r', encoding='utf-8') as f:
            inventory_data = json.load(f)
        
        used_capacity = 0
        warehouse_capacity = 0
        inventory_utilization = 0.0
        actions = []
        policy = get_auto_policy_config()["inventory"]
        low_stock_items = []
        below_reorder_point_items = []
        policy_by_item = {}
        
        if 'self_state' in inventory_data:
            self_state = inventory_data['self_state']
            used_capacity = self_state.get('used_capacity', 0)
            warehouse_capacity = self_state.get('warehouse_capacity', 0)
            policy_by_item = self_state.get('policy_by_item') or {}
            policy_alerts = (inventory_data.get('blackboard') or {}).get('departments', {}).get('inventory', {}).get('policy_alerts') or {}
            low_stock_items = policy_alerts.get('low_stock_items') or [
                item_id for item_id, item in policy_by_item.items()
                if item.get("is_low_stock")
            ]
            below_reorder_point_items = policy_alerts.get('below_reorder_point_items') or [
                item_id for item_id, item in policy_by_item.items()
                if item.get("is_below_reorder_point")
            ]
            
            if warehouse_capacity > 0:
                inventory_utilization = used_capacity / warehouse_capacity
            
            if inventory_utilization > policy["expand_trigger_threshold"]:
                increment = int(used_capacity * policy["expand_ratio"])
                options = policy["expansion_options"]
                increment = min(options, key=lambda x: abs(x - increment))
                if increment == 0 and used_capacity > 0:
                    increment = policy["min_expansion_if_nonzero"]
                actions.append({
                    "action": {
                        "action_name": "expand_warehouse",
                        "action_param": {
                            "size": increment
                        }
                    },
                    "action_reason": (
                        f"库存利用率过高({inventory_utilization:.2%})，需要增加{increment}容量。"
                        f"当前低库存项: {', '.join(low_stock_items) if low_stock_items else '无'}；"
                        f"低于再订购点项: {', '.join(below_reorder_point_items) if below_reorder_point_items else '无'}"
                    ),
                    "module_type": "InventoryManager",
                    "executor_id": enterprise_name
                })
            else:
                low_stock_reason = ""
                if low_stock_items or below_reorder_point_items:
                    low_stock_reason = (
                        f" 已识别低库存项({', '.join(low_stock_items) if low_stock_items else '无'})"
                        f" 与再订购点告警({', '.join(below_reorder_point_items) if below_reorder_point_items else '无'})，"
                        "当前优先交由采购/生产链路处理。"
                    )
                actions.append({
                    "action": {
                        "action_name": "action_pass",
                        "action_param": f"库存利用率正常，无需增加容量。{low_stock_reason}".strip()
                    },
                    "action_reason": f"库存利用率正常，无需增加容量。{low_stock_reason}".strip(),
                    "module_type": "InventoryManager",
                    "executor_id": enterprise_name
                })
        
        if not actions:
            actions.append({
                "action": {
                    "action_name": "action_pass",
                    "action_param": "无法获取库存数据"
                },
                "action_reason": "无法获取库存数据",
                "module_type": "InventoryManager",
                "executor_id": enterprise_name
            })
        
        inventory_action = actions
        
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(inventory_action, f, indent=2, ensure_ascii=False)

    @staticmethod
    def file_check_analysis(enterprise_name: str, log_missing: bool = False):
        analysis_file = Config.ENTERPRISE_DIR / enterprise_name / "analysis.json"
        has_file = os.path.exists(analysis_file)
        if log_missing and not has_file:
            logger.debug("analysis file not ready: %s", analysis_file)
        return has_file

    @staticmethod
    def ensure_enterprise_analysis_file(
        enterprise_name: str,
        round_id: Optional[int] = None,
        require_round_id: Optional[int] = None,
        allow_archive_fallback: bool = True,
    ) -> bool:
        """
        确保企业根目录下存在可供 observation / skill 读取的 analysis.json。

        当本轮未运行 analyst 时，会从最近一次归档 records/day*/analysis.json 回填到根目录，
        让 analysis 退回低频战略背景而不是每轮强制重算。
        正式蛛网C3在分析轮可指定 require_round_id，并关闭归档回填，防止旧报告
        在 Analyst 超时后被误当作当轮结果。
        """
        enterprise_dir = Config.ENTERPRISE_DIR / enterprise_name
        analysis_file = enterprise_dir / "analysis.json"
        if MultiTenantUtils._is_valid_json_file(analysis_file):
            if require_round_id is None:
                return True
            payload = MultiTenantUtils._read_json_if_exists(
                analysis_file,
                {},
            )
            try:
                payload_round_id = int(payload.get("round_id"))
            except (AttributeError, TypeError, ValueError):
                payload_round_id = None
            if payload_round_id == int(require_round_id):
                return True
            logger.warning(
                "analysis.json is stale for %s: expected round %s, got %s",
                enterprise_name,
                require_round_id,
                payload_round_id,
            )
        if analysis_file.exists():
            logger.warning(
                "analysis.json exists but is invalid for %s: %s",
                enterprise_name,
                analysis_file,
            )

        if not allow_archive_fallback:
            return False

        archive_candidates = sorted(
            enterprise_dir.glob("records/day*/analysis.json"),
            key=lambda path: int(path.parent.name.removeprefix("day")),
        )
        valid_archive_candidates = [
            path for path in archive_candidates
            if MultiTenantUtils._is_valid_json_file(path)
        ]
        if not valid_archive_candidates:
            return MultiTenantUtils._write_fallback_enterprise_analysis(
                enterprise_name,
                round_id,
            )

        analysis_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(valid_archive_candidates[-1], analysis_file)
        return True

    @staticmethod
    def file_check_department(enterprise_name: str, dept: str, round_id: int, log_missing: bool = False):
        department_file = Config.ENTERPRISE_DIR / enterprise_name / "department" / dept / f"day{round_id}" / f"{dept}_action.json"
        has_file = os.path.exists(department_file)
        if log_missing and not has_file:
            logger.debug("department action file not ready: %s", department_file)
        return has_file

    @staticmethod
    def _candidate_action_files(day_dir: Path, dept: str) -> List[Path]:
        candidates = [day_dir / f"{dept}_action.json"]
        if dept in TRADE_DEPARTMENTS:
            candidates.append(day_dir / f"pre_{dept}_action.json")
        return candidates

    @staticmethod
    def _candidate_result_files(day_dir: Path, dept: str) -> List[Path]:
        candidates = [day_dir / f"{dept}_result.json"]
        if dept in TRADE_DEPARTMENTS:
            candidates.append(day_dir / f"pre_{dept}_result.json")
        return candidates

    @staticmethod
    def _first_existing_valid_json(candidates: List[Path], dept: Optional[str] = None) -> Dict[str, Any]:
        existing = [path for path in candidates if path.exists()]
        if dept:
            valid = [path for path in existing if MultiTenantUtils._is_valid_action_file(path, dept)]
        else:
            valid = [path for path in existing if MultiTenantUtils._is_valid_json_file(path)]
        return {
            "exists": bool(existing),
            "valid": bool(valid),
            "path": str(valid[0] if valid else existing[0]) if existing else "",
            "candidates": [str(path) for path in candidates],
        }

    @staticmethod
    def _workspace_enterprise_configs() -> Dict[str, Dict[str, Any]]:
        run_meta = MultiTenantUtils._read_json_if_exists(WORKSPACE / "run_meta.json", {})
        scenario_config = run_meta.get("scenario_config") or {}
        enterprise_configs = scenario_config.get("enterprise_configs") or run_meta.get("enterprise_configs") or []
        if not enterprise_configs:
            enterprise_configs = get_active_enterprise_configs()
        configs = {
            str(item.get("id")): dict(item)
            for item in enterprise_configs
            if item.get("id")
        }
        agent_layout = (
            scenario_config.get("agent_enterprise_layout")
            or run_meta.get("agent_enterprise_layout")
            or []
        )
        for enterprise in agent_layout:
            enterprise_id = str(
                enterprise.get("enterprise_id")
                or enterprise.get("id")
                or ""
            )
            if not enterprise_id or enterprise_id not in configs:
                continue
            if not configs[enterprise_id].get("agent_departments"):
                configs[enterprise_id]["agent_departments"] = [
                    dict(department)
                    for department in (enterprise.get("departments") or [])
                    if isinstance(department, dict)
                ]
        return configs

    @staticmethod
    def _expected_action_departments(
        enterprise_name: str,
        round_id: int,
        enterprise_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[str]:
        enterprise_dir = Config.ENTERPRISE_DIR / enterprise_name
        department_root = enterprise_dir / "department"
        expected = set()

        configs = enterprise_configs or MultiTenantUtils._workspace_enterprise_configs()
        enterprise_config = configs.get(enterprise_name) or {}
        for dept in enterprise_config.get("enabled_functions", []):
            if dept in ACTION_DEPARTMENTS:
                expected.add(dept)

        if not expected and department_root.exists():
            for dept_dir in department_root.iterdir():
                if not dept_dir.is_dir() or dept_dir.name not in ACTION_DEPARTMENTS:
                    continue
                day_dir = dept_dir / f"day{round_id}"
                action_status = MultiTenantUtils._first_existing_valid_json(
                    MultiTenantUtils._candidate_action_files(day_dir, dept_dir.name),
                    dept=dept_dir.name,
                )
                if action_status["exists"]:
                    expected.add(dept_dir.name)

        return sorted(expected)

    @staticmethod
    def write_round_integrity_summary(round_id: int) -> str:
        """
        记录每轮最终落盘完整性。

        注意：该检查在 day end 归档后执行，因此 analysis 优先读取 records/dayN，
        交易部门同时接受 pre_* 归档文件，避免把正常归档误判为缺失。
        """
        enterprise_ids = list(Config.ENTERPRISE_IDS)
        totals = {
            "enterprise_count": len(enterprise_ids),
            "analysis_expected": len(enterprise_ids),
            "analysis_valid": 0,
            "analysis_missing": 0,
            "analysis_invalid": 0,
            "action_expected": 0,
            "action_valid": 0,
            "action_missing": 0,
            "action_invalid": 0,
            "result_present": 0,
            "error_files": 0,
            "recoverable_error_files": 0,
            "stale_trade_error_files": 0,
            "validation_failed_error_files": 0,
            "skill_audit_expected": 0,
            "skill_audit_valid": 0,
            "skill_audit_missing": 0,
            "skill_audit_invalid": 0,
            "skill_audit_fallback": 0,
            "skill_audit_unsuccessful": 0,
            "cobweb_agent_execution_failures_cumulative": 0,
            "coordination_report_expected": 0,
            "coordination_report_valid": 0,
            "coordination_report_missing": 0,
            "coordination_report_failed": 0,
        }
        summary = {
            "round_id": round_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "archive_aware": True,
            "notes": [
                "analysis.json is checked in records/dayN after end-of-day archive.",
                "trade departments accept both dept_action.json and pre_dept_action.json.",
            ],
            "totals": totals,
            "enterprises": {},
        }

        run_meta = MultiTenantUtils._read_json_if_exists(WORKSPACE / "run_meta.json", {})
        scenario_config = run_meta.get("scenario_config") or {}
        integration_profiles = run_meta.get("integration_profiles") or {}
        skill_profile = (
            ((integration_profiles.get("capabilities") or {}).get("skill"))
            or {}
        )
        skill_audit_enabled = bool(skill_profile.get("audit_enabled", False))
        coordination_profile = (
            ((integration_profiles.get("capabilities") or {}).get("coordination"))
            or {}
        )
        communication_validation_mode = str(
            coordination_profile.get("communication_validation") or "off"
        )
        coordination_expected = bool(
            coordination_profile.get("blackboard_enabled")
            or communication_validation_mode != "off"
        )
        simulation_config = scenario_config.get("simulation") or {}
        cobweb_config = simulation_config.get("cobweb_config") or {}
        experiment_design = run_meta.get("experiment_design") or scenario_config.get(
            "experiment_design"
        ) or {}
        scripted_policy = (
            (scenario_config.get("runtime_injection") or {}).get(
                "scripted_rule_policy"
            )
            or {}
        )
        is_cobweb_agent_run = bool(
            (
                simulation_config.get("market_demand_mode") == "cobweb"
                or cobweb_config.get("enabled")
            )
            and cobweb_config.get("production_response_mode") == "agent_endogenous"
            and not scripted_policy.get("enabled")
            and str(experiment_design.get("experiment_group") or "").upper()
            in {"C2", "C3"}
        )
        herding_config = simulation_config.get("herding_config") or {}
        herding_metrics_expected = bool(
            simulation_config.get("market_demand_mode") == "herding_market"
            or simulation_config.get("is_herding_mode")
            or herding_config.get("enabled")
        )
        herding_metrics_candidates = [
            WORKSPACE / "public" / "exchange" / f"day{round_id}" / "herding_metrics.json",
            WORKSPACE / "public" / "exchange" / f"day{round_id}" / "end_of_day" / "herding_metrics.json",
        ]
        herding_metrics_status = MultiTenantUtils._first_existing_valid_json(herding_metrics_candidates)
        herding_metrics_payload = (
            MultiTenantUtils._read_json_if_exists(Path(herding_metrics_status["path"]), {})
            if herding_metrics_status["valid"]
            else {}
        )
        herding_required_fields = [
            "herding_index",
            "synchronization_index",
            "production_growth_sync_rate",
            "overproduction_gap",
            "agent_reason_keyword_stats",
        ]
        herding_missing_fields = [
            field for field in herding_required_fields
            if field not in herding_metrics_payload
        ]
        summary["mode_metrics"] = {
            "herding": {
                "expected": herding_metrics_expected,
                "status": herding_metrics_status,
                "required_fields": herding_required_fields,
                "missing_fields": herding_missing_fields if herding_metrics_expected else [],
                "note": "Required only when market_demand_mode=herding_market or herding_config.enabled=true.",
            }
        }

        enterprise_configs = MultiTenantUtils._workspace_enterprise_configs()
        for enterprise_name in enterprise_ids:
            enterprise_dir = Config.ENTERPRISE_DIR / enterprise_name
            analysis_candidates = [
                enterprise_dir / "records" / f"day{round_id}" / "analysis.json",
                enterprise_dir / "analysis.json",
            ]
            analysis_status = MultiTenantUtils._first_existing_valid_json(analysis_candidates)
            if analysis_status["valid"]:
                totals["analysis_valid"] += 1
            elif analysis_status["exists"]:
                totals["analysis_invalid"] += 1
            else:
                totals["analysis_missing"] += 1

            departments = {}
            enterprise_config = enterprise_configs.get(enterprise_name) or {}
            agent_department_configs = {
                str(item.get("dept_id")): item
                for item in enterprise_config.get("agent_departments", [])
                if item.get("dept_id") and item.get("type") == "Agent"
            }
            for dept in MultiTenantUtils._expected_action_departments(
                enterprise_name,
                round_id,
                enterprise_configs,
            ):
                day_dir = enterprise_dir / "department" / dept / f"day{round_id}"
                action_status = MultiTenantUtils._first_existing_valid_json(
                    MultiTenantUtils._candidate_action_files(day_dir, dept),
                    dept=dept,
                )
                result_status = MultiTenantUtils._first_existing_valid_json(
                    MultiTenantUtils._candidate_result_files(day_dir, dept)
                )
                error_files = sorted(
                    [
                        str(path)
                        for path in day_dir.glob("*")
                        if path.is_file() and ("error" in path.name or "failed" in path.name)
                    ]
                ) if day_dir.exists() else []
                expected_skill_audit_paths = []
                agent_department_config = agent_department_configs.get(dept)
                if skill_audit_enabled and agent_department_config:
                    expected_skill_audit_paths.append(
                        day_dir / "skill_execution_audit.json"
                    )
                    if agent_department_config.get("need_trade"):
                        expected_skill_audit_paths.append(
                            day_dir / "trade_skill_execution_audit.json"
                        )
                skill_audit_artifacts = []
                for path in expected_skill_audit_paths:
                    exists = path.exists()
                    valid = MultiTenantUtils._is_valid_json_file(path)
                    audit_payload = (
                        MultiTenantUtils._read_json_if_exists(path, {})
                        if valid
                        else {}
                    )
                    skill_audit_artifacts.append({
                        "exists": exists,
                        "valid": valid,
                        "path": str(path),
                        "success": audit_payload.get("success") is True,
                        "fallback_used": bool(
                            audit_payload.get("fallback_used")
                        ),
                    })
                skill_audit_status = {
                    "expected": bool(expected_skill_audit_paths),
                    "expected_count": len(expected_skill_audit_paths),
                    "valid_count": sum(
                        item["valid"] for item in skill_audit_artifacts
                    ),
                    "clean_count": sum(
                        item["valid"]
                        and item["success"]
                        and not item["fallback_used"]
                        for item in skill_audit_artifacts
                    ),
                    "fallback_count": sum(
                        item["valid"] and item["fallback_used"]
                        for item in skill_audit_artifacts
                    ),
                    "unsuccessful_count": sum(
                        item["valid"] and not item["success"]
                        for item in skill_audit_artifacts
                    ),
                    "artifacts": skill_audit_artifacts,
                }

                totals["action_expected"] += 1
                if action_status["valid"]:
                    totals["action_valid"] += 1
                elif action_status["exists"]:
                    totals["action_invalid"] += 1
                else:
                    totals["action_missing"] += 1
                if result_status["exists"]:
                    totals["result_present"] += 1
                totals["error_files"] += len(error_files)
                error_summary = MultiTenantUtils._summarize_error_files(
                    error_files,
                    final_action_valid=bool(action_status["valid"]),
                    final_result_present=bool(result_status["exists"]),
                )
                totals["recoverable_error_files"] += error_summary["recoverable_count"]
                totals["stale_trade_error_files"] += error_summary["stale_trade_count"]
                totals["validation_failed_error_files"] += error_summary["validation_failed_count"]
                if skill_audit_status["expected"]:
                    totals["skill_audit_expected"] += skill_audit_status["expected_count"]
                    totals["skill_audit_valid"] += skill_audit_status["valid_count"]
                    totals["skill_audit_invalid"] += sum(
                        item["exists"] and not item["valid"]
                        for item in skill_audit_artifacts
                    )
                    totals["skill_audit_missing"] += sum(
                        not item["exists"]
                        for item in skill_audit_artifacts
                    )
                    totals["skill_audit_fallback"] += skill_audit_status[
                        "fallback_count"
                    ]
                    totals["skill_audit_unsuccessful"] += skill_audit_status[
                        "unsuccessful_count"
                    ]

                departments[dept] = {
                    "action": action_status,
                    "result": result_status,
                    "error_files": error_files,
                    "error_summary": error_summary,
                    "skill_audit": skill_audit_status,
                }

            summary["enterprises"][enterprise_name] = {
                "analysis": analysis_status,
                "departments": departments,
            }
            coordination_report_path = (
                enterprise_dir
                / "department"
                / "blackboard"
                / f"day{round_id}"
                / "communication_merge_report.json"
            )
            coordination_report_exists = coordination_report_path.exists()
            coordination_report_valid = MultiTenantUtils._is_valid_json_file(
                coordination_report_path
            )
            coordination_report_payload = (
                MultiTenantUtils._read_json_if_exists(
                    coordination_report_path,
                    {},
                )
                if coordination_report_valid
                else {}
            )
            coordination_report_ok = bool(
                coordination_report_payload.get("ok", False)
            )
            coordination_status = {
                "expected": coordination_expected,
                "exists": coordination_report_exists,
                "valid": coordination_report_valid,
                "ok": coordination_report_ok,
                "path": str(coordination_report_path),
                "validation_mode": communication_validation_mode,
            }
            summary["enterprises"][enterprise_name]["coordination"] = coordination_status
            if coordination_expected:
                totals["coordination_report_expected"] += 1
                if not coordination_report_exists:
                    totals["coordination_report_missing"] += 1
                elif not coordination_report_valid:
                    totals["coordination_report_failed"] += 1
                elif communication_validation_mode == "strict" and not coordination_report_ok:
                    totals["coordination_report_failed"] += 1
                else:
                    totals["coordination_report_valid"] += 1

        cumulative_cobweb_agent_failures = []
        if is_cobweb_agent_run:
            for enterprise_name, enterprise_config in enterprise_configs.items():
                for department_config in enterprise_config.get(
                    "agent_departments",
                    [],
                ):
                    if department_config.get("type") != "Agent":
                        continue
                    dept = str(department_config.get("dept_id") or "")
                    if not dept:
                        continue
                    audit_names = ["skill_execution_audit.json"]
                    if department_config.get("need_trade"):
                        audit_names.append("trade_skill_execution_audit.json")
                    for day in range(max(0, int(round_id)) + 1):
                        day_dir = (
                            Config.ENTERPRISE_DIR
                            / enterprise_name
                            / "department"
                            / dept
                            / f"day{day}"
                        )
                        for audit_name in audit_names:
                            audit_path = day_dir / audit_name
                            if not MultiTenantUtils._is_valid_json_file(audit_path):
                                continue
                            audit_payload = MultiTenantUtils._read_json_if_exists(
                                audit_path,
                                {},
                            )
                            if (
                                audit_payload.get("fallback_used")
                                or audit_payload.get("success") is not True
                            ):
                                cumulative_cobweb_agent_failures.append({
                                    "enterprise_id": enterprise_name,
                                    "department": dept,
                                    "round_id": day,
                                    "path": str(audit_path),
                                    "fallback_used": bool(
                                        audit_payload.get("fallback_used")
                                    ),
                                    "success": audit_payload.get("success")
                                    is True,
                                })
        totals["cobweb_agent_execution_failures_cumulative"] = len(
            cumulative_cobweb_agent_failures
        )
        summary["cobweb_agent_quality"] = {
            "strict_gate_enabled": is_cobweb_agent_run,
            "execution_failures_cumulative": len(
                cumulative_cobweb_agent_failures
            ),
            "failure_artifacts": cumulative_cobweb_agent_failures,
            "note": (
                "C2/C3 cobweb samples reject any Agent audit with fallback_used=true "
                "or success!=true, including failures from earlier rounds."
            ),
        }

        summary["ok"] = (
            totals["analysis_missing"] == 0
            and totals["analysis_invalid"] == 0
            and totals["action_missing"] == 0
            and totals["action_invalid"] == 0
            and totals["error_files"] == 0
            and totals["skill_audit_missing"] == 0
            and totals["skill_audit_invalid"] == 0
            and (
                not is_cobweb_agent_run
                or totals["cobweb_agent_execution_failures_cumulative"] == 0
            )
            and totals["coordination_report_missing"] == 0
            and totals["coordination_report_failed"] == 0
            and (
                not herding_metrics_expected
                or (
                    herding_metrics_status["valid"]
                    and not herding_missing_fields
                )
            )
        )
        target_path = WORKSPACE / "round_integrity" / f"day{round_id}.json"
        MultiTenantUtils._write_json(target_path, summary)
        print(
            "round_integrity "
            f"day{round_id}: ok={summary['ok']} "
            f"analysis={totals['analysis_valid']}/{totals['analysis_expected']} "
            f"actions={totals['action_valid']}/{totals['action_expected']} "
            f"missing={totals['analysis_missing'] + totals['action_missing']} "
            f"invalid={totals['analysis_invalid'] + totals['action_invalid']} "
            f"errors={totals['error_files']} "
            f"recoverable_errors={totals['recoverable_error_files']} "
            f"skill_audits={totals['skill_audit_valid']}/{totals['skill_audit_expected']} "
            f"coordination={totals['coordination_report_valid']}/{totals['coordination_report_expected']} "
            f"herding_metrics={herding_metrics_status['valid'] if herding_metrics_expected else 'n/a'} "
            f"report={target_path}"
        )
        return str(target_path)

    @staticmethod
    def write_history_projection_summary(round_id: int) -> Optional[str]:
        run_meta = MultiTenantUtils._read_json_if_exists(WORKSPACE / "run_meta.json", {})
        profiles = run_meta.get("integration_profiles") or {}
        analysis_profile = (
            ((profiles.get("capabilities") or {}).get("analysis"))
            or {}
        )
        if analysis_profile.get("profile") != "historical_diagnosis":
            return None

        history_days = max(1, int(analysis_profile.get("history_days", 5) or 5))
        mirror_repo = get_sql_mirror_repository(profiles)
        projection_root = WORKSPACE / "projections" / "history" / f"day{round_id}"
        manifest = {
            "schema_version": "history_projection_manifest.v1",
            "round_id": round_id,
            "history_days": history_days,
            "no_future_data": True,
            "enterprises": {},
        }
        for enterprise_id in Config.ENTERPRISE_IDS:
            output_path = projection_root / enterprise_id / "history_projection.json"
            payload = write_history_projection(
                enterprise_dir=Config.ENTERPRISE_DIR / enterprise_id,
                enterprise_id=enterprise_id,
                current_day=round_id,
                history_days=history_days,
                output_path=output_path,
            )
            if mirror_repo is not None:
                mirror_history_projection(
                    mirror_repo,
                    run_id=str(run_meta.get("run_id") or "workspace_unarchived"),
                    scenario_id=str(run_meta.get("scenario_id") or ""),
                    enterprise_id=enterprise_id,
                    day=round_id,
                    projection=payload,
                )
            manifest["enterprises"][enterprise_id] = {
                "path": str(output_path),
                "source_day_range": payload["source_day_range"],
                "no_future_data": payload["no_future_data"],
                "sql_mirrored": mirror_repo is not None,
            }
            manifest["no_future_data"] = (
                manifest["no_future_data"] and payload["no_future_data"]
            )

        manifest_path = projection_root / "history_projection_manifest.json"
        MultiTenantUtils._write_json(manifest_path, manifest)
        return str(manifest_path)

    @staticmethod
    def write_single_enterprise_chart_export(round_id: int) -> Optional[str]:
        """导出旧单企业 charts_data_export.json contract，并按轮次归档快照。"""
        runtime_config = get_runtime_injection_config()
        policy = runtime_config.get("single_enterprise_chart_export_policy") or {}
        if not policy.get("enabled"):
            return None

        target_enterprises = list(policy.get("target_enterprise_ids") or Config.ENTERPRISE_IDS)
        manifest = {
            "schema_version": "single_enterprise_chart_export_manifest.v1",
            "round_id": round_id,
            "enabled": True,
            "exports": {},
            "errors": {},
        }
        for enterprise_id in target_enterprises:
            if enterprise_id not in Config.ENTERPRISE_IDS:
                continue
            enterprise_dir = WORKSPACE / "enterprises" / enterprise_id
            output_path = enterprise_dir / "charts_data_export.json"
            try:
                payload = export_chart_data_file(enterprise_dir, output_path)
                export_paths = {"latest": str(output_path)}
                if policy.get("archive_per_round", True):
                    archive_path = (
                        enterprise_dir
                        / "records"
                        / f"day{round_id}"
                        / "charts_data_export.json"
                    )
                    archive_path.parent.mkdir(parents=True, exist_ok=True)
                    MultiTenantUtils._write_json(archive_path, payload)
                    export_paths["archive"] = str(archive_path)
                manifest["exports"][enterprise_id] = {
                    "paths": export_paths,
                    "latest_day": payload.get("meta", {}).get("latest_day"),
                    "available_days": payload.get("meta", {}).get("available_days", []),
                }
            except Exception as exc:
                logger.warning(
                    "single-enterprise chart export failed for %s day%s: %s",
                    enterprise_id,
                    round_id,
                    exc,
                )
                manifest["errors"][enterprise_id] = str(exc)

        manifest_path = (
            WORKSPACE
            / "projections"
            / "single_enterprise_charts"
            / f"day{round_id}"
            / "single_enterprise_chart_export_manifest.json"
        )
        MultiTenantUtils._write_json(manifest_path, manifest)
        return str(manifest_path)

    @staticmethod
    def write_run_metrics_projection(round_id: int) -> str:
        run_meta = MultiTenantUtils._read_json_if_exists(WORKSPACE / "run_meta.json", {})
        profiles = run_meta.get("integration_profiles") or {}
        output_path = (
            WORKSPACE
            / "projections"
            / "run_metrics"
            / f"day{round_id}"
            / "run_metrics_projection.json"
        )
        payload = write_run_metrics_projection(
            workspace_dir=WORKSPACE,
            round_id=round_id,
            output_path=output_path,
        )
        mirror_repo = get_sql_mirror_repository(profiles)
        if mirror_repo is not None:
            mirror_run_metrics_projection(
                mirror_repo,
                run_id=str(payload.get("run_id") or run_meta.get("run_id") or "workspace_unarchived"),
                scenario_id=str(payload.get("scenario_id") or run_meta.get("scenario_id") or ""),
                round_id=round_id,
                projection=payload,
            )
        return str(output_path)

    @staticmethod
    def write_case_evaluation_projection(round_id: int) -> Optional[str]:
        run_meta = MultiTenantUtils._read_json_if_exists(WORKSPACE / "run_meta.json", {})
        profiles = run_meta.get("integration_profiles") or {}
        output_path = (
            WORKSPACE
            / "projections"
            / "case_evaluation"
            / f"day{round_id}"
            / "case_evaluation_projection.json"
        )
        payload = write_case_evaluation_projection(
            workspace_dir=WORKSPACE,
            round_id=round_id,
            output_path=output_path,
        )
        if payload is None:
            return None
        mirror_repo = get_sql_mirror_repository(profiles)
        if mirror_repo is not None:
            mirror_case_evaluation_projection(
                mirror_repo,
                run_id=str(payload.get("run_id") or run_meta.get("run_id") or "workspace_unarchived"),
                scenario_id=str(payload.get("scenario_id") or run_meta.get("scenario_id") or ""),
                case_id=str(payload.get("case_id") or ""),
                round_id=round_id,
                projection=payload,
            )
        return str(output_path)

    @staticmethod
    def write_multi_enterprise_projections(round_id: int) -> str:
        run_meta = MultiTenantUtils._read_json_if_exists(WORKSPACE / "run_meta.json", {})
        profiles = run_meta.get("integration_profiles") or {}
        projection_root = WORKSPACE / "projections" / "multi_enterprise" / f"day{round_id}"
        order_payload = write_order_lifecycle_projection(
            workspace_dir=WORKSPACE,
            round_id=round_id,
            output_path=projection_root / "order_lifecycle_projection.json",
        )
        topology_payload = write_topology_projection(
            workspace_dir=WORKSPACE,
            round_id=round_id,
            output_path=projection_root / "topology_projection.json",
        )
        metrics_payload = write_enterprise_daily_metrics_projection(
            workspace_dir=WORKSPACE,
            round_id=round_id,
            output_path=projection_root / "enterprise_daily_metrics_projection.json",
        )
        mirror_repo = get_sql_mirror_repository(profiles)
        if mirror_repo is not None:
            run_id = str(run_meta.get("run_id") or "workspace_unarchived")
            scenario_id = str(run_meta.get("scenario_id") or "")
            mirror_order_lifecycle_projection(
                mirror_repo,
                run_id=run_id,
                scenario_id=scenario_id,
                round_id=round_id,
                projection=order_payload,
            )
            mirror_topology_projection(
                mirror_repo,
                run_id=run_id,
                scenario_id=scenario_id,
                round_id=round_id,
                projection=topology_payload,
            )
            mirror_enterprise_daily_metrics_projection(
                mirror_repo,
                run_id=run_id,
                scenario_id=scenario_id,
                round_id=round_id,
                projection=metrics_payload,
            )
        manifest = {
            "round_id": round_id,
            "sql_mirrored": mirror_repo is not None,
            "projections": {
                "order_lifecycle_projection": str(
                    projection_root / "order_lifecycle_projection.json"
                ),
                "topology_projection": str(projection_root / "topology_projection.json"),
                "enterprise_daily_metrics_projection": str(
                    projection_root / "enterprise_daily_metrics_projection.json"
                ),
            },
        }
        manifest_path = projection_root / "multi_enterprise_projection_manifest.json"
        MultiTenantUtils._write_json(manifest_path, manifest)
        return str(manifest_path)

    @staticmethod
    def _flatten_action_reason_texts(payload: Any) -> List[str]:
        """Extract action_reason-like text fragments from an action payload."""
        texts: List[str] = []
        if isinstance(payload, list):
            for item in payload:
                texts.extend(MultiTenantUtils._flatten_action_reason_texts(item))
            return texts
        if not isinstance(payload, dict):
            return texts

        for key in ("action_reason", "reason", "target_reason"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
        action = payload.get("action")
        if isinstance(action, dict):
            action_param = action.get("action_param")
            if isinstance(action_param, str) and action_param.strip():
                texts.append(action_param.strip())
        return texts

    @staticmethod
    def _build_herding_agent_reason_stats(round_id: int) -> Dict[str, Any]:
        """Summarize whether Agent action reasons cite market heat, peers, and risk signals."""
        keyword_groups = {
            "market_heat": [
                "市场热度", "热度", "市场信号", "需求信号", "可见需求", "visible_demand_signal",
                "行业趋势", "趋势", "market heat", "market_heat", "trend",
            ],
            "peer_signal": [
                "同业", "同行", "同伴", "聚合摘要", "同业摘要", "peer", "peer_summary",
                "herding_signal", "herding", "同步", "synchronization", "竞争", "市场份额", "份额",
            ],
            "inventory_risk": ["库存", "积压", "滞销", "inventory", "backlog"],
            "cash_risk": ["现金", "资金", "财务", "利润", "cash", "profit"],
            "order_demand": ["订单", "需求", "客户", "order", "demand"],
        }
        result = {
            "round": round_id,
            "source": "workspace_multi.action_reason",
            "keyword_groups": keyword_groups,
            "total_reason_count": 0,
            "group_mentions": {group: 0 for group in keyword_groups},
            "departments": {},
            "enterprises": {},
        }

        for enterprise_name in Config.ENTERPRISE_IDS:
            enterprise_summary = {
                "reason_count": 0,
                "group_mentions": {group: 0 for group in keyword_groups},
            }
            for dept in ("production", "sales"):
                day_dir = Config.ENTERPRISE_DIR / enterprise_name / "department" / dept / f"day{round_id}"
                action_status = MultiTenantUtils._first_existing_valid_json(
                    MultiTenantUtils._candidate_action_files(day_dir, dept),
                    dept=dept,
                )
                texts: List[str] = []
                if action_status["valid"]:
                    payload = MultiTenantUtils._read_json_if_exists(Path(action_status["path"]), [])
                    texts = MultiTenantUtils._flatten_action_reason_texts(payload)

                dept_key = f"{enterprise_name}.{dept}"
                dept_summary = {
                    "action_file": action_status.get("path"),
                    "reason_count": len(texts),
                    "group_mentions": {group: 0 for group in keyword_groups},
                    "sample_reasons": texts[:3],
                }
                for text in texts:
                    lowered = text.lower()
                    result["total_reason_count"] += 1
                    enterprise_summary["reason_count"] += 1
                    for group, keywords in keyword_groups.items():
                        if any(keyword.lower() in lowered for keyword in keywords):
                            result["group_mentions"][group] += 1
                            enterprise_summary["group_mentions"][group] += 1
                            dept_summary["group_mentions"][group] += 1
                result["departments"][dept_key] = dept_summary

            result["enterprises"][enterprise_name] = enterprise_summary

        total = result["total_reason_count"] or 1
        result["group_mention_rates"] = {
            group: count / total
            for group, count in result["group_mentions"].items()
        }
        result["herding_reason_reference_rate"] = (
            min(
                1.0,
                (result["group_mentions"]["market_heat"] + result["group_mentions"]["peer_signal"])
                / total,
            )
        )
        result["risk_reason_reference_rate"] = (
            min(
                1.0,
                (result["group_mentions"]["inventory_risk"] + result["group_mentions"]["cash_risk"])
                / total,
            )
        )
        return result

    @staticmethod
    def _enrich_herding_metrics_with_agent_reasons(round_id: int, herding_metrics: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(herding_metrics, dict):
            return herding_metrics
        enriched = dict(herding_metrics)
        enriched["agent_reason_keyword_stats"] = MultiTenantUtils._build_herding_agent_reason_stats(round_id)
        return enriched

    @staticmethod
    def archive_enterprise_json_files(round_id: int):
        for enterprise_name in Config.ENTERPRISE_IDS:
            archive_dir = WORKSPACE / "enterprises" / enterprise_name / "records" / f"day{round_id}"
            archive_dir.mkdir(parents=True, exist_ok=True)

            src = WORKSPACE / "enterprises" / enterprise_name / "analysis.json"
            if src.exists():
                shutil.move(str(src), str(archive_dir / "analysis.json"))

    @staticmethod
    def archive_enterprise_trade_files(enterprise_name: str, round_id: int):
        archive_dir1 = WORKSPACE / "enterprises" / enterprise_name / "department" / "procurement" / f"day{round_id}" 
        files1 = [
            "procurement_action.json",
            "procurement_result.json",
        ]
        # TODO 对 error 情况补充
        for name in files1:
            src = archive_dir1 / name
            if src.exists():
                shutil.move(src, archive_dir1 / f"pre_{name}")

        archive_dir2 = WORKSPACE / "enterprises" / enterprise_name / "department" / "sales" / f"day{round_id}" 
        files2 = [
            "sales_action.json",
            "sales_result.json",
        ]
        for name in files2:
            src = archive_dir2 / name
            if src.exists():
                shutil.move(src, archive_dir2 / f"pre_{name}")
                

    @staticmethod
    def save_model_messages(enterprise_name: str, round_id: int, messages: List[dict]):
        """
        保存企业各角色的模型消息到指定目录
        :param enterprise_name: 企业名称
        :param round_id: 轮次ID
        :param messages: 消息列表
        """
        # 创建消息存储目录
        msg_dir = WORKSPACE / "enterprises" / enterprise_name / "model_messages" / f"day{round_id}"
        msg_dir.mkdir(parents=True, exist_ok=True)
        
        # 按角色分类消息
        role_messages = {}
        for msg in messages:
            role = msg.get("role", "unknown")
            if role not in role_messages:
                role_messages[role] = []
            role_messages[role].append(msg)
        
        # 为每个角色保存单独的消息文件
        for role, role_msgs in role_messages.items():
            # 将角色名转换为小写并作为文件名
            role_lower = role.lower()
            msg_file = msg_dir / f"{role_lower}_messages.json"
            
            # 写入消息文件
            with open(msg_file, 'w', encoding='utf-8') as f:
                json.dump(role_msgs, f, indent=2, ensure_ascii=False)

    @staticmethod
    def save_exchange_info(round_id: int, stage: str = None):
        """
        保存交易所信息到指定目录
        :param round_id: 轮次ID
        """
        try:
            # 发送请求获取交易所详细信息
            response = requests.get(
                f"{Config.BASE_URL}/exchange",
                headers=StaticUtils.simulation_session_headers(),
            )
            
            if response.status_code == 200:
                exchange_data = response.json()
                
                # 创建交易所信息存储目录
                exchange_dir = WORKSPACE / "public" / "exchange" / f"day{round_id}"
                if stage:
                    exchange_dir = exchange_dir / stage
                exchange_dir.mkdir(parents=True, exist_ok=True)
                
                # 保存交易所信息到文件
                exchange_file = exchange_dir / "exchange.json"
                with open(exchange_file, 'w', encoding='utf-8') as f:
                    json.dump(exchange_data, f, indent=2, ensure_ascii=False)

                demand_response = requests.get(
                    f"{Config.BASE_URL}/market/external_demand",
                    headers=StaticUtils.simulation_session_headers(),
                    timeout=30,
                )
                if demand_response.status_code == 200:
                    demand_payload = demand_response.json()
                    demand_file = exchange_dir / "external_demand.json"
                    with open(demand_file, 'w', encoding='utf-8') as f:
                        json.dump(demand_payload, f, indent=2, ensure_ascii=False)
                    shared_resource_metrics = (
                        (demand_payload.get("data") or {}).get("shared_resource_latest_metrics")
                    )
                    if shared_resource_metrics:
                        shared_resource_file = exchange_dir / "shared_resource_metrics.json"
                        with open(shared_resource_file, 'w', encoding='utf-8') as f:
                            json.dump(shared_resource_metrics, f, indent=2, ensure_ascii=False)
                    herding_metrics = (
                        (demand_payload.get("data") or {}).get("herding_latest_metrics")
                    )
                    if herding_metrics:
                        herding_metrics = MultiTenantUtils._enrich_herding_metrics_with_agent_reasons(
                            round_id,
                            herding_metrics,
                        )
                        herding_file = exchange_dir / "herding_metrics.json"
                        with open(herding_file, 'w', encoding='utf-8') as f:
                            json.dump(herding_metrics, f, indent=2, ensure_ascii=False)

                bullwhip_response = requests.get(
                    f"{Config.BASE_URL}/bullwhip",
                    headers=StaticUtils.simulation_session_headers(),
                    timeout=30,
                )
                if bullwhip_response.status_code == 200:
                    bullwhip_file = exchange_dir / "bullwhip_metrics.json"
                    with open(bullwhip_file, 'w', encoding='utf-8') as f:
                        json.dump(bullwhip_response.json(), f, indent=2, ensure_ascii=False)

                context_response = requests.get(
                    f"{Config.BASE_URL}/simulation_context",
                    headers=StaticUtils.simulation_session_headers(),
                    timeout=30,
                )
                if context_response.status_code == 200:
                    context_payload = context_response.json()
                    external_environment = (
                        (context_payload.get("data") or {}).get("external_environment")
                    )
                    if isinstance(external_environment, dict) and external_environment.get("enabled"):
                        with open(exchange_dir / "external_environment.json", 'w', encoding='utf-8') as f:
                            json.dump(external_environment, f, indent=2, ensure_ascii=False)
                    
                print(f"交易所信息已保存到: {exchange_file}")
            else:
                print(f"获取交易所信息失败，HTTP状态码: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"请求交易所信息时发生错误: {str(e)}")
        except json.JSONDecodeError as e:
            print(f"解析交易所信息响应时发生错误: {str(e)}")
        except Exception as e:
            print(f"保存交易所信息时发生未知错误: {str(e)}")

    @staticmethod
    def materialize_exchange_root_alias(round_id: int, source_stage: str = "end_of_day"):
        """Expose end-of-day exchange artifacts at the legacy root without rewriting them."""
        exchange_root = WORKSPACE / "public" / "exchange" / f"day{round_id}"
        source_dir = exchange_root / source_stage
        if not source_dir.exists():
            return
        exchange_root.mkdir(parents=True, exist_ok=True)
        for source_path in source_dir.iterdir():
            if not source_path.is_file():
                continue
            target_path = exchange_root / source_path.name
            try:
                if target_path.exists() or target_path.is_symlink():
                    target_path.unlink()
                os.link(source_path, target_path)
            except OSError:
                shutil.copy2(source_path, target_path)

    @staticmethod
    def save_observer_state(round_id: int, stage: str):
        """
        保存供复盘和可视化使用的完整状态快照。
        这些文件保留完整 simulation_context，不作为 agent 决策输入。
        """
        observer_dir = WORKSPACE / "public" / "observer_state" / f"day{round_id}" / stage
        observer_dir.mkdir(parents=True, exist_ok=True)

        for enterprise_name in Config.ENTERPRISE_IDS:
            try:
                response = requests.get(
                    f"{Config.BASE_URL}/state",
                    json={"enterprise_name": enterprise_name},
                    headers=StaticUtils.simulation_session_headers(),
                    timeout=30
                )
                if response.status_code != 200:
                    continue
                result = response.json()
                if result.get("status") != "success":
                    continue

                data = result.get("data", {})
                snapshot = {
                    "round_id": round_id,
                    "stage": stage,
                    "enterprise_name": enterprise_name,
                    "current_time": data.get("current_time"),
                    "observation": data.get("observation")
                }
                snapshot_file = observer_dir / f"{enterprise_name}.json"
                with open(snapshot_file, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"保存 {enterprise_name} observer_state 失败: {str(e)}")
