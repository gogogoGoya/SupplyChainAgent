"""
enterprise Related Data Model
"""
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.orm import relationship

from database.models.base import BaseModel


class Enterprise(BaseModel):
    """
    enterprise Model
        """
    __tablename__ = "enterprises"
    
    # Basic information
    enterprise_id = Column(String(50), unique=True, nullable=False, index=True, comment="enterpriseID")
    name = Column(String(255), nullable=False, comment="Name enterprise")
    type = Column(String(50), nullable=False, comment="Enterprise type: manufacturer, retailer, or supplier")
    location = Column(String(255), comment="Location enterprise")
    industry = Column(String(100), comment="Industry")
    founded_year = Column(Integer, comment="Year established")
    
    # Financial information
    capital = Column(Float, default=0.0, comment="Initial funding")
    current_balance = Column(Float, default=0.0, comment="Current balance")
    revenue = Column(Float, default=0.0, comment="Total income")
    expenses = Column(Float, default=0.0, comment="Total expenditure")
    profit = Column(Float, default=0.0, comment="Profit")
    credit_score = Column(Float, default=0.0, comment="Credit rating")
    
    # Resources and capacities
    capacity = Column(Integer, default=0, comment="Production capacity")
    warehouse_space = Column(Integer, default=0, comment="Warehouse space")
    delivery_capacity = Column(Integer, default=0, comment="Delivery capacity")
    
    # Operational information
    products = relationship("Product", back_populates="enterprise", cascade="all, delete-orphan")
    suppliers = relationship("Supplier", back_populates="enterprise", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="enterprise", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="enterprise", cascade="all, delete-orphan")
    sales_orders = relationship("SalesOrder", back_populates="enterprise", cascade="all, delete-orphan")
    production_plans = relationship("ProductionPlan", back_populates="enterprise", cascade="all, delete-orphan")
    
    # Configure Information
    config = Column(JSON, default={}, comment="enterprise Configuration Information")
    
    # Status Information
    is_active = Column(Boolean, default=True, comment="Activate")
    
    def __repr__(self):
        return f"<Enterprise(id={self.id}, name={self.name}, type={self.type})>"


class Supplier(BaseModel):
    """
    Vendor model
        """
    __tablename__ = "suppliers"
    
    name = Column(String(255), nullable=False, comment="Name of supplier")
    contact_info = Column(JSON, default={}, comment="Contact")
    reliability_score = Column(Float, default=0.0, comment="Reliability rating")
    lead_time = Column(Integer, default=0, comment="Delivery cycle")
    minimum_order_quantity = Column(Integer, default=0, comment="Minimum orders")
    
    # Association
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="From enterpriseID")
    enterprise = relationship("Enterprise", back_populates="suppliers")
    
    def __repr__(self):
        return f"<Supplier(id={self.id}, name={self.name})>"


class Customer(BaseModel):
    """
    Client model
        """
    __tablename__ = "customers"
    
    name = Column(String(255), nullable=False, comment="Client Name")
    contact_info = Column(JSON, default={}, comment="Contact")
    credit_limit = Column(Float, default=0.0, comment="Credit level")
    order_frequency = Column(Float, default=0.0, comment="Order frequency")
    
    # Association
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="From enterpriseID")
    enterprise = relationship("Enterprise", back_populates="customers")
    
    def __repr__(self):
        return f"<Customer(id={self.id}, name={self.name})>"


class ProductionPlan(BaseModel):
    """
    Production plan model
        """
    __tablename__ = "production_plans"
    
    name = Column(String(255), nullable=False, comment="Schedule Name")
    product_id = Column(Integer, ForeignKey("products.id"), comment="Product ID")
    quantity = Column(Integer, nullable=False, comment="Number planned")
    start_date = Column(DateTime, nullable=False, comment="Start date")
    end_date = Column(DateTime, nullable=False, comment="End Date")
    progress = Column(Float, default=0.0, comment="Completion progress")
    status = Column(String(50), default="pending", comment="Status")
    
    # Association
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="From enterpriseID")
    enterprise = relationship("Enterprise", back_populates="production_plans")
    product = relationship("Product")
    
    def __repr__(self):
        return f"<ProductionPlan(id={self.id}, name={self.name}, status={self.status})>"


class PurchaseOrder(BaseModel):
    """
    Purchase order model
        """
    __tablename__ = "purchase_orders"
    
    po_number = Column(String(100), unique=True, nullable=False, index=True, comment="Purchase order number")
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), comment="Vendor ID")
    total_amount = Column(Float, default=0.0, comment="Total amount")
    status = Column(String(50), default="pending", comment="Status")
    expected_delivery_date = Column(DateTime, comment="Projected delivery date")
    actual_delivery_date = Column(DateTime, comment="Actual delivery date")
    
    # Association
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="From enterpriseID")
    enterprise = relationship("Enterprise", back_populates="purchase_orders")
    supplier = relationship("Supplier")
    line_items = relationship("PurchaseOrderLineItem", back_populates="purchase_order", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<PurchaseOrder(id={self.id}, po_number={self.po_number}, status={self.status})>"


class SalesOrder(BaseModel):
    """
    Sales order model
        """
    __tablename__ = "sales_orders"
    
    order_number = Column(String(100), unique=True, nullable=False, index=True, comment="Sales order number")
    customer_id = Column(Integer, ForeignKey("customers.id"), comment="Client ID")
    total_amount = Column(Float, default=0.0, comment="Total amount")
    status = Column(String(50), default="pending", comment="Status")
    expected_delivery_date = Column(DateTime, comment="Projected delivery date")
    actual_delivery_date = Column(DateTime, comment="Actual delivery date")
    
    # Association
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="From enterpriseID")
    enterprise = relationship("Enterprise", back_populates="sales_orders")
    customer = relationship("Customer")
    line_items = relationship("SalesOrderLineItem", back_populates="sales_order", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<SalesOrder(id={self.id}, order_number={self.order_number}, status={self.status})>"


class PurchaseOrderLineItem(BaseModel):
    """
    Procurement order model
        """
    __tablename__ = "purchase_order_line_items"
    
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), comment="Purchase order ID")
    product_id = Column(Integer, ForeignKey("products.id"), comment="Product ID")
    quantity = Column(Integer, nullable=False, comment="Number")
    unit_price = Column(Float, nullable=False, comment="Unit price")
    total_price = Column(Float, nullable=False, comment="Total cost")
    
    # Association
    purchase_order = relationship("PurchaseOrder", back_populates="line_items")
    product = relationship("Product")
    
    def __repr__(self):
        return f"<PurchaseOrderLineItem(id={self.id}, quantity={self.quantity}, total_price={self.total_price})>"


class SalesOrderLineItem(BaseModel):
    """
    Sales order model
        """
    __tablename__ = "sales_order_line_items"
    
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), comment="Sales order ID")
    product_id = Column(Integer, ForeignKey("products.id"), comment="Product ID")
    quantity = Column(Integer, nullable=False, comment="Number")
    unit_price = Column(Float, nullable=False, comment="Unit price")
    total_price = Column(Float, nullable=False, comment="Total cost")
    
    # Association
    sales_order = relationship("SalesOrder", back_populates="line_items")
    product = relationship("Product")
    
    def __repr__(self):
        return f"<SalesOrderLineItem(id={self.id}, quantity={self.quantity}, total_price={self.total_price})>"
