"""
Business module base, providing a harmonized interface and life-cycle approach for all business modules
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
    """Responding to Mixer Category"""
    
    def create_response(self, action_type: str) -> ModuleResponse:
        """Create standard response object"""
        response = ModuleResponse()
        response.module_id = self.module_id
        response.module_type = self.module_type
        response.action_type = action_type
        response.timestamp = time.time()
        
        # Get time consumption from configuration
        if hasattr(self, 'config') and hasattr(self.config, 'TIME_COST'):
            response.consumed_time = self.config.TIME_COST.get(action_type, 60)
        else:
            response.consumed_time = 60  # Default value
        
        return response
    
    def success_response(self, response: ModuleResponse, 
                        message: str, data: dict = None) -> ModuleResponse:
        """Setup Successful Response"""
        response.set_status(ResponseStatus.SUCCESS)
        response.set_message(message)
        if data:
            response.data = data
        
        # Add Warning
        if hasattr(self, 'warnings') and self.warnings:
            for warning in self.warnings:
                response.add_warning(warning["level"], warning["message"])
        
        return response
    
    def error_response(self, response: ModuleResponse, 
                      error_code: str, error_msg: str, 
                      main_message: str = None) -> ModuleResponse:
        """Set Error Response"""
        response.set_status(ResponseStatus.FAILED)
        response.add_error(error_code, error_msg)
        response.set_message(main_message or f"Failed to {response.action_type}")
        return response

    def partial_success_response(self, response: ModuleResponse,
                                 message: str, data: Dict = None,
                                 warnings: List[Dict] = None) -> ModuleResponse:
        """
        Set Partially Successful Response
                
        Args:
            responding objects
            message:
            Data: Response data
            Warnings: Warning list
                        
        Returns:
            ModeuleResponse: Respond objects after setting
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
    """Parameter verification into class"""
    
    def validate_positive_amount(self, amount: float, 
                                 response: ModuleResponse) -> bool:
        """Positive amount certified"""
        if amount <= 0:
            self.error_response(response, "INVALID_AMOUNT", 
                              "Amount must be positive")
            return False
        return True
    
    def validate_choice(self, value: str, valid_choices: list, 
                       param_name: str, response: ModuleResponse) -> bool:
        """Validate options"""
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
        Authentication date format
                
        Args:
            parameter: Date string
            parameter: Parameter Name
            responding objects
                        
        Returns:
            Bool: Verify pass
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
    Business module base category
    All enterprise jobs department modules should inherit this base category
        """
    
    def __init__(self, enterprise, module_id: str = None, **kwargs):
        """
        Initialization of business modules
                
        Args:
            Enterprise: Examples of enterprise
            module_id: Only identifier of the module, if not provided, automatically generated
            **kwargs: Other configuration parameters
                """
        self.enterprise = enterprise
        self.module_id = module_id or f"{self.__class__.__name__.lower()}_{uuid.uuid4().hex[:8]}"
        self.module_name = self.__class__.__name__
        self.config = kwargs
        
        # Module Status
        self.is_active = True
        self.created_at = time.time()
        self.last_updated = time.time()
        
        # Record action history of module execution
        self.action_history = []
        
        # Initialization module
        self._initialize()
    
    def _initialize(self):
        """
        module initialises logic, and subclasses can be rewritten for custom initialization
                """
        pass

    def message_handle(self, message: Dict) -> Dict:
        """
        Process messages from other modules or external systems
                
        Args:
            message: Dictionary with message content, at least " type" and "content" keys
                        
        Returns:
            dict: Process results with "status" and "message" keys
                """
        return {
            "status": "success",
            "message": f"Message received: {message.get('content', 'No content')}"
        }
    
    def get_module_by_type(self,module_type):
        """Fetch the first instance of the specified type of module from enterprise.business modules"""
        if hasattr(self.enterprise, 'business_modules') and module_type in self.enterprise.business_modules:
            modules = self.enterprise.business_modules[module_type]
            return modules[0] if modules else None
        return None

    def get_module_info(self) -> Dict:
        """
        Get Module Basic Information
                
        Returns:
            dict: module information
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
        Get module status
        Subcategory should rewrite this to provide detailed status information
                
        Returns:
            dict: modular status
                """
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "is_active": self.is_active,
            "action_history_count": len(self.action_history)
        }
    
    def _record_action(self, action: Dict):
        """
        Record action to history
                
        Args:
            Action: Execute Action
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
        Update module configuration
                
        Args:
            **kwargs: Configuration Parameters to Update
                """
        self.config.update(kwargs)
        self.last_updated = time.time()
    
    def activate(self):
        """
        Activate Module
                """
        self.is_active = True
        self.last_updated = time.time()
    
    def deactivate(self):
        """
        Disable module
                """
        self.is_active = False
        self.last_updated = time.time()

    def __str__(self):
        return f"{self.module_name} (ID: {self.module_id}) for Enterprise {self.enterprise.id}"

class EnhancedBaseModule(BaseBusinessModule, ResponseMixin, ValidationMixin):
    """Enhanced base module class"""
    
    def __init__(self, enterprise, module_id: str, config=None):
        super().__init__(enterprise, module_id)
        self.config = config
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Secure Access Configuration Value
                
        Args:
            Key: Configure Keyname
            default: default
                        
        Returns:
            Configure values or defaults
                """
        if self.config and hasattr(self.config, key):
            return getattr(self.config, key)
        return default
    
    def batch_execute(self, operations: List[Dict]) -> ModuleResponse:
        """
        Batch validation of multiple methods (validation only, not real logic)

        Args:
            Organisations: Operations list, each element containing:
            {
                "action_name": "method_name",
                "action_param": {...}
            }

        Returns:
            ModeuleResponse: Verify Results
                """

        # Create main response object
        response = self.create_response("batch_execute")

        errors = []
        # Operation by Operation
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
                # Create a temporary response object (for validation)
                temp_response = self.create_response(action_name)

                # Get a way to sign
                sig = inspect.signature(method)

                # Check for redundant parameters
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

                # Build valid parameters
                valid_params = {
                    k: v for k, v in action_param.items()
                    if k in sig.parameters
                }

                # If the method supports response arguments, enter
                if "response" in sig.parameters:
                    valid_params["response"] = temp_response
                if getattr(method, "_skip_dry_run_validation", False):
                    continue
                if "dry_run" in sig.parameters:
                    valid_params["dry_run"] = True
                    # Only visible dry_run actions can be called at the pre-check stage.
                    # This avoids the unrollable side effects of the validation phase on historical actions that have not materialized dry_run.
                    result = method(**valid_params)
                else:
                    continue

                # Log error if returned failed
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
