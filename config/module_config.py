"""
业务模块配置中心。

这个文件集中维护六个业务模块自身的参数，包括：
- 枚举类字段与可选项
- 阈值、成本、配方约束
- 模块内动作的时间消耗

使用边界：
- 只服务于 `enterprise/modules/*`
- 不承载多企业场景编排、企业初始盘面、Beer Game 市场预设
- 这些场景级固定数据统一放在 `simulation_preset_config.py`
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class FinanceConfig:
    """
    财务模块配置类

    集中管理财务模块的分类字典、预警阈值、折旧规则和动作耗时。

    使用范围：
    - `enterprise/modules/finance_manager.py`
    - `enterprise/modules/decorators.py` 中的 choice 校验
    """
    
    # ==================== 分类配置 ====================
    
    REVENUE_SOURCES: List[str] = field(default_factory=lambda: [
        "order_delivery",   # 订单交付收入
        "b2b_sales",        # B2B销售收入
        "asset_disposal",   # 资产处置收入
        "market",           # 市场收入
        "other_income"      # 其他收入
    ])
    
    COST_CATEGORIES: List[str] = field(default_factory=lambda: [
        "raw_materials",    # 原材料成本
        "production_cost",  # 生产成本
        "labor_cost",       # 人工成本
        "procurement_cost", # 采购成本
        "inventory_cost",   # 库存成本
        "depreciation",     # 折旧
        "produce_cost",     # 生产费用
        "market_cost",      # 市场费用
        "other_cost"        # 其他成本
    ])
    
    ASSET_TYPES: List[str] = field(default_factory=lambda: [
        "fixed_assets",     # 固定资产
        "inventory_value"   # 库存价值
    ])
    
    # ==================== 阈值配置 ====================
    
    # 现金预警阈值（元）
    CASH_WARNING_THRESHOLD: float = 50000.0
    CASH_CRITICAL_THRESHOLD: float = 0.0
    
    # 流动比率预警阈值
    CURRENT_RATIO_WARNING: float = 1.0
    
    # 资产折旧相关
    DEFAULT_DEPRECIATION_RATE: float = 0.1  # 默认年折旧率 10%
    MIN_DEPRECIATION_RATE: float = 0.0
    MAX_DEPRECIATION_RATE: float = 1.0
    
    # ==================== 时间消耗配置（秒） ====================
    
    TIME_COST: Dict[str, int] = field(default_factory=lambda: {
        # 基础财务操作
        "add_revenue": 60,
        "add_cost": 60,
        "pay_accounts_payable": 30,
        
        # 资产管理
        "record_asset_addition": 45,
        "record_asset_depreciation": 60,
        "record_asset_disposal": 90,
        
        # 财务分析
        "calculate_profit": 30,
        "calculate_financial_indicators": 45,
        
        # 报表生成
        "generate_balance_sheet": 60,
        "generate_income_statement": 60,
        "generate_cash_flow_statement": 60,
        
        # 查询操作
        "get_cash_warnings": 10,
        "get_financial_summary": 20,
        "get_transaction_history": 20,
        "get_balance": 10,
        "get_state": 15
    })
    
    # ==================== 财务指标解释阈值 ====================
    
    # 优秀指标阈值
    EXCELLENT_ROI: float = 50.0  # 投资回报率 > 50%
    EXCELLENT_ROE: float = 30.0  # 净资产收益率 > 30%
    EXCELLENT_CURRENT_RATIO: float = 2.0  # 流动比率 > 2.0
    
    # 良好指标阈值
    GOOD_ROI: float = 20.0
    GOOD_ROE: float = 15.0
    GOOD_CURRENT_RATIO: float = 1.5
    
    # 及格指标阈值
    ACCEPTABLE_ROI: float = 0.0
    ACCEPTABLE_ROE: float = 5.0
    ACCEPTABLE_CURRENT_RATIO: float = 1.0
    
    # ==================== 初始化方法 ====================
    
    def get_initial_revenue_dict(self) -> Dict[str, float]:
        """
        获取初始化收入字典
        
        Returns:
            Dict[str, float]: 所有收入来源初始化为0.0
        """
        result = {source: 0.0 for source in self.REVENUE_SOURCES}
        result["total_revenue"] = 0.0
        return result
    
    def get_initial_cost_dict(self) -> Dict[str, float]:
        """
        获取初始化成本字典
        
        Returns:
            Dict[str, float]: 所有成本类别初始化为0.0
        """
        result = {category: 0.0 for category in self.COST_CATEGORIES}
        result["total_cost"] = 0.0
        return result
    
    def get_initial_assets_dict(self, initial_cash: float = 0.0) -> Dict[str, float]:
        """
        获取初始化资产字典
        
        Args:
            initial_cash: 初始现金
            
        Returns:
            Dict[str, float]: 资产字典
        """
        return {
            "cash": initial_cash,
            "inventory_value": 0.0,
            "fixed_assets": 0.0,
            "accumulated_depreciation": 0.0,
            "total_assets": initial_cash
        }
    
    def get_initial_liabilities_dict(self) -> Dict[str, float]:
        """
        获取初始化负债字典
        
        Returns:
            Dict[str, float]: 负债字典
        """
        return {
            "accounts_payable": 0.0,
            "other_liabilities": 0.0,
            "total_liabilities": 0.0
        }
    
    def get_initial_financial_metrics_dict(self) -> Dict[str, float]:
        """
        获取初始化财务指标字典
        
        Returns:
            Dict[str, float]: 财务指标字典
        """
        return {
            "net_profit": 0.0,
            "gross_profit": 0.0,
            "net_profit_rate": 0.0,
            "gross_profit_rate": 0.0,
            "roi": 0.0,
            "roe": 0.0,
            "current_ratio": 0.0,
            "asset_turnover": 0.0
        }
    
    # ==================== 验证方法 ====================
    
    def is_valid_revenue_source(self, source: str) -> bool:
        """验证收入来源是否合法"""
        return source in self.REVENUE_SOURCES
    
    def is_valid_cost_category(self, category: str) -> bool:
        """验证成本类别是否合法"""
        return category in self.COST_CATEGORIES
    
    def is_valid_asset_type(self, asset_type: str) -> bool:
        """验证资产类型是否合法"""
        return asset_type in self.ASSET_TYPES
    
    def is_valid_depreciation_rate(self, rate: float) -> bool:
        """验证折旧率是否合法"""
        return self.MIN_DEPRECIATION_RATE < rate <= self.MAX_DEPRECIATION_RATE


@dataclass
class HRConfig:
    """
    人力资源模块配置类

    集中管理 HR 部门的薪资、招聘、人效阈值和动作耗时。

    使用范围：
    - `enterprise/modules/hr_manager.py`
    - 仅作用于 HR 模块本身，不参与多企业场景编排
    """

    # ==================== 部门和薪资配置 ====================

    # 部门工资配置（人民币/人/月）
    DEPARTMENT_WAGES: Dict[str, float] = field(default_factory=lambda: {
        "HR": 700,
        "PRODUCTION": 900,
        "SALES": 700,
        "PROCUREMENT": 750,
        "INVENTORY": 650,
        "FINANCE": 850
    })

    # 部门招聘成本配置（人民币/人）
    DEPARTMENT_RECRUIT_COSTS: Dict[str, float] = field(default_factory=lambda: {
        "HR": 800,
        "PRODUCTION": 1000,
        "SALES": 800,
        "PROCUREMENT": 1500,
        "INVENTORY": 1200,
        "FINANCE": 1600
    })

    # 招聘周期（时间步）
    RECRUIT_CYCLE: int = 1

    # ==================== 业务约束配置 ====================

    MAX_RECRUIT_PER_TIME: int = 10  # 每次招聘最多人数
    MIN_RECRUIT_PER_TIME: int = 1   # 每次招聘最少人数

    # 利用率阈值
    UTILIZATION_SURPLUS_THRESHOLD: float = 0.3      # 人员冗余阈值
    UTILIZATION_SHORTAGE_THRESHOLD: float = 1.0     # 人员不足阈值
    OPTIMAL_UTILIZATION_LOWER: float = 0.7          # 最优利用率下界
    OPTIMAL_UTILIZATION_UPPER: float = 0.9          # 最优利用率上界

    # ==================== 时间消耗配置（秒） ====================

    TIME_COST: Dict[str, int] = field(default_factory=lambda: {
        "initialize_staffing": 10,
        "get_department_employees": 5,
        "get_all_employees": 5,
        "get_department_utilization": 5,
        "get_average_utilization": 5,
        "handle_recruitment": 15,
        "process_recruitment_completion": 10,
        "get_pending_recruitments": 5,
        "get_recruitment_history": 5,
        "calculate_department_salary": 5,
        "calculate_total_salary": 10,
        "process_salary_payment": 15,
        "get_salary_history": 5,
        "get_latest_salary_payment": 5,
        "update_production_utilization": 5,
        "update_sales_utilization": 5,
        "update_procurement_utilization": 5,
        "update_warehouse_utilization": 5,
        "get_cumulative_recruit_cost": 5,
        "get_cumulative_salary_cost": 5,
        "get_total_human_cost": 5,
        "get_cost_breakdown": 10
    })


@dataclass
class InventoryConfig:
    """
    库存管理模块配置类

    集中管理库存部门的规则阈值、成本参数和动作耗时。

    使用范围：
    - `enterprise/modules/inventory_manager.py`
    - 仅作用于库存模块本身，不参与多企业场景编排
    """

    # ==================== 库存管理配置 ====================

    INITIAL_CAPACITY: int = 10000  # 初始仓库容量

    # 维护成本率（库存价值的百分比）
    MAINTENANCE_COST_RATE: float = 0.00001  # 尽量弱化库存价值持有成本影响

    OPERATING_COST_RATE: float = 0.00001  # 尽量弱化仓储运营成本影响

    # 仓库扩建成本配置。key 为扩仓档位，value 为该档位对应的一次性成本。
    WAREHOUSE_EXPANSION_COSTS: Dict[int, float] = field(default_factory=lambda: {
        1000: 50000,
        2000: 80000,
        5000: 150000
    })

    # 不同扩仓档位对应的最少仓储员工需求。
    WAREHOUSE_EXPANSION_WORKER_REQUIREMENTS: Dict[int, int] = field(default_factory=lambda: {
        1000: 1,
        2000: 2,
        5000: 3,
    })

    # ==================== 仓库容量利用率阈值 ====================

    CAPACITY_LOW_THRESHOLD: float = 0.3  # 使用率低于该值时记为 low
    CAPACITY_WARNING_THRESHOLD: float = 0.75  # 容量预警阈值
    CAPACITY_CRITICAL_THRESHOLD: float = 0.9  # 容量紧急阈值

    # ==================== 时间消耗配置（秒） ====================

    TIME_COST: Dict[str, int] = field(default_factory=lambda: {
        "add_inventory": 10,
        "check_capacity": 5,
        "remove_inventory": 10,
        "expand_warehouse": 30,
        "get_inventory_level": 5,
        "get_inventory_detail": 5,
        "get_inventory_overview": 10,
        "check_low_stock_levels": 15,
        "check_reorder_points": 15,
        "get_capacity_warning": 10,
        "set_inventory_policy": 5,
        "get_inventory_history": 10,
        "calculate_inventory_turnover": 10,
        "conduct_inventory_count": 15,
        "calculate_maintenance_cost": 10,
        "set_maintenance_cost_rate": 5,
        "get_maintenance_cost_summary": 5,
        "get_maintenance_cost_history": 5,
        "set_capacity": 5,
        "initialize_inventory": 15,
        "step": 10,
        "get_state": 5
    })


@dataclass
class ProcurementConfig:
    """
    采购管理模块配置类

    集中管理采购模块的物流参数、人员门槛和动作耗时。

    使用范围：
    - `enterprise/modules/procurement_manager.py`
    - 仅作用于采购模块本身，不参与多企业场景编排
    """

    # ==================== 物流配置 ====================

    LOGISTICS_CONFIGS: Dict[str, Dict] = field(default_factory=lambda: {
        "road": {
            "name": "公路运输",
            "base_fee": 100,
            "unit_fee": 2,
            "transit_time": 3
        },
        "rail": {
            "name": "铁路运输",
            "base_fee": 200,
            "unit_fee": 1.5,
            "transit_time": 2
        },
        "air": {
            "name": "航空运输",
            "base_fee": 500,
            "unit_fee": 5,
            "transit_time": 1
        }
    })

    # ==================== 采购约束 ====================

    MIN_PROCUREMENT_STAFF: int = 1  # 创建订单最少需要员工数
    MIN_CANCEL_STAFF: int = 1       # 取消订单最少需要员工数
    MIN_REGISTER_STAFF: int = 1     # 注册供应商最少需要员工数

    # ==================== B2B 出价策略 ====================

    # 采购侧不再直接拿库存单价做硬上限，而是在参考单价上给出可成交带宽。
    B2B_PRICE_REFERENCE_FALLBACK: float = 1.0
    B2B_BASE_MAX_PRICE_MULTIPLIER: float = 1.22
    B2B_URGENT_MAX_PRICE_MULTIPLIER: float = 1.38
    B2B_LOW_STOCK_MAX_PRICE_MULTIPLIER: float = 1.30

    # ==================== 配方联动补货与顶层保供 ====================

    # 当原料需求是由生产配方反推得到时，避免再被 target_inventory_days 过度放大。
    RECIPE_RECOVERY_SOFT_CAP_MULTIPLIER: float = 1.0
    # 对处于生产恢复瓶颈的原料，允许额外保留一部分安全缓冲。
    RECIPE_RECOVERY_SAFETY_BUFFER_SHARE: float = 1.0
    # 用于将 recovery target 转成“日需求等价”时的默认窗口。
    RECIPE_RECOVERY_DEFAULT_TARGET_DAYS: int = 2
    # proposal backlog 仅作为弱信号参与配方联动补货估算，避免直接按 100% 放大。
    RECOVERY_PROPOSAL_SIGNAL_WEIGHT: float = 0.25
    # Supplier 顶层保供时，为 Manufacturer 当前瓶颈料额外提高优先级。
    TOP_TIER_BOTTLENECK_PRIORITY_BOOST: float = 5000.0
    # Supplier 顶层保供时，若多种原料共同服务于同一恢复性生产目标，额外提高“成套保供”优先级。
    TOP_TIER_PACKAGE_PRIORITY_BOOST: float = 3000.0
    # 当 Supplier 自身库存与在途已经足够覆盖若干轮恢复包需求时，停止继续机械外采。
    TOP_TIER_PACKAGE_COVERAGE_TARGET_ROUNDS: float = 2.0
    # 若关键料处于明确瓶颈，优先使用更快物流。
    TOP_TIER_CRITICAL_LOGISTICS_MODE: str = "air"

    # ==================== 时间消耗配置（秒） ====================

    TIME_COST: Dict[str, int] = field(default_factory=lambda: {
        "initialize_suppliers": 20,
        "create_purchase_order": 30,
        "check_arrived_orders": 15,
        "settle_external_payables": 15,
        "cancel_order": 20,
        "get_order_detail": 5,
        "get_all_orders": 10,
        "get_pending_orders": 8,
        "register_supplier": 15,
        "get_supplier_info": 5,
        "get_all_suppliers": 10,
        "query_suppliers_by_material": 15,
        "calculate_logistics_cost": 5,
        "calculate_total_cost": 10,
        "get_logistics_info": 5,
        "initiate_negotiation": 20,
        "respond_to_offer": 15,
        "get_procurement_status": 10,
        "get_supplier_performance": 10,
        "step": 10,
        "get_state": 5
    })


@dataclass
class SalesConfig:
    """
    销售管理模块配置类

    集中管理销售部门的市场开发参数、人员约束和动作耗时。

    使用范围：
    - `enterprise/modules/sales_manager.py`
    - 仅作用于销售模块本身，不参与多企业场景编排
    """

    # ==================== 市场开发配置 ====================

    MARKET_DEVELOPMENT_CONFIGS: Dict[str, Dict] = field(default_factory=lambda: {
        "regional": {
            "name": "区域市场",
            "cost": 50000,
            "development_time": 1
        },
        "international": {
            "name": "国际市场",
            "cost": 150000,
            "development_time": 1
        }
    })

    TOTAL_POSSIBLE_MARKETS: int = 10  # 市场总数（用于计算市场覆盖率）

    # ==================== 销售约束 ====================

    MIN_DEVELOP_MARKET_STAFF: int = 1   # 开发市场最少需要员工数
    MIN_PLACE_ORDER_STAFF: int = 0      # 接受/下单最少需要员工数
    MIN_SEND_QUOTATION_STAFF: int = 1   # 发送报价最少需要员工数
    MIN_RESPOND_QUOTATION_STAFF: int = 1  # 响应报价最少需要员工数

    # ==================== B2B 出价策略 ====================

    # 销售侧也不再直接把库存单价当成绝对底价，而是根据库存压力给出浮动底价。
    B2B_PRICE_REFERENCE_FALLBACK: float = 1.0
    B2B_BASE_MIN_PRICE_MULTIPLIER: float = 1.00
    B2B_LOW_STOCK_MIN_PRICE_MULTIPLIER: float = 1.10
    B2B_HIGH_STOCK_MIN_PRICE_MULTIPLIER: float = 0.95
    # 无论库存压力如何，B2B 销售底价都不应长期低于自身硬成本。
    B2B_HARD_COST_FLOOR_MULTIPLIER: float = 1.02
    # Supplier 对外部采购后再转卖原料时，需要更高一些的毛利底线来覆盖运营波动。
    B2B_TOP_TIER_RAW_MATERIAL_MARGIN_FLOOR: float = 1.08
    # Manufacturer 对下游销售 beer 时，应保持更积极但更高的售价底线，避免持续低价恢复生产。
    B2B_MANUFACTURER_FINISHED_GOODS_BASE_MIN_PRICE_MULTIPLIER: float = 1.08
    B2B_MANUFACTURER_FINISHED_GOODS_LOW_STOCK_MIN_PRICE_MULTIPLIER: float = 1.16
    B2B_MANUFACTURER_FINISHED_GOODS_HIGH_STOCK_MIN_PRICE_MULTIPLIER: float = 1.02
    B2B_MANUFACTURER_FINISHED_GOODS_MARGIN_FLOOR: float = 1.18

    # ==================== 时间消耗配置（秒） ====================

    TIME_COST: Dict[str, int] = field(default_factory=lambda: {
        "develop_market": 20,
        "check_market_development_completion": 15,
        "get_market_info": 5,
        "get_all_markets": 10,
        "get_active_markets": 8,
        "accept_order": 25,
        "check_deliverable_orders": 15,
        "reject_order": 15,
        "get_order_detail": 5,
        "get_all_sales_orders": 10,
        "get_pending_orders": 8,
        "send_quotation": 15,
        "respond_to_quotation": 15,
        "get_quotation_info": 5,
        "get_all_quotations": 10,
        "get_sales_status": 15,
        "calculate_sales_revenue": 10,
        "get_accepted_orders":10,
        "step": 10,
        "get_state": 5
    })


@dataclass
class ProductionConfig:
    """
    生产管理模块配置类

    集中管理生产部门的产线参数、人员约束和动作耗时。

    使用范围：
    - `enterprise/modules/production_manager.py`
    - 仅作用于生产模块本身，不参与多企业场景编排
    """

    # ==================== 生产线配置 ====================

    LINE_CONFIGS: Dict[str, Dict] = field(default_factory=lambda: {
        "small": {
            "capacity": 500,
            "build_cost": 5000,
            "operating_cost": 20,
            "workers_needed": 2,
            "build_time": 1
        },
        "medium": {
            "capacity": 1000,
            "build_cost": 10000,
            "operating_cost": 40,
            "workers_needed": 3,
            "build_time": 2
        },
        "large": {
            "capacity": 2000,
            "build_cost": 20000,
            "operating_cost": 80,
            "workers_needed": 6,
            "build_time": 3
        }
    })

    MAX_PRODUCTION_LINES: int = 10  # 最大生产线数

    # ==================== 生产约束 ====================

    MIN_CANCEL_PLAN_STAFF: int = 1  # 取消计划最少需要员工数

    # 创建生产计划时，每多少产量至少需要 1 名生产员工。
    PLAN_QUANTITY_PER_WORKER: int = 1000

    # ==================== 恢复性供给护栏 ====================

    # 当成品库存低于 safety_stock/reorder_point 乘以下列比例时，视为低库存恢复信号。
    RECOVERY_LOW_STOCK_RATIO: float = 0.5

    # proposal backlog 仅作为弱信号参与恢复性生产估算，避免直接按 100% 放大。
    RECOVERY_PROPOSAL_SIGNAL_WEIGHT: float = 0.25

    # 单轮恢复性生产建议的最小批量；若资源不足以满足该批量，则保留更小的真实可执行量。
    RECOVERY_MIN_BATCH_QUANTITY: float = 50.0

    # 单轮恢复性生产建议最多使用可用产能的比例，避免一次性吃满全部产能。
    RECOVERY_MAX_BATCH_SHARE_OF_CAPACITY: float = 0.75
    # 当成品库存明显低于策略地板时，恢复性生产对库存缺口可做额外放大，避免恢复过慢。
    RECOVERY_POLICY_GAP_MULTIPLIER: float = 1.5
    # stale backlog 比普通 proposal backlog 更接近真实服务恢复压力。
    RECOVERY_STALE_BACKLOG_WEIGHT: float = 1.0
    # 已存在恢复计划时，只按部分比例抵消新增恢复需求，避免恢复节奏长期偏慢。
    RECOVERY_ACTIVE_PLAN_OFFSET_SHARE: float = 0.5

    # ==================== 生产毛利护栏 ====================

    # 恢复性生产在正常经营模式下，期望达到的最低毛利率。
    RECOVERY_MARGIN_HEALTHY_FLOOR_RATE: float = 0.08

    # 若存在真实 confirmed/stale backlog，可容忍的小幅低毛利恢复区间。
    RECOVERY_MARGIN_SERVICE_FLOOR_RATE: float = -0.03

    # 扩产比恢复生产更严格；若预计毛利率低于该阈值，不建议建设新产线。
    BUILD_LINE_MIN_MARGIN_RATE: float = 0.10
    # 当库存单价或销售侧价格信号缺失时，给关键成品一个经营性售价回退，避免冷启动阶段完全无价可算。
    EXPECTED_SALE_PRICE_FALLBACKS: Dict[str, float] = field(default_factory=lambda: {
        "beer": 140.0,
    })

    # ==================== 时间消耗配置（秒） ====================

    TIME_COST: Dict[str, int] = field(default_factory=lambda: {
        "build_production_line": 30,
        "check_construction_completion": 15,
        "get_production_line_status": 5,
        "get_total_capacity": 5,
        "get_available_capacity": 5,
        "get_occupied_capacity": 5,
        "calculate_capacity_utilization": 10,
        "set_product_recipe": 10,
        "get_product_recipe": 5,
        "create_production_plan": 20,
        "execute_production_plan": 30,
        "check_completed_plans": 20,
        "cancel_production_plan": 15,
        "calculate_production_cost": 25,
        "get_production_status": 20,
        "get_production_plan_detail": 5,
        "get_all_production_lines": 10,
        "get_all_production_plans": 10,
        "get_state": 5
    })


# ==================== 配置工厂 ====================

class ModuleConfigFactory:
    """
    模块配置工厂。

    使用范围：
    - `enterprise/modules/*_manager.py` 在未显式注入配置时可回退到这里
    - 便于后续按模块替换或覆写配置实例
    """
    
    _configs = {
        "finance": FinanceConfig(),
        "hr": HRConfig(),
        "inventory": InventoryConfig(),
        "procurement": ProcurementConfig(),
        "production": ProductionConfig(),
        "sales": SalesConfig(),
    }
    
    @classmethod
    def get_config(cls, module_type: str):
        """
        获取指定模块的配置
        
        Args:
            module_type: 模块类型（如 "finance", "production"）
            
        Returns:
            配置对象，如果不存在则返回None
        """
        config = cls._configs.get(module_type)
        if config is None:
            raise ValueError(f"Unknown module type: {module_type}")
        return config
    
    @classmethod
    def register_config(cls, module_type: str, config):
        """
        注册新的模块配置
        
        Args:
            module_type: 模块类型
            config: 配置对象
        """
        cls._configs[module_type] = config
