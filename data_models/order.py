"""
订单数据模型模块

定义订单、订单行项目等相关数据模型
"""

from typing import Dict, Any, Optional, List, Set, Tuple
from datetime import datetime
from enum import Enum

from supply_chain_agent.data_models.base_model import BaseModel, NamedModel, AuditableModel, TimestampedModel


class OrderStatus(str, Enum):
    """
    订单状态枚举
    """
    DRAFT = "draft"              # 草稿
    PENDING = "pending"          # 待处理
    PROCESSING = "processing"    # 处理中
    CONFIRMED = "confirmed"      # 已确认
    SHIPPED = "shipped"          # 已发货
    DELIVERED = "delivered"      # 已送达
    CANCELLED = "cancelled"      # 已取消
    RETURNED = "returned"        # 已退货
    REFUNDED = "refunded"        # 已退款
    PARTIALLY_SHIPPED = "partially_shipped"  # 部分发货
    PARTIALLY_DELIVERED = "partially_delivered"  # 部分送达


class PaymentStatus(str, Enum):
    """
    支付状态枚举
    """
    PENDING = "pending"          # 待支付
    PAID = "paid"                # 已支付
    PARTIALLY_PAID = "partially_paid"  # 部分支付
    REFUNDED = "refunded"        # 已退款
    PARTIALLY_REFUNDED = "partially_refunded"  # 部分退款
    FAILED = "failed"            # 支付失败
    CANCELLED = "cancelled"      # 支付取消


class ShippingStatus(str, Enum):
    """
    物流状态枚举
    """
    PENDING = "pending"          # 待发货
    PROCESSING = "processing"    # 处理中
    SHIPPED = "shipped"          # 已发货
    IN_TRANSIT = "in_transit"    # 运输中
    DELIVERED = "delivered"      # 已送达
    FAILED = "failed"            # 配送失败
    RETURNED = "returned"        # 已退回


