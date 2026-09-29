"""
基础数据库模型

定义数据库表的基类和通用结构
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import Column, String, DateTime, JSON, Boolean, Integer
from sqlalchemy.sql import func
from database.db_manager import Base


class BaseModel(Base):
    """
    数据库模型基类
    对应于数据模型中的BaseModel
    """
    __abstract__ = True
    
    # 主键ID
    id = Column(String, primary_key=True, index=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.now())
    
    # 状态
    status = Column(String, default="active")
    
    # 标签（使用JSON存储列表）
    tags = Column(JSON, default=list)
    
    # 元数据
    metadata_ = Column("metadata", JSON, default=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将数据库模型转换为字典
        
        Returns:
            dict: 模型字典表示
        """
        result = {}
        for column in self.__table__.columns:
            key = column.name
            value = getattr(self, key)
            
            # 处理JSON字段
            if isinstance(value, dict) or isinstance(value, list):
                result[key] = value
            # 处理datetime字段
            elif hasattr(value, 'isoformat'):
                result[key] = value.isoformat()
            else:
                result[key] = value
        
        # 修复metadata_字段名
        if 'metadata_' in result:
            result['metadata'] = result.pop('metadata_')
        
        return result
    
    def from_dict(self, data: Dict[str, Any]) -> "BaseModel":
        """
        从字典加载数据到模型
        
        Args:
            data: 模型字典数据
        
        Returns:
            BaseModel: 更新后的模型实例
        """
        for key, value in data.items():
            # 处理metadata字段名
            if key == 'metadata':
                key = 'metadata_'
            
            if hasattr(self, key):
                setattr(self, key, value)
        
        return self