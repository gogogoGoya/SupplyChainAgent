"""
产品相关数据库模型

定义产品、产品类别、产品属性等数据库表
"""

from typing import Dict, Any, List, Optional
from sqlalchemy import Column, String, Float, Integer, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from database.models.base import BaseModel


class ProductCategory(BaseModel):
    """
    产品类别表
    对应于数据模型中的ProductCategory
    """
    __tablename__ = "product_categories"
    
    # 基本信息
    name = Column(String, nullable=False)
    code = Column(String, index=True, unique=True)
    description = Column(String)
    
    # 分类结构
    parent_id = Column(String, ForeignKey("product_categories.id"), nullable=True)
    child_ids = Column(JSON, default=list)
    path = Column(JSON, default=list)
    level = Column(Integer, default=1)
    is_leaf = Column(Boolean, default=True)
    
    # 关系
    parent = relationship("ProductCategory", remote_side="ProductCategory.id", backref="children")


class ProductAttribute(BaseModel):
    """
    产品属性表
    对应于数据模型中的ProductAttribute
    """
    __tablename__ = "product_attributes"
    
    # 基本信息
    name = Column(String, nullable=False)
    code = Column(String, index=True, unique=True)
    description = Column(String)
    
    # 属性类型
    type = Column(String, nullable=False)  # select, text, number, boolean, etc.
    required = Column(Boolean, default=False)
    
    # 选项（用于select类型）
    options = Column(JSON, default=list)
    
    # 默认值
    default_value = Column(JSON, nullable=True)


class Brand(BaseModel):
    """
    品牌表
    对应于数据模型中的Brand
    """
    __tablename__ = "brands"
    
    # 基本信息
    name = Column(String, nullable=False, unique=True)
    code = Column(String, index=True, unique=True)
    description = Column(String)
    
    # 品牌信息
    logo_url = Column(String)
    website = Column(String)
    is_active = Column(Boolean, default=True)
    
    # 关系
    products = relationship("Product", back_populates="brand")


class Product(BaseModel):
    """
    产品表
    对应于数据模型中的Product
    """
    __tablename__ = "products"
    
    # 基本信息
    name = Column(String, nullable=False)
    code = Column(String, index=True)
    sku = Column(String, index=True, unique=True)
    
    # 价格信息
    base_price = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    
    # 分类
    category_ids = Column(JSON, default=list)
    
    # 品牌
    brand_id = Column(String, ForeignKey("brands.id"), nullable=True)
    brand = relationship("Brand", back_populates="products")
    
    # 描述
    short_description = Column(String)
    long_description = Column(String)
    
    # 库存状态
    stock_status = Column(String, default="in_stock")
    
    # 变体信息
    has_variants = Column(Boolean, default=False)
    variant_attributes = Column(JSON, default=list)
    
    # 媒体
    images = Column(JSON, default=list)
    
    # 供应商信息
    supplier_ids = Column(JSON, default=list)
    preferred_supplier_id = Column(String, nullable=True)
    
    # 产品属性
    attributes = Column(JSON, default=dict)
    
    # 版本信息（对应VersionedModel）
    version = Column(Integer, default=1)
    version_history = Column(JSON, default=list)
    
    # 关系
    variants = relationship("ProductVariant", back_populates="parent_product")


class ProductVariant(BaseModel):
    """
    产品变体表
    对应于数据模型中的ProductVariant
    """
    __tablename__ = "product_variants"
    
    # 基本信息
    name = Column(String, nullable=False)
    sku = Column(String, index=True, unique=True)
    
    # 父产品
    parent_product_id = Column(String, ForeignKey("products.id"), nullable=False)
    parent_product = relationship("Product", back_populates="variants")
    
    # 价格信息
    base_price = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    price_adjustment = Column(Float, default=0.0)
    price_adjustment_type = Column(String, default="absolute")
    
    # 变体值
    variant_values = Column(JSON, default=dict)
    
    # 库存状态
    stock_status = Column(String, default="in_stock")
    
    # 媒体
    images = Column(JSON, default=list)
    
    # 实际价格（计算字段，不存储在数据库中）
    @property
    def actual_price(self) -> float:
        if self.price_adjustment_type == "absolute":
            return self.base_price + self.price_adjustment
        elif self.price_adjustment_type == "percentage":
            return self.base_price * (1 + self.price_adjustment / 100)
        return self.base_price