from functools import wraps
import time
import traceback
import inspect
from typing import Callable, Any
from enterprise.modules.response_model import ModuleResponse, ResponseStatus


def skip_dry_run_validation(func: Callable) -> Callable:
    """
    Marks that the action does not require a real call at the dry_run verification stage.
        """
    setattr(func, "_skip_dry_run_validation", True)
    return func


def with_response(action_type: str = None):
    """
    Autocreate and process ModuleResponse decorators
        
    Function:
    1. Automatically create responding objects
    2. Automatic injection of responding objects into method parameters
    Harmonization of anomalies
    Automatically add warning messages
        
    Args:
        action_type: Operation type name; defaults to the method name.
                
    Example used:
        @with_response("add_revenue")
        def add_revenue(self, amount, source, response: ModuleResponse = None):
            # Response has been created and injected
            if amount <= 0:
                return self.error_response(response, "INVALID_AMOUNT", "Amount must be positive")
                        
            Business logic
                        
            return self.success_response(response, "Revenue added", {...})
        """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Determine type of operation
            _action_type = action_type or func.__name__
            
            # Create Response Object
            response = self.create_response(_action_type)
            
            try:
                sig = inspect.signature(func)
                bound_args = sig.bind(self, *args, **kwargs)
                bound_args.apply_defaults()

                # Remove self and response (if any)
                input_params = {
                    k: v for k, v in bound_args.arguments.items()
                    if k not in ('self', 'response')
                }

                response.params = input_params
            except Exception:
                # Parameter log failure should not affect the main process
                response.params = {
                    "args": args,
                    "kwargs": kwargs
                }
            try:
                # Implementation method to inject response into kwargs
                kwargs['response'] = response
                result = func(self, *args, **kwargs)
                
                # If the method returns ModeuleResponse, go straight back
                if isinstance(result, ModuleResponse):
                    return result
                
                # If the method returns to the dictionary, package it as a successful sound Response
                if isinstance(result, dict):
                    return self.success_response(
                        response, 
                        f"{_action_type} completed successfully", 
                        result
                    )
                
                # Other cases, return original results (not recommended)
                return result
                
            except ValueError as e:
                # Parameter Authentication Error
                return self.error_response(
                    response, 
                    "VALIDATION_ERROR", 
                    str(e),
                    f"Validation failed for {_action_type}"
                )
            except KeyError as e:
                # Key does not contain error
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
    Decorators with positive parameters
        
    Args:
        param_name: Name of the parameter to validate.
                
    Example used:
        @validate_positive("amount")
        def add_revenue(self, amount, source):
            # Amount has been certified as positive
            ...
        """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Fetch Parameter Value
            value = kwargs.get(param_name)
            
            # If not found in kwargs, try to get from args
            if value is None and len(args) > 0:
                # Fetch function signature, find parameter position
                import inspect
                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())
                
                if param_name in param_names:
                    param_index = param_names.index(param_name)
                    # Note: Self takes the first position, so it's needed-1
                    if param_index <= len(args):
                        value = args[param_index - 1]
            
            # Authentication
            if value is not None and value <= 0:
                raise ValueError(f"{param_name} must be positive, got {value}")
            
            return func(self, *args, **kwargs)
        
        return wrapper
    return decorator


def validate_choice(param_name: str, valid_choices_attr: str):
    """
    Decorator to verify parameters in a valid option
        
    Args:
        param_name: Name of the parameter to validate.
        valid_choices_attr: Name of the valid-choice list on `self.config`.
                
    Example used:
        @validate_choice("source", "REVENUE_SOURCES")
        def add_revenue(self, amount, source):
            # `source` has been validated against the configured choices.
            ...
        """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Get a list of valid options
            if not hasattr(self, 'config'):
                raise AttributeError("Instance must have 'config' attribute")
            
            valid_choices = getattr(self.config, valid_choices_attr, None)
            if valid_choices is None:
                raise AttributeError(f"Config has no attribute '{valid_choices_attr}'")
            
            # Fetch Parameter Value
            value = kwargs.get(param_name)
            
            # If not found in kwargs, try to get from args
            if value is None and len(args) > 0:
                import inspect
                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())
                
                if param_name in param_names:
                    param_index = param_names.index(param_name)
                    if param_index <= len(args):
                        value = args[param_index - 1]
            
            # Authentication
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
    Decorator to verify date range
        
    Args:
        start_param: Name of the start-date parameter.
        end_param: Name of the end-date parameter.
                
    Example used:
        @validate_date_range()
        def generate_report(self, start_date, end_date):
            # Date range verified
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
    Performance Monitor Decorator
    Record the execution time of the method and the warning if the threshold is exceeded
        
    Args:
        log_slow_threshold: Slow query threshold (sec)
                
    Example used:
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
