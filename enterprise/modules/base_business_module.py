"""
业务模块基类，为所有业务模块提供统一的接口和生命周期方法
"""

from typing import Dict, List, Optional, Any
import uuid
import time
import inspect
import copy
from functools import wraps
from typing import Callable, Any
from enterprise.modules.response_model import ModuleResponse, ResponseStatus

class ResponseMixin:
    """响应处理混入类"""
    
    def create_response(self, action_type: str) -> ModuleResponse:
        """创建标准响应对象"""
        response = ModuleResponse()
        response.module_id = self.module_id
        response.module_type = self.module_type
        response.action_type = action_type
        response.timestamp = time.time()
        
        # 从配置获取时间消耗
        if hasattr(self, 'config') and hasattr(self.config, 'TIME_COST'):
            response.consumed_time = self.config.TIME_COST.get(action_type, 60)
        else:
            response.consumed_time = 60  # 默认值
        
        return response
    
    def success_response(self, response: ModuleResponse, 
                        message: str, data: dict = None) -> ModuleResponse:
        """设置成功响应"""
        response.set_status(ResponseStatus.SUCCESS)
        response.set_message(message)
        if data:
            response.data = data
        
        # 添加警告
        if hasattr(self, 'warnings') and self.warnings:
            for warning in self.warnings:
                response.add_warning(warning["level"], warning["message"])
        
        return response
    
    def error_response(self, response: ModuleResponse, 
                      error_code: str, error_msg: str, 
                      main_message: str = None) -> ModuleResponse:
        """设置错误响应"""
        response.set_status(ResponseStatus.FAILED)
        response.add_error(error_code, error_msg)
        response.set_message(main_message or f"Failed to {response.action_type}")
        return response

    def partial_success_response(self, response: ModuleResponse,
                                 message: str, data: Dict = None,
                                 warnings: List[Dict] = None) -> ModuleResponse:
        """
        设置部分成功响应
        
        Args:
            response: 响应对象
            message: 消息
            data: 响应数据
            warnings: 警告列表
            
        Returns:
            ModuleResponse: 设置后的响应对象
        """
        response.set_status(ResponseStatus.PARTIAL_SUCCESS)
        response.set_message(message)
        
        if data:
            response.data = data
        
        if warnings:
            for warning in warnings:
                response.add_warning(warning.get("level", "WARNING"), 
                                   warning.get("message", "Unknown warning"))
        return response


class ValidationMixin:
    """参数验证混入类"""
    
    def validate_positive_amount(self, amount: float, 
                                 response: ModuleResponse) -> bool:
        """验证金额为正数"""
        if amount <= 0:
            self.error_response(response, "INVALID_AMOUNT", 
                              "Amount must be positive")
            return False
        return True
    
    def validate_choice(self, value: str, valid_choices: list, 
                       param_name: str, response: ModuleResponse) -> bool:
        """验证选项是否合法"""
        if value not in valid_choices:
            self.error_response(
                response, 
                f"INVALID_{param_name.upper()}", 
                f"Invalid {param_name}. Must be one of: {', '.join(valid_choices)}"
            )
            return False
        return True

    def validate_date_format(self, date_str: str, param_name: str,
                           response: ModuleResponse) -> bool:
        """
        验证日期格式
        
        Args:
            date_str: 日期字符串
            param_name: 参数名称
            response: 响应对象
            
        Returns:
            bool: 验证是否通过
        """
        import datetime
        
        try:
            datetime.datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            self.error_response(
                response,
                "INVALID_DATE_FORMAT",
                f"Invalid {param_name} format: '{date_str}'. Use YYYY-MM-DD"
            )
            return False

