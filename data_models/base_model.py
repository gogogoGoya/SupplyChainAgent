"""
基础模型模块

定义系统中所有数据模型的基类和通用结构
"""

import time
import uuid
from typing import Dict, Any, Optional, List


class BaseModel:
    """
    所有数据模型的基类
    提供通用的属性和方法
    """
    def __init__(self, **kwargs):
        """
        初始化基础模型
        
        Args:
            **kwargs: 模型属性
        """
        # 唯一标识符
        self.id = kwargs.get("id", str(uuid.uuid4()))
        
        # 时间戳
        self.created_at = kwargs.get("created_at", time.time())
        self.updated_at = kwargs.get("updated_at", time.time())
        
        # 状态
        self.status = kwargs.get("status", "active")
        
        # 标签
        self.tags = kwargs.get("tags", [])
        
        # 元数据
        self.metadata = kwargs.get("metadata", {})
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将模型转换为字典
        
        Returns:
            dict: 模型字典表示
        """
        result = {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "tags": self.tags,
            "metadata": self.metadata
        }
        
        # 添加子类特有属性
        for key, value in self.__dict__.items():
            if key not in result:
                # 递归转换嵌套模型
                if isinstance(value, BaseModel):
                    result[key] = value.to_dict()
                # 转换模型列表
                elif isinstance(value, list) and value and isinstance(value[0], BaseModel):
                    result[key] = [item.to_dict() for item in value]
                else:
                    result[key] = value
        
        return result
    
    def from_dict(self, data: Dict[str, Any]) -> "BaseModel":
        """
        从字典加载模型数据
        
        Args:
            data: 模型字典数据
            
        Returns:
            BaseModel: 更新后的模型实例
        """
        for key, value in data.items():
            if hasattr(self, key):
                # 对于字典类型的属性，需要特殊处理
                if isinstance(getattr(self, key), dict) and isinstance(value, dict):
                    getattr(self, key).update(value)
                # 对于列表类型的属性，需要特殊处理
                elif isinstance(getattr(self, key), list) and isinstance(value, list):
                    setattr(self, key, value)
                else:
                    setattr(self, key, value)
        
        # 更新时间戳
        self.updated_at = time.time()
        
        return self
    
    def update(self, **kwargs) -> "BaseModel":
        """
        更新模型属性
        
        Args:
            **kwargs: 要更新的属性
            
        Returns:
            BaseModel: 更新后的模型实例
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        # 更新时间戳
        self.updated_at = time.time()
        
        return self
    
    def validate(self) -> bool:
        """
        验证模型数据的有效性
        
        Returns:
            bool: 是否有效
        """
        # 基础验证：确保ID不为空
        if not self.id:
            return False
        
        # 确保状态是有效的
        valid_statuses = ["active", "inactive", "draft", "deleted"]
        if self.status not in valid_statuses:
            return False
        
        return True
    
    def get_validation_errors(self) -> List[str]:
        """
        获取验证错误列表
        
        Returns:
            list: 错误消息列表
        """
        errors = []
        
        if not self.id:
            errors.append("ID cannot be empty")
        
        valid_statuses = ["active", "inactive", "draft", "deleted"]
        if self.status not in valid_statuses:
            errors.append(f"Invalid status: {self.status}. Must be one of: {', '.join(valid_statuses)}")
        
        return errors
    
    def soft_delete(self) -> "BaseModel":
        """
        软删除模型
        
        Returns:
            BaseModel: 更新后的模型实例
        """
        self.status = "deleted"
        self.updated_at = time.time()
        return self
    
    def activate(self) -> "BaseModel":
        """
        激活模型
        
        Returns:
            BaseModel: 更新后的模型实例
        """
        self.status = "active"
        self.updated_at = time.time()
        return self
    
    def deactivate(self) -> "BaseModel":
        """
        停用模型
        
        Returns:
            BaseModel: 更新后的模型实例
        """
        self.status = "inactive"
        self.updated_at = time.time()
        return self
    
    def add_tag(self, tag: str) -> "BaseModel":
        """
        添加标签
        
        Args:
            tag: 标签名称
            
        Returns:
            BaseModel: 更新后的模型实例
        """
        if tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = time.time()
        return self
    
    def remove_tag(self, tag: str) -> "BaseModel":
        """
        移除标签
        
        Args:
            tag: 标签名称
            
        Returns:
            BaseModel: 更新后的模型实例
        """
        if tag in self.tags:
            self.tags.remove(tag)
            self.updated_at = time.time()
        return self
    
    def set_metadata(self, key: str, value: Any) -> "BaseModel":
        """
        设置元数据
        
        Args:
            key: 元数据键
            value: 元数据值
            
        Returns:
            BaseModel: 更新后的模型实例
        """
        self.metadata[key] = value
        self.updated_at = time.time()
        return self
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """
        获取元数据
        
        Args:
            key: 元数据键
            default: 默认值
            
        Returns:
            Any: 元数据值或默认值
        """
        return self.metadata.get(key, default)
    
    def __str__(self) -> str:
        """
        字符串表示
        """
        return f"<{self.__class__.__name__} id={self.id} status={self.status}>"
    
    def __repr__(self) -> str:
        """
        正式表示
        """
        return self.__str__()


