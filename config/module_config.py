"""
Business module configuration centre.

This document focuses on maintaining the parameters of the six business modules themselves, including:
- Enumeration fields and options
- Thresholds, costs, formulation constraints
- Time consumption of actions within modules

Use boundary:
- Only at `enterprise/modules/*`
- No multi-enterprise scenario, enterprise initial disk, Beer Game market preset
- These scene-level fixed data are unified at `simulation_preset_config.py`
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class FinanceConfig:
    """
    Finance module configuration Category

    The classification dictionary, warning threshold, depreciation rules and actions of the financial module are centrally managed.

    Scope of use:
    - `enterprise/modules/finance_manager.py`
    - choice verification in `enterprise/modules/decorators.py`
        """
    
    
    REVENUE_SOURCES: List[str] = field(default_factory=lambda: [
        "order_delivery",   # Income from order delivery
        "b2b_sales",        # B2B sales revenue
        "asset_disposal",   # Income from disposal of assets
        "market",           # Market income
        "other_income"      # Other income
    ])
    
    COST_CATEGORIES: List[str] = field(default_factory=lambda: [
        "raw_materials",    # Cost of raw materials
        "production_cost",  # Production costs
        "labor_cost",       # Labour costs
        "procurement_cost", # Procurement costs
        "inventory_cost",   # Cost of inventory
        "depreciation",     # Depreciation
        "produce_cost",     # Production costs
        "market_cost",      # Market costs
        "other_cost"        # Other costs
    ])
    
    ASSET_TYPES: List[str] = field(default_factory=lambda: [
        "fixed_assets",     # Fixed assets
        "inventory_value"   # Inventory value
    ])
    
    
    # Cash warning threshold ($)
    CASH_WARNING_THRESHOLD: float = 50000.0
    CASH_CRITICAL_THRESHOLD: float = 0.0
    
    # Flow ratio early warning threshold
    CURRENT_RATIO_WARNING: float = 1.0
    
    # Depreciation of assets
    DEFAULT_DEPRECIATION_RATE: float = 0.1  # Default annual depreciation rate 10%
    MIN_DEPRECIATION_RATE: float = 0.0
    MAX_DEPRECIATION_RATE: float = 1.0
    
    
    TIME_COST: Dict[str, int] = field(default_factory=lambda: {
        # Basic financial operations
        "add_revenue": 60,
        "add_cost": 60,
        "pay_accounts_payable": 30,
        
        # Asset management
        "record_asset_addition": 45,
        "record_asset_depreciation": 60,
        "record_asset_disposal": 90,
        
        # Financial analysis
        "calculate_profit": 30,
        "calculate_financial_indicators": 45,
        
        # Report Generation
        "generate_balance_sheet": 60,
        "generate_income_statement": 60,
        "generate_cash_flow_statement": 60,
        
        # Query Operations
        "get_cash_warnings": 10,
        "get_financial_summary": 20,
        "get_transaction_history": 20,
        "get_balance": 10,
        "get_state": 15
    })
    
    
    # Threshold of excellent indicators
    EXCELLENT_ROI: float = 50.0  # Investment return > 50%
    EXCELLENT_ROE: float = 30.0  # Net asset return > 30 per cent
    EXCELLENT_CURRENT_RATIO: float = 2.0  # Mobility ratio > 2.0
    
    # Good indicator threshold
    GOOD_ROI: float = 20.0
    GOOD_ROE: float = 15.0
    GOOD_CURRENT_RATIO: float = 1.5
    
    # Pass indicator threshold
    ACCEPTABLE_ROI: float = 0.0
    ACCEPTABLE_ROE: float = 5.0
    ACCEPTABLE_CURRENT_RATIO: float = 1.0
    
    
    def get_initial_revenue_dict(self) -> Dict[str, float]:
        """
        Get Initialized Income Dictionary
                
        Returns:
            Dict [str, flat]: All sources of income are initially 0.0
                """
        result = {source: 0.0 for source in self.REVENUE_SOURCES}
        result["total_revenue"] = 0.0
        return result
    
    def get_initial_cost_dict(self) -> Dict[str, float]:
        """
        Get Initial Cost Dictionary
                
        Returns:
            Dict [str, float]: Initialization of all cost categories to 0.0
                """
        result = {category: 0.0 for category in self.COST_CATEGORIES}
        result["total_cost"] = 0.0
        return result
    
    def get_initial_assets_dict(self, initial_cash: float = 0.0) -> Dict[str, float]:
        """
        Get Initialized Asset Dictionary
                
        Args:
            parameter: Initial cash
                        
        Returns:
            Dict[str, float]: Asset dictionary
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
        Get Initialised Liabilities Dictionary
                
        Returns:
            Dict[str, float]: Debt Dictionary
                """
        return {
            "accounts_payable": 0.0,
            "other_liabilities": 0.0,
            "total_liabilities": 0.0
        }
    
    def get_initial_financial_metrics_dict(self) -> Dict[str, float]:
        """
        Get Initialized Financial Indicators Dictionary
                
        Returns:
            Dict [str, float]: dictionaries of financial indicators
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
    
    
    def is_valid_revenue_source(self, source: str) -> bool:
        """Validation of legal sources of income"""
        return source in self.REVENUE_SOURCES
    
    def is_valid_cost_category(self, category: str) -> bool:
        """Validate the legality of cost categories"""
        return category in self.COST_CATEGORIES
    
    def is_valid_asset_type(self, asset_type: str) -> bool:
        """Verifying the legality of asset types"""
        return asset_type in self.ASSET_TYPES
    
    def is_valid_depreciation_rate(self, rate: float) -> bool:
        """Validate depreciation"""
        return self.MIN_DEPRECIATION_RATE < rate <= self.MAX_DEPRECIATION_RATE


