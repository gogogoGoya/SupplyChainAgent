export const ACTION_LABELS = {
  action_pass: '跳过',
  create_order: '创建销售订单',
  accept_order: '接收销售订单',
  reject_order: '拒绝销售订单',
  develop_market: '开拓市场',
  adjust_sales_demand: '调整销售需求',
  create_production_plan: '创建生产计划',
  build_production_line: '建设生产线',
  initialize_production_line: '初始化生产线',
  create_purchase_order: '创建采购订单',
  create_purchase_demand: '创建采购需求',
  create_replenishment_order: '创建补货订单',
  accept_proposal_order: '接受企业间订单',
  reject_proposal_order: '拒绝企业间订单',
  expand_warehouse: '扩建仓库',
  add_inventory: '增加库存',
  set_capacity: '设置仓容',
  set_product_recipe: '设置产品配方',
  initialize_staffing: '初始化人员',
  handle_recruitment: '招聘人员',
  process_employee_attrition: '处理人员流失',
  initialize_suppliers: '初始化供应商',
  add_cost: '登记成本',
  create_loan: '创建贷款',
  repay_loan: '偿还贷款',
};

export const getActionDisplayName = (actionName, fallback = '未知动作') => {
  const key = String(actionName || '').trim();
  if (!key || key === 'unknown_action' || key === '未知动作') {
    return fallback;
  }
  return ACTION_LABELS[key] || key;
};

export const isActionPassAction = (actionName) => (
  String(actionName || '').trim() === 'action_pass'
);