class NamedModel(BaseModel):
    """
    具有名称的模型基类
    """
    def __init__(self, **kwargs):
        """
        初始化命名模型
        
        Args:
            **kwargs: 模型属性
        """
        super().__init__(**kwargs)
        
        # 名称和描述
        self.name = kwargs.get("name", "")
        self.description = kwargs.get("description", "")
        
        # 代码/标识符
        self.code = kwargs.get("code", "")
    
    def validate(self) -> bool:
        """
        验证模型数据的有效性
        
        Returns:
            bool: 是否有效
        """
        # 调用父类验证
        if not super().validate():
            return False
        
        # 验证名称
        if not self.name:
            return False
        
        return True
    
    def get_validation_errors(self) -> List[str]:
        """
        获取验证错误列表
        
        Returns:
            list: 错误消息列表
        """
        errors = super().get_validation_errors()
        
        if not self.name:
            errors.append("Name cannot be empty")
        
        return errors
    
    def __str__(self) -> str:
        """
        字符串表示
        """
        return f"<{self.__class__.__name__} id={self.id} name='{self.name}' status={self.status}>"


class AuditableModel(BaseModel):
    """
    可审计的模型基类
    包含创建者、更新者等审计信息
    """
    def __init__(self, **kwargs):
        """
        初始化可审计模型
        
        Args:
            **kwargs: 模型属性
        """
        super().__init__(**kwargs)
        
        # 审计信息
        self.created_by = kwargs.get("created_by", "system")
        self.updated_by = kwargs.get("updated_by", "system")
        self.deleted_by = kwargs.get("deleted_by", None)
        self.deleted_at = kwargs.get("deleted_at", None)
    
    def update(self, **kwargs) -> "AuditableModel":
        """
        更新模型属性
        
        Args:
            **kwargs: 要更新的属性
            
        Returns:
            AuditableModel: 更新后的模型实例
        """
        # 更新更新者
        if "updated_by" in kwargs:
            self.updated_by = kwargs["updated_by"]
        
        return super().update(**kwargs)
    
    def soft_delete(self, deleted_by: str = "system") -> "AuditableModel":
        """
        软删除模型
        
        Args:
            deleted_by: 删除者
            
        Returns:
            AuditableModel: 更新后的模型实例
        """
        self.deleted_by = deleted_by
        self.deleted_at = time.time()
        return super().soft_delete()


