"""
销售管理模块

负责企业的产品销售业务，支持市场销售(B2C)和企业间销售(B2B)两种模式
"""

from typing import Any, Dict, List, Optional
from enterprise.modules import hr_manager
from enterprise.modules.base_business_module import EnhancedBaseModule
from enterprise.modules.response_model import ModuleResponse, ResponseStatus
from enterprise.modules.decorators import with_response, validate_positive, skip_dry_run_validation
from config.module_config import SalesConfig
from config.simulation_preset_config import get_runtime_injection_config
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from network.trade_entities import (
    OrderProposal,
    Order
)


class SalesManager(EnhancedBaseModule):
    """
    销售管理器类
    处理企业销售相关的所有业务逻辑
    """

    def __init__(self, enterprise, total_possible_markets: int = None, module_id=None, config: SalesConfig = None):
        """
        初始化销售管理器

        Args:
            enterprise: 所属企业实例
            total_possible_markets: 市场总数（可选，默认从 config 读取）
            module_id: 模块唯一标识（可选）
            config: 销售配置对象（可选，默认使用 SalesConfig()）
        """
        # 使用配置或默认配置
        self.config = config or SalesConfig()

        # 调用父类初始化方法
        super().__init__(
            enterprise,
            module_id or f"sales_{enterprise.id}",
            self.config
        )
        self.module_type = "SalesManager"
        self.total_possible_markets = total_possible_markets or self.config.TOTAL_POSSIBLE_MARKETS

        # 市场管理
        self.markets: Dict[str, Dict] = {}  # 市场信息 {market_id: market_data}
        self.next_market_id = 1  # 下一个市场ID

        # 订单管理
        self.sales_orders: List[Dict] = []  # 销售订单列表
        self.next_order_id = 1  # 下一个订单ID

        # B2B报价（可选功能）
        self.quotations: Dict[str, Dict] = {}  # 报价记录 {quotation_id: quotation_data}
        self.next_quotation_id = 1  # 下一个报价ID

        self.proposals_list: List[OrderProposal] = []  # 当前仍待销售部门响应的提案收件箱
        self.proposal_history: List[OrderProposal] = []  # 已见提案历史（含已响应/已完结）

        # 销售指标
        self.sales_metrics = {
            "total_orders": 0,              # 总订单数
            "accepted_orders": 0,           # 已接受订单数
            "completed_orders": 0,          # 完成订单数
            "rejected_orders": 0,           # 拒绝订单数
            "expired_orders": 0,            # 报价有效期内未处理的订单数
            "breached_orders": 0,           # 违约订单数
            "total_revenue": 0.0,           # 总收入
            "total_quantity_sold": 0.0,     # 总销售数量
            "order_fulfillment_rate": 0.0,  # 订单履约率
            "market_coverage_rate": 0.0,    # 市场覆盖率
            "on_time_delivery_rate": 0.0,   # 按时交付率
            "total_downstream_demand": 0.0,
            "fulfilled_downstream_demand": 0.0,
            "backlog_quantity": 0.0,
            "lost_sales_quantity": 0.0,
            "confirmed_order_backlog_quantity": 0.0,
            "proposal_backlog_quantity": 0.0,
            "stale_backlog_quantity": 0.0,
            "overdue_confirmed_order_quantity": 0.0,
        }

        # 销售事件日志
        self.sales_events: List[Dict] = []
        self.received_demand_history: List[Dict] = []
        self.fulfilled_demand_history: List[Dict] = []
        self.backlog_history: List[Dict] = []
        self.lost_sales_history: List[Dict] = []
        
        # 价格策略配置
        self.price_strategy = {}

    # ========== 市场管理 ==========

    def _get_current_day(self) -> int:
        return self.enterprise.time_manager.get_day() if hasattr(self.enterprise, "time_manager") else 0

    def _estimate_landed_unit_cost(self, product_id: str) -> float:
        """
        估算当前销售品项的落地单位成本。

        对外采原料，优先使用采购侧真实 `total_cost / quantity`；
        对成品或无采购历史项，则退回库存单价。
        """
        procurement_manager = super().get_module_by_type("ProcurementManager")
        landed_cost = 0.0
        if procurement_manager and hasattr(procurement_manager, "purchase_orders"):
            received_orders = [
                order for order in procurement_manager.purchase_orders
                if order.get("material_id") == product_id and order.get("status") == "received"
            ]
            total_quantity = sum(float(order.get("quantity", 0) or 0) for order in received_orders)
            total_cost = sum(float(order.get("total_cost", 0) or 0) for order in received_orders)
            if total_quantity > 0:
                landed_cost = total_cost / total_quantity

        inventory_manager = super().get_module_by_type("InventoryManager")
        detail_result = inventory_manager.get_inventory_detail(product_id)
        inventory_unit_price = 0.0
        if getattr(detail_result, "success", False):
            stock = detail_result.data if isinstance(detail_result.data, dict) else {}
            inventory_unit_price = float(stock.get("unit_price", 0) or 0)

        return max(landed_cost, inventory_unit_price, 0.0)

    def _has_role_tag(self, tag: str) -> bool:
        return tag in set(getattr(self.enterprise, "role_tags", []) or [])

    def _long_horizon_margin_floor(self) -> float:
        runtime_config = getattr(self.enterprise, "runtime_injection_config", None)
        if not isinstance(runtime_config, dict):
            controller = getattr(self.enterprise, "controller", None)
            runtime_config = getattr(controller, "runtime_injection_config", None)
        if not isinstance(runtime_config, dict):
            runtime_config = get_runtime_injection_config()
        policy = (runtime_config or {}).get("long_horizon_profitability_policy") or {}
        target_ids = set(policy.get("target_enterprise_ids") or [])
        if not policy.get("enabled") or (
            target_ids and getattr(self.enterprise, "id", None) not in target_ids
        ):
            return 0.0
        role_floors = policy.get("b2b_margin_floor_by_role_tag") or {}
        enterprise_tags = set(getattr(self.enterprise, "role_tags", []) or [])
        floors = []
        for role_tag, value in role_floors.items():
            if role_tag not in enterprise_tags:
                continue
            try:
                floors.append(float(value))
            except (TypeError, ValueError):
                continue
        return max(floors, default=0.0)

    def _resolve_b2b_min_price(self, product_id: str) -> Dict[str, float]:
        inventory_manager = super().get_module_by_type("InventoryManager")
        detail_result = inventory_manager.get_inventory_detail(product_id)
        if not getattr(detail_result, "success", False):
            reference_price = float(self.config.B2B_PRICE_REFERENCE_FALLBACK)
            landed_unit_cost = reference_price
            cost_floor_multiplier = max(
                float(self.config.B2B_HARD_COST_FLOOR_MULTIPLIER),
                self._long_horizon_margin_floor(),
            )
            cost_floor = landed_unit_cost * cost_floor_multiplier
            return {
                "reference_price": reference_price,
                "landed_unit_cost": landed_unit_cost,
                "cost_floor": cost_floor,
                "min_price": max(
                    reference_price * float(self.config.B2B_BASE_MIN_PRICE_MULTIPLIER),
                    cost_floor,
                ),
                "multiplier": float(self.config.B2B_BASE_MIN_PRICE_MULTIPLIER),
                "strategy": "fallback_band_with_cost_floor",
            }

        stock = detail_result.data if isinstance(detail_result.data, dict) else {}
        reference_price = float(stock.get("unit_price", 0) or 0)
        if reference_price <= 0:
            reference_price = float(self.config.B2B_PRICE_REFERENCE_FALLBACK)
        landed_unit_cost = self._estimate_landed_unit_cost(product_id)

        quantity = float(stock.get("quantity", 0) or 0)
        reorder_point = float(stock.get("reorder_point", 0) or 0)
        safety_stock = float(stock.get("safety_stock", 0) or 0)
        policy_floor = max(reorder_point, safety_stock)

        multiplier = float(self.config.B2B_BASE_MIN_PRICE_MULTIPLIER)
        strategy = "base_band"
        if policy_floor > 0 and quantity <= policy_floor:
            multiplier = float(self.config.B2B_LOW_STOCK_MIN_PRICE_MULTIPLIER)
            strategy = "low_stock_band"
        elif quantity >= max(policy_floor * 2, 1):
            multiplier = float(self.config.B2B_HIGH_STOCK_MIN_PRICE_MULTIPLIER)
            strategy = "high_stock_band"

        cost_floor_multiplier = float(self.config.B2B_HARD_COST_FLOOR_MULTIPLIER)
        if (
            self._has_role_tag("top_tier_supply_node")
            and product_id in getattr(self.enterprise, "purchasable_materials_idList", [])
        ):
            cost_floor_multiplier = float(self.config.B2B_TOP_TIER_RAW_MATERIAL_MARGIN_FLOOR)
        elif self._has_role_tag("finished_goods_manufacturer") and product_id == "beer":
            if policy_floor > 0 and quantity <= policy_floor:
                multiplier = float(self.config.B2B_MANUFACTURER_FINISHED_GOODS_LOW_STOCK_MIN_PRICE_MULTIPLIER)
                strategy = "manufacturer_low_stock_band"
            elif quantity >= max(policy_floor * 2, 1):
                multiplier = float(self.config.B2B_MANUFACTURER_FINISHED_GOODS_HIGH_STOCK_MIN_PRICE_MULTIPLIER)
                strategy = "manufacturer_high_stock_band"
            else:
                multiplier = float(self.config.B2B_MANUFACTURER_FINISHED_GOODS_BASE_MIN_PRICE_MULTIPLIER)
                strategy = "manufacturer_base_band"
            cost_floor_multiplier = float(self.config.B2B_MANUFACTURER_FINISHED_GOODS_MARGIN_FLOOR)
        cost_floor_multiplier = max(
            cost_floor_multiplier,
            self._long_horizon_margin_floor(),
        )
        cost_floor = max(reference_price, landed_unit_cost) * cost_floor_multiplier
        candidate_min_price = reference_price * multiplier
        min_price = max(candidate_min_price, cost_floor)
        if min_price > candidate_min_price:
            strategy = f"{strategy}_cost_floor_guard"

        return {
            "reference_price": reference_price,
            "landed_unit_cost": landed_unit_cost,
            "cost_floor": cost_floor,
            "min_price": min_price,
            "multiplier": multiplier,
            "strategy": strategy,
        }

    def _serialize_proposals(self, proposals: Optional[List[OrderProposal]] = None) -> List[Dict]:
        serialized = []
        for proposal in proposals if proposals is not None else self.proposals_list:
            if is_dataclass(proposal):
                serialized.append(asdict(proposal))
            elif isinstance(proposal, dict):
                serialized.append(proposal)
            else:
                serialized.append(getattr(proposal, "__dict__", {"value": str(proposal)}))
        return serialized

    def _is_relevant_proposal(self, proposal: OrderProposal) -> bool:
        return getattr(proposal, "seller_company_id", None) == self.enterprise.id

    def _is_waiting_for_local_response(self, proposal: OrderProposal) -> bool:
        return proposal.status == "pending" and proposal.seller_response is None

    def _get_exchange(self):
        return getattr(self.enterprise, "downstream_exchange", None)

    def _ingest_proposals(self, proposals: List[OrderProposal]) -> None:
        history_ids = {proposal.proposal_id for proposal in self.proposal_history}
        inbox_ids = {proposal.proposal_id for proposal in self.proposals_list}
        for proposal in proposals:
            if not self._is_relevant_proposal(proposal):
                continue
            if proposal.proposal_id not in history_ids:
                self.proposal_history.append(proposal)
                history_ids.add(proposal.proposal_id)
            if self._is_waiting_for_local_response(proposal) and proposal.proposal_id not in inbox_ids:
                self.proposals_list.append(proposal)
                inbox_ids.add(proposal.proposal_id)

    def _prune_proposal_views(self) -> None:
        self.proposal_history = [
            proposal for proposal in self.proposal_history
            if self._is_relevant_proposal(proposal)
        ]
        self.proposals_list = [
            proposal for proposal in self.proposals_list
            if self._is_relevant_proposal(proposal) and self._is_waiting_for_local_response(proposal)
        ]

    def _refresh_proposal_views(self) -> None:
        """
        使用交易所最新 dispatch 结果重建待响应提案 inbox，并同步历史视图。
        """
        exchange = self._get_exchange()
        if not exchange:
            self._prune_proposal_views()
            return

        pending_inbox = [
            proposal
            for proposal in exchange.dispatch_proposals()
            if self._is_relevant_proposal(proposal) and self._is_waiting_for_local_response(proposal)
        ]
        pending_by_id = {proposal.proposal_id: proposal for proposal in pending_inbox}
        history_by_id = {
            proposal.proposal_id: proposal
            for proposal in self.proposal_history
            if self._is_relevant_proposal(proposal)
        }
        history_by_id.update(pending_by_id)
        self.proposal_history = list(history_by_id.values())
        self.proposals_list = list(pending_by_id.values())
        self._prune_proposal_views()

    def _get_exchange_proposal(self, proposal_id: str) -> Optional[OrderProposal]:
        exchange = self._get_exchange()
        if exchange and hasattr(exchange, "get_proposal"):
            return exchange.get_proposal(proposal_id)
        return self._find_relevant_proposal(proposal_id)

    def _find_pending_proposal(self, proposal_id: str) -> Optional[OrderProposal]:
        for proposal in self.proposals_list:
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def _find_relevant_proposal(self, proposal_id: str) -> Optional[OrderProposal]:
        self._prune_proposal_views()
        for proposal in self.proposal_history:
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def _record_downstream_demand(
        self,
        order: Dict,
        event_type: str,
        status: str,
        fulfilled_quantity: float = 0.0,
        backlog_quantity: float = 0.0,
        lost_quantity: float = 0.0
    ):
        quantity = order.get("quantity", 0) or 0
        event = {
            "round": self._get_current_day(),
            "order_id": order.get("order_id"),
            "product_id": order.get("product_id"),
            "source_id": order.get("source_id"),
            "source_type": order.get("source_type"),
            "external_demand_id": order.get("external_demand_id"),
            "quantity": quantity,
            "fulfilled_quantity": fulfilled_quantity,
            "backlog_quantity": backlog_quantity,
            "lost_quantity": lost_quantity,
            "status": status,
            "event_type": event_type
        }
        self.received_demand_history.append(event)
        if fulfilled_quantity:
            self.fulfilled_demand_history.append(event)
        if backlog_quantity:
            self.backlog_history.append(event)
        if lost_quantity:
            self.lost_sales_history.append(event)

        market_manager = getattr(self.enterprise, "market_manager", None)
        if (
            market_manager
            and hasattr(market_manager, "record_external_order_event")
            and order.get("source_type") in ("market", "external_market")
        ):
            market_manager.record_external_order_event(self.enterprise.id, event_type, event)

    def _get_demand_backlog_status(self) -> Dict:
        by_product = defaultdict(lambda: {
            "received_quantity": 0.0,
            "fulfilled_quantity": 0.0,
            "backlog_quantity": 0.0,
            "lost_sales_quantity": 0.0
        })
        for event in self.received_demand_history:
            product_id = event.get("product_id")
            if not product_id:
                continue
            if event.get("event_type") == "created":
                by_product[product_id]["received_quantity"] += event.get("quantity", 0) or 0
        for event in self.fulfilled_demand_history:
            product_id = event.get("product_id")
            if product_id:
                by_product[product_id]["fulfilled_quantity"] += event.get("fulfilled_quantity", 0) or 0
        for event in self.backlog_history:
            product_id = event.get("product_id")
            if product_id:
                if event.get("event_type") in ("rejected", "breached"):
                    by_product[product_id]["backlog_quantity"] += event.get("backlog_quantity", 0) or 0
        for event in self.lost_sales_history:
            product_id = event.get("product_id")
            if product_id:
                by_product[product_id]["lost_sales_quantity"] += event.get("lost_quantity", 0) or 0
        return {
            "by_product": dict(by_product),
            "received_demand_history": self.received_demand_history,
            "fulfilled_demand_history": self.fulfilled_demand_history,
            "backlog_history": self.backlog_history,
            "lost_sales_history": self.lost_sales_history
        }

    def _get_backlog_breakdown_status(self) -> Dict:
        current_day = self._get_current_day()
        demand_backlog = self._get_demand_backlog_status()
        proposal_source = []
        exchange = self._get_exchange()
        if exchange:
            proposal_source = [
                proposal for proposal in getattr(exchange, "proposals", [])
                if self._is_relevant_proposal(proposal)
            ]
        else:
            proposal_source = list(self.proposal_history)

        confirmed_by_product = defaultdict(lambda: {
            "quantity": 0.0,
            "order_count": 0,
            "overdue_quantity": 0.0,
            "overdue_order_count": 0,
        })
        proposal_by_product = defaultdict(lambda: {
            "quantity": 0.0,
            "proposal_count": 0,
            "stale_quantity": 0.0,
            "stale_proposal_count": 0,
        })
        stale_by_product = defaultdict(lambda: {
            "quantity": 0.0,
            "confirmed_order_quantity": 0.0,
            "proposal_quantity": 0.0,
        })

        confirmed_total = 0.0
        overdue_confirmed_total = 0.0
        proposal_total = 0.0
        stale_proposal_total = 0.0

        for order in self.sales_orders:
            status = order.get("status")
            if status not in ("accepted", "breached"):
                continue
            product_id = order.get("product_id")
            quantity = float(order.get("quantity", 0) or 0)
            confirmed_total += quantity
            confirmed_by_product[product_id]["quantity"] += quantity
            confirmed_by_product[product_id]["order_count"] += 1
            deadline = order.get("delivery_deadline")
            is_overdue = (
                status == "breached"
                or (deadline is not None and current_day > int(deadline))
            )
            if is_overdue:
                overdue_confirmed_total += quantity
                confirmed_by_product[product_id]["overdue_quantity"] += quantity
                confirmed_by_product[product_id]["overdue_order_count"] += 1
                stale_by_product[product_id]["quantity"] += quantity
                stale_by_product[product_id]["confirmed_order_quantity"] += quantity

        for proposal in proposal_source:
            if getattr(proposal, "status", None) != "pending":
                continue
            product_id = getattr(proposal, "product_id", None)
            quantity = float(getattr(proposal, "quantity", 0) or 0)
            proposal_total += quantity
            proposal_by_product[product_id]["quantity"] += quantity
            proposal_by_product[product_id]["proposal_count"] += 1
            proposed_delivery_round = getattr(proposal, "proposed_delivery_round", None)
            is_stale = (
                proposed_delivery_round is not None
                and current_day >= int(proposed_delivery_round)
            )
            if is_stale:
                stale_proposal_total += quantity
                proposal_by_product[product_id]["stale_quantity"] += quantity
                proposal_by_product[product_id]["stale_proposal_count"] += 1
                stale_by_product[product_id]["quantity"] += quantity
                stale_by_product[product_id]["proposal_quantity"] += quantity

        demand_total = sum(
            float(item.get("backlog_quantity", 0) or 0)
            for item in demand_backlog.get("by_product", {}).values()
        )
        lost_sales_total = sum(
            float(item.get("lost_sales_quantity", 0) or 0)
            for item in demand_backlog.get("by_product", {}).values()
        )

        return {
            "demand_backlog": {
                "total_quantity": demand_total,
                "lost_sales_quantity": lost_sales_total,
                "by_product": demand_backlog.get("by_product", {}),
            },
            "confirmed_order_backlog": {
                "total_quantity": confirmed_total,
                "overdue_quantity": overdue_confirmed_total,
                "by_product": dict(confirmed_by_product),
            },
            "proposal_backlog": {
                "total_quantity": proposal_total,
                "stale_quantity": stale_proposal_total,
                "by_product": dict(proposal_by_product),
            },
            "stale_backlog": {
                "total_quantity": overdue_confirmed_total + stale_proposal_total,
                "by_product": dict(stale_by_product),
            },
        }

    @with_response("adjust_sales_demand")
    def adjust_sales_demand(self, product_id: str, quantity: int, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        if product_id not in getattr(self.enterprise, "salable_products_idList", []):
            return self.error_response(
                response,
                "PRODUCT_NOT_SALABLE",
                f"企业 {self.enterprise.id} 不允许销售产品 {product_id}。可售产品: {getattr(self.enterprise, 'salable_products_idList', [])}"
            )

        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="sales")
        employee_count = hr_result.data.get("count", 0) 
        # TODO 后续再考虑企业间交易时的销售人数影响
        assigned_workers = 1
        if employee_count < assigned_workers:
            return self.error_response(response, "INSUFFICIENT_STAFF", f"人手不足。目标投入: {assigned_workers}，当前可用: {employee_count}")

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        current_time = self.enterprise.time_manager.get_day()
        inventory_manager = super().get_module_by_type("InventoryManager")
        detail_result = inventory_manager.get_inventory_detail(product_id)
        if not getattr(detail_result, "success", False):
            return self.error_response(response, "PRODUCT_NOT_FOUND", f"产品 {product_id} 不存在")
        stock = detail_result.data if isinstance(detail_result.data, dict) else {}
        pricing = self._resolve_b2b_min_price(product_id)

        data = self.enterprise.downstream_exchange.submit_sell_request(
            seller_company_id = self.enterprise.id,
            product_id = product_id,
            quantity = quantity,
            created_round = current_time,
            min_price = pricing["min_price"],
            #lead_time = 1,  TODO 交付周期后续再考虑
        )
        payload = asdict(data)
        payload["pricing_strategy"] = pricing
        return self.success_response(response, f"已在交易所更新销售需求，等待下游企业响应", payload)

    @with_response("develop_market")
    def develop_market(self, market_type: str,  assigned_workers: int, market_name: str = None, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        开发市场

        Args:
            market_type: 市场类型（"regional" 或 "international"）
            assigned_workers: 在这个市场投入的销售员人数
            market_name: 市场名称（可选）
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含开发结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="sales")
        employee_count = hr_result.data.get("count", 0) 

        if assigned_workers < self.config.MIN_DEVELOP_MARKET_STAFF:
            return self.error_response(
                response,
                "INVALID_WORKERS_COUNT",
                f"销售员人数必须大于等于 {self.config.MIN_DEVELOP_MARKET_STAFF}"
            )

        if employee_count < assigned_workers:
            return self.error_response(response, "INSUFFICIENT_STAFF", f"人手不足。目标投入: {assigned_workers}，当前可用: {employee_count}")

        # 2. 验证市场类型
        if market_type not in self.config.MARKET_DEVELOPMENT_CONFIGS:
            return self.error_response(response, "INVALID_MARKET_TYPE", f"无效的市场类型，请选择 'regional' 或 'international'")

        config = self.config.MARKET_DEVELOPMENT_CONFIGS[market_type]
        finance_manager = super().get_module_by_type("FinanceManager")

        # 3. 检查资金
        balance_result = finance_manager.get_balance()
        # 处理不同返回类型的情况
        if isinstance(balance_result, (int, float)):
            balance = balance_result
        elif hasattr(balance_result, 'data'):
            balance = balance_result.data.get("balance", 0) if isinstance(balance_result.data, dict) else 0
        elif isinstance(balance_result, dict):
            balance = balance_result.get("balance", 0)
        else:
            balance = 0
        if balance < config["cost"]:
            return self.error_response(response, "INSUFFICIENT_FUNDS", f"资金不足，需要 ¥{config['cost']:,}")

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        # 4. 创建市场标识并提前分配销售人员
        market_id = f"market_{self.next_market_id}"
        self.next_market_id += 1
        completion_time = self.enterprise.time_manager.get_day() + config["development_time"]

        if not market_name:
            market_name = f"{config['name']}_{market_id}"

        assign_result = hr_manager.assign_workers(
            "sales",
            market_id,
            assigned_workers
        )
        if not getattr(assign_result, "success", True):
            return self.error_response(
                response,
                "ASSIGN_WORKERS_ERROR",
                getattr(assign_result, "message", "市场开发人手分配失败")
            )

        # 5. 扣除开发费用
        result = finance_manager.add_cost(
            config["cost"],
            "market_cost",
            "market_development"
        )
        if not getattr(result, "success", True):
            hr_manager.release_workers('sales', market_id, assigned_workers, "cancelled")
            return self.error_response(
                response,
                "COST_RECORD_FAILED",
                getattr(result, "message", "市场开发成本记录失败")
            )

        self.markets[market_id] = {
            "market_id": market_id,
            "market_name": market_name,
            "market_type": market_type,
            "status": "developing",  # developing, active
            "development_start_time": self.enterprise.time_manager.get_day(),
            "completion_time": completion_time,
            "total_orders_received": 0,
            "total_orders_completed": 0,
            "total_revenue": 0.0,
            "assigned_workers": assigned_workers
        }

        # 6. 记录事件
        self._log_event({
            "type": "market_development_started",
            "market_id": market_id,
            "market_type": market_type,
            "completion_time": completion_time
        })

        # 设置成功响应
        return self.success_response(
            response,
            f"市场 {market_name} 开始开发，将于第 {completion_time} 个工作日 完成",
            {
                "market_id": market_id,
                "market_name": market_name,
                "market_type": market_type,
                "completion_time": completion_time
            }
        )

    @with_response("adjust_market_workers")
    def adjust_market_workers(self, market_id: str, adjust_type: str, adjust_nums: int,dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        调整指定市场中的人员分配（增加或减少）

        Args:
            market_id: 市场ID
            adjust_type: 调整类型（"increase" 或 "decrease"）
            adjust_nums: 调整数量数

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含完成开发的市场信息的统一响应对象
        """
        # 1. 验证市场是否存在
        if market_id not in self.markets:
            return self.error_response(response, "MARKET_NOT_FOUND", f"市场 {market_id} 不存在")
        
        # 2. 验证调整类型
        if adjust_type not in ["increase", "decrease"]:
            return self.error_response(response, "INVALID_ADJUST_TYPE", f"无效的调整类型，请选择 'increase' 或 'decrease'")
        # 3. 验证调整数量
        if adjust_nums < 1:
            return self.error_response(response, "INVALID_ADJUST_NUMS", f"调整数量必须大于等于 1")
        market = self.markets[market_id]
        market_workers = market["assigned_workers"]
        if adjust_type == "decrease":
            if adjust_nums > market_workers:
                return self.error_response(response, "INSUFFICIENT_WORKERS", f"当前市场 {market_id} 有 {market_workers} 个销售员，无法减少 {adjust_nums} 个")
        else:
            hr_manager = super().get_module_by_type("HRManager")
            hr_result = hr_manager.get_available_workers(department="sales")  
            employee_count = hr_result.data.get("count", 0) 
            if adjust_nums > employee_count:
                    return self.error_response(response, "INSUFFICIENT_WORKERS", f"当前销售部门的空闲员工只有{employee_count} 个，无法增加 {adjust_nums} 个")

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        
        # 4. 调整人员分配
        if adjust_type == "decrease":
            market_workers -= adjust_nums
            release_result = hr_manager.release_workers(
                'sales',
                market_id,
                adjust_nums,
                "cancelled"
            )
            if not getattr(release_result, "success", True):
                return self.error_response(
                    response,
                    "RELEASE_WORKERS_ERROR",
                    getattr(release_result, "message", "市场销售人员释放失败")
                )
        elif adjust_type == "increase":
            market_workers += adjust_nums
            assign_result = hr_manager.assign_workers(
                "sales",
                market_id,
                adjust_nums
            )
            if not getattr(assign_result, "success", True):
                return self.error_response(
                    response,
                    "ASSIGN_WORKERS_ERROR",
                    getattr(assign_result, "message", "市场销售人员分配失败")
                )
        self.markets[market_id]["assigned_workers"] = market_workers
        
        return self.success_response(response, "SUCCESS", f"成功调整市场 {market_id} 的销售员人数为 {market_workers}")

    @skip_dry_run_validation
    @with_response("check_market_development_completion")
    def check_market_development_completion(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        检查并激活已完成开发的市场（每个时间步开始时调用）

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含完成开发的市场信息的统一响应对象
        """

        completed_markets = []
        for market_id, market_data in self.markets.items():
            if (market_data["status"] == "developing" and
                self.enterprise.time_manager.get_day() >= market_data["completion_time"]):

                # 激活市场
                market_data["status"] = "active"
                completed_markets.append(market_id)
                
                inventory_manager = super().get_module_by_type("InventoryManager")
                inventory_overview = inventory_manager.get_inventory_overview()
                products = inventory_overview.data.get("products", [])
                self.enterprise.market_manager.register_market(market_id, self.enterprise, market_data["assigned_workers"], market_data["market_type"], products) 
                # 记录完成事件
                self._log_event({
                    "type": "market_development_completed",
                    "market_id": market_id,
                    "market_name": market_data["market_name"]
                })
        return self.success_response(
            response,
            f"成功检查并激活 {len(completed_markets)} 个已完成开发的市场",
            {
                "completed_markets": completed_markets,
                "total_completed": len(completed_markets)
            }
        )

    @with_response("get_market_info")
    def get_market_info(self, market_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取市场信息

        Args:
            market_id: 市场ID
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含市场信息的统一响应对象
        """
        market_data = self.markets.get(market_id)
        if market_data:
            return self.success_response(response, f"成功获取市场 {market_id} 的信息", market_data)
        else:
            return self.error_response(response, "MARKET_NOT_FOUND", f"市场 {market_id} 不存在")

    @with_response("get_all_markets")
    def get_all_markets(self, status_filter: Optional[str] = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取所有市场

        Args:
            status_filter: 状态过滤器（可选）
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含市场列表的统一响应对象
        """
        if status_filter:
            markets = [m for m in self.markets.values() if m["status"] == status_filter]
            message = f"成功获取状态为 {status_filter} 的市场 {len(markets)} 个"
        else:
            markets = list(self.markets.values())
            message = f"成功获取所有市场 {len(markets)} 个"

        return self.success_response(
            response,
            message,
            {
                "markets": markets,
                "total_count": len(markets),
                "status_filter": status_filter
            }
        )

    @with_response("get_active_markets")
    def get_active_markets(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取所有已激活的市场

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含已激活市场列表的统一响应对象
        """
        return self.get_all_markets(status_filter="active", response=response)

    # ========== 订单管理 ==========

    def receive_proposals(self):
        """
        接收交易所分发的潜在订单并创建待接收订单列表
        """
        self._refresh_proposal_views()

    def build_orders_from_exchange(self):
        """
        建立采购订单
        """
        exchange = self._get_exchange()
        if exchange is None:
            return
        existing_exchange_order_ids = {
            order.get("exchange_order_id")
            for order in self.sales_orders
            if order.get("exchange_order_id")
        }
        orders:List[Order] = exchange.get_confirm_orders_for_seller(self.enterprise.id)
        for order in orders:
            if order.order_id in existing_exchange_order_ids:
                continue
            response = self.create_order(
                order.product_id, order.quantity, order.agreed_price, order.buyer_company_id, order.planned_delivery_round, "b2b_sales")
            response_data = response.data
            order_id = response_data.get("order_id", None)
            if order_id:
                sales_order = self._find_order(order_id)
                if sales_order is not None:
                    sales_order["exchange_order_id"] = order.order_id
                    sales_order["proposal_id"] = order.proposal_id
                self.accept_order(order_id)
                existing_exchange_order_ids.add(order.order_id)


    @with_response("accept_proposal_order")
    def accept_proposal_order(self, proposal_id: str, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        接受采购订单

        Args:
            proposal_id: 订单ID
            response: 模块响应对象
        """
        self._refresh_proposal_views()

        # 1. 查找当前仍待销售侧响应的订单 inbox
        proposal = self._find_pending_proposal(proposal_id)
        if not proposal:
            exchange_proposal = self._get_exchange_proposal(proposal_id)
            if not exchange_proposal or not self._is_relevant_proposal(exchange_proposal):
                return self.error_response(response, "ORDER_NOT_FOUND", f"订单 {proposal_id} 不存在")
            if exchange_proposal.status != "pending":
                return self.error_response(response, "INVALID_ORDER_STATUS", f"订单状态为 {exchange_proposal.status}，无法接受")
            return self.error_response(response, "PROPOSAL_ALREADY_RESPONDED", f"订单 {proposal_id} 已完成销售侧响应")
        
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        
        # 3. 更新订单状态
        self.enterprise.downstream_exchange.handle_company_response(
            proposal_id,
            "accept",
            "seller"
        )
        self._refresh_proposal_views()
        return self.success_response(
            response,
            f"订单 {proposal_id} 已接受, 等待下游",
            {
                "proposal_id": proposal_id,
            }
        )

    @with_response("reject_proposal_order")
    def reject_proposal_order(self, proposal_id: str, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        拒绝采购订单

        Args:
            proposal_id: 订单ID
            response: 模块响应对象
        """
        self._refresh_proposal_views()

        # 1. 查找当前仍待销售侧响应的订单 inbox
        proposal = self._find_pending_proposal(proposal_id)
        if not proposal:
            exchange_proposal = self._get_exchange_proposal(proposal_id)
            if not exchange_proposal or not self._is_relevant_proposal(exchange_proposal):
                return self.error_response(response, "ORDER_NOT_FOUND", f"订单 {proposal_id} 不存在")
            if exchange_proposal.status != "pending":
                return self.error_response(response, "INVALID_ORDER_STATUS", f"订单状态为 {exchange_proposal.status}，无法拒绝")
            return self.error_response(response, "PROPOSAL_ALREADY_RESPONDED", f"订单 {proposal_id} 已完成销售侧响应")
        
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        
        # 3. 更新订单状态
        self.enterprise.downstream_exchange.handle_company_response(
            proposal_id,
            "reject",
            "seller"
        )
        self._refresh_proposal_views()
        backlog_event = {
            "round": self._get_current_day(),
            "proposal_id": proposal_id,
            "product_id": proposal.product_id,
            "source_id": proposal.buyer_company_id,
            "source_type": "b2b_sales",
            "quantity": proposal.quantity,
            "fulfilled_quantity": 0,
            "backlog_quantity": proposal.quantity,
            "lost_quantity": 0,
            "status": "proposal_rejected",
            "event_type": "proposal_rejected"
        }
        self.sales_events.append({
            "type": "proposal_rejected",
            **backlog_event
        })
        self._refresh_service_level_metrics()
        return self.success_response(
            response,
            f"订单 {proposal_id} 已拒绝",
            {
                "proposal_id": proposal_id,
            }
        )



    @with_response("create_order")
    def create_order(self, product_id: str, quantity: float, unit_price: float,
                    source_id: str, delivery_deadline: int, source_type: str = "market",
                    external_demand_id: str = None,
                    offer_expiry_day: int = None,
                    breach_penalty_enabled: bool = False,
                    breach_penalty_per_unit: float = 0.0,
                    breach_penalty_finance_category: str = "market_cost",
                    dry_run: bool = False,
                    response: ModuleResponse = None) -> ModuleResponse:
        """
        创建销售订单（通常由外部系统调用，如市场或B2B协商系统）

        Args:
            product_id: 产品ID
            quantity: 数量
            unit_price: 单价
            source_id: 来源ID（市场ID或买方企业ID）
            delivery_deadline: 交货截止时间步
            source_type: 来源类型（"market" 或 "b2b_sales"）
            external_demand_id: 外部需求唯一ID，用于防止同一轮消费者需求被重复创建

        Returns:
            ModuleResponse: 包含创建结果的统一响应对象
        """
        
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="sales")
        employee_count = hr_result.data.get("count", 0) 
        # if employee_count < 5:
        #     response.set_status(ResponseStatus.FAILED)
        #     response.add_error("INSUFFICIENT_STAFF", "人手不足，无法创建销售订单。至少需要: 5")
        #     response.set_message("无法创建销售订单")
        #     return response

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", {
                "product_id": product_id,
                "quantity": quantity,
                "source_id": source_id,
                "source_type": source_type,
                "delivery_deadline": delivery_deadline,
                "external_demand_id": external_demand_id,
                "offer_expiry_day": offer_expiry_day,
                "breach_penalty_enabled": breach_penalty_enabled,
                "breach_penalty_per_unit": breach_penalty_per_unit,
                "breach_penalty_finance_category": breach_penalty_finance_category
            })

        if external_demand_id:
            existing_order = next(
                (
                    order for order in self.sales_orders
                    if order.get("external_demand_id") == external_demand_id
                ),
                None
            )
            if existing_order:
                return self.success_response(
                    response,
                    f"外部需求 {external_demand_id} 已存在销售订单，跳过重复创建",
                    {
                        "order_id": existing_order["order_id"],
                        "order": existing_order,
                        "duplicate": True
                    }
                )

        order_id = f"SALE_ORDER_{self.next_order_id}"
        self.next_order_id += 1

        total_amount = unit_price * quantity

        sales_order = {
            "order_id": order_id,
            "product_id": product_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_amount": total_amount,
            "source_id": source_id,
            "source_type": source_type,
            "external_demand_id": external_demand_id,
            "created_time": self.enterprise.time_manager.get_day(),
            "delivery_deadline": delivery_deadline,
            "offer_expiry_day": offer_expiry_day,
            "status": "available",  # available, accepted, in_progress, completed, breached
            "accepted_time": None,
            "delivered_time": None,
            "on_time": None,
            "breach_penalty_enabled": bool(breach_penalty_enabled),
            "breach_penalty_per_unit": float(breach_penalty_per_unit or 0),
            "breach_penalty_finance_category": breach_penalty_finance_category or "market_cost",
            "breach_penalty_applied": False,
            "breach_penalty_amount": 0.0,
        }

        self.sales_orders.append(sales_order)
        self.sales_metrics["total_orders"] += 1
        self._record_downstream_demand(
            sales_order,
            event_type="created",
            status="available"
        )
        self._refresh_service_level_metrics()

        # 更新市场统计（如果是市场订单）
        if source_type in ("market", "external_market") and source_id in self.markets:
            self.markets[source_id]["total_orders_received"] += 1

        # 记录事件
        self._log_event({
            "type": "order_created",
            "order_id": order_id,
            "product_id": product_id,
            "quantity": quantity,
            "source_id": source_id
        })

        response.set_status(ResponseStatus.SUCCESS)
        response.set_message(f"销售订单 {order_id} 已创建")
        response.data = {
            "order_id": order_id,
            "order": sales_order
        }
        
        return response

    @with_response("accept_order")
    def accept_order(self, order_id: str, 
                     dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        接受销售订单

        Args:
            order_id: 订单ID
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含接受结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="sales")
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_PLACE_ORDER_STAFF:
            return self.error_response(response, "INSUFFICIENT_STAFF", f"人手不足，无法接受订单。至少需要: {self.config.MIN_PLACE_ORDER_STAFF}")

        # 2. 查找订单
        order = self._find_order(order_id)
        if not order:
            return self.error_response(response, "ORDER_NOT_FOUND", f"订单 {order_id} 不存在")
        

        # 3. 检查订单状态
        if order["status"] != "available":
            return self.error_response(response, "INVALID_ORDER_STATUS", f"订单状态为 {order['status']}，无法接受")
        offer_expiry_day = order.get("offer_expiry_day")
        current_day = self.enterprise.time_manager.get_day()
        if offer_expiry_day is not None and current_day > int(offer_expiry_day):
            if not dry_run:
                order["status"] = "expired"
            return self.error_response(response, "ORDER_OFFER_EXPIRED", f"订单 {order_id} 的报价已过期")
        
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        
        # 4. 验证库存（可选 - 根据业务策略决定）
        # 策略A：接受时不验证库存，只在交付时验证（推荐，符合按订单生产模式）
        # 策略B：接受时验证并预留库存（适合按库存销售模式）
        # 这里采用策略A，在交付时才验证库存，允许企业接单后安排生产

        # 5. 更新订单状态
        order["status"] = "accepted"
        order["accepted_time"] = current_day

        self.sales_metrics["accepted_orders"] += 1
        self._record_downstream_demand(
            order,
            event_type="accepted",
            status="accepted"
        )
        self._refresh_service_level_metrics()

        # 6. 记录事件
        self._log_event({
            "type": "order_accepted",
            "order_id": order_id,
            "product_id": order["product_id"],
            "quantity": order["quantity"]
        })

        immediate_delivery_result = None
        if order.get("delivery_deadline") is not None and current_day >= int(order["delivery_deadline"]):
            immediate_delivery_result = self._deliver_order(order)

        # 设置成功响应
        return self.success_response(
            response,
            f"订单 {order_id} 已接受",
            {
                "order_id": order_id,
                "delivery_deadline": order["delivery_deadline"],
                "immediate_delivery_result": immediate_delivery_result,
                "note": "请确保在交货截止期前准备足够的产品库存"
            }
        )

    @with_response("reject_order")
    def reject_order(self, order_id: str, 
                     reason: str = "", dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        拒绝销售订单

        Args:
            order_id: 订单ID
            reason: 拒绝原因
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含拒绝结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="sales")
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_PLACE_ORDER_STAFF:
            return self.error_response(response, "INSUFFICIENT_STAFF", f"人手不足，无法拒绝订单。至少需要: {self.config.MIN_PLACE_ORDER_STAFF}")

        # 2. 查找订单
        order = self._find_order(order_id)
        if not order:
            return self.error_response(response, "ORDER_NOT_FOUND", f"订单 {order_id} 不存在")

        if order["status"] != "available":
            return self.error_response(response, "INVALID_ORDER_STATUS", f"订单状态为 {order['status']}，无法拒绝")

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        

        # 3. 标记为已拒绝状态（保留历史记录）
        order["status"] = "rejected"
        self.sales_metrics["rejected_orders"] += 1
        is_external_market_order = order.get("source_type") in ("market", "external_market")
        lost_quantity = order["quantity"] if is_external_market_order else 0
        backlog_quantity = 0 if is_external_market_order else order["quantity"]
        self._record_downstream_demand(
            order,
            event_type="rejected",
            status="rejected",
            backlog_quantity=backlog_quantity,
            lost_quantity=lost_quantity
        )
        self._refresh_service_level_metrics()

        # 4. 记录事件
        self._log_event({
            "type": "order_rejected",
            "order_id": order_id,
            "reason": reason
        })

        # 设置成功响应
        return self.success_response(
            response,
            f"订单 {order_id} 已拒绝",
            {
                "order_id": order_id,
                "reason": reason
            }
        )

    @with_response("get_order_detail")
    def get_order_detail(self, order_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取订单详情

        Args:
            order_id: 订单ID
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含订单详情的统一响应对象
        """
        order = self._find_order(order_id)
        if order:
            return self.success_response(response, f"成功获取订单 {order_id} 的详情", order)
        else:
            return self.error_response(response, "ORDER_NOT_FOUND", f"订单 {order_id} 不存在")

    @with_response("get_all_sales_orders")
    def get_all_orders(self, status_filter: Optional[str] = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取所有订单

        Args:
            status_filter: 状态过滤器（可选）
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含订单列表的统一响应对象
        """
        if status_filter:
            orders = [order for order in self.sales_orders if order["status"] == status_filter]
            message = f"成功获取状态为 {status_filter} 的订单 {len(orders)} 个"
        else:
            orders = self.sales_orders.copy()
            message = f"成功获取所有订单 {len(orders)} 个"

        return self.success_response(
            response,
            message,
            {
                "orders": orders,
                "total_count": len(orders),
                "status_filter": status_filter
            }
        )

    @with_response("get_pending_orders")
    def get_available_orders(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取可接受的订单

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含可接受订单列表的统一响应对象
        """
        return self.get_all_orders(status_filter="available", response=response)

    @with_response("get_accepted_orders")
    def get_accepted_orders(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取已接受的订单

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含已接受订单列表的统一响应对象
        """
        return self.get_all_orders(status_filter="accepted", response=response)

    # ========== 订单交付 ==========

    @skip_dry_run_validation
    @with_response("check_deliverable_orders")
    def check_deliverable_orders(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        检查并交付到期的订单（每个时间步开始时调用）

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含交付结果列表的统一响应对象
        """
        
        delivery_results = []
        current_day = self.enterprise.time_manager.get_day()
        for order in self.sales_orders:
            expiry_day = order.get("offer_expiry_day")
            if (
                order.get("status") == "available"
                and expiry_day is not None
                and current_day > int(expiry_day)
            ):
                order["status"] = "expired"
                self.sales_metrics["expired_orders"] += 1
                quantity = float(order.get("quantity", 0) or 0)
                self._record_downstream_demand(
                    order,
                    event_type="expired",
                    status="expired",
                    backlog_quantity=0,
                    lost_quantity=quantity,
                )
                self._log_event({
                    "type": "order_offer_expired",
                    "order_id": order.get("order_id"),
                    "quantity": quantity,
                    "offer_expiry_day": expiry_day,
                })
        for order in self.sales_orders:
            if (order["status"] == "accepted" and
                order.get("delivery_deadline") is not None and
                current_day >= int(order["delivery_deadline"])):

                # 尝试交付
                result = self._deliver_order(order)
                delivery_results.append(result)

        self._refresh_service_level_metrics()
        return self.success_response(
            response,
            f"成功检查并处理 {len(delivery_results)} 个到期订单",
            {
                "delivery_results": delivery_results,
                "total_processed": len(delivery_results)
            }
        )

    # ========== B2B销售（简化版） ==========

    @with_response("send_quotation")
    @validate_positive("quantity")
    def generate_quotation(self, buyer_enterprise_id: str, product_id: str,
                          quantity: float, target_profit_rate: float = 0.2, response: ModuleResponse = None) -> ModuleResponse:
        """
        生成B2B报价（简化版，实际需要消息系统支持）

        Args:
            buyer_enterprise_id: 买方企业ID
            product_id: 产品ID
            quantity: 数量
            target_profit_rate: 目标利润率（默认20%）
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含报价结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="sales")
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_SEND_QUOTATION_STAFF:
            return self.error_response(response, "INSUFFICIENT_STAFF", f"人手不足，无法生成报价。至少需要: {self.config.MIN_SEND_QUOTATION_STAFF}")

        # 2. 检查库存
        inventory_manager = super().get_module_by_type("InventoryManager")
        # 处理不同返回类型的情况
        level_result = inventory_manager.get_inventory_level(product_id)
        if isinstance(level_result, (int, float)):
            available_inventory = level_result
        elif hasattr(level_result, 'data'):
            available_inventory = level_result.data.get("quantity", 0) if isinstance(level_result.data, dict) else 0
        elif isinstance(level_result, dict):
            available_inventory = level_result.get("quantity", 0)
        else:
            available_inventory = 0
        if available_inventory < quantity:
            return self.error_response(response, "INSUFFICIENT_INVENTORY", f"库存不足，无法报价。需要: {quantity}, 当前: {available_inventory}")

        # 3. 获取产品成本
        detail_result = inventory_manager.get_inventory_detail(product_id)
        # 处理不同返回类型的情况
        product_detail = detail_result if isinstance(detail_result, dict) else detail_result.data
        if not product_detail:
            return self.error_response(response, "PRODUCT_NOT_FOUND", f"产品 {product_id} 不存在")

        unit_cost = product_detail["unit_price"]

        # 4. 计算报价（成本加成定价）
        unit_price = unit_cost * (1 + target_profit_rate)
        total_amount = unit_price * quantity

        # 5. 创建报价记录
        quotation_id = f"quotation_{self.next_quotation_id}"
        self.next_quotation_id += 1

        quotation = {
            "quotation_id": quotation_id,
            "buyer_enterprise_id": buyer_enterprise_id,
            "product_id": product_id,
            "quantity": quantity,
            "unit_cost": unit_cost,
            "unit_price": unit_price,
            "total_amount": total_amount,
            "target_profit_rate": target_profit_rate,
            "status": "pending",  # pending, accepted, rejected
            "created_time": self.enterprise.time_manager.get_day()
        }

        self.quotations[quotation_id] = quotation

        # 6. 记录事件
        self._log_event({
            "type": "quotation_generated",
            "quotation_id": quotation_id,
            "buyer_enterprise_id": buyer_enterprise_id,
            "product_id": product_id,
            "unit_price": unit_price
        })

        # 设置成功响应
        return self.success_response(
            response,
            "报价已生成（简化版，实际需要消息系统支持）",
            {
                "quotation_id": quotation_id,
                "unit_price": unit_price,
                "total_amount": total_amount,
                "quotation": quotation
            }
        )

    @with_response("respond_to_quotation")
    @validate_positive("counter_price")
    def evaluate_counteroffer(self, quotation_id: str, counter_price: float,
                             min_acceptable_price: float = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        评估还价（简化版）

        Args:
            quotation_id: 报价ID
            counter_price: 还价金额
            min_acceptable_price: 最低可接受价格（可选）
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含评估结果的统一响应对象
        """
        if quotation_id not in self.quotations:
            return self.error_response(response, "QUOTATION_NOT_FOUND", f"报价 {quotation_id} 不存在")

        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(department="sales")
        employee_count = hr_result.data.get("count", 0)
        if employee_count < self.config.MIN_RESPOND_QUOTATION_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法响应报价。至少需要: {self.config.MIN_RESPOND_QUOTATION_STAFF}"
            )

        quotation = self.quotations[quotation_id]

        # 如果没有指定最低价格，使用成本价
        if min_acceptable_price is None:
            min_acceptable_price = quotation["unit_cost"]

        # 评估还价
        if counter_price >= min_acceptable_price:
            decision = "accept"
            message = f"可以接受还价 ¥{counter_price:.2f}"
        else:
            decision = "reject"
            message = f"还价 ¥{counter_price:.2f} 低于底价 ¥{min_acceptable_price:.2f}，拒绝"

        # 设置成功响应
        return self.success_response(
            response,
            message,
            {
                "quotation_id": quotation_id,
                "counter_price": counter_price,
                "min_acceptable_price": min_acceptable_price,
                "decision": decision
            }
        )


    @with_response("get_market_performance")
    def get_market_performance(self, market_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取市场绩效

        Args:
            market_id: 市场ID
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含市场绩效信息的统一响应对象
        """
        
        if market_id not in self.markets:
            return self.error_response(
                response,
                "MARKET_NOT_FOUND",
                f"市场 {market_id} 不存在",
                "无法获取市场绩效"
            )

        market = self.markets[market_id]

        # 统计该市场的订单
        market_orders = [o for o in self.sales_orders if o["source_id"] == market_id]
        completed_orders = [o for o in market_orders if o["status"] == "completed"]
        on_time_orders = [o for o in completed_orders if o.get("on_time", False)]

        performance_data = {
            "market_id": market_id,
            "market_name": market["market_name"],
            "market_type": market["market_type"],
            "status": market["status"],
            "total_orders": len(market_orders),
            "completed_orders": len(completed_orders),
            "on_time_orders": len(on_time_orders),
            "on_time_rate": len(on_time_orders) / len(completed_orders) if completed_orders else 0,
            "total_revenue": market["total_revenue"],
            "avg_order_value": market["total_revenue"] / len(completed_orders) if completed_orders else 0
        }
        
        return response.success(
            message=f"成功获取市场 {market_id} 的绩效信息",
            data=performance_data
        )

    @with_response("get_state")
    def get_state(self, response: ModuleResponse = None):
        """
        获取当前模块状态

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含模块状态的统一响应对象
        """
        self._refresh_proposal_views()
        self._refresh_service_level_metrics()
        # 获取当前销售状态
        sales_status = self._get_sales_status()
        grouped = defaultdict(list)
        for order in self.sales_orders:
            status = order.get("status", "unknown")
            # if status != "unknown" and status != "completed":
            if status != "unknown":
                grouped[status].append(order)
        state = {
            # "module_id": self.module_id,
            "module_type": self.module_type,
            "salable_products_idList": self.enterprise.salable_products_idList,
            "pending_proposals_count": len(self.proposals_list),
            "proposals_list": self._serialize_proposals(),
            "proposal_history": self._serialize_proposals(self.proposal_history),
            "sales_orders": dict(grouped),
            "markets": list(self.markets.values()),
            "demand_backlog": self._get_demand_backlog_status(),
            "backlog_breakdown": self._get_backlog_breakdown_status(),
            # "customers": [],  # B2B客户列表（如需要可从其他地方获取）
            "total_sales": sales_status.get("sales_metrics", {}).get("total_revenue", 0.0),
            "sales_metrics": sales_status.get("sales_metrics", {}),
            "orders_summary": sales_status.get("orders", {}),
            "markets_summary": sales_status.get("markets", {}),
            # "quotations": list(self.quotations.values())

        }
        return self.success_response(response, "成功获取模块状态", state)

    # ========== 报价查询方法 ==========

    @with_response("get_quotation_info")
    def get_quotation_info(self, quotation_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取报价信息

        Args:
            quotation_id: 报价ID
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含报价信息的统一响应对象
        """
        quotation_data = self.quotations.get(quotation_id)
        if quotation_data:
            return self.success_response(response, f"成功获取报价 {quotation_id} 的信息", quotation_data)
        else:
            return self.error_response(response, "QUOTATION_NOT_FOUND", f"报价 {quotation_id} 不存在")

    @with_response("get_all_quotations")
    def get_all_quotations(self, status_filter: Optional[str] = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取所有报价

        Args:
            status_filter: 状态过滤器（可选）
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含报价列表的统一响应对象
        """
        if status_filter:
            quotations = [q for q in self.quotations.values() if q["status"] == status_filter]
            message = f"成功获取状态为 {status_filter} 的报价 {len(quotations)} 个"
        else:
            quotations = list(self.quotations.values())
            message = f"成功获取所有报价 {len(quotations)} 个"

        return self.success_response(
            response,
            message,
            {
                "quotations": quotations,
                "total_count": len(quotations),
                "status_filter": status_filter
            }
        )

    @with_response("calculate_sales_revenue")
    def calculate_sales_revenue(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        计算销售收入

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含销售收入统计的统一响应对象
        """
        return self.success_response(
            response,
            f"成功计算销售收入，总收入: ¥{self.sales_metrics['total_revenue']:,.2f}",
            {
                "total_revenue": self.sales_metrics["total_revenue"],
                "total_quantity_sold": self.sales_metrics["total_quantity_sold"],
                "completed_orders": self.sales_metrics["completed_orders"],
                "average_order_value": self.sales_metrics["total_revenue"] / self.sales_metrics["completed_orders"] if self.sales_metrics["completed_orders"] > 0 else 0
            }
        )

    # ========== 内部方法 ==========

    def _find_order(self, order_id: str) -> Optional[Dict]:
        """查找订单"""
        for order in self.sales_orders:
            if order["order_id"] == order_id:
                return order
        return None

    def _log_event(self, event: Dict):
        """记录销售事件"""
        event["time_step"] = self.enterprise.time_manager.get_day()
        self.sales_events.append(event)

    def _refresh_service_level_metrics(self) -> None:
        demand_backlog = self._get_demand_backlog_status()
        demand_by_product = demand_backlog.get("by_product", {})
        self.sales_metrics["total_downstream_demand"] = sum(
            float(item.get("received_quantity", 0) or 0)
            for item in demand_by_product.values()
        )
        self.sales_metrics["fulfilled_downstream_demand"] = sum(
            float(item.get("fulfilled_quantity", 0) or 0)
            for item in demand_by_product.values()
        )
        self.sales_metrics["backlog_quantity"] = sum(
            float(item.get("backlog_quantity", 0) or 0)
            for item in demand_by_product.values()
        )
        self.sales_metrics["lost_sales_quantity"] = sum(
            float(item.get("lost_sales_quantity", 0) or 0)
            for item in demand_by_product.values()
        )

        backlog_breakdown = self._get_backlog_breakdown_status()
        confirmed_backlog = backlog_breakdown.get("confirmed_order_backlog", {})
        proposal_backlog = backlog_breakdown.get("proposal_backlog", {})
        stale_backlog = backlog_breakdown.get("stale_backlog", {})
        self.sales_metrics["confirmed_order_backlog_quantity"] = float(
            confirmed_backlog.get("total_quantity", 0) or 0
        )
        self.sales_metrics["overdue_confirmed_order_quantity"] = float(
            confirmed_backlog.get("overdue_quantity", 0) or 0
        )
        self.sales_metrics["proposal_backlog_quantity"] = float(
            proposal_backlog.get("total_quantity", 0) or 0
        )
        self.sales_metrics["stale_backlog_quantity"] = float(
            stale_backlog.get("total_quantity", 0) or 0
        )

        accepted_orders = self.sales_metrics.get("accepted_orders", 0) or 0
        if accepted_orders > 0:
            self.sales_metrics["order_fulfillment_rate"] = (
                self.sales_metrics.get("completed_orders", 0) / accepted_orders
            )
        else:
            self.sales_metrics["order_fulfillment_rate"] = 0.0

        completed_orders_list = [o for o in self.sales_orders if o["status"] == "completed"]
        if completed_orders_list:
            on_time_orders = [o for o in completed_orders_list if o.get("on_time", False)]
            self.sales_metrics["on_time_delivery_rate"] = (
                len(on_time_orders) / len(completed_orders_list)
            )
        else:
            self.sales_metrics["on_time_delivery_rate"] = 0.0

    def _apply_order_breach_penalty(self, order: Dict, reason: str) -> Dict:
        """Apply optional financial penalty when a configured order is breached."""
        if not order.get("breach_penalty_enabled"):
            return {"enabled": False, "applied": False, "reason": "disabled"}
        if order.get("breach_penalty_applied"):
            return {
                "enabled": True,
                "applied": False,
                "reason": "already_applied",
                "amount": order.get("breach_penalty_amount", 0.0),
            }

        penalty_per_unit = float(order.get("breach_penalty_per_unit", 0) or 0)
        quantity = float(order.get("quantity", 0) or 0)
        amount = penalty_per_unit * quantity
        if amount <= 0:
            return {"enabled": True, "applied": False, "reason": "non_positive_penalty", "amount": 0.0}

        finance_manager = super().get_module_by_type("FinanceManager")
        if finance_manager is None:
            return {"enabled": True, "applied": False, "reason": "finance_manager_unavailable", "amount": amount}

        category = order.get("breach_penalty_finance_category") or "market_cost"
        result = finance_manager.add_cost(
            amount,
            category,
            description=f"order_breach_penalty:{order.get('order_id')}:{reason}",
        )
        applied = bool(getattr(result, "success", False))
        effect = {
            "enabled": True,
            "applied": applied,
            "amount": amount,
            "penalty_per_unit": penalty_per_unit,
            "category": category,
            "reason": "applied" if applied else getattr(result, "message", "finance_cost_failed"),
        }
        if applied:
            order["breach_penalty_applied"] = True
            order["breach_penalty_amount"] = amount
            order["breach_penalty_effect"] = effect
            self._log_event({
                "type": "order_breach_penalty_applied",
                "order_id": order.get("order_id"),
                "amount": amount,
                "penalty_per_unit": penalty_per_unit,
                "category": category,
                "reason": reason,
            })
        return effect

    def _deliver_order(self, order: Dict) -> Dict:
        """
        交付订单（内部方法）

        Args:
            order: 订单记录

        Returns:
            dict: 交付结果
        """
        order_id = order["order_id"]
        product_id = order["product_id"]
        quantity = order["quantity"]
        inventory_manager = super().get_module_by_type("InventoryManager")
        # 1. 验证库存
        available_inventory = inventory_manager.get_inventory_level(product_id)
        quantity_available = available_inventory.data.get("quantity", 0)
        if quantity_available < quantity:
            # 时限已到且库存不足，标记为违约
            order["status"] = "breached"
            self.sales_metrics["breached_orders"] += 1

            self._log_event({
                "type": "order_breached",
                "order_id": order_id,
                "reason": "insufficient_inventory",
                "required": quantity,
                "available": quantity_available
            })
            self._record_downstream_demand(
                order,
                event_type="breached",
                status="breached",
                backlog_quantity=quantity
            )
            penalty_effect = self._apply_order_breach_penalty(order, "insufficient_inventory")
            self._refresh_service_level_metrics()

            return {
                "success": False,
                "order_id": order_id,
                "error": "库存不足，订单违约",
                "required": quantity,
                "available": quantity_available,
                "breach_penalty_effect": penalty_effect
            }
        # 2. 从仓库出库
        outbound_result = inventory_manager.remove_inventory(
            product_id, quantity, "sales"
        )

        if not outbound_result.success:
            # 出库失败，标记为违约
            order["status"] = "breached"
            self.sales_metrics["breached_orders"] += 1

            self._log_event({
                "type": "order_breached",
                "order_id": order_id,
                "reason": "outbound_failed"
            })
            self._record_downstream_demand(
                order,
                event_type="breached",
                status="breached",
                backlog_quantity=quantity
            )
            penalty_effect = self._apply_order_breach_penalty(order, "outbound_failed")
            self._refresh_service_level_metrics()

            return {
                "success": False,
                "order_id": order_id,
                "error": f"出库失败: {self._response_error_text(outbound_result)}",
                "breach_penalty_effect": penalty_effect
            }

        # 3. 记录销售收入
        revenue = order["total_amount"]
        finance_manager = super().get_module_by_type("FinanceManager")

        revenue_source = order["source_type"]
        if revenue_source == "external_market":
            revenue_source = "market"

        result = finance_manager.add_revenue(amount=revenue, source=revenue_source, order_id=order["order_id"])

        if not result.success:
            # 记录事件
            self._log_event({
                "type": "order_breached",
                "order_id": order_id,
                "reason": "finance_failed"
            })
            return {
                "success": False,
                "order_id": order_id,
                "error": f"记录销售收入失败: {self._response_error_text(result)}"
            }
        
        # 4. 更新订单状态
        order["status"] = "completed"
        order["delivered_time"] = self.enterprise.time_manager.get_day()
        order["on_time"] = (order["delivered_time"] <= order["delivery_deadline"])  # 提前或准时都算准时

        # 5. 更新指标
        self.sales_metrics["completed_orders"] += 1
        self.sales_metrics["total_revenue"] += revenue
        self.sales_metrics["total_quantity_sold"] += quantity
        self._record_downstream_demand(
            order,
            event_type="completed",
            status="completed",
            fulfilled_quantity=quantity
        )
        self._refresh_service_level_metrics()

        # 更新市场统计（如果是市场订单）
        if order["source_type"] == "market" and order["source_id"] in self.markets:
            market = self.markets[order["source_id"]]
            market["total_orders_completed"] += 1
            market["total_revenue"] += revenue

        # 6. 记录事件
        self._log_event({
            "type": "order_delivered",
            "order_id": order_id,
            "product_id": product_id,
            "quantity": quantity,
            "revenue": revenue,
            "on_time": order["on_time"]
        })

        return {
            "success": True,
            "order_id": order_id,
            "product_id": product_id,
            "quantity": quantity,
            "revenue": revenue,
            "on_time": order["on_time"],
            "message": f"订单 {order_id} 已交付，收入 ¥{revenue:,.2f}"
        }

    @staticmethod
    def _response_error_text(result: Any) -> str:
        if isinstance(result, dict):
            return str(result.get("error") or result.get("message") or result)
        message = getattr(result, "message", "")
        if message:
            return str(message)
        errors = getattr(result, "errors", None)
        if isinstance(errors, list) and errors:
            first_error = errors[0]
            if isinstance(first_error, dict):
                return str(first_error.get("message") or first_error)
            return str(first_error)
        return str(result)

    def _get_sales_status(self):
        """
        获取销售状态总览

        Args:
            response: 模块响应对象

        Returns:
            ModuleResponse: 包含销售状态信息的统一响应对象
        """
        # 统计订单状态
        orders_by_status = {
            "available": 0,
            "accepted": 0,
            "in_progress": 0,
            "completed": 0,
            "rejected": 0,
            "breached": 0
        }

        for order in self.sales_orders:
            status = order["status"]
            orders_by_status[status] = orders_by_status.get(status, 0) + 1

        # 统计市场状态
        markets_by_status = {
            "developing": 0,
            "active": 0
        }

        for market in self.markets.values():
            status = market["status"]
            markets_by_status[status] = markets_by_status.get(status, 0) + 1

        # 计算市场覆盖率
        self.sales_metrics["market_coverage_rate"] = (
            len(self.markets) / self.total_possible_markets
        )

        # 设置成功响应
        return {
                "orders": {
                    "total": len(self.sales_orders),
                    "by_status": orders_by_status
                },
                "markets": {
                    "total": len(self.markets),
                    "by_status": markets_by_status
                },
                "quotations": {
                    "total": len(self.quotations),
                    "pending": len([q for q in self.quotations.values() if q["status"] == "pending"])
                },
                "sales_metrics": self.sales_metrics
        }

    @with_response("generate_sales_analysis")
    def generate_sales_analysis(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        生成销售订单分析JSON

        Args:
            response: 响应对象，由装饰器自动注入

        Returns:
            ModuleResponse: 包含销售订单分析JSON的统一响应对象
        """
        try:
            # 订单状态分析
            orders_by_status = {}
            for order in self.sales_orders:
                status = order.get("status", "unknown")
                if status not in orders_by_status:
                    orders_by_status[status] = []
                orders_by_status[status].append(order)

            # 市场绩效分析
            market_performance = {}
            for market_id, market in self.markets.items():
                market_orders = [o for o in self.sales_orders if o.get("source_id") == market_id and o.get("source_type") == "market"]
                completed_orders = [o for o in market_orders if o.get("status") == "completed"]
                on_time_orders = [o for o in completed_orders if o.get("on_time", False)]
                
                total_revenue = sum(o.get("total_amount", 0) for o in completed_orders)
                avg_order_value = total_revenue / len(completed_orders) if completed_orders else 0
                on_time_rate = len(on_time_orders) / len(completed_orders) if completed_orders else 0
                
                market_performance[market_id] = {
                    "market_name": market.get("market_name"),
                    "market_type": market.get("market_type"),
                    "status": market.get("status"),
                    "total_orders": len(market_orders),
                    "completed_orders": len(completed_orders),
                    "on_time_orders": len(on_time_orders),
                    "on_time_rate": on_time_rate,
                    "total_revenue": total_revenue,
                    "avg_order_value": avg_order_value
                }

            # 产品销售分析
            product_sales_analysis = {}
            for order in self.sales_orders:
                product_id = order.get("product_id")
                if product_id:
                    if product_id not in product_sales_analysis:
                        product_sales_analysis[product_id] = {
                            "total_orders": 0,
                            "total_quantity": 0,
                            "total_revenue": 0,
                            "avg_unit_price": 0
                        }
                    product_sales_analysis[product_id]["total_orders"] += 1
                    product_sales_analysis[product_id]["total_quantity"] += order.get("quantity", 0)
                    product_sales_analysis[product_id]["total_revenue"] += order.get("total_amount", 0)

            # 计算平均单价
            for product_id, data in product_sales_analysis.items():
                if data["total_quantity"] > 0:
                    data["avg_unit_price"] = data["total_revenue"] / data["total_quantity"]

            # 收入分析
            total_revenue = self.sales_metrics.get("total_revenue", 0)
            completed_orders = len([o for o in self.sales_orders if o.get("status") == "completed"])
            avg_order_value = total_revenue / completed_orders if completed_orders > 0 else 0

            # 时间趋势分析
            orders_by_time = {}
            for order in self.sales_orders:
                created_time = order.get("created_time")
                if created_time:
                    if created_time not in orders_by_time:
                        orders_by_time[created_time] = []
                    orders_by_time[created_time].append(order)

            # B2B报价分析
            quotations_by_status = {}
            for quotation_id, quotation in self.quotations.items():
                status = quotation.get("status", "unknown")
                if status not in quotations_by_status:
                    quotations_by_status[status] = []
                quotations_by_status[status].append(quotation)

            # 获取当前时间
            try:
                timestamp = self.enterprise.time_manager.get_day() if hasattr(self.enterprise, 'time_manager') else 0
            except Exception:
                timestamp = 0

            # 构建分析JSON
            analysis_json = {
                "analysis_type": "销售订单分析",
                "timestamp": timestamp,
                "metrics": self.sales_metrics,
                "order_analysis": {
                    "by_status": {
                        status: {
                            "count": len(orders),
                            "total_revenue": sum(o.get("total_amount", 0) for o in orders),
                            "avg_order_value": sum(o.get("total_amount", 0) for o in orders) / len(orders) if orders else 0
                        }
                        for status, orders in orders_by_status.items()
                    },
                    "by_time": {
                        time_step: {
                            "count": len(orders),
                            "total_revenue": sum(o.get("total_amount", 0) for o in orders)
                        }
                        for time_step, orders in orders_by_time.items()
                    }
                },
                "market_analysis": market_performance,
                "product_analysis": product_sales_analysis,
                "revenue_analysis": {
                    "total_revenue": total_revenue,
                    "completed_orders": completed_orders,
                    "avg_order_value": avg_order_value,
                    "order_fulfillment_rate": self.sales_metrics.get("order_fulfillment_rate", 0),
                    "on_time_delivery_rate": self.sales_metrics.get("on_time_delivery_rate", 0)
                },
                "quotation_analysis": {
                    "by_status": {
                        status: {
                            "count": len(quotations),
                            "total_amount": sum(q.get("total_amount", 0) for q in quotations)
                        }
                        for status, quotations in quotations_by_status.items()
                    },
                    "total_quotations": len(self.quotations)
                },
                "insights": [
                    f"总销售订单数: {self.sales_metrics.get('total_orders', 0)}",
                    f"完成销售订单数: {self.sales_metrics.get('completed_orders', 0)}",
                    f"总收入: ¥{self.sales_metrics.get('total_revenue', 0):,.2f}",
                    f"总销售数量: {self.sales_metrics.get('total_quantity_sold', 0)}",
                    f"订单履约率: {self.sales_metrics.get('order_fulfillment_rate', 0):.2f}",
                    f"按时交付率: {self.sales_metrics.get('on_time_delivery_rate', 0):.2f}",
                    f"市场覆盖率: {self.sales_metrics.get('market_coverage_rate', 0):.2f}"
                ]
            }

            return self.success_response(
                response,
                "成功生成销售订单分析",
                {
                    "analysis": analysis_json
                }
            )
        except Exception as e:
            return self.error_response(
                response,
                "ANALYSIS_ERROR",
                f"生成销售订单分析失败: {e}"
            )
