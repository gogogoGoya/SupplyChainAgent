"""
消息管理器模块

负责处理企业间的消息传递
"""

import uuid
import time
import threading
from typing import Dict, List, Callable, Optional


class MessageManager:
    """
    消息管理器
    
    线程安全实现
    """
    def __init__(self, config: Dict = None):
        """
        初始化消息管理器
        
        Args:
            config: 配置信息
        """
        self.config = config or {
            "message_delay": 0,  # 消息延迟（秒）
            "max_retries": 3,    # 最大重试次数
            "ttl": 3600          # 消息生存时间（秒）
        }
        
        self.message_queue = []  # 消息队列
        self.message_history = []  # 消息历史
        self.subscribers = {}  # 订阅者 {message_type: [callbacks]}
        self.delayed_messages = []  # 延迟消息
        self.enterprises = {}  # 企业实例映射 {enterprise_id: enterprise_instance}
        self.message_type_subscriptions = {}  # 消息类型订阅 {message_type: [enterprise_ids]}
        
        # 添加线程锁，确保线程安全
        self.lock = threading.RLock()  # 使用可重入锁

    def __getstate__(self):
        """Keep durable message state while excluding runtime-only callbacks/locks."""
        state = dict(self.__dict__)
        state["subscribers"] = {}
        state["lock"] = None
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.subscribers = {}
        self.lock = threading.RLock()
    
    def send_message(self, sender_id: str, receiver_id: str, message_type: str, content: Dict,
                    priority: str = "normal", metadata: Dict = None):
        """
        发送消息
        
        Args:
            sender_id: 发送者ID
            receiver_id: 接收者ID
            message_type: 消息类型
            content: 消息内容
            priority: 优先级 (high, normal, low)
            metadata: 额外元数据
            
        Returns:
            str: 消息ID
        """
        message_id = str(uuid.uuid4())
        timestamp = time.time()
        
        # 创建标准化消息格式
        message = {
            "id": message_id,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "message_type": message_type,
            "content": content,
            "priority": priority,
            "metadata": metadata or {},
            "timestamp": timestamp,
            "status": "sent",
            "retries": 0,
            "ttl": timestamp + self.config["ttl"],
            "urgent": metadata.get("urgent", False) if metadata else False
        }
        
        with self.lock:
            # 添加发送者名称到消息中
            if sender_id in self.enterprises:
                message["sender_name"] = self.enterprises[sender_id].name
            
            # 根据优先级插入队列
            if self.config["message_delay"] > 0:
                # 添加到延迟队列
                message["delivery_time"] = timestamp + self.config["message_delay"]
                self.delayed_messages.append(message)
                self.delayed_messages.sort(key=lambda x: x["delivery_time"])
            else:
                # 直接添加到消息队列
                self._insert_into_queue(message)
        
        return message_id
    
    def broadcast_message(self, sender_id: str, message_type: str, content: Dict,
                         priority: str = "normal", metadata: Dict = None):
        """
        广播消息
        
        Args:
            sender_id: 发送者ID
            message_type: 消息类型
            content: 消息内容
            priority: 优先级
            metadata: 额外元数据
            
        Returns:
            list: 消息ID列表
        """
        message_ids = []
        
        # 获取所有订阅该消息类型的接收者（使用锁保护）
        with self.lock:
            receivers = self._get_potential_receivers(message_type)
        
        for receiver_id in receivers:
            if receiver_id != sender_id:
                message_id = self.send_message(
                    sender_id, receiver_id, message_type, content, priority, metadata
                )
                message_ids.append(message_id)
        
        return message_ids
    
    def process_messages(self, state: Dict = None) -> List[Dict]:
        """
        处理消息队列中的消息
        
        Args:
            state: 当前状态（可选）
            
        Returns:
            list: 处理结果
        """
        results = []
        current_time = time.time()
        messages_to_process = []
        # 处理到期的延迟消息
        self._process_delayed_messages(current_time)
        
        # 获取当前消息队列中的消息（避免在处理过程中修改共享队列）
        with self.lock:
            messages_to_process = self.message_queue.copy()
            self.message_queue = []
        
        # 在锁外处理消息
        for message in messages_to_process:
            # 检查消息是否过期
            if current_time > message["ttl"]:
                message["status"] = "expired"
                with self.lock:
                    self.message_history.append(message)
                continue
            
            # 更新消息状态
            message["status"] = "processing"
            
            try:
                # 通知订阅者
                result = self._notify_subscribers(message, state)
                message["status"] = "delivered"
                results.append({
                    "message_id": message["id"],
                    "success": True,
                    "result": result
                })
            except Exception as e:
                # 处理失败，尝试重试
                message["retries"] += 1
                message["error"] = str(e)
                
                if message["retries"] <= self.config["max_retries"]:
                    # 重新加入队列
                    message["status"] = "retrying"
                    self._insert_into_queue(message)
                else:
                    # 达到最大重试次数
                    message["status"] = "failed"
                    results.append({
                        "message_id": message["id"],
                        "success": False,
                        "error": str(e)
                    })
            finally:
                # 将已处理的消息添加到历史记录
                if message["status"] not in ["retrying", "processing"]:
                    with self.lock:
                        self.message_history.append(message)
        
        return results
    
    def subscribe(self, message_type: str, callback: Callable):
        """
        订阅消息
        
        Args:
            message_type: 消息类型
            callback: 回调函数
        """
        with self.lock:
            if message_type not in self.subscribers:
                self.subscribers[message_type] = []
            
            if callback not in self.subscribers[message_type]:
                self.subscribers[message_type].append(callback)
    
    def unsubscribe(self, message_type: str, callback: Callable):
        """
        取消订阅
        
        Args:
            message_type: 消息类型
            callback: 回调函数
        """
        with self.lock:
            if message_type in self.subscribers:
                if callback in self.subscribers[message_type]:
                    self.subscribers[message_type].remove(callback)
    
    def get_message_history(self, filters: Dict = None) -> List[Dict]:
        """
        获取消息历史
        
        Args:
            filters: 过滤条件
            
        Returns:
            list: 符合条件的消息列表
        """
        filtered_messages = self.message_history.copy()
        
        if filters:
            for key, value in filters.items():
                filtered_messages = [msg for msg in filtered_messages if msg.get(key) == value]
        
        return filtered_messages
    
    def get_message_status(self, message_id: str) -> Optional[Dict]:
        """
        获取消息状态
        
        Args:
            message_id: 消息ID
            
        Returns:
            dict: 消息信息，如果不存在返回None
        """
        # 先在队列中查找
        for message in self.message_queue:
            if message["id"] == message_id:
                return message
        
        # 再在延迟队列中查找
        for message in self.delayed_messages:
            if message["id"] == message_id:
                return message
        
        # 最后在历史记录中查找
        for message in self.message_history:
            if message["id"] == message_id:
                return message
        
        return None
    
    def cancel_message(self, message_id: str) -> bool:
        """
        取消消息
        
        Args:
            message_id: 消息ID
            
        Returns:
            bool: 是否成功取消
        """
        # 从队列中移除
        for i, message in enumerate(self.message_queue):
            if message["id"] == message_id:
                message["status"] = "cancelled"
                self.message_history.append(self.message_queue.pop(i))
                return True
        
        # 从延迟队列中移除
        for i, message in enumerate(self.delayed_messages):
            if message["id"] == message_id:
                message["status"] = "cancelled"
                self.message_history.append(self.delayed_messages.pop(i))
                return True
        
        return False
    
    def _insert_into_queue(self, message: Dict):
        """
        根据优先级插入消息队列
        
        Args:
            message: 消息对象
        """
        priority_order = {"high": 0, "normal": 1, "low": 2}
        priority = priority_order.get(message["priority"], 1)
        
        with self.lock:
            # 找到合适的插入位置
            inserted = False
            for i, existing_message in enumerate(self.message_queue):
                existing_priority = priority_order.get(existing_message["priority"], 1)
                if priority < existing_priority:
                    self.message_queue.insert(i, message)
                    inserted = True
                    break
            
            if not inserted:
                self.message_queue.append(message)
    
    def _process_delayed_messages(self, current_time: float):
        """
        处理到期的延迟消息
        
        Args:
            current_time: 当前时间
        """
        ready_messages = []
        remaining_delayed = []
        
        with self.lock:
            for message in self.delayed_messages:
                if message["delivery_time"] <= current_time:
                    ready_messages.append(message)
                else:
                    remaining_delayed.append(message)
            
            # 更新延迟队列
            self.delayed_messages = remaining_delayed
        
        # 将到期的消息加入队列
        for message in ready_messages:
            self._insert_into_queue(message)
    
    def _notify_subscribers(self, message: Dict, state: Dict = None) -> List[Dict]:
        """
        通知订阅者
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            list: 回调结果列表
        """
        results = []
        message_type = message.get("message_type", message.get("type"))
        receiver_id = message.get("receiver_id", message.get("receiver"))
        enterprise = None
        callbacks = []
        
        with self.lock:
            # 1. 首先尝试直接路由到目标企业的receive_message方法
            if receiver_id and receiver_id in self.enterprises:
                enterprise = self.enterprises[receiver_id]
            
            # 获取回调函数列表
            callbacks = self.subscribers.get(message_type, []).copy()
        
        # 在锁外调用企业的receive_message方法，避免死锁
        if enterprise:
            try:
                result = enterprise.receive_message(message)
                results.append({
                    "success": True,
                    "enterprise_id": receiver_id,
                    "result": result
                })
            except Exception as e:
                results.append({
                    "success": False,
                    "enterprise_id": receiver_id,
                    "error": str(e)
                })
        
        # 2. 执行注册的回调函数（保持兼容性）
        for callback in callbacks:
            try:
                result = callback(message, state)
                results.append({
                    "success": True,
                    "result": result
                })
            except Exception as e:
                results.append({
                    "success": False,
                    "error": str(e)
                })
        
        return results
    
    def _get_potential_receivers(self, message_type: str) -> List[str]:
        """
        获取潜在的消息接收者
        
        Args:
            message_type: 消息类型
            
        Returns:
            list: 接收者ID列表
        """
        with self.lock:
            # 根据消息类型获取订阅该消息的企业ID列表
            subscribers = self.message_type_subscriptions.get(message_type, []).copy()
            
            # 如果没有特定的订阅者，返回所有已注册的企业ID
            if not subscribers:
                return list(self.enterprises.keys())
        
        return subscribers
    
    def register_enterprise(self, enterprise_id: str, enterprise_instance):
        """
        注册企业实例到消息管理器
        
        Args:
            enterprise_id: 企业ID
            enterprise_instance: 企业实例
        """
        with self.lock:
            self.enterprises[enterprise_id] = enterprise_instance
    
    def unregister_enterprise(self, enterprise_id: str):
        """
        从消息管理器中注销企业实例
        
        Args:
            enterprise_id: 企业ID
        """
        if enterprise_id in self.enterprises:
            del self.enterprises[enterprise_id]
    
    def subscribe_enterprise_to_message(self, enterprise_id: str, message_type: str):
        """
        订阅企业到特定消息类型
        
        Args:
            enterprise_id: 企业ID
            message_type: 消息类型
        """
        with self.lock:
            if message_type not in self.message_type_subscriptions:
                self.message_type_subscriptions[message_type] = []
            
            if enterprise_id not in self.message_type_subscriptions[message_type]:
                self.message_type_subscriptions[message_type].append(enterprise_id)
    
    def set_config(self, config: Dict):
        """
        设置配置
        
        Args:
            config: 配置字典
        """
        self.config.update(config)
    
    def clear_history(self):
        """
        清空消息历史
        """
        self.message_history = []
    
    def get_statistics(self) -> Dict:
        """
        获取消息统计信息
        
        Returns:
            dict: 统计信息
        """
        all_messages = self.message_history + self.message_queue + self.delayed_messages
        
        status_counts = {}
        type_counts = {}
        priority_counts = {}
        
        for message in all_messages:
            # 统计状态
            status = message["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            
            # 统计类型
            msg_type = message["type"]
            type_counts[msg_type] = type_counts.get(msg_type, 0) + 1
            
            # 统计优先级
            priority = message["priority"]
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
        
        return {
            "total_messages": len(all_messages),
            "in_queue": len(self.message_queue),
            "delayed": len(self.delayed_messages),
            "history_size": len(self.message_history),
            "status_distribution": status_counts,
            "type_distribution": type_counts,
            "priority_distribution": priority_counts
        }

# 预定义消息类型
MESSAGE_TYPES = {
    "ORDER_PLACED": "order_placed",
    "ORDER_CONFIRMED": "order_confirmed",
    "ORDER_SHIPPED": "order_shipped",
    "ORDER_DELIVERED": "order_delivered",
    "PAYMENT_REQUEST": "payment_request",
    "PAYMENT_CONFIRMED": "payment_confirmed",
    "INVENTORY_UPDATE": "inventory_update",
    "PRICE_CHANGE": "price_change",
    "DEMAND_FORCAST": "demand_forcast",
    "SUPPLY_DISRUPTION": "supply_disruption",
    "QUALITY_ISSUE": "quality_issue",
    "MAINTENANCE_SCHEDULE": "maintenance_schedule",
    "NEW_PRODUCT": "new_product",
    "PARTNERSHIP_PROPOSAL": "partnership_proposal",
    "CONTRACT_EXPIRING": "contract_expiring",
    "MARKET_INTELLIGENCE": "market_intelligence",
    "FINANCIAL_REPORT": "financial_report"
}
