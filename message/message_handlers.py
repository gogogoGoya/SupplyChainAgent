"""
消息处理器模块

定义各种类型消息的处理器
"""

from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod


class MessageHandler(ABC):
    """
    消息处理器基类
    """
    @abstractmethod
    def handle(self, message: Dict, state: Dict = None) -> Any:
        """
        处理消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            处理结果
        """
        pass
    
    @property
    def message_type(self) -> str:
        """
        获取消息类型
        
        Returns:
            str: 消息类型
        """
        pass


class OrderHandler(MessageHandler):
    """
    订单消息处理器
    """
    def __init__(self):
        self.message_types = ["order_placed", "order_confirmed", "order_shipped", "order_delivered"]
    
    def handle(self, message: Dict, state: Dict = None) -> Dict:
        """
        处理订单相关消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        msg_type = message["type"]
        content = message["content"]
        result = {"status": "handled", "message_type": msg_type}
        
        if msg_type == "order_placed":
            result["action"] = self._handle_order_placed(content, state)
        elif msg_type == "order_confirmed":
            result["action"] = self._handle_order_confirmed(content, state)
        elif msg_type == "order_shipped":
            result["action"] = self._handle_order_shipped(content, state)
        elif msg_type == "order_delivered":
            result["action"] = self._handle_order_delivered(content, state)
        
        return result
    
    @property
    def message_type(self) -> str:
        """
        返回第一个消息类型（基类要求）
        
        Returns:
            str: 消息类型
        """
        return self.message_types[0]
    
    def _handle_order_placed(self, content: Dict, state: Dict = None) -> str:
        """
        处理订单已下单消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            str: 处理动作
        """
        # 检查库存、生成订单记录等
        order_id = content.get("order_id", "")
        product_id = content.get("product_id", "")
        quantity = content.get("quantity", 0)
        
        # 在实际应用中，这里应该与库存系统交互
        if state and "enterprises" in state:
            receiver_id = content.get("receiver_id", "")
            if receiver_id in state["enterprises"]:
                enterprise = state["enterprises"][receiver_id]
                # 检查库存等逻辑
                pass
        
        return f"Created order {order_id} for product {product_id}, quantity {quantity}"
    
    def _handle_order_confirmed(self, content: Dict, state: Dict = None) -> str:
        """
        处理订单已确认消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            str: 处理动作
        """
        order_id = content.get("order_id", "")
        return f"Confirmed order {order_id}"
    
    def _handle_order_shipped(self, content: Dict, state: Dict = None) -> str:
        """
        处理订单已发货消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            str: 处理动作
        """
        order_id = content.get("order_id", "")
        tracking_number = content.get("tracking_number", "")
        return f"Shipped order {order_id} with tracking {tracking_number}"
    
    def _handle_order_delivered(self, content: Dict, state: Dict = None) -> str:
        """
        处理订单已送达消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            str: 处理动作
        """
        order_id = content.get("order_id", "")
        delivery_time = content.get("delivery_time", "")
        return f"Delivered order {order_id} at {delivery_time}"


class PaymentHandler(MessageHandler):
    """
    支付消息处理器
    """
    def handle(self, message: Dict, state: Dict = None) -> Dict:
        """
        处理支付相关消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        content = message["content"]
        order_id = content.get("order_id", "")
        amount = content.get("amount", 0)
        
        if message["type"] == "payment_request":
            return {
                "status": "payment_requested",
                "order_id": order_id,
                "amount": amount,
                "action": f"Requested payment of {amount} for order {order_id}"
            }
        elif message["type"] == "payment_confirmed":
            # 更新订单状态、财务记录等
            transaction_id = content.get("transaction_id", "")
            return {
                "status": "payment_confirmed",
                "order_id": order_id,
                "amount": amount,
                "transaction_id": transaction_id,
                "action": f"Confirmed payment of {amount} for order {order_id} (transaction {transaction_id})"
            }
        
        return {"status": "unknown_message_type"}
    
    @property
    def message_type(self) -> str:
        """
        获取消息类型
        
        Returns:
            str: 消息类型
        """
        return "payment_request"


