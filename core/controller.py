"""
控制器模块

作为仿真系统的控制中枢，负责协调各组件工作、管理企业决策调度、
处理消息和事件、执行企业动作，以及控制整体模拟流程。
"""

import os
import sys
import json
import time
import uuid
import logging
import asyncio
from collections import defaultdict
from copy import deepcopy
from typing import Dict, List, Any, Optional
from datetime import datetime
# 添加项目根目录到Python路径，确保所有导入都能正常工作
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# 使用基于项目根目录的绝对导入
from core.action_executor import ActionExecutor
from enterprise.enterprise import Enterprise
from config.simulation_preset_config import (
    DEFAULT_BEER_GAME_CUSTOMER_DELIVERY_LEAD_TIME,
    DEFAULT_BEER_GAME_UNIT_PRICE,
    DEFAULT_COBWEB_CONFIG,
    DEFAULT_HERDING_CONFIG,
    DEFAULT_MARKET_DEMAND_MODE,
    DEFAULT_SERVICE_TOTAL_STEPS,
    DEFAULT_SHARED_RESOURCE_CONFIG,
    EXTERNAL_MARKET_ORDER_ENTERPRISE_ID,
    LEGACY_MARKET_DEMAND_MODE_BEER_GAME,
    MARKET_DEMAND_MODE_SCHEDULED_EXTERNAL,
    normalize_market_demand_mode,
    get_active_enterprise_configs,
)

