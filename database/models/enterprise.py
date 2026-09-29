"""
企业相关数据模型
"""
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.orm import relationship

from database.models.base import BaseModel


class Enterprise(BaseModel):
    """
    企业模型
    """
    __tablename__ = "enterprises"
    
    # 基本信息
    enterprise_id = Column(String(50), unique=True, nullable=False, index=True, comment="企业ID")
    name = Column(String(255), nullable=False, comment="企业名称")
    type = Column(String(50), nullable=False, comment="企业类型: manufacturer, retailer, supplier")
    location = Column(String(255), comment="企业位置")
    industry = Column(String(100), comment="所属行业")
    founded_year = Column(Integer, comment="成立年份")
    
    # 财务信息
    capital = Column(Float, default=0.0, comment="初始资金")
    current_balance = Column(Float, default=0.0, comment="当前余额")
    revenue = Column(Float, default=0.0, comment="总收入")
    expenses = Column(Float, default=0.0, comment="总支出")
    profit = Column(Float, default=0.0, comment="利润")
    credit_score = Column(Float, default=0.0, comment="信用评分")
    
    # 资源和能力
    capacity = Column(Integer, default=0, comment="产能")
    warehouse_space = Column(Integer, default=0, comment="仓库空间")
    delivery_capacity = Column(Integer, default=0, comment="配送能力")
    
    # 业务信息
    products = relationship("Product", back_populates="enterprise", cascade="all, delete-orphan")
    suppliers = relationship("Supplier", back_populates="enterprise", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="enterprise", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="enterprise", cascade="all, delete-orphan")
    sales_orders = relationship("SalesOrder", back_populates="enterprise", cascade="all, delete-orphan")
    production_plans = relationship("ProductionPlan", back_populates="enterprise", cascade="all, delete-orphan")
    
    # 配置信息
    config = Column(JSON, default={}, comment="企业配置信息")
    
    # 状态信息
    is_active = Column(Boolean, default=True, comment="是否激活")
    
    def __repr__(self):
        return f"<Enterprise(id={self.id}, name={self.name}, type={self.type})>"


class Supplier(BaseModel):
    """
    供应商模型
    """
    __tablename__ = "suppliers"
    
    name = Column(String(255), nullable=False, comment="供应商名称")
    contact_info = Column(JSON, default={}, comment="联系方式")
    reliability_score = Column(Float, default=0.0, comment="可靠性评分")
    lead_time = Column(Integer, default=0, comment="交货周期")
    minimum_order_quantity = Column(Integer, default=0, comment="最小订单量")
    
    # 关联
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="所属企业ID")
    enterprise = relationship("Enterprise", back_populates="suppliers")
    
    def __repr__(self):
        return f"<Supplier(id={self.id}, name={self.name})>"


class Customer(BaseModel):
    """
    客户模型
    """
    __tablename__ = "customers"
    
    name = Column(String(255), nullable=False, comment="客户名称")
    contact_info = Column(JSON, default={}, comment="联系方式")
    credit_limit = Column(Float, default=0.0, comment="信用额度")
    order_frequency = Column(Float, default=0.0, comment="订单频率")
    
    # 关联
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="所属企业ID")
    enterprise = relationship("Enterprise", back_populates="customers")
    
    def __repr__(self):
        return f"<Customer(id={self.id}, name={self.name})>"


class ProductionPlan(BaseModel):
    """
    生产计划模型
    """
    __tablename__ = "production_plans"
    
    name = Column(String(255), nullable=False, comment="计划名称")
    product_id = Column(Integer, ForeignKey("products.id"), comment="产品ID")
    quantity = Column(Integer, nullable=False, comment="计划数量")
    start_date = Column(DateTime, nullable=False, comment="开始日期")
    end_date = Column(DateTime, nullable=False, comment="结束日期")
    progress = Column(Float, default=0.0, comment="完成进度")
    status = Column(String(50), default="pending", comment="状态")
    
    # 关联
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="所属企业ID")
    enterprise = relationship("Enterprise", back_populates="production_plans")
    product = relationship("Product")
    
    def __repr__(self):
        return f"<ProductionPlan(id={self.id}, name={self.name}, status={self.status})>"


class PurchaseOrder(BaseModel):
    """
    采购订单模型
    """
    __tablename__ = "purchase_orders"
    
    po_number = Column(String(100), unique=True, nullable=False, index=True, comment="采购订单号")
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), comment="供应商ID")
    total_amount = Column(Float, default=0.0, comment="总金额")
    status = Column(String(50), default="pending", comment="状态")
    expected_delivery_date = Column(DateTime, comment="预计交货日期")
    actual_delivery_date = Column(DateTime, comment="实际交货日期")
    
    # 关联
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="所属企业ID")
    enterprise = relationship("Enterprise", back_populates="purchase_orders")
    supplier = relationship("Supplier")
    line_items = relationship("PurchaseOrderLineItem", back_populates="purchase_order", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<PurchaseOrder(id={self.id}, po_number={self.po_number}, status={self.status})>"


class SalesOrder(BaseModel):
    """
    销售订单模型
    """
    __tablename__ = "sales_orders"
    
    order_number = Column(String(100), unique=True, nullable=False, index=True, comment="销售订单号")
    customer_id = Column(Integer, ForeignKey("customers.id"), comment="客户ID")
    total_amount = Column(Float, default=0.0, comment="总金额")
    status = Column(String(50), default="pending", comment="状态")
    expected_delivery_date = Column(DateTime, comment="预计交货日期")
    actual_delivery_date = Column(DateTime, comment="实际交货日期")
    
    # 关联
    enterprise_id = Column(Integer, ForeignKey("enterprises.id"), comment="所属企业ID")
    enterprise = relationship("Enterprise", back_populates="sales_orders")
    customer = relationship("Customer")
    line_items = relationship("SalesOrderLineItem", back_populates="sales_order", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<SalesOrder(id={self.id}, order_number={self.order_number}, status={self.status})>"


class PurchaseOrderLineItem(BaseModel):
    """
    采购订单项模型
    """
    __tablename__ = "purchase_order_line_items"
    
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), comment="采购订单ID")
    product_id = Column(Integer, ForeignKey("products.id"), comment="产品ID")
    quantity = Column(Integer, nullable=False, comment="数量")
    unit_price = Column(Float, nullable=False, comment="单价")
    total_price = Column(Float, nullable=False, comment="总价")
    
    # 关联
    purchase_order = relationship("PurchaseOrder", back_populates="line_items")
    product = relationship("Product")
    
    def __repr__(self):
        return f"<PurchaseOrderLineItem(id={self.id}, quantity={self.quantity}, total_price={self.total_price})>"


class SalesOrderLineItem(BaseModel):
    """
    销售订单项模型
    """
    __tablename__ = "sales_order_line_items"
    
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), comment="销售订单ID")
    product_id = Column(Integer, ForeignKey("products.id"), comment="产品ID")
    quantity = Column(Integer, nullable=False, comment="数量")
    unit_price = Column(Float, nullable=False, comment="单价")
    total_price = Column(Float, nullable=False, comment="总价")
    
    # 关联
    sales_order = relationship("SalesOrder", back_populates="line_items")
    product = relationship("Product")
    
    def __repr__(self):
        return f"<SalesOrderLineItem(id={self.id}, quantity={self.quantity}, total_price={self.total_price})>"