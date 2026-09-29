"""
产品数据模型模块

定义产品、产品变体等相关数据模型
"""

from typing import Dict, Any, Optional, List, Set
from datetime import datetime

from supply_chain_agent.data_models.base_model import NamedModel, VersionedModel


class ProductCategory(NamedModel):
    """
    产品类别
    """
    def __init__(self, **kwargs):
        """
        初始化产品类别
        
        Args:
            **kwargs: 类别属性
        """
        super().__init__(**kwargs)
        
        # 父类别ID
        self.parent_id = kwargs.get("parent_id", None)
        
        # 子类别ID列表
        self.child_ids = kwargs.get("child_ids", [])
        
        # 分类路径
        self.path = kwargs.get("path", [])
        
        # 级别
        self.level = kwargs.get("level", 1)
        
        # 是否为叶节点
        self.is_leaf = kwargs.get("is_leaf", True)
    
    def set_parent(self, parent_id: str) -> "ProductCategory":
        """
        设置父类别
        
        Args:
            parent_id: 父类别ID
            
        Returns:
            ProductCategory: 更新后的类别实例
        """
        self.parent_id = parent_id
        self.is_leaf = False
        return self
    
    def add_child(self, child_id: str) -> "ProductCategory":
        """
        添加子类别
        
        Args:
            child_id: 子类别ID
            
        Returns:
            ProductCategory: 更新后的类别实例
        """
        if child_id not in self.child_ids:
            self.child_ids.append(child_id)
            self.is_leaf = False
        return self
    
    def remove_child(self, child_id: str) -> "ProductCategory":
        """
        移除子类别
        
        Args:
            child_id: 子类别ID
            
        Returns:
            ProductCategory: 更新后的类别实例
        """
        if child_id in self.child_ids:
            self.child_ids.remove(child_id)
            # 如果没有子类别了，设置为叶节点
            if not self.child_ids:
                self.is_leaf = True
        return self
    
    def update_path(self, path: List[str]) -> "ProductCategory":
        """
        更新分类路径
        
        Args:
            path: 分类路径列表
            
        Returns:
            ProductCategory: 更新后的类别实例
        """
        self.path = path
        self.level = len(path)
        return self


class ProductAttribute(NamedModel):
    """
    产品属性定义
    """
    def __init__(self, **kwargs):
        """
        初始化产品属性
        
        Args:
            **kwargs: 属性定义
        """
        super().__init__(**kwargs)
        
        # 属性类型
        self.type = kwargs.get("type", "string")  # string, number, boolean, date, select, multi-select
        
        # 默认值
        self.default_value = kwargs.get("default_value", None)
        
        # 是否必填
        self.required = kwargs.get("required", False)
        
        # 是否可搜索
        self.searchable = kwargs.get("searchable", True)
        
        # 是否可过滤
        self.filterable = kwargs.get("filterable", True)
        
        # 选项列表（用于select和multi-select类型）
        self.options = kwargs.get("options", [])
        
        # 单位
        self.unit = kwargs.get("unit", "")
        
        # 排序权重
        self.sort_order = kwargs.get("sort_order", 0)
    
    def add_option(self, value: str, label: str = None) -> "ProductAttribute":
        """
        添加选项
        
        Args:
            value: 选项值
            label: 选项标签
            
        Returns:
            ProductAttribute: 更新后的属性实例
        """
        option = {"value": value}
        if label:
            option["label"] = label
        
        # 检查是否已存在
        for existing_option in self.options:
            if existing_option["value"] == value:
                return self
        
        self.options.append(option)
        return self
    
    def validate_value(self, value: Any) -> bool:
        """
        验证属性值
        
        Args:
            value: 属性值
            
        Returns:
            bool: 是否有效
        """
        # 检查必填
        if self.required and value is None:
            return False
        
        # 检查类型
        if value is not None:
            if self.type == "string" and not isinstance(value, str):
                return False
            elif self.type == "number" and not isinstance(value, (int, float)):
                return False
            elif self.type == "boolean" and not isinstance(value, bool):
                return False
            elif self.type == "date" and not isinstance(value, (datetime, str, float)):
                return False
            elif self.type == "select" and value not in [opt["value"] for opt in self.options]:
                return False
            elif self.type == "multi-select" and isinstance(value, list):
                for item in value:
                    if item not in [opt["value"] for opt in self.options]:
                        return False
        
        return True