@dataclass
class HRConfig:
    """
    Human resources module configuration Category

    Centrally managed HR department payroll, recruitment, human impact thresholds and time-consuming operations.

    Scope of use:
    - `enterprise/modules/hr_manager.py`
    - Only for HR module itself, not participating in multi-enterprise scenario
        """


    # < x6/ > Wage Allocation (NMB/person/month)
    DEPARTMENT_WAGES: Dict[str, float] = field(default_factory=lambda: {
        "HR": 700,
        "PRODUCTION": 900,
        "SALES": 700,
        "PROCUREMENT": 750,
        "INVENTORY": 650,
        "FINANCE": 850
    })

    # < x6/> Recruitment cost allocation (NMB/person)
    DEPARTMENT_RECRUIT_COSTS: Dict[str, float] = field(default_factory=lambda: {
        "HR": 800,
        "PRODUCTION": 1000,
        "SALES": 800,
        "PROCUREMENT": 1500,
        "INVENTORY": 1200,
        "FINANCE": 1600
    })

    # Recruitment cycle (timescale)
    RECRUIT_CYCLE: int = 1


    MAX_RECRUIT_PER_TIME: int = 10  # Maximum number per recruitment
    MIN_RECRUIT_PER_TIME: int = 1   # Minimum number per recruitment

    # Utilization threshold
    UTILIZATION_SURPLUS_THRESHOLD: float = 0.3      # Personnel redundancy threshold
    UTILIZATION_SHORTAGE_THRESHOLD: float = 1.0     # Personnel deficit threshold
    OPTIMAL_UTILIZATION_LOWER: float = 0.7          # Underutilization
    OPTIMAL_UTILIZATION_UPPER: float = 0.9          # Highest utilization


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
    Inventory management module configuration Category

    Centrally managed inventory department rule thresholds, cost parameters and actions are time-consuming.

    Scope of use:
    - `enterprise/modules/inventory_manager.py`
    - Use only the inventory module itself and do not participate in the multi-enterprise scenario
        """


    INITIAL_CAPACITY: int = 10000  # Initial warehouse capacity

    # Maintenance cost rate (percentage of inventory value)
    MAINTENANCE_COST_RATE: float = 0.00001  # Minimize the cost impact of holding inventory value

    OPERATING_COST_RATE: float = 0.00001  # Minimize the cost impact of warehousing operations

    # Warehouse expansion cost configuration. Key is the one-time cost associated with the silo.
    WAREHOUSE_EXPANSION_COSTS: Dict[int, float] = field(default_factory=lambda: {
        1000: 50000,
        2000: 80000,
        5000: 150000
    })

    # Minimum storage staff requirements for different silos.
    WAREHOUSE_EXPANSION_WORKER_REQUIREMENTS: Dict[int, int] = field(default_factory=lambda: {
        1000: 1,
        2000: 2,
        5000: 3,
    })


    CAPACITY_LOW_THRESHOLD: float = 0.3  # Low when usage below this value
    CAPACITY_WARNING_THRESHOLD: float = 0.75  # Capacity early warning threshold
    CAPACITY_CRITICAL_THRESHOLD: float = 0.9  # Capacity emergency threshold


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
    Procurement management module configuration Category

    The logistics parameters, personnel thresholds and movements of the procurement module are centrally managed and time-consuming.

    Scope of use:
    - `enterprise/modules/procurement_manager.py`
    - serve only the procurement module itself and do not participate in the multi-enterprise scenario
        """


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


    MIN_PROCUREMENT_STAFF: int = 1  # Minimum number of employees required to create an order
    MIN_CANCEL_STAFF: int = 1       # Minimum number of employees required to cancel the order
    MIN_REGISTER_STAFF: int = 1     # Minimum number of registered vendors required


    # Instead of using the unit price of inventory as a hard cap, the side of the procurement gives a tradeable bandwidth on the reference unit price.
    B2B_PRICE_REFERENCE_FALLBACK: float = 1.0
    B2B_BASE_MAX_PRICE_MULTIPLIER: float = 1.22
    B2B_URGENT_MAX_PRICE_MULTIPLIER: float = 1.38
    B2B_LOW_STOCK_MAX_PRICE_MULTIPLIER: float = 1.30


    # When raw material demand is inverted by the production formulation, it is avoided being over-magnified by target_inventory_days.
    RECIPE_RECOVERY_SOFT_CAP_MULTIPLIER: float = 1.0
    # For raw material, which is a production recovery bottleneck, an additional part of the security buffer is allowed.
    RECIPE_RECOVERY_SAFETY_BUFFER_SHARE: float = 1.0
    # The default window for converting the value of a value value into a " daily demand equivalent " .
    RECIPE_RECOVERY_DEFAULT_TARGET_DAYS: int = 2
    # Proposal backlog is only used as a weak signal in the estimation of the formula combination replenishment to avoid a direct 100% magnification.
    RECOVERY_PROPOSAL_SIGNAL_WEIGHT: float = 0.25
    # The Supplier top-level insulation has added priority to the current Manufacturer bottlenecks.
    TOP_TIER_BOTTLENECK_PRIORITY_BOOST: float = 5000.0
    # During the Supplier top-level insulation, additional raw material priority was given to raw material co-services to the same restorative production target.
    TOP_TIER_PACKAGE_PRIORITY_BOOST: float = 3000.0
    # The continuation of mechanical extraction was stopped when Supplier's own inventory and in transit were sufficient to cover several recovery package requirements.
    TOP_TIER_PACKAGE_COVERAGE_TARGET_ROUNDS: float = 2.0
    # If key materials are identified as bottlenecks, priority is given to faster logistics.
    TOP_TIER_CRITICAL_LOGISTICS_MODE: str = "air"


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
    Sales management module configuration Category

    The market development parameters, personnel constraints and movements of department sales are centrally managed.

    Scope of use:
    - `enterprise/modules/sales_manager.py`
    - Only for the sales module itself, not for the multi-enterprise scenery
        """


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

    TOTAL_POSSIBLE_MARKETS: int = 10  # Total market (for market coverage)


    MIN_DEVELOP_MARKET_STAFF: int = 1   # Minimum number of employees needed to develop the market
    MIN_PLACE_ORDER_STAFF: int = 0      # Minimum number of staff required to accept/decree
    MIN_SEND_QUOTATION_STAFF: int = 1   # Minimum number of employees required to send offers
    MIN_RESPOND_QUOTATION_STAFF: int = 1  # Minimum number of staff required to respond to offers


    # The sales side no longer directly treats the unit price of the inventory as the absolute floor, but rather gives the floating floor price based on the pressure of the stock.
    B2B_PRICE_REFERENCE_FALLBACK: float = 1.0
    B2B_BASE_MIN_PRICE_MULTIPLIER: float = 1.00
    B2B_LOW_STOCK_MIN_PRICE_MULTIPLIER: float = 1.10
    B2B_HIGH_STOCK_MIN_PRICE_MULTIPLIER: float = 0.95
    # Whatever the stock pressure, the B2B sales floor should not be below its own hard cost in the long term.
    B2B_HARD_COST_FLOOR_MULTIPLIER: float = 1.02
    # Upon resale of raw material after external procurement, Suplier required a higher Māori base to cover operational fluctuations.
    B2B_TOP_TIER_RAW_MATERIAL_MARGIN_FLOOR: float = 1.08
    # Manufacturer should maintain a more active, but higher, sales floor for downstream sales to beer and avoid a continued low-cost resumption of production.
    B2B_MANUFACTURER_FINISHED_GOODS_BASE_MIN_PRICE_MULTIPLIER: float = 1.08
    B2B_MANUFACTURER_FINISHED_GOODS_LOW_STOCK_MIN_PRICE_MULTIPLIER: float = 1.16
    B2B_MANUFACTURER_FINISHED_GOODS_HIGH_STOCK_MIN_PRICE_MULTIPLIER: float = 1.02
    B2B_MANUFACTURER_FINISHED_GOODS_MARGIN_FLOOR: float = 1.18


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
    Production management module configuration Category

    The production of department line parameters, human constraints and time-consuming operations are centrally managed.

    Scope of use:
    - `enterprise/modules/production_manager.py`
    - Use only the production module itself and do not participate in the multi-enterprise scenery
        """


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

    MAX_PRODUCTION_LINES: int = 10  # Maximum number of production lines


    MIN_CANCEL_PLAN_STAFF: int = 1  # Minimum number of employees required to cancel the plan

    # At the time of the creation of the production plan, at least one production worker is required for every production.
    PLAN_QUANTITY_PER_WORKER: int = 1000


    # Low stock recovery signals are considered to be held at a level below < x 17/ > when this is multiplied by the following ratio.
    RECOVERY_LOW_STOCK_RATIO: float = 0.5

    # Proposal backlog is only used as a weak signal to estimate restorative production, avoiding direct 100% magnification.
    RECOVERY_PROPOSAL_SIGNAL_WEIGHT: float = 0.25

    # The minimum amount recommended for single-cycle restorative production; if resources are insufficient to meet that volume, a smaller, real implementable amount is retained.
    RECOVERY_MIN_BATCH_QUANTITY: float = 50.0

    # A maximum of capacity is recommended for a single round of restorative production to avoid full one-time capacity.
    RECOVERY_MAX_BATCH_SHARE_OF_CAPACITY: float = 0.75
    # When the stock of pawns is clearly below the strategic floor, the stock gap can be magnified by restorative production to avoid a slow recovery.
    RECOVERY_POLICY_GAP_MULTIPLIER: float = 1.5
    # This post is part of our special coverage Global Development 2011.
    RECOVERY_STALE_BACKLOG_WEIGHT: float = 1.0
    # Where recovery plans already exist, only additional recovery needs are partially offset to avoid a long-term slowdown in recovery.
    RECOVERY_ACTIVE_PLAN_OFFSET_SHARE: float = 0.5


    # Restorative production is expected to achieve the minimum Māori rate under the normal business model.
    RECOVERY_MARGIN_HEALTHY_FLOOR_RATE: float = 0.08

    # If there is a real confirmed/stale backlog, a small low-māori recovery area is tolerated.
    RECOVERY_MARGIN_SERVICE_FLOOR_RATE: float = -0.03

    # The increase is more stringent than the resumption of production; if the Māori rate is expected to fall below that threshold, the construction of new production lines is not recommended.
    BUILD_LINE_MIN_MARGIN_RATE: float = 0.10
    # When the unit price of the inventory or the sales side price signal is missing, an operational sale price for the key product is reversed to avoid a completely priceless cold start-up phase.
    EXPECTED_SALE_PRICE_FALLBACKS: Dict[str, float] = field(default_factory=lambda: {
        "beer": 140.0,
    })


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



class ModuleConfigFactory:
    """
    Module configuration plant.

    Scope of use:
    - `enterprise/modules/*_manager.py` Back here when invisible injection configuration
    - Follow-up to replace or overwrite the configuration with modules
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
        Get the configuration of the specified module
                
        Args:
            module_type: Module type (e.g. "finance", "protection")
                        
        Returns:
            Configure objects, return None if none does not exist
                """
        config = cls._configs.get(module_type)
        if config is None:
            raise ValueError(f"Unknown module type: {module_type}")
        return config
    
    @classmethod
    def register_config(cls, module_type: str, config):
        """
        Register new module configuration
                
        Args:
            parameter: Module type
            config: Configure Object
                """
        cls._configs[module_type] = config
