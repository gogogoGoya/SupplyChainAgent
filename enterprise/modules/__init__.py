"""
业务模块

包含企业运营的核心业务功能模块，支持生产、采购、销售、仓储、人力资源和财务管理等企业运营全流程。
"""

# 从各个业务模块导入主要类
from .production_manager import ProductionManager
from .procurement_manager import ProcurementManager
from .sales_manager import SalesManager
from .inventory_manager import InventoryManager
from .finance_manager import FinanceManager
from .hr_manager import HRManager

# 导出列表
__all__ = [
    'ProductionManager',
    'ProcurementManager',
    'SalesManager',
    'InventoryManager',
    'FinanceManager',
    'HRManager'
]

# 版本信息
__version__ = "2.0.0"
