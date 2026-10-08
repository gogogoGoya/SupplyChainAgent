"""
Action Execution Module

Actions to implement enterprise
"""

class ActionExecutor:
    """
    Action Executor
        """
    def __init__(self):
        """
        Initialise Action Executor
                """
        # Storage of enterprise action sequence execution status
        self.enterprise_action_sequence_states = {}
    
    def execute(self, enterprise_id, action, environment):
        """
        Execute action enterprise
                
        Args:
            enterprise_id: enterpriseID
            action: action content
            Other Organiser
                        
        Returns:
            dict: Execute results with more detailed information for event creation
                """
        action_type = action.get("type")
        
        enterprise = environment.get_enterprise(enterprise_id)
        if not enterprise:
            return {
                "status": "error", 
                "message": f"企业 {enterprise_id} 不存在",
                "action_type": action_type,
                "event_type": "ACTION_FAILED"
            }
        
        if not action_type:
            return {
                "status": "error", 
                "message": "动作类型未指定",
                "action_type": action_type,
                "event_type": "ACTION_FAILED"
            }
        
        # Initialize enterprise action sequence state (if not available)
        if enterprise_id not in self.enterprise_action_sequence_states:
            self.enterprise_action_sequence_states[enterprise_id] = {
                "current_step": 0,
                "in_sequence": False,
                "sequence_type": None
            }
        
        state = self.enterprise_action_sequence_states[enterprise_id]
        
        # If you are not currently in the sequence, but you receive a production action, you start a new sequence.
        if not state["in_sequence"] and action_type == "PRODUCTION":
            state["in_sequence"] = True
            state["sequence_type"] = "PRODUCTION_SEQUENCE"
            state["current_step"] = 0
        
        # Step 1: Let all the work of enterprise x6/ > Modular Confirmation Actions
        confirmation_result = enterprise.confirm_action_by_modules(action)
        if not confirmation_result.get("confirmed", False):
            # If action execution fails, reset sequence status
            if state["in_sequence"]:
                print(f"企业 {enterprise_id} 动作序列执行失败: 动作未通过企业部门模块确认")
                state["in_sequence"] = False
                state["sequence_type"] = None
                state["current_step"] = 0
                if "next_action" in state:
                    del state["next_action"]
            
            return {
                "status": "error",
                "message": "动作未通过企业部门模块确认",
                "confirmations": confirmation_result.get("confirmations", []),
                "action_type": action_type,
                "event_type": "ACTION_REJECTED"
            }
        
        # Step 2: Try to find the corresponding responsible module to implement the action
        executing_module = self._find_executing_module(enterprise, action_type)
        if executing_module:
            try:
                if action:
                    module_result = executing_module.execute_action(action)            
                # Record action to enterprise history
                if hasattr(enterprise, 'record_action'):
                    enterprise.record_action(action or selected_action, module_result)
                
                # Enhance Results
                module_result['action_type'] = action_type
                module_result['event_type'] = 'ACTION_EXECUTED_BY_MODULE'
                module_result['executing_module'] = getattr(executing_module, 'module_id', 'unknown')
                module_result['data'] = (action or selected_action).copy()
                
                # Process action sequences
                if state["in_sequence"] and module_result.get("status") == "success":
                    state["current_step"] += 1
                    print(f"企业 {enterprise_id} 完成动作序列步骤 {state['current_step']}: {action_type}")
                    
                    # If this is a production move, the next step should be to increase the stock.
                    if action_type == "PRODUCTION" and hasattr(enterprise, "inventory_manager"):
                        # Automatically create and execute inventory addition actions
                        print(f"企业 {enterprise_id} 自动触发库存增加动作")
                        # Here we only mark the state. The actual execution will be triggered by the controller at the next step.
                        state["next_action"] = "INVENTORY_TRANSFER"
                    
                    # If this is an inventory transfer, the next step is sales.
                    elif action_type in ["INVENTORY_TRANSFER", "B2B_PURCHASE"] and hasattr(enterprise, "sales_manager"):
                        # Automatically create and execute sales actions
                        print(f"企业 {enterprise_id} 自动触发销售动作")
                        # Mark Next Action
                        state["next_action"] = "SALES"
                    
                    # If it's a sales move, the action sequence is complete.
                    elif action_type in ["SALES", "B2B_SALES"]:
                        print(f"企业 {enterprise_id} 完成整个动作序列: 生产->库存->销售")
                        # Reset Serial Status
                        state["in_sequence"] = False
                        state["sequence_type"] = None
                        state["current_step"] = 0
                        if "next_action" in state:
                            del state["next_action"]
                
                return module_result
            except Exception as e:
                # If action execution fails, reset sequence status
                if state["in_sequence"]:
                    print(f"企业 {enterprise_id} 动作序列执行失败: {str(e)}")
                    state["in_sequence"] = False
                    state["sequence_type"] = None
                    state["current_step"] = 0
                    if "next_action" in state:
                        del state["next_action"]
                
                return {
                    "status": "error",
                    "message": f"模块执行动作出错: {str(e)}",
                    "executing_module": getattr(executing_module, 'module_id', 'unknown'),
                    "action_type": action_type,
                    "event_type": "ACTION_FAILED"
                }
    
    def _find_executing_module(self, enterprise, action_type):
        """
        Find modules to execute specific types of actions
                
        Args:
            Example: enterprise
            parameter: Action type
                        
        Returns:
            BaseBusinesModule: Examples of modules responsible for the execution of the action, returnNone if not found
                """
        # Use action handlers dictionaries to find the corresponding processing function as an alternative
        if action_type in self.action_handlers:
            # Retain the original logic to support module implementation
            # Map to the corresponding module type by action type
            action_module_mapping = {
                "FINANCIAL_MANAGEMENT": "FinanceManager",
                "INVENTORY_TRANSFER": "InventoryManager",
                "PRODUCTION": "ProductionManager",
                "PROCUREMENT": "ProcurementManager",
                "SALES": "SalesManager",
                "HR_MANAGEMENT": "HRManager"
            }
            
            # Get the corresponding module type
            module_type = action_module_mapping.get(action_type)
            if module_type:
                # Find the corresponding module in enterprise
                modules = enterprise.get_module_by_type(module_type)
                if modules:
                    # Returns first found module
                    return modules[0]
            
            # Try to get enterprise to decide which module to use
            if hasattr(enterprise, 'get_executing_module_for_action'):
                return enterprise.get_executing_module_for_action(action_type)
        
        return None
        
    def get_next_action_for_enterprise(self, enterprise_id):
        """
        Next action to get enterprise (if in the action sequence)
                
        Args:
            enterprise_id: enterpriseID
                        
        Returns:
            st or None: Next action type, if not
                """
        if enterprise_id in self.enterprise_action_sequence_states:
            state = self.enterprise_action_sequence_states[enterprise_id]
            return state.get("next_action")
        return None
    
    def _call_department_functions(self, enterprise, action, dept, current_tick):
        """
        Call the functional method according to department type
        Args: 
            enterprise_id: enterpriseID
            Example: enterprise
            step: current steps
            Action lists for current steps
                """
        # Unified Return Structure
        def error_result(reason, detail=None):
            return {
                # "tick": current_tick,
                "dept": dept,
                "action": action.get("action_name") if action else None,
                "status": "error",
                "reason": reason,
                "detail": detail,
            }

        if not action:
            return error_result("action_is_none")

        action_name = action.get("action_name")
        action_param = action.get("action_param", {})

        if dept not in enterprise.business_modules:
            return error_result("invalid_dept", f"{dept} not found")
        managers = enterprise.business_modules.get(dept)
        if not managers:
            return error_result("empty_dept_manager")

        manager = managers[0]

        if not hasattr(manager, action_name):
            return error_result("method_not_found")

        method = getattr(manager, action_name)
        
        if not isinstance(action_param, dict):
            return error_result("invalid_action_param_type")

        try:
            result = method(**action_param) 
            return result
        except TypeError as e:
            return error_result("parameter_error", str(e))

        except Exception as e:
            return error_result("runtime_error", str(e))
