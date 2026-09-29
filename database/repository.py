"""
数据访问层 - Repository模式实现

提供通用的数据库CRUD操作接口
"""
from typing import Generic, TypeVar, Optional, List, Dict, Any, Type
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, inspect, func

from database.models.base import BaseModel

T = TypeVar('T', bound=BaseModel)


class Repository(Generic[T]):
    """
    通用数据仓库基类
    提供对数据库实体的基本CRUD操作
    """
    
    def __init__(self, model_class: Type[T]):
        """
        初始化Repository
        
        Args:
            model_class: 数据库模型类
        """
        self.model_class = model_class
    
    def get(self, db: Session, id: int) -> Optional[T]:
        """
        根据ID获取单个实体
        
        Args:
            db: 数据库会话
            id: 实体ID
            
        Returns:
            实体实例或None
        """
        return db.query(self.model_class).filter(self.model_class.id == id).first()
    
    def get_all(self, db: Session, skip: int = 0, limit: int = 100) -> List[T]:
        """
        获取所有实体（可分页）
        
        Args:
            db: 数据库会话
            skip: 跳过的记录数
            limit: 返回的最大记录数
            
        Returns:
            实体列表
        """
        return db.query(self.model_class).offset(skip).limit(limit).all()
    
    def get_by(self, db: Session, **kwargs) -> List[T]:
        """
        根据条件查询实体
        
        Args:
            db: 数据库会话
            **kwargs: 查询条件，格式为字段名=值
            
        Returns:
            符合条件的实体列表
        """
        # 构建查询条件
        conditions = []
        for key, value in kwargs.items():
            # 检查属性是否存在
            if hasattr(self.model_class, key):
                conditions.append(getattr(self.model_class, key) == value)
        
        return db.query(self.model_class).filter(and_(*conditions)).all()
    
    def get_first(self, db: Session, **kwargs) -> Optional[T]:
        """
        根据条件查询单个实体
        
        Args:
            db: 数据库会话
            **kwargs: 查询条件，格式为字段名=值
            
        Returns:
            第一个符合条件的实体或None
        """
        # 构建查询条件
        conditions = []
        for key, value in kwargs.items():
            if hasattr(self.model_class, key):
                conditions.append(getattr(self.model_class, key) == value)
        
        return db.query(self.model_class).filter(and_(*conditions)).first()
    
    def create(self, db: Session, obj_in: Dict[str, Any]) -> T:
        """
        创建新实体
        
        Args:
            db: 数据库会话
            obj_in: 实体数据字典
            
        Returns:
            创建的实体实例
        """
        # 过滤掉模型中不存在的字段
        model_columns = [c.name for c in inspect(self.model_class).columns]
        filtered_data = {k: v for k, v in obj_in.items() if k in model_columns}
        
        # 创建实体实例
        db_obj = self.model_class(**filtered_data)
        
        # 添加到会话并提交
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        
        return db_obj
    
    def update(self, db: Session, db_obj: T, obj_in: Dict[str, Any]) -> T:
        """
        更新现有实体
        
        Args:
            db: 数据库会话
            db_obj: 数据库中的实体对象
            obj_in: 更新的数据字典
            
        Returns:
            更新后的实体实例
        """
        # 过滤掉模型中不存在的字段
        model_columns = [c.name for c in inspect(self.model_class).columns]
        filtered_data = {k: v for k, v in obj_in.items() if k in model_columns}
        
        # 更新字段
        for field, value in filtered_data.items():
            setattr(db_obj, field, value)
        
        # 提交更新
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        
        return db_obj
    
    def delete(self, db: Session, id: int) -> bool:
        """
        删除实体
        
        Args:
            db: 数据库会话
            id: 实体ID
            
        Returns:
            是否删除成功
        """
        db_obj = self.get(db, id)
        if db_obj:
            db.delete(db_obj)
            db.commit()
            return True
        return False
    
    def delete_by(self, db: Session, **kwargs) -> int:
        """
        根据条件删除实体
        
        Args:
            db: 数据库会话
            **kwargs: 删除条件，格式为字段名=值
            
        Returns:
            删除的记录数
        """
        # 构建查询条件
        conditions = []
        for key, value in kwargs.items():
            if hasattr(self.model_class, key):
                conditions.append(getattr(self.model_class, key) == value)
        
        # 执行删除
        result = db.query(self.model_class).filter(and_(*conditions)).delete()
        db.commit()
        
        return result
    
    def count(self, db: Session, **kwargs) -> int:
        """
        统计实体数量
        
        Args:
            db: 数据库会话
            **kwargs: 过滤条件，格式为字段名=值
            
        Returns:
            实体数量
        """
        query = db.query(func.count(self.model_class.id))
        
        # 应用过滤条件
        if kwargs:
            conditions = []
            for key, value in kwargs.items():
                if hasattr(self.model_class, key):
                    conditions.append(getattr(self.model_class, key) == value)
            query = query.filter(and_(*conditions))
        
        return query.scalar() or 0
    
    def exists(self, db: Session, **kwargs) -> bool:
        """
        检查是否存在符合条件的实体
        
        Args:
            db: 数据库会话
            **kwargs: 查询条件，格式为字段名=值
            
        Returns:
            是否存在
        """
        return self.count(db, **kwargs) > 0
    
    def get_by_ids(self, db: Session, ids: List[int]) -> List[T]:
        """
        根据ID列表获取多个实体
        
        Args:
            db: 数据库会话
            ids: ID列表
            
        Returns:
            实体列表
        """
        return db.query(self.model_class).filter(self.model_class.id.in_(ids)).all()
    
    def search(self, db: Session, search_text: str, fields: List[str], skip: int = 0, limit: int = 100) -> List[T]:
        """
        搜索实体
        
        Args:
            db: 数据库会话
            search_text: 搜索文本
            fields: 要搜索的字段列表
            skip: 跳过的记录数
            limit: 返回的最大记录数
            
        Returns:
            符合搜索条件的实体列表
        """
        # 构建搜索条件
        search_conditions = []
        for field in fields:
            if hasattr(self.model_class, field):
                field_attr = getattr(self.model_class, field)
                # 只对字符串类型字段应用like查询
                if hasattr(field_attr, 'like'):
                    search_conditions.append(field_attr.like(f'%{search_text}%'))
        
        # 执行搜索
        return db.query(self.model_class)\
            .filter(or_(*search_conditions))\
            .offset(skip)\
            .limit(limit)\
            .all()