class BaseBusinessModule:
    """
    业务模块基类
    所有企业的工作部门模块都应该继承这个基类
    """
    
    def __init__(self, enterprise, module_id: str = None, **kwargs):
        """
        初始化业务模块
        
        Args:
            enterprise: 所属企业实例
            module_id: 模块唯一标识符，如果不提供则自动生成
            **kwargs: 其他配置参数
        """
        self.enterprise = enterprise
        self.module_id = module_id or f"{self.__class__.__name__.lower()}_{uuid.uuid4().hex[:8]}"
        self.module_name = self.__class__.__name__
        self.config = kwargs
        
        # 模块状态
        self.is_active = True
        self.created_at = time.time()
        self.last_updated = time.time()
        
        # 记录模块执行的动作历史
        self.action_history = []
        
        # 初始化模块
        self._initialize()
    
    def _initialize(self):
        """
        模块初始化逻辑，子类可以重写此方法进行自定义初始化
        """
        pass

    def message_handle(self, message: Dict) -> Dict:
        """
        处理来自其他模块或外部系统的消息
        
        Args:
            message: 包含消息内容的字典，至少包含"type"和"content"键
            
        Returns:
            dict: 处理结果，包含"status"和"message"键
        """
        return {
            "status": "success",
            "message": f"Message received: {message.get('content', 'No content')}"
        }
    
    def get_module_by_type(self,module_type):
        """从enterprise.business_modules中获取指定类型的第一个模块实例"""
        if hasattr(self.enterprise, 'business_modules') and module_type in self.enterprise.business_modules:
            modules = self.enterprise.business_modules[module_type]
            return modules[0] if modules else None
        return None

    def get_module_info(self) -> Dict:
        """
        获取模块基本信息
        
        Returns:
            dict: 模块信息
        """
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "enterprise_id": self.enterprise.id,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_updated": self.last_updated
        }
    
    def get_state(self) -> Dict:
        """
        获取模块当前状态
        子类应该重写此方法来提供详细的状态信息
        
        Returns:
            dict: 模块状态
        """
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "is_active": self.is_active,
            "action_history_count": len(self.action_history)
        }
    
    def _record_action(self, action: Dict):
        """
        记录动作到历史
        
        Args:
            action: 执行的动作
        """
        action_record = {
            "timestamp": time.time(),
            "time_step": getattr(self.enterprise, "time_step", 0),
            "action": action.copy()
        }
        self.action_history.append(action_record)
        self.last_updated = time.time()
    
    def update(self, **kwargs):
        """
        更新模块配置
        
        Args:
            **kwargs: 要更新的配置参数
        """
        self.config.update(kwargs)
        self.last_updated = time.time()
    
    def activate(self):
        """
        激活模块
        """
        self.is_active = True
        self.last_updated = time.time()
    
    def deactivate(self):
        """
        停用模块
        """
        self.is_active = False
        self.last_updated = time.time()

    def __str__(self):
        return f"{self.module_name} (ID: {self.module_id}) for Enterprise {self.enterprise.id}"

class EnhancedBaseModule(BaseBusinessModule, ResponseMixin, ValidationMixin):
    """增强的基础模块类"""
    
    def __init__(self, enterprise, module_id: str, config=None):
        super().__init__(enterprise, module_id)
        self.config = config
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        安全获取配置值
        
        Args:
            key: 配置键名
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        if self.config and hasattr(self.config, key):
            return getattr(self.config, key)
        return default
    
    def batch_execute(self, operations: List[Dict]) -> ModuleResponse:
        """
        批量验证多个方法（只验证，不执行真实逻辑）

        Args:
            operations: 操作列表，每个元素包含:
            {
                "action_name": "method_name",
                "action_param": {...}
            }

        Returns:
            ModuleResponse: 验证结果
        """

        # 创建主响应对象
        response = self.create_response("batch_execute")

        errors = []
        # 逐个操作进行验证
        for i, operation in enumerate(operations):

            action_name = operation.get("action_name")
            action_param = operation.get("action_param", {})
            if not action_name:
                errors.append({
                    "code": f"INVALID_OPERATION_{i+1}",
                    "message": f"Operation {i+1} missing action_name"
                })
                continue

            if not hasattr(self, action_name):
                errors.append({
                    "code": f"METHOD_NOT_FOUND_{i+1}",
                    "message": f"Method {action_name} not found"
                })
                continue

            method = getattr(self, action_name)

            try:
                # 创建临时响应对象（用于验证）
                temp_response = self.create_response(action_name)

                # 获取方法签名
                sig = inspect.signature(method)

                # 检查是否存在多余参数
                invalid_params = [
                    k for k in action_param.keys()
                    if k not in sig.parameters
                ]

                if invalid_params:
                    errors.append({
                        "code": f"INVALID_PARAMS_{i+1}",
                        "message": f"Action << {action_name} >> received unexpected keyword arguments: {invalid_params}"
                    })
                    continue

                # 构建有效参数
                valid_params = {
                    k: v for k, v in action_param.items()
                    if k in sig.parameters
                }

                # 如果方法支持 response 参数则传入
                if "response" in sig.parameters:
                    valid_params["response"] = temp_response
                if getattr(method, "_skip_dry_run_validation", False):
                    continue
                if "dry_run" in sig.parameters:
                    valid_params["dry_run"] = True
                    # 只有显式支持 dry_run 的动作，才在预检查阶段真实调用。
                    # 这样可以避免校验阶段对未实现 dry_run 的历史动作产生不可回滚副作用。
                    result = method(**valid_params)
                else:
                    continue

                # 如果返回失败状态则记录错误
                if isinstance(result, ModuleResponse) and result.status == ResponseStatus.FAILED:
                    result_dict = result.to_dict()
                    errors.append({
                        "code": f"VALIDATION_FAILED_{i+1}",
                        "message": f"Action << {action_name} >> validation failed : << {result_dict['errors'][0]['message']} >>"
                    })
            except Exception as e:
                errors.append({
                    "code": f"VALIDATION_ERROR_{i+1}",
                    "message": f"Error validating action {action_name}: {str(e)}"
                })
        if errors:
            for error in errors:
                response.add_error(error["code"], error["message"])

            response.set_status(ResponseStatus.FAILED)
            response.set_message(f"Validation failed for {len(errors)} operations")
            return response
        response.set_status(ResponseStatus.SUCCESS)
        response.set_message("All operations validated successfully")
        return response