class OrderLineItem(BaseModel):
    """
    订单行项目
    """
    def __init__(self, **kwargs):
        """
        初始化订单行项目
        
        Args:
            **kwargs: 行项目属性
        """
        super().__init__(**kwargs)
        
        # 产品信息
        self.product_id = kwargs.get("product_id", "")
        self.product_variant_id = kwargs.get("product_variant_id", "")
        self.sku = kwargs.get("sku", "")
        self.product_name = kwargs.get("product_name", "")
        self.product_description = kwargs.get("product_description", "")
        
        # 数量
        self.quantity = kwargs.get("quantity", 1)
        
        # 价格信息
        self.unit_price = kwargs.get("unit_price", 0.0)
        self.total_price = kwargs.get("total_price", 0.0)
        self.cost_price = kwargs.get("cost_price", 0.0)
        
        # 折扣信息
        self.discount_amount = kwargs.get("discount_amount", 0.0)
        self.discount_percentage = kwargs.get("discount_percentage", 0.0)
        
        # 税率信息
        self.tax_rate = kwargs.get("tax_rate", 0.0)
        self.tax_amount = kwargs.get("tax_amount", 0.0)
        
        # 行项目状态
        self.status = kwargs.get("status", "active")
        
        # 产品属性
        self.attributes = kwargs.get("attributes", {})
        
        # 履行状态
        self.fulfilled_quantity = kwargs.get("fulfilled_quantity", 0)
        self.backordered_quantity = kwargs.get("backordered_quantity", 0)
        
        # 计算总价
        if self.total_price == 0.0 and self.unit_price > 0 and self.quantity > 0:
            self.total_price = self.unit_price * self.quantity - self.discount_amount
        
        # 计算税额
        if self.tax_amount == 0.0 and self.tax_rate > 0:
            self.tax_amount = (self.unit_price * self.quantity - self.discount_amount) * (self.tax_rate / 100)
    
    def update_quantity(self, quantity: int) -> "OrderLineItem":
        """
        更新数量
        
        Args:
            quantity: 新数量
            
        Returns:
            OrderLineItem: 更新后的行项目
        """
        self.quantity = quantity
        self.recalculate()
        return self
    
    def update_unit_price(self, unit_price: float) -> "OrderLineItem":
        """
        更新单价
        
        Args:
            unit_price: 新单价
            
        Returns:
            OrderLineItem: 更新后的行项目
        """
        self.unit_price = unit_price
        self.recalculate()
        return self
    
    def apply_discount(self, discount_amount: float = None, discount_percentage: float = None) -> "OrderLineItem":
        """
        应用折扣
        
        Args:
            discount_amount: 折扣金额
            discount_percentage: 折扣百分比
            
        Returns:
            OrderLineItem: 更新后的行项目
        """
        if discount_amount is not None:
            self.discount_amount = discount_amount
        elif discount_percentage is not None:
            self.discount_percentage = discount_percentage
            self.discount_amount = (self.unit_price * self.quantity) * (discount_percentage / 100)
        
        self.recalculate()
        return self
    
    def update_tax_rate(self, tax_rate: float) -> "OrderLineItem":
        """
        更新税率
        
        Args:
            tax_rate: 新税率
            
        Returns:
            OrderLineItem: 更新后的行项目
        """
        self.tax_rate = tax_rate
        self.recalculate()
        return self
    
    def recalculate(self) -> None:
        """
        重新计算行项目金额
        """
        # 计算折扣金额
        if self.discount_percentage > 0:
            self.discount_amount = (self.unit_price * self.quantity) * (self.discount_percentage / 100)
        
        # 计算总价
        self.total_price = self.unit_price * self.quantity - self.discount_amount
        
        # 计算税额
        self.tax_amount = self.total_price * (self.tax_rate / 100)
    
    def get_subtotal(self) -> float:
        """
        获取小计（不含税）
        
        Returns:
            float: 小计金额
        """
        return self.total_price
    
    def get_total_with_tax(self) -> float:
        """
        获取含税总价
        
        Returns:
            float: 含税总价
        """
        return self.total_price + self.tax_amount
    
    def update_fulfillment(self, fulfilled_quantity: int, backordered_quantity: int = 0) -> "OrderLineItem":
        """
        更新履行状态
        
        Args:
            fulfilled_quantity: 已履行数量
            backordered_quantity: 延期交付数量
            
        Returns:
            OrderLineItem: 更新后的行项目
        """
        self.fulfilled_quantity = fulfilled_quantity
        self.backordered_quantity = backordered_quantity
        return self
    
    def is_fully_fulfilled(self) -> bool:
        """
        检查是否完全履行
        
        Returns:
            bool: 是否已完全履行
        """
        return self.fulfilled_quantity >= self.quantity


class ShippingAddress(BaseModel):
    """
    配送地址
    """
    def __init__(self, **kwargs):
        """
        初始化配送地址
        
        Args:
            **kwargs: 地址属性
        """
        super().__init__(**kwargs)
        
        # 收货人信息
        self.recipient_name = kwargs.get("recipient_name", "")
        self.phone = kwargs.get("phone", "")
        
        # 地址信息
        self.street = kwargs.get("street", "")
        self.street2 = kwargs.get("street2", "")
        self.city = kwargs.get("city", "")
        self.state = kwargs.get("state", "")
        self.postal_code = kwargs.get("postal_code", "")
        self.country = kwargs.get("country", "")
        
        # 地址类型
        self.address_type = kwargs.get("address_type", "shipping")
        
        # 是否为默认地址
        self.is_default = kwargs.get("is_default", False)
    
    def validate(self) -> bool:
        """
        验证地址信息
        
        Returns:
            bool: 是否有效
        """
        required_fields = [
            "recipient_name", "phone", "street", "city",
            "postal_code", "country"
        ]
        
        for field in required_fields:
            if not getattr(self, field, ""):
                return False
        
        return True