class InventoryHandler(MessageHandler):
    """
    库存更新消息处理器
    """
    def handle(self, message: Dict, state: Dict = None) -> Dict:
        """
        处理库存更新消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        content = message["content"]
        product_id = content.get("product_id", "")
        new_quantity = content.get("quantity", 0)
        previous_quantity = content.get("previous_quantity", 0)
        
        # 更新库存记录
        if state and "enterprises" in state:
            enterprise_id = message["sender"]
            if enterprise_id in state["enterprises"]:
                enterprise = state["enterprises"][enterprise_id]
                # 更新企业库存
                if "inventory" not in enterprise:
                    enterprise["inventory"] = {}
                enterprise["inventory"][product_id] = new_quantity
        
        return {
            "status": "inventory_updated",
            "product_id": product_id,
            "previous_quantity": previous_quantity,
            "new_quantity": new_quantity,
            "change": new_quantity - previous_quantity,
            "action": f"Updated inventory for product {product_id}: {previous_quantity} -> {new_quantity}"
        }
    
    @property
    def message_type(self) -> str:
        """
        获取消息类型
        
        Returns:
            str: 消息类型
        """
        return "inventory_update"


class PriceChangeHandler(MessageHandler):
    """
    价格变动消息处理器
    """
    def handle(self, message: Dict, state: Dict = None) -> Dict:
        """
        处理价格变动消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        content = message["content"]
        product_id = content.get("product_id", "")
        new_price = content.get("price", 0)
        previous_price = content.get("previous_price", 0)
        effective_date = content.get("effective_date", None)
        
        # 更新价格记录
        if state and "enterprises" in state:
            enterprise_id = message["sender"]
            if enterprise_id in state["enterprises"]:
                enterprise = state["enterprises"][enterprise_id]
                # 更新企业产品价格
                if "products" not in enterprise:
                    enterprise["products"] = {}
                if product_id not in enterprise["products"]:
                    enterprise["products"][product_id] = {}
                enterprise["products"][product_id]["price"] = new_price
        
        return {
            "status": "price_updated",
            "product_id": product_id,
            "previous_price": previous_price,
            "new_price": new_price,
            "effective_date": effective_date,
            "percentage_change": ((new_price - previous_price) / previous_price * 100) if previous_price > 0 else 0,
            "action": f"Updated price for product {product_id}: {previous_price} -> {new_price}"
        }
    
    @property
    def message_type(self) -> str:
        """
        获取消息类型
        
        Returns:
            str: 消息类型
        """
        return "price_change"


