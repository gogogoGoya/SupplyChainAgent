"""
统一响应模型

所有企业部门的功能方法都应该使用此模型返回执行结果，确保返回格式的一致性和可预测性。
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from enum import Enum
import time


class ResponseStatus(Enum):
    """响应状态枚举"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"  # 部分成功
    PENDING = "pending"  # 待处理


@dataclass
class ModuleResponse:
    """
    统一响应类 - 所有业务模块方法的标准返回格式

    该类为所有企业部门(财务、HR、生产、销售、采购、库存)的功能方法提供统一的返回格式。
    通过标准化返回结构，便于上层系统统一处理和分析。

    Attributes:
        status (ResponseStatus): 执行状态 (success/failed/partial/pending)
        success (bool): 是否执行成功的布尔标记，便于快速判断
        consumed_time (float): 方法执行在模拟时间中的预计耗时，以秒为单位
        message (str): 执行结果的文本说明
        module_id (str): 执行此方法的模块唯一标识
        action_type (str): 执行的动作类型 (如 "add_revenue", "recruit_employees" 等)
        timestamp (float): 执行时的时间戳

        data (Dict[str, Any]): 方法特定的返回数据，使用嵌套字典存储不同维度的结果
            - 推荐的嵌套结构示例:
              {
                  "financial": {
                      "cash_before": 100000,
                      "cash_after": 105000,
                      "amount": 5000
                  },
                  "transaction": {
                      "transaction_id": "txn_001",
                      "transaction_type": "income"
                  },
                  "metrics": {
                      "total_revenue": 500000,
                      "profit_margin": 0.15
                  }
              }

        errors (List[Dict]): 错误信息列表，每个错误包含code和message
            - 示例: [{"code": "INSUFFICIENT_CASH", "message": "现金不足"}]

        warnings (List[Dict]): 警告信息列表，不影响执行但需要注意
            - 示例: [{"level": "WARNING", "message": "现金余额偏低"}]
    """

    status: ResponseStatus = ResponseStatus.SUCCESS
    success: bool = True  # 是否执行成功的布尔标记，便于快速判断
    consumed_time: float = 0.0  # 以秒为单位的模拟执行时间
    message: str = ""
    module_type: str = ""
    module_id: str = ""
    action_type: str = ""  # 执行的动作类型
    timestamp: float = 0.0

    params: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)

    errors: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[Dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        """初始化后处理，确保status和success保持一致"""
        # 根据success值自动设置status
        if not self.success:
            if self.status == ResponseStatus.SUCCESS:
                self.status = ResponseStatus.FAILED
        elif self.status == ResponseStatus.FAILED:
            self.success = False

        # 如果有错误但success为True，则修正为False
        if self.errors and self.success:
            self.success = False
            self.status = ResponseStatus.FAILED

    def set_success(self, success: bool, message: str = ""):
        """设置成功状态"""
        self.success = success
        self.status = ResponseStatus.SUCCESS if success else ResponseStatus.FAILED
        if message:
            self.message = message
        return self

    def set_status(self, status: ResponseStatus):
        """设置响应状态"""
        self.status = status
        self.success = (status == ResponseStatus.SUCCESS)
        return self

    def set_message(self, message: str):
        """设置执行结果消息"""
        self.message = message
        return self
    def add_error(self, code: str, message: str):
        """添加错误信息"""
        self.errors.append({"code": code, "message": message})
        self.success = False
        self.status = ResponseStatus.FAILED
        return self

    def add_warning(self, level: str, message: str):
        """添加警告信息"""
        self.warnings.append({"level": level, "message": message})
        return self

    def set_consumed_time(self, seconds: float):
        """设置消耗时间（以秒为单位）"""
        self.consumed_time = max(0, seconds)  # 确保非负
        return self

    def set_data(self, key: str, value: Any):
        """设置嵌套数据"""
        self.data[key] = value
        return self

    def add_data(self, key: str, **kwargs):
        """添加嵌套数据对象"""
        if key not in self.data:
            self.data[key] = {}
        self.data[key].update(kwargs)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "status": self.status.value,
            "success": self.success,
            "consumed_time": self.consumed_time,
            "message": self.message,
            "module_id": self.module_id,
            "action_type": self.action_type,
            "timestamp": self.timestamp,
            "data": self.data,
            "errors": self.errors,
            "warnings": self.warnings,
            "has_errors": len(self.errors) > 0,
            "has_warnings": len(self.warnings) > 0
        }

    def get_consume_time(self) -> float:
        """获取消耗时间"""
        return self.consumed_time
    @classmethod
    def success_response(cls, message: str = "Operation completed successfully",
                        module_id: str = "", action_type: str = "",
                        consumed_time: float = 0.0) -> "ModuleResponse":
        """创建成功响应"""
        return cls(
            status=ResponseStatus.SUCCESS,
            message=message,
            module_id=module_id,
            action_type=action_type,
            consumed_time=consumed_time
        )

    @classmethod
    def failed_response(cls, message: str = "Operation failed",
                       module_id: str = "", action_type: str = "") -> "ModuleResponse":
        """创建失败响应"""
        return cls(
            status=ResponseStatus.FAILED,
            message=message,
            module_id=module_id,
            action_type=action_type
        )

    @classmethod
    def partial_response(cls, message: str = "Operation partially completed",
                        module_id: str = "", action_type: str = "",
                        consumed_time: float = 0.0) -> "ModuleResponse":
        """创建部分成功响应"""
        return cls(
            status=ResponseStatus.PARTIAL,
            message=message,
            module_id=module_id,
            action_type=action_type,
            consumed_time=consumed_time
        )