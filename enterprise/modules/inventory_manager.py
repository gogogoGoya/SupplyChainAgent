"""
库存管理模块

负责企业库存相关的业务逻辑，包括库存跟踪、盘点、预警等功能
"""

import time
from typing import Dict, List, Optional
from enterprise.modules.base_business_module import EnhancedBaseModule
from enterprise.modules.response_model import ModuleResponse, ResponseStatus
from enterprise.modules.decorators import with_response, validate_positive
from config.module_config import InventoryConfig


class InventoryManager(EnhancedBaseModule):
    """
    库存管理器类
    处理企业库存相关的所有业务逻辑
    """
    def __init__(self, enterprise, initial_capacity: int = None, module_id=None, config: InventoryConfig = None):
        """
        初始化库存管理器

        Args:
            enterprise: 所属企业实例
            initial_capacity: 初始仓库容量（可选，默认从 config 读取）
            module_id: 模块ID（可选）
            config: 库存配置对象（可选，默认使用 InventoryConfig()）
        """
        # 使用配置或默认配置
        self.config = config or InventoryConfig()

        # 调用父类初始化方法
        super().__init__(
            enterprise,
            module_id or f"inventory_{enterprise.id}",
            self.config
        )

        # 库存跟踪
        self.inventory: Dict[str, Dict] = {}  # 库存信息 {item_id: {"quantity": float, "unit_price": float, "total_value": float}}
        self.inventory_history: Dict[str, List] = {}  # 库存变动历史 {item_id: [history_records]}

        # 库存策略
        self.reorder_points: Dict[str, float] = {}  # 再订购点 {item_id: reorder_point}
        self.safety_stocks: Dict[str, float] = {}  # 安全库存 {item_id: safety_stock}

        # 仓库管理
        self.total_capacity = initial_capacity or self.config.INITIAL_CAPACITY  # 总容量
        self.used_capacity = 0  # 已使用容量
        self.expansion_history = []  # 仓库扩建历史

        # 库存事件
        self.inventory_events: List[Dict] = []  # 库存事件日志

        # 库存指标
        self.inventory_metrics = {
            "total_items": 0,
            "total_value": 0.0,
            "inventory_turnover": 0.0,
            "stockout_rate": 0.0,
            "warehouse_utilization": 0.0,
            # "shrinkage_rate": 0.0
        }

        # 缺货统计（用于计算缺货率）
        self.stockout_count = 0  # 缺货次数
        self.total_outbound_requests = 0  # 总出库请求次数

        # 销售成本跟踪（用于计算库存周转率）
        # self.cost_of_goods_sold = 0.0  # 销售成本
        # self.average_inventory_value_history = []  # 平均库存价值历史

        # 缩水跟踪（用于计算缩水率）
        # self.total_shrinkage_value = 0.0  # 累计缩水价值
        # self.total_inventory_value_at_shrinkage = 0.0  # 发生缩水时的库存总价值

        # 维护成本跟踪
        self.maintenance_cost_rate = self.config.MAINTENANCE_COST_RATE  # 维护成本率（从 config 读取）
        self.total_maintenance_cost = 0.0  # 累计维护成本
        self.maintenance_cost_history = []  # 维护成本历史记录

        self.operating_cost_rate = self.config.OPERATING_COST_RATE  # 运营成本率（从 config 读取）
        self.total_operating_cost = 0.0  # 累计运营成本
        self.operating_cost_history = []  # 运营成本历史记录

        # 模块类型标识
        self.module_type = "InventoryManager"

        # 单位转换表：外部单位 -> SU（写死配置，不提供动态修改）
        # 格式: {unit_name: {"to_su": ratio, "from_su": inverse_ratio}}
        # 例如: {"malt": {"to_su": 0.01, "from_su": 100}} 表示 100 malt = 1 SU
        self.unit_conversion_table: Dict[str, Dict[str, float]] = {}

        # 默认单位映射（写死配置）
        # 100 Malt = 1 SU, 10 Hops = 1 SU, 5 Yeast = 1 SU, 1 Beer = 1 SU
        self._initialize_default_unit_mappings()

    @with_response("add_inventory")
    @validate_positive("quantity")
    @validate_positive("purchase_price")
    def add_inventory(self, item_id: str, quantity: float, purchase_price: float, item_type: str, dry_run: bool = False,response: ModuleResponse = None) -> ModuleResponse:
        """
        添加入库

        装饰器说明：
        - @with_response: 自动创建响应对象、异常处理
        - @validate_positive: 自动验证quantity > 0 和 purchase_price > 0

        Args:
            item_id: 物料ID（如果包含单位信息，如 "malt_1"，会自动检测并转换）
            quantity: 数量（外部单位，会自动转换为SU）
            purchase_price: 采购单价（由装饰器验证 > 0）
            item_type: "raw_material" 或 "product"
            dry_run: 是否为测试运行
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 入库结果的统一响应对象

        **代码实现**:
        - 验证数量 > 0
        - 自动从物料ID中检测单位（如 "malt_1" → "malt"）
        - 将外部单位转换为SU进行内部计算
        - 检查仓库容量是否充足
        - 使用加权平均法计算新单价（原库存为0时直接使用新价格）
        - 更新库存和仓库使用量（使用SU）
        - 记录入库历史和事件
        """
        # 自动从物料ID中检测单位
        original_unit = self._get_item_original_unit(item_id)
        normalized_item_type = self._normalize_item_type(item_id, item_type)

        # 如果检测到单位，转换为SU
        su_quantity = self._to_su_quantity(quantity, original_unit)
        
        # 1. 检查仓库容量
        if self.used_capacity + su_quantity > self.total_capacity:
            remaining_capacity = self.total_capacity - self.used_capacity
            return self.error_response(
                response,
                "INSUFFICIENT_CAPACITY",
                f"容量不足，无法入库。剩余容量: {remaining_capacity}, 需要: {su_quantity} SU"
            )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        
        # 2. 更新库存（查找或创建）
        if item_id not in self.inventory:
            self.inventory[item_id] = {
                "quantity": 0,
                "unit_price": 0.0,
                "total_value": 0.0,
                "item_type": normalized_item_type,
                "original_unit": original_unit,  # 保存检测到的原始单位
                "last_updated": self.enterprise.time_manager.get_day()
            }

        # 3. 计算加权平均单价
        current_stock = self.inventory[item_id]
        if current_stock.get("original_unit") is None:
            current_stock["original_unit"] = original_unit
        current_stock["item_type"] = self._normalize_item_type(
            item_id,
            normalized_item_type,
            current_stock.get("item_type")
        )
        original_value = current_stock["total_value"]
        current_pricing_quantity = self._to_pricing_quantity(
            current_stock["quantity"],
            current_stock.get("original_unit")
        )
        inbound_pricing_quantity = self._to_pricing_quantity(
            su_quantity,
            current_stock.get("original_unit")
        )
        new_value = inbound_pricing_quantity * purchase_price
        new_total_quantity = current_stock["quantity"] + su_quantity
        new_total_pricing_quantity = current_pricing_quantity + inbound_pricing_quantity

        # 如果原库存为0，直接使用新价格；否则使用加权平均
        if current_pricing_quantity == 0:
            new_unit_price = purchase_price
        else:
            new_unit_price = (original_value + new_value) / new_total_pricing_quantity

        # 4. 更新库存记录（内部使用SU）
        current_stock["quantity"] = new_total_quantity
        current_stock["unit_price"] = new_unit_price
        current_stock["total_value"] = original_value + new_value
        current_stock["last_updated"] = self.enterprise.time_manager.get_day()

        # 5. 更新仓库使用量（使用SU）
        self.used_capacity += su_quantity

        # 6. 记录历史和事件
        self._record_inventory_transaction(item_id, su_quantity, "inbound", "purchase/production")
        self._update_inventory_metrics()

        # 返回成功响应
        response_data = {
            "item_id": item_id,
            "new_quantity": current_stock["quantity"],
            "new_unit_price": new_unit_price,
            "financial": {
                "total_value": current_stock["total_value"]
            },
            "inventory": {
                "item_type": current_stock["item_type"],
                "last_updated": current_stock["last_updated"]
            }
        }
        
        return self.success_response(
            response,
            f"物料 {item_id} 成功入库 {su_quantity} SU ({quantity} {original_unit if original_unit else 'SU'})",
            response_data
        )

    @with_response("check_capacity")
    @validate_positive("quantity")
    def check_capacity(self, item_id: str, quantity: float, response: ModuleResponse = None) -> ModuleResponse:
        """
        验证是否可以添加指定数量的物品而不超过仓库容量

        Args:
            item_id: 物品ID
            quantity: 要添加的数量（由装饰器验证 > 0）
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 容量检查结果的统一响应对象

        **代码实现**:
        - 检查仓库使用量 + 要添加数量是否 <= 总容量
        - 简单的容量验证方法，用于约束检查
        """
        original_unit = self._get_item_original_unit(item_id)
        su_quantity = self._to_su_quantity(quantity, original_unit)

        # 执行容量检查
        is_valid = (self.used_capacity + su_quantity) <= self.total_capacity

        # 返回成功响应
        return self.success_response(
            response,
            f"容量检查{'通过' if is_valid else '未通过'}",
            {
                "item_id": item_id,
                "quantity": quantity,
                "su_quantity": su_quantity,
                "used_capacity": self.used_capacity,
                "total_capacity": self.total_capacity,
                "is_valid": is_valid
            }
        )

    @with_response("remove_inventory")
    @validate_positive("quantity")
    def remove_inventory(self, item_id: str, quantity: float, reason: str,
                        response: ModuleResponse = None) -> ModuleResponse:
        """
        移除库存

        Args:
            item_id: 物料ID（如果包含单位信息，如 "malt_1"，会自动检测并转换）
            quantity: 数量（外部单位，会自动转换为SU）
            reason: 移除原因 (e.g., "production", "sales")
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 出库结果的统一响应对象

        **代码实现**:
        - 验证数量 > 0
        - 自动从物料ID中检测单位（如 "malt_1" → "malt"）
        - 将外部单位转换为SU进行内部计算
        - 检查物料是否存在
        - 检查库存是否充足
        - 更新库存和仓库使用量（使用SU）
        - 记录出库历史
        - 统计出库请求次数和缺货次数（用于计算缺货率）
        """
        # 自动从物料ID中检测单位
        original_unit = self._get_item_original_unit(item_id)

        # 如果检测到单位，转换为SU
        su_quantity = self._to_su_quantity(quantity, original_unit)
        
        # 1. 检查库存是否存在
        resolved_item_id = self._resolve_item_id(item_id)
        if not resolved_item_id:
            return self.error_response(
                response,
                "ITEM_NOT_FOUND",
                f"物料 {item_id} 不存在"
            )

        # 2. 检查库存是否充足
        current_stock = self.inventory[resolved_item_id]
        self.total_outbound_requests += 1  # 记录出库请求

        if current_stock["quantity"] < su_quantity:
            # 记录缺货
            self.stockout_count += 1
            self._update_stockout_rate()
            return self.error_response(
                response,
                "INSUFFICIENT_INVENTORY",
                f"库存不足。需要: {su_quantity} SU, 当前: {current_stock['quantity']} SU"
            )

        # 3. 更新库存（使用SU）
        current_stock["quantity"] -= su_quantity
        remaining_pricing_quantity = self._to_pricing_quantity(
            current_stock["quantity"],
            current_stock.get("original_unit")
        )
        current_stock["total_value"] = remaining_pricing_quantity * current_stock["unit_price"]
        current_stock["last_updated"] = self.enterprise.time_manager.get_day()

        # 4. 更新仓库使用量（使用SU）
        self.used_capacity -= su_quantity

        # 5. 记录历史和事件（使用SU）
        self._record_inventory_transaction(resolved_item_id, -su_quantity, "outbound", reason)
        self._update_inventory_metrics()

        # 返回成功响应
        response_data = {
            "item_id": resolved_item_id,
            "remaining_quantity": current_stock["quantity"],
            "financial": {
                "total_value": current_stock["total_value"]
            },
            "inventory": {
                "last_updated": current_stock["last_updated"]
            },
            "transaction": {
                "reason": reason,
                "quantity": su_quantity,
                "unit": "SU"
            }
        }
        
        
        return self.success_response(
            response,
            f"物料 {resolved_item_id} 成功出库 {su_quantity} SU ({quantity} {original_unit if original_unit else 'SU'})",
            response_data
        )

    @with_response("expand_warehouse")
    def expand_warehouse(self, size: int, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        扩建仓库

        Args:
            size: 扩建规模 (1000, 2000, 5000)
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 扩建结果的统一响应对象

        **代码实现**:
        - 验证扩建规模是否有效
        - 检查企业资金是否充足
        - 通过财务模块扣除费用
        - 立即增加仓库容量（无建设周期）
        - 记录扩建历史
        """
        costs = self.config.WAREHOUSE_EXPANSION_COSTS
        if size not in costs:
            return self.error_response(
                response,
                "INVALID_SIZE",
                "无效的扩建规模，请选择size 1000, 2000, 或 5000"
            )
        needed_workers = self.config.WAREHOUSE_EXPANSION_WORKER_REQUIREMENTS.get(size, 1)
        base_cost = costs[size]
        cost_multiplier = self._long_horizon_cost_multiplier(
            "warehouse_expansion_cost_multiplier"
        )
        cost = base_cost * cost_multiplier
        finance_manager = super().get_module_by_type("FinanceManager")
        hr_manager = super().get_module_by_type("HRManager")

        # 与财务模块交互
        if finance_manager.cash < cost:
            return self.error_response(
                response,
                "INSUFFICIENT_FUNDS",
                f"资金不足，无法扩建。至少需要: {cost}"
            )

        # 检查人力资源
        hr_result = hr_manager.get_available_workers(department="inventory")
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < needed_workers:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法扩建。至少需要: {needed_workers}"
            )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        assignment_id = f"warehouse_expand_{self.enterprise.time_manager.get_day()}_{size}"
        assign_result = hr_manager.assign_workers("inventory", assignment_id, needed_workers)
        if not getattr(assign_result, "success", True):
            return self.error_response(
                response,
                "ASSIGN_WORKERS_ERROR",
                getattr(assign_result, "message", "仓库扩建人手分配失败")
            )

        # 扣除费用
        cost_result = finance_manager.add_cost(cost, "inventory_cost", "warehouse expand")
        if not getattr(cost_result, "success", True):
            hr_manager.release_workers("inventory", assignment_id, needed_workers, "cancelled")
            return self.error_response(
                response,
                "COST_RECORD_FAILED",
                getattr(cost_result, "message", "仓库扩建成本记录失败")
            )

        # 增加容量
        self.total_capacity += size

        # 记录历史
        self.expansion_history.append({
            "time_step": self.enterprise.time_manager.get_day(),
            "expanded_size": size,
            "new_total_capacity": self.total_capacity,
            "cost": cost
        })

        self._update_inventory_metrics()
        hr_manager.release_workers("inventory", assignment_id, needed_workers, "completed")

        # 返回成功响应
        return self.success_response(
            response,
            f"仓库成功扩建 {size} 单位，新总容量为 {self.total_capacity}",
            {
                "expanded_size": size,
                "new_total_capacity": self.total_capacity,
                "cost": cost,
                "warehouse": {
                    "total_capacity": self.total_capacity,
                    "used_capacity": self.used_capacity,
                    "utilization": self.inventory_metrics["warehouse_utilization"]
                },
                "financial": {
                    "cost": cost
                }
            }
        )

    @with_response("get_inventory_level")
    def get_inventory_level(self, item_id: str, response: ModuleResponse = None, convert_to_original_unit: bool = True) -> ModuleResponse:
        """
        获取单个物料的库存数量

        Args:
            item_id: 物料ID
            response: 响应对象（由装饰器注入）
            convert_to_original_unit: 是否转换回原始单位（默认True）

        Returns:
            ModuleResponse: 包含物料库存数量的统一响应对象

        **代码实现**:
        - 参数：`item_id` - 物料ID
        - 返回：ModuleResponse 包含库存数量（物料不存在时返回0）
        - 如果 convert_to_original_unit=True 且物料有 original_unit，则转换回原始单位
        """
        # 获取库存数据
        resolved_item_id = self._resolve_item_id(item_id)
        inventory_data = self.inventory.get(resolved_item_id, {}) if resolved_item_id else {}
        su_quantity = inventory_data.get("quantity", 0)
        
        # 如果有原始单位且需要转换，则转换回原始单位
        original_unit = inventory_data.get("original_unit")
        quantity = su_quantity
        unit = None
        
        if convert_to_original_unit and original_unit and original_unit in self.unit_conversion_table:
            quantity = self._from_su_quantity(su_quantity, original_unit)
            unit = original_unit
        
        # 返回成功响应
        response_data = {
            "item_id": resolved_item_id or item_id,
            "quantity": quantity
        }
        
        if unit:
            response_data["unit"] = unit
            response_data["su_quantity"] = su_quantity
        
        return self.success_response(
            response,
            f"成功获取物料 {resolved_item_id or item_id} 的库存数量",
            response_data
        )

    @with_response("get_inventory_detail")
    def get_inventory_detail(self, item_id: str, response: ModuleResponse = None, convert_to_original_unit: bool = True) -> ModuleResponse:
        """
        获取单个物料的详细库存信息，包括安全库存、再订购点、预警状态等

        Args:
            item_id: 物料ID
            response: 响应对象（由装饰器注入）
            convert_to_original_unit: 是否转换回原始单位（默认True）

        Returns:
            ModuleResponse: 包含物料详细信息的统一响应对象

        **代码实现**:
        - 参数：`item_id` - 物料ID
        - 返回：ModuleResponse 包含完整物料信息
        - 返回字段：
          - `quantity`: 当前库存数量（转换回原始单位）
          - `unit`: 原始单位（如果有）
          - `su_quantity`: SU数量（内部使用）
          - `unit_price`: 单位价格
          - `total_value`: 总价值
          - `item_type`: 物料类型
          - `last_updated`: 最后更新时间步
          - `safety_stock`: 安全库存
          - `reorder_point`: 再订购点
          - `is_low_stock`: 是否低于安全库存
          - `is_below_reorder_point`: 是否低于再订购点
        """
        resolved_item_id = self._resolve_item_id(item_id)
        if not resolved_item_id:
            return self.error_response(
                response,
                "ITEM_NOT_FOUND",
                f"物料 {item_id} 不存在"
            )

        data = self.inventory[resolved_item_id]
        su_quantity = data["quantity"]
        
        # 转换回原始单位
        original_unit = data.get("original_unit")
        quantity = su_quantity
        unit = None
        
        if convert_to_original_unit and original_unit and original_unit in self.unit_conversion_table:
            quantity = self._from_su_quantity(su_quantity, original_unit)
            unit = original_unit

        safety_stock = self.safety_stocks.get(item_id, 0)
        reorder_point = self.reorder_points.get(item_id, 0)
        display_safety_stock = self._from_su_quantity(safety_stock, original_unit) if unit else safety_stock
        display_reorder_point = self._from_su_quantity(reorder_point, original_unit) if unit else reorder_point

        detail = {
            "item_id": resolved_item_id,
            "quantity": quantity,
            "unit_price": data["unit_price"],
            "total_value": data["total_value"],
            "item_type": data["item_type"],
            "last_updated": data["last_updated"],
            "safety_stock": display_safety_stock,
            "reorder_point": display_reorder_point,
            "is_low_stock": data["quantity"] < safety_stock,
            "is_below_reorder_point": data["quantity"] < reorder_point
        }
        
        if unit:
            detail["unit"] = unit
            detail["su_quantity"] = su_quantity

        # 返回成功响应
        return self.success_response(
            response,
            f"成功获取物料 {resolved_item_id} 的详细信息",
            detail
        )

    @with_response("get_inventory_overview")
    def get_inventory_overview(self, response: ModuleResponse = None, convert_to_original_unit: bool = True) -> ModuleResponse:
        """
        获取库存总览

        Args:
            response: 响应对象（由装饰器注入）
            convert_to_original_unit: 是否转换回原始单位（默认True）

        Returns:
            ModuleResponse: 包含库存总览信息的统一响应对象

        **代码实现**:
        - 返回：ModuleResponse 包含以下字段
          - `raw_materials`: List[Dict] - 原材料列表
          - `products`: List[Dict] - 产品列表
          - `total_inventory_value`: float - 库存总价值
          - `warehouse_info`: Dict - 仓库信息（总容量、已使用、使用率）
          - 每个物料包含：`id`, `quantity`, `unit` (原始单位), `su_quantity`, `unit_price`, `total_value`, `last_updated`
        """
        raw_materials = []
        products = []
        stocks = []
        for item_id, data in self.inventory.items():
            su_quantity = data["quantity"]
            original_unit = data.get("original_unit")
            quantity = su_quantity
            unit = None
            
            # 转换回原始单位
            if convert_to_original_unit and original_unit and original_unit in self.unit_conversion_table:
                quantity = self._from_su_quantity(su_quantity, original_unit)
                unit = original_unit
            
            item_info = {
                "id": item_id,
                "item_id": item_id,
                "quantity": quantity,
                "unit_price": data["unit_price"],
                "total_value": data["total_value"],
                "last_updated": data["last_updated"]
            }
            
            if unit:
                item_info["unit"] = unit
                item_info["su_quantity"] = su_quantity
            
            stocks.append(item_info)
            if data["item_type"] == "raw_material":
                raw_materials.append(item_info)
            else:
                products.append(item_info)

        # 返回成功响应
        return self.success_response(
            response,
            "成功获取库存总览",
            {
                "stocks": stocks,
                "raw_materials": raw_materials,
                "products": products,
                "total_inventory_value": self.inventory_metrics["total_value"],
                "warehouse_info": {
                    "total_capacity": self.total_capacity,
                    "used_capacity": self.used_capacity,
                    "utilization": self.inventory_metrics["warehouse_utilization"]
                }
            }
        )

    @with_response("check_low_stock_levels")
    def check_low_stock_levels(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        检查低库存物料
        
        Args:
            response: 响应对象（由装饰器注入）
        
        Returns:
            ModuleResponse: 包含低库存物料列表的统一响应对象
        
        **代码实现**: 
        - 返回：ModuleResponse 包含低库存物料列表
        - 每项包含：`item_id`, `current_quantity`, `safety_stock`, `shortfall`（缺口）
        """
        low_stock_items = []
        for item_id, safety_stock in self.safety_stocks.items():
            if item_id not in self.inventory:
                continue
            current_su_quantity = self.inventory[item_id]["quantity"]
            original_unit = self.inventory[item_id].get("original_unit")
            if current_su_quantity < safety_stock:
                current_quantity = self._from_su_quantity(current_su_quantity, original_unit)
                display_safety_stock = self._from_su_quantity(safety_stock, original_unit)
                low_stock_items.append({
                    "item_id": item_id,
                    "current_quantity": current_quantity,
                    "safety_stock": display_safety_stock,
                    "shortfall": display_safety_stock - current_quantity,
                    "unit": original_unit or "SU"
                })
        
        # 返回成功响应
        return self.success_response(
            response,
            f"成功检查低库存，发现 {len(low_stock_items)} 个低库存物料",
            {
                "low_stock_items": low_stock_items,
                "total_low_stock_items": len(low_stock_items)
            }
        )
    
    @with_response("check_reorder_points")
    def check_reorder_points(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        检查再订购点

        Args:
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 包含需要再订购的物料列表的统一响应对象

        **代码实现**:
        - 返回：ModuleResponse 包含需要再订购的物料列表
        - 每项包含：`item_id`, `current_quantity`, `reorder_point`, `shortfall`（缺口）
        """
        reorder_items = []
        for item_id, reorder_point in self.reorder_points.items():
            if item_id not in self.inventory:
                continue
            current_su_quantity = self.inventory[item_id]["quantity"]
            original_unit = self.inventory[item_id].get("original_unit")
            if current_su_quantity < reorder_point:
                current_quantity = self._from_su_quantity(current_su_quantity, original_unit)
                display_reorder_point = self._from_su_quantity(reorder_point, original_unit)
                reorder_items.append({
                    "item_id": item_id,
                    "current_quantity": current_quantity,
                    "reorder_point": display_reorder_point,
                    "shortfall": display_reorder_point - current_quantity,
                    "unit": original_unit or "SU"
                })

        # 返回成功响应
        return self.success_response(
            response,
            f"成功检查再订购点，发现 {len(reorder_items)} 个需要再订购的物料",
            {
                "reorder_items": reorder_items,
                "total_reorder_items": len(reorder_items)
            }
        )
    
    @with_response("get_capacity_warning")
    def get_capacity_warning(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取容量预警信息

        Args:
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 包含容量预警信息的统一响应对象

        **代码实现**:
        - 返回：ModuleResponse 包含预警级别、使用率、剩余容量、建议等
        - 预警级别：
          - `"low"`: 使用率 < 30%
          - `"normal"`: 30% ≤ 使用率 < 75%
          - `"warning"`: 75% ≤ 使用率 < 90%
          - `"critical"`: 使用率 ≥ 90%
        """
        utilization = self.inventory_metrics["warehouse_utilization"]
        remaining_capacity = self.total_capacity - self.used_capacity

        if utilization < self.config.CAPACITY_LOW_THRESHOLD:
            level = "low"
            message = "仓库使用率较低，可能存在过度投资"
            suggestion = "考虑优化库存管理或减少仓库容量"
        elif utilization < self.config.CAPACITY_WARNING_THRESHOLD:
            level = "normal"
            message = "仓库使用率正常"
            suggestion = "继续保持"
        elif utilization < self.config.CAPACITY_CRITICAL_THRESHOLD:
            level = "warning"
            message = "仓库使用率较高，建议考虑扩建"
            suggestion = f"建议扩建仓库，当前剩余容量: {remaining_capacity}"
        else:
            level = "critical"
            message = "仓库使用率严重过高，需要紧急扩建"
            suggestion = f"紧急扩建仓库，当前剩余容量: {remaining_capacity}"

        # 返回成功响应
        return self.success_response(
            response,
            f"容量预警：{message}",
            {
                "level": level,
                "utilization": utilization,
                "used_capacity": self.used_capacity,
                "total_capacity": self.total_capacity,
                "remaining_capacity": remaining_capacity,
                "message": message,
                "suggestion": suggestion
            }
        )
    
    @with_response("set_inventory_policy")
    def set_inventory_policy(self, item_id: str, reorder_point: float, safety_stock: float,
                            dry_run: bool = False,
                            response: ModuleResponse = None) -> ModuleResponse:
        """
        设置库存策略
        
        Args:
            item_id: 物料ID
            reorder_point: 再订购点（由装饰器验证 >= 0）
            safety_stock: 安全库存（由装饰器验证 >= 0）
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 设置结果的统一响应对象
        
        **代码实现**: 
        - 参数：`item_id` - 物料ID, `reorder_point` - 再订购点, `safety_stock` - 安全库存
        - 返回：ModuleResponse 包含设置结果
        - 验证物料存在和参数有效性
        """
        resolved_item_id = self._resolve_item_id(item_id)
        if not resolved_item_id:
            return self.error_response(
                response,
                "ITEM_NOT_FOUND",
                f"物料 {item_id} 不存在，无法设置策略"
            )

        if reorder_point < 0 or safety_stock < 0:
            return self.error_response(
                response,
                "INVALID_POLICY",
                "再订购点和安全库存必须大于等于0"
            )
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "item_id": resolved_item_id,
                    "policy": {
                        "reorder_point": reorder_point,
                        "safety_stock": safety_stock
                    }
                }
            )

        original_unit = self.inventory[resolved_item_id].get("original_unit")
        self.reorder_points[resolved_item_id] = self._to_su_quantity(reorder_point, original_unit)
        self.safety_stocks[resolved_item_id] = self._to_su_quantity(safety_stock, original_unit)
        
        # 返回成功响应
        return self.success_response(
            response,
            f"已为物料 {item_id} 设置库存策略",
            {
                "item_id": resolved_item_id,
                "policy": {
                    "reorder_point": reorder_point,
                    "safety_stock": safety_stock
                }
            }
        )

    @with_response("get_inventory_history")
    def get_inventory_history(self, item_id: str, limit: int = 100,
                              response: ModuleResponse = None) -> ModuleResponse:
        """
        获取物料的库存变动历史

        Args:
            item_id: 物料ID
            limit: 返回记录数量限制（默认100，0表示返回全部）
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 包含库存变动历史记录的统一响应对象

        **代码实现**:
        - 参数：`item_id` - 物料ID, `limit` - 返回记录数量限制
        - 返回：ModuleResponse 包含历史记录列表（最近的记录）
        - 每条记录包含：`time_step`, `quantity_change`, `type`, `reason`, `new_quantity`
        - 数据结构：`self.inventory_history` - Dict[str, List[Dict]]
        """
        if item_id not in self.inventory_history:
            # 返回空历史
            return self.success_response(
                response,
                f"物料 {item_id} 没有库存历史记录",
                {
                    "item_id": item_id,
                    "history": [],
                    "total_records": 0
                }
            )

        history = self.inventory_history[item_id]
        result_history = history[-limit:] if limit > 0 else history

        # 返回成功响应
        return self.success_response(
            response,
            f"成功获取物料 {item_id} 的库存历史记录",
            {
                "item_id": item_id,
                "history": result_history,
                "total_records": len(history),
                "returned_records": len(result_history),
                "limit": limit
            }
        )
    
    # @with_response("calculate_inventory_turnover")
    # def calculate_inventory_turnover(self, cost_of_goods_sold: Optional[float] = None,
    #                                  response: ModuleResponse = None) -> ModuleResponse:
    #     """
    #     计算库存周转率

    #     Args:
    #         cost_of_goods_sold: 销售成本，如果为None则使用内部跟踪的值
    #         response: 响应对象（由装饰器注入）

    #     Returns:
    #         ModuleResponse: 包含库存周转率的统一响应对象

    #     **代码实现**:
    #     - 参数：`cost_of_goods_sold` - 销售成本（可选，默认使用内部跟踪值）
    #     - 返回：ModuleResponse 包含库存周转率
    #     - 关键逻辑：
    #       - 使用历史库存价值计算平均值（最近100个时间步）
    #       - 周转率 = 销售成本 / 平均库存价值
    #       - 自动更新 `inventory_metrics["inventory_turnover"]`
    #     """
    #     if cost_of_goods_sold is None:
    #         cost_of_goods_sold = self.cost_of_goods_sold

    #     # 计算平均库存价值
    #     current_value = self.inventory_metrics["total_value"]

    #     # 如果有历史记录，计算平均值
    #     if len(self.average_inventory_value_history) > 0:
    #         avg_value = sum(self.average_inventory_value_history) / len(self.average_inventory_value_history)
    #         # 加入当前值
    #         avg_value = (avg_value + current_value) / 2
    #     else:
    #         avg_value = current_value

    #     # 计算周转率
    #     turnover = 0.0
    #     if avg_value > 0:
    #         turnover = cost_of_goods_sold / avg_value
    #         self.inventory_metrics["inventory_turnover"] = turnover

    #     # 返回成功响应
    #     return self.success_response(
    #         response,
    #         "成功计算库存周转率",
    #         {
    #             "turnover": turnover,
    #             "cost_of_goods_sold": cost_of_goods_sold,
    #             "average_inventory_value": avg_value,
    #             "current_inventory_value": current_value
    #         }
    #     )
    
    # def record_sales_cost(self, cost: float):
    #     """
    #     记录销售成本
        
    #     Args:
    #         cost: 销售成本
        
    #     **代码实现**: 
    #     - 参数：`cost` - 销售成本
    #     - 关键逻辑：
    #       - 累加销售成本到 `cost_of_goods_sold`
    #       - 记录当前库存价值到历史列表
    #       - 保持历史记录在100个时间步内
    #     """
    #     self.cost_of_goods_sold += cost
    #     # 记录当前库存价值到历史
    #     self.average_inventory_value_history.append(self.inventory_metrics["total_value"])
    #     # 保持历史记录在合理范围内（最近100个时间步）
    #     if len(self.average_inventory_value_history) > 100:
    #         self.average_inventory_value_history.pop(0)

    @with_response("conduct_inventory_count")
    def conduct_inventory_count(self, item_id: str, actual_quantity: float,
                               response: ModuleResponse = None) -> ModuleResponse:
        """
        执行库存盘点并调整

        Args:
            item_id: 盘点的物料ID
            actual_quantity: 实际盘点数量（由装饰器验证 >= 0）
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 盘点调整结果的统一响应对象

        **代码实现**:
        - 参数：`item_id` - 物料ID, `actual_quantity` - 实际盘点数量
        - 返回：ModuleResponse 包含盘点结果、差异等信息
        - 关键逻辑：
          1. 验证物料是否存在
          2. 计算差异（实际数量 - 系统数量）
          3. 如果差异为正（增加），先检查仓库容量是否充足
          4. 更新库存数量和总价值
          5. 更新仓库使用容量
          6. 记录盘点历史（类型为 "adjustment"）
          7. 如果差异为负（缩水），计算并更新缩水率
        - 缩水率计算：累计缩水价值 / 累计库存价值（包括已缩水部分）
        """
        # 1. 验证物料是否存在
        resolved_item_id = self._resolve_item_id(item_id)
        if not resolved_item_id:
            return self.error_response(
                response,
                "ITEM_NOT_FOUND",
                f"物料 {item_id} 不存在"
            )

        if actual_quantity < 0:
            return self.error_response(
                response,
                "INVALID_QUANTITY",
                "盘点数量必须大于等于0"
            )

        # 2. 获取系统数量和计算差异
        original_unit = self.inventory[resolved_item_id].get("original_unit")
        actual_su_quantity = self._to_su_quantity(actual_quantity, original_unit)
        system_quantity = self.inventory[resolved_item_id]["quantity"]
        variance = actual_su_quantity - system_quantity
        shrinkage_value = 0.0

        if variance == 0:
            # 盘点数量与系统一致，无需调整
            system_quantity_display = self._from_su_quantity(system_quantity, original_unit)
            return self.success_response(
                response,
                "盘点数量与系统一致，无需调整",
                {
                    "item_id": resolved_item_id,
                    "system_quantity": system_quantity_display,
                    "system_su_quantity": system_quantity,
                    "actual_quantity": actual_quantity,
                    "actual_su_quantity": actual_su_quantity,
                    "variance": 0,
                    "variance_su": 0,
                    "unit": original_unit or "SU"
                }
            )

        # 3. 检查容量（如果盘点数量增加）
        if variance > 0:
            if self.used_capacity + variance > self.total_capacity:
                return self.error_response(
                    response,
                    "INSUFFICIENT_CAPACITY",
                    f"盘点数量增加后超出容量。当前使用: {self.used_capacity}, 增加: {variance}, 总容量: {self.total_capacity}"
                )

        # 4. 更新库存
        self.inventory[resolved_item_id]["quantity"] = actual_su_quantity
        pricing_quantity = self._to_pricing_quantity(actual_su_quantity, original_unit)
        self.inventory[resolved_item_id]["total_value"] = pricing_quantity * self.inventory[resolved_item_id]["unit_price"]

        # 5. 更新容量
        self.used_capacity += variance

        # 6. 记录调整
        self._record_inventory_transaction(resolved_item_id, variance, "adjustment", "physical_count")
        self._update_inventory_metrics()

        # # 7. 计算缩水（如果盘点数量减少）
        # shrinkage_value = 0.0
        # if variance < 0:
        #     shrinkage_value = abs(variance) * self.inventory[item_id]["unit_price"]
        #     self.total_shrinkage_value += shrinkage_value
        #     # 使用更新后的库存总价值
        #     total_value = self.inventory_metrics["total_value"]
        #     self.total_inventory_value_at_shrinkage += total_value + shrinkage_value

        #     # 更新缩水率：累计缩水价值 / 累计库存价值（包括已缩水部分）
        #     if self.total_inventory_value_at_shrinkage > 0:
        #         self.inventory_metrics["shrinkage_rate"] = self.total_shrinkage_value / self.total_inventory_value_at_shrinkage

        # 返回成功响应
        system_quantity_display = self._from_su_quantity(system_quantity, original_unit)
        variance_display = self._from_su_quantity(variance, original_unit)
        return self.success_response(
            response,
            f"库存已调整，差异为 {variance}",
            {
                "item_id": resolved_item_id,
                "system_quantity": system_quantity_display,
                "system_su_quantity": system_quantity,
                "actual_quantity": actual_quantity,
                "actual_su_quantity": actual_su_quantity,
                "variance": variance_display,
                "variance_su": variance,
                "shrinkage_value": shrinkage_value,
                "current_quantity": actual_quantity,
                "current_value": self.inventory[resolved_item_id]["total_value"],
                "unit": original_unit or "SU"
            }
        )

    # ===== 维护成本管理方法 =====

    def _active_runtime_injection_config(self) -> Dict:
        runtime_config = getattr(self.enterprise, "runtime_injection_config", None)
        if not isinstance(runtime_config, dict):
            controller = getattr(self.enterprise, "controller", None)
            runtime_config = getattr(controller, "runtime_injection_config", None)
        if isinstance(runtime_config, dict):
            return runtime_config
        try:
            from config.simulation_preset_config import get_runtime_injection_config

            return get_runtime_injection_config() or {}
        except Exception:
            return {}

    def _long_horizon_cost_multiplier(self, key: str) -> float:
        policy = self._active_runtime_injection_config().get("long_horizon_cost_policy") or {}
        target_ids = set(policy.get("target_enterprise_ids") or [])
        if not policy.get("enabled") or (
            target_ids and getattr(self.enterprise, "id", None) not in target_ids
        ):
            return 1.0
        try:
            return max(0.0, float(policy.get(key, 1.0)))
        except (TypeError, ValueError):
            return 1.0

    def _is_inventory_cost_exempt(self) -> bool:
        """
        判断当前企业是否命中库存持有成本豁免策略。
        """
        try:
            runtime_config = self._active_runtime_injection_config()
            policy = runtime_config.get("inventory_cost_exemption_policy") or {}
            if not policy.get("enabled"):
                return False

            target_enterprise_ids = set(policy.get("target_enterprise_ids") or [])
            if self.enterprise.id in target_enterprise_ids:
                return True

            target_role_tags = set(policy.get("target_role_tags") or [])
            enterprise_role_tags = set(getattr(self.enterprise, "role_tags", []) or [])
            return bool(target_role_tags and (enterprise_role_tags & target_role_tags))
        except Exception:
            return False

    @with_response("calculate_inventory_cost")
    def calculate_inventory_cost(self, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        计算当前时间步的维护成本

        Args:
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 包含当期成本、库存价值等信息的统一响应对象

        **代码实现**:
        - 获取当前库存总价值
        - 计算维护成本 = 库存价值 × 成本率
        - 累加到总维护成本
        - 记录到历史列表
        - 通过财务模块记录支出
        - 更新库存指标
        """
        if self._is_inventory_cost_exempt():
            return self.success_response(
                response,
                "库存持有成本豁免已生效，本轮不结转库存成本",
                {
                    "maintenance_cost": 0.0,
                    "operating_cost": 0.0,
                    "inventory_value": self.inventory_metrics["total_value"],
                    "cost_rate": self.maintenance_cost_rate,
                    "operating_cost_rate": self.operating_cost_rate,
                    "inventory_cost_exempt": True
                }
            )

        # 1. 获取当前库存总价值
        inventory_value = self.inventory_metrics["total_value"]

        # 2. 计算维护成本
        maintenance_multiplier = self._long_horizon_cost_multiplier(
            "inventory_maintenance_cost_multiplier"
        )
        operating_multiplier = self._long_horizon_cost_multiplier(
            "warehouse_operating_cost_multiplier"
        )
        effective_maintenance_rate = self.maintenance_cost_rate * maintenance_multiplier
        effective_operating_rate = self.operating_cost_rate * operating_multiplier
        maintenance_cost = inventory_value * effective_maintenance_rate
        operating_cost = self.total_capacity * effective_operating_rate
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "maintenance_cost": maintenance_cost,
                    "operating_cost": operating_cost,
                    "inventory_value": inventory_value,
                    "cost_rate": effective_maintenance_rate,
                    "operating_cost_rate": effective_operating_rate,
                    "cost_policy_multipliers": {
                        "maintenance": maintenance_multiplier,
                        "operating": operating_multiplier,
                    },
                }
            )

        # 3. 累加到总维护成本
        self.total_maintenance_cost += maintenance_cost

        # 4. 记录到历史列表
        maintenance_history_record = {
            "time_step": self.enterprise.time_manager.get_day(),
            "inventory_value": inventory_value,
            "cost_rate": effective_maintenance_rate,
            "maintenance_cost": maintenance_cost,
            "total_cost": self.total_maintenance_cost
        }
        self.maintenance_cost_history.append(maintenance_history_record)
        finance_manager = super().get_module_by_type("FinanceManager")

        #计算运营成本

        #累加到总运营成本
        self.total_operating_cost += operating_cost

        #记录到历史列表
        operating_history_record = {
            "time_step": self.enterprise.time_manager.get_day(),
            "total_capacity": self.total_capacity,
            "cost_rate": effective_operating_rate,
            "operating_cost": operating_cost,
            "total_cost": self.total_operating_cost
        }
        self.operating_cost_history.append(operating_history_record)


        # 通过财务模块记录支出（如果有财务模块）
        if maintenance_cost > 0:
            try:
                result = finance_manager.add_cost(
                    maintenance_cost,
                    "inventory_cost",
                    "inventory_maintenance"
                )
                # 处理不同返回类型的情况
                if hasattr(result, "success"):
                    if not result.success:
                        response.add_warning("COST_RECORD_WARNING", f"Failed to record maintenance cost: {result.message}")
                else:
                    if result:
                        response.add_warning("COST_RECORD_WARNING", f"Failed to record maintenance cost: {result}")
            except Exception as e:
                response.add_error("COST_RECORD_ERROR", f"Error recording maintenance cost: {e}")

        if operating_cost > 0:
            try:
                result = finance_manager.add_cost(
                    operating_cost,
                    "inventory_cost",
                    "inventory_operating"
                )
                # 处理不同返回类型的情况
                if hasattr(result, "success"):
                    if not result.success:
                        response.add_warning("COST_RECORD_WARNING", f"Failed to record operating cost: {result.message}")
                else:
                    if result:
                        response.add_warning("COST_RECORD_WARNING", f"Failed to record operating cost: {result}")
            except Exception as e:
                response.add_error("COST_RECORD_ERROR", f"Error recording operating cost: {e}")



        # 6. 更新库存指标
        self._update_inventory_metrics()

        # 返回成功响应
        return self.success_response(
            response,
            f"维护成本已计算: ¥{maintenance_cost:.2f}",
            {
                "maintenance_cost": maintenance_cost,
                "operating_cost": operating_cost,   
                "inventory_value": inventory_value,
                "cost_rate": effective_maintenance_rate,
                "operating_cost_rate": effective_operating_rate,
                "cost_policy_multipliers": {
                    "maintenance": maintenance_multiplier,
                    "operating": operating_multiplier,
                },
                "total_maintenance_cost": self.total_maintenance_cost,
                "maintenance_history_record": maintenance_history_record,
                "operating_history_record": operating_history_record
            }
        )

    @with_response("set_maintenance_cost_rate")
    def set_maintenance_cost_rate(self, rate: float, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        设置维护成本率

        Args:
            rate: 新的成本率（0-1之间的小数）
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 设置结果的统一响应对象

        **代码实现**:
        - 验证成本率必须 >= 0 且 <= 1
        - 更新成本率
        - 返回成功状态
        """
        # 验证成本率范围
        if rate < 0 or rate > 1:
            return self.error_response(
                response,
                "INVALID_RATE",
                "维护成本率必须在0到1之间"
            )
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "old_rate": self.maintenance_cost_rate,
                    "new_rate": rate
                }
            )

        # 更新成本率
        old_rate = self.maintenance_cost_rate
        self.maintenance_cost_rate = rate

        # 返回成功响应
        return self.success_response(
            response,
            f"维护成本率已设置为 {rate*100:.2f}%",
            {
                "old_rate": old_rate,
                "new_rate": rate,
                "message": f"维护成本率已从 {old_rate*100:.2f}% 更新为 {rate*100:.2f}%"
            }
        )

    @with_response("get_maintenance_cost_summary")
    def get_maintenance_cost_summary(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取维护成本汇总

        Args:
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 包含总成本、平均成本、成本率等信息的统一响应对象

        **代码实现**:
        - 返回总成本、当前成本率、历史记录数、平均每时间步成本
        """
        # 计算维护成本汇总信息
        history_count = len(self.maintenance_cost_history)
        average_cost_per_step = (
            self.total_maintenance_cost / history_count
            if history_count > 0 else 0.0
        )

        # 返回成功响应
        return self.success_response(
            response,
            "成功获取维护成本汇总",
            {
                "total_cost": self.total_maintenance_cost,
                "current_rate": self.maintenance_cost_rate,
                "history_count": history_count,
                "average_cost_per_step": average_cost_per_step
            }
        )

    @with_response("get_maintenance_cost_history")
    def get_maintenance_cost_history(self, limit: int = 100, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取维护成本历史

        Args:
            limit: 返回记录数量限制（默认100，0表示返回全部）
            response: 响应对象（由装饰器注入）

        Returns:
            ModuleResponse: 包含历史记录列表的统一响应对象

        **代码实现**:
        - 参数：`limit` - 返回记录数量限制
        - 返回：ModuleResponse 包含历史记录列表（最近的记录）
        """
        # 获取历史记录
        if limit == 0 or limit < 0:
            history = self.maintenance_cost_history
        else:
            history = self.maintenance_cost_history[-limit:]

        # 返回成功响应
        return self.success_response(
            response,
            f"成功获取维护成本历史，共返回 {len(history)} 条记录",
            {
                "history": history,
                "total_records": len(self.maintenance_cost_history),
                "returned_records": len(history),
                "limit": limit
            }
        )
               
    @with_response("set_capacity")
    # 兼容旧接口
    def set_capacity(self, capacity: int, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        设置仓库容量

        Args:
            capacity: 新的仓库容量
            response: 响应对象，由装饰器自动注入

        Returns:
            ModuleResponse: 设置结果的统一响应对象
        """
        
        # 验证容量是否有效
        if capacity <= 0:
            return self.error_response(
                response,
                "INVALID_CAPACITY",
                "容量必须大于0",
                "Failed to set warehouse capacity"
            )
        
        # 如果新容量小于已使用容量，不允许设置
        if capacity < self.used_capacity:
            return self.error_response(
                response,
                "INSUFFICIENT_CAPACITY",
                f"新容量不能小于已使用容量。已使用容量: {self.used_capacity}, 新容量: {capacity}",
                "Failed to set warehouse capacity"
            )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        
        # 更新容量
        old_capacity = self.total_capacity
        self.total_capacity = capacity
        self._update_inventory_metrics()
        return self.success_response(
            response,
            f"仓库容量已设置为 {capacity}",
            {
                "old_capacity": old_capacity,
                "new_capacity": capacity,
                "used_capacity": self.used_capacity,
                "utilization": self.inventory_metrics["warehouse_utilization"]
            }
        )
    
    @with_response("initialize_inventory")
    def initialize_inventory(self, raw_materials: Dict = None, products: Dict = None,
                             dry_run: bool = False,
                             response: ModuleResponse = None) -> ModuleResponse:
        """
        初始化库存
        
        Args:
            raw_materials: 原材料库存数据 {item_id: {"quantity": float, "unit_price": float}} 或简写数量
            products: 产品库存数据 {item_id: {"quantity": float, "unit_price": float}} 或简写数量
            
            格式说明：
            - 简写: {"item_id": 100} 或 {"item_id": {"quantity": 100, "unit_price": 10.5}}
            - 自动从物料ID中检测单位（如 "malt_1" → "malt"）
            
        Returns:
            ModuleResponse: 初始化结果的统一响应对象
        """
        
        raw_materials = raw_materials or {}
        products = products or {}
        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "raw_material_count": len(raw_materials),
                    "product_count": len(products)
                }
            )

        initialized_count = 0
        errors = []
        all_items = []
        
        # 初始化原材料库存
        for item_id, item_data in raw_materials.items():
            quantity, unit_price, err = _parse_item_data(item_id, item_data)
            if err:
                errors.append(f"原材料 {err}")
                continue
            
            if quantity > 0:
                result = self.add_inventory(item_id, quantity, unit_price, "raw_material")
                all_items.append({
                    "item_id": item_id,
                    "item_type": "raw_material",
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "success": result.success
                })
                if result.success:
                    initialized_count += 1
                else:
                    errors.append(f"原材料 {item_id} 初始化失败: {result.errors[0].message if result.errors else '未知错误'}")
        
        # 初始化产品库存
        for item_id, item_data in products.items():
            quantity, unit_price, err = _parse_item_data(item_id, item_data)
            if err:
                errors.append(f"产品 {err}")
                continue
            
            if quantity > 0:
                result = self.add_inventory(item_id, quantity, unit_price, "product")
                all_items.append({
                    "item_id": item_id,
                    "item_type": "product",
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "success": result.success
                })
                if result.success:
                    initialized_count += 1
                else:
                    errors.append(f"产品 {item_id} 初始化失败: {result.errors[0].message if result.errors else '未知错误'}")
        
        # 设置响应状态和数据
        total_items = len(raw_materials) + len(products)
        if len(errors) == 0:
            response.set_status(ResponseStatus.SUCCESS)
            response.set_message(f"库存初始化完成，成功初始化 {initialized_count} 个项目")
        elif initialized_count > 0:
            response.set_status(ResponseStatus.PARTIAL)
            response.set_message(f"库存初始化部分成功，成功初始化 {initialized_count} 个项目，{len(errors)} 个失败")
        else:
            response.set_status(ResponseStatus.FAILED)
            response.set_message(f"库存初始化失败，所有 {total_items} 个项目均未成功初始化")
        
        # 添加错误信息
        for error in errors:
            response.add_error("INITIALIZATION_ERROR", error)
        
        response.data = {
            "initialized_count": initialized_count,
            "total_items": total_items,
            "raw_materials_count": len(raw_materials),
            "products_count": len(products),
            "errors": errors,
            "all_items": all_items
        }
        return response
    
    @with_response("get_state")
    def get_state(self, response: ModuleResponse = None, convert_to_original_unit: bool = True) -> ModuleResponse:
        """
        获取当前模块状态

        Args:
            response: 响应对象（由装饰器注入）
            convert_to_original_unit: 是否转换回原始单位（默认True）

        Returns:
            ModuleResponse: 包含模块状态的统一响应对象
        """
        try:
            self._update_inventory_metrics()
            
            # 计算总库存数量和价值（使用SU）
            total_inventory = 0
            total_value = 0

            for item_id, inventory_data in self.inventory.items():
                quantity = inventory_data.get("quantity", 0)
                unit_price = inventory_data.get("unit_price", 0)
                total_inventory += quantity
                total_value += inventory_data.get("total_value", 0)

            # 构建库存物品详细列表
            inventory_items = []
            for item_id, inventory_data in self.inventory.items():
                su_quantity = inventory_data.get("quantity", 0)
                original_unit = inventory_data.get("original_unit")
                quantity = su_quantity
                unit = None
                safety_stock = self.safety_stocks.get(item_id, 0)
                reorder_point = self.reorder_points.get(item_id, 0)
                
                # 转换回原始单位
                if convert_to_original_unit and original_unit and original_unit in self.unit_conversion_table:
                    quantity = self._from_su_quantity(su_quantity, original_unit)
                    unit = original_unit
                display_safety_stock = self._from_su_quantity(safety_stock, original_unit) if unit else safety_stock
                display_reorder_point = self._from_su_quantity(reorder_point, original_unit) if unit else reorder_point
                
                item_info = {
                    "item_id": item_id,
                    "item_type": inventory_data.get("item_type", "unknown"),
                    "quantity": quantity,
                    "unit_price": inventory_data.get("unit_price", 0),
                    "total_value": inventory_data.get("total_value", 0),
                    "last_updated": inventory_data.get("last_updated", 0),
                    "safety_stock": display_safety_stock,
                    "reorder_point": display_reorder_point,
                    "is_low_stock": su_quantity < safety_stock,
                    "is_below_reorder_point": su_quantity < reorder_point
                }
                
                if unit:
                    item_info["unit"] = unit
                    item_info["su_quantity"] = su_quantity
                
                inventory_items.append(item_info)

            state_data = {
                # "module_id": self.module_id,
                "module_type": self.module_type,
                "total_inventory": total_inventory,
                "total_inventory_su": total_inventory,
                "total_value": total_value,
                "warehouse_capacity": self.total_capacity,
                "used_capacity": self.used_capacity,
                "warehouse_utilization": self.inventory_metrics["warehouse_utilization"],
                "total_maintenance_cost":self.total_maintenance_cost,
                "total_operating_cost":self.total_operating_cost,
                "inventory_metrics": dict(self.inventory_metrics),
                "inventory_items": inventory_items,
                "event_count": len(self.inventory_events)
            }

            return self.success_response(
                response,
                "成功获取模块状态",
                state_data
            )
        except Exception as e:
            # 处理异常情况
            return self.error_response(
                response,
                "STATE_ERROR",
                f"获取模块状态失败: {e}"
            )

        # ===== 私有方法 =====

    def _record_inventory_transaction(self, item_id: str, quantity: float, trans_type: str, reason: str):
        """
        记录库存交易历史
        
        **代码实现**: 
        - 私有方法，由公开方法调用
        - 记录库存变动历史到 `inventory_history`
        - 调用 `_log_inventory_event()` 记录事件
        """
        if item_id not in self.inventory_history:
            self.inventory_history[item_id] = []
        
        self.inventory_history[item_id].append({
            "time_step": self.enterprise.time_manager.get_day(),
            "quantity_change": quantity,
            "type": trans_type,
            "reason": reason,
            "new_quantity": self.inventory[item_id]["quantity"]
        })
        
        # 记录事件
        self._log_inventory_event({
            "type": f"inventory_{trans_type}",
            "item_id": item_id,
            "quantity": abs(quantity),
            "reason": reason
        })

    def _update_inventory_metrics(self):
        """
        更新库存关键指标
        
        **代码实现**: 
        - 私有方法，由公开方法调用
        - 更新 `total_items`, `total_value`, `warehouse_utilization`
        - 如果已记录销售成本，自动更新 `inventory_turnover`
        """
        total_value = sum(item["total_value"] for item in self.inventory.values())
        self.inventory_metrics["total_items"] = len(self.inventory)
        self.inventory_metrics["total_value"] = total_value
        
        if self.total_capacity > 0:
            self.inventory_metrics["warehouse_utilization"] = self.used_capacity / self.total_capacity
        else:
            self.inventory_metrics["warehouse_utilization"] = 0
        
        # 更新库存周转率（如果已记录销售成本）
        # if self.cost_of_goods_sold > 0:
        #     self.calculate_inventory_turnover()
    
    def _update_stockout_rate(self):
        """
        更新缺货率
        
        **代码实现**: 
        - 私有方法，由 `remove_inventory()` 调用
        - 计算缺货率 = 缺货次数 / 总出库请求次数
        """
        if self.total_outbound_requests > 0:
            self.inventory_metrics["stockout_rate"] = self.stockout_count / self.total_outbound_requests

    def _log_inventory_event(self, event: Dict):
        """
        记录库存相关事件

        **代码实现**:
        - 私有方法，由 `_record_inventory_transaction()` 调用
        - 向 `inventory_events` 列表添加事件记录
        """
        self.inventory_events.append(event)

    @with_response("generate_inventory_analysis")
    def generate_inventory_analysis(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        生成库存变动分析JSON

        Args:
            response: 响应对象，由装饰器自动注入

        Returns:
            ModuleResponse: 包含库存变动分析JSON的统一响应对象
        """
        try:
            # 库存水平分析
            inventory_levels = {}
            total_value = 0
            total_quantity = 0
            for item_id, item_data in self.inventory.items():
                su_quantity = item_data.get("quantity", 0)
                original_unit = item_data.get("original_unit")
                quantity = self._from_su_quantity(su_quantity, original_unit)
                inventory_levels[item_id] = {
                    "quantity": quantity,
                    "su_quantity": su_quantity,
                    "unit": original_unit or "SU",
                    "unit_price": item_data.get("unit_price", 0),
                    "total_value": item_data.get("total_value", 0),
                    "item_type": item_data.get("item_type", "unknown"),
                    "last_updated": item_data.get("last_updated")
                }
                total_value += item_data.get("total_value", 0)
                total_quantity += su_quantity

            # 库存类型分布分析
            inventory_by_type = {}
            for item_id, item_data in self.inventory.items():
                item_type = item_data.get("item_type", "unknown")
                su_quantity = item_data.get("quantity", 0)
                quantity = self._from_su_quantity(
                    su_quantity,
                    item_data.get("original_unit")
                )
                if item_type not in inventory_by_type:
                    inventory_by_type[item_type] = {
                        "total_items": 0,
                        "total_quantity": 0,
                        "total_quantity_su": 0,
                        "total_value": 0
                    }
                inventory_by_type[item_type]["total_items"] += 1
                inventory_by_type[item_type]["total_quantity"] += su_quantity
                inventory_by_type[item_type]["total_quantity_su"] += su_quantity
                inventory_by_type[item_type]["total_value"] += item_data.get("total_value", 0)

            # 仓库容量利用率分析
            utilization = self.used_capacity / self.total_capacity if self.total_capacity > 0 else 0
            remaining_capacity = self.total_capacity - self.used_capacity

            # 库存预警分析
            low_stock_items = []
            reorder_items = []
            for item_id, item_data in self.inventory.items():
                su_quantity = item_data.get("quantity", 0)
                original_unit = item_data.get("original_unit")
                quantity = self._from_su_quantity(su_quantity, original_unit)
                safety_stock = self.safety_stocks.get(item_id, 0)
                reorder_point = self.reorder_points.get(item_id, 0)
                display_safety_stock = self._from_su_quantity(safety_stock, original_unit)
                display_reorder_point = self._from_su_quantity(reorder_point, original_unit)

                if su_quantity < safety_stock:
                    low_stock_items.append({
                        "item_id": item_id,
                        "current_quantity": quantity,
                        "safety_stock": display_safety_stock,
                        "shortfall": display_safety_stock - quantity,
                        "unit": original_unit or "SU"
                    })
                
                if su_quantity < reorder_point:
                    reorder_items.append({
                        "item_id": item_id,
                        "current_quantity": quantity,
                        "reorder_point": display_reorder_point,
                        "shortfall": display_reorder_point - quantity,
                        "unit": original_unit or "SU"
                    })

            # 库存变动趋势分析
            inventory_history_summary = {}
            for item_id, history in self.inventory_history.items():
                if history:
                    inventory_history_summary[item_id] = {
                        "total_transactions": len(history),
                        "recent_transactions": history[-5:] if len(history) > 5 else history
                    }

            # 库存周转率分析
            turnover = self.inventory_metrics.get("inventory_turnover", 0)

            # 维护成本分析
            maintenance_cost_summary = {
                "total_maintenance_cost": self.total_maintenance_cost,
                "maintenance_cost_rate": self.maintenance_cost_rate,
                "history_count": len(self.maintenance_cost_history),
                "average_cost_per_step": self.total_maintenance_cost / len(self.maintenance_cost_history) if len(self.maintenance_cost_history) > 0 else 0
            }

            # 获取当前时间
            try:
                timestamp = self.enterprise.time_manager.get_day() if hasattr(self.enterprise, 'time_manager') else 0
            except Exception:
                timestamp = 0

            # 构建分析JSON
            analysis_json = {
                "analysis_type": "库存变动分析",
                "timestamp": timestamp,
                "metrics": self.inventory_metrics,
                "inventory_levels": inventory_levels,
                "inventory_summary": {
                    "total_items": len(self.inventory),
                    "total_quantity": total_quantity,
                    "total_quantity_su": total_quantity,
                    "total_value": total_value
                },
                "inventory_by_type": inventory_by_type,
                "warehouse_analysis": {
                    "total_capacity": self.total_capacity,
                    "used_capacity": self.used_capacity,
                    "remaining_capacity": remaining_capacity,
                    "utilization": utilization,
                    "utilization_level": (
                        "low"
                        if utilization < self.config.CAPACITY_LOW_THRESHOLD
                        else "normal"
                        if utilization < self.config.CAPACITY_WARNING_THRESHOLD
                        else "warning"
                        if utilization < self.config.CAPACITY_CRITICAL_THRESHOLD
                        else "critical"
                    )
                },
                "inventory_alerts": {
                    "low_stock_items": low_stock_items,
                    "reorder_items": reorder_items,
                    "low_stock_count": len(low_stock_items),
                    "reorder_count": len(reorder_items)
                },
                "inventory_history": inventory_history_summary,
                "turnover_analysis": {
                    "inventory_turnover": turnover,
                    "stockout_rate": self.inventory_metrics.get("stockout_rate", 0),
                    # "shrinkage_rate": self.inventory_metrics.get("shrinkage_rate", 0)
                },
                "maintenance_cost_analysis": maintenance_cost_summary,
                "insights": [
                    f"总库存项目数: {len(self.inventory)}",
                    f"总库存价值: ¥{total_value:,.2f}",
                    f"仓库利用率: {utilization:.2f}",
                    f"库存周转率: {turnover:.2f}",
                    f"缺货率: {self.inventory_metrics.get('stockout_rate', 0):.2f}",
                    # f"缩水率: {self.inventory_metrics.get('shrinkage_rate', 0):.2f}",
                    f"低库存项目数: {len(low_stock_items)}",
                    f"需要再订购项目数: {len(reorder_items)}"
                ]
            }

            return self.success_response(
                response,
                "成功生成库存变动分析",
                {
                    "analysis": analysis_json
                }
            )
        except Exception as e:
            return self.error_response(
                response,
                "ANALYSIS_ERROR",
                f"生成库存变动分析失败: {e}"
            )

    def _initialize_default_unit_mappings(self):
        """
        初始化默认单位映射
        
        **代码实现**:
        - 设置默认的单位转换比例
        - 100 Malt = 1 SU, 10 Hops = 1 SU, 5 Yeast = 1 SU, 1 Beer = 1 SU
        """
        self.unit_conversion_table = {
            "malt": {"to_su": 0.01, "from_su": 100},
            "hops": {"to_su": 0.1, "from_su": 10},
            "yeast": {"to_su": 0.2, "from_su": 5},
            "beer": {"to_su": 1.0, "from_su": 1}
        }

    def _get_item_original_unit(self, item_id: str) -> Optional[str]:
        """优先读取库存记录中的单位，其次按物料 ID 推断。"""
        resolved_item_id = self._resolve_item_id(item_id)
        inventory_item = self.inventory.get(resolved_item_id) if resolved_item_id else None
        if inventory_item and inventory_item.get("original_unit"):
            return inventory_item["original_unit"]
        return self._detect_unit_from_item_id(item_id)

    def _resolve_item_id(self, item_id: str) -> Optional[str]:
        """在现有库存中解析真实物料 ID，兼容大小写差异。"""
        if not item_id:
            return None
        if item_id in self.inventory:
            return item_id

        normalized_item_id = item_id.strip().lower()
        for existing_item_id in self.inventory.keys():
            if existing_item_id.lower() == normalized_item_id:
                return existing_item_id
        return None

    def _to_su_quantity(self, quantity: float, original_unit: Optional[str]) -> float:
        """把外部原始单位数量换算为内部 SU 数量。"""
        if original_unit and original_unit in self.unit_conversion_table:
            return quantity * self.unit_conversion_table[original_unit]["to_su"]
        return quantity

    def _from_su_quantity(self, su_quantity: float, original_unit: Optional[str]) -> float:
        """把内部 SU 数量换算回外部原始单位数量。"""
        if original_unit and original_unit in self.unit_conversion_table:
            return su_quantity * self.unit_conversion_table[original_unit]["from_su"]
        return su_quantity

    def _to_pricing_quantity(self, su_quantity: float, original_unit: Optional[str]) -> float:
        """把 SU 数量换算成与 `unit_price` 同口径的计价数量。"""
        return self._from_su_quantity(su_quantity, original_unit)

    def _normalize_item_type(
        self,
        item_id: str,
        item_type: Optional[str],
        existing_item_type: Optional[str] = None
    ) -> str:
        """把调用方传入的物料类型归一化为 `raw_material` 或 `product`。"""
        if existing_item_type in {"raw_material", "product"}:
            return existing_item_type

        normalized = (item_type or "").strip().lower()
        if normalized in {"raw_material", "raw", "material", "procurement", "purchase"}:
            return "raw_material"
        if normalized in {"product", "produce_daily", "produce_completed", "finished_good", "finished_product"}:
            return "product"

        inferred_unit = self._get_item_original_unit(item_id)
        if inferred_unit == "beer":
            return "product"
        if inferred_unit in {"malt", "hops", "yeast"}:
            return "raw_material"

        return "product"

    @with_response("convert_to_su")
    def convert_to_su(self, quantity: float, unit: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        将外部单位转换为标准单位 SU
        
        Args:
            quantity: 数量（外部单位）
            unit: 单位名称（如 "malt", "hops", "yeast", "beer"）
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含转换后SU数量的统一响应对象
            
        **代码实现**:
        - 检查单位是否在转换表中
        - 使用 to_su 比例进行转换
        - 返回转换后的SU数量
        """
        unit_lower = unit.lower()
        
        if unit_lower not in self.unit_conversion_table:
            return self.error_response(
                response,
                "UNIT_NOT_FOUND",
                f"单位 '{unit}' 未在转换表中配置。可用单位: {list(self.unit_conversion_table.keys())}"
            )
        
        conversion_ratio = self.unit_conversion_table[unit_lower]["to_su"]
        su_quantity = quantity * conversion_ratio
        
        return self.success_response(
            response,
            f"成功将 {quantity} {unit} 转换为 SU",
            {
                "original_quantity": quantity,
                "original_unit": unit,
                "su_quantity": su_quantity,
                "conversion_ratio": conversion_ratio
            }
        )

    @with_response("convert_from_su")
    def convert_from_su(self, su_quantity: float, unit: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        将标准单位 SU 转换为外部单位
        
        Args:
            su_quantity: SU数量
            unit: 目标单位名称（如 "malt", "hops", "yeast", "beer"）
            response: 响应对象（由装饰器注入）
            
        Returns:
            ModuleResponse: 包含转换后外部单位数量的统一响应对象
            
        **代码实现**:
        - 检查单位是否在转换表中
        - 使用 from_su 比例进行转换
        - 返回转换后的外部单位数量
        """
        unit_lower = unit.lower()
        
        if unit_lower not in self.unit_conversion_table:
            return self.error_response(
                response,
                "UNIT_NOT_FOUND",
                f"单位 '{unit}' 未在转换表中配置。可用单位: {list(self.unit_conversion_table.keys())}"
            )
        
        conversion_ratio = self.unit_conversion_table[unit_lower]["from_su"]
        original_quantity = su_quantity * conversion_ratio
        
        return self.success_response(
            response,
            f"成功将 {su_quantity} SU 转换为 {unit}",
            {
                "su_quantity": su_quantity,
                "target_unit": unit,
                "quantity": original_quantity,
                "conversion_ratio": conversion_ratio
            }
        )

    def _detect_unit_from_item_id(self, item_id: str) -> str:
        """
        从物料ID中自动检测单位
        
        Args:
            item_id: 物料ID（如 "malt_1", "hops_batch", "beer_final"）
            
        Returns:
            str: 检测到的单位（如 "malt", "hops", "beer"），如果未检测到则返回 None
            
        **代码实现**:
        - 遍历单位转换表中的所有单位
        - 检查单位是否在物料ID中（不区分大小写）
        - 返回第一个匹配的单位
        """
        if not item_id:
            return None
        
        item_id_lower = item_id.lower()
        
        for unit in self.unit_conversion_table.keys():
            if unit in item_id_lower:
                return unit
        
        return None


def _parse_item_data(item_id: str, item_data) -> tuple:
    """
    解析物料数据（简化版，不包含单位参数）
    
    Args:
        item_id: 物料ID
        item_data: 物料数据，可以是：
            - 简写数字: 100
            - 字典: {"quantity": 100, "unit_price": 10.5}
    
    Returns:
        tuple: (quantity, unit_price, error)
            - quantity: 数量
            - unit_price: 单价
            - error: 错误信息（如果有）
    """
    try:
        quantity = 0
        unit_price = 0.0
        
        if isinstance(item_data, (int, float)):
            quantity = float(item_data)
            unit_price = 0.0
        elif isinstance(item_data, dict):
            quantity = item_data.get("quantity", 0)
            unit_price = item_data.get("unit_price", 0.0)
            
            if quantity is None:
                quantity = 0
            if unit_price is None:
                unit_price = 0.0
        else:
            return 0, 0.0, f"无效的数据类型: {type(item_data)}"
        
        if not isinstance(quantity, (int, float)) or quantity < 0:
            return 0, 0.0, f"数量必须是非负数字: {quantity}"
        
        if not isinstance(unit_price, (int, float)) or unit_price < 0:
            return 0, 0.0, f"单价必须是非负数字: {unit_price}"
        
        return float(quantity), float(unit_price), None
        
    except Exception as e:
        return 0, 0.0, f"解析错误: {str(e)}"


def _parse_item_data_with_unit(item_id: str, item_data) -> tuple:
    """
    解析物料数据，支持单位参数（保留用于向后兼容）
    
    Args:
        item_id: 物料ID
        item_data: 物料数据，可以是：
            - 简写数字: 100
            - 字典: {"quantity": 100, "unit_price": 10.5}
            - 完整字典: {"quantity": 100, "unit_price": 10.5, "unit": "malt"}
    
    Returns:
        tuple: (quantity, unit_price, unit, error)
            - quantity: 数量
            - unit_price: 单价
            - unit: 单位（可选）
            - error: 错误信息（如果有）
    """
    try:
        quantity = 0
        unit_price = 0.0
        unit = None
        
        if isinstance(item_data, (int, float)):
            quantity = float(item_data)
            unit_price = 0.0
        elif isinstance(item_data, dict):
            quantity = item_data.get("quantity", 0)
            unit_price = item_data.get("unit_price", 0.0)
            unit = item_data.get("unit", None)
            
            if quantity is None:
                quantity = 0
            if unit_price is None:
                unit_price = 0.0
        else:
            return 0, 0.0, None, f"无效的数据类型: {type(item_data)}"
        
        if not isinstance(quantity, (int, float)) or quantity < 0:
            return 0, 0.0, None, f"数量必须是非负数字: {quantity}"
        
        if not isinstance(unit_price, (int, float)) or unit_price < 0:
            return 0, 0.0, None, f"单价必须是非负数字: {unit_price}"
        
        if unit is not None and not isinstance(unit, str):
            return 0, 0.0, None, f"单位必须是字符串: {unit}"
        
        return float(quantity), float(unit_price), unit, None
        
    except Exception as e:
        return 0, 0.0, None, f"解析错误: {str(e)}"