# 导入组件类
from .environment.environment import Environment
from .async_time_manager import AsyncTimeManager
from .event_manager import EventManager
from .market_manager import MarketManager
from network.exchange_manager import ExchangeManager
from network.network_manager import NetworkManager
from message.message_manager import MessageManager
class Controller:
    """
    仿真系统控制器
    
    作为仿真系统的核心控制中枢，负责协调各组件工作，
    管理企业决策调度，处理消息和事件，执行企业动作，
    并控制整体模拟流程。
    """
    def __init__(self, config=None, enterprise_configs=None, relationship_configs=None):
        """
        初始化控制器
        
        初始化控制器核心组件和状态
        
        Args:
            config: 模拟配置字典
            enterprise_configs: 企业配置列表，从外部传入，优先级高于配置文件
            relationship_configs: 企业关系配置列表，从外部传入，优先级高于配置文件
        """
        # 保存配置
        self.config = config or {}
        self.runtime_injection_config = (
            self.config.get("runtime_injection_config")
            or self.config.get("runtime_injection")
            or {}
        )
        
        # 系统状态
        self.is_running = False
        self.enterprises = {}
        self.is_initialized = False
        self.total_steps = self.config.get("time_config", {}).get("total_steps", DEFAULT_SERVICE_TOTAL_STEPS)
        self.enterprise_configs = enterprise_configs or get_active_enterprise_configs()
        self.enterprise_role_ids = self._build_enterprise_role_ids(self.enterprise_configs)
        
        # 组件引用
        self.environment = None
        self.time_manager = None
        self.event_manager = None
        self.network_manager = None
        self.message_manager = None
        self.market_manager = None
        self.exchange_manager = None
        
        # 如果提供了配置，自动创建和初始化组件
        if config:
            self.create_components()

            print("开始创建企业")
            try:
                # 优先使用外部传入的配置，否则使用当前主链路的统一预设
                enterprise_configs = self.enterprise_configs
                # 创建企业实例，确保使用配置中的ID
                enterprises = {}
                for enterprise_config in enterprise_configs:
                    # 确保企业ID使用配置中的值
                    enterprise = Enterprise(config=enterprise_config)
                    # 直接设置ID，避免Enterprise类覆盖
                    enterprise.id = enterprise_config['id']
                    enterprises[enterprise.id] = enterprise
                    print(f"创建企业: {enterprise.name}, ID: {enterprise.id}, 层级: {enterprise.tier}")
                
                # 初始化业务模块
                for enterprise in enterprises.values():
                    enterprise.initialize_default_modules()
                # 注册企业到控制器
                for enterprise in enterprises.values():
                    self.register_enterprise(enterprise)
                print(f"企业创建完成，控制器中的企业数量: {len(self.enterprises)}")
            except Exception as e:
                print(f"创建企业时发生错误: {str(e)}")
                import traceback
                traceback.print_exc()
            
            self.initialize_network_structure()
            # 初始化环境
            if self.environment and hasattr(self.environment, 'reset'):
                self.environment.reset()
                # 初始化网络结构和环境中的企业
                self.initialize_environment()

    @staticmethod
    def _build_enterprise_role_ids(enterprise_configs: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
        """
        根据企业 tier 推导当前主链路中的上下游角色 ID。

        这样控制器内部不再依赖写死的 `Supplier / Manufacturer / Distributor / Retailer`
        字面量，而是跟随配置中的企业层级自动识别。
        """
        ordered_enterprises = sorted(
            enterprise_configs,
            key=lambda item: (item.get("tier", 0), item.get("id", "")),
        )
        role_ids = {
            "supplier": None,
            "manufacturer": None,
            "distributor": None,
            "retailer": None,
        }
        if not ordered_enterprises:
            return role_ids
        role_ids["supplier"] = ordered_enterprises[0]["id"]
        role_ids["retailer"] = ordered_enterprises[-1]["id"]
        if len(ordered_enterprises) > 1:
            role_ids["manufacturer"] = ordered_enterprises[1]["id"]
        if len(ordered_enterprises) > 2:
            role_ids["distributor"] = ordered_enterprises[2]["id"]
        return role_ids
    
    def set_environment(self, environment):
        """
        设置环境实例
        
        Args:
            environment: Environment实例
        """
        self.environment = environment
        # 双向关联
        if hasattr(environment, 'set_controller'):
            environment.set_controller(self)
      

    

    def set_message_manager(self, message_manager):
        """
        设置消息管理器实例
        
        Args:
            message_manager: MessageManager实例
        """
        self.message_manager = message_manager
    
    def create_components(self):
        """
        根据配置创建所有核心组件
        """
        # 创建时间管理器
        self.time_manager = AsyncTimeManager()
        
        # 创建动作执行器
        self.action_executor = ActionExecutor()

        # 创建事件管理器
        self.event_manager = EventManager()

        # 创建环境市场模块
        environment_config = self.config.get("environment_config", {})
        self.market_manager = MarketManager(
            self.get_enterprise_instance,
            total_steps=self.config.get("time_config", {}).get("total_steps"),
            demand_mode=environment_config.get("market_demand_mode", DEFAULT_MARKET_DEMAND_MODE),
            beer_game_demand_series=environment_config.get("beer_game_demand_series"),
            beer_game_customer_delivery_lead_time=environment_config.get(
                "beer_game_customer_delivery_lead_time",
                DEFAULT_BEER_GAME_CUSTOMER_DELIVERY_LEAD_TIME,
            ),
            beer_game_unit_price=environment_config.get(
                "beer_game_unit_price",
                DEFAULT_BEER_GAME_UNIT_PRICE,
            ),
            beer_game_product_id=environment_config.get("beer_game_product_id", "beer"),
            cobweb_config=environment_config.get(
                "cobweb_config",
                DEFAULT_COBWEB_CONFIG,
            ),
            shared_resource_config=environment_config.get(
                "shared_resource_config",
                DEFAULT_SHARED_RESOURCE_CONFIG,
            ),
            herding_config=environment_config.get(
                "herding_config",
                DEFAULT_HERDING_CONFIG,
            ),
        )
        
        # 创建网络管理器
        self.network_manager = NetworkManager()
        
        # 创建交易所管理器
        self.exchange_manager = ExchangeManager()
        self.exchange_manager.set_trading_mode(
            environment_config.get("market_demand_mode", DEFAULT_MARKET_DEMAND_MODE)
        )

        # 创建消息管理器
        self.message_manager = MessageManager()
        # 创建环境
        self.environment = Environment()
        self.environment.set_controller(self)
        
        print("控制器核心组件创建完成")
    
    def hanlde_network_action(self, step: int, action: dict):
        """
        处理网络模块的动作

        Args:
            step: 当前时间步
            action: 包含动作信息的字典
        """
        action_name = action.get("action_name")
        action_param = action.get("action_param", {})
        results = []
        if hasattr(self.network_manager, action_name):
            method = getattr(self.network_manager, action_name)
            try:
                result = method(**action_param)
                results.append({
                    "action": action_name,
                    "status": "success",
                    "result": result
                })

            except Exception as e:
                results.append({
                    "action": action_name,
                    "status": "error",
                    "error": str(e)
                })

    def _generate_initial_events(self):
        """
        生成初始事件
        """
        print("控制器生成初始事件...")
        
        if self.event_manager:
            # 为零售商生成初始销售订单
            if "retailer_1" in self.enterprises:
                retailer = self.enterprises["retailer_1"]
                # 创建一个初始销售订单事件
                self.event_manager.add_event({
                    "type": "new_sales_order",
                    "target": retailer.id,
                    "data": {
                        "order_id": "initial_order_1",
                        "customer_id": "customer_initial",
                        "products": {"finished_good_1": 5},
                        "priority": "normal"
                    },
                    "timestamp": 0
                })
    
    def on_decision_completed(self, enterprise_id, decisions):
        """
        企业决策完成时的处理
        
        Args:
            enterprise_id: 企业ID
            decisions: 企业决策结果
        """
        print(f"企业 {enterprise_id} 决策完成: {decisions}")
        
        # 可以在这里添加决策完成后的处理逻辑
    
    def get_enterprise_instance(self, enterprise_id):
        """
        获取企业实例
        
        Args:
            enterprise_id: 企业ID
            
        Returns:
            Enterprise实例或None
        """
        if enterprise_id not in self.enterprises:
            return None
        return self.enterprises[enterprise_id]

    def register_enterprise(self, enterprise):
        """
        注册企业到控制系统
        
        Args:
            enterprise: 企业实例
            
        Returns:
            bool: 注册是否成功
        """
        try:
            # 添加到企业字典
            self.enterprises[enterprise.id] = enterprise
            enterprise.controller = self
            enterprise.runtime_injection_config = self.runtime_injection_config
            
            # 设置企业的消息管理器
            if self.message_manager and hasattr(enterprise, 'set_message_manager'):
                enterprise.set_message_manager(self.message_manager)
            
            if self.time_manager and hasattr(enterprise, 'set_time_manager'):
                enterprise.set_time_manager(self.time_manager)

            # 设置企业的环境市场管理器
            if self.market_manager and hasattr(enterprise, 'set_market_manager'):
                enterprise.set_market_manager(self.market_manager)
            
            # 为企业注册消息处理器
            self._setup_enterprise_message_handlers(enterprise)
            
            # 将企业添加到网络管理器
            if self.network_manager and hasattr(self.network_manager, 'add_enterprise'):
                self.network_manager.add_enterprise(enterprise.id, {
                    "name": enterprise.name,
                    "type": "integrated" if hasattr(enterprise, 'type') else "unknown"
                },enterprise)
            
            print(f"企业 {enterprise.name} ({enterprise.id}) 已成功注册到控制系统")
            return True
        except Exception as e:
            print(f"注册企业时出错: {str(e)}")
            return False

    def set_runtime_injection_config(self, runtime_injection_config: Optional[Dict[str, Any]] = None):
        """同步当前运行级策略到控制器与已注册企业。"""
        self.runtime_injection_config = runtime_injection_config or {}
        self.config["runtime_injection_config"] = self.runtime_injection_config
        for enterprise in getattr(self, "enterprises", {}).values():
            enterprise.runtime_injection_config = self.runtime_injection_config
    
    def _setup_enterprise_message_handlers(self, enterprise):
        """
        为企业设置消息处理器
        
        Args:
            enterprise: 企业实例
        """
        # 确保企业已经设置了消息管理器
        if not hasattr(enterprise, 'message_manager') or enterprise.message_manager is None:
            print(f"警告: 企业 {enterprise.name} 尚未设置消息管理器")
            return
        
        # 使用消息管理器注册处理器
        message_manager = enterprise.message_manager
        
        # 定义库存更新处理函数
        def handle_inventory_update(message):
            print(f"企业 {enterprise.name} 处理库存更新消息: {message.get('content', '')}")
            # 这里可以添加具体的库存更新逻辑
            
        # 定义价格变动处理函数
        def handle_price_change(message):
            print(f"企业 {enterprise.name} 处理价格变动消息: {message.get('content', '')}")
            # 这里可以添加具体的价格变动逻辑
            
        # 定义订单确认处理函数
        def handle_order_confirmed(message):
            print(f"企业 {enterprise.name} 处理订单确认消息: {message.get('content', '')}")
            # 这里可以添加具体的订单确认逻辑
            
        # 注册消息处理器到消息管理器 (使用subscribe方法)
        if hasattr(message_manager, 'subscribe'):
            message_manager.subscribe("inventory_update", handle_inventory_update)
            message_manager.subscribe("price_change", handle_price_change)
            message_manager.subscribe("order_confirmed", handle_order_confirmed)

    def restore_runtime_links_after_checkpoint(self):
        """Rebind runtime-only references removed from persisted checkpoints."""
        if self.environment is not None:
            self.environment.set_controller(self)
        if self.message_manager is not None:
            self.message_manager.subscribers = {}
            self.message_manager.enterprises = {}
        for enterprise in self.enterprises.values():
            enterprise.controller = self
            enterprise.runtime_injection_config = self.runtime_injection_config
            if self.message_manager is not None:
                enterprise.set_message_manager(self.message_manager)
                self.message_manager.enterprises[enterprise.id] = enterprise
            if self.time_manager is not None:
                enterprise.set_time_manager(self.time_manager)
            if self.market_manager is not None:
                enterprise.set_market_manager(self.market_manager)
            self._setup_enterprise_message_handlers(enterprise)
        if self.environment is not None:
            self.environment.enterprises = self.enterprises
    
    def _display_simulation_stats(self, step: int):
        """
        显示模拟统计信息
        
        Args:
            step: 当前时间步
        """
        if (step + 1) % 10 != 0:
            return
            
        print(f"\n--- 时间步 {step + 1} 统计信息 ---")
        print(f"企业总数: {len(self.enterprises)}")
        
        # 可以添加更多统计信息
        # 例如：订单数量、库存水平、销售额等
    
    def _save_simulation_results(self):
        """
        保存模拟结果
        
        Returns:
            dict: 模拟结果
        """
        try:
            # 收集结果数据
            results = {
                "total_steps": self.time_manager.get_day(),
                "enterprise_count": len(self.enterprises),
                "timestamp": time.time()
            }
            
            # 如果环境有状态历史，可以保存
            if hasattr(self.environment, 'state_history'):
                # 只保存最后几个状态以减少数据量
                results["last_states"] = self.environment.state_history[-10:] if len(self.environment.state_history) > 10 else self.environment.state_history
            
            print(f"模拟结果已收集: 总工作日 {self.time_manager.get_day()}, 企业数量 {len(self.enterprises)}")
            return results
        except Exception as e:
            print(f"保存模拟结果时出错: {str(e)}")
            return {"error": str(e)}
    
    def initialize_network_structure(self, structure: str = None, enterprises_config=None):
        """
        初始化网络结构
        
        Args:
            structure: 网络结构类型 (linear, star, mesh等)，如果不指定则使用配置中的值
            enterprises_config: 企业配置
        """
        print(f"开始初始化网络结构，当前企业数量: {len(self.enterprises)}")
        
        # 如果没有指定结构，从配置中获取
        if structure is None:
            structure = self.config.get("network_config", {}).get("structure", "linear")
        
        print(f"初始化网络结构: {structure}")
        
        # 确保network_manager已初始化
        if not self.network_manager:
            print("错误: 网络管理器未初始化")
            return
        
        # 检查企业是否存在
        if len(self.enterprises) == 0:
            print("警告: 未检测到企业")
            return
        
        # 构建默认的供应链层级
        supply_chain_layers = []
        
        if structure == "linear":
            supply_chain_layers = [
                ["supplier_1"],  # 第一层：供应商
                ["manufacturer_1"],  # 第二层：制造商
                ["retailer_1"]  # 第三层：零售商
            ]
        elif structure == "mesh":
            # 对于网状结构，使用所有已注册企业
            enterprise_ids = list(self.enterprises.keys())
            num_enterprises = len(enterprise_ids)
            
            if num_enterprises <= 2:
                # 如果企业数量很少，使用简单的两层结构
                mid_point = max(1, num_enterprises // 2)
                supply_chain_layers = [
                    enterprise_ids[:mid_point],  # 第一层：供应商
                    enterprise_ids[mid_point:]   # 第二层：客户
                ]
            else:
                # 将企业分成三层，确保每层至少有一个企业
                third_point = max(1, num_enterprises // 3)
                two_thirds_point = max(third_point + 1, 2 * num_enterprises // 3)
                supply_chain_layers = [
                    enterprise_ids[:third_point],      
                    enterprise_ids[third_point:two_thirds_point],  
                    enterprise_ids[two_thirds_point:]  
                ]
        elif structure == "custom":
            # 对于自定义结构, 根据企业注册时的tier分配层级
            for enterprise in self.enterprises.values():
                tier = enterprise.tier
                
                while len(supply_chain_layers) <= tier:
                    supply_chain_layers.append([])
                supply_chain_layers[tier].append(enterprise.id)
        if supply_chain_layers and self.network_manager and hasattr(self.network_manager, 'build_supply_chain'):
            self.network_manager.build_supply_chain(supply_chain_layers)
            print(f"供应链网络构建完成，层数: {len(supply_chain_layers)}")
        # 在此处利用network设置每一层的交易所exchange
        self.exchange_manager.initialize_exchange(supply_chain_layers)
        for enterprise in self.enterprises.values():
            exchanges = self.exchange_manager.get_exchanges_by_enterprise(enterprise.id)
            enterprise.set_exchange(exchanges)


    
    def initialize_environment(self):
        """
        初始化环境
        
        将所有企业注册到环境中
        """
        print(f"开始初始化环境，当前企业数量: {len(self.enterprises)}")
        
        if not self.environment:
            print("错误: 环境未初始化")
            return
        
        # 重置环境
        self.environment.reset()
        
        # 注册企业到环境
        registered_count = 0
        for enterprise_id, enterprise in self.enterprises.items():
            try:
                self.environment.add_enterprise(enterprise)
                self.environment.enterprises[enterprise_id] = enterprise
                registered_count += 1
            except Exception as e:
                print(f"注册企业 {enterprise_id} 到环境时出错: {str(e)}")
        # 确保环境的enterprises属性被正确设置
        if hasattr(self.environment, 'enterprises') and not isinstance(self.environment.enterprises, dict):
            self.environment.enterprises = self.enterprises
            print("已将企业字典直接设置到环境")
        print(f"环境初始化完成，已注册 {registered_count} 家企业")

    def stop(self):
        """
        停止控制器
        """
        self.is_running = False
        print("控制器已停止")

    # 模拟执行部分
    # 通用的单步执行
    async def _execute_time_step(self, actions=None, log_file=None, part="常规工作流"):
        """
        执行单个时间步的模拟 

        Args:
            step: 当前时间步
            actions: 当前步骤的动作列表
        """
        if not actions or not isinstance(actions, list):
            return {
                "day": self.time_manager.get_day(),
                "environment_result": [],
                "enterprise_results": []
            }

        # 更新环境时间
        if hasattr(self.environment, 'current_time'):
            self.environment.current_time = self.time_manager.get_day()

        # #  环境事件处理 - 负责处理整体模拟的事件
        # if self.environment:
        #     environment_result = self.environment.step(self.time_manager.get_day())

        # # 处理消息
        # if self.message_manager and hasattr(self.message_manager, 'process_messages'):
        #     self.message_manager.process_messages()

        # 执行流程
        actions_by_enterprise = {}
        actions_by_controller = {}
        for item in actions:
            eid = item.get('executor_id')
            if eid is not None:
                if eid == "controller":
                    actions_by_controller.setdefault(eid, []).append(item)
                else:
                    actions_by_enterprise.setdefault(eid, []).append(item)
        # 执行controller层级的动作
        for item in actions_by_controller.get("controller", []):
            action = item.get("action")
            dept = item.get("module_type")
            if dept == "network":
                self.hanlde_network_action(self.time_manager.get_day(), action)
        # 并发执行企业层级的动作
        grouped = defaultdict(lambda: defaultdict(list))
        for item in actions:
            eid = item.get("executor_id")
            dept = item.get("module_type")
            grouped[eid][dept].append(item)
         # 找到最大队列长度
        max_depth = max((len(dept_actions) 
                 for e in grouped.values() 
                 for dept_actions in e.values()), default=0)
        actions_by_timeline = []
        for i in range(max_depth):
            batch = defaultdict(dict)
            for eid, dept_dict in grouped.items():
                for dept, queue in dept_dict.items():
                    if i < len(queue):
                        batch[eid][dept] = queue[i]  # 取第 i 个行为
            if batch:
                actions_by_timeline.append(batch)
        flattened_results = []
        # department_time = defaultdict(int)
        # last_elapsed_time = 0 
        for action_in_timeline in actions_by_timeline:
            tasks = []
            task_info = []  # 用于存储任务相关信息，解决变量作用域问题
            for enterprise_name, dept_dict in action_in_timeline.items():
                for dept, action_info in dept_dict.items():
                    action = action_info.get("action")
                    enterprise = self.enterprises[enterprise_name]
                    # 创建一个带超时的包装函数
                    async def create_timeout_task(enterprise, action, dept, tick, timeout=30.0):
                        loop = asyncio.get_event_loop()
                        try:
                            # 使用 wait_for 为线程任务添加超时
                            result = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None,
                                    self.action_executor._call_department_functions,
                                    enterprise,
                                    action,
                                    dept,
                                    tick
                                ),
                                timeout=timeout
                            )
                            return result
                        except asyncio.TimeoutError:
                            return Exception(f"企业 {enterprise_name} 部门 {dept} 执行任务超时 ({timeout}秒)")
                    
                    action_name = action.get("action_name") if isinstance(action, dict) else None
                    task = create_timeout_task(enterprise, action, dept, self.time_manager.get_tick())
                    tasks.append(task)
                    task_info.append((enterprise_name, dept, action_name))  # 保存任务信息用于异常处理
            
            results_in_line = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 使用 task_info 来正确处理异常和日志
            normalized_results = []
            for i, result in enumerate(results_in_line):
                enterprise_name, dept, action_name = task_info[i]  # 从 task_info 获取正确的变量
                if isinstance(result, Exception):
                    print(f"企业 {enterprise_name} 部门 {dept} 执行任务时出错: {str(result)}")
                    normalized_results.append({
                        "action_type": action_name,
                        "executor_id": enterprise_name,
                        "module_type": dept,
                        "status": "error",
                        "errors": [{
                            "code": "ACTION_EXECUTION_EXCEPTION",
                            "message": str(result),
                        }],
                    })
                    continue
                if result is None:
                    normalized_results.append({
                        "action_type": action_name,
                        "executor_id": enterprise_name,
                        "module_type": dept,
                        "status": "error",
                        "errors": [{
                            "code": "ACTION_RETURNED_NONE",
                            "message": (
                                f"Action '{action_name}' in module '{dept}' returned None"
                            ),
                        }],
                    })
                    continue
                if not hasattr(result, "to_dict") and not isinstance(result, dict):
                    normalized_results.append({
                        "action_type": action_name,
                        "executor_id": enterprise_name,
                        "module_type": dept,
                        "status": "error",
                        "errors": [{
                            "code": "INVALID_ACTION_RESULT",
                            "message": (
                                f"Action '{action_name}' in module '{dept}' returned "
                                f"unsupported result type {type(result).__name__}"
                            ),
                        }],
                    })
                    continue
                normalized_results.append(result)
                # if result.consumed_time is not None:
                #     department_time[result.module_id] += result.consumed_time
                if log_file and hasattr(result, "to_dict"):
                    with open(log_file, "a", encoding="utf-8") as f:
                        print(f"企业 {enterprise_name} 部门 {dept} 执行任务: {result.action_type}\n{result.to_dict()}\n")
            
            flattened_results.extend(normalized_results)
            # total_elapsed = max(department_time.values(), default=0)
            # delta = total_elapsed - last_elapsed_time  
            # if delta > 0:
            #     await self.time_manager.run_timer(delta)
            # last_elapsed_time = total_elapsed
        if log_file and part == "常规工作流":
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"时间步 {self.time_manager.get_day()} 企业 {enterprise_name} 执行完成当前任务流\n")
        
        return {
            "day": self.time_manager.get_day(),
            "environment_result": [],
            "enterprise_results": flattened_results
        }

    # 将模拟的开始、结束、流程推进独立出来，交给agent调用
    async def start_simulation(self, total_steps: int = None, environment=None):
        """
        初始化并开始模拟，可以调用多次 advance_simulation 推进
        """

        print("===== 初始化模拟环境 =====")

        if environment:
            self.set_environment(environment)

        if total_steps is None:
            total_steps = self.config.get("time_config", {}).get("total_steps", 100)

        self.total_steps = total_steps      # 总步数上限
        if self.market_manager:
            self.market_manager.set_total_steps(total_steps)
        self.is_running = True

        if not hasattr(self, "enterprises"):
            self.enterprises = {}

        print(f"模拟初始化完成，总步数上限: {self.total_steps}")

    def configure_simulation(
        self,
        total_steps: int = None,
        market_demand_mode: str = None,
        beer_game_demand_series: list = None,
        beer_game_customer_delivery_lead_time: int = None,
        beer_game_unit_price: float = None,
        beer_game_product_id: str = None,
        cobweb_config: Dict[str, Any] = None,
        shared_resource_config: Dict[str, Any] = None,
        herding_config: Dict[str, Any] = None
    ):
        """
        更新运行级配置。用于让外部Agent管理器在正式推进前同步最终轮次与市场需求模式。
        """
        if total_steps is not None:
            self.total_steps = int(total_steps)
            self.config.setdefault("time_config", {})["total_steps"] = self.total_steps
            if self.market_manager:
                self.market_manager.set_total_steps(self.total_steps)

        if self.market_manager:
            self.market_manager.configure(
                demand_mode=market_demand_mode,
                beer_game_demand_series=beer_game_demand_series,
                beer_game_customer_delivery_lead_time=beer_game_customer_delivery_lead_time,
                beer_game_unit_price=beer_game_unit_price,
                beer_game_product_id=beer_game_product_id,
                cobweb_config=cobweb_config,
                shared_resource_config=shared_resource_config,
                herding_config=herding_config,
            )
        if market_demand_mode and self.exchange_manager:
            self.exchange_manager.set_trading_mode(
                normalize_market_demand_mode(market_demand_mode)
            )

        return {
            "total_steps": self.total_steps,
            "final_round": max(0, self.total_steps - 1),
            "market": self.market_manager.get_config() if self.market_manager else {}
        }

    def get_simulation_context(self):
        market_config = self.market_manager.get_config() if self.market_manager else {}
        trade_mode = self.exchange_manager.trading_mode if self.exchange_manager else None
        normalized_market_mode = normalize_market_demand_mode(
            market_config.get("demand_mode")
        )
        normalized_trade_mode = normalize_market_demand_mode(trade_mode)
        is_scheduled_external_demand_mode = (
            normalized_market_mode == MARKET_DEMAND_MODE_SCHEDULED_EXTERNAL
            and normalized_trade_mode == MARKET_DEMAND_MODE_SCHEDULED_EXTERNAL
        )
        return {
            "total_steps": self.total_steps,
            "final_round": max(0, self.total_steps - 1),
            "market_demand_mode": normalized_market_mode,
            "trade_mode": normalized_trade_mode,
            "is_scheduled_external_demand_mode": is_scheduled_external_demand_mode,
            "is_beer_game_mode": (
                is_scheduled_external_demand_mode
                or (
                    market_config.get("demand_mode") == LEGACY_MARKET_DEMAND_MODE_BEER_GAME
                    and trade_mode == LEGACY_MARKET_DEMAND_MODE_BEER_GAME
                )
            ),
            "is_cobweb_mode": market_config.get("demand_mode") == "cobweb",
            "is_shared_resource_mode": market_config.get("demand_mode") == "shared_resource_market",
            "is_herding_mode": market_config.get("demand_mode") == "herding_market",
            "beer_game_demand_series": market_config.get("beer_game_demand_series"),
            "beer_game_customer_delivery_lead_time": market_config.get("beer_game_customer_delivery_lead_time"),
            "beer_game_unit_price": market_config.get("beer_game_unit_price"),
            "beer_game_product_id": market_config.get("beer_game_product_id"),
            "cobweb_config": market_config.get("cobweb_config"),
            "cobweb_history": market_config.get("cobweb_history"),
            "shared_resource_config": market_config.get("shared_resource_config"),
            "shared_resource_state": market_config.get("shared_resource_state"),
            "shared_resource_history": market_config.get("shared_resource_history"),
            "herding_config": market_config.get("herding_config"),
            "herding_state": market_config.get("herding_state"),
            "herding_history": market_config.get("herding_history"),
            "external_environment": deepcopy(
                getattr(self, "external_environment_state", {"enabled": False})
            ),
        }

    def get_bullwhip_metrics(self):
        def variance(values):
            if len(values) < 2:
                return 0.0
            mean = sum(values) / len(values)
            return sum((value - mean) ** 2 for value in values) / len(values)

        def series_from_pairs(pairs):
            by_round = defaultdict(float)
            for round_id, quantity in pairs:
                by_round[int(round_id)] += quantity or 0
            return [
                {"round": round_id, "quantity": quantity}
                for round_id, quantity in sorted(by_round.items())
            ]

        def dense_series_from_pairs(pairs, final_round: Optional[int]):
            sparse_series = series_from_pairs(pairs)
            sparse_map = {item["round"]: item["quantity"] for item in sparse_series}
            if final_round is None:
                if not sparse_map:
                    return []
                final_round = max(sparse_map.keys())
            return [
                {"round": round_id, "quantity": sparse_map.get(round_id, 0.0)}
                for round_id in range(max(0, int(final_round)) + 1)
            ]

        def ratio(variance_map, numerator_key, denominator_key):
            denominator = variance_map.get(denominator_key, 0)
            if denominator <= 0:
                return None
            return variance_map.get(numerator_key, 0) / denominator

        def build_flow_label(from_label: str, to_label: str) -> str:
            return f"{from_label} -> {to_label}"

        def build_dynamic_ratio_entries(variance_map, ordered_keys):
            entries = []
            for idx in range(1, len(ordered_keys)):
                numerator_key = ordered_keys[idx]
                denominator_key = ordered_keys[idx - 1]
                entries.append(
                    {
                        "numerator_key": numerator_key,
                        "denominator_key": denominator_key,
                        "ratio": ratio(variance_map, numerator_key, denominator_key),
                    }
                )
            return entries

        def is_effective_request(req) -> bool:
            return getattr(req, "lifecycle_status", None) not in {"superseded", "expired"}

        retailer_id = self.enterprise_role_ids.get("retailer") or EXTERNAL_MARKET_ORDER_ENTERPRISE_ID
        distributor_id = self.enterprise_role_ids.get("distributor")
        manufacturer_id = self.enterprise_role_ids.get("manufacturer")
        final_round = max(0, int(self.total_steps) - 1) if self.total_steps is not None else None
        ordered_enterprises = sorted(
            self.enterprise_configs,
            key=lambda item: (item.get("tier", 0), item.get("id", "")),
        )
        enterprise_by_id = {item.get("id"): item for item in ordered_enterprises}
        bottom_enterprise = ordered_enterprises[-1] if ordered_enterprises else None
        customer_dynamic_key = (
            f"customer_to_tier_{bottom_enterprise.get('tier')}"
            if bottom_enterprise else "customer_to_retailer"
        )

        canonical_edge_keys = [
            "retailer_to_distributor",
            "distributor_to_manufacturer",
            "manufacturer_to_supplier",
        ]
        edge_defs = []
        for idx, (upstream, downstream) in enumerate(reversed(list(zip(ordered_enterprises, ordered_enterprises[1:])))):
            dynamic_key = f"tier_{downstream.get('tier')}_to_tier_{upstream.get('tier')}"
            downstream_id = downstream.get("id")
            downstream_enterprise = self.enterprises.get(downstream_id)
            normalize_by_recipe = False
            recipe_raw_materials = {}
            if downstream_enterprise:
                production_modules = downstream_enterprise.business_modules.get("ProductionManager", [])
                if production_modules:
                    product_recipes = getattr(production_modules[0], "product_recipes", {}) or {}
                    first_recipe = next(iter(product_recipes.values()), None)
                    if isinstance(first_recipe, dict):
                        recipe_raw_materials = first_recipe.get("raw_materials", {}) or {}
                        normalize_by_recipe = bool(recipe_raw_materials)

            edge_defs.append(
                {
                    "canonical_key": canonical_edge_keys[idx] if idx < len(canonical_edge_keys) else None,
                    "dynamic_key": dynamic_key,
                    "upstream_enterprise_id": upstream.get("id"),
                    "upstream_enterprise_name": upstream.get("name", upstream.get("id")),
                    "upstream_tier": upstream.get("tier"),
                    "downstream_enterprise_id": downstream_id,
                    "downstream_enterprise_name": downstream.get("name", downstream.get("id")),
                    "downstream_tier": downstream.get("tier"),
                    "label": build_flow_label(
                        downstream.get("name", downstream.get("id")),
                        upstream.get("name", upstream.get("id")),
                    ),
                    "normalize_by_recipe": normalize_by_recipe,
                    "recipe_raw_materials": recipe_raw_materials,
                }
            )

        external_history = (
            self.market_manager.get_external_demand_history(retailer_id)
            if self.market_manager
            else []
        )
        customer_raw_series = series_from_pairs(
            (item.get("round", 0), item.get("quantity", 0))
            for item in external_history
        )
        customer_effective_series = dense_series_from_pairs(
            [
                (item.get("round", 0), item.get("quantity", 0))
                for item in external_history
            ],
            final_round,
        )

        raw_dynamic_flow_pairs = {
            customer_dynamic_key: [
                (item.get("round", 0), item.get("quantity", 0))
                for item in external_history
            ],
        }
        effective_dynamic_flow_pairs = {
            customer_dynamic_key: [
                (item.get("round", 0), item.get("quantity", 0))
                for item in external_history
            ],
        }
        raw_normalized_request_maps = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        effective_normalized_request_maps = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        edge_by_buyer_id = {}
        for edge in edge_defs:
            raw_dynamic_flow_pairs[edge["dynamic_key"]] = []
            effective_dynamic_flow_pairs[edge["dynamic_key"]] = []
            edge_by_buyer_id[edge["downstream_enterprise_id"]] = edge

        if self.exchange_manager:
            for exchange in self.exchange_manager.get_all_exchanges().values():
                for req in exchange.buy_requests:
                    edge = edge_by_buyer_id.get(req.buyer_company_id)
                    if edge is None:
                        continue
                    if edge.get("normalize_by_recipe"):
                        dynamic_key = edge["dynamic_key"]
                        raw_normalized_request_maps[dynamic_key][int(req.created_round)][req.product_id] += req.quantity or 0
                        if is_effective_request(req):
                            effective_normalized_request_maps[dynamic_key][int(req.created_round)][req.product_id] += req.quantity or 0
                        continue

                    raw_dynamic_flow_pairs[edge["dynamic_key"]].append((req.created_round, req.quantity))
                    if is_effective_request(req):
                        effective_dynamic_flow_pairs[edge["dynamic_key"]].append((req.created_round, req.quantity))

        def normalized_series_from_request_map(request_map, recipe_raw_materials):
            normalized_pairs = []
            for round_id, material_quantities in request_map.items():
                equivalents = []
                for material_id, quantity in material_quantities.items():
                    recipe_quantity = recipe_raw_materials.get(material_id)
                    if recipe_quantity:
                        equivalents.append(quantity / recipe_quantity)
                    else:
                        equivalents.append(quantity)
                normalized_pairs.append((round_id, min(equivalents) if equivalents else 0))
            return normalized_pairs

        for edge in edge_defs:
            if not edge.get("normalize_by_recipe"):
                continue
            dynamic_key = edge["dynamic_key"]
            recipe_raw_materials = edge.get("recipe_raw_materials") or {}
            raw_dynamic_flow_pairs[dynamic_key] = normalized_series_from_request_map(
                raw_normalized_request_maps[dynamic_key],
                recipe_raw_materials,
            )
            effective_dynamic_flow_pairs[dynamic_key] = normalized_series_from_request_map(
                effective_normalized_request_maps[dynamic_key],
                recipe_raw_materials,
            )

        dynamic_flow_sequence = [
            {
                "order": 0,
                "canonical_key": "customer_to_retailer",
                "dynamic_key": customer_dynamic_key,
                "label": build_flow_label("Customer", bottom_enterprise.get("name", retailer_id) if bottom_enterprise else retailer_id),
                "upstream_enterprise_id": bottom_enterprise.get("id") if bottom_enterprise else retailer_id,
                "upstream_enterprise_name": bottom_enterprise.get("name", retailer_id) if bottom_enterprise else retailer_id,
                "upstream_tier": bottom_enterprise.get("tier") if bottom_enterprise else None,
                "downstream_enterprise_id": "external_market",
                "downstream_enterprise_name": "Customer",
                "downstream_tier": None,
                "normalize_by_recipe": False,
            }
        ]
        dynamic_flow_sequence.extend(
            {
                "order": index + 1,
                **edge,
            }
            for index, edge in enumerate(edge_defs)
        )
        ordered_dynamic_keys = [item["dynamic_key"] for item in dynamic_flow_sequence]

        raw_dynamic_flows = {
            customer_dynamic_key: customer_raw_series,
        }
        effective_dynamic_flows = {
            customer_dynamic_key: customer_effective_series,
        }
        for edge in edge_defs:
            dynamic_key = edge["dynamic_key"]
            raw_dynamic_flows[dynamic_key] = series_from_pairs(raw_dynamic_flow_pairs[dynamic_key])
            effective_dynamic_flows[dynamic_key] = dense_series_from_pairs(
                effective_dynamic_flow_pairs[dynamic_key],
                final_round,
            )

        raw_tier_flows = {
            "customer_to_retailer": raw_dynamic_flows.get(customer_dynamic_key, []),
        }
        effective_tier_flows = {
            "customer_to_retailer": effective_dynamic_flows.get(customer_dynamic_key, []),
        }
        for edge in edge_defs:
            canonical_key = edge.get("canonical_key")
            if canonical_key:
                raw_tier_flows[canonical_key] = raw_dynamic_flows.get(edge["dynamic_key"], [])
                effective_tier_flows[canonical_key] = effective_dynamic_flows.get(edge["dynamic_key"], [])

        raw_variance_by_tier = {
            key: variance([item.get("quantity", 0) for item in series])
            for key, series in raw_tier_flows.items()
        }
        effective_variance_by_tier = {
            key: variance([item.get("quantity", 0) for item in series])
            for key, series in effective_tier_flows.items()
        }
        raw_dynamic_variance_by_tier = {
            key: variance([item.get("quantity", 0) for item in series])
            for key, series in raw_dynamic_flows.items()
        }
        effective_dynamic_variance_by_tier = {
            key: variance([item.get("quantity", 0) for item in series])
            for key, series in effective_dynamic_flows.items()
        }

        return {
            "series": effective_tier_flows,
            "variance": effective_variance_by_tier,
            "bullwhip_ratio": {
                "retailer_vs_customer": ratio(effective_variance_by_tier, "retailer_to_distributor", "customer_to_retailer"),
                "distributor_vs_retailer": ratio(effective_variance_by_tier, "distributor_to_manufacturer", "retailer_to_distributor"),
                "manufacturer_vs_distributor": ratio(effective_variance_by_tier, "manufacturer_to_supplier", "distributor_to_manufacturer")
            },
            "raw_series": raw_tier_flows,
            "raw_variance": raw_variance_by_tier,
            "raw_bullwhip_ratio": {
                "retailer_vs_customer": ratio(raw_variance_by_tier, "retailer_to_distributor", "customer_to_retailer"),
                "distributor_vs_retailer": ratio(raw_variance_by_tier, "distributor_to_manufacturer", "retailer_to_distributor"),
                "manufacturer_vs_distributor": ratio(raw_variance_by_tier, "manufacturer_to_supplier", "distributor_to_manufacturer")
            },
            "effective_series": effective_tier_flows,
            "effective_variance": effective_variance_by_tier,
            "effective_bullwhip_ratio": {
                "retailer_vs_customer": ratio(effective_variance_by_tier, "retailer_to_distributor", "customer_to_retailer"),
                "distributor_vs_retailer": ratio(effective_variance_by_tier, "distributor_to_manufacturer", "retailer_to_distributor"),
                "manufacturer_vs_distributor": ratio(effective_variance_by_tier, "manufacturer_to_supplier", "distributor_to_manufacturer")
            },
            "flow_sequence": dynamic_flow_sequence,
            "dynamic_series": effective_dynamic_flows,
            "dynamic_variance": effective_dynamic_variance_by_tier,
            "dynamic_bullwhip_ratio": build_dynamic_ratio_entries(
                effective_dynamic_variance_by_tier,
                ordered_dynamic_keys,
            ),
            "dynamic_raw_series": raw_dynamic_flows,
            "dynamic_raw_variance": raw_dynamic_variance_by_tier,
            "dynamic_raw_bullwhip_ratio": build_dynamic_ratio_entries(
                raw_dynamic_variance_by_tier,
                ordered_dynamic_keys,
            ),
            "dynamic_effective_series": effective_dynamic_flows,
            "dynamic_effective_variance": effective_dynamic_variance_by_tier,
            "dynamic_effective_bullwhip_ratio": build_dynamic_ratio_entries(
                effective_dynamic_variance_by_tier,
                ordered_dynamic_keys,
            ),
            "recording_notes": {
                "effective_filters": {
                    "buy_request_lifecycle_excluded": ["superseded", "expired"],
                    "round_axis_dense_zero_fill": True,
                },
                "manufacturer_to_supplier_normalization": "min_complete_package_equivalent_by_round",
                "dynamic_flow_keys_enabled": True,
            },
        }

    async def advance_simulation(self, workflow=None, log_file=None, part = "常规工作流"):
        """
        推进一次 workflow,对应多个 step
        可以被反复调用以推进时间轴
        """

        if not self.is_running:
            print("模拟未运行，请先调用 start_simulation")
            return {
                "enterprise_results": [],
                "environment_result": None
            }
        
        # print("===== 推进模拟 =====")
        if log_file and part == "每日系统自动操作":
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*70}\n")
                f.write(f"工作日 {self.time_manager.get_day()} - {part}\n")
                f.write(f"{'='*70}\n")
                f.write(f"执行时间: {datetime.now().isoformat()}\n\n")
        # 解析 workflow
        step_actions_map = {}
        if isinstance(workflow, dict) and "workflows" in workflow:
            step_actions_map = {
                int(step_key): actions
                for step_key, actions in workflow["workflows"].items()
            }
        elif isinstance(workflow, list):
            step_actions_map[0] = workflow
        has_executable_actions = any(
            isinstance(item, dict)
            and isinstance(item.get("action"), dict)
            and item["action"].get("action_name") != "action_pass"
            for actions_flow in step_actions_map.values()
            for item in (actions_flow or [])
        )
        has_pass_reason = any(
            isinstance(item, dict) and "pass_reason" in item
            for actions_flow in step_actions_map.values()
            for item in (actions_flow or [])
        )
        if has_pass_reason and not has_executable_actions:
            return {
                "enterprise_results": [],
                "environment_result": None
            }
        # 获取 workflow 中最大的 step
        max_step = max(step_actions_map.keys()) if step_actions_map else 0
        has_errors = False
        # 时间步推进
        action_result = []

        for offset_step in range(max_step + 1):
            actions_flow = step_actions_map.get(offset_step, None)
            actions = [
                a for a in actions_flow
                if isinstance(a.get("action"), dict)
                and "action_name" in a["action"]
                and "action_param" in a["action"]
                and a["action"]["action_name"] != "action_pass"
            ]
            if actions:
                # 执行之前增加部门行为检查
                action_list_by_dept = {}
                error_list = []
                has_error = False
                for item in actions:
                    executor = item["executor_id"]
                    module = item["module_type"]

                    if executor not in action_list_by_dept:
                        action_list_by_dept[executor] = {}
                    if module not in action_list_by_dept[executor]:
                        action_list_by_dept[executor][module] = []
                    action_list_by_dept[executor][module].append(item["action"])
                
                for executor_id, modules in action_list_by_dept.items():
                    for module_type, actions_by_dept in modules.items():
                        if executor_id not in self.enterprises:
                            error_list.append({
                                "action_type": "batch_execute",
                                "executor_id": executor_id,
                                "module_type": module_type,
                                "status": "failed",
                                "errors": [{
                                    "code": "UNKNOWN_ENTERPRISE",
                                    "message": (
                                        f"Enterprise '{executor_id}' is not registered "
                                        f"in current simulation session"
                                    ),
                                }],
                            })
                            has_error = True
                            break
                        enterprise = self.enterprises[executor_id]
                        managers = enterprise.business_modules.get(module_type)
                        if not managers:
                            error_list.append({
                                "action_type": "batch_execute",
                                "executor_id": executor_id,
                                "module_type": module_type,
                                "status": "failed",
                                "errors": [{
                                    "code": "UNKNOWN_MODULE_MANAGER",
                                    "message": (
                                        f"Enterprise '{executor_id}' has no registered "
                                        f"module manager for '{module_type}'"
                                    ),
                                }],
                            })
                            has_error = True
                            break
                        manager = managers[0]
                        check_response = manager.batch_execute(actions_by_dept)
                        check_response_dict = check_response.to_dict()
                        if check_response_dict["status"] != "success":
                            error_list.append(check_response_dict)
                            has_error = True
                            break
                if has_error:
                    action_result.extend(error_list)
                    has_errors = True
                    break

                result = await self._execute_time_step(actions, log_file, part)
                if not result or "enterprise_results" not in result:
                    continue
                action_result.extend(result["enterprise_results"])
                # self._display_simulation_stats(step)
        grouped = defaultdict(list)
        if not isinstance(action_result, list):
            return {}
        if has_errors:
            grouped["error"].append(action_result)
        else:
            for item in action_result:
                if hasattr(item, "to_dict"):
                    status = item.to_dict()["status"]
                    grouped[status].append(item)
                elif isinstance(item, dict):
                    status = item.get("status") or "error"
                    grouped[status].append(item)
                else:
                    print("item",item)
        return dict(grouped)


    async def end_simulation(self):
        """
        结束模拟，保存和返回最终结果
        """ 
        print("===== 模拟结束 =====")
        self.is_running = False

        if self.environment:
            results = self._save_simulation_results()
        else:
            results = {}

        return results
    # 一次性的模拟调用,保留用于工作流测试
    async def run_simulation(self, total_steps: int = None, environment=None, workflow=None):
        """
        运行模拟
        
        Args:
            total_steps: 总时间步数，如果不指定则使用配置中的值
            environment: 环境实例（可选）
        
        Returns:
            dict: 模拟结果
        """
        print("===== 开始运行模拟 =====")
        
        # 确保环境已设置
        if environment:
            print("使用提供的环境实例")
            self.set_environment(environment)
        
        # 如果没有指定总步数，从配置中获取
        if total_steps is None:
            total_steps = self.config.get("time_config", {}).get("total_steps", DEFAULT_SERVICE_TOTAL_STEPS)
        
        # 确保控制器有enterprises属性
        if not hasattr(self, 'enterprises'):
            self.enterprises = {}
        if workflow:
            workflows = workflow.get('workflows', {})
            if workflows:
                # 将键转换为整数并找到最大值
                max_key = max(int(key) for key in workflows.keys())
                # 总步数为最大值加1（因为步骤从0开始）
                total_steps = max_key + 1
            else:
                total_steps = 0
        print(f"控制器开始运行模拟，总步数: {total_steps}")
        
        # 设置运行状态
        self.is_running = True
        
        # 模拟结果
        results = {}

        # 解析 workflow，构建步骤到 actions 的映射
        step_actions_map = {}
        if workflow:
            workflows = workflow.get('workflows', {})
            for step_key, actions in workflows.items():
                step_actions_map[int(step_key)] = actions
        # 开始时间轴循环
        for step in range(total_steps):
            # 获取当前步骤的 actions
            actions = step_actions_map.get(step, None)
            if actions:
            # 执行时间步
                await self._execute_time_step(step, actions)
                
                # 显示统计信息
                self._display_simulation_stats(step)
            
            # 检查是否停止
            if not self.is_running:
                print("模拟已停止")
                break
        
        # 保存结果
        if self.environment:
            results = self._save_simulation_results()
        
        return results

    def handle_enterprises_ordercheck(self):
        """
        校验订单情况
        """
        supplier_id = self.enterprise_role_ids.get("supplier")
        retailer_id = self.enterprise_role_ids.get("retailer")
        # 交易所分发潜在订单
        self.exchange_manager.analyze_potential_transaction(self.time_manager.get_day())
        # 各企业销售/采购部门自动接收潜在订单
        for enterprise in self.enterprises.values():
            if enterprise.id != supplier_id:
                # 处理向上采购
                ProcurementManagers = enterprise.business_modules.get("ProcurementManager")
                if ProcurementManagers:
                    ProcurementManager = ProcurementManagers[0]
                    ProcurementManager.receive_proposals()
            if enterprise.id != retailer_id:
                # 处理向下销售订单
                SaleManagers = enterprise.business_modules.get("SalesManager")
                if SaleManagers:
                    SaleManager = SaleManagers[0]
                    SaleManager.receive_proposals()

    def handle_enterprises_orderstatistics(self):
        """
        统计订单情况
        """
        supplier_id = self.enterprise_role_ids.get("supplier")
        retailer_id = self.enterprise_role_ids.get("retailer")
        self.exchange_manager.statistics_exchange_orders()
        # 各企业销售/采购部门建立订单
        for enterprise in self.enterprises.values():
            if enterprise.id != supplier_id:
                # 处理向上采购
                ProcurementManagers = enterprise.business_modules.get("ProcurementManager")
                if ProcurementManagers:
                    ProcurementManager = ProcurementManagers[0]
                    ProcurementManager.build_orders_from_exchange()
            if enterprise.id != retailer_id:
                # 处理向下销售订单
                SalesManagers = enterprise.business_modules.get("SalesManager")
                if SalesManagers:
                    SalesManager = SalesManagers[0]
                    SalesManager.build_orders_from_exchange()
            