class SupplyChainEventHandler(MessageHandler):
    """
    供应链事件处理器
    """
    def handle(self, message: Dict, state: Dict = None) -> Dict:
        """
        处理供应链事件消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        msg_type = message["type"]
        content = message["content"]
        
        handlers = {
            "demand_forcast": self._handle_demand_forcast,
            "supply_disruption": self._handle_supply_disruption,
            "quality_issue": self._handle_quality_issue,
            "maintenance_schedule": self._handle_maintenance_schedule
        }
        
        if msg_type in handlers:
            return handlers[msg_type](content, state)
        
        return {"status": "unknown_event_type", "event_type": msg_type}
    
    @property
    def message_type(self) -> str:
        """
        获取消息类型
        
        Returns:
            str: 消息类型
        """
        return "demand_forcast"
    
    def _handle_demand_forcast(self, content: Dict, state: Dict = None) -> Dict:
        """
        处理需求预测消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        product_id = content.get("product_id", "")
        period = content.get("period", "")
        forecast_quantity = content.get("quantity", 0)
        confidence = content.get("confidence", 0.5)
        
        return {
            "status": "demand_forecast_processed",
            "product_id": product_id,
            "period": period,
            "forecast_quantity": forecast_quantity,
            "confidence": confidence,
            "action": f"Processed demand forecast for product {product_id} in {period}: {forecast_quantity} units"
        }
    
    def _handle_supply_disruption(self, content: Dict, state: Dict = None) -> Dict:
        """
        处理供应中断消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        supplier_id = content.get("supplier_id", "")
        product_id = content.get("product_id", "")
        reason = content.get("reason", "")
        start_date = content.get("start_date", "")
        end_date = content.get("end_date", "")
        
        # 触发应急计划
        emergency_actions = []
        if state and "network" in state:
            # 寻找替代供应商
            # 调整生产计划
            # 通知下游企业
            pass
        
        return {
            "status": "supply_disruption_handled",
            "supplier_id": supplier_id,
            "product_id": product_id,
            "reason": reason,
            "start_date": start_date,
            "end_date": end_date,
            "emergency_actions": emergency_actions,
            "action": f"Handled supply disruption from {supplier_id} for product {product_id}"
        }
    
    def _handle_quality_issue(self, content: Dict, state: Dict = None) -> Dict:
        """
        处理质量问题消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        product_id = content.get("product_id", "")
        batch_number = content.get("batch_number", "")
        issue_description = content.get("description", "")
        severity = content.get("severity", "medium")
        
        # 启动质量控制流程
        quality_actions = []
        if severity in ["high", "critical"]:
            quality_actions.append("Initiate product recall")
        quality_actions.append("Notify affected customers")
        quality_actions.append("Investigate root cause")
        
        return {
            "status": "quality_issue_handled",
            "product_id": product_id,
            "batch_number": batch_number,
            "severity": severity,
            "description": issue_description,
            "quality_actions": quality_actions,
            "action": f"Handled quality issue for product {product_id}, batch {batch_number}"
        }
    
    def _handle_maintenance_schedule(self, content: Dict, state: Dict = None) -> Dict:
        """
        处理维护计划消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        equipment_id = content.get("equipment_id", "")
        maintenance_type = content.get("type", "scheduled")
        start_time = content.get("start_time", "")
        end_time = content.get("end_time", "")
        impact = content.get("impact", "minimal")
        
        # 调整生产计划
        production_adjustments = []
        if impact in ["significant", "critical"]:
            production_adjustments.append("Reschedule affected production runs")
            production_adjustments.append("Allocate alternative equipment")
        
        return {
            "status": "maintenance_scheduled",
            "equipment_id": equipment_id,
            "maintenance_type": maintenance_type,
            "start_time": start_time,
            "end_time": end_time,
            "impact": impact,
            "production_adjustments": production_adjustments,
            "action": f"Scheduled maintenance for equipment {equipment_id} from {start_time} to {end_time}"
        }


class BusinessDevelopmentHandler(MessageHandler):
    """
    业务发展消息处理器
    """
    def handle(self, message: Dict, state: Dict = None) -> Dict:
        """
        处理业务发展相关消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        msg_type = message["type"]
        content = message["content"]
        
        handlers = {
            "new_product": self._handle_new_product,
            "partnership_proposal": self._handle_partnership_proposal,
            "contract_expiring": self._handle_contract_expiring,
            "market_intelligence": self._handle_market_intelligence
        }
        
        if msg_type in handlers:
            return handlers[msg_type](content, state)
        
        return {"status": "unknown_business_event", "event_type": msg_type}
    
    @property
    def message_type(self) -> str:
        """
        获取消息类型
        
        Returns:
            str: 消息类型
        """
        return "new_product"
    
    def _handle_new_product(self, content: Dict, state: Dict = None) -> Dict:
        """
        处理新产品发布消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        product_id = content.get("product_id", "")
        product_name = content.get("name", "")
        description = content.get("description", "")
        price = content.get("price", 0)
        launch_date = content.get("launch_date", "")
        
        # 更新产品目录
        if state and "enterprises" in state:
            enterprise_id = message["sender"]
            if enterprise_id in state["enterprises"]:
                enterprise = state["enterprises"][enterprise_id]
                # 添加新产品
                if "products" not in enterprise:
                    enterprise["products"] = {}
                enterprise["products"][product_id] = {
                    "name": product_name,
                    "description": description,
                    "price": price,
                    "launch_date": launch_date
                }
        
        return {
            "status": "new_product_added",
            "product_id": product_id,
            "product_name": product_name,
            "price": price,
            "launch_date": launch_date,
            "action": f"Added new product {product_name} ({product_id})"
        }
    
    def _handle_partnership_proposal(self, content: Dict, state: Dict = None) -> Dict:
        """
        处理合作提案消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        proposer_id = content.get("proposer_id", "")
        partnership_type = content.get("type", "general")
        terms = content.get("terms", {})
        deadline = content.get("response_deadline", "")
        
        # 评估合作提案
        evaluation = {
            "proposer_id": proposer_id,
            "partnership_type": partnership_type,
            "potential_value": "unknown",
            "risk_level": "unknown",
            "next_steps": ["Review proposal details", "Analyze business impact", "Schedule negotiation"]
        }
        
        return {
            "status": "partnership_proposal_received",
            "proposer_id": proposer_id,
            "partnership_type": partnership_type,
            "deadline": deadline,
            "evaluation": evaluation,
            "action": f"Received partnership proposal from {proposer_id}"
        }
    
    def _handle_contract_expiring(self, content: Dict, state: Dict = None) -> Dict:
        """
        处理合同到期消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        contract_id = content.get("contract_id", "")
        partner_id = content.get("partner_id", "")
        expiration_date = content.get("expiration_date", "")
        days_remaining = content.get("days_remaining", 0)
        auto_renew = content.get("auto_renew", False)
        
        # 准备合同续签或终止流程
        actions = []
        if days_remaining <= 30:
            actions.append("Immediate review required")
        if auto_renew:
            actions.append("Confirm auto-renewal terms")
        else:
            actions.append("Prepare negotiation for renewal")
        
        return {
            "status": "contract_expiration_alert",
            "contract_id": contract_id,
            "partner_id": partner_id,
            "expiration_date": expiration_date,
            "days_remaining": days_remaining,
            "actions": actions,
            "action": f"Alert: Contract {contract_id} with {partner_id} expires in {days_remaining} days"
        }
    
    def _handle_market_intelligence(self, content: Dict, state: Dict = None) -> Dict:
        """
        处理市场情报消息
        
        Args:
            content: 消息内容
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        market_segment = content.get("market_segment", "")
        trend_type = content.get("trend_type", "")
        trend_description = content.get("description", "")
        source = content.get("source", "")
        confidence = content.get("confidence", 0.5)
        
        # 更新市场情报数据库
        if state and "market_intelligence" not in state:
            state["market_intelligence"] = []
        
        return {
            "status": "market_intelligence_processed",
            "market_segment": market_segment,
            "trend_type": trend_type,
            "source": source,
            "confidence": confidence,
            "action": f"Processed market intelligence for {market_segment}: {trend_description}"
        }


