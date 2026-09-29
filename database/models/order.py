"""
订单相关数据模型
"""
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.orm import relationship

from database.models.base import BaseModel


class Order(BaseModel):
    """
    订单模型
    """
    __tablename__ = "orders"
    
    # 订单基本信息
    order_number = Column(String(100), unique=True, nullable=False, index=True, comment="订单编号")
    order_type = Column(String(50), nullable=False, comment="订单类型: sales, purchase")
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, comment="客户ID")
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, comment="供应商ID")
    
    # 订单金额信息
    subtotal = Column(Float, default=0.0, comment="小计金额")
    tax = Column(Float, default=0.0, comment="税费")
    shipping_fee = Column(Float, default=0.0, comment="运费")
    discount = Column(Float, default=0.0, comment="折扣金额")
    total_amount = Column(Float, default=0.0, comment="总金额")
    
    # 订单状态
    status = Column(String(50), default="pending", comment="订单状态: pending, processing, shipped, delivered, cancelled")
    payment_status = Column(String(50), default="unpaid", comment="支付状态: unpaid, paid, partially_paid, refunded")
    
    # 时间信息
    order_date = Column(DateTime, default=func.now(), comment="下单时间")
    expected_delivery_date = Column(DateTime, comment="预计交货日期")
    actual_delivery_date = Column(DateTime, comment="实际交货日期")
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now(), comment="最后更新时间")
    
    # 关联
    shipping_address_id = Column(Integer, ForeignKey("shipping_addresses.id"), comment="配送地址ID")
    billing_address_id = Column(Integer, ForeignKey("shipping_addresses.id"), comment="账单地址ID")
    payment_info_id = Column(Integer, ForeignKey("payment_infos.id"), comment="支付信息ID")
    shipping_info_id = Column(Integer, ForeignKey("shipping_infos.id"), comment="物流信息ID")
    
    # 关系
    line_items = relationship("OrderLineItem", back_populates="order", cascade="all, delete-orphan")
    shipping_address = relationship("ShippingAddress", foreign_keys=[shipping_address_id])
    billing_address = relationship("ShippingAddress", foreign_keys=[billing_address_id])
    payment_info = relationship("PaymentInfo")
    shipping_info = relationship("ShippingInfo")
    customer = relationship("Customer")
    supplier = relationship("Supplier")
    
    # 其他信息
    notes = Column(Text, comment="订单备注")
    tracking_number = Column(String(100), comment="物流追踪号")
    
    def __repr__(self):
        return f"<Order(id={self.id}, order_number={self.order_number}, status={self.status})>"


class OrderLineItem(BaseModel):
    """
    订单行项目模型
    """
    __tablename__ = "order_line_items"
    
    # 基本信息
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, comment="订单ID")
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, comment="产品ID")
    product_variant_id = Column(Integer, ForeignKey("product_variants.id"), nullable=True, comment="产品变体ID")
    
    # 数量和价格
    quantity = Column(Integer, nullable=False, default=1, comment="数量")
    unit_price = Column(Float, nullable=False, default=0.0, comment="单价")
    line_total = Column(Float, nullable=False, default=0.0, comment="行项目总价")
    
    # 产品信息快照
    product_name = Column(String(255), nullable=False, comment="产品名称快照")
    product_description = Column(Text, comment="产品描述快照")
    product_attributes = Column(JSON, default={}, comment="产品属性快照")
    
    # 关系
    order = relationship("Order", back_populates="line_items")
    product = relationship("Product")
    product_variant = relationship("ProductVariant")
    
    def __repr__(self):
        return f"<OrderLineItem(id={self.id}, product_id={self.product_id}, quantity={self.quantity})>"


class ShippingAddress(BaseModel):
    """
    配送地址模型
    """
    __tablename__ = "shipping_addresses"
    
    # 地址信息
    recipient_name = Column(String(255), nullable=False, comment="收件人姓名")
    phone_number = Column(String(50), nullable=False, comment="电话号码")
    address_line1 = Column(String(255), nullable=False, comment="地址第一行")
    address_line2 = Column(String(255), comment="地址第二行")
    city = Column(String(100), nullable=False, comment="城市")
    state = Column(String(100), comment="州/省")
    postal_code = Column(String(50), nullable=False, comment="邮政编码")
    country = Column(String(100), nullable=False, comment="国家")
    
    # 地址类型
    address_type = Column(String(50), default="shipping", comment="地址类型: shipping, billing")
    is_default = Column(Boolean, default=False, comment="是否默认地址")
    
    # 关联信息
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, comment="客户ID")
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=True, comment="企业ID")
    
    # 关系
    customer = relationship("Customer")
    enterprise = relationship("Enterprise")
    
    def __repr__(self):
        return f"<ShippingAddress(id={self.id}, recipient={self.recipient_name}, city={self.city})>"


class PaymentInfo(BaseModel):
    """
    支付信息模型
    """
    __tablename__ = "payment_infos"
    
    # 支付基本信息
    payment_method = Column(String(50), nullable=False, comment="支付方式: credit_card, paypal, bank_transfer, etc.")
    transaction_id = Column(String(100), unique=True, index=True, comment="交易ID")
    payment_date = Column(DateTime, default=func.now(), comment="支付时间")
    amount = Column(Float, nullable=False, default=0.0, comment="支付金额")
    payment_status = Column(String(50), default="pending", comment="支付状态: pending, completed, failed, refunded")
    
    # 支付详情（根据支付方式不同而不同）
    payment_details = Column(JSON, default={}, comment="支付详情")
    
    # 关联信息
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, comment="客户ID")
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=True, comment="企业ID")
    
    # 关系
    customer = relationship("Customer")
    enterprise = relationship("Enterprise")
    
    def __repr__(self):
        return f"<PaymentInfo(id={self.id}, method={self.payment_method}, status={self.payment_status})>"


class ShippingInfo(BaseModel):
    """
    物流信息模型
    """
    __tablename__ = "shipping_infos"
    
    # 物流基本信息
    carrier = Column(String(100), comment="物流公司")
    tracking_number = Column(String(100), unique=True, index=True, comment="物流追踪号")
    shipping_method = Column(String(100), comment="配送方式")
    shipping_status = Column(String(50), default="pending", comment="物流状态: pending, shipped, in_transit, delivered, returned")
    
    # 时间信息
    ship_date = Column(DateTime, comment="发货时间")
    estimated_delivery_date = Column(DateTime, comment="预计送达时间")
    actual_delivery_date = Column(DateTime, comment="实际送达时间")
    
    # 物流详情
    shipping_cost = Column(Float, default=0.0, comment="物流费用")
    delivery_instructions = Column(Text, comment="配送说明")
    
    # 物流事件历史
    delivery_history = Column(JSON, default=[], comment="配送历史事件")
    
    def __repr__(self):
        return f"<ShippingInfo(id={self.id}, carrier={self.carrier}, tracking={self.tracking_number})>"