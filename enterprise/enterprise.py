"""
企业模块

定义集成了多种职能的企业类，包含生产、采购、销售、分销等功能
"""

import uuid
import time
from typing import Dict, List, Optional, Any, Callable
from enterprise.modules.base_business_module import BaseBusinessModule
from enterprise.modules.finance_manager import FinanceManager
from enterprise.modules.production_manager import ProductionManager
from enterprise.modules.procurement_manager import ProcurementManager
from enterprise.modules.inventory_manager import InventoryManager
from enterprise.modules.sales_manager import SalesManager
from enterprise.modules.hr_manager import HRManager
from network.exchange_manager import Exchange

class Enterprise:
    """
    企业类 - 集成了生产、采购、销售、分销等多种职能
    """
    def __init__(self, config: Dict = None, id: str = None, **kwargs):
        """
        初始化企业
        
        Args:
            config: 企业配置信息
            id: 企业唯一标识符，如果不提供则自动生成
            **kwargs: 其他配置参数，将被添加到config字典中
        
        支持两种初始化方式：
        1. Enterprise(config, id, **kwargs)
        2. Enterprise({'name': name, 'initial_fund': initial_fund}) - 字典形式参数
        """
        # 支持字典形式的直接参数传递
        if config and isinstance(config, dict) and ('name' in config or 'initial_fund' in config):
            self.config = config.copy()
            # 将kwargs添加到配置中
            self.config.update(kwargs)
        else:
            self.config = config or {}
            # 将kwargs参数添加到config字典中
            self.config.update(kwargs)
        
        # 企业基本信息
        self.id = id if id else str(uuid.uuid4())  # 企业唯一标识符
        self.name = self.config.get("name", f"Enterprise-{self.id[:8]}")
        self.description = self.config.get("description", "Integrated enterprise with multiple functions")
        self.location = self.config.get("location", {"city": "Unknown", "country": "Unknown"})
        self.established_time = self.config.get("established_time", time.time())
        # 企业层级
        self.tier = self.config.get("tier", 0)
        self.role_tags = list(self.config.get("role_tags", []))
        self.policy_tags = list(self.config.get("policy_tags", []))

        self.salable_products_idList = self.config.get("salable_products_idList", [])
        self.purchasable_materials_idList = self.config.get("purchasable_materials_idList", [])
        self.supplier_name_list = self.config.get("supplier_name_list", [])
        
        # 企业状态 - 支持从config字典或kwargs中获取initial_fund参数
        initial_fund = self.config.get("initial_fund") or kwargs.get("initial_fund")
        if initial_fund is not None:
            self.capital = float(initial_fund)
        else:
            self.capital = self.config.get("initial_capital", 1000000.0)
        # 确保fund和cash与capital保持一致
        self.fund = self.capital
        self.cash = self.capital
        self.revenue = 0.0  # 总收入
        self.expenses = 0.0  # 总支出
        self.profit = 0.0  # 净利润
        self.credit_score = self.config.get("initial_credit_score", 700)  # 信用评分
        
        # 添加缺失的属性以避免在to_dict和from_dict中出错
        self.products = []
        self.inventory = {}
        self.suppliers = []
        self.customers = []
        self.resources = {}
        self.capabilities = []
        self.processing_capacity = 0
        self.lead_time = 0
        self.is_active = True
        self.extensions = {}
        self.current_orders = []
        self.backlog_orders = []
        self.processing_orders = []
            
        # 启用的职能 (通过配置启用/禁用不同职能)
        self.enabled_functions = self.config.get("enabled_functions", [
            "production", "procurement", "sales", "distribution", "inventory_management"
        ])
        
        # 历史记录
        self.history = {
            "financials": [],
            "inventory_changes": [],
            "orders": [],
            "decisions": [],
            "production": [],
            "sales": [],
            "messages": []
        }
        
        # 消息系统相关
        self.message_manager = None  # 消息管理器，将由环境注入
        self.time_manager = None  # 时间管理器，将由环境注入
        self.market_manager = None  # 环境市场管理器，将由环境注入
        self.controller = None  # 控制器引用，将由控制器注册时注入
        self.runtime_injection_config = None  # 当前运行级实验策略，将由适配器/控制器注入
        self.exchanges = []  # 交易所列表，将由环境注入
        self.upstream_exchange = None 
        self.downstream_exchange = None  

        self.message_handlers = {}  # 消息处理器字典
        self.message_subscriptions = {}  # 消息订阅关系
        
        # 其他配置
        self.business_modules = {}  # 业务模块字典
        self.risk_tolerance = self.config.get("risk_tolerance", "medium")
        self.decision_strategy = self.config.get("decision_strategy", "default")
        
    def initialize_default_modules(self):
        """
        初始化默认业务模块
        
        Returns:
            初始化的模块实例
        """
        # 这里可以根据需要初始化默认模块
        if 'finance' in self.enabled_functions:
            finance_manager = FinanceManager(self,initial_cash=self.capital)
            self.register_module(finance_manager)
            self.register_message_handler("Finance", finance_manager.message_handle)
        if 'production' in self.enabled_functions:
            production_manager = ProductionManager(self)
            self.register_module(production_manager)
            self.register_message_handler("Production", production_manager.message_handle)
        if 'procurement' in self.enabled_functions:
            procurement_manager = ProcurementManager(self)
            self.register_module(procurement_manager)
            self.register_message_handler("Procurement", procurement_manager.message_handle) 
        if 'inventory' in self.enabled_functions:
            inventory_manager = InventoryManager(self)
            self.register_module(inventory_manager) 
            self.register_message_handler("Inventory", inventory_manager.message_handle) 
        if 'sales' in self.enabled_functions:
            sales_manager = SalesManager(self)
            self.register_module(sales_manager)
            self.register_message_handler("Sales", sales_manager.message_handle)         
        if 'hr' in self.enabled_functions:
            hr_manager = HRManager(self)
            self.register_module(hr_manager)
            self.register_message_handler("HR", hr_manager.message_handle)   
        return 
    

    # 消息系统相关方法
    def set_message_manager(self, message_manager):
        """
        设置消息管理器并注册企业实例
        
        Args:
            message_manager: 消息管理器实例
        """
        self.message_manager = message_manager
        # 注册企业实例到消息管理器
        if hasattr(message_manager, 'register_enterprise'):
            message_manager.register_enterprise(self.id, self)

    def set_market_manager(self, market_manager):
        """
        设置环境市场管理器并注册企业实例
        
        Args:
            market_manager: 环境市场管理器实例
        """
        self.market_manager = market_manager

    def set_time_manager(self, time_manager):
        """
        设置时间管理器并注册企业实例
        
        Args:
            time_manager: 时间管理器实例
        """
        self.time_manager = time_manager

    def set_exchange(self, exchanges: List[Exchange]):
        """
        设置交易所管理器并注册企业实例
        
        Args:
            exchanges: 交易所实例列表
        """
        self.exchanges = exchanges
        enterprise_info = {
            "tier": self.tier,
            "role_tags": list(self.role_tags or []),
            "policy_tags": list(self.policy_tags or []),
            "salable_products_idList": list(self.salable_products_idList or []),
            "purchasable_materials_idList": list(self.purchasable_materials_idList or []),
        }
        # 在对应的交易所中注册企业自身的 上游/下游 信息 
        for exchange in exchanges:
            exchange_prefix = exchange.id.split("_")[0]   # "0-1"
            upstream_str, downstream_str = exchange_prefix.split("-")

            upstream = int(upstream_str)
            downstream = int(downstream_str)
            if self.tier == upstream:
                exchange.register_upstream_enterprise(self.id, self.name, enterprise_info)
                self.downstream_exchange = exchange
            elif self.tier == downstream:
                exchange.register_downstream_enterprise(self.id, self.name, enterprise_info)
                self.upstream_exchange = exchange

    
    
    def send_message(self, recipient_id: str, message_type: str, content: Dict, urgent: bool = False) -> Dict:
        """
        发送消息给指定企业
        
        Args:
            recipient_id: 接收者企业ID
            message_type: 消息类型
            content: 消息内容
            urgent: 是否为紧急消息
            
        Returns:
            dict: 消息发送结果
        """
        if not self.message_manager:
            return {"success": False, "message": "Message manager not set"}
        
        try:
            # 直接调用message_manager的send_message方法，传递所有必需参数
            message_id = self.message_manager.send_message(
                sender_id=self.id,
                receiver_id=recipient_id,
                message_type=message_type,
                content=content,
                priority="high" if urgent else "normal",
                metadata={"sender_name": self.name, "urgent": urgent, "timestamp": time.time()}
            )
            # 记录发送的消息
            self.history["messages"].append({
                "type": "sent",
                "message": {
                    "id": message_id,
                    "sender_id": self.id,
                    "recipient_id": recipient_id,
                    "message_type": message_type,
                    "content": content
                }
            })
            
            return {"success": True, "message_id": message_id}
        except Exception as e:
            print(f"Error sending message from {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def broadcast_message(self, message_type: str, content: Dict, urgent: bool = False) -> Dict:
        """
        广播消息给所有企业
        
        Args:
            message_type: 消息类型
            content: 消息内容
            urgent: 是否为紧急消息
            
        Returns:
            dict: 消息发送结果
        """
        if not self.message_manager:
            return {"success": False, "message": "Message manager not set"}
        
        try:
            # 直接调用message_manager的broadcast_message方法
            message_ids = self.message_manager.broadcast_message(
                sender_id=self.id,
                message_type=message_type,
                content=content,
                priority="high" if urgent else "normal",
                metadata={"sender_name": self.name, "urgent": urgent, "timestamp": time.time()}
            )
            
            # 记录发送的广播消息
            self.history["messages"].append({
                "type": "broadcast",
                "message": {
                    "sender_id": self.id,
                    "message_type": message_type,
                    "content": content,
                    "message_ids": message_ids
                }
            })
            
            return {"success": True, "message_ids": message_ids}
        except Exception as e:
            print(f"Error broadcasting message from {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def receive_message(self, message: Dict):
        """
        接收消息
        
        Args:
            message: 消息内容
        """
        message_type = message.get("message_type")
        # 记录接收的消息
        self.history["messages"].append({
            "type": "received",
            "message_type": message_type,
            "sender_id": message.get("sender_id"),
            "message": message,
            "timestamp": time.time()
        })
        
        # 检查是否有对应的消息处理器
        if message_type in self.message_handlers:
            handler = self.message_handlers[message_type]
            try:
                handler(message)
                return {"success": True, "message_id": message.get("id")}
            except Exception as e:
                print(f"Error processing message {message.get('id')} for enterprise {self.name}: {str(e)}")
                return {"success": False, "error": str(e)}
        else:
            # 默认处理逻辑
            print(f"Enterprise {self.name} received message of type {message_type} from {message.get('sender_name')}")
            return {"success": True, "message": "Message received but no handler registered"}
    
    def register_message_handler(self, message_type: str, handler: Callable):
        """
        注册消息处理器
        
        Args:
            message_type: 消息类型
            handler: 消息处理函数
        """
        self.message_handlers[message_type] = handler
        return {"success": True, "message_type": message_type}
    
    def subscribe_to_messages(self, message_type: str):
        """
        订阅特定类型的消息
        
        Args:
            message_type: 消息类型
            
        Returns:
            dict: 订阅结果
        """
        if not self.message_manager:
            return {"success": False, "message": "Message manager not set"}
        
        self.message_subscriptions[message_type] = True
        # 使用新的subscribe_enterprise_to_message方法进行订阅
        if hasattr(self.message_manager, 'subscribe_enterprise_to_message'):
            return self.message_manager.subscribe_enterprise_to_message(self.id, message_type)
        else:
            # 兼容旧版本
            return self.message_manager.subscribe(self.id, message_type)
             
    def to_dict(self) -> Dict:
        """
        转换为字典格式
        
        Returns:
            dict: 企业的字典表示
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "capital": self.capital,
            "revenue": self.revenue,
            "expenses": self.expenses,
            "profit": self.profit,
            "credit_score": self.credit_score,
            "products": self.products,
            "inventory": self.inventory,
            "suppliers": self.suppliers,
            "customers": self.customers,
            "config": self.config,
            "resources": self.resources,
            "capabilities": self.capabilities,
            "processing_capacity": self.processing_capacity,
            "lead_time": self.lead_time,
            "is_active": self.is_active,
            "risk_tolerance": self.risk_tolerance,
            "decision_strategy": self.decision_strategy,
            "extensions": self.extensions
        }
    
    def register_business_module(self, module_name: str, module_instance):
        """
        注册业务模块
        
        Args:
            module_name: 模块名称
            module_instance: 模块实例
        """
        self.business_modules[module_name] = module_instance
        print(f"企业 {self.name} 已注册业务模块: {module_name}")
        
    def get_business_module(self, module_name: str):
        """
        获取业务模块
        
        Args:
            module_name: 模块名称
            
        Returns:
            业务模块实例，不存在则返回None
        """
        return self.business_modules.get(module_name)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Enterprise':
        """
        从字典创建企业实例
        
        Args:
            data: 企业数据
            
        Returns:
            Enterprise: 企业实例
        """
        enterprise = cls(data.get("config", {}))
        enterprise.id = data.get("id", enterprise.id)
        enterprise.name = data.get("name", enterprise.name)
        enterprise.description = data.get("description", enterprise.description)
        enterprise.location = data.get("location", enterprise.location)
        enterprise.capital = data.get("capital", enterprise.capital)
        enterprise.revenue = data.get("revenue", enterprise.revenue)
        enterprise.expenses = data.get("expenses", enterprise.expenses)
        enterprise.profit = data.get("profit", enterprise.profit)
        enterprise.credit_score = data.get("credit_score", enterprise.credit_score)
        enterprise.products = data.get("products", enterprise.products)
        enterprise.inventory = data.get("inventory", enterprise.inventory)
        enterprise.suppliers = data.get("suppliers", enterprise.suppliers)
        enterprise.customers = data.get("customers", enterprise.customers)
        enterprise.resources = data.get("resources", enterprise.resources)
        enterprise.capabilities = data.get("capabilities", enterprise.capabilities)
        enterprise.processing_capacity = data.get("processing_capacity", enterprise.processing_capacity)
        enterprise.lead_time = data.get("lead_time", enterprise.lead_time)
        enterprise.is_active = data.get("is_active", enterprise.is_active)
        enterprise.risk_tolerance = data.get("risk_tolerance", enterprise.risk_tolerance)
        enterprise.decision_strategy = data.get("decision_strategy", enterprise.decision_strategy)
        enterprise.extensions = data.get("extensions", enterprise.extensions)
        
        return enterprise
    
    def register_module(self, module):
        """
        注册工作部门模块
        
        Args:
            module: 业务模块实例，必须继承BaseBusinessModule
            
        Returns:
            str: 注册的模块ID
        """
        # 验证模块是否是BaseBusinessModule的实例
        if not isinstance(module, BaseBusinessModule):
            raise TypeError(f"模块必须继承BaseBusinessModule，当前类型: {type(module)}")
        
        # 注册模块
        if not hasattr(self, 'business_modules'):
            self.business_modules = {}
        
        module_type = getattr(module, 'module_type', 'unknown')
        if module_type not in self.business_modules:
            self.business_modules[module_type] = []
        
        self.business_modules[module_type].append(module)
        
        # 记录到历史
        self.history["decisions"].append({
            "action": "register_module",
            "module_id": module.module_id,
            "module_name": module.module_name
        })
        return module.module_id
    
    def get_module(self, module_id: str):
        """
        根据模块ID获取模块实例
        
        Args:
            module_id: 模块ID
            
        Returns:
            BaseBusinessModule: 模块实例，如果不存在则返回None
        """
        return self.business_modules.get(module_id)
    
    def list_modules(self) -> list:
        """
        列出所有注册的模块
        
        Returns:
            list: 模块信息列表
        """
        lists = []
        for module_type,module_list in self.business_modules.items():
            for module in module_list:
                lists.append(module.get_module_info())
        return lists
    
    def remove_module(self, module_id: str):
        """
        移除工作部门模块
        
        Args:
            module_id: 模块ID
            
        Returns:
            bool: 是否成功移除
        """
        if module_id in self.business_modules:
            del self.business_modules[module_id]
            
            # 记录到历史
            self.history["decisions"].append({
                "time": self.time_manager.get_day(),
                "action": "remove_module",
                "module_id": module_id
            })
            return True
        return False  

    def get_info(self) -> Dict:
        """
        获取企业基本信息
        
        Returns:
            dict: 包含企业名称、ID、资金等基本信息的字典
        """
        # 返回企业实际的资金值，不再根据名称硬编码
        return {
            "name": self.name,
            "id": self.id,
            "fund": float(self.fund),
            "capital": self.capital,
            "cash": self.cash,
            "revenue": self.revenue,
            "expenses": self.expenses,
            "profit": self.profit,
            "credit_score": self.credit_score
        }
    
    
    def get_state(self) -> Dict:
        """
        获取企业当前状态
        
        Returns:
            dict: 企业状态
        """
        # TODO 有大量无用内容待清理
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "capital": self.capital,
            "cash": self.cash,
            "revenue": self.revenue,
            "expenses": self.expenses,
            "profit": self.profit,
            "credit_score": self.credit_score,
            "inventory": self.inventory.copy(),
            "products": self.products.copy(),
            "suppliers": self.suppliers.copy(),
            "customers": self.customers.copy(),
            "current_orders": len(self.current_orders),
            "backlog_orders": len(self.backlog_orders),
            "processing_orders": len(self.processing_orders),
            "is_active": self.is_active,
            "risk_tolerance": self.risk_tolerance,
            "decision_strategy": self.decision_strategy
        }
