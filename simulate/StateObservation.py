import json
import re
from typing import Dict, List, Any, Set
# ============================================================================
# 面向CEO的状态观察类
# ============================================================================
class StateObservation:
    """基于各模块 get_state() 的完整状态观察"""

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
            enterprise_id: 企业ID
            finance: 财务状态
            production: 生产状态
            procurement: 采购状态
            inventory: 库存状态
            sales: 销售状态
            hr: 人力资源状态
        """
        self.enterprise_id = enterprise_id
        self.finance = finance
        self.production = production
        self.procurement = procurement
        self.inventory = inventory
        self.sales = sales
        self.hr = hr

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
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
        """从 Enterprise 对象创建观察（使用各模块的 get_state 方法）"""

        def get_module(module_type: str):
            """获取指定类型的业务模块"""
            if not hasattr(enterprise, 'business_modules'):
                return None
            modules = enterprise.business_modules.get(module_type, [])
            return modules[0] if modules else None

        def extract_state_data(state_result):
            """从 get_state() 结果中提取数据（处理 ModuleResponse 或字典）"""
            if state_result is None:
                return {}
            elif hasattr(state_result, 'data'):
                # ModuleResponse 对象
                return state_result.data if isinstance(state_result.data, dict) else {}
            elif isinstance(state_result, dict):
                # 已经是字典
                return state_result
            else:
                return {}

        # 获取各模块状态
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
        """获取财务部门状态"""
        return self.finance

    def get_production_state(self) -> Dict[str, Any]:
        """获取生产部门状态"""
        return self.production

    def get_procurement_state(self) -> Dict[str, Any]:
        """获取采购部门状态"""
        return self.procurement

    def get_inventory_state(self) -> Dict[str, Any]:
        """获取库存部门状态"""
        return self.inventory

    def get_sales_state(self) -> Dict[str, Any]:
        """获取销售部门状态"""
        return self.sales

    def get_hr_state(self) -> Dict[str, Any]:
        """获取人力资源部门状态"""
        return self.hr

    def get_department_state(self, department_name: str) -> Dict[str, Any]:
        """根据部门名称获取状态
        
        Args:
            department_name: 部门名称，可选值：'finance', 'production', 'procurement', 'inventory', 'sales', 'hr'
            
        Returns:
            指定部门的状态字典，如果部门名称无效则返回空字典
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
        """获取所有部门状态
        
        Returns:
            包含所有部门状态的字典
        """
        return {
            'finance': self.finance,
            'production': self.production,
            'procurement': self.procurement,
            'inventory': self.inventory,
            'sales': self.sales,
            'hr': self.hr
        }
