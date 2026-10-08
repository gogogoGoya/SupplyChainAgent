"""
enterprise Module

Defined as a enterprise class of multiple functions, including production, procurement, sales, distribution, etc.
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
    enterprise - Combining production, procurement, sales, distribution, etc.
        """
    def __init__(self, config: Dict = None, id: str = None, **kwargs):
        """
        Initialise enterprise
                
        Args:
            config: enterprise Configuration information
            id: enterprise Unique identifier, if not provided, automatically generated
            **kwargs: Other configuration parameters will be added to the config dictionary Medium
                
        Two approaches to initialization are supported:
        1. Enterprise(config, id, **kwargs)
        Enterprise({'name': name, 'initial_fund': initial_fund}) - Dictionary form parameters
                """
        # Supports direct parameter transfer in dictionary form
        if config and isinstance(config, dict) and ('name' in config or 'initial_fund' in config):
            self.config = config.copy()
            # Add kwargs to configuration
            self.config.update(kwargs)
        else:
            self.config = config or {}
            # Add kwargs parameter to config dictionary Medium
            self.config.update(kwargs)
        
        # enterpriseBasic information
        self.id = id if id else str(uuid.uuid4())  # enterprise Unique identifier
        self.name = self.config.get("name", f"Enterprise-{self.id[:8]}")
        self.description = self.config.get("description", "Integrated enterprise with multiple functions")
        self.location = self.config.get("location", {"city": "Unknown", "country": "Unknown"})
        self.established_time = self.config.get("established_time", time.time())
        # enterprise Level
        self.tier = self.config.get("tier", 0)
        self.role_tags = list(self.config.get("role_tags", []))
        self.policy_tags = list(self.config.get("policy_tags", []))

        self.salable_products_idList = self.config.get("salable_products_idList", [])
        self.purchasable_materials_idList = self.config.get("purchasable_materials_idList", [])
        self.supplier_name_list = self.config.get("supplier_name_list", [])
        
        # enterprise Status - Supports obtaining initial fund parameters from config dictionary or kwargs
        initial_fund = self.config.get("initial_fund") or kwargs.get("initial_fund")
        if initial_fund is not None:
            self.capital = float(initial_fund)
        else:
            self.capital = self.config.get("initial_capital", 1000000.0)
        # Ensuring consistency between fund and cash and capital
        self.fund = self.capital
        self.cash = self.capital
        self.revenue = 0.0  # Total income
        self.expenses = 0.0  # Total expenditure
        self.profit = 0.0  # Net profit
        self.credit_score = self.config.get("initial_credit_score", 700)  # Credit rating
        
        # Add missing properties to avoid displaying in to dict and from dict Wrong.
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
            
        # Enabled functions (enabling/disable by configuration)
        self.enabled_functions = self.config.get("enabled_functions", [
            "production", "procurement", "sales", "distribution", "inventory_management"
        ])
        
        # History
        self.history = {
            "financials": [],
            "inventory_changes": [],
            "orders": [],
            "decisions": [],
            "production": [],
            "sales": [],
            "messages": []
        }
        
        # Message System Related
        self.message_manager = None  # Message Manager, to be injected into the environment
        self.time_manager = None  # Time manager, to be injected into the environment
        self.market_manager = None  # Environmental market manager, to be injected by environment
        self.controller = None  # controller reference to be injected when the controller is registered
        self.runtime_injection_config = None  # Current operational level experimental policy to be injected by adaptor/controller
        self.exchanges = []  # exchange List, to be injected by environment
        self.upstream_exchange = None 
        self.downstream_exchange = None  

        self.message_handlers = {}  # Message Processor Dictionary
        self.message_subscriptions = {}  # Can not open message
        
        # Other Configurations
        self.business_modules = {}  # Business module dictionary
        self.risk_tolerance = self.config.get("risk_tolerance", "medium")
        self.decision_strategy = self.config.get("decision_strategy", "default")
        
    def initialize_default_modules(self):
        """
        Initialization of the default business module
                
        Returns:
            Examples of initialized modules
                """
        # The default module can be initialized as needed
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
    

    # Message system-related methods
    def set_message_manager(self, message_manager):
        """
        Set message manager and register enterprise Examples
                
        Args:
            parameter: Message Manager Example
                """
        self.message_manager = message_manager
        # Register enterprise instance to message manager
        if hasattr(message_manager, 'register_enterprise'):
            message_manager.register_enterprise(self.id, self)

    def set_market_manager(self, market_manager):
        """
        Set up an environmental market manager and register enterprise Examples
                
        Args:
            market_manager: Examples of environmental market managers
                """
        self.market_manager = market_manager

    def set_time_manager(self, time_manager):
        """
        Set time manager and register enterprise Examples
                
        Args:
            parameter: Time Manager Example
                """
        self.time_manager = time_manager

    def set_exchange(self, exchanges: List[Exchange]):
        """
        Set up exchange Manager and register enterprise Examples
                
        Args:
            Exchanges: exchange Examples List
                """
        self.exchanges = exchanges
        enterprise_info = {
            "tier": self.tier,
            "role_tags": list(self.role_tags or []),
            "policy_tags": list(self.policy_tags or []),
            "salable_products_idList": list(self.salable_products_idList or []),
            "purchasable_materials_idList": list(self.purchasable_materials_idList or []),
        }
        # Register your own upstream/downstream information at exchange
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
        Send message to specified enterprise
                
        Args:
            recipient_id: Recipient enterpriseID
            parameter: Message Type
            Contact: Message Contents
            Other Organiser
                        
        Returns:
            dict: Message sent result
                """
        if not self.message_manager:
            return {"success": False, "message": "Message manager not set"}
        
        try:
            # Directly calls the message manager send message method and transmits all necessary parameters
            message_id = self.message_manager.send_message(
                sender_id=self.id,
                receiver_id=recipient_id,
                message_type=message_type,
                content=content,
                priority="high" if urgent else "normal",
                metadata={"sender_name": self.name, "urgent": urgent, "timestamp": time.time()}
            )
            # Record messages sent
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
        Radio message to all enterprise
                
        Args:
            parameter: Message Type
            Contact: Message Contents
            Other Organiser
                        
        Returns:
            dict: Message sent result
                """
        if not self.message_manager:
            return {"success": False, "message": "Message manager not set"}
        
        try:
            # Directly call message manager's Broadcast message method
            message_ids = self.message_manager.broadcast_message(
                sender_id=self.id,
                message_type=message_type,
                content=content,
                priority="high" if urgent else "normal",
                metadata={"sender_name": self.name, "urgent": urgent, "timestamp": time.time()}
            )
            
            # Record the broadcast.
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
        Receive Message
                
        Args:
            message:
                """
        message_type = message.get("message_type")
        # Record the receipt.
        self.history["messages"].append({
            "type": "received",
            "message_type": message_type,
            "sender_id": message.get("sender_id"),
            "message": message,
            "timestamp": time.time()
        })
        
        # Check if there's a corresponding message processor.
        if message_type in self.message_handlers:
            handler = self.message_handlers[message_type]
            try:
                handler(message)
                return {"success": True, "message_id": message.get("id")}
            except Exception as e:
                print(f"Error processing message {message.get('id')} for enterprise {self.name}: {str(e)}")
                return {"success": False, "error": str(e)}
        else:
            # Default processing logic
            print(f"Enterprise {self.name} received message of type {message_type} from {message.get('sender_name')}")
            return {"success": True, "message": "Message received but no handler registered"}
    
    def register_message_handler(self, message_type: str, handler: Callable):
        """
        Register Message Processor
                
        Args:
            parameter: Message Type
            Handler: Message processing function
                """
        self.message_handlers[message_type] = handler
        return {"success": True, "message_type": message_type}
    
    def subscribe_to_messages(self, message_type: str):
        """
        Can not open message
                
        Args:
            parameter: Message Type
                        
        Returns:
            dict: Subscription Results
                """
        if not self.message_manager:
            return {"success": False, "message": "Message manager not set"}
        
        self.message_subscriptions[message_type] = True
        # Subscriptions using the new subscribe entry to message method
        if hasattr(self.message_manager, 'subscribe_enterprise_to_message'):
            return self.message_manager.subscribe_enterprise_to_message(self.id, message_type)
        else:
            # Compatible with old versions
            return self.message_manager.subscribe(self.id, message_type)
             
    def to_dict(self) -> Dict:
        """
        Convert to Dictionary Format
                
        Returns:
            Dict: enterprise Dict
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
        Registration business module
                
        Args:
            parameter: Module name
            parameter: Examples of modules
                """
        self.business_modules[module_name] = module_instance
        print(f"企业 {self.name} 已注册业务模块: {module_name}")
        
    def get_business_module(self, module_name: str):
        """
        Getting Operations Modules
                
        Args:
            parameter: Module name
                        
        Returns:
            Examples of business modules, if none does not exist
                """
        return self.business_modules.get(module_name)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Enterprise':
        """
        Create instance enterprise from dictionary
                
        Args:
            Data: enterprise Data
                        
        Returns:
            Enterprise: enterprise Examples
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
        Registration department module
                
        Args:
            Modeule: Examples of business modules that must inherit BaseBusinesModule
                        
        Returns:
            st: Registered module ID
                """
        # Check if the module is the case of BaseBusinesModule
        if not isinstance(module, BaseBusinessModule):
            raise TypeError(f"模块必须继承BaseBusinessModule，当前类型: {type(module)}")
        
        # Registration module
        if not hasattr(self, 'business_modules'):
            self.business_modules = {}
        
        module_type = getattr(module, 'module_type', 'unknown')
        if module_type not in self.business_modules:
            self.business_modules[module_type] = []
        
        self.business_modules[module_type].append(module)
        
        # Record to History
        self.history["decisions"].append({
            "action": "register_module",
            "module_id": module.module_id,
            "module_name": module.module_name
        })
        return module.module_id
    
    def get_module(self, module_id: str):
        """
        Fetch module examples from module ID
                
        Args:
            module_id: Modular ID
                        
        Returns:
            BaseBusinesModule: Examples of modules, return None if none
                """
        return self.business_modules.get(module_id)
    
    def list_modules(self) -> list:
        """
        List all registered modules
                
        Returns:
            list: list of module information
                """
        lists = []
        for module_type,module_list in self.business_modules.items():
            for module in module_list:
                lists.append(module.get_module_info())
        return lists
    
    def remove_module(self, module_id: str):
        """
        Remove Task department Module
                
        Args:
            module_id: Modular ID
                        
        Returns:
            Bool: Remove successfully
                """
        if module_id in self.business_modules:
            del self.business_modules[module_id]
            
            # Record to History
            self.history["decisions"].append({
                "time": self.time_manager.get_day(),
                "action": "remove_module",
                "module_id": module_id
            })
            return True
        return False  

    def get_info(self) -> Dict:
        """
        Access enterprisebasic information
                
        Returns:
            dict: Dictionary containing enterprise basic information such as names, ID, funds, etc.
                """
        # returns enterprise actual value of funds, no longer coded by name
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
        Fetch enterprise Current Status
                
        Returns:
            dict: enterprise Status
                """
        # TODO Substantial amount of useless content to clean
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
