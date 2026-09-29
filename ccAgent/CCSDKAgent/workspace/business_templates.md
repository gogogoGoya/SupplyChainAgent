# 企业行为模板

## 可用操作类型

### HRManager
- **handle_recruitment**: 【推进操作】发起招聘流程，增加指定部门的人员
  参数: department (str (MUST be one of: 'HR', 'PRODUCTION', 'SALES', 'PROCUREMENT', 'INVENTORY', 'FINANCE')), num_people (int (MUST be 1-10))
  前置条件:
    1. {'check_type': 'resource', 'description': '现金余额足够支付招聘成本（约5000/人）和后续工资', 'check_method': '检查 observations.finance.cash 是否 >= (5000 × num_people)'}
    2. {'check_type': 'data', 'description': 'department参数必须是有效的部门名称', 'check_method': None}
    3. {'check_type': 'data', 'description': 'num_people必须在1-10之间', 'check_method': None}
  示例场景:
    1. 生产订单积压时，招聘PRODUCTION部门员工增加产能
    2. 销售市场扩大时，招聘SALES部门员工提升销售能力
    3. 采购业务繁忙时，招聘PROCUREMENT部门员工加快采购处理
    4. 对已执行过的业务操作，如果有因人员不足而失败或无法推进的情况，则说明需要招聘对应部门的员工
- **process_employee_attrition**: 【推进操作】减少指定部门的人员
  参数: department_name (str (MUST be one of: 'HR', 'PRODUCTION', 'SALES', 'PROCUREMENT', 'INVENTORY', 'FINANCE')), num_people (int (>0)), reason (str (optional))
  前置条件:
    1. {'check_type': 'resource', 'description': '指定部门的员工数 >= num_people', 'check_method': '检查 observations.hr.employees 中对应 department 的 count 是否 >= num_people'}
    2. {'check_type': 'data', 'description': 'department_name参数必须是有效的部门名称', 'check_method': None}
  示例场景:
    1. 成本压力大时，裁减冗余部门员工降低开支
    2. 业务收缩时，减少不必要的人力成本

### ProcurementManager
- **create_purchase_order**: 【推进操作】创建采购订单（传统外部采购），建立后需要等待一定轮次才能完成
  参数: material_id (str (required)), quantity (float (required, >0)), supplier_id (str (required)), logistics_mode (str (MUST be one of: 'road', 'rail', 'air'))
  前置条件:
    1. {'check_type': 'resource', 'description': 'PROCUREMENT部门有足够的人员（至少MIN_PROCUREMENT_STAFF人）', 'check_method': '检查 observations.hr.employees 中 PROCUREMENT 部门的 count'}
    2. {'check_type': 'data', 'description': "logistics_mode必须是'road', 'rail', 'air'之一", 'check_method': None}
    3. {'check_type': 'data', 'description': 'supplier_id必须是已注册的供应商（【注意】未检查，会抛出KeyError）', 'check_method': '检查 observations.procurement.suppliers 列表中是否存在该 supplier_id'}
    4. {'check_type': 'data', 'description': '供应商必须提供该material_id的材料', 'check_method': '检查 observations.procurement.suppliers 中对应供应商的 materials 列表是否包含该 material_id'}
    5. {'check_type': 'resource', 'description': 'quantity必须 >= 供应商的最小订货量', 'check_method': '检查 observations.procurement.suppliers 中对应供应商的 min_order_quantity'}
    6. {'check_type': 'resource', 'description': '现金余额足够支付采购成本（材料成本+物流成本）', 'check_method': '检查 observations.finance.cash 是否 >= (material单价 × quantity + 物流成本)'}
    7. {'check_type': 'resource', 'description': '【未实现】仓库容量检查（代码中未检查）', 'check_method': '【警告】代码未检查仓库容量，订单可能导致仓库超载'}
  示例场景:
    1. 原材料库存低于安全库存时，创建采购订单补充库存
    2. 接受销售订单后，发现原材料不足，需要紧急采购
    3. 预测未来需求，提前采购原材料以避免生产延误