class PaymentInfo(BaseModel):
    """
    支付信息
    """
    def __init__(self, **kwargs):
        """
        初始化支付信息
        
        Args:
            **kwargs: 支付属性
        """
        super().__init__(**kwargs)
        
        # 支付方式
        self.payment_method = kwargs.get("payment_method", "")
        
        # 支付金额
        self.amount = kwargs.get("amount", 0.0)
        
        # 交易ID
        self.transaction_id = kwargs.get("transaction_id", "")
        
        # 支付状态
        self.status = kwargs.get("status", PaymentStatus.PENDING)
        
        # 支付时间
        self.payment_date = kwargs.get("payment_date", None)
        
        # 支付网关
        self.gateway = kwargs.get("gateway", "")
        
        # 支付详情
        self.details = kwargs.get("details", {})
    
    def update_status(self, status: PaymentStatus, transaction_id: str = None) -> "PaymentInfo":
        """
        更新支付状态
        
        Args:
            status: 新状态
            transaction_id: 交易ID
            
        Returns:
            PaymentInfo: 更新后的支付信息
        """
        self.status = status
        if transaction_id:
            self.transaction_id = transaction_id
        if status == PaymentStatus.PAID:
            self.payment_date = datetime.now()
        return self


class ShippingInfo(BaseModel):
    """
    物流信息
    """
    def __init__(self, **kwargs):
        """
        初始化物流信息
        
        Args:
            **kwargs: 物流属性
        """
        super().__init__(**kwargs)
        
        # 物流方式
        self.shipping_method = kwargs.get("shipping_method", "")
        
        # 物流费用
        self.shipping_cost = kwargs.get("shipping_cost", 0.0)
        
        # 物流公司
        self.carrier = kwargs.get("carrier", "")
        
        # 运单号
        self.tracking_number = kwargs.get("tracking_number", "")
        
        # 物流状态
        self.status = kwargs.get("status", ShippingStatus.PENDING)
        
        # 预计发货时间
        self.estimated_ship_date = kwargs.get("estimated_ship_date", None)
        
        # 预计送达时间
        self.estimated_delivery_date = kwargs.get("estimated_delivery_date", None)
        
        # 实际发货时间
        self.actual_ship_date = kwargs.get("actual_ship_date", None)
        
        # 实际送达时间
        self.actual_delivery_date = kwargs.get("actual_delivery_date", None)
        
        # 物流详情
        self.tracking_events = kwargs.get("tracking_events", [])
    
    def update_tracking(self, tracking_number: str, carrier: str) -> "ShippingInfo":
        """
        更新物流跟踪信息
        
        Args:
            tracking_number: 运单号
            carrier: 物流公司
            
        Returns:
            ShippingInfo: 更新后的物流信息
        """
        self.tracking_number = tracking_number
        self.carrier = carrier
        return self
    
    def update_status(self, status: ShippingStatus) -> "ShippingInfo":
        """
        更新物流状态
        
        Args:
            status: 新状态
            
        Returns:
            ShippingInfo: 更新后的物流信息
        """
        self.status = status
        
        # 更新对应时间
        now = datetime.now()
        if status == ShippingStatus.SHIPPED:
            self.actual_ship_date = now
        elif status == ShippingStatus.DELIVERED:
            self.actual_delivery_date = now
        
        return self
    
    def add_tracking_event(self, event_type: str, location: str, description: str) -> "ShippingInfo":
        """
        添加物流跟踪事件
        
        Args:
            event_type: 事件类型
            location: 地点
            description: 描述
            
        Returns:
            ShippingInfo: 更新后的物流信息
        """
        event = {
            "event_type": event_type,
            "location": location,
            "description": description,
            "timestamp": datetime.now()
        }
        self.tracking_events.append(event)
        return self


