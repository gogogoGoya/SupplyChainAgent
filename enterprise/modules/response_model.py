"""
Unified response model

All functional methods of enterprisedepartment should use this model to return the results of the implementation and ensure consistency and predictability in the return format.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from enum import Enum
import time


class ResponseStatus(Enum):
    """Response status count"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"  # Partially successful
    PENDING = "pending"  # Pending


@dataclass
class ModuleResponse:
    """
    Harmonized Response Category - Standard Return Format for All Business Modules Approach

    This category provides a uniform return format for all functional methods of enterprisex6/> (financial, HR, production, sale, procurement, inventory).
    The standardized return structure allows for integrated processing and analysis of upper-level systems.

    Attributes:
        Status (Responsestatus): Execute status (success/failed/partial/pending)
        Access (bool): Whether to execute a successful boolean tag to facilitate quick judgement
        consumed_time (float): Estimated time in seconds for method execution in simulation time
        message(str): text description of the results
        module_id (str): The only module identifier for implementing this method
        action_type (str): Action type executed (e.g. "add_revenue", "recruit_employees, etc.)
        Timestamp (float): Time stamp at execution

        Data (Dict [str, Any]: Method-specific returns data, using embedded dictionaries to store results of different dimensions
            - Recommended examples of embedded structures:
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

        errors (List [Dict]: list of errors, each containing code and message
            - Example: [{"code": "INSUFFICIENT_CASH", "message": "现金不足"}]

        Warnings (List [Dict]: Warning message list, without prejudice to execution but needing attention
            - Example: [{"level": "WARNING", "message": "现金余额偏低"}]
        """

    status: ResponseStatus = ResponseStatus.SUCCESS
    success: bool = True  # Whether or not to implement successful boolean tags to facilitate quick judgement
    consumed_time: float = 0.0  # Simulation execution time in seconds
    message: str = ""
    module_type: str = ""
    module_id: str = ""
    action_type: str = ""  # Type of action executed
    timestamp: float = 0.0

    params: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)

    errors: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[Dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        """Initialized post-treatment to ensure consistency between status and access"""
        # Auto set status based on access
        if not self.success:
            if self.status == ResponseStatus.SUCCESS:
                self.status = ResponseStatus.FAILED
        elif self.status == ResponseStatus.FAILED:
            self.success = False

        # Amend to False if there is a mistake but the result is True
        if self.errors and self.success:
            self.success = False
            self.status = ResponseStatus.FAILED

    def set_success(self, success: bool, message: str = ""):
        """Set Success Status"""
        self.success = success
        self.status = ResponseStatus.SUCCESS if success else ResponseStatus.FAILED
        if message:
            self.message = message
        return self

    def set_status(self, status: ResponseStatus):
        """Set Response Status"""
        self.status = status
        self.success = (status == ResponseStatus.SUCCESS)
        return self

    def set_message(self, message: str):
        """Set execution result message"""
        self.message = message
        return self
    def add_error(self, code: str, message: str):
        """Can not open message"""
        self.errors.append({"code": code, "message": message})
        self.success = False
        self.status = ResponseStatus.FAILED
        return self

    def add_warning(self, level: str, message: str):
        """Add Warning Message"""
        self.warnings.append({"level": level, "message": message})
        return self

    def set_consumed_time(self, seconds: float):
        """Set consumption time (in seconds)"""
        self.consumed_time = max(0, seconds)  # Ensure non-negative
        return self

    def set_data(self, key: str, value: Any):
        """Set Embedded Data"""
        self.data[key] = value
        return self

    def add_data(self, key: str, **kwargs):
        """Add embedded data objects"""
        if key not in self.data:
            self.data[key] = {}
        self.data[key].update(kwargs)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Dictionary Format"""
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
        """Acquisition of consumption time"""
        return self.consumed_time
    @classmethod
    def success_response(cls, message: str = "Operation completed successfully",
                        module_id: str = "", action_type: str = "",
                        consumed_time: float = 0.0) -> "ModuleResponse":
        """Create Successful Response"""
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
        """Create failed response"""
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
        """Create Partially Successful Response"""
        return cls(
            status=ResponseStatus.PARTIAL,
            message=message,
            module_id=module_id,
            action_type=action_type,
            consumed_time=consumed_time
        )