### ProductionManager
- **build_production_line**: 【推进操作】建设生产线，建立后需要等待一定轮次才能完成
  参数: line_type (str (MUST be one of: 'small', 'medium', 'large'))
  前置条件:
    1. {'check_type': 'resource', 'description': '现金余额足够支付建设成本（small:50000, medium:120000, large:250000）', 'check_method': '检查 observations.finance.cash 是否 >= 建设成本'}
    2. {'check_type': 'data', 'description': "line_type必须是'small'、'medium'、'large'之一", 'check_method': None}
  示例场景:
    1. 销售订单增多，现有产能不足，建设新生产线扩大产能
    2. 预计未来需求增长，提前建设生产线做准备
    3. 初期启动时，建设首条生产线开始生产业务
- **create_production_plan**: 【推进操作】创建生产计划
  参数: product_id (str (required)), quantity (float (required, >0))
  前置条件:
    1. {'check_type': 'resource', 'description': '总产能（total_capacity）> 0，至少有一条激活的生产线', 'check_method': '检查 observations.production.total_capacity 是否 > 0'}
    2. {'check_type': 'data', 'description': 'product_id必须是已配置配方的产品', 'check_method': '检查 observations.production.product_recipes 中是否存在该 product_id'}
    3. {'check_type': 'data', 'description': 'quantity必须 > 0', 'check_method': None}
    4. {'check_type': 'resource', 'description': '可用产能（available_capacity）>= quantity（在执行时检查）', 'check_method': '检查 observations.production.available_capacity 是否 >= quantity'}
    5. {'check_type': 'resource', 'description': '原材料库存足够满足生产配方需求（在执行时检查）', 'check_method': '对比 observations.production.product_recipes 中的原材料需求和 observations.inventory.inventory_items 中的库存'}
  示例场景:
    1. 接受销售订单后，根据订单需求创建生产计划
    2. 原材料到货后，创建生产计划消耗原材料生产产品
    3. 预测市场需求，提前创建生产计划备货
- **execute_production_plan**: 【推进操作】执行生产计划，开始实际生产
  参数: plan_id (str (required))
  前置条件:
    1. {'check_type': 'state', 'description': "计划状态必须为'pending'（待执行）", 'check_method': "检查 observations.production.production_plans 中对应计划的 status 是否为 'pending'"}
    2. {'check_type': 'data', 'description': 'plan_id必须是已存在的生产计划ID', 'check_method': '检查 observations.production.production_plans 列表中是否存在该 plan_id'}
    3. {'check_type': 'resource', 'description': '可用产能 >= 计划的quantity', 'check_method': '检查 observations.production.available_capacity 是否 >= 计划的 quantity'}
    4. {'check_type': 'resource', 'description': '原材料库存足够（根据配方×quantity计算）', 'check_method': '对比 observations.production.product_recipes 和 observations.inventory.inventory_items 验证原材料充足'}
    5. {'check_type': 'resource', 'description': '至少有一条空闲（idle）的生产线', 'check_method': "检查 observations.production.production_lines 中是否存在 status='idle' 的生产线"}
  示例场景:
    1. 原材料到货后，立即执行待执行的生产计划开始生产
    2. 有空闲产能时，执行积压的生产计划
    3. 销售订单交付期临近，优先执行对应的生产计划
- **cancel_production_plan**: 【推进操作】取消生产计划
  参数: plan_id (str (required)), reason (str (optional))
  前置条件:
    1. {'check_type': 'state', 'description': "计划状态必须为'pending'或'in_progress'", 'check_method': "检查 observations.production.production_plans 中对应计划的 status 是否为 'pending' 或 'in_progress'"}
    2. {'check_type': 'data', 'description': 'plan_id必须是已存在的生产计划ID', 'check_method': '检查 observations.production.production_plans 列表中是否存在该 plan_id'}
  示例场景:
    1. 发现计划参数错误，取消后重新创建
    2. 销售订单被拒绝，取消对应的生产计划
    3. 资源调整，取消低优先级的生产计划

