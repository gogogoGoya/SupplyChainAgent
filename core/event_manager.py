"""
事件管理器模块

负责管理仿真系统中的各类事件
"""

class EventManager:
    """
    事件管理器
    """
    def __init__(self):
        """
        初始化事件管理器
        """
        self.events = []  # 事件列表
        self.event_handlers = {}  # 事件处理器映射
    
    def add_event(self, event):
        """
        添加事件
        
        Args:
            event: 事件对象,应包含type, timestamp, payload等字段
        """
        # 按时间戳排序插入
        inserted = False
        for i, existing_event in enumerate(self.events):
            if event["timestamp"] < existing_event["timestamp"]:
                self.events.insert(i, event)
                inserted = True
                break
        
        if not inserted:
            self.events.append(event)
    
    def add_events(self, events):
        """
        批量添加事件
        
        Args:
            events: 事件列表
        """
        for event in events:
            self.add_event(event)
    
    def get_next_events(self, current_time):
        """
        获取当前时间点及之前的所有未处理事件
        
        Args:
            current_time: 当前时间点
            
        Returns:
            list: 事件列表
        """
        events_to_process = []
        remaining_events = []
        
        for event in self.events:
            if event["timestamp"] <= current_time:
                events_to_process.append(event)
            else:
                remaining_events.append(event)
        
        # 更新事件列表
        self.events = remaining_events
        
        return events_to_process
        
    def process_events(self, events, current_state=None):
        """
        处理事件列表
        
        Args:
            events: 要处理的事件列表
            current_state: 当前系统状态（可选）
            
        Returns:
            list: 处理结果列表
        """
        results = []
        
        for event in events:
            # 查找适合处理此事件的处理器
            for handler in self.event_handlers.get(event["type"], []):
                try:
                    # 执行处理器
                    if current_state is not None:
                        result = handler(event, current_state)
                    else:
                        result = handler(event)
                    
                    # 记录处理结果
                    if result is not None:
                        results.append({
                            'event_id': id(event),
                            'event_type': event["type"],
                            'handler': str(handler),
                            'result': result
                        })
                except Exception as e:
                    # 记录处理异常
                    results.append({
                        'event_id': id(event),
                        'event_type': event["type"],
                        'handler': str(handler),
                        'result': {'status': 'error', 'message': str(e)}
                    })
        
        return results
    
    def register_handler(self, event_type, handler):
        """
        注册事件处理器
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        
        self.event_handlers[event_type].append(handler)
    
    def unregister_handler(self, event_type, handler):
        """
        注销事件处理器
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if event_type in self.event_handlers:
            self.event_handlers[event_type].remove(handler)
    
    def process_events(self, events, state):
        """
        处理事件
        
        Args:
            events: 要处理的事件列表
            state: 当前状态
            
        Returns:
            list: 处理结果列表
        """
        results = []
        
        for event in events:
            event_type = event["type"]
            
            # 查找事件处理器
            handlers = self.event_handlers.get(event_type, [])
            
            for handler in handlers:
                result = handler(event, state)
                results.append(result)
        
        return results
    
    def clear_events(self):
        """
        清空所有事件
        """
        self.events = []
    
    def get_event_count(self):
        """
        获取当前事件数量
        
        Returns:
            int: 事件数量
        """
        return len(self.events)
    
    def get_pending_events_by_type(self, event_type):
        """
        获取指定类型的待处理事件
        
        Args:
            event_type: 事件类型
            
        Returns:
            list: 事件列表
        """
        return [event for event in self.events if event["type"] == event_type]
    
    def cancel_events(self, event_type=None, enterprise_id=None):
        """
        取消指定类型或企业的事件
        
        Args:
            event_type: 事件类型（可选）
            enterprise_id: 企业ID（可选）
        """
        remaining_events = []
        
        for event in self.events:
            should_keep = True
            
            if event_type is not None and event["type"] == event_type:
                should_keep = False
            
            if enterprise_id is not None and event.get("enterprise_id") == enterprise_id:
                should_keep = False
            
            if should_keep:
                remaining_events.append(event)
        
        self.events = remaining_events
    
    def reset(self):
        """
        重置事件管理器状态
        """
        self.events = []
        self.event_handlers = {}

# 预定义事件类型
EVENT_TYPES = {
    "PRODUCTION_COMPLETE": "production_complete",
    "ORDER_RECEIVED": "order_received",
    "ORDER_DELIVERED": "order_delivered",
    "PAYMENT_MADE": "payment_made",
    "PAYMENT_RECEIVED": "payment_received",
    "INVENTORY_LOW": "inventory_low",
    "SUPPLIER_DELAY": "supplier_delay",
    "DEMAND_CHANGE": "demand_change",
    "PRICE_CHANGE": "price_change",
    "ENTERPRISE_BANKRUPTCY": "enterprise_bankruptcy",
    "NEW_SUPPLIER": "new_supplier",
    "NEW_CUSTOMER": "new_customer",
    "CONTRACT_EXPIRE": "contract_expire",
    "QUALITY_ISSUE": "quality_issue",
    "MAINTENANCE_START": "maintenance_start",
    "MAINTENANCE_END": "maintenance_end"
}

# 事件工厂函数
def create_event(event_type, timestamp, payload=None, enterprise_id=None, data=None):
    """
    创建事件
    
    Args:
        event_type: 事件类型
        timestamp: 时间戳
        payload: 事件数据（可选）
        enterprise_id: 企业ID（可选）
        data: 事件数据（兼容新格式）
        
    Returns:
        dict: 事件对象
    """
    # 创建事件对象，支持data和payload两种格式
    event = {
        "type": event_type,
        "timestamp": timestamp
    }
    
    # 如果提供了payload，使用payload
    if payload is not None:
        event["payload"] = payload
    # 如果提供了data，使用data
    elif data is not None:
        event["data"] = data
    # 否则使用空字典
    else:
        event["data"] = {}
    
    if enterprise_id:
        event["enterprise_id"] = enterprise_id
    
    return event

# 预定义的时间步和阶段事件类型
TIME_STEP_EVENT_TYPES = {
    "TIME_STEP_START": "time_step_start",
    "TIME_STEP_END": "time_step_end",
    "TIME_STEP_PHASE_STARTED": "time_step_phase_started",
    "TIME_STEP_PHASE_COMPLETED": "time_step_phase_completed",
    "TIME_STEP_COMPLETED": "time_step_completed",
    "ENTERPRISE_DECISION_STARTED": "enterprise_decision_started",
    "ENTERPRISE_DECISION_COMPLETED": "enterprise_decision_completed",
    "ENTERPRISE_EXECUTION_STARTED": "enterprise_execution_started",
    "ENTERPRISE_EXECUTION_COMPLETED": "enterprise_execution_completed"
}