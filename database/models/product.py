"""
Product-related database model

Database tables defining products, product categories, product attributes, etc.
"""

from typing import Dict, Any, List, Optional
from sqlalchemy import Column, String, Float, Integer, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from database.models.base import BaseModel


class ProductCategory(BaseModel):
    """
    List of product categories
    ProjectCategory in Data Model
        """
    __tablename__ = "product_categories"
    
    # Basic information
    name = Column(String, nullable=False)
    code = Column(String, index=True, unique=True)
    description = Column(String)
    
    # Classification structure
    parent_id = Column(String, ForeignKey("product_categories.id"), nullable=True)
    child_ids = Column(JSON, default=list)
    path = Column(JSON, default=list)
    level = Column(Integer, default=1)
    is_leaf = Column(Boolean, default=True)
    
    # Relations
    parent = relationship("ProductCategory", remote_side="ProductCategory.id", backref="children")


class ProductAttribute(BaseModel):
    """
    Product Properties Table
    ProjectAtribute in the data model
        """
    __tablename__ = "product_attributes"
    
    # Basic information
    name = Column(String, nullable=False)
    code = Column(String, index=True, unique=True)
    description = Column(String)
    
    # Properties Type
    type = Column(String, nullable=False)  # select, text, number, boolean, etc.
    required = Column(Boolean, default=False)
    
    # Options (for selftypes)
    options = Column(JSON, default=list)
    
    # Default value
    default_value = Column(JSON, nullable=True)


class Brand(BaseModel):
    """
    Brand
    Corresponds to Brand in the data model
        """
    __tablename__ = "brands"
    
    # Basic information
    name = Column(String, nullable=False, unique=True)
    code = Column(String, index=True, unique=True)
    description = Column(String)
    
    # Brand information
    logo_url = Column(String)
    website = Column(String)
    is_active = Column(Boolean, default=True)
    
    # Relations
    products = relationship("Product", back_populates="brand")


class Product(BaseModel):
    """
    List of products
    Correspond to Project in Data Model
        """
    __tablename__ = "products"
    
    # Basic information
    name = Column(String, nullable=False)
    code = Column(String, index=True)
    sku = Column(String, index=True, unique=True)
    
    # Price Information
    base_price = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    
    # Classification
    category_ids = Column(JSON, default=list)
    
    # Brand
    brand_id = Column(String, ForeignKey("brands.id"), nullable=True)
    brand = relationship("Brand", back_populates="products")
    
    # Description
    short_description = Column(String)
    long_description = Column(String)
    
    # Inventory status
    stock_status = Column(String, default="in_stock")
    
    # Variable Information
    has_variants = Column(Boolean, default=False)
    variant_attributes = Column(JSON, default=list)
    
    # Media
    images = Column(JSON, default=list)
    
    # Vendor information
    supplier_ids = Column(JSON, default=list)
    preferred_supplier_id = Column(String, nullable=True)
    
    # Product Properties
    attributes = Column(JSON, default=dict)
    
    # Version Information (to VersionedModel)
    version = Column(Integer, default=1)
    version_history = Column(JSON, default=list)
    
    # Relations
    variants = relationship("ProductVariant", back_populates="parent_product")


class ProductVariant(BaseModel):
    """
    Product variant table
    ProductVariant in the data model
        """
    __tablename__ = "product_variants"
    
    # Basic information
    name = Column(String, nullable=False)
    sku = Column(String, index=True, unique=True)
    
    # Parent
    parent_product_id = Column(String, ForeignKey("products.id"), nullable=False)
    parent_product = relationship("Product", back_populates="variants")
    
    # Price Information
    base_price = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    price_adjustment = Column(Float, default=0.0)
    price_adjustment_type = Column(String, default="absolute")
    
    # Variable Value
    variant_values = Column(JSON, default=dict)
    
    # Inventory status
    stock_status = Column(String, default="in_stock")
    
    # Media
    images = Column(JSON, default=list)
    
    # Actual prices (calculated fields, not stored in database)
    @property
    def actual_price(self) -> float:
        if self.price_adjustment_type == "absolute":
            return self.base_price + self.price_adjustment
        elif self.price_adjustment_type == "percentage":
            return self.base_price * (1 + self.price_adjustment / 100)
        return self.base_price