class VersionedModel(BaseModel):
    """
    版本化的模型基类
    跟踪模型的版本历史
    """
    def __init__(self, **kwargs):
        """
        初始化版本化模型
        
        Args:
            **kwargs: 模型属性
        """
        super().__init__(**kwargs)
        
        # 版本信息
        self.version = kwargs.get("version", 1)
        self.version_history = kwargs.get("version_history", [])
        
        # 初始版本记录
        initial_version = {
            "version": 1,
            "created_at": self.created_at,
            "created_by": kwargs.get("created_by", "system"),
            "changes": {}
        }
        
        # 确保版本历史不为空
        if not self.version_history:
            self.version_history.append(initial_version)
    
    def update(self, **kwargs) -> "VersionedModel":
        """
        更新模型属性并创建新版本
        
        Args:
            **kwargs: 要更新的属性
            
        Returns:
            VersionedModel: 更新后的模型实例
        """
        # 记录变更
        changes = {}
        for key, value in kwargs.items():
            if hasattr(self, key) and getattr(self, key) != value:
                changes[key] = {
                    "old_value": getattr(self, key),
                    "new_value": value
                }
        
        # 如果有变更，创建新版本
        if changes:
            # 调用父类更新
            updated_by = kwargs.pop("updated_by", "system")
            super().update(**kwargs)
            
            # 增加版本号
            self.version += 1
            
            # 记录版本历史
            version_record = {
                "version": self.version,
                "created_at": self.updated_at,
                "created_by": updated_by,
                "changes": changes
            }
            self.version_history.append(version_record)
        
        return self
    
    def get_version(self, version_number: int) -> Optional[Dict[str, Any]]:
        """
        获取指定版本的信息
        
        Args:
            version_number: 版本号
            
        Returns:
            dict: 版本信息或None
        """
        for version_record in self.version_history:
            if version_record["version"] == version_number:
                return version_record
        return None
    
    def get_latest_version(self) -> Dict[str, Any]:
        """
        获取最新版本的信息
        
        Returns:
            dict: 最新版本信息
        """
        if self.version_history:
            return max(self.version_history, key=lambda x: x["version"])
        return {}


class TimestampedModel(BaseModel):
    """
    时间戳模型基类
    包含开始时间、结束时间等时间相关信息
    """
    def __init__(self, **kwargs):
        """
        初始化时间戳模型
        
        Args:
            **kwargs: 模型属性
        """
        super().__init__(**kwargs)
        
        # 时间信息
        self.start_time = kwargs.get("start_time", None)
        self.end_time = kwargs.get("end_time", None)
        self.duration = kwargs.get("duration", None)  # 持续时间（秒）
    
    def is_active_at(self, timestamp: float) -> bool:
        """
        检查在指定时间戳是否处于活动状态
        
        Args:
            timestamp: 时间戳
            
        Returns:
            bool: 是否活动
        """
        # 如果没有设置开始时间，则认为总是活动
        if self.start_time is None:
            # 如果设置了结束时间，检查是否在结束时间之前
            if self.end_time is not None:
                return timestamp < self.end_time
            return True
        
        # 检查是否在开始时间之后
        if timestamp < self.start_time:
            return False
        
        # 检查是否在结束时间之前（如果设置了）
        if self.end_time is not None and timestamp > self.end_time:
            return False
        
        return True
    
    def set_duration(self, duration: float) -> "TimestampedModel":
        """
        设置持续时间
        
        Args:
            duration: 持续时间（秒）
            
        Returns:
            TimestampedModel: 更新后的模型实例
        """
        self.duration = duration
        
        # 如果有开始时间，自动计算结束时间
        if self.start_time is not None:
            self.end_time = self.start_time + duration
        
        self.updated_at = time.time()
        return self
    
    def get_remaining_time(self, timestamp: float = None) -> float:
        """
        获取剩余时间
        
        Args:
            timestamp: 参考时间戳（默认当前时间）
            
        Returns:
            float: 剩余时间（秒），如果已结束则返回0
        """
        if timestamp is None:
            timestamp = time.time()
        
        if self.end_time is None:
            return float('inf')  # 没有结束时间，剩余时间无限
        
        remaining = self.end_time - timestamp
        return max(0, remaining)


# 示例用法
if __name__ == "__main__":
    # 创建基础模型
    base = BaseModel(name="测试模型", value=100)
    print(f"基础模型: {base}")
    print(f"模型字典: {base.to_dict()}")
    
    # 测试更新
    base.update(value=200)
    print(f"更新后的值: {base.value}")
    
    # 创建命名模型
    named = NamedModel(name="产品A", description="这是一个测试产品", code="PROD-A")
    print(f"命名模型: {named}")
    print(f"验证结果: {named.validate()}")
    
    # 测试标签
    named.add_tag("新产品")
    named.add_tag("热销")
    print(f"添加标签后的模型: {named.tags}")
    
    # 创建版本化模型
    versioned = VersionedModel(name="配置项", value="初始值")
    versioned.update(value="更新值", updated_by="admin")
    versioned.update(value="最终值", updated_by="admin")
    print(f"当前版本: {versioned.version}")
    print(f"版本历史: {len(versioned.version_history)}")
    
    # 获取特定版本
    v1 = versioned.get_version(1)
    v2 = versioned.get_version(2)
    print(f"版本1: {v1['changes']}")
    print(f"版本2: {v2['changes']}")