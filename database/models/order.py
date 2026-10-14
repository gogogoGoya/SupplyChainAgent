"""
Model of data related to orders
"""
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.orm import relationship

from database.models.base import BaseModel


class Order(BaseModel):
    """
    Order Model
        """
    __tablename__ = "orders"
    
    # Order Basic Information
    order_number = Column(String(100), unique=True, nullable=False, index=True, comment="Order number")
    order_type = Column(String(50), nullable=False, comment="Order type:")
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, comment="Client ID")
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, comment="Vendor ID")
    
    # Order amount information
    subtotal = Column(Float, default=0.0, comment="Subtotal")
    tax = Column(Float, default=0.0, comment="Taxes and charges")
    shipping_fee = Column(Float, default=0.0, comment="Freight")
    discount = Column(Float, default=0.0, comment="Discount amount")
    total_amount = Column(Float, default=0.0, comment="Total amount")
    
    # Order Status
    status = Column(String(50), default="pending", comment="Ordering, obtaining, shipping,")
    payment_status = Column(String(50), default="unpaid", comment="Payment status: unpaid, paid, partially_paid, paid")
    
    # Time Information
    order_date = Column(DateTime, default=func.now(), comment="Next Time")
    expected_delivery_date = Column(DateTime, comment="Projected delivery date")
    actual_delivery_date = Column(DateTime, comment="Actual delivery date")
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now(), comment="Last update time")
    
    # Association
    shipping_address_id = Column(Integer, ForeignKey("shipping_addresses.id"), comment="Distribution Address ID")
    billing_address_id = Column(Integer, ForeignKey("shipping_addresses.id"), comment="Billing address ID")
    payment_info_id = Column(Integer, ForeignKey("payment_infos.id"), comment="Payment Information ID")
    shipping_info_id = Column(Integer, ForeignKey("shipping_infos.id"), comment="Logistics Information ID")
    
    # Relations
    line_items = relationship("OrderLineItem", back_populates="order", cascade="all, delete-orphan")
    shipping_address = relationship("ShippingAddress", foreign_keys=[shipping_address_id])
    billing_address = relationship("ShippingAddress", foreign_keys=[billing_address_id])
    payment_info = relationship("PaymentInfo")
    shipping_info = relationship("ShippingInfo")
    customer = relationship("Customer")
    supplier = relationship("Supplier")
    
    # Other information
    notes = Column(Text, comment="Remarks to Orders")
    tracking_number = Column(String(100), comment="Logistics Tracker")
    
    def __repr__(self):
        return f"<Order(id={self.id}, order_number={self.order_number}, status={self.status})>"


class OrderLineItem(BaseModel):
    """
    Order line project model
        """
    __tablename__ = "order_line_items"
    
    # Basic information
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, comment="Order ID")
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, comment="Product ID")
    product_variant_id = Column(Integer, ForeignKey("product_variants.id"), nullable=True, comment="Product variant ID")
    
    # Quantity and price
    quantity = Column(Integer, nullable=False, default=1, comment="Number")
    unit_price = Column(Float, nullable=False, default=0.0, comment="Unit price")
    line_total = Column(Float, nullable=False, default=0.0, comment="Total line price")
    
    # Product information snapshot
    product_name = Column(String(255), nullable=False, comment="Product Name Snapshot")
    product_description = Column(Text, comment="Product Description Snapshot")
    product_attributes = Column(JSON, default={}, comment="Product Properties Snapshot")
    
    # Relations
    order = relationship("Order", back_populates="line_items")
    product = relationship("Product")
    product_variant = relationship("ProductVariant")
    
    def __repr__(self):
        return f"<OrderLineItem(id={self.id}, product_id={self.product_id}, quantity={self.quantity})>"


class ShippingAddress(BaseModel):
    """
    Distribution Address Model
        """
    __tablename__ = "shipping_addresses"
    
    # Chile
    recipient_name = Column(String(255), nullable=False, comment="Recipient Name")
    phone_number = Column(String(50), nullable=False, comment="Telephone number")
    address_line1 = Column(String(255), nullable=False, comment="Address first line")
    address_line2 = Column(String(255), comment="Address Line 2")
    city = Column(String(100), nullable=False, comment="Urban")
    state = Column(String(100), comment="State/provincial")
    postal_code = Column(String(50), nullable=False, comment="Postal Code")
    country = Column(String(100), nullable=False, comment="National")
    
    # Address Type
    address_type = Column(String(50), default="shipping", comment="Address type: shipping, billing")
    is_default = Column(Boolean, default=False, comment="Whether to Default Address")
    
    # Association Information
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, comment="Client ID")
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=True, comment="enterpriseID")
    
    # Relations
    customer = relationship("Customer")
    enterprise = relationship("Enterprise")
    
    def __repr__(self):
        return f"<ShippingAddress(id={self.id}, recipient={self.recipient_name}, city={self.city})>"


class PaymentInfo(BaseModel):
    """
    Payment information model
        """
    __tablename__ = "payment_infos"
    
    # Payment Basic Information
    payment_method = Column(String(50), nullable=False, comment="Method of payment: credit_card, paypal, bank_transfer, etc.")
    transaction_id = Column(String(100), unique=True, index=True, comment="Transaction ID")
    payment_date = Column(DateTime, default=func.now(), comment="Payment Time")
    amount = Column(Float, nullable=False, default=0.0, comment="Amount paid")
    payment_status = Column(String(50), default="pending", comment="Paying, paid, paid")
    
    # Details of payments (different according to the mode of payment)
    payment_details = Column(JSON, default={}, comment="Details of Payments")
    
    # Association Information
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, comment="Client ID")
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), nullable=True, comment="enterpriseID")
    
    # Relations
    customer = relationship("Customer")
    enterprise = relationship("Enterprise")
    
    def __repr__(self):
        return f"<PaymentInfo(id={self.id}, method={self.payment_method}, status={self.payment_status})>"


class ShippingInfo(BaseModel):
    """
    Logistics information model
        """
    __tablename__ = "shipping_infos"
    
    # Logistics Basic Information
    carrier = Column(String(100), comment="Logistics")
    tracking_number = Column(String(100), unique=True, index=True, comment="Logistics Tracker")
    shipping_method = Column(String(100), comment="Distribution Method")
    shipping_status = Column(String(50), default="pending", comment="Logistics state: pending, shipping, in_transit,")
    
    # Time Information
    ship_date = Column(DateTime, comment="Delivery time")
    estimated_delivery_date = Column(DateTime, comment="Estimated time of delivery")
    actual_delivery_date = Column(DateTime, comment="Actual time of delivery")
    
    # Logistics details
    shipping_cost = Column(Float, default=0.0, comment="Logistics costs")
    delivery_instructions = Column(Text, comment="Distribution instructions")
    
    # History of Logistics Events
    delivery_history = Column(JSON, default=[], comment="Distribution of historical events")
    
    def __repr__(self):
        return f"<ShippingInfo(id={self.id}, carrier={self.carrier}, tracking={self.tracking_number})>"
