"""
Business modules

A core business functionality module comprising enterprise operations to support enterprise production, procurement, sales, warehousing, human resources and financial management operations.
"""

# Import major from business modules Category
from .production_manager import ProductionManager
from .procurement_manager import ProcurementManager
from .sales_manager import SalesManager
from .inventory_manager import InventoryManager
from .finance_manager import FinanceManager
from .hr_manager import HRManager

# Export List
__all__ = [
    'ProductionManager',
    'ProcurementManager',
    'SalesManager',
    'InventoryManager',
    'FinanceManager',
    'HRManager'
]

# Version Information
__version__ = "2.0.0"
