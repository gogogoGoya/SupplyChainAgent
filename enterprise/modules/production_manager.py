"""
生产管理模块

负责企业的生产规划、产能管理和生产执行，包括生产线建设、生产计划制定与执行、成本核算等功能
"""
import math
from typing import Dict, List, Optional
from enterprise.modules.base_business_module import EnhancedBaseModule
from enterprise.modules.hr_manager import DepartmentType
from enterprise.modules.response_model import ModuleResponse, ResponseStatus
from enterprise.modules.decorators import with_response, validate_positive, skip_dry_run_validation
from config.module_config import ProductionConfig
from collections import defaultdict

class ProductionManager(EnhancedBaseModule):
    """
    生产管理器类
    处理企业生产相关的所有业务逻辑
    """

    def __init__(self, enterprise, max_lines: int = None, module_id=None, config: ProductionConfig = None):
        """
        初始化生产管理器

        Args:
            enterprise: 所属企业实例
            max_lines: 最大生产线数量（可选，默认从 config 读取）
            module_id: 模块唯一标识（可选）
            config: 生产配置对象（可选，默认使用 ProductionConfig()）
        """
        # 使用配置或默认配置
        self.config = config or ProductionConfig()

        # 调用父类初始化方法
        super().__init__(
            enterprise,
            module_id or f"production_{getattr(enterprise, 'id', 'default')}",
            self.config
        )
        self.module_type = "ProductionManager"
        self.max_lines = max_lines or self.config.MAX_PRODUCTION_LINES

        # 从配置中提取常用属性
        self.LINE_CONFIGS = self.config.LINE_CONFIGS

        # 生产线类型配置（支持data_initializer.py中的设置）
        self.production_line_types = {}  # 用于存储生产线类型配置

        # 生产线管理
        self.production_lines: Dict[str, Dict] = {}  # 生产线记录 {line_id: line_data}
        self.next_line_id = 1  # 下一个生产线ID

        # 生产计划管理
        self.production_plans: List[Dict] = []  # 生产计划列表
        self.next_plan_id = 1  # 下一个计划ID

        # 产品配方（BOM - Bill of Materials）
        self.product_recipes: Dict[str, Dict] = {}  # {product_id: recipe_data}

        # 生产指标
        self.production_metrics = {
            "total_production": 0,           # 总产量
            "total_plans": 0,                # 总计划数
            "total_planned": 0,              # 总计划产量
            "completed_plans": 0,            # 完成的计划数
            "failed_plans": 0,               # 失败的计划数
            "capacity_utilization": 0.0,     # 产能利用率
            "production_efficiency": 0.0,    # 生产效率
            "total_cost": 0.0                # 总生产成本
        }

        # 生产事件日志
        self.production_events: List[Dict] = []

    # ========== 生产线管理 ==========

    @skip_dry_run_validation
    @with_response("initialize_production_line")
    def initialize_production_line(
        self,
        line_type: str,
        ready_at_start: bool = True,
        initial_status: str = None,
        response: ModuleResponse = None
    ) -> ModuleResponse:
        """
        初始化场景预置产线。

        该动作仅用于模拟初始化阶段，表示企业在 day0 前已经拥有可投入使用的产线；
        不触发建设成本、建设工人占用或等待完工流程。
        """
        if line_type not in self.LINE_CONFIGS:
            return self.error_response(response, "INVALID_LINE_TYPE", f"无效的生产线类型，请选择 'small', 'medium', 或 'large'")

        if len(self.production_lines) >= self.max_lines:
            return self.error_response(response, "MAX_LINES_REACHED", f"已达到生产线数量上限（{self.max_lines}条）")

        config = self.LINE_CONFIGS[line_type]
        current_day = self.enterprise.time_manager.get_day() if getattr(self.enterprise, "time_manager", None) else 0
        status = initial_status or ("idle" if ready_at_start else "under_construction")
        if status not in {"idle", "under_construction", "maintaining"}:
            return self.error_response(response, "INVALID_INITIAL_LINE_STATUS", "初始产线状态必须为 idle、under_construction 或 maintaining")

        line_id = f"line_{self.next_line_id}"
        self.next_line_id += 1
        completion_time = current_day if status == "idle" else current_day + config["build_time"]

        self.production_lines[line_id] = {
            "line_id": line_id,
            "line_type": line_type,
            "capacity": config["capacity"],
            "remaining_capacity": config["capacity"],
            "operating_cost": config["operating_cost"],
            "workers_needed": config["workers_needed"],
            "assigned_workers": 0,
            "status": status,
            "build_start_time": current_day,
            "completion_time": completion_time,
            "assigned_plan_id": None,
            "total_produced": 0,
            "initialization_source": "scenario_config",
        }

        self._log_event({
            "type": "production_line_initialized",
            "line_id": line_id,
            "line_type": line_type,
            "status": status,
            "completion_time": completion_time,
        })

        return self.success_response(response, f"初始生产线 {line_id} 已配置为 {status}", {
            "line_id": line_id,
            "line_type": line_type,
            "status": status,
            "completion_time": completion_time,
            "initialization_source": "scenario_config",
        })

    @with_response("build_production_line")
    def build_production_line(self, line_type: str, 
                              dry_run: bool = False,
                              single_case_prewarm_seed: bool = False,
                              single_case_capacity_diagnostic: bool = False,
                              single_enterprise_capacity_recovery: bool = False,
                              response: ModuleResponse = None) -> ModuleResponse:
        """
        建设生产线

        Args:
            line_type: 生产线类型 ("small", "medium", "large")
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 建设结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        if line_type not in self.LINE_CONFIGS:
            return self.error_response(response, "INVALID_LINE_TYPE", f"无效的生产线类型，请选择 'small', 'medium', 或 'large'")
        config = self.LINE_CONFIGS[line_type]
        workers_assigned = 0  # 记录已分配的工人数
        hr_result = hr_manager.get_available_workers(department='production')
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < config["workers_needed"]:
            return self.error_response(response, "INSUFFICIENT_PRODUCTION_WORKERS", f"生产工人不足。需要: {config['workers_needed']}, 可用: {employee_count}")

        # 3. 检查空间约束（最多10条生产线）
        total_lines = len(self.production_lines)
        if total_lines >= self.max_lines:
            return self.error_response(response, "MAX_LINES_REACHED", f"已达到生产线数量上限（{self.max_lines}条）")

        
        finance_manager = super().get_module_by_type("FinanceManager")

        # 3. 检查资金约束
        balance_result = finance_manager.get_balance()
        # 处理不同返回类型的情况
        if isinstance(balance_result, (int, float)):
            balance_value = balance_result
        elif hasattr(balance_result, 'data'):
            balance_value = balance_result.data.get("balance", 0) if isinstance(balance_result.data, dict) else 0
        elif isinstance(balance_result, dict):
            balance_value = balance_result.get("balance", 0)
        else:
            balance_value = 0

        if balance_value < config["build_cost"]:
            return self.error_response(response, "INSUFFICIENT_FUNDS", f"资金不足，需要 ¥{config['build_cost']:,}")

        margin_guard = self._get_margin_guard_status()
        usable_lines = [
            line for line in self.production_lines.values()
            if line.get("status") in {"idle", "working", "maintaining"}
        ]
        # 仅当尚无任何已完工可用产线时，仍视作冷启动，避免“只有在建线”时被误判为扩产。
        is_cold_start_build = len(usable_lines) == 0
        if (
            (not is_cold_start_build)
            and not single_case_prewarm_seed
            and not single_case_capacity_diagnostic
            and not single_enterprise_capacity_recovery
            and not (margin_guard.get("summary") or {}).get("has_capacity_expansion_candidate")
        ):
            return self.error_response(
                response,
                "MARGIN_GUARD_BLOCKED",
                "当前没有满足毛利护栏的扩产候选产品，不建议建设新产线"
            )

        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "line_type": line_type,
                    "build_cost": config["build_cost"],
                    "workers_needed": config["workers_needed"],
                    "cash_guard": self._get_cash_guard_status(),
                    "margin_guard": margin_guard,
                    "is_cold_start_build": is_cold_start_build,
                    "single_case_prewarm_seed": bool(single_case_prewarm_seed),
                    "single_enterprise_capacity_recovery": bool(
                        single_enterprise_capacity_recovery
                        or single_case_capacity_diagnostic
                    ),
                }
            )
        

        # 4. 生成生产线ID（在分配工人前生成，确保ID一致）
        line_id = f"line_{self.next_line_id}"
        self.next_line_id += 1

        # 5. 检查人力约束并提前分配工人
        workers_assigned = 0  # 记录已分配的工人数
            # 提前分配工人（符合"所需工人提前招聘"的需求）
            # 使用真实line_id分配，确保与生产线记录一致
        assign_result = hr_manager.assign_workers(
            'production',
            line_id,  # 使用真实line_id而非临时ID
            config["workers_needed"]
        )
        assign_success = assign_result.success if hasattr(assign_result, "success") else bool(assign_result.get("success"))
        if not assign_success:
            assign_error = getattr(assign_result, "message", None) or assign_result.get("error", "生产工人分配失败")
            return self.error_response(response, "ASSIGN_WORKERS_ERROR", assign_error)
        workers_assigned = config["workers_needed"]

        # 6. 扣除建设成本
        cost_result = finance_manager.add_cost(
            config["build_cost"],
            "produce_cost",
            "production_line_construction"
        )
        if not getattr(cost_result, "success", True):
            hr_manager.release_workers('production', line_id, workers_assigned, "cancelled")
            return self.error_response(
                response,
                "COST_RECORD_FAILED",
                getattr(cost_result, "message", "生产线建设成本记录失败")
            )

        # 7. 创建生产线记录
        completion_time = self.enterprise.time_manager.get_day() + config["build_time"]

        self.production_lines[line_id] = {
            "line_id": line_id,
            "line_type": line_type,
            "capacity": config["capacity"],
            "remaining_capacity": config["capacity"],
            "operating_cost": config["operating_cost"],
            "workers_needed": config["workers_needed"],
            "assigned_workers": workers_assigned,  # 建设时已分配的工人数
            "status": "under_construction",  # 建设中
            "build_start_time": self.enterprise.time_manager.get_day(),
            "completion_time": completion_time,
            "assigned_plan_id": None,  # 当前分配的计划ID
            "total_produced": 0  # 累计产量
        }

        # 7. 记录建设事件
        self._log_event({
            "type": "line_construction_started",
            "line_id": line_id,
            "line_type": line_type,
            "completion_time": completion_time
        })

        # 返回成功响应
        return self.success_response(response, f"生产线 {line_id} 开始建设，将于第 {completion_time} 个工作日完工", {
            "line_id": line_id,
            "line_type": line_type,
            "completion_time": completion_time
        })

    @skip_dry_run_validation
    @with_response("check_construction_completion")
    def check_construction_completion(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        检查并激活已完工的生产线（每个时间步开始时调用）

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含完工生产线信息的统一响应对象
        """
        completed_lines = []
        hr_manager = super().get_module_by_type("HRManager")
        for line_id, line_data in self.production_lines.items():
            if (line_data["status"] == "under_construction" and
                self.enterprise.time_manager.get_day() >= line_data["completion_time"]):

                # 激活生产线
                line_data["status"] = "idle"
                completed_lines.append(line_id)

                # 释放工人
                hr_manager.release_workers(
                    'production',
                    line_id,
                    line_data["assigned_workers"],
                    "completed"
                )

                # 记录完工事件
                self._log_event({
                    "type": "line_construction_completed",
                    "line_id": line_id,
                    "line_type": line_data["line_type"],
                    "workers_assigned": line_data["assigned_workers"]
                })

        # 返回成功响应
        return self.success_response(response, f"成功检查并激活 {len(completed_lines)} 条已完工生产线", {
            "completed_lines": completed_lines,
            "total_completed": len(completed_lines),
            "production_lines": self.production_lines
        })

    @with_response("get_production_line_status")
    def get_production_line_status(self, line_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取生产线状态

        Args:
            line_id: 生产线ID
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含生产线状态信息的统一响应对象
        """
        line_data = self.production_lines.get(line_id)
        if line_data:
            return self.success_response(response, f"成功获取生产线 {line_id} 的状态", line_data)
        else:
            return self.error_response(response, "LINE_NOT_FOUND", f"生产线 {line_id} 不存在")

    # ========== 产能管理 ==========

    @with_response("get_total_capacity")
    def get_total_capacity(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取总产能（所有已完工的生产线）

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含总产能信息的统一响应对象
        """
        total = 0
        for line_data in self.production_lines.values():
            if line_data["status"] in ["idle", "working"]:
                total += line_data["capacity"]

        return self.success_response(response, "成功获取总产能", {
            "total_capacity": total
        })

    @with_response("get_available_capacity")
    def get_available_capacity(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取可用产能（空闲生产线的产能）

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含可用产能信息的统一响应对象
        """
        available = 0
        for line_data in self.production_lines.values():
            if line_data["status"] in ["idle", "working"]:
                available += line_data["remaining_capacity"]

        return self.success_response(response, "成功获取可用产能", {
            "available_capacity": available
        })

    @with_response("get_occupied_capacity")
    def get_occupied_capacity(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取已占用产能（工作中生产线的产能）

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含已占用产能信息的统一响应对象
        """
        occupied = 0
        for line_data in self.production_lines.values():
            if line_data["status"] in ["idle", "working"]:
                occupied += line_data["capacity"] - line_data["remaining_capacity"]

        return self.success_response(response, "成功获取已占用产能", {
            "occupied_capacity": occupied
        })

    @with_response("calculate_capacity_utilization")
    def calculate_capacity_utilization(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        计算产能利用率

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含产能利用率信息的统一响应对象
        """
        # 获取总产能和已占用产能（从ModuleResponse中提取）
        total_capacity_response = self.get_total_capacity()
        total_capacity = total_capacity_response.data["total_capacity"] if total_capacity_response.success else 0

        if total_capacity == 0:
            utilization = 0.0
        else:
            occupied_capacity_response = self.get_occupied_capacity()
            occupied_capacity = occupied_capacity_response.data["occupied_capacity"] if occupied_capacity_response.success else 0
            utilization = occupied_capacity / total_capacity

        # 更新指标
        self.production_metrics["capacity_utilization"] = utilization

        return self.success_response(response, "成功计算产能利用率", {
            "capacity_utilization": utilization
        })

    # ========== 产品配方管理 ==========

    @with_response("set_product_recipe")
    @validate_positive("production_time")
    def set_product_recipe(self, product_id: str, raw_materials: Dict[str, float],
                          production_time: int, labor_cost_per_unit: float = 0,
                          equipment_cost_per_unit: float = 0, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        设置产品配方（BOM）

        Args:
            product_id: 产品ID
            raw_materials: 原材料需求 {material_id: quantity_per_unit}
            production_time: 生产周期（时间步）
            labor_cost_per_unit: 单位人工成本
            equipment_cost_per_unit: 单位设备成本
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含设置结果的统一响应对象
        """
        # 验证参数
        if not product_id:
            return self.error_response(response, "INVALID_PRODUCT_ID", "产品ID不能为空")
        
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        
        # 设置产品配方
        self.product_recipes[product_id] = {
            "product_id": product_id,
            "raw_materials": raw_materials,
            "production_time": production_time,
            "labor_cost_per_unit": labor_cost_per_unit,
            "equipment_cost_per_unit": equipment_cost_per_unit
        }

        return self.success_response(response, f"产品 {product_id} 的配方已设置", {
            "product_id": product_id,
            "recipe": self.product_recipes[product_id]
        })

    @with_response("get_product_recipe")
    def get_product_recipe(self, product_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取产品配方

        Args:
            product_id: 产品ID
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含产品配方信息的统一响应对象
        """
        recipe = self.product_recipes.get(product_id)
        if recipe:
            return self.success_response(response, f"成功获取产品 {product_id} 的配方", recipe)
        else:
            return self.error_response(response, "RECIPE_NOT_FOUND", f"产品 {product_id} 的配方不存在")

    # ========== 生产计划管理 ==========

    @with_response("create_production_plan")
    @validate_positive("quantity")
    def create_production_plan(self, product_id: str, quantity: float, daily_capacity: float = None,
                               dry_run: bool = False,
                               _cobweb_scripted_formula_override: bool = False,
                               response: ModuleResponse = None) -> ModuleResponse:
        """
        创建生产计划，并直接启动生产，取消execute二次确认

        Args:
            product_id: 产品ID
            quantity: 生产数量
            daily_capacity: 每日产能（每天生产多少份），默认为总产能
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含创建结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(DepartmentType.PRODUCTION)
        employee_count = hr_result.data.get("count", 0) 
        capacity_per_worker = self.config.PLAN_QUANTITY_PER_WORKER
        needed_workers = quantity // capacity_per_worker + 1 if quantity % capacity_per_worker != 0 else quantity // capacity_per_worker
        if employee_count < needed_workers:
            return self.error_response(response, "INSUFFICIENT_STAFF", f"人手不足，无法创建生产计划。至少需要: {needed_workers}")

        # 2. 验证产品配方存在
        recipe_response = self.get_product_recipe(product_id)
        if not recipe_response.success:
            return self.error_response(response, "RECIPE_NOT_FOUND", f"产品 {product_id} 的配方不存在，请先设置配方")

        recipe = recipe_response.data

        # 3. 计算所需原材料（总量）
        materials_needed = {}
        for material_id, qty_per_unit in recipe["raw_materials"].items():
            materials_needed[material_id] = qty_per_unit * quantity

        # 4. 验证原材料约束（检查总量是否足够）
        inventory_manager = super().get_module_by_type("InventoryManager")
        for material_id, needed_qty in materials_needed.items():
            # 处理不同返回类型的情况
            level_result = inventory_manager.get_inventory_level(material_id)
            if isinstance(level_result, (int, float)):
                available_qty = level_result
            elif hasattr(level_result, 'data'):
                available_qty = level_result.data.get("quantity", 0) if isinstance(level_result.data, dict) else 0
            elif isinstance(level_result, dict):
                available_qty = level_result.get("quantity", 0)
            else:
                available_qty = 0
            if available_qty < needed_qty:
                return self.error_response(response, "INSUFFICIENT_MATERIALS", f"原材料 {material_id} 库存不足。需要: {needed_qty}, 当前: {available_qty}")

        # 5. 处理每日产能参数
        if daily_capacity is None:
            capacity_response = self.get_available_capacity()
            available_capacity = capacity_response.data["available_capacity"]
            daily_capacity = available_capacity
        else:
            if daily_capacity <= 0:
                return self.error_response(response, "INVALID_DAILY_CAPACITY", "每日产能必须为正数")
            capacity_response = self.get_available_capacity()
            available_capacity = capacity_response.data["available_capacity"]
            if available_capacity < daily_capacity:
                return self.error_response(response, "INSUFFICIENT_AVAILABLE_CAPACITY", f"可用产能不足指定每日产能。需要: {daily_capacity}, 可用: {available_capacity}")
            if daily_capacity > quantity:
                return self.error_response(response, "INSUFFICIENT_DAILY_CAPACITY", f"每日产能 {daily_capacity} 大于生产数量 {quantity},无法创建生产计划")

        assigned_lines = self._assign_production_lines(daily_capacity)
        if not assigned_lines:
            return self.error_response(response, "INSUFFICIENT_CAPACITY", "无法分配生产线，可用产能不足")

        material_costs = self._estimate_total_material_cost(recipe, quantity)

        # 6. 计算生产天数（向上取整）
        
        production_days = math.ceil(quantity / daily_capacity)

        # 7. 计算每天需要消耗的原材料
        daily_materials = {}
        for material_id, total_qty in materials_needed.items():
            daily_materials[material_id] = total_qty / production_days

        # 8. 计算成本（基于总量）
        recipe_response = self.get_product_recipe(product_id)
        recipe = recipe_response.data
        labor_cost = recipe["labor_cost_per_unit"] * quantity

        equipment_cost_from_recipe = recipe["equipment_cost_per_unit"] * quantity



        operating_cost = sum(
            self.production_lines[line["line_id"]]["operating_cost"]
            for line in assigned_lines
        ) * production_days
        equipment_cost = equipment_cost_from_recipe + operating_cost

        total_cost = material_costs + labor_cost + equipment_cost
        unit_cost = total_cost / quantity if quantity > 0 else 0
        recovery_guard = self._get_recovery_guard_status()
        recovery_candidate = next(
            (item for item in (recovery_guard.get("candidates") or []) if item.get("product_id") == product_id),
            None
        )
        margin_guard = self._evaluate_margin_guard_for_plan(
            product_id=product_id,
            quantity=quantity,
            assigned_lines=assigned_lines,
            candidate=recovery_candidate,
        )

        # 9. 记录成本（通过财务模块）
        # 10. 创建生产计划
        plan_id = f"PLAN_{self.next_plan_id}"
        self.next_plan_id += 1

        finance_manager = super().get_module_by_type("FinanceManager")
        balance_result = finance_manager.get_balance()
        if isinstance(balance_result, (int, float)):
            balance_value = balance_result
        elif hasattr(balance_result, 'data'):
            balance_value = balance_result.data.get("balance", 0) if isinstance(balance_result.data, dict) else 0
        elif isinstance(balance_result, dict):
            balance_value = balance_result.get("balance", 0)
        else:
            balance_value = 0

        conversion_cost = labor_cost + equipment_cost
        if balance_value < conversion_cost:
            return self.error_response(
                response,
                "INSUFFICIENT_FUNDS",
                f"资金不足，生产计划至少需要 ¥{conversion_cost:,.2f}"
            )

        cash_summary = self._get_cash_summary()
        cash_commitment = {
            "current_cash": balance_value,
            "warning_threshold": self._safe_number(cash_summary.get("warning_threshold")),
            "projected_remaining_cash": balance_value - conversion_cost,
            "commitment_level": (
                "warning"
                if balance_value - conversion_cost < self._safe_number(cash_summary.get("warning_threshold"))
                else "healthy"
            ),
        }

        hard_blocked_without_recovery = (
            margin_guard.get("guard_level") == "hard_blocked"
            and not margin_guard.get("allow_service_recovery")
            and not margin_guard.get("allow_continuity_recovery")
            and self._safe_number(margin_guard.get("estimated_sale_unit_price")) <= 0
        )
        if hard_blocked_without_recovery and not _cobweb_scripted_formula_override:
            return self.error_response(
                response,
                "MARGIN_GUARD_BLOCKED",
                f"预计销售毛利不足，当前不建议创建 {product_id} 的生产计划"
            )
        if _cobweb_scripted_formula_override:
            margin_guard = {
                **margin_guard,
                "enforcement": "diagnostic_only_for_cobweb_c1_scripted_formula",
            }

        if dry_run:
            return self.success_response(
                response,
                "DRY_RUN_SUCCESS",
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "daily_capacity": daily_capacity,
                    "materials_needed": materials_needed,
                    "assigned_lines": assigned_lines,
                    "total_cost": total_cost,
                    "conversion_cost": conversion_cost,
                    "cash_commitment": cash_commitment,
                    "margin_guard": margin_guard,
                }
            )

        hr_assign_result = hr_manager.assign_workers(
            'production',
            plan_id,
            needed_workers,
        )
        if not getattr(hr_assign_result, "success", True):
            return self.error_response(
                response,
                "ASSIGN_WORKERS_ERROR",
                getattr(hr_assign_result, "message", "生产计划工人分配失败")
            )
        cost_result = finance_manager.add_cost(labor_cost + equipment_cost, "production_cost")
        if not getattr(cost_result, "success", True):
            hr_manager.release_workers('production', plan_id, needed_workers, "cancelled")
            return self.error_response(
                response,
                "COST_RECORD_FAILED",
                getattr(cost_result, "message", "生产成本记录失败")
            )

        # 11. 更新生产线状态
        for line in assigned_lines:
            line_id = line["line_id"]
            self.production_lines[line_id]["status"] = "working"
            self.production_lines[line_id]["assigned_plan_id"] = plan_id
            self.production_lines[line_id]["remaining_capacity"] -= line["cost_capacity"]

        # 12. 更新指标
        self.production_metrics["total_cost"] += total_cost

        # 13. 记录事件
        self._log_event({
            "type": "production_started",
            "plan_id": plan_id,
            "product_id": product_id,
            "quantity": quantity,
            "daily_capacity": daily_capacity,
            "production_days": production_days,
            "assigned_lines": assigned_lines
        })

        production_plan = {
            "plan_id": plan_id,
            "product_id": product_id,
            "quantity": quantity,
            "daily_capacity": daily_capacity,
            "production_days": production_days,
            "materials_needed": materials_needed,
            "daily_materials": daily_materials,
            "status": "in_progress",
            "created_time": self.enterprise.time_manager.get_day(),
            "start_time": self.enterprise.time_manager.get_day(),
            "completion_time": self.enterprise.time_manager.get_day() + production_days,
            "assigned_lines": assigned_lines,
            "assigned_workers": needed_workers,
            "total_cost": total_cost,
            "unit_cost": unit_cost,
            "progress": {
                "days_completed": 0,
                "quantity_produced": 0,
                "materials_consumed": {},
                "is_completed_today": False,
                "last_progress_day": None
            }
        }

        self.production_plans.append(production_plan)
        self.production_metrics["total_plans"] += 1


        return self.success_response(response, f"生产计划 {plan_id} 已创建，计划生产 {production_days} 天", {
            "plan_id": plan_id,
            "plan": production_plan,
            "completion_time": self.enterprise.time_manager.get_day() + production_days,
            "daily_capacity": daily_capacity,
            "production_days": production_days,
            "total_cost": total_cost,
            "unit_cost": unit_cost,
            "assigned_lines": assigned_lines,
            "margin_guard": margin_guard,
        })

    @skip_dry_run_validation
    @with_response("check_completed_plans")
    def check_completed_plans(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        检查并处理进行中的生产计划（每个时间步开始时调用）
        - 每日消耗原材料并产出产品
        - 追踪生产进度
        - 完成到期计划并入库

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含处理结果信息的统一响应对象
        """
        completed_products = []
        completed_plans = []
        daily_production = []

        inventory_manager = super().get_module_by_type("InventoryManager")
        hr_manager = super().get_module_by_type("HRManager")
        for plan in self.production_plans:
            if plan["status"] != "in_progress":
                continue

            if "progress" not in plan:
                plan["progress"] = {
                    "days_completed": 0,
                    "quantity_produced": 0,
                    "materials_consumed": {},
                    "is_completed_today": False,
                    "last_progress_day": None
                }

            progress = plan["progress"]
            current_day = self.enterprise.time_manager.get_day()
            if progress.get("last_progress_day") != current_day:
                progress["is_completed_today"] = False

            if current_day < plan["completion_time"]:
                if progress["is_completed_today"]:
                    continue

                daily_capacity = plan.get("daily_capacity", 100)
                daily_materials = plan.get("daily_materials", {})

                materials_consumed_today = {}
                for material_id, daily_qty in daily_materials.items():
                    remove_result = inventory_manager.remove_inventory(
                        material_id, daily_qty, "production_daily"
                    )
                    remove_success = remove_result.success if isinstance(remove_result, dict) else remove_result.success
                    if not remove_success:
                        continue

                    materials_consumed_today[material_id] = daily_qty
                    progress["materials_consumed"][material_id] = (
                        progress["materials_consumed"].get(material_id, 0) + daily_qty
                    )

                quantity_produced_today = daily_capacity
                remaining_quantity = plan["quantity"] - progress["quantity_produced"]
                if remaining_quantity < quantity_produced_today:
                    quantity_produced_today = remaining_quantity

                progress["quantity_produced"] += quantity_produced_today
                progress["days_completed"] += 1
                progress["is_completed_today"] = True
                progress["last_progress_day"] = current_day

                add_result = inventory_manager.add_inventory(
                    plan["product_id"], quantity_produced_today,
                    plan["unit_cost"],
                    "product"
                )

                if progress["days_completed"] >= plan.get("production_days", 1) or \
                   progress["quantity_produced"] >= plan["quantity"]:
                    plan["status"] = "completed"
                    completed_plans.append(plan["plan_id"])

                    for line in plan["assigned_lines"]:
                        line_id = line["line_id"]
                        if line_id in self.production_lines:
                            self.production_lines[line_id]["status"] = "idle"
                            self.production_lines[line_id]["assigned_plan_id"] = None
                            self.production_lines[line_id]["total_produced"] += progress["quantity_produced"]
                            self.production_lines[line_id]["remaining_capacity"] += line["cost_capacity"]
                            if self.production_lines[line_id]["remaining_capacity"] > self.production_lines[line_id]["capacity"]:
                                self.production_lines[line_id]["remaining_capacity"] = self.production_lines[line_id]["capacity"]

                    self.production_metrics["completed_plans"] += 1
                    self.production_metrics["total_production"] += progress["quantity_produced"]

                    total_planned_quantity = sum(p["quantity"] for p in self.production_plans)
                    if total_planned_quantity > 0:
                        self.production_metrics["production_efficiency"] = (
                            self.production_metrics["total_production"] /
                            total_planned_quantity
                        )
                    self.production_metrics["total_planned"] = total_planned_quantity

                    # 释放工人
                    hr_manager.release_workers(
                        'production',
                        plan["plan_id"],
                        plan["assigned_workers"],
                        "completed"
                    )

                    self._log_event({
                        "type": "production_completed",
                        "plan_id": plan["plan_id"],
                        "product_id": plan["product_id"],
                        "quantity": progress["quantity_produced"],
                        "days_completed": progress["days_completed"]
                    })

                    completed_products.append({
                        "product_id": plan["product_id"],
                        "quantity": progress["quantity_produced"],
                        "unit_cost": plan["unit_cost"]
                    })

                daily_production.append({
                    "plan_id": plan["plan_id"],
                    "product_id": plan["product_id"],
                    "quantity_produced_today": quantity_produced_today,
                    "total_produced": progress["quantity_produced"],
                    "days_completed": progress["days_completed"],
                    "total_days": plan.get("production_days", 1)
                })

            elif current_day >= plan["completion_time"] and plan["status"] == "in_progress":
                if not progress["is_completed_today"]:
                    remaining_quantity = plan["quantity"] - progress["quantity_produced"]
                    if remaining_quantity > 0:
                        daily_materials = plan.get("daily_materials", {})
                        for material_id, daily_qty in daily_materials.items():
                            inventory_manager.remove_inventory(
                                material_id, daily_qty, "production_daily"
                            )

                        inventory_manager.add_inventory(
                            plan["product_id"], remaining_quantity,
                            plan["unit_cost"],
                            "product"
                        )
                        progress["quantity_produced"] += remaining_quantity
                        progress["days_completed"] += 1
                        progress["is_completed_today"] = True
                        progress["last_progress_day"] = current_day

                        daily_production.append({
                            "plan_id": plan["plan_id"],
                            "product_id": plan["product_id"],
                            "quantity_produced_today": remaining_quantity,
                            "total_produced": progress["quantity_produced"],
                            "days_completed": progress["days_completed"],
                            "total_days": plan.get("production_days", 1)
                        })

                plan["status"] = "completed"
                completed_plans.append(plan["plan_id"])

                for line in plan["assigned_lines"]:
                    line_id = line["line_id"]
                    if line_id in self.production_lines:
                        self.production_lines[line_id]["status"] = "idle"
                        self.production_lines[line_id]["assigned_plan_id"] = None
                        self.production_lines[line_id]["total_produced"] += progress["quantity_produced"]
                        self.production_lines[line_id]["remaining_capacity"] += line["cost_capacity"]
                        if self.production_lines[line_id]["remaining_capacity"] > self.production_lines[line_id]["capacity"]:
                            self.production_lines[line_id]["remaining_capacity"] = self.production_lines[line_id]["capacity"]

                self.production_metrics["completed_plans"] += 1
                self.production_metrics["total_production"] += progress["quantity_produced"]

                total_planned_quantity = sum(p["quantity"] for p in self.production_plans)
                if total_planned_quantity > 0:
                    self.production_metrics["production_efficiency"] = (
                        self.production_metrics["total_production"] /
                        total_planned_quantity
                    )
                self.production_metrics["total_planned"] = total_planned_quantity

                hr_manager.release_workers(
                    'production',
                    plan["plan_id"],
                    plan["assigned_workers"],
                    "completed"
                )

                self._log_event({
                    "type": "production_completed",
                    "plan_id": plan["plan_id"],
                    "product_id": plan["product_id"],
                    "quantity": progress["quantity_produced"]
                })

                completed_products.append({
                    "product_id": plan["product_id"],
                    "quantity": progress["quantity_produced"],
                    "unit_cost": plan["unit_cost"]
                })

        return self.success_response(response, f"成功处理 {len(daily_production)} 个生产计划", {
            "completed_products": completed_products,
            "completed_plans": completed_plans,
            "daily_production": daily_production,
            "total_completed": len(completed_plans),
            "total_produced_today": sum(p["quantity_produced_today"] for p in daily_production)
        })

    @with_response("cancel_production_plan")
    def cancel_production_plan(self, plan_id: str, reason: str = "", 
                               dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        取消生产计划（支持部分完成的计划取消并退回剩余原材料）

        Args:
            plan_id: 生产计划ID
            reason: 取消原因
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含取消结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(DepartmentType.PRODUCTION)
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_CANCEL_PLAN_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法取消生产计划。至少需要: {self.config.MIN_CANCEL_PLAN_STAFF}"
            )

        # 2. 验证计划存在性
        plan = self._find_plan(plan_id)
        if not plan:
            return self.error_response(response, "PLAN_NOT_FOUND", f"计划 {plan_id} 不存在")

        # 3. 验证计划状态
        if plan["status"] not in ["pending", "in_progress", "interrupted"]:
            return self.error_response(response, "INVALID_PLAN_STATUS", f"计划状态为 {plan['status']}，无法取消")

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        # 4. 如果计划正在进行或被中断，释放生产线并退回剩余原材料
        released_lines = []
        quantity_produced = 0
        days_completed = 0

        if plan["status"] in ["in_progress", "interrupted"]:
            for line in plan["assigned_lines"]:
                line_id = line["line_id"]
                if line_id in self.production_lines:
                    self.production_lines[line_id]["status"] = "idle"
                    self.production_lines[line_id]["assigned_plan_id"] = None
                    self.production_lines[line_id]["remaining_capacity"] += line["cost_capacity"]
                    if self.production_lines[line_id]["remaining_capacity"] > self.production_lines[line_id]["capacity"]:
                        self.production_lines[line_id]["remaining_capacity"] = self.production_lines[line_id]["capacity"]
                    released_lines.append(line_id)

            progress = plan.get("progress", {})
            quantity_produced = progress.get("quantity_produced", 0)
            days_completed = progress.get("days_completed", 0)


        # 5. 更新计划状态和指标
        plan["status"] = "failed"
        plan["cancelled_time"] = self.enterprise.time_manager.get_day()
        self.production_metrics["failed_plans"] += 1

        # 6. 记录事件
        self._log_event({
            "type": "production_cancelled",
            "plan_id": plan_id,
            "reason": reason,
            "quantity_produced": quantity_produced,
            "days_completed": days_completed
        })

        hr_manager.release_workers(
            'production',
            plan["plan_id"],
            plan["assigned_workers"],
            "cancelled"
        )

        # 构建返回数据
        response_data = {
            "plan_id": plan_id,
            "reason": reason,
            "quantity_produced": quantity_produced,
            "days_completed": days_completed
        }
        if released_lines:
            response_data["released_lines"] = released_lines

        return self.success_response(response, f"生产计划 {plan_id} 已取消", response_data)

    @with_response("interrupt_production_plan")
    def interrupt_production_plan(self, plan_id: str, 
                                  dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        中断生产计划（保留进度，可以后续恢复）

        Args:
            plan_id: 生产计划ID
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含中断结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(DepartmentType.PRODUCTION)
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_CANCEL_PLAN_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法中断生产计划。至少需要: {self.config.MIN_CANCEL_PLAN_STAFF}"
            )

        # 2. 验证计划存在性
        plan = self._find_plan(plan_id)
        if not plan:
            return self.error_response(response, "PLAN_NOT_FOUND", f"计划 {plan_id} 不存在")

        # 3. 验证计划状态
        if plan["status"] != "in_progress":
            return self.error_response(response, "INVALID_PLAN_STATUS", f"计划状态为 {plan['status']}，无法中断")

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        # 4. 记录中断前的进度
        progress = plan.get("progress", {})
        days_completed = progress.get("days_completed", 0)
        quantity_produced = progress.get("quantity_produced", 0)
        remaining_quantity = plan["quantity"] - quantity_produced

        # 5. 释放生产线
        released_lines = []
        for line in plan["assigned_lines"]:
            line_id = line["line_id"]
            if line_id in self.production_lines:
                self.production_lines[line_id]["status"] = "idle"
                self.production_lines[line_id]["assigned_plan_id"] = None
                self.production_lines[line_id]["remaining_capacity"] += line["cost_capacity"]
                if self.production_lines[line_id]["remaining_capacity"] > self.production_lines[line_id]["capacity"]:
                    self.production_lines[line_id]["remaining_capacity"] = self.production_lines[line_id]["capacity"]
                released_lines.append(line_id)

        # 6. 更新计划状态为 interrupted
        plan["status"] = "interrupted"
        plan["interrupted_time"] = self.enterprise.time_manager.get_day()

        # 7. 记录事件
        self._log_event({
            "type": "production_interrupted",
            "plan_id": plan_id,
            "days_completed": days_completed,
            "quantity_produced": quantity_produced,
            "remaining_quantity": remaining_quantity,
        })

        return self.success_response(response, f"生产计划 {plan_id} 已中断", {
            "plan_id": plan_id,
            "days_completed": days_completed,
            "quantity_produced": quantity_produced,
            "remaining_quantity": remaining_quantity,
            "released_lines": released_lines
        })

    @with_response("resume_production_plan")
    def resume_production_plan(self, plan_id: str, 
                               dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        恢复被中断的生产计划（从断点继续执行）

        Args:
            plan_id: 生产计划ID
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含恢复结果的统一响应对象
        """
        # 1. 检查部门人手情况
        hr_manager = super().get_module_by_type("HRManager")
        hr_result = hr_manager.get_available_workers(DepartmentType.PRODUCTION)
        employee_count = hr_result.data.get("count", 0) 
        if employee_count < self.config.MIN_CANCEL_PLAN_STAFF:
            return self.error_response(
                response,
                "INSUFFICIENT_STAFF",
                f"人手不足，无法恢复生产计划。至少需要: {self.config.MIN_CANCEL_PLAN_STAFF}"
            )

        # 2. 验证计划存在性
        plan = self._find_plan(plan_id)
        if not plan:
            return self.error_response(response, "PLAN_NOT_FOUND", f"计划 {plan_id} 不存在")

        # 3. 验证计划状态
        if plan["status"] != "interrupted":
            return self.error_response(response, "INVALID_PLAN_STATUS", f"计划状态为 {plan['status']}，无法恢复")

        # 4. 检查进度
        progress = plan.get("progress", {})
        days_completed = progress.get("days_completed", 0)
        quantity_produced = progress.get("quantity_produced", 0)
        remaining_quantity = plan["quantity"] - quantity_produced

        if remaining_quantity <= 0:
            return self.error_response(response, "PLAN_ALREADY_COMPLETED", "计划已完成，无需恢复")

        # 5. 验证剩余原材料
        inventory_manager = super().get_module_by_type("InventoryManager")
        daily_materials = plan.get("daily_materials", {})
        remaining_days = plan.get("production_days", 1) - days_completed

        for material_id, daily_qty in daily_materials.items():
            total_remaining_needed = daily_qty * remaining_days
            level_result = inventory_manager.get_inventory_level(material_id)
            if isinstance(level_result, (int, float)):
                available_qty = level_result
            elif hasattr(level_result, 'data'):
                available_qty = level_result.data.get("quantity", 0) if isinstance(level_result.data, dict) else 0
            elif isinstance(level_result, dict):
                available_qty = level_result.get("quantity", 0)
            else:
                available_qty = 0
            if available_qty < total_remaining_needed:
                return self.error_response(response, "INSUFFICIENT_MATERIALS",
                    f"原材料 {material_id} 库存不足，无法恢复生产。需要: {total_remaining_needed}, 当前: {available_qty}")

        # 6. 分配生产线
        daily_capacity = plan.get("daily_capacity", 100)
        assigned_lines = self._assign_production_lines(daily_capacity)
        if not assigned_lines:
            return self.error_response(response, "INSUFFICIENT_CAPACITY", "无法分配生产线，可用产能不足")

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        # 7. 更新计划状态为 in_progress
        plan["status"] = "in_progress"
        plan["assigned_lines"] = assigned_lines
        plan["completion_time"] = self.enterprise.time_manager.get_day() + remaining_days
        plan["progress"]["is_completed_today"] = False

        # 8. 更新生产线状态
        for line in assigned_lines:
            line_id = line["line_id"]
            self.production_lines[line_id]["status"] = "working"
            self.production_lines[line_id]["assigned_plan_id"] = plan_id
            self.production_lines[line_id]["remaining_capacity"] -= line["cost_capacity"]

        # 9. 记录事件
        self._log_event({
            "type": "production_resumed",
            "plan_id": plan_id,
            "days_completed": days_completed,
            "quantity_produced": quantity_produced,
            "remaining_quantity": remaining_quantity,
            "remaining_days": remaining_days,
            "assigned_lines": assigned_lines
        })

        return self.success_response(response, f"生产计划 {plan_id} 已恢复，继续生产剩余 {remaining_quantity} 件", {
            "plan_id": plan_id,
            "days_completed": days_completed,
            "quantity_produced": quantity_produced,
            "remaining_quantity": remaining_quantity,
            "remaining_days": remaining_days,
            "completion_time": plan["completion_time"],
            "assigned_lines": assigned_lines
        })

    # ========== 成本核算 ==========

    @with_response("calculate_production_cost")
    @validate_positive("quantity")
    def calculate_production_cost(self, product_id: str, quantity: float, response: ModuleResponse = None) -> ModuleResponse:
        """
        计算生产成本（估算）

        Args:
            product_id: 产品ID
            quantity: 生产数量
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含成本计算结果的统一响应对象
        """
        # 1. 验证产品配方
        recipe_response = self.get_product_recipe(product_id)
        if not recipe_response.success:
            return self.error_response(response, "RECIPE_NOT_FOUND", f"产品 {product_id} 的配方不存在")

        recipe = recipe_response.data

        # 2. 计算原材料成本
        material_costs = 0
        material_details = {}
        inventory_manager = super().get_module_by_type("InventoryManager")

        for material_id, qty_per_unit in recipe["raw_materials"].items():
            total_qty = qty_per_unit * quantity
            detail_result = inventory_manager.get_inventory_detail(material_id)

            # 处理不同返回类型的情况
            material_detail = detail_result if isinstance(detail_result, dict) else detail_result.data

            if material_detail:
                unit_price = material_detail["unit_price"]
            else:
                unit_price = 0  # 如果没有库存记录，默认为0

            cost = total_qty * unit_price
            material_costs += cost
            material_details[material_id] = {
                "quantity": total_qty,
                "unit_price": unit_price,
                "cost": cost
            }

        # 3. 计算人工成本
        labor_cost = recipe["labor_cost_per_unit"] * quantity

        # 4. 计算设备成本（改进：根据实际需要的生产线数量计算）
        # 先计算配方中的单位设备成本
        equipment_cost_from_recipe = recipe["equipment_cost_per_unit"] * quantity

        # 再模拟分配生产线，计算实际需要的运营成本
        idle_lines = [
            (line_id, line_data)
            for line_id, line_data in self.production_lines.items()
            if line_data["status"] in ["idle","working"]  # 修复：只考虑空闲生产线
        ]
        idle_lines.sort(key=lambda x: x[1]["remaining_capacity"], reverse=True)

        operating_cost = 0
        remaining_quantity = quantity
        lines_needed = 0

        for line_id, line_data in idle_lines:
            operating_cost += line_data["operating_cost"]
            remaining_quantity -= line_data["remaining_capacity"]
            lines_needed += 1

            if remaining_quantity <= 0:
                break

        # 如果没有可用生产线，使用平均成本估算
        if lines_needed == 0 and self.production_lines:
            completed_lines = [l for l in self.production_lines.values()
                             if l["status"] != "under_construction"]
            if completed_lines:
                avg_operating_cost = sum(line["operating_cost"] for line in completed_lines) / len(completed_lines)
                # 估算需要的生产线数量
                estimated_lines = max(1, int((quantity / 50) + 0.5))  # 假设平均产能50
                operating_cost = avg_operating_cost * estimated_lines

        equipment_cost = equipment_cost_from_recipe + operating_cost

        # 5. 计算总成本
        total_cost = material_costs + labor_cost + equipment_cost
        unit_cost = total_cost / quantity if quantity > 0 else 0

        return self.success_response(response, f"成功计算产品 {product_id} 的生产成本", {
            "product_id": product_id,
            "quantity": quantity,
            "material_costs": material_costs,
            "labor_cost": labor_cost,
            "equipment_cost": equipment_cost,
            "total_cost": total_cost,
            "unit_cost": unit_cost,
            "material_details": material_details,
            "lines_needed": lines_needed
        })

    # ========== 查询方法 ==========

    @with_response("get_production_status")
    def get_production_status(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取生产状态总览

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含生产状态信息的统一响应对象
        """
        # 统计生产线状态
        lines_by_status = {
            "under_construction": 0,
            "idle": 0,
            "working": 0,
            "maintaining": 0
        }

        for line_data in self.production_lines.values():
            status = line_data["status"]
            lines_by_status[status] = lines_by_status.get(status, 0) + 1

        # 统计计划状态
        plans_by_status = {
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0
        }

        for plan in self.production_plans:
            status = plan["status"]
            plans_by_status[status] = plans_by_status.get(status, 0) + 1

        # 获取产能数据（从ModuleResponse中提取）
        utilization_response = self.calculate_capacity_utilization()
        capacity_utilization = utilization_response.data["capacity_utilization"]

        total_capacity_response = self.get_total_capacity()
        total_capacity = total_capacity_response.data["total_capacity"]

        available_capacity_response = self.get_available_capacity()
        available_capacity = available_capacity_response.data["available_capacity"]

        occupied_capacity_response = self.get_occupied_capacity()
        occupied_capacity = occupied_capacity_response.data["occupied_capacity"]

        # 构建产品配方信息列表
        product_recipes_list = []
        for product_id, recipe in self.product_recipes.items():
            product_recipes_list.append({
                "product_id": product_id,
                "raw_materials": recipe.get("raw_materials", {}),
                "production_time": recipe.get("production_time", 0),
                "labor_cost_per_unit": recipe.get("labor_cost_per_unit", 0),
                "equipment_cost_per_unit": recipe.get("equipment_cost_per_unit", 0)
            })

        production_plans = []
        for plan in self.production_plans:
            production_plans.append(plan)
        # 设置响应数据
        status_data = {
            "production_lines": {
                "total": len(self.production_lines),
                "by_status": lines_by_status,
                "total_capacity": total_capacity,
                "available_capacity": available_capacity,
                "occupied_capacity": occupied_capacity
            },
            "production_plans": production_plans,
            "product_recipes": product_recipes_list,
            "capacity_utilization": capacity_utilization,
            "production_metrics": self.production_metrics
        }

        return self.success_response(response, "成功获取生产状态总览", status_data)

    @with_response("get_production_plan_detail")
    def get_production_plan_detail(self, plan_id: str, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取生产计划详情

        Args:
            plan_id: 生产计划ID
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含计划详情的统一响应对象
        """
        plan = self._find_plan(plan_id)
        if plan:
            return self.success_response(response, f"成功获取生产计划 {plan_id} 的详情", plan)
        else:
            return self.error_response(response, "PLAN_NOT_FOUND", f"生产计划 {plan_id} 不存在")

    @with_response("get_all_production_lines")
    def get_all_production_lines(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取所有生产线列表

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含生产线列表的统一响应对象
        """
        production_lines = list(self.production_lines.values())

        return self.success_response(response, f"成功获取 {len(production_lines)} 条生产线信息", {
            "production_lines": production_lines,
            "total_count": len(production_lines)
        })

    @with_response("get_all_production_plans")
    def get_all_production_plans(self, status_filter: Optional[str] = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取所有生产计划

        Args:
            status_filter: 状态过滤器（可选）
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含计划列表的统一响应对象
        """
        if status_filter:
            plans = [plan for plan in self.production_plans if plan["status"] == status_filter]
            message = f"成功获取状态为 {status_filter} 的生产计划 {len(plans)} 个"
        else:
            plans = self.production_plans.copy()
            message = f"成功获取所有生产计划 {len(plans)} 个"

        return self.success_response(response, message, {
            "production_plans": plans,
            "total_count": len(plans),
            "status_filter": status_filter
        })

    @with_response("get_state")
    def get_state(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        获取当前模块状态

        Args:
            response: 响应对象（由装饰器自动注入）

        Returns:
            ModuleResponse: 包含当前模块状态的统一响应对象
        """
        try:
            # 获取生产状态总览
            production_status = self.get_production_status()

            # 获取生产线详细信息
            production_lines_details = list(self.production_lines.values())
            # 过滤生产线详细信息，只保留指定属性
            filtered_production_lines = []
            for line in production_lines_details:
                filtered_line = {
                    "line_id": line.get("line_id"),
                    "line_type": line.get("line_type"),
                    "capacity": line.get("capacity"),
                    "remaining_capacity": line.get("remaining_capacity"),
                    "total_produced": line.get("total_produced")
                }
                filtered_production_lines.append(filtered_line)
            production_lines_details = filtered_production_lines
            grouped = defaultdict(list)
            for plan in self.production_plans:
                status = plan.get("status", "unknown")
                if status != "unknown" and status != "completed":
                    grouped[status].append(plan)
            status_plans = dict(grouped)
            state = {
                # "module_id": self.module_id,
                "module_type": self.module_type,
                "products_idList": self.enterprise.salable_products_idList,
                "total_capacity": production_status.data["production_lines"]["total_capacity"],
                "available_capacity": production_status.data["production_lines"]["available_capacity"],
                "occupied_capacity": production_status.data["production_lines"]["occupied_capacity"],
                "production_lines": {
                    **production_status.data["production_lines"],
                    "details": production_lines_details  # 添加详细生产线信息
                },
                "production_plans": status_plans,
                "product_recipes": production_status.data["product_recipes"],
                "production_metrics": production_status.data["production_metrics"],
                "capacity_utilization": production_status.data["capacity_utilization"],
                "recovery_guard": self._get_recovery_guard_status(),
                "cash_guard": self._get_cash_guard_status(),
                "margin_guard": self._get_margin_guard_status(),
            }

            return self.success_response(response, "获取生产模块状态成功", state)
        except Exception as e:
            return self.error_response(response, "STATE_ERROR", f"获取生产模块状态失败: {e}")

        # ========== 内部辅助方法 ==========

    def _find_plan(self, plan_id: str) -> Optional[Dict]:
        """查找生产计划"""
        for plan in self.production_plans:
            if plan["plan_id"] == plan_id:
                return plan
        return None

    def _safe_number(self, value, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _get_cash_summary(self) -> Dict:
        finance_manager = super().get_module_by_type("FinanceManager")
        if not finance_manager:
            return {
                "current_cash": 0.0,
                "warning_threshold": 0.0,
                "critical_threshold": 0.0,
                "available_after_warning_buffer": 0.0,
                "cash_level": "unknown",
                "has_warning_buffer": False,
            }
        finance_state = finance_manager.get_state()
        finance_data = finance_state.data if getattr(finance_state, "success", False) else {}
        return finance_data.get("cash_summary") or {
            "current_cash": self._safe_number(finance_data.get("cash")),
            "warning_threshold": 0.0,
            "critical_threshold": 0.0,
            "available_after_warning_buffer": self._safe_number(finance_data.get("cash")),
            "cash_level": "unknown",
            "has_warning_buffer": True,
        }

    def _estimate_conversion_cost(self, recipe: Dict, quantity: float, assigned_lines: Optional[List[Dict]] = None) -> Dict:
        labor_cost = self._safe_number(recipe.get("labor_cost_per_unit")) * quantity
        equipment_cost_from_recipe = self._safe_number(recipe.get("equipment_cost_per_unit")) * quantity
        operating_cost = 0.0
        if assigned_lines:
            operating_cost = sum(
                self._safe_number(self.production_lines[line["line_id"]]["operating_cost"])
                for line in assigned_lines
                if line.get("line_id") in self.production_lines
            )
        equipment_cost = equipment_cost_from_recipe + operating_cost
        return {
            "labor_cost": labor_cost,
            "equipment_cost": equipment_cost,
            "conversion_cost": labor_cost + equipment_cost,
        }

    def _estimate_expected_sale_floor(self, product_id: str) -> Dict:
        """估算当前产品的 B2B 售价底线，供生产毛利护栏使用。"""
        sales_manager = super().get_module_by_type("SalesManager")
        inventory_manager = super().get_module_by_type("InventoryManager")
        if sales_manager and hasattr(sales_manager, "_resolve_b2b_min_price"):
            try:
                pricing = sales_manager._resolve_b2b_min_price(product_id) or {}
                return {
                    "expected_sale_unit_price": self._safe_number(pricing.get("min_price")),
                    "reference_price": self._safe_number(pricing.get("reference_price")),
                    "landed_unit_cost": self._safe_number(pricing.get("landed_unit_cost")),
                    "pricing_strategy": pricing.get("strategy"),
                }
            except Exception:
                pass

        inventory_detail = inventory_manager.get_inventory_detail(product_id) if inventory_manager else None
        inventory_data = (
            inventory_detail.data
            if getattr(inventory_detail, "success", False) and isinstance(inventory_detail.data, dict)
            else {}
        )
        fallback_price = self._safe_number(inventory_data.get("unit_price"))
        if fallback_price <= 0:
            fallback_price = self._safe_number(
                (self.config.EXPECTED_SALE_PRICE_FALLBACKS or {}).get(product_id)
            )
        return {
            "expected_sale_unit_price": fallback_price,
            "reference_price": fallback_price,
            "landed_unit_cost": fallback_price,
            "pricing_strategy": "inventory_price_fallback",
        }

    def _estimate_total_material_cost(self, recipe: Dict, quantity: float) -> float:
        """按当前原料库存单价估算一笔生产计划的总原料成本。"""
        inventory_manager = super().get_module_by_type("InventoryManager")
        total_material_cost = 0.0
        for material_id, required_per_unit in (recipe.get("raw_materials") or {}).items():
            required_quantity = self._safe_number(required_per_unit) * quantity
            material_detail = inventory_manager.get_inventory_detail(material_id) if inventory_manager else None
            material_data = (
                material_detail.data
                if getattr(material_detail, "success", False) and isinstance(material_detail.data, dict)
                else {}
            )
            unit_price = self._safe_number(material_data.get("unit_price"))
            total_material_cost += required_quantity * unit_price
        return total_material_cost

    def _evaluate_margin_guard_for_plan(
        self,
        product_id: str,
        quantity: float,
        assigned_lines: Optional[List[Dict]] = None,
        candidate: Optional[Dict] = None,
    ) -> Dict:
        """评估一笔恢复性生产/扩产决策的预期毛利健康度。"""
        recipe = self.product_recipes.get(product_id) or {}
        if not recipe or quantity <= 0:
            return {
                "product_id": product_id,
                "estimated_sale_unit_price": 0.0,
                "estimated_unit_cost": 0.0,
                "projected_revenue": 0.0,
                "projected_total_cost": 0.0,
                "projected_gross_profit": 0.0,
                "projected_gross_margin_rate": -1.0,
                "guard_level": "hard_blocked",
                "allow_service_recovery": False,
                "allow_capacity_expansion": False,
                "reason_codes": ["MISSING_RECIPE_OR_ZERO_QUANTITY"],
                "pricing_strategy": None,
            }

        pricing_floor = self._estimate_expected_sale_floor(product_id)
        estimated_sale_unit_price = self._safe_number(pricing_floor.get("expected_sale_unit_price"))
        material_cost = self._estimate_total_material_cost(recipe, quantity)
        conversion_costs = self._estimate_conversion_cost(recipe, quantity, assigned_lines)
        projected_total_cost = material_cost + conversion_costs["conversion_cost"]
        estimated_unit_cost = projected_total_cost / quantity if quantity > 0 else 0.0
        projected_revenue = estimated_sale_unit_price * quantity
        projected_gross_profit = projected_revenue - projected_total_cost
        projected_gross_margin_rate = (
            projected_gross_profit / projected_revenue if projected_revenue > 0 else -1.0
        )

        confirmed_backlog_quantity = self._safe_number((candidate or {}).get("confirmed_order_backlog_quantity"))
        stale_backlog_quantity = self._safe_number((candidate or {}).get("stale_backlog_quantity"))
        demand_backlog_quantity = self._safe_number((candidate or {}).get("demand_backlog_quantity"))
        proposal_backlog_quantity = self._safe_number((candidate or {}).get("proposal_backlog_quantity"))
        policy_floor = self._safe_number((candidate or {}).get("policy_floor"))
        on_hand = self._safe_number((candidate or {}).get("on_hand"))
        should_recover_now = bool((candidate or {}).get("should_recover_now"))
        inventory_gap_quantity = max(0.0, policy_floor - on_hand)

        healthy_floor = self._safe_number(self.config.RECOVERY_MARGIN_HEALTHY_FLOOR_RATE, 0.08)
        service_floor = self._safe_number(self.config.RECOVERY_MARGIN_SERVICE_FLOOR_RATE, -0.03)
        build_floor = self._safe_number(self.config.BUILD_LINE_MIN_MARGIN_RATE, 0.10)

        reason_codes = []
        if estimated_sale_unit_price <= 0:
            reason_codes.append("NO_PRICE_SIGNAL")
        if confirmed_backlog_quantity > 0:
            reason_codes.append("CONFIRMED_BACKLOG_SUPPORT")
        if stale_backlog_quantity > 0:
            reason_codes.append("STALE_BACKLOG_SUPPORT")
        if demand_backlog_quantity > 0:
            reason_codes.append("DEMAND_BACKLOG_PRESENT")
        if proposal_backlog_quantity > 0:
            reason_codes.append("PROPOSAL_BACKLOG_PRESENT")
        if inventory_gap_quantity > 0:
            reason_codes.append("FINISHED_GOODS_GAP")

        continuity_pressure = bool(
            confirmed_backlog_quantity > 0
            or stale_backlog_quantity > 0
            or demand_backlog_quantity > 0
            or proposal_backlog_quantity > 0
            or inventory_gap_quantity > 0
            or should_recover_now
        )
        allow_service_recovery = bool(
            projected_revenue > 0
            and projected_gross_margin_rate >= service_floor
            and (confirmed_backlog_quantity > 0 or stale_backlog_quantity > 0)
        )
        allow_continuity_recovery = bool(
            projected_revenue > 0
            and continuity_pressure
        )
        allow_capacity_expansion = bool(
            projected_revenue > 0
            and projected_gross_margin_rate >= build_floor
        )

        if estimated_sale_unit_price <= 0:
            guard_level = "hard_blocked"
        elif projected_gross_margin_rate >= healthy_floor:
            guard_level = "healthy"
            reason_codes.append("HEALTHY_MARGIN")
        elif allow_service_recovery:
            guard_level = "warning"
            reason_codes.append("SERVICE_RECOVERY_OVERRIDE")
        elif allow_continuity_recovery:
            guard_level = "warning"
            reason_codes.append("CONTINUITY_RECOVERY_OVERRIDE")
        else:
            guard_level = "hard_blocked"
            reason_codes.append("NEGATIVE_MARGIN_GUARD")

        return {
            "product_id": product_id,
            "estimated_sale_unit_price": estimated_sale_unit_price,
            "estimated_unit_cost": estimated_unit_cost,
            "reference_price": self._safe_number(pricing_floor.get("reference_price")),
            "landed_unit_cost": self._safe_number(pricing_floor.get("landed_unit_cost")),
            "pricing_strategy": pricing_floor.get("pricing_strategy"),
            "projected_revenue": projected_revenue,
            "projected_total_cost": projected_total_cost,
            "projected_gross_profit": projected_gross_profit,
            "projected_gross_margin_rate": projected_gross_margin_rate,
            "healthy_margin_floor_rate": healthy_floor,
            "service_recovery_floor_rate": service_floor,
            "build_line_floor_rate": build_floor,
            "guard_level": guard_level,
            "allow_service_recovery": allow_service_recovery,
            "allow_continuity_recovery": allow_continuity_recovery,
            "allow_capacity_expansion": allow_capacity_expansion,
            "reason_codes": reason_codes,
        }

    def _get_cash_guard_status(self) -> Dict:
        cash_summary = self._get_cash_summary()
        current_cash = self._safe_number(cash_summary.get("current_cash"))
        warning_threshold = self._safe_number(cash_summary.get("warning_threshold"))
        available_conversion_budget = max(0.0, current_cash - warning_threshold)

        affordable_line_types = []
        for line_type, config in self.LINE_CONFIGS.items():
            if current_cash >= self._safe_number(config.get("build_cost")):
                affordable_line_types.append(line_type)

        recovery_guard = self._get_recovery_guard_status()
        affordable_recovery_candidates = []
        for candidate in recovery_guard.get("candidates") or []:
            if not candidate.get("should_recover_now"):
                continue
            recipe = next(
                (item for item in self.product_recipes.values() if item.get("product_id") == candidate.get("product_id")),
                None
            )
            if not recipe:
                continue
            estimated_costs = self._estimate_conversion_cost(
                recipe=recipe,
                quantity=self._safe_number(candidate.get("recommended_plan_quantity")),
                assigned_lines=[],
            )
            affordable_recovery_candidates.append({
                "product_id": candidate.get("product_id"),
                "recommended_plan_quantity": candidate.get("recommended_plan_quantity"),
                "recommended_daily_capacity": candidate.get("recommended_daily_capacity"),
                "estimated_conversion_cost": estimated_costs["conversion_cost"],
                "cash_feasible": current_cash >= estimated_costs["conversion_cost"],
                "warning_buffer_feasible": available_conversion_budget >= estimated_costs["conversion_cost"],
            })

        if current_cash <= self._safe_number(cash_summary.get("critical_threshold")):
            guard_level = "critical"
        elif current_cash <= warning_threshold:
            guard_level = "warning"
        else:
            guard_level = "healthy"

        return {
            "cash_summary": cash_summary,
            "available_conversion_budget": available_conversion_budget,
            "guard_level": guard_level,
            "affordable_line_types": affordable_line_types,
            "affordable_recovery_candidates": affordable_recovery_candidates,
        }

    def _get_margin_guard_status(self) -> Dict:
        """给恢复性生产和扩产提供预期毛利护栏。"""
        recovery_guard = self._get_recovery_guard_status()
        candidate_evaluations = []
        expansion_candidates = []
        healthy_count = 0
        warning_count = 0
        hard_blocked_count = 0

        for candidate in recovery_guard.get("candidates") or []:
            product_id = candidate.get("product_id")
            recommended_plan_quantity = self._safe_number(candidate.get("recommended_plan_quantity"))
            evaluation = self._evaluate_margin_guard_for_plan(
                product_id=product_id,
                quantity=recommended_plan_quantity,
                assigned_lines=[],
                candidate=candidate,
            )
            candidate_evaluation = {
                **evaluation,
                "should_recover_now": bool(candidate.get("should_recover_now")),
                "recommended_plan_quantity": recommended_plan_quantity,
                "recommended_daily_capacity": self._safe_number(candidate.get("recommended_daily_capacity")),
                "confirmed_order_backlog_quantity": self._safe_number(candidate.get("confirmed_order_backlog_quantity")),
                "stale_backlog_quantity": self._safe_number(candidate.get("stale_backlog_quantity")),
            }
            candidate_evaluations.append(candidate_evaluation)
            if evaluation["guard_level"] == "healthy":
                healthy_count += 1
            elif evaluation["guard_level"] == "warning":
                warning_count += 1
            else:
                hard_blocked_count += 1
            if candidate.get("should_recover_now") and evaluation.get("allow_capacity_expansion"):
                expansion_candidates.append(product_id)

        return {
            "summary": {
                "healthy_candidate_count": healthy_count,
                "warning_candidate_count": warning_count,
                "hard_blocked_candidate_count": hard_blocked_count,
                "has_service_recovery_candidate": any(item.get("allow_service_recovery") for item in candidate_evaluations),
                "has_capacity_expansion_candidate": bool(expansion_candidates),
                "capacity_expansion_candidate_products": expansion_candidates,
            },
            "candidates": candidate_evaluations,
        }

    def _get_recovery_guard_status(self) -> Dict:
        """
        为制造节点生成恢复性供给护栏。
        目标是在缺货、积压、低库存但仍具备原料与产能时，给出一份小步恢复生产建议。
        """
        inventory_manager = super().get_module_by_type("InventoryManager")
        sales_manager = super().get_module_by_type("SalesManager")

        sales_state_result = sales_manager.get_state()
        sales_state = sales_state_result.data if getattr(sales_state_result, "success", False) else {}
        demand_backlog = sales_state.get("demand_backlog") or {}
        backlog_breakdown = sales_state.get("backlog_breakdown") or {}
        demand_backlog_by_product = demand_backlog.get("by_product") or {}
        confirmed_backlog_by_product = (
            (backlog_breakdown.get("confirmed_order_backlog") or {}).get("by_product") or {}
        )
        proposal_backlog_by_product = (
            (backlog_breakdown.get("proposal_backlog") or {}).get("by_product") or {}
        )
        stale_backlog_by_product = (
            (backlog_breakdown.get("stale_backlog") or {}).get("by_product") or {}
        )

        available_capacity_response = self.get_available_capacity()
        total_capacity_response = self.get_total_capacity()
        available_capacity = self._safe_number(
            available_capacity_response.data.get("available_capacity", 0)
            if getattr(available_capacity_response, "success", False)
            else 0
        )
        total_capacity = self._safe_number(
            total_capacity_response.data.get("total_capacity", 0)
            if getattr(total_capacity_response, "success", False)
            else 0
        )
        idle_lines = [
            line for line in self.production_lines.values()
            if line.get("status") == "idle" and self._safe_number(line.get("remaining_capacity")) > 0
        ]
        working_lines = [
            line for line in self.production_lines.values()
            if line.get("status") == "working" and self._safe_number(line.get("remaining_capacity")) > 0
        ]
        capacity_budget = max(
            0.0,
            available_capacity * self._safe_number(self.config.RECOVERY_MAX_BATCH_SHARE_OF_CAPACITY, 0.75)
        )

        candidates = []
        active_candidate_count = 0
        blocking_candidate_count = 0

        for recipe in self.product_recipes.values():
            product_id = recipe.get("product_id")
            if not product_id:
                continue

            finished_detail_result = inventory_manager.get_inventory_detail(product_id)
            finished_detail = (
                finished_detail_result.data
                if getattr(finished_detail_result, "success", False) and isinstance(finished_detail_result.data, dict)
                else {}
            )
            on_hand = self._safe_number(finished_detail.get("quantity"))
            safety_stock = self._safe_number(finished_detail.get("safety_stock"))
            reorder_point = self._safe_number(finished_detail.get("reorder_point"))
            policy_floor = max(safety_stock, reorder_point)
            low_stock_threshold = (
                policy_floor * self._safe_number(self.config.RECOVERY_LOW_STOCK_RATIO, 0.5)
                if policy_floor > 0
                else self._safe_number(self.config.RECOVERY_MIN_BATCH_QUANTITY, 50.0)
            )

            demand_backlog_quantity = self._safe_number(
                (demand_backlog_by_product.get(product_id) or {}).get("backlog_quantity")
            )
            confirmed_backlog_quantity = self._safe_number(
                (confirmed_backlog_by_product.get(product_id) or {}).get("quantity")
            )
            proposal_backlog_quantity = self._safe_number(
                (proposal_backlog_by_product.get(product_id) or {}).get("quantity")
            )
            stale_backlog_quantity = self._safe_number(
                (stale_backlog_by_product.get(product_id) or {}).get("quantity")
            )

            active_plan_quantity = 0.0
            active_plan_count = 0
            for plan in self.production_plans:
                if plan.get("product_id") != product_id or plan.get("status") != "in_progress":
                    continue
                progress = plan.get("progress") or {}
                remaining_quantity = max(
                    0.0,
                    self._safe_number(plan.get("quantity")) - self._safe_number(progress.get("quantity_produced"))
                )
                active_plan_quantity += remaining_quantity
                active_plan_count += 1

            material_feasible_quantity = float("inf")
            material_shortages = []
            raw_material_snapshots = {}
            for material_id, units_per_product in (recipe.get("raw_materials") or {}).items():
                units_per_product = self._safe_number(units_per_product)
                material_detail_result = inventory_manager.get_inventory_detail(material_id)
                material_detail = (
                    material_detail_result.data
                    if getattr(material_detail_result, "success", False) and isinstance(material_detail_result.data, dict)
                    else {}
                )
                material_on_hand = self._safe_number(material_detail.get("quantity"))
                raw_material_snapshots[material_id] = {
                    "on_hand": material_on_hand,
                    "units_per_product": units_per_product,
                }
                if units_per_product <= 0:
                    continue
                feasible_quantity = material_on_hand / units_per_product
                material_feasible_quantity = min(material_feasible_quantity, feasible_quantity)
                if material_on_hand < units_per_product:
                    material_shortages.append({
                        "material_id": material_id,
                        "required_for_one_unit": units_per_product,
                        "on_hand": material_on_hand,
                    })

            if material_feasible_quantity == float("inf"):
                material_feasible_quantity = 0.0

            inventory_gap = max(0.0, policy_floor - on_hand)
            hard_demand_signal = max(demand_backlog_quantity, confirmed_backlog_quantity)
            stale_demand_signal = stale_backlog_quantity * self._safe_number(
                self.config.RECOVERY_STALE_BACKLOG_WEIGHT, 1.0
            )
            soft_demand_signal = proposal_backlog_quantity * self._safe_number(
                self.config.RECOVERY_PROPOSAL_SIGNAL_WEIGHT, 0.25
            )
            policy_gap_signal = inventory_gap * self._safe_number(
                self.config.RECOVERY_POLICY_GAP_MULTIPLIER, 1.5
            )
            target_recovery_quantity = max(
                hard_demand_signal,
                policy_gap_signal,
                stale_demand_signal,
                soft_demand_signal,
            )
            if target_recovery_quantity <= 0 and on_hand <= low_stock_threshold:
                target_recovery_quantity = max(
                    target_recovery_quantity,
                    min(self._safe_number(self.config.RECOVERY_MIN_BATCH_QUANTITY, 50.0), material_feasible_quantity)
                )

            if active_plan_quantity > 0:
                active_plan_offset = active_plan_quantity * self._safe_number(
                    self.config.RECOVERY_ACTIVE_PLAN_OFFSET_SHARE,
                    0.5,
                )
                target_recovery_quantity = max(0.0, target_recovery_quantity - active_plan_offset)

            capped_by_capacity = min(target_recovery_quantity, capacity_budget or available_capacity)
            recommended_plan_quantity = min(capped_by_capacity, material_feasible_quantity)
            if (
                recommended_plan_quantity < self._safe_number(self.config.RECOVERY_MIN_BATCH_QUANTITY, 50.0)
                and recommended_plan_quantity > 0
            ):
                recommended_plan_quantity = min(
                    self._safe_number(self.config.RECOVERY_MIN_BATCH_QUANTITY, 50.0),
                    material_feasible_quantity,
                    capacity_budget or available_capacity
                )
            recommended_plan_quantity = max(0.0, recommended_plan_quantity)
            recommended_daily_capacity = min(recommended_plan_quantity, available_capacity)

            reason_codes = []
            blocking_reasons = []
            if on_hand <= low_stock_threshold:
                reason_codes.append("LOW_FINISHED_GOODS")
            if inventory_gap > 0:
                reason_codes.append("BELOW_POLICY_FLOOR")
            if confirmed_backlog_quantity > 0:
                reason_codes.append("CONFIRMED_ORDER_BACKLOG")
            if demand_backlog_quantity > 0:
                reason_codes.append("DEMAND_BACKLOG")
            if proposal_backlog_quantity > 0:
                reason_codes.append("PROPOSAL_BACKLOG")
            if stale_backlog_quantity > 0:
                reason_codes.append("STALE_BACKLOG")
            if active_plan_count > 0:
                reason_codes.append("ACTIVE_PLAN_EXISTS")
            if available_capacity <= 0:
                blocking_reasons.append("NO_AVAILABLE_CAPACITY")
            if not idle_lines and available_capacity <= 0:
                blocking_reasons.append("NO_IDLE_LINES")
            if material_feasible_quantity <= 0:
                blocking_reasons.append("NO_MATERIAL_FEASIBILITY")
            if material_shortages:
                blocking_reasons.append("MATERIAL_SHORTAGE")

            should_recover_now = bool(
                recommended_plan_quantity > 0
                and available_capacity > 0
                and (
                    hard_demand_signal > 0
                    or inventory_gap > 0
                    or (proposal_backlog_quantity > 0 and on_hand <= low_stock_threshold)
                )
            )
            if should_recover_now:
                active_candidate_count += 1
            elif blocking_reasons:
                blocking_candidate_count += 1

            candidates.append({
                "product_id": product_id,
                "should_recover_now": should_recover_now,
                "reason_codes": reason_codes,
                "blocking_reasons": blocking_reasons,
                "on_hand": on_hand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "policy_floor": policy_floor,
                "low_stock_threshold": low_stock_threshold,
                "demand_backlog_quantity": demand_backlog_quantity,
                "confirmed_order_backlog_quantity": confirmed_backlog_quantity,
                "proposal_backlog_quantity": proposal_backlog_quantity,
                "stale_backlog_quantity": stale_backlog_quantity,
                "active_plan_quantity": active_plan_quantity,
                "active_plan_count": active_plan_count,
                "material_feasible_quantity": material_feasible_quantity,
                "recommended_plan_quantity": recommended_plan_quantity,
                "recommended_daily_capacity": recommended_daily_capacity,
                "raw_material_snapshots": raw_material_snapshots,
                "material_shortages": material_shortages,
            })

        candidates.sort(
            key=lambda item: (
                not item.get("should_recover_now"),
                -self._safe_number(item.get("confirmed_order_backlog_quantity")),
                -self._safe_number(item.get("demand_backlog_quantity")),
                -self._safe_number(item.get("proposal_backlog_quantity")),
            )
        )

        return {
            "summary": {
                "should_recover_any": active_candidate_count > 0,
                "active_candidate_count": active_candidate_count,
                "blocking_candidate_count": blocking_candidate_count,
                "available_capacity": available_capacity,
                "capacity_budget": capacity_budget,
                "total_capacity": total_capacity,
                "idle_line_count": len(idle_lines),
                "working_line_count": len(working_lines),
            },
            "candidates": candidates,
        }

    def _assign_production_lines(self, quantity: float) -> List[str]:
        """
        分配生产线（优先使用产能大的生产线）

        Args:
            quantity: 生产数量

        Returns:
            list: 分配的生产线ID列表
        """
        # 获取所有空闲生产线，按产能降序排序
        idle_lines = [
            (line_id, line_data)
            for line_id, line_data in self.production_lines.items()
            if (line_data["status"] == "idle" or line_data["status"] == "working") and line_data["remaining_capacity"] > 0
        ]
        idle_lines.sort(key=lambda x: x[1]["capacity"], reverse=True)

        assigned = []
        remaining_quantity = quantity

        for line_id, line_data in idle_lines:
            tmp_quantity = remaining_quantity
            remaining_quantity -= line_data["remaining_capacity"]
            cost_capacity = 0
            if remaining_quantity <= 0:
                cost_capacity = tmp_quantity
                remaining_quantity = 0
            else:
                cost_capacity = line_data["remaining_capacity"]
            assigned.append({
                "line_id": line_id,
                "cost_capacity": cost_capacity
            })
            if remaining_quantity <= 0:
                break

        # 如果产能不足，返回空列表
        if remaining_quantity > 0:
            return []

        return assigned

    def _log_event(self, event: Dict):
        """记录生产事件"""
        event["time_step"] = self.enterprise.time_manager.get_day()
        self.production_events.append(event)

    @with_response("generate_production_analysis")
    def generate_production_analysis(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        生成生产情况分析JSON

        Args:
            response: 响应对象，由装饰器自动注入

        Returns:
            ModuleResponse: 包含生产情况分析JSON的统一响应对象
        """
        try:
            # 生产线状态分析
            lines_by_status = {}
            for line_id, line_data in self.production_lines.items():
                status = line_data.get("status", "unknown")
                if status not in lines_by_status:
                    lines_by_status[status] = []
                lines_by_status[status].append(line_data)

            # 生产计划执行分析
            plans_by_status = {}
            for plan in self.production_plans:
                status = plan.get("status", "unknown")
                if status not in plans_by_status:
                    plans_by_status[status] = []
                plans_by_status[status].append(plan)

            # 产能利用率分析
            total_capacity = 0
            occupied_capacity = 0
            for line_data in self.production_lines.values():
                if line_data.get("status") in ["idle", "working"]:
                    total_capacity += line_data.get("capacity", 0)
                if line_data.get("status") in ["idle", "working"]:
                    occupied_capacity +=  line_data.get("capacity", 0) - line_data.get("remaining_capacity", 0)
            capacity_utilization = occupied_capacity / total_capacity if total_capacity > 0 else 0

            # 生产成本分析
            product_cost_analysis = {}
            for plan in self.production_plans:
                product_id = plan.get("product_id")
                if product_id:
                    if product_id not in product_cost_analysis:
                        product_cost_analysis[product_id] = {
                            "total_plans": 0,
                            "total_quantity": 0,
                            "total_cost": 0,
                            "avg_unit_cost": 0
                        }
                    product_cost_analysis[product_id]["total_plans"] += 1
                    product_cost_analysis[product_id]["total_quantity"] += plan.get("quantity", 0)
                    product_cost_analysis[product_id]["total_cost"] += plan.get("total_cost", 0)

            # 计算平均单位成本
            for product_id, data in product_cost_analysis.items():
                if data["total_quantity"] > 0:
                    data["avg_unit_cost"] = data["total_cost"] / data["total_quantity"]

            # 生产效率分析
            total_produced = self.production_metrics.get("total_production", 0)
            total_planned = sum(plan.get("quantity", 0) for plan in self.production_plans)
            production_efficiency = total_produced / total_planned if total_planned > 0 else 0
            self.production_metrics["total_planned"] = total_planned
            # 时间趋势分析
            plans_by_time = {}
            for plan in self.production_plans:
                created_time = plan.get("created_time")
                if created_time:
                    if created_time not in plans_by_time:
                        plans_by_time[created_time] = []
                    plans_by_time[created_time].append(plan)

            # 获取当前时间
            try:
                timestamp = self.enterprise.time_manager.get_day() if hasattr(self.enterprise, 'time_manager') else 0
            except Exception:
                timestamp = 0

            # 构建分析JSON
            analysis_json = {
                "analysis_type": "生产情况分析",
                "timestamp": timestamp,
                "metrics": self.production_metrics,
                "production_lines_analysis": {
                    "by_status": {
                        status: {
                            "count": len(lines),
                            "total_capacity": sum(line.get("capacity", 0) for line in lines)
                        }
                        for status, lines in lines_by_status.items()
                    },
                    "total_lines": len(self.production_lines),
                    "total_capacity": total_capacity,
                    "occupied_capacity": occupied_capacity,
                    "capacity_utilization": capacity_utilization
                },
                "production_plans_analysis": {
                    "by_status": {
                        status: {
                            "count": len(plans),
                            "total_quantity": sum(plan.get("quantity", 0) for plan in plans),
                            "total_cost": sum(plan.get("total_cost", 0) for plan in plans)
                        }
                        for status, plans in plans_by_status.items()
                    },
                    "by_time": {
                        time_step: {
                            "count": len(plans),
                            "total_quantity": sum(plan.get("quantity", 0) for plan in plans)
                        }
                        for time_step, plans in plans_by_time.items()
                    }
                },
                "cost_analysis": {
                    "by_product": product_cost_analysis,
                    "total_production_cost": self.production_metrics.get("total_cost", 0)
                },
                "efficiency_analysis": {
                    "production_efficiency": production_efficiency,
                    "capacity_utilization": capacity_utilization
                },
                "insights": [
                    f"总生产计划数: {self.production_metrics.get('total_plans', 0)}",
                    f"完成生产计划数: {self.production_metrics.get('completed_plans', 0)}",
                    f"总产量: {self.production_metrics.get('total_production', 0)}",
                    f"总生产成本: ¥{self.production_metrics.get('total_cost', 0):,.2f}",
                    f"产能利用率: {capacity_utilization:.2f}",
                    f"生产效率: {production_efficiency:.2f}",
                    f"总计划产量: {self.production_metrics.get('total_planned', 0)}",
                ]
            }

            return self.success_response(
                response,
                "成功生成生产情况分析",
                {
                    "analysis": analysis_json
                }
            )
        except Exception as e:
            return self.error_response(
                response,
                "ANALYSIS_ERROR",
                f"生成生产情况分析失败: {e}"
            )
