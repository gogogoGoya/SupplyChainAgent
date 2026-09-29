"""
动作执行器模块

负责执行企业的各种动作
"""

class ActionExecutor:
    """
    动作执行器
    """
    def __init__(self):
        """
        初始化动作执行器
        """
        # 存储企业的动作序列执行状态
        self.enterprise_action_sequence_states = {}
    
    def execute(self, enterprise_id, action, environment):
        """
        执行企业动作
        
        Args:
            enterprise_id: 企业ID
            action: 动作内容
            environment: 环境实例
            
        Returns:
            dict: 执行结果，包含更详细的信息用于事件创建
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
        
        # 初始化企业动作序列状态（如果不存在）
        if enterprise_id not in self.enterprise_action_sequence_states:
            self.enterprise_action_sequence_states[enterprise_id] = {
                "current_step": 0,
                "in_sequence": False,
                "sequence_type": None
            }
        
        state = self.enterprise_action_sequence_states[enterprise_id]
        
        # 如果当前不在序列中，但接收到的是生产动作，则开始新的动作序列
        if not state["in_sequence"] and action_type == "PRODUCTION":
            state["in_sequence"] = True
            state["sequence_type"] = "PRODUCTION_SEQUENCE"
            state["current_step"] = 0
        
        # 第一步：让企业的所有工作部门模块确认动作
        confirmation_result = enterprise.confirm_action_by_modules(action)
        if not confirmation_result.get("confirmed", False):
            # 如果动作执行失败，重置序列状态
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
        
        # 第二步：尝试找到对应的负责模块来执行动作
        executing_module = self._find_executing_module(enterprise, action_type)
        if executing_module:
            try:
                if action:
                    module_result = executing_module.execute_action(action)            
                # 记录动作到企业历史
                if hasattr(enterprise, 'record_action'):
                    enterprise.record_action(action or selected_action, module_result)
                
                # 增强结果
                module_result['action_type'] = action_type
                module_result['event_type'] = 'ACTION_EXECUTED_BY_MODULE'
                module_result['executing_module'] = getattr(executing_module, 'module_id', 'unknown')
                module_result['data'] = (action or selected_action).copy()
                
                # 处理动作序列
                if state["in_sequence"] and module_result.get("status") == "success":
                    state["current_step"] += 1
                    print(f"企业 {enterprise_id} 完成动作序列步骤 {state['current_step']}: {action_type}")
                    
                    # 如果当前是生产动作，下一步应该是增加库存
                    if action_type == "PRODUCTION" and hasattr(enterprise, "inventory_manager"):
                        # 自动创建并执行库存增加动作
                        print(f"企业 {enterprise_id} 自动触发库存增加动作")
                        # 这里我们只标记状态，实际执行会在下一个时间步由控制器触发
                        state["next_action"] = "INVENTORY_TRANSFER"
                    
                    # 如果当前是库存转移动作，下一步应该是销售
                    elif action_type in ["INVENTORY_TRANSFER", "B2B_PURCHASE"] and hasattr(enterprise, "sales_manager"):
                        # 自动创建并执行销售动作
                        print(f"企业 {enterprise_id} 自动触发销售动作")
                        # 标记下一个动作
                        state["next_action"] = "SALES"
                    
                    # 如果当前是销售动作，动作序列完成
                    elif action_type in ["SALES", "B2B_SALES"]:
                        print(f"企业 {enterprise_id} 完成整个动作序列: 生产->库存->销售")
                        # 重置序列状态
                        state["in_sequence"] = False
                        state["sequence_type"] = None
                        state["current_step"] = 0
                        if "next_action" in state:
                            del state["next_action"]
                
                return module_result
            except Exception as e:
                # 如果动作执行失败，重置序列状态
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
        查找负责执行特定类型动作的模块
        
        Args:
            enterprise: 企业实例
            action_type: 动作类型
            
        Returns:
            BaseBusinessModule: 负责执行该动作的模块实例，如果没有找到则返回None
        """
        # 使用action_handlers字典查找对应的处理函数作为备选
        if action_type in self.action_handlers:
            # 保留原有逻辑以支持模块执行
            # 根据动作类型映射到对应的模块类型
            action_module_mapping = {
                "FINANCIAL_MANAGEMENT": "FinanceManager",
                "INVENTORY_TRANSFER": "InventoryManager",
                "PRODUCTION": "ProductionManager",
                "PROCUREMENT": "ProcurementManager",
                "SALES": "SalesManager",
                "HR_MANAGEMENT": "HRManager"
            }
            
            # 获取对应的模块类型
            module_type = action_module_mapping.get(action_type)
            if module_type:
                # 查找企业中对应的模块
                modules = enterprise.get_module_by_type(module_type)
                if modules:
                    # 返回第一个找到的模块
                    return modules[0]
            
            # 尝试让企业自己决定使用哪个模块执行
            if hasattr(enterprise, 'get_executing_module_for_action'):
                return enterprise.get_executing_module_for_action(action_type)
        
        return None
        
    def get_next_action_for_enterprise(self, enterprise_id):
        """
        获取企业的下一个动作（如果在动作序列中）
        
        Args:
            enterprise_id: 企业ID
            
        Returns:
            str or None: 下一个动作类型，如果没有则返回None
        """
        if enterprise_id in self.enterprise_action_sequence_states:
            state = self.enterprise_action_sequence_states[enterprise_id]
            return state.get("next_action")
        return None
    
    def _call_department_functions(self, enterprise, action, dept, current_tick):
        """
        根据部门类型调用相应的功能方法
        Args: 
            enterprise_id: 企业ID
            enterprise: 企业实例
            step: 当前步骤
            actions: 当前步骤的动作列表
        """
        # 统一返回结构
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
