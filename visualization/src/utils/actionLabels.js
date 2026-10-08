export const ACTION_LABELS = {
  action_pass: 'Skip',
  create_order: 'Create Sales Order',
  accept_order: 'Accept Sales Order',
  reject_order: 'Reject Sales Order',
  develop_market: 'Develop Market',
  adjust_sales_demand: 'Adjust Sales Supply',
  create_production_plan: 'Create Production Plan',
  build_production_line: 'Build Production Line',
  initialize_production_line: 'Initialize Production Line',
  create_purchase_order: 'Create Purchase Order',
  create_purchase_demand: 'Create Purchase Demand',
  create_replenishment_order: 'Create Replenishment Order',
  accept_proposal_order: 'Accept B2B Proposal',
  reject_proposal_order: 'Reject B2B Proposal',
  expand_warehouse: 'Expand Warehouse',
  add_inventory: 'Add Inventory',
  set_capacity: 'Set Warehouse Capacity',
  set_product_recipe: 'Set Product Recipe',
  initialize_staffing: 'Initialize Staffing',
  handle_recruitment: 'Recruit Employees',
  process_employee_attrition: 'Process Employee Attrition',
  initialize_suppliers: 'Initialize Suppliers',
  add_cost: 'Record Cost',
  create_loan: 'Create Loan',
  repay_loan: 'Repay Loan',
};

export const getActionDisplayName = (actionName, fallback = 'Unknown Action') => {
  const key = String(actionName || '').trim();
  if (!key || key === 'unknown_action') {
    return fallback;
  }
  return ACTION_LABELS[key] || key;
};

export const isActionPassAction = (actionName) => (
  String(actionName || '').trim() === 'action_pass'
);
