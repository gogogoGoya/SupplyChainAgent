"""
数据模型模块

包含系统中所有核心数据模型的定义
"""

# 从基础模型导入
from supply_chain_agent.data_models.base_model import (
    BaseModel,
    NamedModel,
    AuditableModel,
    VersionedModel,
    TimestampedModel
)

# 从产品模型导入
from supply_chain_agent.data_models.product import (
    ProductCategory,
    ProductAttribute,
    Product,
    ProductVariant,
    Brand
)

# 从订单模型导入
from supply_chain_agent.data_models.order import (
    OrderStatus,
    PaymentStatus,
    ShippingStatus,
    OrderLineItem,
    ShippingAddress,
    PaymentInfo,
    ShippingInfo,
    Order
)

# 导出列表
__all__ = [
    # 基础模型
    "BaseModel",
    "NamedModel",
    "AuditableModel",
    "VersionedModel",
    "TimestampedModel",
    
    # 产品模型
    "ProductCategory",
    "ProductAttribute",
    "Product",
    "ProductVariant",
    "Brand",
    
    # 订单模型
    "OrderStatus",
    "PaymentStatus",
    "ShippingStatus",
    "OrderLineItem",
    "ShippingAddress",
    "PaymentInfo",
    "ShippingInfo",
    "Order"
]