class Product(NamedModel, VersionedModel):
    """
    产品主数据
    """
    def __init__(self, **kwargs):
        """
        初始化产品
        
        Args:
            **kwargs: 产品属性
        """
        # 调用父类构造函数
        NamedModel.__init__(self, **kwargs)
        VersionedModel.__init__(self, **kwargs)
        
        # 产品基本信息
        self.sku = kwargs.get("sku", "")  # 库存单位编码
        self.upc = kwargs.get("upc", "")  # 通用产品代码
        self.ean = kwargs.get("ean", "")  # 欧洲商品编号
        
        # 分类信息
        self.category_ids = kwargs.get("category_ids", [])
        
        # 品牌
        self.brand_id = kwargs.get("brand_id", "")
        self.brand_name = kwargs.get("brand_name", "")
        
        # 价格信息
        self.base_price = kwargs.get("base_price", 0.0)
        self.cost_price = kwargs.get("cost_price", 0.0)
        
        # 库存信息
        self.stock_status = kwargs.get("stock_status", "in_stock")  # in_stock, out_of_stock, low_stock
        self.min_stock_level = kwargs.get("min_stock_level", 0)
        self.reorder_level = kwargs.get("reorder_level", 0)
        
        # 产品详情
        self.short_description = kwargs.get("short_description", "")
        self.long_description = kwargs.get("long_description", "")
        
        # 媒体信息
        self.images = kwargs.get("images", [])
        self.videos = kwargs.get("videos", [])
        
        # 产品属性
        self.attributes = kwargs.get("attributes", {})
        
        # 变体信息
        self.has_variants = kwargs.get("has_variants", False)
        self.variant_attributes = kwargs.get("variant_attributes", [])  # 变体属性名称列表
        self.variant_ids = kwargs.get("variant_ids", [])  # 变体产品ID列表
        
        # 关联产品
        self.related_product_ids = kwargs.get("related_product_ids", [])
        self.cross_sell_ids = kwargs.get("cross_sell_ids", [])
        self.up_sell_ids = kwargs.get("up_sell_ids", [])
        
        # 重量和尺寸
        self.weight = kwargs.get("weight", 0.0)
        self.weight_unit = kwargs.get("weight_unit", "kg")
        self.length = kwargs.get("length", 0.0)
        self.width = kwargs.get("width", 0.0)
        self.height = kwargs.get("height", 0.0)
        self.dimension_unit = kwargs.get("dimension_unit", "cm")
        
        # 包装信息
        self.packaging_type = kwargs.get("packaging_type", "")
        self.packaging_quantity = kwargs.get("packaging_quantity", 1)
        
        # 可用性
        self.is_active = kwargs.get("is_active", True)
        self.is_featured = kwargs.get("is_featured", False)
        self.is_new = kwargs.get("is_new", False)
        
        # 税信息
        self.tax_class = kwargs.get("tax_class", "standard")
        
        # 供应商信息
        self.supplier_ids = kwargs.get("supplier_ids", [])
        self.preferred_supplier_id = kwargs.get("preferred_supplier_id", "")
    
    def add_category(self, category_id: str) -> "Product":
        """
        添加分类
        
        Args:
            category_id: 分类ID
            
        Returns:
            Product: 更新后的产品实例
        """
        if category_id not in self.category_ids:
            self.category_ids.append(category_id)
        return self
    
    def remove_category(self, category_id: str) -> "Product":
        """
        移除分类
        
        Args:
            category_id: 分类ID
            
        Returns:
            Product: 更新后的产品实例
        """
        if category_id in self.category_ids:
            self.category_ids.remove(category_id)
        return self
    
    def update_price(self, base_price: float, cost_price: float = None) -> "Product":
        """
        更新价格
        
        Args:
            base_price: 基础价格
            cost_price: 成本价格（可选）
            
        Returns:
            Product: 更新后的产品实例
        """
        self.base_price = base_price
        if cost_price is not None:
            self.cost_price = cost_price
        return self
    
    def update_stock_status(self, status: str) -> "Product":
        """
        更新库存状态
        
        Args:
            status: 库存状态
            
        Returns:
            Product: 更新后的产品实例
        """
        valid_statuses = ["in_stock", "out_of_stock", "low_stock"]
        if status in valid_statuses:
            self.stock_status = status
        return self
    
    def set_attribute(self, name: str, value: Any) -> "Product":
        """
        设置产品属性
        
        Args:
            name: 属性名称
            value: 属性值
            
        Returns:
            Product: 更新后的产品实例
        """
        self.attributes[name] = value
        return self
    
    def get_attribute(self, name: str, default: Any = None) -> Any:
        """
        获取产品属性
        
        Args:
            name: 属性名称
            default: 默认值
            
        Returns:
            Any: 属性值或默认值
        """
        return self.attributes.get(name, default)
    
    def add_image(self, image_url: str, is_primary: bool = False) -> "Product":
        """
        添加产品图片
        
        Args:
            image_url: 图片URL
            is_primary: 是否为主图
            
        Returns:
            Product: 更新后的产品实例
        """
        image = {
            "url": image_url,
            "is_primary": is_primary,
            "order": len(self.images)
        }
        
        # 如果设置为主图，取消其他图片的主图标记
        if is_primary:
            for img in self.images:
                img["is_primary"] = False
        
        self.images.append(image)
        return self
    
    def add_variant(self, variant_id: str) -> "Product":
        """
        添加产品变体
        
        Args:
            variant_id: 变体产品ID
            
        Returns:
            Product: 更新后的产品实例
        """
        if variant_id not in self.variant_ids:
            self.variant_ids.append(variant_id)
            self.has_variants = True
        return self
    
    def add_supplier(self, supplier_id: str, is_preferred: bool = False) -> "Product":
        """
        添加供应商
        
        Args:
            supplier_id: 供应商ID
            is_preferred: 是否为首选供应商
            
        Returns:
            Product: 更新后的产品实例
        """
        if supplier_id not in self.supplier_ids:
            self.supplier_ids.append(supplier_id)
        
        if is_preferred:
            self.preferred_supplier_id = supplier_id
        
        return self
    
    def toggle_active(self) -> "Product":
        """
        切换产品状态
        
        Returns:
            Product: 更新后的产品实例
        """
        self.is_active = not self.is_active
        return self


