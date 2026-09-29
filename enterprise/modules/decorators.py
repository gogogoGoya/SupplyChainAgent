from functools import wraps
import time
import traceback
import inspect
from typing import Callable, Any
from enterprise.modules.response_model import ModuleResponse, ResponseStatus


def skip_dry_run_validation(func: Callable) -> Callable:
    """
    标记该动作在 dry_run 校验阶段无需真实调用。
    """
    setattr(func, "_skip_dry_run_validation", True)
    return func


def with_response(action_type: str = None):
    """
    自动创建和处理ModuleResponse的装饰器
    
    功能：
    1. 自动创建响应对象
    2. 自动注入响应对象到方法参数
    3. 统一异常处理
    4. 自动添加警告信息
    
    Args:
        action_type: 操作类型名称，默认使用方法名
        
    使用示例：
        @with_response("add_revenue")
        def add_revenue(self, amount, source, response: ModuleResponse = None):
            # response 已经自动创建并注入
            if amount <= 0:
                return self.error_response(response, "INVALID_AMOUNT", "Amount must be positive")
            
            # ... 业务逻辑 ...
            
            return self.success_response(response, "Revenue added", {...})
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # 确定操作类型
            _action_type = action_type or func.__name__
            
            # 创建响应对象
            response = self.create_response(_action_type)
            
            try:
                sig = inspect.signature(func)
                bound_args = sig.bind(self, *args, **kwargs)
                bound_args.apply_defaults()

                # 去掉 self 和 response（如果有）
                input_params = {
                    k: v for k, v in bound_args.arguments.items()
                    if k not in ('self', 'response')
                }

                response.params = input_params
            except Exception:
                # 参数记录失败不应影响主流程
                response.params = {
                    "args": args,
                    "kwargs": kwargs
                }
            try:
                # 执行方法，将response注入到kwargs中
                kwargs['response'] = response
                result = func(self, *args, **kwargs)
                
                # 如果方法返回ModuleResponse，直接返回
                if isinstance(result, ModuleResponse):
                    return result
                
                # 如果方法返回字典，包装为成功响应
                if isinstance(result, dict):
                    return self.success_response(
                        response, 
                        f"{_action_type} completed successfully", 
                        result
                    )
                
                # 其他情况，返回原始结果（不推荐）
                return result
                
            except ValueError as e:
                # 参数验证错误
                return self.error_response(
                    response, 
                    "VALIDATION_ERROR", 
                    str(e),
                    f"Validation failed for {_action_type}"
                )
            except KeyError as e:
                # 键不存在错误
                return self.error_response(
                    response,
                    "KEY_ERROR",
                    f"Missing required key: {str(e)}",
                    f"Data error in {_action_type}"
                )
            except Exception as e:
                tb = traceback.format_exc()
                return self.error_response(
                    response,
                    "INTERNAL_ERROR",
                    str(e),
                    f"{tb}"
                )
        
        return wrapper
    return decorator


def validate_positive(param_name: str):
    """
    验证参数为正数的装饰器
    
    Args:
        param_name: 需要验证的参数名
        
    使用示例：
        @validate_positive("amount")
        def add_revenue(self, amount, source):
            # amount 已经被验证为正数
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # 获取参数值
            value = kwargs.get(param_name)
            
            # 如果在kwargs中没有找到，尝试从args中获取
            if value is None and len(args) > 0:
                # 获取函数签名，找到参数位置
                import inspect
                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())
                
                if param_name in param_names:
                    param_index = param_names.index(param_name)
                    # 注意：self占用第一个位置，所以需要-1
                    if param_index <= len(args):
                        value = args[param_index - 1]
            
            # 验证
            if value is not None and value <= 0:
                raise ValueError(f"{param_name} must be positive, got {value}")
            
            return func(self, *args, **kwargs)
        
        return wrapper
    return decorator


def validate_choice(param_name: str, valid_choices_attr: str):
    """
    验证参数在有效选项中的装饰器
    
    Args:
        param_name: 需要验证的参数名
        valid_choices_attr: self.config中有效选项列表的属性名
        
    使用示例：
        @validate_choice("source", "REVENUE_SOURCES")
        def add_revenue(self, amount, source):
            # source 已经被验证在 self.config.REVENUE_SOURCES 中
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # 获取有效选项列表
            if not hasattr(self, 'config'):
                raise AttributeError("Instance must have 'config' attribute")
            
            valid_choices = getattr(self.config, valid_choices_attr, None)
            if valid_choices is None:
                raise AttributeError(f"Config has no attribute '{valid_choices_attr}'")
            
            # 获取参数值
            value = kwargs.get(param_name)
            
            # 如果在kwargs中没有找到，尝试从args中获取
            if value is None and len(args) > 0:
                import inspect
                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())
                
                if param_name in param_names:
                    param_index = param_names.index(param_name)
                    if param_index <= len(args):
                        value = args[param_index - 1]
            
            # 验证
            if value is not None and value not in valid_choices:
                raise ValueError(
                    f"Invalid {param_name}: '{value}'. "
                    f"Must be one of: {', '.join(valid_choices)}"
                )
            
            return func(self, *args, **kwargs)
        
        return wrapper
    return decorator


def validate_date_range(start_param: str = "start_date", end_param: str = "end_date"):
    """
    验证日期范围的装饰器
    
    Args:
        start_param: 开始日期参数名
        end_param: 结束日期参数名
        
    使用示例：
        @validate_date_range()
        def generate_report(self, start_date, end_date):
            # 日期范围已经被验证
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            import datetime
            
            start_date = kwargs.get(start_param)
            end_date = kwargs.get(end_param)
            
            if start_date and end_date:
                try:
                    start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
                    end = datetime.datetime.strptime(end_date, "%Y-%m-%d")
                    
                    if start > end:
                        raise ValueError(
                            f"Start date ({start_date}) must be before end date ({end_date})"
                        )
                except ValueError as e:
                    if "time data" in str(e):
                        raise ValueError(
                            f"Invalid date format. Use YYYY-MM-DD. Error: {str(e)}"
                        )
                    raise
            
            return func(self, *args, **kwargs)
        
        return wrapper
    return decorator


def performance_monitor(log_slow_threshold: float = 1.0):
    """
    性能监控装饰器
    记录方法执行时间，如果超过阈值则记录警告
    
    Args:
        log_slow_threshold: 慢查询阈值（秒）
        
    使用示例：
        @performance_monitor(log_slow_threshold=2.0)
        def complex_calculation(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start_time = time.time()
            result = func(self, *args, **kwargs)
            elapsed_time = time.time() - start_time
            
            if elapsed_time > log_slow_threshold:
                print(f"⚠️ Slow operation detected: {func.__name__} took {elapsed_time:.2f}s")
            
            return result
        
        return wrapper
    return decorator
