import json
import re
from typing import Dict, List, Any, Set
# ============================================================================
# Status observation class for CEOs
# ============================================================================
class StateObservation:
    """Full state observations based on modules < x17/ >()"""

    def __init__(
        self,
        enterprise_id: str,
        finance: Dict[str, Any],
        production: Dict[str, Any],
        procurement: Dict[str, Any],
        inventory: Dict[str, Any],
        sales: Dict[str, Any],
        hr: Dict[str, Any],
    ):
        """
        Args:
            enterprise_id: enterpriseID
            Finance: Financial Status
            Production:
            Procurement status
            Inventory: Stock
            Sales:
            hr: Human resources status
                """
        self.enterprise_id = enterprise_id
        self.finance = finance
        self.production = production
        self.procurement = procurement
        self.inventory = inventory
        self.sales = sales
        self.hr = hr

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Dictionary"""
        return {
            "enterprise_id": self.enterprise_id,
            "finance": self.finance,
            "production": self.production,
            "procurement": self.procurement,
            "inventory": self.inventory,
            "sales": self.sales,
            "hr": self.hr,
        }

    @classmethod
    def from_enterprise(cls, enterprise) -> "StateObservation":
        """Create an observation from an Enterprise object (using the parameter method of each module)"""

        def get_module(module_type: str):
            """Get specified types of business modules"""
            if not hasattr(enterprise, 'business_modules'):
                return None
            modules = enterprise.business_modules.get(module_type, [])
            return modules[0] if modules else None

        def extract_state_data(state_result):
            """Extract data from parameter() results (processing ModuleResponse or dictionary)"""
            if state_result is None:
                return {}
            elif hasattr(state_result, 'data'):
                # ModeuleResponse Object
                return state_result.data if isinstance(state_result.data, dict) else {}
            elif isinstance(state_result, dict):
                # It's already a dictionary.
                return state_result
            else:
                return {}

        # Get the module status
        finance_module = get_module('FinanceManager')
        finance_state = extract_state_data(finance_module.get_state() if finance_module else None)

        production_module = get_module('ProductionManager')
        production_state = extract_state_data(production_module.get_state() if production_module else None)

        procurement_module = get_module('ProcurementManager')
        procurement_state = extract_state_data(procurement_module.get_state() if procurement_module else None)

        inventory_module = get_module('InventoryManager')
        inventory_state = extract_state_data(inventory_module.get_state() if inventory_module else None)

        sales_module = get_module('SalesManager')
        sales_state = extract_state_data(sales_module.get_state() if sales_module else None)

        hr_module = get_module('HRManager')
        hr_state = extract_state_data(hr_module.get_state() if hr_module else None)

        return cls(
            enterprise_id=enterprise.id,
            finance=finance_state,
            production=production_state,
            procurement=procurement_state,
            inventory=inventory_state,
            sales=sales_state,
            hr=hr_state,
        )

    def get_finance_state(self) -> Dict[str, Any]:
        """Get Finance department Status"""
        return self.finance

    def get_production_state(self) -> Dict[str, Any]:
        """Access to production department status"""
        return self.production

    def get_procurement_state(self) -> Dict[str, Any]:
        """Get procurement department status"""
        return self.procurement

    def get_inventory_state(self) -> Dict[str, Any]:
        """Access inventory department status"""
        return self.inventory

    def get_sales_state(self) -> Dict[str, Any]:
        """Get sales department status"""
        return self.sales

    def get_hr_state(self) -> Dict[str, Any]:
        """Get Human Resources department Status"""
        return self.hr

    def get_department_state(self, department_name: str) -> Dict[str, Any]:
        """Get status according to department name
                
        Args:
            department_name: department Name, optional: 'finance', 'protection', 'inventory', 'sales', 'hr'
                        
        Returns:
            Specifies the status dictionary department and returns empty words if the name department is invalid General
                """
        department_map = {
            'finance': self.finance,
            'production': self.production,
            'procurement': self.procurement,
            'inventory': self.inventory,
            'sales': self.sales,
            'hr': self.hr
        }
        return department_map.get(department_name.lower(), {})

    def get_all_departments_state(self) -> Dict[str, Dict[str, Any]]:
        """Get all department states
                
        Returns:
            Dictionary containing all department status
                """
        return {
            'finance': self.finance,
            'production': self.production,
            'procurement': self.procurement,
            'inventory': self.inventory,
            'sales': self.sales,
            'hr': self.hr
        }
