"""
环境引擎模块

负责管理仿真环境的状态和行为
"""

# 从core目录导入
from core.event_manager import EventManager
from config.environment_config import EnvironmentConfig
# 注意：其他模块可能需要创建或修改导入路径
# 临时注释掉缺失的导入，以便能够运行基本代码
# from core.action_manager import ActionManager
# 替换为简单的类定义
class ActionManager:
    def __init__(self):
        pass
    def execute_action(self, *args, **kwargs):
        pass
    def reset(self):
        pass

class StatusManager:
    def __init__(self):
        pass
    def reset(self):
        pass

class EnterpriseNetworkManager:
    def __init__(self):
        self.enterprises = {}
    def reset(self):
        self.enterprises = {}
    def initialize_network(self, *args, **kwargs):
        pass
    def get_network_state(self):
        return {}



class Environment:
    """
    仿真环境类
    负责管理仿真环境的状态和行为，作为Controller的受控组件
    """
    def __init__(self):
        """
        初始化环境引擎
        """
        self.action_manager = None
        self.network_manager = None
        self.event_manager = None
        self.state_manager = None  # 预留状态管理器引用
        self.message_manager = None  
        self.time_manager = None
        self.controller = None  # 控制器引用
        
        # 环境状态
        self.enterprises = {}
        self.state_history = []
        self.event_history = []
    
    def set_time_manager(self, time_manager):
        """
        设置时间步管理器实例
        
        Args:
            time_manager: 时间步管理器实例
        """
        self.time_manager = time_manager
        
    def set_network_manager(self, network_manager):
        """
        设置网络管理器实例
        
        Args:
            network_manager: 网络管理器实例
        """
        self.network_manager = network_manager
        
    def set_message_manager(self, message_manager):
        """
        设置消息管理器实例
        
        Args:
            message_manager: 消息管理器实例
        """
        self.message_manager = message_manager
        
    def set_controller(self, controller):
        """
        设置控制器实例
        
        Args:
            controller: Controller实例
        """
        self.controller = controller
        # 确保环境与控制器的事件管理器同步
        if hasattr(controller, 'event_manager') and controller.event_manager:
            self.event_manager = controller.event_manager
        # 确保环境与控制器的状态管理器同步
        if hasattr(controller, 'state_manager') and controller.state_manager:
            self.state_manager = controller.state_manager
        if hasattr(controller, 'network_manager') and controller.network_manager:
            self.network_manager = controller.network_manager
        if hasattr(controller, 'action_manager') and controller.action_manager:
            self.action_manager = controller.action_manager
        if hasattr(controller, 'message_manager') and controller.message_manager:
            self.message_manager = controller.message_manager
        if hasattr(controller, 'time_manager') and controller.time_manager:
            self.time_manager = controller.time_manager
    
    def reset(self, network_config=None, enterprise_configs=None):
        """
        重置环境
        
        Args:
            network_config: 网络配置
            enterprise_configs: 企业配置列表
        """
        # 重置所有管理器 - 添加检查避免空引用
        if hasattr(self, 'network_manager') and self.network_manager:
            self.network_manager.reset()
        else:
            print("警告: 企业网络管理器未设置，跳过重置")
        
        if hasattr(self, 'event_manager') and self.event_manager:
            self.event_manager.reset()
        else:
            print("警告: 事件管理器未设置，跳过重置")
        
        
        # 初始化状态
        self.state_history = []
        self.event_history = []
        
        # 保存初始状态
        initial_state = self.get_current_state()
        self.state_history.append(initial_state)
    
    def step(self, step: int):
        """
        执行一步环境更新 - 处理整体模拟的事件
        
        负责处理系统级事件，如市场变化、供应中断、季节性需求波动等
        
        Args:
            step: 当前时间步    
        
        Returns:
            dict: 更新后的环境状态和事件处理结果
        """
        
        # 获取当前时间点及之前的所有事件
        events = self.event_manager.get_next_events(self.time_manager.get_datetime())
        
        event_processing_results = {}
        
        # 处理获取到的事件
        if events:
            print(f"处理 {len(events)} 个环境事件...")
            # 获取当前状态用于事件处理
            current_state = self.get_current_state()
            
            # 按类型分类处理不同事件
            for event in events:
                event_type = event.get('type')
                
                # 具体事件处理示例
                if event_type == 'MARKET_DEMAND_CHANGE':
                    print(f"处理市场需求变化事件: {event.get('data', {})}")
                    # 更新市场条件中的需求水平
                    self._update_market_demand(event.get('data', {}))
                    
                elif event_type == 'SUPPLY_DISRUPTION':
                    print(f"处理供应中断事件: {event.get('data', {})}")
                    # 影响供应链中的供应可用性
                    self._handle_supply_disruption(event.get('data', {}))
                    
                elif event_type == 'SEASONAL_ADJUSTMENT':
                    print(f"处理季节性调整事件: {event.get('data', {})}")
                    # 根据季节调整市场条件
                    self._apply_seasonal_adjustments(event.get('data', {}))
                    
                elif event_type == 'LOGISTICS_DELAY':
                    print(f"处理物流延迟事件: {event.get('data', {})}")
                    # 调整物流相关参数
                    self._adjust_logistics(event.get('data', {}))
                    
                elif event_type == 'PRICE_FLUCTUATION':
                    print(f"处理价格波动事件: {event.get('data', {})}")
                    # 更新价格指数
                    self._update_price_index(event.get('data', {}))
                    
                # 记录事件处理结果
                event_processing_results[event.get('id', str(len(event_processing_results)))] = {
                    'type': event_type,
                    'processed': True
                }
            
            # 处理所有事件
            results = self.event_manager.process_events(events, current_state)
            
            # 记录事件
            self.event_history.extend(events)
        
        # 处理消息和协商（使用MessageManager）
        self._process_messages_and_negotiations()
    
        # 获取并保存更新后的状态
        current_state = self.get_current_state()
        self.state_history.append(current_state)
        
        return {
            'state': current_state,
            'events_processed': event_processing_results,
            'total_events': len(events) if events else 0
        }
    
    def _update_market_demand(self, event_data):
        """
        更新市场需求
        
        Args:
            event_data: 包含需求变化信息的数据
        """
        # 实现市场需求更新逻辑
        demand_factor = event_data.get('demand_factor', 1.0)
        product_id = event_data.get('product_id')
        
        # 更新相关企业的需求预测
        if product_id:
            for enterprise in self.enterprises.values():
                if hasattr(enterprise, 'update_demand_forecast'):
                    enterprise.update_demand_forecast(product_id, demand_factor)
    
    def _handle_supply_disruption(self, event_data):
        """
        处理供应中断
        
        Args:
            event_data: 包含中断信息的数据
        """
        supplier_id = event_data.get('supplier_id')
        duration = event_data.get('duration', 1)
        
        # 通知相关企业供应中断
        for enterprise in self.enterprises.values():
            if hasattr(enterprise, 'notify_supply_disruption'):
                enterprise.notify_supply_disruption(supplier_id, duration)
    
    def _apply_seasonal_adjustments(self, event_data):
        """
        应用季节性调整
        
        Args:
            event_data: 包含季节信息的数据
        """
        season = event_data.get('season')
        # 实现季节性调整逻辑
        pass
    
    def _adjust_logistics(self, event_data):
        """
        调整物流参数
        
        Args:
            event_data: 包含物流调整信息的数据
        """
        delay_factor = event_data.get('delay_factor', 1.0)
        # 实现物流调整逻辑
        pass
    
    def _update_price_index(self, event_data):
        """
        更新价格指数
        
        Args:
            event_data: 包含价格变化信息的数据
        """
        price_factor = event_data.get('price_factor', 1.0)
        product_id = event_data.get('product_id')
        # 实现价格指数更新逻辑
        pass
    
    def _process_messages_and_negotiations(self):
        """
        处理消息和协商过程
        """
        # 如果已设置消息管理器，则使用它处理消息
        if hasattr(self, 'message_manager') and self.message_manager:
            # 调用MessageManager的process_messages方法处理所有待处理的消息
            self.message_manager.process_messages()
    
    def get_current_state(self):
        """
        获取当前环境状态
        
        Returns:
            dict: 环境状态
        """
        # 安全获取网络状态，避免空引用
        network_state = {}
        if hasattr(self, 'network_manager') and self.network_manager:
            try:
                network_state = self.network_manager.get_network_state()
            except Exception as e:
                print(f"获取网络状态时出错: {str(e)}")
                network_state = {"status": "error", "message": str(e)}
        else:
            network_state = {"status": "not_available", "message": "企业网络管理器未设置"}
        
        # 安全获取企业状态
        enterprise_states = {}
        if hasattr(self, 'enterprises') and self.enterprises:
            enterprise_states = {eid: ent.get_state() for eid, ent in self.enterprises.items()}
        
        return {
            "time": self.time_manager.get_datetime(),
            "enterprises": enterprise_states,
            "network": network_state,
            "market_conditions": self._get_market_conditions()
        }
    
    def _get_market_conditions(self):
        """
        获取当前市场条件
        
        Returns:
            dict: 市场条件
        """
        # 这里可以实现市场条件的生成逻辑
        return {
            "demand_level": 1.0,
            "price_index": 1.0,
            "supply_availability": 1.0
        }
    
    def add_enterprise(self, enterprise):
        """
        添加企业到环境
        
        Args:
            enterprise: 企业实例
        """
        # 使用enterprise.id作为企业标识符
        self.enterprises[enterprise.id] = enterprise
        # 如果已设置消息管理器，则将企业注册到消息管理器
        if hasattr(self, 'message_manager') and self.message_manager:
            self.message_manager.register_enterprise(enterprise.id, enterprise)
    
    def remove_enterprise(self, enterprise_id):
        """
        从环境中移除企业
        
        Args:
            enterprise_id: 企业ID
        """
        if enterprise_id in self.enterprises:
            del self.enterprises[enterprise_id]
    
    def get_enterprise(self, enterprise_id):
        """
        获取企业实例
        
        Args:
            enterprise_id: 企业ID
            
        Returns:
            Enterprise: 企业实例
        """
        return self.enterprises.get(enterprise_id)
    
    def close(self):
        """
        关闭环境
        """
        # 清理工作由MessageManager处理