# 创建常用模型的Repository类
from database.models.enterprise import Enterprise, Supplier, Customer, ProductionPlan, PurchaseOrder, SalesOrder
from database.models.product import Product, ProductCategory, ProductAttribute, ProductVariant, Brand
from database.models.order import Order, OrderLineItem, ShippingAddress, PaymentInfo, ShippingInfo


class EnterpriseRepository(Repository[Enterprise]):
    """企业数据仓库"""
    def __init__(self):
        super().__init__(Enterprise)


class SupplierRepository(Repository[Supplier]):
    """供应商数据仓库"""
    def __init__(self):
        super().__init__(Supplier)


class CustomerRepository(Repository[Customer]):
    """客户数据仓库"""
    def __init__(self):
        super().__init__(Customer)


class ProductRepository(Repository[Product]):
    """产品数据仓库"""
    def __init__(self):
        super().__init__(Product)


class OrderRepository(Repository[Order]):
    """订单数据仓库"""
    def __init__(self):
        super().__init__(Order)
    
    def get_by_order_number(self, db: Session, order_number: str) -> Optional[Order]:
        """根据订单号获取订单"""
        return self.get_first(db, order_number=order_number)
    
    def get_by_status(self, db: Session, status: str, skip: int = 0, limit: int = 100) -> List[Order]:
        """根据状态获取订单"""
        return self.get_by(db, status=status, skip=skip, limit=limit)


class OrderLineItemRepository(Repository[OrderLineItem]):
    """订单项数据仓库"""
    def __init__(self):
        super().__init__(OrderLineItem)
    
    def get_by_order_id(self, db: Session, order_id: int) -> List[OrderLineItem]:
        """获取订单的所有行项目"""
        return self.get_by(db, order_id=order_id)