class ProductVariant(Product):
    """
    产品变体
    """
    def __init__(self, **kwargs):
        """
        初始化产品变体
        
        Args:
            **kwargs: 变体属性
        """
        super().__init__(**kwargs)
        
        # 父产品ID
        self.parent_product_id = kwargs.get("parent_product_id", "")
        
        # 变体属性组合
        self.variant_values = kwargs.get("variant_values", {})  # 属性名: 属性值
        
        # 变体特有价格差异
        self.price_adjustment = kwargs.get("price_adjustment", 0.0)
        self.price_adjustment_type = kwargs.get("price_adjustment_type", "absolute")  # absolute, percentage
        
        # 实际价格（计算得出）
        self.actual_price = self._calculate_actual_price()
    
    def _calculate_actual_price(self) -> float:
        """
        计算实际价格
        
        Returns:
            float: 实际价格
        """
        if self.price_adjustment_type == "absolute":
            return self.base_price + self.price_adjustment
        elif self.price_adjustment_type == "percentage":
            return self.base_price * (1 + self.price_adjustment / 100)
        return self.base_price
    
    def set_variant_value(self, attribute_name: str, value: Any) -> "ProductVariant":
        """
        设置变体属性值
        
        Args:
            attribute_name: 属性名称
            value: 属性值
            
        Returns:
            ProductVariant: 更新后的变体实例
        """
        self.variant_values[attribute_name] = value
        return self
    
    def update_price_adjustment(self, adjustment: float, adjustment_type: str = "absolute") -> "ProductVariant":
        """
        更新价格调整
        
        Args:
            adjustment: 价格调整值
            adjustment_type: 调整类型
            
        Returns:
            ProductVariant: 更新后的变体实例
        """
        self.price_adjustment = adjustment
        self.price_adjustment_type = adjustment_type
        self.actual_price = self._calculate_actual_price()
        return self
    
    def get_variant_display_name(self) -> str:
        """
        获取变体显示名称
        
        Returns:
            str: 变体显示名称
        """
        variant_parts = []
        for attr_name, attr_value in self.variant_values.items():
            variant_parts.append(f"{attr_name}: {attr_value}")
        
        if variant_parts:
            return f"{self.name} - {', '.join(variant_parts)}"
        return self.name