class FinancialReportHandler(MessageHandler):
    """
    财务报告消息处理器
    """
    def handle(self, message: Dict, state: Dict = None) -> Dict:
        """
        处理财务报告消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        content = message["content"]
        period = content.get("period", "")
        financial_data = content.get("financial_data", {})
        
        # 更新财务记录
        if state and "enterprises" in state:
            enterprise_id = message["sender"]
            if enterprise_id in state["enterprises"]:
                enterprise = state["enterprises"][enterprise_id]
                # 更新财务数据
                if "financials" not in enterprise:
                    enterprise["financials"] = {}
                enterprise["financials"][period] = financial_data
        
        return {
            "status": "financial_report_processed",
            "period": period,
            "revenue": financial_data.get("revenue", 0),
            "profit": financial_data.get("profit", 0),
            "action": f"Processed financial report for period {period}"
        }
    
    @property
    def message_type(self) -> str:
        """
        获取消息类型
        
        Returns:
            str: 消息类型
        """
        return "financial_report"


# 消息处理器工厂
def create_message_handler(message_type: str) -> Optional[MessageHandler]:
    """
    创建消息处理器
    
    Args:
        message_type: 消息类型
        
    Returns:
        MessageHandler: 消息处理器实例
    """
    handlers = {
        "order_placed": OrderHandler,
        "order_confirmed": OrderHandler,
        "order_shipped": OrderHandler,
        "order_delivered": OrderHandler,
        "payment_request": PaymentHandler,
        "payment_confirmed": PaymentHandler,
        "inventory_update": InventoryHandler,
        "price_change": PriceChangeHandler,
        "demand_forcast": SupplyChainEventHandler,
        "supply_disruption": SupplyChainEventHandler,
        "quality_issue": SupplyChainEventHandler,
        "maintenance_schedule": SupplyChainEventHandler,
        "new_product": BusinessDevelopmentHandler,
        "partnership_proposal": BusinessDevelopmentHandler,
        "contract_expiring": BusinessDevelopmentHandler,
        "market_intelligence": BusinessDevelopmentHandler,
        "financial_report": FinancialReportHandler
    }
    
    handler_class = handlers.get(message_type)
    if handler_class:
        return handler_class()
    
    return None


# 消息总线类，用于管理多个处理器
class MessageBus:
    """
    消息总线
    """
    def __init__(self):
        self.handlers = {}
    
    def register_handler(self, handler: MessageHandler):
        """
        注册消息处理器
        
        Args:
            handler: 消息处理器实例
        """
        if hasattr(handler, 'message_types'):
            # 如果处理器支持多种消息类型
            for msg_type in handler.message_types:
                self.handlers[msg_type] = handler
        else:
            # 单一消息类型处理器
            self.handlers[handler.message_type] = handler
    
    def handle_message(self, message: Dict, state: Dict = None) -> Dict:
        """
        处理消息
        
        Args:
            message: 消息对象
            state: 当前状态
            
        Returns:
            dict: 处理结果
        """
        msg_type = message["type"]
        handler = self.handlers.get(msg_type)
        
        if handler:
            return handler.handle(message, state)
        else:
            return {
                "status": "no_handler",
                "message_type": msg_type,
                "action": f"No handler found for message type {msg_type}"
            }
    
    def get_registered_types(self) -> List[str]:
        """
        获取已注册的消息类型
        
        Returns:
            list: 消息类型列表
        """
        return list(self.handlers.keys())