### InventoryManager
- **expand_warehouse**: 【推进操作】扩建仓库容量
  参数: size (int (MUST be one of: 1000, 2000, 5000))
  前置条件:
    1. {'check_type': 'resource', 'description': '现金余额足够支付扩建成本（1000:50000, 2000:80000, 5000:150000）', 'check_method': '检查 observations.finance.cash 是否 >= 扩建成本'}
    2. {'check_type': 'resource', 'description': 'INVENTORY部门有足够的人员（至少2人）', 'check_method': '检查 observations.hr.employees 中 INVENTORY 部门的 count >= 2'}
    3. {'check_type': 'data', 'description': 'size必须是1000、2000、5000之一', 'check_method': None}
  示例场景:
    1. 采购订单因仓库容量不足被拒绝，扩建仓库后重新采购
    2. 预计库存量增长，提前扩建仓库准备容量
    3. 产品积压，扩建仓库增加存储空间

### SalesManager
- **develop_market**: 【推进操作】开发新市场，建立后需要等待一定轮次才能完成
  参数: market_type (str (MUST be one of: 'regional', 'international')), market_name (str (optional))
  前置条件:
    1. {'check_type': 'resource', 'description': '现金余额足够支付开发成本（regional:50000, international:150000）', 'check_method': '检查 observations.finance.cash 是否 >= 开发成本'}
    2. {'check_type': 'data', 'description': "market_type必须是'regional'或'international'", 'check_method': None}
    3. {'check_type': 'resource', 'description': 'SALES部门有足够的人员资源', 'check_method': "检查 observations.hr.employees 中 department='销售部门' 的 count 是否足够"}
  示例场景:
    1. 初期启动时，开发首个市场建立销售渠道
    2. 现有市场订单不足，开发新市场增加订单来源
    3. 产能充足但销售不足，开发国际市场扩大销售规模
- **accept_order**: 【推进操作】接受销售订单，承诺在交付期限前提供产品
  参数: order_id (str (required))
  前置条件:
    1. {'check_type': 'state', 'description': "订单状态必须为'available'（可接受）", 'check_method': "检查 observations.sales.sales_orders 中对应订单的 status 是否为 'available'"}
    2. {'check_type': 'data', 'description': 'order_id必须是已存在的销售订单ID', 'check_method': '检查 observations.sales.sales_orders 列表中是否存在该 order_id'}
    3. {'check_type': 'resource', 'description': '建议检查能否在交付期前生产足够产品（可选检查）', 'check_method': '检查 observations.inventory.inventory_items 中对应产品的 quantity，以及 observations.production.available_capacity'}
  示例场景:
    1. 市场生成新订单，评估后接受订单开始履约
    2. 产品库存充足，接受订单快速交付获得收入
    3. 预计能在交付期前完成生产，提前接受订单锁定收入
- **reject_order**: 【推进操作】拒绝销售订单，放弃该订单的收入机会
  参数: order_id (str (required)), reason (str (optional))
  前置条件:
    1. {'check_type': 'state', 'description': "订单状态必须为'available'（可接受）", 'check_method': "检查 observations.sales.sales_orders 中对应订单的 status 是否为 'available'"}
    2. {'check_type': 'data', 'description': 'order_id必须是已存在的销售订单ID', 'check_method': '检查 observations.sales.sales_orders 列表中是否存在该 order_id'}
  示例场景:
    1. 订单交付期太紧，无法按时生产，拒绝订单避免违约
    2. 订单利润太低，拒绝订单等待更好的订单
    3. 产能不足，优先保证已接受订单，拒绝新订单

