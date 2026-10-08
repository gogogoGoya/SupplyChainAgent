from datetime import datetime
from typing import Dict, List, Tuple, Optional
from enum import Enum
from dataclasses import dataclass
from enterprise.modules.base_business_module import EnhancedBaseModule
from enterprise.modules.response_model import ModuleResponse, ResponseStatus
from enterprise.modules.decorators import with_response, validate_positive, validate_choice, skip_dry_run_validation
from config.module_config import HRConfig
import time
class DepartmentType(Enum):
    """department Type count"""
    HR = "人力资源部门"
    PRODUCTION = "生产部门"
    SALES = "销售部门"
    PROCUREMENT = "采购部门"
    INVENTORY = "仓储部门"
    FINANCE = "财务管理部门"

@dataclass
class DepartmentConfig:
    """department Configure data class"""
    name: str
    wage_per_person: float
    recruit_cost: float
    recruit_cycle: int = 1

@dataclass
class RecruitmentRecord:
    """Recruitment records data category"""
    record_id: str
    department: DepartmentType
    num_people: int
    recruit_cost: float
    start_time: int
    complete_time: int
    status: str = "进行中"

class HRManager(EnhancedBaseModule):
    """
    Human resources management module

    Responsible for enterprise staffing, recruitment, payroll management, utilization statistics and human cost accounting
        """

    def __init__(self, enterprise, module_id=None, config: HRConfig = None):
        """
        Initializing Human Resource Manager

        Args:
            Enterprise: Examples of enterprise
            parameter: Only identification of modules (optional)
            Config: HR Configuration Object (optional, default HRonfig())

        Raises:
            ValueError: empty object
                """
        if not enterprise:
            raise ValueError("enterprise对象不能为空")

        # Use configuration or default configuration
        self.config = config or HRConfig()

        # Call Parent Initialization
        super().__init__(
            enterprise,
            module_id or f"hr_{enterprise.id}",
            self.config
        )
        self.module_type = "HRManager"
        # Create department Configure Dictionary from Configuration
        self.DEPARTMENT_CONFIGS = {
            DepartmentType.HR: DepartmentConfig(
                name="人力资源部门",
                wage_per_person=self.config.DEPARTMENT_WAGES["HR"],
                recruit_cost=self.config.DEPARTMENT_RECRUIT_COSTS["HR"],
                recruit_cycle=self.config.RECRUIT_CYCLE
            ),
            DepartmentType.PRODUCTION: DepartmentConfig(
                name="生产部门",
                wage_per_person=self.config.DEPARTMENT_WAGES["PRODUCTION"],
                recruit_cost=self.config.DEPARTMENT_RECRUIT_COSTS["PRODUCTION"],
                recruit_cycle=self.config.RECRUIT_CYCLE
            ),
            DepartmentType.SALES: DepartmentConfig(
                name="销售部门",
                wage_per_person=self.config.DEPARTMENT_WAGES["SALES"],
                recruit_cost=self.config.DEPARTMENT_RECRUIT_COSTS["SALES"],
                recruit_cycle=self.config.RECRUIT_CYCLE
            ),
            DepartmentType.PROCUREMENT: DepartmentConfig(
                name="采购部门",
                wage_per_person=self.config.DEPARTMENT_WAGES["PROCUREMENT"],
                recruit_cost=self.config.DEPARTMENT_RECRUIT_COSTS["PROCUREMENT"],
                recruit_cycle=self.config.RECRUIT_CYCLE
            ),
            DepartmentType.INVENTORY: DepartmentConfig(
                name="仓储部门",
                wage_per_person=self.config.DEPARTMENT_WAGES["INVENTORY"],
                recruit_cost=self.config.DEPARTMENT_RECRUIT_COSTS["INVENTORY"],
                recruit_cycle=self.config.RECRUIT_CYCLE
            ),
            DepartmentType.FINANCE: DepartmentConfig(
                name="财务管理部门",
                wage_per_person=self.config.DEPARTMENT_WAGES["FINANCE"],
                recruit_cost=self.config.DEPARTMENT_RECRUIT_COSTS["FINANCE"],
                recruit_cycle=self.config.RECRUIT_CYCLE
            ),
        }

        # Extract common properties from configuration
        self.MAX_RECRUIT_PER_TIME = self.config.MAX_RECRUIT_PER_TIME
        self.MIN_RECRUIT_PER_TIME = self.config.MIN_RECRUIT_PER_TIME
        self.UTILIZATION_SURPLUS_THRESHOLD = self.config.UTILIZATION_SURPLUS_THRESHOLD
        self.UTILIZATION_SHORTAGE_THRESHOLD = self.config.UTILIZATION_SHORTAGE_THRESHOLD
        self.OPTIMAL_UTILIZATION_LOWER = self.config.OPTIMAL_UTILIZATION_LOWER
        self.OPTIMAL_UTILIZATION_UPPER = self.config.OPTIMAL_UTILIZATION_UPPER

        # department Staffing
        self.department_employees: Dict[DepartmentType, int] = {
            dept: 0 for dept in DepartmentType
        }
        # department Utilization
        self.department_utilization: Dict[DepartmentType, float] = {
            dept: 0.0 for dept in DepartmentType
        }
        # Recruitment records
        self.recruitment_records: List[RecruitmentRecord] = []
        self.recruitment_counter = 0
        # Wage history
        self.salary_history: List[Dict] = []
        # Cost statistics
        self.cumulative_recruit_cost = 0.0
        self.cumulative_salary_cost = 0.0
        # Staff loss records
        self.employee_attrition_history: List[Dict] = []
        # Recruitment costs and pay base attributes (data initializer.py)
        self.recruitment_cost = {
            dept.value: config.recruit_cost 
            for dept, config in self.DEPARTMENT_CONFIGS.items()
        }
        self.salary_base = {
            dept.value: config.wage_per_person 
            for dept, config in self.DEPARTMENT_CONFIGS.items()
        }
        self.allocated_workers = {dept: 0 for dept in DepartmentType}
        self.assignments = {}

    @staticmethod
    def _resolve_recruit_cycle_days(recruit_cycle) -> int:
        """The recruitment cycle defaults a working day to ensure that the standard configuration arrives on the next day."""
        try:
            cycle_days = int(recruit_cycle)
        except (TypeError, ValueError):
            cycle_days = 1
        return max(1, cycle_days)

    def _get_staffing_relaxation_policy(self) -> Dict:
        """Reads the scene level weak-man strategy to avoid the break of the Beer Game main chain by staffing fail."""
        try:
            from config.simulation_preset_config import get_runtime_injection_config

            policy = (get_runtime_injection_config() or {}).get("staffing_relaxation_policy") or {}
        except Exception:
            policy = {}

        if not policy.get("enabled"):
            return {"enabled": False}

        target_enterprise_ids = policy.get("enterprise_ids") or []
        target_role_tags = set(policy.get("target_role_tags") or [])
        if target_enterprise_ids and self.enterprise.id not in target_enterprise_ids:
            return {"enabled": False}
        if target_role_tags and not (set(getattr(self.enterprise, "role_tags", []) or []) & target_role_tags):
            return {"enabled": False}

        return {
            "enabled": True,
            "virtual_available_workers": max(0, int(policy.get("virtual_available_workers", 0) or 0)),
            "allow_soft_assignment": bool(policy.get("allow_soft_assignment", True)),
            "allow_soft_release": bool(policy.get("allow_soft_release", True)),
        }

    def _get_relaxed_available_workers(self, total: int, allocated: int) -> int:
        """Under the downsized model, more relaxed availability is provided to the business modules."""
        physical_available = max(0, total - allocated)
        policy = self._get_staffing_relaxation_policy()
        if not policy.get("enabled"):
            return physical_available
        return max(physical_available, policy.get("virtual_available_workers", 0))

    def _recalculate_department_utilization(self, department: DepartmentType) -> None:
        """
        Recost department utilization factor based on current and assigned population.
                """
        total = max(0, self.department_employees.get(department, 0))
        allocated = max(0, self.allocated_workers.get(department, 0))
        if total <= 0:
            self.department_utilization[department] = 0.0
            return
        self.department_utilization[department] = min(1.0, allocated / total)

    def _get_pending_recruitment_by_department(self) -> Dict[DepartmentType, int]:
        """
        Summarize all outstanding recruitments at department.
                """
        pending_by_department = {dept: 0 for dept in DepartmentType}
        for record in self.recruitment_records:
            if record.status == "进行中":
                pending_by_department[record.department] += record.num_people
        return pending_by_department

    @with_response("initialize_staffing")
    def initialize_staffing(self, initial_staffing: Dict[str, int], dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Initialization of department Staffing

        Args:
            initial_staffing: Dictionary containing each department initial staffing, key department name, value of personnel
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified response object with initial results
                """
        # Update department Staffing
        for dept_name, num_employees in initial_staffing.items():
            # Number of certifying officers
            if not isinstance(num_employees, int) or num_employees < 0:
                return self.error_response(
                    response,
                    "INVALID_EMPLOYEE_COUNT",
                    f"{dept_name}的人员数量必须是非负整数"
                )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        for dept_name, num_employees in initial_staffing.items():
            # Finds the corresponding department type (without case sensitive)
            dept_type = self._convert_to_department_type(dept_name)
            self.department_employees[dept_type] = num_employees
            # Initialization department Utilization
            self.department_utilization[dept_type] = 0.0

        # Returns Successful Response
        return self.success_response(
            response,
            "部门人员配置初始化成功",
            {
                "department_employees": {dept.value: count for dept, count in self.department_employees.items()}
            }
        )

    @with_response("get_department_employees")
    def get_department_employees(self, department, response: ModuleResponse = None) -> ModuleResponse:
        """
        Get specified department Number of employees

        Args:
            Department: department Type or department Name string
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified response object with department number of employees
                """
        dept_type = self._convert_to_department_type(department)
        employee_count = self.department_employees.get(dept_type, 0)

        # Returns Successful Response
        return self.success_response(
            response,
            f"成功获取{dept_type.value}的员工数",
            {
                "department": dept_type.value,
                "count": employee_count
            }
        )
    
    @with_response("get_all_employees")
    def get_all_employees(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access to enterprise total staff

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified response object with enterprise total number of employees
                """
        total_employees = sum(self.department_employees.values())

        # Returns Successful Response
        return self.success_response(
            response,
            "成功获取企业总员工数",
            {
                "total_employees": total_employees
            }
        )

    @with_response("get_department_utilization")
    def get_department_utilization(self, department, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access to specified department utilization factor

        Args:
            Department: department Type or department Name string
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Harmonized response subject with department utilization factor
                """
        dept_type = self._convert_to_department_type(department)
        utilization = self.department_utilization.get(dept_type, 0.0)

        # Returns Successful Response
        return self.success_response(
            response,
            f"成功获取{dept_type.value}的利用率",
            {
                "department": dept_type.value,
                "utilization": utilization
            }
        )

    @with_response("get_average_utilization")
    def get_average_utilization(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access enterprise average utilization factor

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target with enterprise average utilization factor
                """
        utilizations = list(self.department_utilization.values())
        if not utilizations:
            average_utilization = 0.0
        else:
            average_utilization = sum(utilizations) / len(utilizations)

        # Returns Successful Response
        return self.success_response(
            response,
            "成功获取企业平均利用率",
            {
                "average_utilization": average_utilization
            }
        )
    
    
    @with_response("handle_recruitment")
    @validate_positive("num_people")
    def handle_recruitment(
        self,
        department,
        num_people: int,
        dry_run: bool = False,
        response: ModuleResponse = None
    ) -> ModuleResponse:
        """
        Launching of recruitment processes, validation of funds and creation of recruitment records

        Args:
            Department: department Type or department Name string
            parameter: Recruitments
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified response with recruitment results
                """
        # Parameter Authentication
        department = self._convert_to_department_type(department)
        finance_manager = super().get_module_by_type("FinanceManager")

        # Addressing different types of return
        balance_result = finance_manager.get_balance()
        if isinstance(balance_result, (int, float)):
            current_cash = balance_result
        elif hasattr(balance_result, 'data'):
            current_cash = balance_result.data.get("balance", 0) if isinstance(balance_result.data, dict) else 0
        elif isinstance(balance_result, dict):
            current_cash = balance_result.get("balance", 0)
        else:
            current_cash = 0

        if current_cash < 0:
            return self.error_response(
                response,
                "INVALID_CASH_BALANCE",
                "现金不能为负数"
            )

        # Number of confirmed recruits
        if not isinstance(num_people, int) or num_people < 1 or num_people > self.MAX_RECRUIT_PER_TIME:
            return self.error_response(
                response,
                "INVALID_RECRUIT_COUNT",
                f"招聘人数必须在1-{self.MAX_RECRUIT_PER_TIME}之间"
            )

        # Fetch department Configuration
        dept_config = self.DEPARTMENT_CONFIGS[department]
        recruit_cost = dept_config.recruit_cost * num_people

        # Verification of adequacy of funds
        if current_cash < recruit_cost:
            return self.error_response(
                response,
                "INSUFFICIENT_FUNDS",
                f"资金不足，需要 ¥{recruit_cost:.2f}，当前现金 ¥{current_cash:.2f}"
            )
        
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")
        
        # Create a recruitment record
        record_id = f"REC_{self.recruitment_counter}"
        self.recruitment_counter += 1

        current_time = self.enterprise.time_manager.get_day()
        recruit_cycle_days = self._resolve_recruit_cycle_days(dept_config.recruit_cycle)
        complete_time = current_time + recruit_cycle_days
        record = RecruitmentRecord(
            record_id=record_id,
            department=department,
            num_people=num_people,
            recruit_cost=recruit_cost,
            start_time=current_time,
            complete_time=complete_time,
            status="进行中"
        )

        self.recruitment_records.append(record)
        self.cumulative_recruit_cost += recruit_cost

        # Recording of recruitment costs
        result = finance_manager.add_cost(amount=recruit_cost, category="labor_cost", description="Recruitment costs")

        # Returns Successful Response
        return self.success_response(
            response,
            f"成功发起{department.value}的招聘流程,预计{recruit_cycle_days}个工作日后完成正式招聘入职",
            {
                "record_id": record.record_id,
                "department": department.value,
                "num_people": record.num_people,
                "recruit_cost": record.recruit_cost,
                "complete_time": record.complete_time,
                "recruit_cycle_days": recruit_cycle_days,
                "status": record.status
            }
        )

    @skip_dry_run_validation
    @with_response("process_recruitment_completion")
    def process_recruitment_completion(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Processing completed recruitment and automatic update of department personnel

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified response with results of recruitment
                """
        completed_records = []
        total_cost = 0.0
        current_time = self.enterprise.time_manager.get_day()

        for record in self.recruitment_records:
            if record.status == "进行中" and current_time >= record.complete_time:
                # Update department personnel
                department = record.department
                self.department_employees[department] += record.num_people
                self._recalculate_department_utilization(department)
                # Update Record Status
                record.status = "已到岗"
                completed_records.append(record.record_id)
                total_cost += record.recruit_cost

        # Returns Successful Response
        return self.success_response(
            response,
            f"成功处理 {len(completed_records)} 个招聘完成记录",
            {
                "completed_records": completed_records,
                "total_cost": total_cost,
                "total_completed": len(completed_records)
            }
        )
    
    @with_response("get_pending_recruitments")
    def get_pending_recruitments(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Getting an ongoing recruitment list

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: A unified response with a list of ongoing recruitments
                """
        pending_recruitments = [
            {
                "record_id": r.record_id,
                "department": r.department.value,
                "num_people": r.num_people,
                "recruit_cost": r.recruit_cost,
                "start_time": r.start_time,
                "complete_time": r.complete_time,
                "status": r.status
            }
            for r in self.recruitment_records if r.status == "进行中"
        ]

        # Returns Successful Response
        return self.success_response(
            response,
            f"成功获取 {len(pending_recruitments)} 个进行中的招聘记录",
            {
                "pending_recruitments": pending_recruitments,
                "total_count": len(pending_recruitments)
            }
        )
    
    @with_response("get_recruitment_history")
    def get_recruitment_history(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Access all recruitment history records

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target with recruitment history
                """
        recruitment_history = [
            {
                "record_id": r.record_id,
                "department": r.department.value,
                "num_people": r.num_people,
                "recruit_cost": r.recruit_cost,
                "start_time": r.start_time,
                "complete_time": r.complete_time,
                "status": r.status
            }
            for r in self.recruitment_records
        ]

        # Returns Successful Response
        return self.success_response(
            response,
            f"成功获取 {len(recruitment_history)} 条招聘历史记录",
            {
                "recruitment_history": recruitment_history,
                "total_count": len(recruitment_history)
            }
        )
    

    def _long_horizon_salary_cost_multiplier(self) -> float:
        runtime_config = getattr(self.enterprise, "runtime_injection_config", None)
        if not isinstance(runtime_config, dict):
            controller = getattr(self.enterprise, "controller", None)
            runtime_config = getattr(controller, "runtime_injection_config", None)
        if not isinstance(runtime_config, dict):
            try:
                from config.simulation_preset_config import get_runtime_injection_config

                runtime_config = get_runtime_injection_config() or {}
            except Exception:
                runtime_config = {}

        policy = runtime_config.get("long_horizon_cost_policy") or {}
        target_ids = set(policy.get("target_enterprise_ids") or [])
        if not policy.get("enabled") or (
            target_ids and getattr(self.enterprise, "id", None) not in target_ids
        ):
            return 1.0
        try:
            return max(0.0, float(policy.get("salary_cost_multiplier", 1.0)))
        except (TypeError, ValueError):
            return 1.0
    
    @with_response("calculate_department_salary")
    def calculate_department_salary(self, department, response: ModuleResponse = None) -> ModuleResponse:
        """
        Calculates the total salary of department

        Args:
            Department: department Type or department Name string
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: A unified response with department total wages
                """
        dept_type = self._convert_to_department_type(department)

        num_employees = self.department_employees[dept_type]
        base_wage_per_person = self.DEPARTMENT_CONFIGS[dept_type].wage_per_person
        cost_multiplier = self._long_horizon_salary_cost_multiplier()
        wage_per_person = base_wage_per_person * cost_multiplier
        total_salary = num_employees * wage_per_person


        # Returns Successful Response
        return self.success_response(
            response,
            f"成功计算{dept_type.value}的工资总额",
            {
                "department": dept_type.value,
                "num_employees": num_employees,
                "wage_per_person": wage_per_person,
                "base_wage_per_person": base_wage_per_person,
                "cost_multiplier": cost_multiplier,
                "total_salary": total_salary
            }
        )
    
    @with_response("calculate_total_salary")
    def calculate_total_salary(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Calculate enterprise gross salary

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target with enterprise gross salary
                """
        total = 0.0
        department_breakdown = {}

        for department in DepartmentType:
            # Draw department gross salary from ModuleResponse
            dept_salary_response = self.calculate_department_salary(department)
            if dept_salary_response.success:
                dept_salary = dept_salary_response.data["total_salary"]
                total += dept_salary
                department_breakdown[department.value] = {
                    "num_employees": dept_salary_response.data["num_employees"],
                    "wage_per_person": dept_salary_response.data["wage_per_person"],
                    "total_salary": dept_salary
                }

        # Returns Successful Response
        return self.success_response(
            response,
            "成功计算企业总工资",
            {
                "total_salary": total,
                "department_breakdown": department_breakdown
            }
        )
    
    @with_response("process_salary_payment")
    def process_salary_payment(self, dry_run: bool = False, response: ModuleResponse = None) -> ModuleResponse:
        """
        Implement payroll payment processes, record history, update costs

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target with pay results
                """
        finance_manager = super().get_module_by_type("FinanceManager")

        # Addressing different types of return
        balance_result = finance_manager.get_balance()
        if isinstance(balance_result, (int, float)):
            available_cash = balance_result
        elif hasattr(balance_result, 'data'):
            # ModeuleResponse Object
            available_cash = balance_result.data.get("balance", 0) if isinstance(balance_result.data, dict) else 0
        elif isinstance(balance_result, dict):
            available_cash = balance_result.get("balance", 0)
        else:
            available_cash = 0

        if available_cash < 0:
            return self.error_response(
                response,
                "INVALID_CASH_BALANCE",
                "现金不能为负数"
            )

        # Draw the gross salary from ModuleResponse
        total_salary_response = self.calculate_total_salary()
        if not total_salary_response.success:
            return self.error_response(
                response,
                "SALARY_CALCULATION_ERROR",
                "无法计算总工资"
            )

        total_salary = total_salary_response.data["total_salary"]

        # No payment for no employees
        if total_salary == 0:
            return self.success_response(
                response,
                "无员工，无需支付工资",
                {"total_salary": total_salary}
            )

        # Insufficient funding
        if available_cash < total_salary:
            return self.error_response(
                response,
                "INSUFFICIENT_FUNDS",
                f"资金不足，需要 ¥{total_salary:.2f}，当前现金 ¥{available_cash:.2f}"
            )
        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")

        # Recording of salary payments
        salary_record = {
            "time": self.enterprise.time_manager.get_day(),
            "amount": total_salary,
            "total_salary": total_salary,
            "department_breakdown": {}
        }

        # Implementation cost records
        result = finance_manager.add_cost(amount=total_salary, category="labor_cost", description="Salary payment")

        # Addressing different types of return
        cost_success = result.success
        if not cost_success:
            cost_error = result.get("error", "未知错误") if isinstance(result, dict) else getattr(result, "message", "未知错误")
        else:
            cost_error = None

        if not cost_success:
            return self.error_response(
                response,
                "COST_RECORD_FAILED",
                f"成本记录失败: {cost_error}"
            )

        # Fill department Details
        for department in DepartmentType:
            # Draw department from ModuleResponse
            dept_salary_response = self.calculate_department_salary(department)
            if dept_salary_response.success:
                dept_salary = dept_salary_response.data["total_salary"]
                dept_employees = self.department_employees[department]
                salary_record["department_breakdown"][department.value] = {
                    "employees": dept_employees,
                    "salary_total": dept_salary
                }

        # Update historical records and costs
        self.salary_history.append(salary_record)
        self.cumulative_salary_cost += total_salary

        # Returns Successful Response
        return self.success_response(
            response,
            "成功执行工资支付",
            {
                "total_salary": total_salary,
                "available_cash_after": available_cash - total_salary,
                "salary_record": salary_record
            }
        )
    
    @with_response("get_salary_history")
    def get_salary_history(self, limit: Optional[int] = None, response: ModuleResponse = None) -> ModuleResponse:
        """
        Get a pay history, if limit returns to the net

        Args:
            Limited number of returns (optional)
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: A unified response with a history of wage payments
                """
        if limit is None:
            history = self.salary_history
        else:
            history = self.salary_history[-limit:]

        # Returns Successful Response
        return self.success_response(
            response,
            f"成功获取 {len(history)} 条工资支付历史记录",
            {
                "salary_history": history,
                "total_count": len(history),
                "limit": limit
            }
        )
    
    @with_response("get_latest_salary_payment")
    def get_latest_salary_payment(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Obtaining last salary payment records

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified response with last pay history
                """
        if not self.salary_history:
            return self.error_response(
                response,
                "NO_SALARY_HISTORY",
                "暂无工资支付记录"
            )

        latest_record = self.salary_history[-1]
        return self.success_response(
            response,
            "成功获取最近一次工资支付记录",
            latest_record
        )
    # == sync, corrected by elderman ==
    
    @with_response("get_cumulative_recruit_cost")
    def get_cumulative_recruit_cost(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Acquisition of accumulated recruitment costs

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target audience with accumulated recruitment costs
                """
        return self.success_response(
            response,
            "成功获取累计招聘成本",
            {
                "cumulative_recruit_cost": self.cumulative_recruit_cost
            }
        )

    @with_response("get_cumulative_salary_cost")
    def get_cumulative_salary_cost(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Accumulated wage costs

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target with accumulated salary costs
                """
        return self.success_response(
            response,
            "成功获取累计工资成本",
            {
                "cumulative_salary_cost": self.cumulative_salary_cost
            }
        )

    @with_response("get_total_human_cost")
    def get_total_human_cost(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Total labour cost (recruitment + wages)

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified target with total human cost
                """
        total_cost = self.cumulative_recruit_cost + self.cumulative_salary_cost

        return self.success_response(
            response,
            "成功获取总人力成本",
            {
                "total_human_cost": total_cost,
                "cumulative_recruit_cost": self.cumulative_recruit_cost,
                "cumulative_salary_cost": self.cumulative_salary_cost
            }
        )

    @with_response("get_cost_breakdown")
    def get_cost_breakdown(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Obtain cost breakdown details

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified response object with cost breakdown details
                """
        # Draw total manpower costs from ModuleResponse
        total_cost_response = self.get_total_human_cost(response)
        if not total_cost_response.success:
            return self.error_response(
                response,
                "COST_CALCULATION_ERROR",
                "无法计算总人力成本"
            )

        total = total_cost_response.data["total_human_cost"]

        # Calculate cost ratio
        recruit_cost_ratio = self.cumulative_recruit_cost / total if total > 0 else 0.0
        salary_cost_ratio = self.cumulative_salary_cost / total if total > 0 else 0.0

        return self.success_response(
            response,
            "成功获取成本分解详情",
            {
                "recruit_cost": self.cumulative_recruit_cost,
                "salary_cost": self.cumulative_salary_cost,
                "total_cost": total,
                "recruit_cost_ratio": recruit_cost_ratio,
                "salary_cost_ratio": salary_cost_ratio
            }
        )
    
    
    def get_summary(self) -> dict:
        """Get a complete state snapshot of the HR module (internal method, return dictionary)"""
        # Calculate the number of recruitments in progress (direct access to data rather than call back to ModeuleResponse)
        pending_recruitments_count = len([
            r for r in self.recruitment_records
            if r.status in ["进行中", "pending"]
        ])

        # Calculate total staff loss (direct access data)
        total_attrition = len(self.employee_attrition_history)

        # Calculation of total staff (direct calculation)
        total_employees = sum(self.department_employees.values())

        # Calculated average utilization rate (direct calculation)
        utilizations = list(self.department_utilization.values())
        average_utilization = sum(utilizations) / len(utilizations) if utilizations else 0.0

        # Calculate total manpower costs (direct calculation)
        total_human_cost = self.cumulative_recruit_cost + self.cumulative_salary_cost

        return {
            "enterprise_id": self.enterprise.id,
            "total_employees": total_employees,
            "department_employees": {
                dept.value: count for dept, count in self.department_employees.items()
            },
            "average_utilization": average_utilization,
            "department_utilization": {
                dept.value: util for dept, util in self.department_utilization.items()
            },
            "utilization_status": {
                dept.value: self._get_utilization_status(dept)
                for dept in DepartmentType
            },
            "salary_cost_total": self.cumulative_salary_cost,
            "recruit_cost_total": self.cumulative_recruit_cost,
            "total_human_cost": total_human_cost,
            "pending_recruitments": pending_recruitments_count,
            "total_attrition": total_attrition,
            "salary_payment_times": len(self.salary_history)
        }
    
        
    @with_response("process_employee_attrition")
    def process_employee_attrition(
        self,
        department_name,
        num_people: int,
        reason: str,
        dry_run: bool = False,
        response: ModuleResponse = None
    ) -> ModuleResponse:
        """Dismissal of staff, update of department personnel, recording of reasons for dismissal"""
        department_type = self._convert_to_department_type(department_name)
        
        if not isinstance(num_people, int) or num_people < 0:
            raise ValueError("解聘人数必须是非负整数")
        
        if num_people == 0:
            return self.error_response(
                response,
                "INVALID_PARAM",
                "解聘人数不能为0"
            )
        
        current_employees = self.department_employees[department_type]
        
        if num_people > current_employees:
            return self.error_response(
                response,
                "INVALID_PARAM",
                f"部门{department_type.value}当前只有{current_employees}人,无法解聘{num_people}人"
            )
        
        hr_result = self.get_available_workers(department_type)
        available_workers = hr_result.data.get("count", 0)
        if num_people > available_workers:
            return self.error_response(
                response,
                "INVALID_PARAM",
                f"部门{department_type.value}当前有目标员工正处于工作中,无法直接解聘"
            )

        if dry_run:
            return self.success_response(response, "DRY_RUN_SUCCESS", f"测试通过")


        self.department_employees[department_type] -= num_people
        self._recalculate_department_utilization(department_type)
        
        attrition_record = {
            "time": self.enterprise.time_manager.get_day(),
            "department": department_name,
            "num_people": num_people,
            "reason": reason,
            "remaining_employees": self.department_employees[department_type]
        }
        
        self.employee_attrition_history.append(attrition_record)
        
        return self.success_response(
            response,
            "成功处理员工流失",
            attrition_record
        )

    @with_response("get_state")
    def get_state(self, response: ModuleResponse = None) -> ModuleResponse:
        """
        Get Current Module Status

        Args:
            Response: Respond objects (injected by decorator)

        Returns:
            ModuleResponse: Unified response object with modular status
                """
        try:
            # Get HR Status Summary
            hr_summary = self.get_summary()
            staffing_relaxation_policy = self._get_staffing_relaxation_policy()

            # Construct a list of employees (Observer desired format)
            employees = []
            for dept, count in self.department_employees.items():
                if count > 0:
                    employees.append({
                        "department": dept.name,
                        "count": count,
                        "allocated":self.allocated_workers.get(dept, 0.0),
                        "utilization": self.department_utilization.get(dept, 0.0)
                    })

            # Access to recent recruitment history (up to 5)
            recent_recruitment_history = []
            for r in self.recruitment_records[-5:]:
                recent_recruitment_history.append({
                    "record_id": r.record_id,
                    "department": r.department.value,
                    "num_people": r.num_people,
                    "recruit_cost": r.recruit_cost,
                    "start_time": r.start_time,
                    "complete_time": r.complete_time,
                    "status": r.status
                })
            pending_by_department = self._get_pending_recruitment_by_department()

            state = {
                # "module_id": self.module_id,
                "module_type": self.module_type,
                "employees": employees,  # Expected Fields for Observer
                "department_staffing": {
                    dept.value: {
                        "count": self.department_employees.get(dept, 0),
                        "allocated": self.allocated_workers.get(dept, 0),
                        "available": self._get_relaxed_available_workers(
                            self.department_employees.get(dept, 0),
                            self.allocated_workers.get(dept, 0)
                        ),
                        "physical_available": max(
                            0,
                            self.department_employees.get(dept, 0) - self.allocated_workers.get(dept, 0)
                        ),
                        "utilization": self.department_utilization.get(dept, 0.0),
                        "pending_recruits": pending_by_department.get(dept, 0)
                    }
                    for dept in DepartmentType
                },
                "total_payroll": hr_summary["salary_cost_total"],  # Expected Fields for Observer
                "recruitment_status": {  # Expected Fields for Observer
                    "pending": hr_summary["pending_recruitments"],
                    "total_recruited": len([r for r in self.recruitment_records if r.status == "已到岗"]),
                    "pending_by_department": {
                        dept.value: count for dept, count in pending_by_department.items()
                    },
                    "recruitment_history": recent_recruitment_history
                },
                "staffing_relaxation": {
                    "enabled": staffing_relaxation_policy.get("enabled", False),
                    "virtual_available_workers": staffing_relaxation_policy.get("virtual_available_workers", 0),
                    "allow_soft_assignment": staffing_relaxation_policy.get("allow_soft_assignment", False),
                    "allow_soft_release": staffing_relaxation_policy.get("allow_soft_release", False),
                },
                "total_human_cost": hr_summary["total_human_cost"],
                "salary_cost_total": hr_summary["salary_cost_total"],
                "recruit_cost_total": hr_summary["recruit_cost_total"]
            }

            return self.success_response(
                response,
                "成功获取模块状态",
                state
            )
        except Exception as e:
            # Addressing anomalies
            return self.error_response(
                response,
                "STATE_ERROR",
                f"获取模块状态失败: {e}"
            )

    @with_response("get_available_workers")
    def get_available_workers(self, department, response: ModuleResponse = None) -> ModuleResponse:
        """
        Number of workers available (undistributed) in department (public interface)

        Args:
            Partment: < x6/ > Type (DepartmentType Count) or parameter Name String

        Returns:
            ModuleResponse: Unified response object with number of available workers
                """
        if not hasattr(self, 'allocated_workers'):
            self.allocated_workers = {dept: 0 for dept in DepartmentType}

        dept_type = self._convert_to_department_type(department)
        total_result = self.get_department_employees(dept_type)

        # Addressing different types of return
        if isinstance(total_result, int):
            total = total_result
        elif hasattr(total_result, 'data'):
            total = total_result.data.get("count", 0) if isinstance(total_result.data, dict) else 0
        elif isinstance(total_result, dict):
            total = total_result.get("count", 0)
        else:
            total = 0

        allocated = self.allocated_workers.get(dept_type, 0)
        available_count = self._get_relaxed_available_workers(total, allocated)
        policy = self._get_staffing_relaxation_policy()
        return self.success_response(
            response,
            "成功获取可用工人数",
            {
                "department": department,
                "count": available_count,
                "physical_available": max(0, total - allocated),
                "staffing_relaxation_enabled": policy.get("enabled", False),
            }
        )

    @with_response("assign_workers")
    def assign_workers(self, department, assignment_id: str,
                      num_workers: int, response: ModuleResponse = None) -> ModuleResponse:
        """
        Assignment of workers to specific tasks

        Args:
            Partment: < x6/ > Type (DepartmentType Count) or parameter Name String
            assignment_id: Task ID (e.g. production line ID)
            parameter: Number to be distributed

        Returns:
            ModuleResponse: Unified responder with distributed results

        **Code achieved**:
        - Check the adequacy of available workers
        - Update the allocated count if sufficient
        - Recording assignments
        - Return results
                """
        dept_type = self._convert_to_department_type(department)
        hr_result = self.get_available_workers(dept_type)
        available = hr_result.data.get("count", 0)
        physical_available = hr_result.data.get("physical_available", available)
        relaxation_policy = self._get_staffing_relaxation_policy()
        department = dept_type
        if num_workers > available:
            return self.error_response(
                response,
                "ASSIGN_WORKERS_ERROR",
                f"可用工人不足。需要: {num_workers}, 可用: {available}",
            )

        # Update allocated
        self.allocated_workers[department] = self.allocated_workers.get(department, 0) + num_workers
        self._recalculate_department_utilization(department)
        # Distribution of records
        existing_assignment = self.assignments.get(assignment_id, {})
        self.assignments[assignment_id] = {
            "department": department,
            "num_workers": existing_assignment.get("num_workers", 0) + num_workers,
            "assigned_time": existing_assignment.get("assigned_time", self.enterprise.time_manager.get_day()),
            "release_time": None,
            "state": "assigned",
            "soft_assigned": bool(relaxation_policy.get("enabled") and num_workers > physical_available),
        }
        remaining_workers = max(0, self.department_employees[department] - self.allocated_workers.get(department, 0))

        return self.success_response(
            response,
            "成功分配工人",
            {
                "assignment_id": assignment_id,
                "department": department.value,
                "num_workers": num_workers,
                "remaining_workers": remaining_workers,
                "soft_assigned": bool(relaxation_policy.get("enabled") and num_workers > physical_available),
            }
        )

    @with_response("release_workers")
    def release_workers(self, department, assignment_id: str,
                      num_workers: int,state:str, response: ModuleResponse = None) -> ModuleResponse:
        """
        Release of workers from specific assignments

        Args:
            Partment: < x6/ > Type (DepartmentType Count) or parameter Name String
            assignment_id: Task ID (e.g. production line ID)
            parameter: Number of persons to be released

        Returns:
            ModuleResponse: Unified responder with release results

        **Code achieved**:
        - Check the adequacy of available workers
        - Update the allocated count if sufficient
        - Record release.
        - Return results
                """
        dept_type = self._convert_to_department_type(department)
        department = dept_type
        assignment = self.assignments.get(assignment_id)
        relaxation_policy = self._get_staffing_relaxation_policy()
        if not assignment:
            if relaxation_policy.get("enabled") and relaxation_policy.get("allow_soft_release"):
                return self.success_response(
                    response,
                    "软人力模式下忽略缺失的工人释放任务",
                    {
                        "assignment_id": assignment_id,
                        "department": department.value,
                        "num_workers": 0,
                        "remaining_workers": max(0, self.department_employees[department] - self.allocated_workers.get(department, 0)),
                        "soft_released": True,
                    }
                )
            return self.error_response(
                response,
                "RELEASE_WORKERS_ERROR",
                f"任务 {assignment_id} not found in assignments",
            )
        assignment_workers = assignment.get("num_workers", 0)
        
        if num_workers > assignment_workers:
            if relaxation_policy.get("enabled") and relaxation_policy.get("allow_soft_release"):
                num_workers = assignment_workers
            else:
                return self.error_response(
                    response,
                    "RELEASE_WORKERS_ERROR",
                    f"工人释放数量不符，预释放人数: {num_workers}, 任务当前投入人数: {assignment_workers}",
                )
        
        # Update allocated
        self.allocated_workers[department] = max(0, self.allocated_workers.get(department, 0) - num_workers)
        self._recalculate_department_utilization(department)
        remaining_workers = max(0, self.department_employees[department] - self.allocated_workers.get(department, 0))

        # Update distribution
        self.assignments[assignment_id] = {
            "department": department,
            "num_workers": max(0, assignment_workers - num_workers),
            "assigned_time": assignment["assigned_time"],
            "release_time":self.enterprise.time_manager.get_day(),
            "state": state
        }

        return self.success_response(
            response,
            "成功释放工人",
            {
                "assignment_id": assignment_id,
                "department": department.value,
                "num_workers": num_workers,
                "remaining_workers": remaining_workers,
                "soft_released": bool(relaxation_policy.get("enabled") and relaxation_policy.get("allow_soft_release")),
            }
        )


    def reset(self):
        """Reset all data (for testing only)"""
        self.department_employees = {dept: 0 for dept in DepartmentType}
        self.department_utilization = {dept: 0.0 for dept in DepartmentType}
        self.recruitment_records = []
        self.recruitment_counter = 0
        self.salary_history = []
        self.cumulative_recruit_cost = 0.0
        self.cumulative_salary_cost = 0.0
        self.employee_attrition_history = []


    
    def _calculate_per_capita_output(self, total_revenue: float) -> float:
        """Calculated per capita output (total income/total staff)"""
        if total_revenue < 0:
            raise ValueError("总收入不能为负")
        
        total_employees = self.get_all_employees()
        if total_employees == 0:
            return 0.0
        return total_revenue / total_employees
    
    def _calculate_labor_cost_rate(self, total_cost: float) -> float:
        """Calculated labour cost rate (work cost/total cost)"""
        if total_cost < 0:
            raise ValueError("总成本不能为负")
        
        if total_cost == 0:
            return 0.0
        
        rate = self.get_total_human_cost() / total_cost
        return min(rate, 1.0)
    

    def _get_attrition_history(self) -> List[Dict]:
        """Get all lost staff history."""
        return self.employee_attrition_history
    
    def _get_total_attrition(self) -> int:
        """Accumulated loss"""
        return sum(record["num_people"] for record in self.employee_attrition_history)

    def _get_utilization_status(self, department: DepartmentType) -> str:
        """Access status description of department utilization (internal method, direct access to data)"""
        util = self.department_utilization.get(department, 0.0)
        if util < self.UTILIZATION_SURPLUS_THRESHOLD:
            return "人员冗余"
        elif util > self.UTILIZATION_SHORTAGE_THRESHOLD:
            return "人员不足"
        elif self.OPTIMAL_UTILIZATION_LOWER <= util <= self.OPTIMAL_UTILIZATION_UPPER:
            return "最优配置"
        else:
            return "偏低利用"
    
    def _validate_state(self) -> Tuple[bool, List[str]]:
        """Verify consistency of HR module status"""
        issues = []
        
        # Check for consistency in the number of employees
        for dept in DepartmentType:
            if self.department_employees[dept] < 0:
                issues.append(f"{dept.value}员工数为负数")
        
        # Check utilization coverage
        for dept in DepartmentType:
            util = self.department_utilization[dept]
            if util < 0 or util > 2:
                issues.append(f"{dept.value}利用率超出合理范围: {util}")
        
        # Check for cost consistency
        if self.cumulative_recruit_cost < 0 or self.cumulative_salary_cost < 0:
            issues.append("成本数据为负数")
        
        # Check for consistency in recruitment records
        for record in self.recruitment_records:
            if record.num_people < 0:
                issues.append(f"招聘记录{record.record_id}人数为负")
            if record.recruit_cost < 0:
                issues.append(f"招聘记录{record.record_id}成本为负")
        
        return len(issues) == 0, issues
      
    def _convert_to_department_type(self, department_input):
        """
        Convert input to DepartmentType count (support string and number type input, case insensitive)
                
        Args:
            department_input: department Name string or DepartType Lift
                        
        Returns:
            DepartmentType: corresponding list of department types
                        
        Raises:
            ValueError: If input is invalid
                """
        if isinstance(department_input, DepartmentType):
            return department_input
        
        if isinstance(department_input, str):
            # Convert to uppercase to match case-neutral
            input_lower = department_input.strip().lower()
            aliases = {
                "hr": DepartmentType.HR,
                "human_resources": DepartmentType.HR,
                "人力": DepartmentType.HR,
                "人力资源": DepartmentType.HR,
                "人力资源部门": DepartmentType.HR,
                "production": DepartmentType.PRODUCTION,
                "生产": DepartmentType.PRODUCTION,
                "生产部门": DepartmentType.PRODUCTION,
                "sales": DepartmentType.SALES,
                "销售": DepartmentType.SALES,
                "销售部门": DepartmentType.SALES,
                "procurement": DepartmentType.PROCUREMENT,
                "purchase": DepartmentType.PROCUREMENT,
                "采购": DepartmentType.PROCUREMENT,
                "采购部门": DepartmentType.PROCUREMENT,
                "inventory": DepartmentType.INVENTORY,
                "warehouse": DepartmentType.INVENTORY,
                "仓储": DepartmentType.INVENTORY,
                "仓储部门": DepartmentType.INVENTORY,
                "库存": DepartmentType.INVENTORY,
                "库存部门": DepartmentType.INVENTORY,
                "finance": DepartmentType.FINANCE,
                "财务": DepartmentType.FINANCE,
                "财务管理": DepartmentType.FINANCE,
                "财务管理部门": DepartmentType.FINANCE,
            }
            if input_lower in aliases:
                return aliases[input_lower]
            for dept in DepartmentType:
                if dept.name.lower() == input_lower or dept.value.lower() == input_lower:
                    return dept
            raise ValueError(f"无效的部门类型: {department_input}")
        
        raise ValueError(f"无效的部门类型输入: {department_input}")
    
    
    def _is_department_surplus(self, department) -> bool:
        """Determination of redundancy at department (utilization rate <0.3)"""
        # Draw utilization from ModuleResponse
        utilization_response = self.get_department_utilization(department)
        utilization = utilization_response.data["utilization"] if utilization_response.success else 0.0
        return utilization < self.UTILIZATION_SURPLUS_THRESHOLD
    
    def _is_department_shortage(self, department) -> bool:
        """Determination of department understaffing (utilization > 1.0)"""
        # Draw utilization from ModuleResponse
        utilization_response = self.get_department_utilization(department)
        utilization = utilization_response.data["utilization"] if utilization_response.success else 0.0
        return utilization > self.UTILIZATION_SHORTAGE_THRESHOLD
    