class Order(BaseModel, AuditableModel, TimestampedModel):
    """
    订单
    """
    def __init__(self, **kwargs):
        """
        初始化订单
        
        Args:
            **kwargs: 订单属性
        """
        # 调用父类构造函数
        BaseModel.__init__(self, **kwargs)
        AuditableModel.__init__(self, **kwargs)
        TimestampedModel.__init__(self, **kwargs)
        
        # 订单基本信息
        self.order_number = kwargs.get("order_number", "")
        self.customer_id = kwargs.get("customer_id", "")
        self.customer_name = kwargs.get("customer_name", "")
        
        # 订单状态
        self.status = kwargs.get("status", OrderStatus.DRAFT)
        
        # 订单行项目
        self.line_items = kwargs.get("line_items", [])
        
        # 地址信息
        self.shipping_address = kwargs.get("shipping_address", None)
        self.billing_address = kwargs.get("billing_address", None)
        
        # 支付信息
        self.payments = kwargs.get("payments", [])
        self.payment_status = kwargs.get("payment_status", PaymentStatus.PENDING)
        
        # 物流信息
        self.shipping_info = kwargs.get("shipping_info", None)
        
        # 金额信息
        self.subtotal = kwargs.get("subtotal", 0.0)
        self.discount_amount = kwargs.get("discount_amount", 0.0)
        self.tax_amount = kwargs.get("tax_amount", 0.0)
        self.shipping_amount = kwargs.get("shipping_amount", 0.0)
        self.total_amount = kwargs.get("total_amount", 0.0)
        
        # 备注
        self.notes = kwargs.get("notes", "")
        
        # 来源
        self.source = kwargs.get("source", "online")
        
        # 相关实体
        self.salesperson_id = kwargs.get("salesperson_id", "")
        self.enterprise_id = kwargs.get("enterprise_id", "")
        
        # 自动计算金额
        self.recalculate_totals()
    
    def add_line_item(self, line_item: OrderLineItem) -> "Order":
        """
        添加行项目
        
        Args:
            line_item: 订单行项目
            
        Returns:
            Order: 更新后的订单
        """
        self.line_items.append(line_item)
        self.recalculate_totals()
        return self
    
    def remove_line_item(self, line_item_id: str) -> "Order":
        """
        移除行项目
        
        Args:
            line_item_id: 行项目ID
            
        Returns:
            Order: 更新后的订单
        """
        self.line_items = [item for item in self.line_items if item.id != line_item_id]
        self.recalculate_totals()
        return self
    
    def update_line_item_quantity(self, line_item_id: str, quantity: int) -> "Order":
        """
        更新行项目数量
        
        Args:
            line_item_id: 行项目ID
            quantity: 新数量
            
        Returns:
            Order: 更新后的订单
        """
        for item in self.line_items:
            if item.id == line_item_id:
                item.update_quantity(quantity)
                break
        self.recalculate_totals()
        return self
    
    def apply_discount(self, discount_amount: float = None, discount_percentage: float = None) -> "Order":
        """
        应用订单级折扣
        
        Args:
            discount_amount: 折扣金额
            discount_percentage: 折扣百分比
            
        Returns:
            Order: 更新后的订单
        """
        if discount_amount is not None:
            self.discount_amount = discount_amount
        elif discount_percentage is not None:
            self.discount_amount = self.subtotal * (discount_percentage / 100)
        
        self.recalculate_totals()
        return self
    
    def add_payment(self, payment: PaymentInfo) -> "Order":
        """
        添加支付
        
        Args:
            payment: 支付信息
            
        Returns:
            Order: 更新后的订单
        """
        self.payments.append(payment)
        self.update_payment_status()
        return self
    
    def update_payment_status(self) -> "Order":
        """
        更新支付状态
        
        Returns:
            Order: 更新后的订单
        """
        if not self.payments:
            self.payment_status = PaymentStatus.PENDING
            return self
        
        # 计算已支付金额
        paid_amount = sum(p.amount for p in self.payments if p.status == PaymentStatus.PAID)
        
        # 更新支付状态
        if paid_amount >= self.total_amount:
            self.payment_status = PaymentStatus.PAID
        elif paid_amount > 0:
            self.payment_status = PaymentStatus.PARTIALLY_PAID
        else:
            self.payment_status = PaymentStatus.PENDING
        
        return self
    
    def update_status(self, status: OrderStatus) -> "Order":
        """
        更新订单状态
        
        Args:
            status: 新状态
            
        Returns:
            Order: 更新后的订单
        """
        self.status = status
        
        # 更新时间戳
        if status == OrderStatus.CONFIRMED:
            self.start_time = datetime.now()
        elif status in [OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.REFUNDED]:
            self.end_time = datetime.now()
        
        return self
    
    def recalculate_totals(self) -> None:
        """
        重新计算订单金额
        """
        # 重置金额
        self.subtotal = 0.0
        self.tax_amount = 0.0
        
        # 计算行项目金额
        for item in self.line_items:
            self.subtotal += item.get_subtotal()
            self.tax_amount += item.tax_amount
        
        # 计算总运费
        if self.shipping_info:
            self.shipping_amount = self.shipping_info.shipping_cost
        else:
            self.shipping_amount = 0.0
        
        # 计算总金额
        self.total_amount = self.subtotal - self.discount_amount + self.tax_amount + self.shipping_amount
    
    def get_total_quantity(self) -> int:
        """
        获取订单总数量
        
        Returns:
            int: 总数量
        """
        return sum(item.quantity for item in self.line_items)
    
    def get_fulfilled_quantity(self) -> int:
        """
        获取已履行数量
        
        Returns:
            int: 已履行数量
        """
        return sum(item.fulfilled_quantity for item in self.line_items)
    
    def is_fully_fulfilled(self) -> bool:
        """
        检查是否完全履行
        
        Returns:
            bool: 是否已完全履行
        """
        for item in self.line_items:
            if not item.is_fully_fulfilled():
                return False
        return True
    
    def get_product_ids(self) -> Set[str]:
        """
        获取订单中的产品ID集合
        
        Returns:
            set: 产品ID集合
        """
        return {item.product_id for item in self.line_items if item.product_id}


