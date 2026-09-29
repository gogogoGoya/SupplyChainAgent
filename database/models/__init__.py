"""
数据库模型模块

导出所有数据库模型
"""

# 基础模型
from database.models.base import Base, BaseModel

# 产品相关模型
from database.models.product import (
    ProductCategory,
    ProductAttribute,
    Product,
    ProductVariant,
    Brand
)

# 订单相关模型
from database.models.order import (
    Order,
    OrderLineItem,
    ShippingAddress,
    PaymentInfo,
    ShippingInfo
)

# 企业相关模型
from database.models.enterprise import (
    Enterprise,
    Supplier,
    Customer,
    ProductionPlan,
    PurchaseOrder,
    SalesOrder
)

__all__ = [
    # 基础
    'Base',
    'BaseModel',
    
    # 产品相关
    'ProductCategory',
    'ProductAttribute',
    'Product',
    'ProductVariant',
    'Brand',
    
    # 订单相关
    'Order',
    'OrderLineItem',
    'ShippingAddress',
    'PaymentInfo',
    'ShippingInfo',
    
    # 企业相关
    'Enterprise',
    'Supplier',
    'Customer',
    'ProductionPlan',
    'PurchaseOrder',
    'SalesOrder'
]