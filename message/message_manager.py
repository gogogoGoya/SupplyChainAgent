"""
Message Manager Module

Responsible for the transmission of information between enterprise
"""

import uuid
import time
import threading
from typing import Dict, List, Callable, Optional


class MessageManager:
    """
    Message Manager
        
    Line secure.
        """
    def __init__(self, config: Dict = None):
        """
        Initialise Message Manager
                
        Args:
            config: Configure information
                """
        self.config = config or {
            "message_delay": 0,  # Message delay (sec)
            "max_retries": 3,    # Maximum number of retries
            "ttl": 3600          # Message survival time (sec)
        }
        
        self.message_queue = []  # Message queue
        self.message_history = []  # Message History
        self.subscribers = {}  # Subscriber {message_type: [callbacks]}
        self.delayed_messages = []  # Delay Message
        self.enterprises = {}  # Example map enterprise {enterprise_id: enterprise_instance}
        self.message_type_subscriptions = {}  # Can not open message
        
        # Add a thread lock to make it safe.
        self.lock = threading.RLock()  # Use re-lockable

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
        Send Message
                
        Args:
            parameter: Sender ID
            parameter: Receiver ID
            parameter: Message Type
            Contact: Message Contents
            priority: (high, low)
            Metadata: Extra metadata
                        
        Returns:
            str: Message ID
                """
        message_id = str(uuid.uuid4())
        timestamp = time.time()
        
        # Create standardized message format
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
            # Add sender name to message
            if sender_id in self.enterprises:
                message["sender_name"] = self.enterprises[sender_id].name
            
            # Insert Queue by Priority
            if self.config["message_delay"] > 0:
                # Add to Delay Queue
                message["delivery_time"] = timestamp + self.config["message_delay"]
                self.delayed_messages.append(message)
                self.delayed_messages.sort(key=lambda x: x["delivery_time"])
            else:
                # Can not open message
                self._insert_into_queue(message)
        
        return message_id
    
    def broadcast_message(self, sender_id: str, message_type: str, content: Dict,
                         priority: str = "normal", metadata: Dict = None):
        """
        Radio
                
        Args:
            parameter: Sender ID
            parameter: Message Type
            Contact: Message Contents
            priority:
            Metadata: Extra metadata
                        
        Returns:
            list: Message ID list
                """
        message_ids = []
        
        # Can not get message: %s %s
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
        Handle messages in line
                
        Args:
            State: Current Status (optional)
                        
        Returns:
            list: Processing results
                """
        results = []
        current_time = time.time()
        messages_to_process = []
        # Can not open message
        self._process_delayed_messages(current_time)
        
        # Fetch the current message queue (avoid changing the share queue during processing)
        with self.lock:
            messages_to_process = self.message_queue.copy()
            self.message_queue = []
        
        # Handle messages outside lock
        for message in messages_to_process:
            # Check if the message is expired
            if current_time > message["ttl"]:
                message["status"] = "expired"
                with self.lock:
                    self.message_history.append(message)
                continue
            
            # Can not open message
            message["status"] = "processing"
            
            try:
                # Notify subscribers
                result = self._notify_subscribers(message, state)
                message["status"] = "delivered"
                results.append({
                    "message_id": message["id"],
                    "success": True,
                    "result": result
                })
            except Exception as e:
                # Process failed. Try again.
                message["retries"] += 1
                message["error"] = str(e)
                
                if message["retries"] <= self.config["max_retries"]:
                    # Rejoinder
                    message["status"] = "retrying"
                    self._insert_into_queue(message)
                else:
                    # Maximum number of retries reached
                    message["status"] = "failed"
                    results.append({
                        "message_id": message["id"],
                        "success": False,
                        "error": str(e)
                    })
            finally:
                # Add processed messages to historical records
                if message["status"] not in ["retrying", "processing"]:
                    with self.lock:
                        self.message_history.append(message)
        
        return results
    
    def subscribe(self, message_type: str, callback: Callable):
        """
        Can not open message
                
        Args:
            parameter: Message Type
            Callback function
                """
        with self.lock:
            if message_type not in self.subscribers:
                self.subscribers[message_type] = []
            
            if callback not in self.subscribers[message_type]:
                self.subscribers[message_type].append(callback)
    
    def unsubscribe(self, message_type: str, callback: Callable):
        """
        Unsubscribe
                
        Args:
            parameter: Message Type
            Callback function
                """
        with self.lock:
            if message_type in self.subscribers:
                if callback in self.subscribers[message_type]:
                    self.subscribers[message_type].remove(callback)
    
    def get_message_history(self, filters: Dict = None) -> List[Dict]:
        """
        Get Message History
                
        Args:
            Filters: Filter Conditions
                        
        Returns:
            list: list of eligible messages
                """
        filtered_messages = self.message_history.copy()
        
        if filters:
            for key, value in filters.items():
                filtered_messages = [msg for msg in filtered_messages if msg.get(key) == value]
        
        return filtered_messages
    
    def get_message_status(self, message_id: str) -> Optional[Dict]:
        """
        Can not open message
                
        Args:
            parameter: Message ID
                        
        Returns:
            dict: Message message if no one returns
                """
        # Find in queue first
        for message in self.message_queue:
            if message["id"] == message_id:
                return message
        
        # Find in the delayed queue
        for message in self.delayed_messages:
            if message["id"] == message_id:
                return message
        
        # Finally find in history
        for message in self.message_history:
            if message["id"] == message_id:
                return message
        
        return None
    
    def cancel_message(self, message_id: str) -> bool:
        """
        Can not open message
                
        Args:
            parameter: Message ID
                        
        Returns:
            Bool: Cancel successfully
                """
        # Remove From Queue
        for i, message in enumerate(self.message_queue):
            if message["id"] == message_id:
                message["status"] = "cancelled"
                self.message_history.append(self.message_queue.pop(i))
                return True
        
        # Remove from Delay Queue
        for i, message in enumerate(self.delayed_messages):
            if message["id"] == message_id:
                message["status"] = "cancelled"
                self.message_history.append(self.delayed_messages.pop(i))
                return True
        
        return False
    
    def _insert_into_queue(self, message: Dict):
        """
        Insert Message Queue By Priority
                
        Args:
            message:
                """
        priority_order = {"high": 0, "normal": 1, "low": 2}
        priority = priority_order.get(message["priority"], 1)
        
        with self.lock:
            # Finds the right place to insert
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
        Can not open message
                
        Args:
            parameter: Current time
                """
        ready_messages = []
        remaining_delayed = []
        
        with self.lock:
            for message in self.delayed_messages:
                if message["delivery_time"] <= current_time:
                    ready_messages.append(message)
                else:
                    remaining_delayed.append(message)
            
            # Update delay queue
            self.delayed_messages = remaining_delayed
        
        # Queue messages due
        for message in ready_messages:
            self._insert_into_queue(message)
    
    def _notify_subscribers(self, message: Dict, state: Dict = None) -> List[Dict]:
        """
        Notify subscribers
                
        Args:
            message:
            State: Current status
                        
        Returns:
            list: Return result list
                """
        results = []
        message_type = message.get("message_type", message.get("type"))
        receiver_id = message.get("receiver_id", message.get("receiver"))
        enterprise = None
        callbacks = []
        
        with self.lock:
            # First attempt at direct route to target enterprise
            if receiver_id and receiver_id in self.enterprises:
                enterprise = self.enterprises[receiver_id]
            
            # Retrieving return function list
            callbacks = self.subscribers.get(message_type, []).copy()
        
        # Call enterprisereceive message method outside the lock to avoid a dead lock
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
        
        # 2. Execution of a callback function for registration (maintain compatibility)
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
        Get Potential Receiver
                
        Args:
            parameter: Message Type
                        
        Returns:
            list: Recipient ID list
                """
        with self.lock:
            # Can not delete folder: %s: No such folder
            subscribers = self.message_type_subscriptions.get(message_type, []).copy()
            
            # Return all registered enterpriseIDs if no specific subscriber
            if not subscribers:
                return list(self.enterprises.keys())
        
        return subscribers
    
    def register_enterprise(self, enterprise_id: str, enterprise_instance):
        """
        Register enterprise instance to message manager
                
        Args:
            enterprise_id: enterpriseID
            enterprise_instance: enterprise Examples
                """
        with self.lock:
            self.enterprises[enterprise_id] = enterprise_instance
    
    def unregister_enterprise(self, enterprise_id: str):
        """
        Can not delete folder: %s: No such folder
                
        Args:
            enterprise_id: enterpriseID
                """
        if enterprise_id in self.enterprises:
            del self.enterprises[enterprise_id]
    
    def subscribe_enterprise_to_message(self, enterprise_id: str, message_type: str):
        """
        Subscription to enterprise Specific Message Type
                
        Args:
            enterprise_id: enterpriseID
            parameter: Message Type
                """
        with self.lock:
            if message_type not in self.message_type_subscriptions:
                self.message_type_subscriptions[message_type] = []
            
            if enterprise_id not in self.message_type_subscriptions[message_type]:
                self.message_type_subscriptions[message_type].append(enterprise_id)
    
    def set_config(self, config: Dict):
        """
        Settings Configuration
                
        Args:
            config: Configure Dictionary
                """
        self.config.update(config)
    
    def clear_history(self):
        """
        Clear Message History
                """
        self.message_history = []
    
    def get_statistics(self) -> Dict:
        """
        Get news statistics
                
        Returns:
            dict: Statistical information
                """
        all_messages = self.message_history + self.message_queue + self.delayed_messages
        
        status_counts = {}
        type_counts = {}
        priority_counts = {}
        
        for message in all_messages:
            # Statistical Status
            status = message["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            
            # Statistical type
            msg_type = message["type"]
            type_counts[msg_type] = type_counts.get(msg_type, 0) + 1
            
            # Statistical priorities
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

# Predefined Message Type
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