class Brand(NamedModel):
    """
    品牌
    """
    def __init__(self, **kwargs):
        """
        初始化品牌
        
        Args:
            **kwargs: 品牌属性
        """
        super().__init__(**kwargs)
        
        # 品牌标志
        self.logo_url = kwargs.get("logo_url", "")
        
        # 品牌网站
        self.website = kwargs.get("website", "")
        
        # 品牌描述
        self.brand_description = kwargs.get("brand_description", "")
        
        # 品牌状态
        self.is_active = kwargs.get("is_active", True)
        
        # 排序
        self.sort_order = kwargs.get("sort_order", 0)
    
    def toggle_active(self) -> "Brand":
        """
        切换品牌状态
        
        Returns:
            Brand: 更新后的品牌实例
        """
        self.is_active = not self.is_active
        return self


# 示例用法
if __name__ == "__main__":
    # 创建产品类别
    electronics = ProductCategory(name="电子产品", code="ELECTRONICS")
    smartphones = ProductCategory(name="智能手机", code="SMARTPHONES", parent_id=electronics.id)
    electronics.add_child(smartphones.id)
    
    print(f"创建类别: {electronics.name}, 子类别: {len(electronics.child_ids)}")
    
    # 创建产品属性
    color_attr = ProductAttribute(name="颜色", code="COLOR", type="select")
    color_attr.add_option("red", "红色")
    color_attr.add_option("blue", "蓝色")
    color_attr.add_option("black", "黑色")
    
    size_attr = ProductAttribute(name="存储容量", code="STORAGE", type="select")
    size_attr.add_option("64gb", "64GB")
    size_attr.add_option("128gb", "128GB")
    size_attr.add_option("256gb", "256GB")
    
    print(f"创建属性: {color_attr.name}, 选项数: {len(color_attr.options)}")
    
    # 创建主产品
    phone_product = Product(
        name="智能手机X",
        code="PHONE-X",
        sku="PHX-001",
        base_price=5999.0,
        cost_price=3000.0,
        category_ids=[electronics.id, smartphones.id],
        short_description="最新款智能手机",
        long_description="这是一款功能强大的智能手机，配备最新处理器和高清屏幕。",
        has_variants=True,
        variant_attributes=["颜色", "存储容量"]
    )
    
    phone_product.add_image("https://example.com/phone-main.jpg", is_primary=True)
    phone_product.add_image("https://example.com/phone-back.jpg")
    
    print(f"创建产品: {phone_product.name}, SKU: {phone_product.sku}")
    
    # 创建产品变体
    variant1 = ProductVariant(
        name="智能手机X",
        sku="PHX-001-RED-64",
        parent_product_id=phone_product.id,
        base_price=phone_product.base_price,
        variant_values={"颜色": "红色", "存储容量": "64GB"}
    )
    
    variant2 = ProductVariant(
        name="智能手机X",
        sku="PHX-001-BLUE-128",
        parent_product_id=phone_product.id,
        base_price=phone_product.base_price,
        price_adjustment=500.0,
        price_adjustment_type="absolute",
        variant_values={"颜色": "蓝色", "存储容量": "128GB"}
    )
    
    # 将变体添加到主产品
    phone_product.add_variant(variant1.id)
    phone_product.add_variant(variant2.id)
    
    print(f"变体1显示名称: {variant1.get_variant_display_name()}")
    print(f"变体2显示名称: {variant2.get_variant_display_name()}")
    print(f"变体2实际价格: {variant2.actual_price}")