# 示例用法
if __name__ == "__main__":
    # 创建订单行项目
    item1 = OrderLineItem(
        product_id="prod-001",
        sku="PHONE-X-64",
        product_name="智能手机X 64GB",
        quantity=2,
        unit_price=5999.0,
        cost_price=3000.0,
        tax_rate=13
    )
    
    item2 = OrderLineItem(
        product_id="prod-002",
        sku="CASE-X",
        product_name="手机保护壳",
        quantity=1,
        unit_price=99.0,
        cost_price=50.0,
        tax_rate=13,
        discount_percentage=10
    )
    
    print(f"行项目1总价: {item1.get_total_with_tax()}")
    print(f"行项目2总价: {item2.get_total_with_tax()}")
    
    # 创建配送地址
    shipping_address = ShippingAddress(
        recipient_name="张三",
        phone="13800138000",
        street="科技路100号",
        city="深圳",
        state="广东",
        postal_code="518000",
        country="中国"
    )
    
    # 创建物流信息
    shipping_info = ShippingInfo(
        shipping_method="标准快递",
        shipping_cost=15.0,
        estimated_delivery_date=datetime.now()
    )
    
    # 创建订单
    order = Order(
        order_number="ORD-20240101-0001",
        customer_id="cust-001",
        customer_name="李四",
        shipping_address=shipping_address,
        billing_address=shipping_address,
        shipping_info=shipping_info,
        source="website"
    )
    
    # 添加行项目
    order.add_line_item(item1)
    order.add_line_item(item2)
    
    # 应用订单折扣
    order.apply_discount(discount_amount=100.0)
    
    print(f"订单编号: {order.order_number}")
    print(f"订单小计: {order.subtotal}")
    print(f"订单折扣: {order.discount_amount}")
    print(f"订单税额: {order.tax_amount}")
    print(f"订单运费: {order.shipping_amount}")
    print(f"订单总计: {order.total_amount}")
    
    # 更新订单状态
    order.update_status(OrderStatus.CONFIRMED)
    print(f"订单状态: {order.status}")
    
    # 添加支付
    payment = PaymentInfo(
        payment_method="支付宝",
        amount=order.total_amount,
        gateway="alipay",
        transaction_id="ALI1234567890"
    )
    payment.update_status(PaymentStatus.PAID)
    order.add_payment(payment)
    
    print(f"支付状态: {order.payment_status}")
    
    # 更新物流状态
    order.shipping_info.update_status(ShippingStatus.SHIPPED)
    order.shipping_info.update_tracking("SF1234567890", "顺丰速运")
    order.shipping_info.add_tracking_event("shipping", "深圳", "包裹已发出")
    
    print(f"物流状态: {order.shipping_info.status}")
    print(f"运单号: {order.shipping_info.tracking_number}")