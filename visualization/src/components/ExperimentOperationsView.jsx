import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  createOperationsJob,
  deleteOperationsJob,
  getOperationsJobSummary,
  listOperationScenarios,
  listOperationsJobs,
  resumeOperationsJob,
  resumeArtifactRun,
  runOperationsJob,
  stopOperationsJob,
} from '../utils/operationsApi';
import { getActionDisplayName } from '../utils/actionLabels';

const STATUS_LABELS = {
  queued: '等待',
  running: '运行中',
  stop_requested: '请求停止',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
};

const ACTIVE_STATUSES = new Set(['queued', 'running', 'stop_requested']);
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'stopped']);
const STOPPABLE_STATUSES = new Set(['queued', 'running']);
const CONTROL_PRESETS = {
  agent: {
    id: 'agent',
    label: 'Agent Skill 参与',
    description: '保留部门 Agent Skill 执行路径，用于正式智能体仿真。',
  },
  scripted: {
    id: 'scripted',
    label: '固定规则脚本',
    description: '由规则算法生成分析与部门动作。',
  },
};
const EXPERIMENT_GROUPS = {
  C1: {
    id: 'C1',
    label: 'C1',
    title: '规则脚本',
    fullLabel: 'C1 规则理性脚本组',
    description: '固定规则/脚本控制，用于验证环境机制。',
    preset: 'scripted',
  },
  C2: {
    id: 'C2',
    label: 'C2',
    title: '约束 Agent',
    fullLabel: 'C2 约束 Agent 机制组',
    description: 'Agent 参与决策，并带机制导向约束。',
    preset: 'agent',
  },
  C3: {
    id: 'C3',
    label: 'C3',
    title: '盈利目标',
    fullLabel: 'C3 盈利最优理性 Agent 组',
    description: 'Agent 以利润、现金、服务和风险为开放目标。',
    preset: 'agent',
  },
  S0: {
    id: 'S0',
    label: 'S0',
    title: '单企校验',
    fullLabel: 'S0 单企业理性能力校验',
    description: '单企业 case 中验证诊断和纠偏能力。',
    preset: 'agent',
  },
  E1: {
    id: 'E1',
    label: 'E1',
    title: '持续演变',
    fullLabel: 'E1 多企业持续演变长跑',
    description: '稳定四级供应链在分阶段外部成本、政策与需求变化下的长期适应实验。',
    preset: 'agent',
  },
};
const MULTI_SCENARIO_GROUPS = [
  {
    id: 'evolution',
    label: '持续演变长跑',
    summary: '200轮四级供应链经营，观察企业识别并响应分阶段外部环境变化。',
  },
  {
    id: 'bullwhip',
    label: '牛鞭效应',
    summary: '观察需求扰动在供应链上游逐级放大的过程。',
  },
  {
    id: 'cobweb',
    label: '蛛网模型',
    summary: '观察滞后生产决策与价格反馈形成的收敛、均衡或发散轨迹。',
  },
  {
    id: 'commons',
    label: '公地悲剧',
    summary: '观察共享资源过度获取导致资源池退化及企业经营受损。',
  },
  {
    id: 'herding',
    label: '羊群效应',
    summary: '观察企业受同行信号影响而从差异化决策走向同步行动。',
  },
];

const SINGLE_CASE_SUMMARIES = {
  single_case_01_order_selection: '订单入口有限，观察销售能否基于库存与订单证据合理开发市场，并选择利润与履约兼顾的订单组合。',
  single_case_02_material_shortage: '原料短缺，重点观察采购能否选择合适供应商、数量与物流方式。',
  single_case_03_capacity_bottleneck: '产能瓶颈，重点观察生产是否识别并处理产能不足。',
  single_case_04_staff_shortage: '人员不足，重点观察人力是否补足关键岗位人手。',
  single_case_05_cash_pressure: '现金压力，重点观察是否保守经营并优先修复现金。',
};

const formatValue = (value) => {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  return String(value);
};

const formatMoney = (value) => {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '-';
  }
  return number.toLocaleString('zh-CN', {
    maximumFractionDigits: 2,
  });
};

const formatTime = (value) => {
  if (!value) {
    return '-';
  }
  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  }
  return String(value).replace('T', ' ');
};

const formatCompactTime = (value) => {
  if (!value) {
    return '-';
  }
  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  }
  return String(value).replace('T', ' ').slice(5, 16);
};

const formatShortRunId = (value) => {
  const text = String(value || '').trim();
  if (!text) {
    return '-';
  }
  const matched = text.match(/^(run|job)_([A-Za-z0-9]+)/);
  if (matched) {
    return `${matched[1]}_${matched[2].slice(0, 8)}`;
  }
  return text.length > 12 ? `${text.slice(0, 12)}...` : text;
};

const getJobActivityTime = (job) => (
  job?.finished_at
  || job?.updated_at
  || job?.started_at
  || job?.created_at
  || ''
);

const getJobActivityTimestamp = (job) => {
  const parsed = new Date(getJobActivityTime(job)).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
};

const getScenarioId = (runMeta) => (
  runMeta?.scenario_id
  || runMeta?.scenario_meta?.scenario_id
  || runMeta?.scenario_config?.meta?.scenario_id
  || '-'
);

const getRunId = (runMeta, fallback) => (
  runMeta?.run_id
  || runMeta?.job_id
  || fallback
  || ''
);

const normalizeJobStatus = (status) => String(status || 'unknown');

const getRequestFailureText = (result) => (
  result?.error
  || result?.result?.error
  || result?.result?.message
  || result?.message
  || ''
);

const isFailedActionResult = (result) => {
  const status = normalizeJobStatus(result?.result?.status || result?.job?.status);
  return !result?.available || Boolean(result?.error) || status === 'failed';
};

const getActionResultMessage = (result) => (
  getRequestFailureText(result)
  || result?.result?.finish_reason
  || 'Operations action failed'
);

const getJobErrorText = (job) => {
  if (!job) {
    return '';
  }
  const status = normalizeJobStatus(job.status);
  const stopReason = job.stop_reason;
  const checkpointError = job.latest_checkpoint?.details?.error;
  if (status !== 'failed') {
    return job.error || checkpointError || '';
  }
  if (typeof stopReason === 'string') {
    return job.error || checkpointError || stopReason;
  }
  return (
    job.error
    || checkpointError
    || stopReason?.message
    || stopReason?.reason
    || job.message
    || job.finish_reason
    || ''
  );
};

const getJobNoticeText = (job) => {
  if (!job) {
    return '';
  }
  const status = normalizeJobStatus(job.status);
  if (status === 'failed' || status === 'completed') {
    return '';
  }
  const stopReason = job.stop_reason;
  if (typeof stopReason === 'string') {
    return stopReason;
  }
  return (
    stopReason?.message
    || stopReason?.reason
    || job.message
    || job.finish_reason
    || ''
  );
};

const getScenarioKey = (scenario) => scenario?.scenario_id || scenario?.value || '';

const getScenarioLabel = (scenario) => (
  scenario?.label
  || scenario?.name
  || scenario?.scenario_id
  || scenario?.value
  || '-'
);

const getSingleCaseSummary = (scenario) => {
  const scenarioId = String(getScenarioKey(scenario) || '')
    .replace(/_scripted$/i, '')
    .replace(/_profit_objective$/i, '');
  return SINGLE_CASE_SUMMARIES[scenarioId] || '';
};

const getScenarioSummary = (scenario) => (
  getSingleCaseSummary(scenario)
  || scenario?.description
  || scenario?.summary
  || scenario?.config_defaults?.simulation?.market_demand_mode
  || ''
);

const getScenarioProfile = (scenario) => (
  scenario?.simulation_profile === 'single_enterprise' ? 'single' : 'multi'
);

const isScriptedScenarioVariant = (scenario) => (
  String(getScenarioKey(scenario)).toLowerCase().endsWith('_scripted')
);

const getExperimentDesign = (scenario) => (
  scenario?.experiment_design
  || scenario?.config_defaults?.experiment_design
  || {}
);

const getExperimentGroup = (scenario) => {
  const group = String(getExperimentDesign(scenario).experiment_group || '').toUpperCase();
  if (EXPERIMENT_GROUPS[group]) {
    return group;
  }
  if (isScriptedScenarioVariant(scenario)) {
    return 'C1';
  }
  if (String(getScenarioKey(scenario)).toLowerCase().includes('profit_objective')) {
    return 'C3';
  }
  if (getScenarioProfile(scenario) === 'single') {
    return 'S0';
  }
  return 'C2';
};

const getExperimentGroupMeta = (scenarioOrGroup) => {
  const group = typeof scenarioOrGroup === 'string'
    ? String(scenarioOrGroup).toUpperCase()
    : getExperimentGroup(scenarioOrGroup);
  return EXPERIMENT_GROUPS[group] || {
    id: group || '-',
    label: group || '-',
    title: '未标注',
    fullLabel: group || '未标注实验组',
    description: '',
    preset: 'agent',
  };
};

const getExperimentGroupLabel = (scenario) => {
  const meta = getExperimentGroupMeta(scenario);
  return `${meta.label} ${meta.title}`;
};

const getFormalExperimentConfig = (scenario) => (
  scenario?.config_defaults?.formal_experiment_config || {}
);

const getFormalExperimentRoleLabel = (scenario) => {
  const formalConfig = getFormalExperimentConfig(scenario);
  if (!formalConfig.ready_for_formal_run) {
    return '探索配置';
  }
  if (formalConfig.experiment_role === 'mechanism_calibration') {
    return '正式参数校验';
  }
  if (formalConfig.experiment_role === 'main_comparison') {
    return '正式主比较';
  }
  return '正式实验';
};

const getLongRunExperimentPolicy = (scenario) => (
  scenario?.config_defaults?.runtime_injection?.long_run_experiment_policy || {}
);

const getProfitObjectivePolicy = (scenario) => (
  scenario?.config_defaults?.runtime_injection?.profit_objective_policy || {}
);

const formatEvaluationWindow = (formalConfig) => {
  const window = formalConfig?.primary_evaluation_window || {};
  if (window.start_round === undefined || window.end_round_inclusive === undefined) {
    return '-';
  }
  return `Turn ${window.start_round}-Turn ${window.end_round_inclusive}`;
};

const formatObjectiveWeights = (objectiveWeights) => {
  const entries = Object.entries(objectiveWeights || {});
  if (!entries.length) {
    return '-';
  }
  return entries
    .map(([key, value]) => `${key}:${value}`)
    .join(' / ');
};

const getRecommendedPresetForScenario = (scenario) => (
  getExperimentGroupMeta(scenario).preset || 'agent'
);

const scenarioMatchesControlPreset = (scenario, presetId) => (
  presetId === 'scripted'
    ? isScriptedScenarioVariant(scenario)
    : !isScriptedScenarioVariant(scenario)
);

const getScenarioVariantForPreset = (selectedScenario, scenarioVariants = [], presetId = 'agent') => {
  const selectedKey = getScenarioKey(selectedScenario);
  const variants = [
    selectedScenario,
    ...(scenarioVariants || []),
  ].filter(Boolean);
  const uniqueVariants = Array.from(
    new Map(variants.map((variant) => [getScenarioKey(variant), variant])).values()
  );
  const selectedBaseKey = getScenarioBaseKey(selectedScenario);
  return (
    uniqueVariants.find((variant) => (
      getScenarioBaseKey(variant) === selectedBaseKey
      && scenarioMatchesControlPreset(variant, presetId)
    ))
    || uniqueVariants.find((variant) => getScenarioKey(variant) === selectedKey)
    || selectedScenario
  );
};

const getExperimentSortOrder = (scenario) => {
  const order = { E1: 1, C1: 2, C2: 3, C3: 4, S0: 5 };
  return order[getExperimentGroup(scenario)] || 99;
};

const sortScenarioVariants = (variants) => (
  [...(variants || [])].sort((left, right) => (
    getExperimentSortOrder(left) - getExperimentSortOrder(right)
    || getScenarioKey(left).localeCompare(getScenarioKey(right))
  ))
);

const isScriptedJob = (job) => {
  const tags = Array.isArray(job?.tags) ? job.tags.map((item) => String(item).toLowerCase()) : [];
  if (tags.includes('preset:scripted')) {
    return true;
  }
  const scriptedPolicy = job?.config_overrides?.runtime_injection?.scripted_rule_policy || {};
  if (scriptedPolicy.enabled === true) {
    return true;
  }
  return String(job?.execution_mode || '').toLowerCase() === 'scripted_subprocess';
};

const getActiveAgentJob = (jobs) => (
  jobs.find((job) => (
    ACTIVE_STATUSES.has(normalizeJobStatus(job?.status))
    && !isScriptedJob(job)
  )) || null
);

const getScenarioBaseKey = (scenario) => (
  String(getScenarioKey(scenario) || '')
    .replace(/_scripted$/i, '')
    .replace(/_profit_objective$/i, '')
);

const getScenarioMarketMode = (scenario) => (
  scenario?.config_defaults?.simulation?.market_demand_mode
  || scenario?.market_demand_mode
  || ''
);

const getExternalOrderIntegrity = (scenario) => (
  scenario?.config_defaults?.external_order_integrity || {}
);

const getScenarioDemandProduct = (scenario) => {
  const integrity = getExternalOrderIntegrity(scenario);
  if (integrity.demand_product_id) {
    return integrity.demand_product_id;
  }
  const simulation = scenario?.config_defaults?.simulation || {};
  const marketMode = String(simulation.market_demand_mode || '').toLowerCase();
  if (marketMode === 'shared_resource_market') {
    return simulation.shared_resource_config?.product_id || '-';
  }
  if (marketMode === 'herding_market') {
    return simulation.herding_config?.product_id || '-';
  }
  if (marketMode === 'cobweb') {
    return simulation.cobweb_config?.product_id || '-';
  }
  return simulation.beer_game_product_id || '-';
};

const formatExternalOrderTargets = (scenario) => {
  const targets = getExternalOrderIntegrity(scenario).targets || [];
  if (!targets.length) {
    return '-';
  }
  return targets
    .map((target) => `${target.enterprise_id}:${target.matched ? '匹配' : '不匹配'}`)
    .join(' / ');
};

const getMultiScenarioGroupId = (scenario) => {
  const scenarioId = String(getScenarioKey(scenario)).toLowerCase();
  const marketMode = String(getScenarioMarketMode(scenario)).toLowerCase();
  const text = `${scenarioId} ${marketMode}`.toLowerCase();
  if (
    scenarioId.startsWith('architecture_')
    || text.includes('architecture')
  ) {
    return null;
  }
  if (scenarioId === 'long_horizon_evolution') {
    return 'evolution';
  }
  if (text.includes('cobweb')) {
    return 'cobweb';
  }
  if (text.includes('commons') || marketMode === 'shared_resource_market') {
    return 'commons';
  }
  if (text.includes('herding') || marketMode === 'herding_market') {
    return 'herding';
  }
  return 'bullwhip';
};

const getScriptedModeForScenario = (scenario) => {
  const groupId = scenario?.scenario_group_id || getMultiScenarioGroupId(scenario);
  if (getScenarioProfile(scenario) === 'single') {
    return 'single_case';
  }
  return groupId || 'scripted_rules';
};

const buildMultiScenarioCards = (scenarios) => (
  MULTI_SCENARIO_GROUPS.map((group) => {
    const allVariants = sortScenarioVariants(scenarios.filter((scenario) => (
      getMultiScenarioGroupId(scenario) === group.id
    )));
    const primary = (
      (group.id === 'cobweb'
        ? allVariants.find((scenario) => getScenarioKey(scenario) === 'cobweb_divergent')
        : null)
      || allVariants.find((scenario) => getExperimentGroup(scenario) === 'C2')
      || allVariants[0]
    );
    if (!primary) {
      return null;
    }
    const availableExperimentGroups = Array.from(
      new Set(allVariants.map(getExperimentGroup).filter((item) => ['E1', 'C1', 'C2', 'C3'].includes(item)))
    );
    return {
      ...primary,
      scenario_id: getScenarioKey(primary),
      label: group.label,
      description: group.summary,
      scenario_group_id: group.id,
      scenario_group_label: group.label,
      available_experiment_groups: availableExperimentGroups,
      scenario_variants: allVariants,
      all_scenario_variants: allVariants,
    };
  }).filter(Boolean)
);

const getScenarioVariantIds = (scenario) => {
  const variants = scenario?.scenario_variants || [];
  const ids = variants.map(getScenarioKey).filter(Boolean);
  const primaryId = getScenarioKey(scenario);
  const baseId = getScenarioBaseKey(scenario);
  if (getScenarioProfile(scenario) === 'single' && baseId) {
    ids.push(baseId, `${baseId}_scripted`);
  }
  return Array.from(new Set([primaryId, ...ids].filter(Boolean)));
};

const getScenarioVariantsForSelection = (allScenarios, visibleScenarios, selectedScenario) => {
  const selectedKey = getScenarioKey(selectedScenario);
  const groupedScenario = visibleScenarios.find((scenario) => (
    getScenarioKey(scenario) === selectedKey
    || scenario.scenario_variants?.some((variant) => getScenarioKey(variant) === selectedKey)
  ));
  if (groupedScenario?.scenario_variants?.length) {
    return sortScenarioVariants(groupedScenario.all_scenario_variants || groupedScenario.scenario_variants);
  }
  const selectedBaseKey = getScenarioBaseKey(selectedScenario);
  if (!selectedBaseKey) {
    return [];
  }
  return allScenarios
    .filter((scenario) => getScenarioBaseKey(scenario) === selectedBaseKey)
    .sort((left, right) => (
      getExperimentSortOrder(left) - getExperimentSortOrder(right)
      || getScenarioKey(left).localeCompare(getScenarioKey(right))
    ));
};

const getJobsForScenarioSelection = (jobs, scenario) => {
  const ids = new Set(getScenarioVariantIds(scenario));
  return jobs.filter((job) => ids.has(job?.scenario_id));
};

const getLatestJobForScenario = (jobs, scenario) => {
  const scenarioJobs = getJobsForScenarioSelection(jobs, scenario);
  return [...scenarioJobs].sort((left, right) => (
    getJobActivityTimestamp(right) - getJobActivityTimestamp(left)
  ))[0] || null;
};

const getRunsForScenarioSelection = (runs, scenario) => {
  const ids = new Set(getScenarioVariantIds(scenario));
  return runs.filter((run) => ids.has(getScenarioId(run?.meta)));
};

const toFormValue = (value) => (
  value === null || value === undefined ? '' : String(value)
);

const toFormListValue = (value) => (
  Array.isArray(value) ? value.join(',') : toFormValue(value)
);

const getSingleCaseScriptedProfile = (scenario, scenarioVariants = []) => {
  const defaults = scenario?.config_defaults || {};
  const directProfile = (
    defaults.runtime_injection?.scripted_rule_policy?.single_enterprise_rules
    || defaults.runtime_injection?.scripted_rule_policy?.single_case
    || {}
  );
  if (Object.keys(directProfile).length > 0) {
    return directProfile;
  }
  const variants = [
    ...(scenario?.scenario_variants || []),
    ...(scenarioVariants || []),
  ];
  const scriptedVariant = variants.find((variant) => (
    String(getScenarioKey(variant)).toLowerCase().endsWith('_scripted')
  ));
  return (
    scriptedVariant?.config_defaults?.runtime_injection?.scripted_rule_policy?.single_enterprise_rules
    || scriptedVariant?.config_defaults?.runtime_injection?.scripted_rule_policy?.single_case
    || {}
  );
};

const buildConfigForm = (scenario, scenarioVariants = []) => {
  const defaults = scenario?.config_defaults || {};
  const simulation = defaults.simulation || {};
  const runtimeInjection = defaults.runtime_injection || {};
  const scriptedPolicy = runtimeInjection.scripted_rule_policy || {};
  const productionPolicy = scriptedPolicy.production || {};
  const singleCaseProfile = getSingleCaseScriptedProfile(scenario, scenarioVariants);
  const autoPolicy = defaults.auto_policy || {};
  const singleCasePolicy = runtimeInjection.single_enterprise_case_policy || {};
  return {
    agentRunSteps: toFormValue(simulation.agent_run_steps),
    serviceTotalSteps: toFormValue(simulation.service_total_steps),
    maxEnterpriseConcurrency: toFormValue(simulation.max_enterprise_concurrency),
    maxDepartmentConcurrency: toFormValue(simulation.max_department_concurrency),
    marketDemandMode: toFormValue(simulation.market_demand_mode),
    hrRecruitThreshold: toFormValue(autoPolicy.hr?.recruit_trigger_threshold),
    hrRecruitRatio: toFormValue(autoPolicy.hr?.recruit_ratio),
    inventoryExpandThreshold: toFormValue(autoPolicy.inventory?.expand_trigger_threshold),
    inventoryExpandRatio: toFormValue(autoPolicy.inventory?.expand_ratio),
    salaryInterval: toFormValue(runtimeInjection.salary_payment_interval_days),
    inventoryCostDaily: runtimeInjection.inventory_cost_daily_settlement_enabled ? 'true' : 'false',
    scriptedEnabled: scriptedPolicy.enabled ? 'true' : 'false',
    scriptedMode: toFormValue(scriptedPolicy.mode),
    productionBaseQuantity: toFormValue(productionPolicy.base_quantity),
    productionOscillationAmplitude: toFormValue(productionPolicy.oscillation_amplitude),
    productionGrowthRate: toFormValue(productionPolicy.growth_rate),
    productionPeerSignalSensitivity: toFormValue(productionPolicy.peer_signal_sensitivity),
    singlePrewarmRounds: toFormValue(singleCasePolicy.prewarm_rounds),
    singleHandoffDay: toFormValue(singleCasePolicy.handoff_day),
    singleAcceptOrdersPerRound: toFormValue(singleCaseProfile.accept_orders_per_round),
    singleMarketDevelopmentRounds: toFormListValue(singleCaseProfile.market_development_rounds),
    singleMarketDevelopmentWorkers: toFormValue(singleCaseProfile.market_development_workers),
    singleProductionRoundInterval: toFormValue(singleCaseProfile.production_round_interval),
    singleProductionQuantity: toFormValue(singleCaseProfile.production_quantity),
    singleProductionDailyCapacity: toFormValue(singleCaseProfile.production_daily_capacity),
    singleBuildLineRounds: toFormListValue(singleCaseProfile.build_line_rounds),
    singleBuildLineType: toFormValue(singleCaseProfile.build_line_type),
    singleProcurementStrategy: toFormValue(singleCaseProfile.procurement_strategy),
    singleMaterialCoverageTargetQuantity: toFormValue(singleCaseProfile.material_coverage_target_quantity),
    singleMaterialOrderMultiplier: toFormValue(singleCaseProfile.material_order_multiplier),
    singlePreferredLogisticsMode: toFormValue(singleCaseProfile.preferred_logistics_mode),
    singleHrRecruitRounds: toFormListValue(singleCaseProfile.hr_recruit_rounds),
    singleHrTargetDepartment: toFormValue(singleCaseProfile.hr_target_department),
    singleHrRecruitPeople: toFormValue(singleCaseProfile.hr_recruit_people),
    singleCashGuardThreshold: toFormValue(singleCaseProfile.cash_guard_threshold),
    singleAvoidCapexActions: singleCaseProfile.avoid_capex_actions ? 'true' : 'false',
  };
};

const buildPresetConfigForm = (scenario, presetId = 'agent', scenarioVariants = []) => {
  const form = buildConfigForm(scenario, scenarioVariants);
  if (presetId === 'scripted') {
    return {
      ...form,
      scriptedEnabled: 'true',
      scriptedMode: form.scriptedMode || getScriptedModeForScenario(scenario),
    };
  }
  return {
    ...form,
    scriptedEnabled: 'false',
    scriptedMode: form.scriptedMode || getScriptedModeForScenario(scenario),
  };
};

const toNumberOrUndefined = (value) => {
  if (value === '' || value === null || value === undefined) {
    return undefined;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : undefined;
};

const toNumberListOrUndefined = (value) => {
  if (value === '' || value === null || value === undefined) {
    return undefined;
  }
  const values = String(value)
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  return values.length > 0 ? values : undefined;
};

const compactObject = (value) => {
  if (!value || typeof value !== 'object') {
    return value;
  }
  const result = {};
  Object.entries(value).forEach(([key, child]) => {
    if (child === undefined || child === '') {
      return;
    }
    if (child && typeof child === 'object' && !Array.isArray(child)) {
      const compacted = compactObject(child);
      if (Object.keys(compacted).length > 0) {
        result[key] = compacted;
      }
      return;
    }
    result[key] = child;
  });
  return result;
};

const buildConfigOverrides = (form, scenario) => compactObject({
  simulation: {
    agent_run_steps: toNumberOrUndefined(form.agentRunSteps),
    service_total_steps: toNumberOrUndefined(form.serviceTotalSteps),
    max_enterprise_concurrency: toNumberOrUndefined(form.maxEnterpriseConcurrency),
    max_department_concurrency: toNumberOrUndefined(form.maxDepartmentConcurrency),
  },
  auto_policy: {
    hr: {
      recruit_trigger_threshold: toNumberOrUndefined(form.hrRecruitThreshold),
      recruit_ratio: toNumberOrUndefined(form.hrRecruitRatio),
    },
    inventory: {
      expand_trigger_threshold: toNumberOrUndefined(form.inventoryExpandThreshold),
      expand_ratio: toNumberOrUndefined(form.inventoryExpandRatio),
    },
  },
  runtime_injection: {
    salary_payment_interval_days: toNumberOrUndefined(form.salaryInterval),
    inventory_cost_daily_settlement_enabled: form.inventoryCostDaily === 'true',
    scripted_rule_policy: {
      enabled: form.scriptedEnabled === 'true',
      analyst: {
        enabled: form.scriptedEnabled === 'true',
      },
      departments: {
        apply_to_departments: ['all'],
      },
      mode: (
        form.scriptedEnabled === 'true'
          ? (
            form.scriptedMode && form.scriptedMode !== 'scripted_rules'
              ? form.scriptedMode
              : getScriptedModeForScenario(scenario)
          )
          : (form.scriptedMode || getScriptedModeForScenario(scenario))
      ),
      production: {
        base_quantity: toNumberOrUndefined(form.productionBaseQuantity),
        oscillation_amplitude: toNumberOrUndefined(form.productionOscillationAmplitude),
        growth_rate: toNumberOrUndefined(form.productionGrowthRate),
        peer_signal_sensitivity: toNumberOrUndefined(form.productionPeerSignalSensitivity),
      },
      single_enterprise_rules: scenario?.simulation_profile === 'single_enterprise' ? {
        accept_orders_per_round: toNumberOrUndefined(form.singleAcceptOrdersPerRound),
        market_development_rounds: toNumberListOrUndefined(form.singleMarketDevelopmentRounds),
        market_development_workers: toNumberOrUndefined(form.singleMarketDevelopmentWorkers),
        production_round_interval: toNumberOrUndefined(form.singleProductionRoundInterval),
        production_quantity: toNumberOrUndefined(form.singleProductionQuantity),
        production_daily_capacity: toNumberOrUndefined(form.singleProductionDailyCapacity),
        build_line_rounds: toNumberListOrUndefined(form.singleBuildLineRounds),
        build_line_type: form.singleBuildLineType,
        procurement_strategy: form.singleProcurementStrategy,
        material_coverage_target_quantity: toNumberOrUndefined(form.singleMaterialCoverageTargetQuantity),
        material_order_multiplier: toNumberOrUndefined(form.singleMaterialOrderMultiplier),
        preferred_logistics_mode: form.singlePreferredLogisticsMode,
        hr_recruit_rounds: toNumberListOrUndefined(form.singleHrRecruitRounds),
        hr_target_department: form.singleHrTargetDepartment,
        hr_recruit_people: toNumberOrUndefined(form.singleHrRecruitPeople),
        cash_guard_threshold: toNumberOrUndefined(form.singleCashGuardThreshold),
        avoid_capex_actions: form.singleAvoidCapexActions === 'true',
      } : undefined,
      single_case: scenario?.simulation_profile === 'single_enterprise' ? {
        accept_orders_per_round: toNumberOrUndefined(form.singleAcceptOrdersPerRound),
        market_development_rounds: toNumberListOrUndefined(form.singleMarketDevelopmentRounds),
        market_development_workers: toNumberOrUndefined(form.singleMarketDevelopmentWorkers),
        production_round_interval: toNumberOrUndefined(form.singleProductionRoundInterval),
        production_quantity: toNumberOrUndefined(form.singleProductionQuantity),
        production_daily_capacity: toNumberOrUndefined(form.singleProductionDailyCapacity),
        build_line_rounds: toNumberListOrUndefined(form.singleBuildLineRounds),
        build_line_type: form.singleBuildLineType,
        procurement_strategy: form.singleProcurementStrategy,
        material_coverage_target_quantity: toNumberOrUndefined(form.singleMaterialCoverageTargetQuantity),
        material_order_multiplier: toNumberOrUndefined(form.singleMaterialOrderMultiplier),
        preferred_logistics_mode: form.singlePreferredLogisticsMode,
        hr_recruit_rounds: toNumberListOrUndefined(form.singleHrRecruitRounds),
        hr_target_department: form.singleHrTargetDepartment,
        hr_recruit_people: toNumberOrUndefined(form.singleHrRecruitPeople),
        cash_guard_threshold: toNumberOrUndefined(form.singleCashGuardThreshold),
        avoid_capex_actions: form.singleAvoidCapexActions === 'true',
      } : undefined,
    },
    single_enterprise_case_policy: {
      prewarm_rounds: toNumberOrUndefined(form.singlePrewarmRounds),
      handoff_day: toNumberOrUndefined(form.singleHandoffDay),
    },
  },
});

const findCurrentJob = (jobs, currentRunId, currentRunMeta, currentRunSourceLabel) => {
  const runId = getRunId(currentRunMeta, currentRunId);
  const explicitJobId = currentRunMeta?.job_id || currentRunMeta?.operations_job?.job_id;
  const sourceLabel = String(currentRunSourceLabel || '');
  return jobs.find((job) => (
    (explicitJobId && job?.job_id === explicitJobId)
    || (runId && job?.run_id === runId)
    || (runId && job?.job_id === runId)
    || (sourceLabel && String(job?.artifact_root || '').includes(sourceLabel))
  )) || null;
};

const ExperimentOperationsView = ({
  currentRunId,
  currentRunMeta,
  currentRunSourceLabel,
  availableRuns = [],
}) => {
  const [jobs, setJobs] = useState([]);
  const [scenarios, setScenarios] = useState([]);
  const [backendAvailable, setBackendAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submittingAction, setSubmittingAction] = useState('');
  const [error, setError] = useState('');
  const [actionMessage, setActionMessage] = useState('');
  const [lastLoadedAt, setLastLoadedAt] = useState('');
  const [createScenarioId, setCreateScenarioId] = useState(getScenarioId(currentRunMeta));
  const [scenarioScope, setScenarioScope] = useState('multi');
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [detailScenario, setDetailScenario] = useState(null);
  const [toast, setToast] = useState(null);
  const jobsRefreshInFlightRef = useRef(false);

  const showToast = (type, message) => {
    setToast({ type, message });
  };

  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => (
      (scenario.scenario_id || scenario.value) === createScenarioId
    )) || null,
    [scenarios, createScenarioId]
  );

  const visibleScenarios = useMemo(
    () => {
      const scopedScenarios = scenarios.filter((scenario) => (
        getScenarioProfile(scenario) === scenarioScope
      ));
      return scenarioScope === 'multi'
        ? buildMultiScenarioCards(scopedScenarios)
        : scopedScenarios.filter((scenario) => !isScriptedScenarioVariant(scenario));
    },
    [scenarios, scenarioScope]
  );

  const currentJob = useMemo(
    () => findCurrentJob(jobs, currentRunId, currentRunMeta, currentRunSourceLabel),
    [jobs, currentRunId, currentRunMeta, currentRunSourceLabel]
  );

  const statusCounts = useMemo(() => {
    const counts = {
      queued: 0,
      running: 0,
      stop_requested: 0,
      completed: 0,
      failed: 0,
      stopped: 0,
      active: 0,
    };
    jobs.forEach((job) => {
      const status = normalizeJobStatus(job?.status);
      if (counts[status] !== undefined) {
        counts[status] += 1;
      }
      if (ACTIVE_STATUSES.has(status)) {
        counts.active += 1;
      }
    });
    return counts;
  }, [jobs]);

  const recentRuns = useMemo(
    () => availableRuns.slice(0, 6),
    [availableRuns]
  );

  const activeAgentJob = useMemo(
    () => getActiveAgentJob(jobs),
    [jobs]
  );

  const upsertJobRecord = (job) => {
    if (!job?.job_id) {
      return;
    }
    setJobs((previous) => {
      const next = previous.filter((item) => item?.job_id !== job.job_id);
      next.unshift(job);
      return next.sort((left, right) => (
        getJobActivityTimestamp(right) - getJobActivityTimestamp(left)
      ));
    });
  };

  const loadJobs = async ({ silent = false } = {}) => {
    if (jobsRefreshInFlightRef.current) {
      return;
    }
    jobsRefreshInFlightRef.current = true;
    if (!silent) {
      setLoading(true);
    }
    try {
      const [jobResult, scenarioResult] = await Promise.all([
        listOperationsJobs({ limit: 100 }),
        listOperationScenarios(),
      ]);
      setBackendAvailable(jobResult.available || scenarioResult.available);
      if (jobResult.available || Array.isArray(jobResult.jobs)) {
        setJobs(jobResult.jobs || []);
      }
      if (scenarioResult.available && Array.isArray(scenarioResult.scenarios) && scenarioResult.scenarios.length > 0) {
        setScenarios(scenarioResult.scenarios);
      }
      const nextError = jobResult.error || scenarioResult.error || '';
      setError(nextError);
      setLastLoadedAt(new Date().toLocaleString('zh-CN'));
    } catch (loadError) {
      const message = loadError?.message || String(loadError);
      setBackendAvailable(false);
      setError(message || 'Operations backend 暂不可用');
    } finally {
      jobsRefreshInFlightRef.current = false;
      if (!silent) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    loadJobs();
  }, []);

  useEffect(() => {
    if (!toast) {
      return undefined;
    }
    const timer = window.setTimeout(() => setToast(null), 3600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const nextScenarioId = getScenarioId(currentRunMeta);
    if (nextScenarioId && nextScenarioId !== '-') {
      setCreateScenarioId(nextScenarioId);
    }
  }, [currentRunMeta]);

  useEffect(() => {
    if (!detailScenario) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      loadJobs({ silent: true });
    }, 3500);
    return () => window.clearInterval(timer);
  }, [detailScenario]);

  useEffect(() => {
    if (statusCounts.active <= 0) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      loadJobs({ silent: true });
    }, 3500);
    return () => window.clearInterval(timer);
  }, [statusCounts.active]);

  const runAction = async (actionKey, action) => {
    setSubmittingAction(actionKey);
    setError('');
    setActionMessage('');
    showToast(
      'info',
      actionKey.startsWith('delete-')
        ? '正在删除任务记录...'
        : actionKey.startsWith('stop-')
          ? '正在请求中止模拟...'
          : '操作已提交，正在处理...'
    );
    let result = null;
    try {
      result = await action();
      if (isFailedActionResult(result)) {
        const message = getActionResultMessage(result);
        setError(message);
        showToast('error', message);
      } else {
        const message = actionKey.startsWith('delete-')
          ? '任务记录已删除。'
          : actionKey.startsWith('stop-')
            ? '中止请求已提交，任务将在最近的完整轮次边界封口。'
            : '操作已写入 operations job 状态。';
        setActionMessage(message);
        showToast('success', message);
      }
      return result;
    } catch (actionError) {
      const message = actionError?.message || String(actionError);
      setError(message || 'Operations action failed');
      showToast('error', message || 'Operations action failed');
      return { available: false, error: message };
    } finally {
      try {
        await loadJobs();
      } finally {
        setSubmittingAction('');
      }
    }
  };

  const launchJobInBackground = (jobId, scenarioId) => {
    if (!jobId) {
      return;
    }
    showToast('info', `任务 ${jobId} 已创建，后台运行已触发。`);
    runOperationsJob(jobId, {
      scenario_id: scenarioId,
      worker_id: 'operations-page-worker',
    }).then((runResult) => {
      if (isFailedActionResult(runResult)) {
        const message = getActionResultMessage(runResult);
        setError(message);
        showToast('error', message);
        return;
      }
      showToast('success', `任务 ${jobId} 已完成或已写入运行状态。`);
    }).catch((runError) => {
      const message = runError?.message || String(runError);
      setError(message);
      showToast('error', message || '后台运行失败');
    }).finally(() => {
      loadJobs();
    });
  };

  const createJobForScenario = async (scenario, {
    runImmediately = false,
    formOverride = null,
    preset = 'agent',
  } = {}) => {
    const scenarioId = getScenarioKey(scenario);
    if (!scenarioId) {
      const message = '请先选择场景。';
      setError(message);
      showToast('error', message);
      return null;
    }
    if (runImmediately && preset !== 'scripted' && activeAgentJob) {
      const message = `已有 Agent Skill 任务正在执行：${formatShortRunId(activeAgentJob.job_id)}。请等待完成或先中止该任务。`;
      setError(message);
      showToast('error', message);
      return null;
    }
    const scenarioForm = formOverride || buildPresetConfigForm(scenario, 'agent');
    const plannedSteps = scenarioForm.agentRunSteps === '' ? null : Number(scenarioForm.agentRunSteps);
    if (plannedSteps !== null && (!Number.isFinite(plannedSteps) || plannedSteps < 1)) {
      const message = '计划轮次必须为空或不小于 1。';
      setError(message);
      showToast('error', message);
      return null;
    }

    const result = await runAction(
      runImmediately ? `run-${scenarioId}` : `create-${scenarioId}`,
      async () => {
        const created = await createOperationsJob({
          scenario_id: scenarioId,
          planned_total_steps: plannedSteps,
          tags: ['ui', `preset:${preset}`],
          requested_by: 'operations-page',
          config_overrides: buildConfigOverrides(scenarioForm, scenario),
        });
        if (created.available && created.job?.job_id) {
          upsertJobRecord(created.job);
        }
        if (!created.available || created.error || !created.job?.job_id || !runImmediately) {
          return created;
        }
        launchJobInBackground(created.job.job_id, scenarioId);
        return created;
      }
    );
    return result;
  };

  const handleOpenConfig = (scenario) => {
    const scenarioId = getScenarioKey(scenario);
    setCreateScenarioId(scenarioId);
    setConfigModalOpen(true);
  };

  const handleRunFromModal = async ({ form, preset = 'agent' } = {}) => {
    if (!selectedScenario) {
      const message = '请先选择场景。';
      setError(message);
      showToast('error', message);
      return;
    }
    const scenarioVariants = getScenarioVariantsForSelection(
      scenarios,
      visibleScenarios,
      selectedScenario
    );
    const launchScenario = getScenarioVariantForPreset(
      selectedScenario,
      scenarioVariants,
      preset
    );
    await createJobForScenario(launchScenario, {
      runImmediately: true,
      formOverride: form || buildPresetConfigForm(selectedScenario, 'agent'),
      preset,
    });
    setConfigModalOpen(false);
  };

  const handleDeleteJob = async (job) => {
    if (!job?.job_id) {
      return null;
    }
    return runAction(`delete-${job.job_id}`, () => deleteOperationsJob(job.job_id, {
      scenario_id: job.scenario_id,
      force: true,
    }));
  };

  const handleStopJob = async (job) => {
    if (!job?.job_id) {
      return null;
    }
    return runAction(`stop-${job.job_id}`, () => stopOperationsJob(job.job_id, {
      scenario_id: job.scenario_id,
      reason: 'Stopped from experiment operations page',
      requested_by: 'operations-page',
    }));
  };

  const handleResumeJob = async (job) => {
    if (!job?.job_id) {
      return null;
    }
    if (activeAgentJob) {
      const message = `已有 Agent Skill 任务正在执行：${formatShortRunId(activeAgentJob.job_id)}。请等待完成或先中止该任务。`;
      setError(message);
      showToast('error', message);
      return null;
    }
    const result = await runAction(`resume-${job.job_id}`, () => resumeOperationsJob(job.job_id, {
      scenario_id: job.scenario_id,
      target_total_steps: 200,
      requested_by: 'operations-page',
    }));
    if (result?.available && result?.job?.job_id) {
      upsertJobRecord(result.job);
      launchJobInBackground(result.job.job_id, result.job.scenario_id);
    }
    return result;
  };

  const handleResumeArtifact = async (run) => {
    if (!run?.source || !run?.name) {
      return null;
    }
    if (activeAgentJob) {
      const message = `已有 Agent Skill 任务正在执行：${formatShortRunId(activeAgentJob.job_id)}。请等待完成或先中止该任务。`;
      setError(message);
      showToast('error', message);
      return null;
    }
    const result = await runAction(
      `resume-artifact-${run.id}`,
      () => resumeArtifactRun({
        source: run.source,
        name: run.name,
        target_total_steps: 200,
        requested_by: 'operations-page',
      })
    );
    if (result?.available && result?.job?.job_id) {
      upsertJobRecord(result.job);
      launchJobInBackground(result.job.job_id, result.job.scenario_id);
    }
    return result;
  };

  return (
    <div className="experiment-ops-page">
      {toast && (
        <div className={`experiment-ops-toast ${toast.type}`} role="status">
          {toast.message}
        </div>
      )}
      <section className="experiment-ops-command-bar">
        <div className="experiment-ops-command-main">
          <div className={`experiment-ops-connection ${backendAvailable ? 'ready' : 'offline'}`}>
            <strong>{backendAvailable ? '服务已连接' : '服务未连接'}</strong>
            <span>{lastLoadedAt || '-'}</span>
          </div>
          <div className="experiment-ops-kpis compact">
            <MetricCard label="活跃" value={statusCounts.active} detail="queued / running" />
            <MetricCard label="运行中" value={statusCounts.running} detail="running" />
            <MetricCard label="已完成" value={statusCounts.completed} detail="completed" />
            <MetricCard label="失败/停止" value={statusCounts.failed + statusCounts.stopped} detail="failed / stopped" tone="danger" />
          </div>
          <button type="button" className="experiment-ops-refresh" onClick={loadJobs}>
            {loading ? '刷新中...' : '刷新状态'}
          </button>
        </div>

        <div className="experiment-ops-bottom-details">
          <div className="experiment-ops-bottom-panel">
            <strong>任务状态</strong>
            {!backendAvailable ? (
              <span>{error || '请先启动系统服务。'}</span>
            ) : jobs.length === 0 ? (
              <span>暂无任务</span>
            ) : (
              <div className="experiment-ops-mini-table">
                {jobs.slice(0, 8).map((job) => {
                  const status = normalizeJobStatus(job.status);
                  return (
                    <div key={job.job_id} className={currentJob?.job_id === job.job_id ? 'linked' : ''}>
                      <span>{formatValue(job.scenario_id)}</span>
                      <strong className={`experiment-ops-status ${status}`}>
                        {STATUS_LABELS[job.status] || formatValue(job.status)}
                      </strong>
                      <small>{formatTime(job.updated_at || job.created_at)}</small>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div className="experiment-ops-bottom-panel">
            <strong>近期运行结果</strong>
            <div className="experiment-ops-mini-runs">
              {recentRuns.length > 0 ? (
                recentRuns.slice(0, 5).map((run) => (
                  <span key={run.id}>
                    {run.sourceLabel || run.id} · {getScenarioId(run.meta)}
                  </span>
                ))
              ) : (
                <span>暂无运行结果</span>
              )}
            </div>
          </div>
        </div>
      </section>

      {(actionMessage || error) && (
        <section className="experiment-ops-feedback">
          {actionMessage && <p className="experiment-ops-success">{actionMessage}</p>}
          {error && <p className="experiment-ops-error">{error}</p>}
        </section>
      )}

      <section className="experiment-scenario-stage">
        <div className="experiment-scope-switch">
          <button
            type="button"
            className={scenarioScope === 'multi' ? 'active' : ''}
            onClick={() => {
              setScenarioScope('multi');
            }}
          >
            多企业场景
          </button>
          <button
            type="button"
            className={scenarioScope === 'single' ? 'active' : ''}
            onClick={() => {
              setScenarioScope('single');
            }}
          >
            单企业场景
          </button>
        </div>

        <div className={`experiment-scenario-grid ${scenarioScope}`}>
          {visibleScenarios.length > 0 ? (
            visibleScenarios.map((scenario) => {
              const scenarioId = getScenarioKey(scenario);
              const experimentMeta = getExperimentGroupMeta(scenario);
              const scenarioJob = getLatestJobForScenario(jobs, scenario);
              const scenarioStatus = normalizeJobStatus(scenarioJob?.status);
              const isBusy = Boolean(submittingAction);
              const scenarioJobs = getJobsForScenarioSelection(jobs, scenario);
              const scenarioRuns = getRunsForScenarioSelection(availableRuns, scenario);
              const isSelected = (
                createScenarioId === scenarioId
                || scenario.scenario_variants?.some((variant) => getScenarioKey(variant) === createScenarioId)
                || scenario.all_scenario_variants?.some((variant) => getScenarioKey(variant) === createScenarioId)
              );
              const availableGroups = scenario.available_experiment_groups || [getExperimentGroup(scenario)];
              const hasScenarioActivity = scenarioJobs.length > 0 || scenarioRuns.length > 0;
              const scenarioStatusLabel = scenarioJob
                ? (STATUS_LABELS[scenarioStatus] || scenarioStatus)
                : '暂无任务';
              const scenarioRunLabel = scenarioJob
                ? formatShortRunId(scenarioJob.run_id || scenarioJob.job_id)
                : '未启动';
              const scenarioTimeLabel = scenarioJob
                ? formatCompactTime(getJobActivityTime(scenarioJob))
                : '-';
              return (
                <article key={scenarioId} className={`experiment-scenario-card ${isSelected ? 'selected' : ''}`}>
                  <div className="experiment-scenario-card-head">
                    <div className="experiment-scenario-card-badges">
                      <span>{scenarioScope === 'single' ? 'Single Case' : 'Multi Case'}</span>
                      <ExperimentGroupBadge group={experimentMeta.id} />
                    </div>
                    <strong>{getScenarioLabel(scenario)}</strong>
                    {scenarioScope === 'multi' && (
                      <div className="experiment-group-chip-row">
                        {availableGroups.map((group) => (
                          <ExperimentGroupBadge key={group} group={group} compact />
                        ))}
                      </div>
                    )}
                  </div>
                  <p>{getScenarioSummary(scenario) || scenarioId}</p>
                  <div className={`experiment-scenario-latest ${scenarioJob ? scenarioStatus : 'idle'}`}>
                    <strong>{scenarioStatusLabel}</strong>
                    <span>{scenarioRunLabel}</span>
                    <small>{scenarioTimeLabel}</small>
                  </div>
                  <div className="experiment-scenario-metrics">
                    <InfoRow label={scenarioScope === 'multi' ? '默认配置' : '场景 ID'} value={scenarioId} />
                    <InfoRow label="实验类别" value={getExperimentGroupLabel(scenario)} />
                    <InfoRow label="轮次" value={scenario?.config_defaults?.simulation?.agent_run_steps} />
                    <InfoRow label="模式" value={scenario?.config_defaults?.simulation?.market_demand_mode} />
                    <InfoRow label="需求商品" value={getScenarioDemandProduct(scenario)} />
                    <InfoRow
                      label={scenarioScope === 'multi' ? '可选配置' : '最新任务'}
                      value={scenarioScope === 'multi'
                        ? `${scenario.scenario_variants?.length || 1} 组`
                        : scenarioRunLabel}
                    />
                  </div>
                  <div className="experiment-scenario-actions">
                    <button
                      type="button"
                      className="experiment-ops-primary-action"
                      disabled={!backendAvailable || isBusy}
                      onClick={() => handleOpenConfig(scenario)}
                    >
                      配置启动
                    </button>
                    <button
                      type="button"
                      className="experiment-ops-secondary-action ghost"
                      disabled={!hasScenarioActivity}
                      onClick={() => setDetailScenario(scenario)}
                    >
                      运行详情
                    </button>
                  </div>
                </article>
              );
            })
          ) : (
            <div className="experiment-ops-empty">
              <strong>暂无可用场景</strong>
            </div>
          )}
        </div>
      </section>

      {configModalOpen && (
        <ConfigModal
          selectedScenario={selectedScenario}
          scenarioVariants={getScenarioVariantsForSelection(scenarios, visibleScenarios, selectedScenario)}
          backendAvailable={backendAvailable}
          submittingAction={submittingAction}
          onVariantChange={(scenarioId) => {
            const nextScenario = scenarios.find((scenario) => getScenarioKey(scenario) === scenarioId);
            if (!nextScenario) {
              return;
            }
            setCreateScenarioId(scenarioId);
          }}
          onNotify={showToast}
          activeAgentJob={activeAgentJob}
          onClose={() => setConfigModalOpen(false)}
          onRun={handleRunFromModal}
        />
      )}
      {detailScenario && (
        <RunDetailModal
          scenario={detailScenario}
          jobs={getJobsForScenarioSelection(jobs, detailScenario)}
          runs={getRunsForScenarioSelection(availableRuns, detailScenario)}
          submittingAction={submittingAction}
          onDeleteJob={handleDeleteJob}
          onStopJob={handleStopJob}
          onResumeJob={handleResumeJob}
          onResumeArtifact={handleResumeArtifact}
          onRefreshJobs={loadJobs}
          onClose={() => setDetailScenario(null)}
        />
      )}
    </div>
  );
};

const MetricCard = ({ label, value, detail, tone = '' }) => (
  <div className={`experiment-ops-metric ${tone}`}>
    <span>{label}</span>
    <strong>{formatValue(value)}</strong>
    <small>{detail}</small>
  </div>
);

const InfoRow = ({ label, value }) => (
  <div className="experiment-ops-info-row">
    <span>{label}</span>
    <strong>{formatValue(value)}</strong>
  </div>
);

const ExperimentGroupBadge = ({ group, compact = false }) => {
  const meta = getExperimentGroupMeta(group);
  return (
    <span className={`experiment-group-badge group-${meta.id.toLowerCase()} ${compact ? 'compact' : ''}`}>
      {compact ? meta.label : `${meta.label} ${meta.title}`}
    </span>
  );
};

const ConfigModal = ({
  selectedScenario,
  scenarioVariants = [],
  backendAvailable,
  submittingAction,
  onVariantChange,
  onNotify,
  activeAgentJob,
  onClose,
  onRun,
}) => {
  const disabled = !backendAvailable || Boolean(submittingAction);
  const isSingle = selectedScenario?.simulation_profile === 'single_enterprise';
  const scenarioVariantKey = scenarioVariants.map(getScenarioKey).filter(Boolean).join('|');
  const recommendedPreset = getRecommendedPresetForScenario(selectedScenario);
  const selectedExperimentMeta = getExperimentGroupMeta(selectedScenario);
  const selectedExperimentDesign = getExperimentDesign(selectedScenario);
  const formalExperimentConfig = getFormalExperimentConfig(selectedScenario);
  const longRunPolicy = getLongRunExperimentPolicy(selectedScenario);
  const profitObjectivePolicy = getProfitObjectivePolicy(selectedScenario);
  const externalEnvironmentPolicy = (
    selectedScenario?.config_defaults?.runtime_injection?.external_environment_policy
    || {}
  );
  const evolutionScenario = getMultiScenarioGroupId(selectedScenario) === 'evolution';
  const externalOrderIntegrity = getExternalOrderIntegrity(selectedScenario);
  const cobwebConfig = selectedScenario?.config_defaults?.simulation?.cobweb_config || {};
  const cobwebGuidancePolicy = (
    selectedScenario?.config_defaults?.runtime_injection?.cobweb_enterprise_guidance_policy
    || {}
  );
  const [controlPreset, setControlPreset] = useState(recommendedPreset);
  const [isEditing, setIsEditing] = useState(false);
  const [localForm, setLocalForm] = useState(() => (
    buildPresetConfigForm(selectedScenario, recommendedPreset, scenarioVariants)
  ));

  useEffect(() => {
    const nextPreset = getRecommendedPresetForScenario(selectedScenario);
    setControlPreset(nextPreset);
    setLocalForm(buildPresetConfigForm(selectedScenario, nextPreset, scenarioVariants));
    setIsEditing(false);
  }, [selectedScenario?.scenario_id, selectedScenario?.value, scenarioVariantKey]);

  const handlePresetChange = (presetId) => {
    const targetScenario = getScenarioVariantForPreset(selectedScenario, scenarioVariants, presetId);
    const targetScenarioId = getScenarioKey(targetScenario);
    const currentScenarioId = getScenarioKey(selectedScenario);
    setControlPreset(presetId);
    setLocalForm(buildPresetConfigForm(targetScenario, presetId, scenarioVariants));
    setIsEditing(false);
    if (targetScenarioId && targetScenarioId !== currentScenarioId) {
      onVariantChange(targetScenarioId);
    } else if (targetScenarioId === currentScenarioId && !scenarioMatchesControlPreset(targetScenario, presetId)) {
      onNotify?.('info', '当前场景没有独立的 Scripted 变体，将在本次启动参数中切换规则脚本模式。');
    }
  };

  const handleFieldChange = (field, value) => {
    setLocalForm((previous) => ({
      ...previous,
      [field]: value,
    }));
  };

  const handleEditToggle = () => {
    setIsEditing((previous) => {
      const next = !previous;
      onNotify?.(
        'success',
        next ? '已开启本次临时配置修改。' : '已切回只读配置查看。'
      );
      return next;
    });
  };

  const fieldDisabled = disabled || !isEditing;
  const agentRunLocked = controlPreset !== 'scripted' && Boolean(activeAgentJob);
  const runDisabled = disabled || agentRunLocked;

  return (
    <div className="experiment-config-modal-backdrop" role="presentation">
      <div className="experiment-config-modal" role="dialog" aria-modal="true" aria-label="场景配置">
        <header className="experiment-config-modal-header">
          <div>
            <span>{isSingle ? '单企业场景配置' : '多企业场景配置'}</span>
            <strong>{getScenarioLabel(selectedScenario)}</strong>
          </div>
          <button type="button" className="experiment-config-close" onClick={onClose}>
            关闭
          </button>
        </header>

        <div className="experiment-config-modal-body">
          <section className="experiment-design-summary">
            <div>
              <h4>实验类别</h4>
              <div className="experiment-design-heading">
                <ExperimentGroupBadge group={selectedExperimentMeta.id} />
                <strong>{selectedExperimentMeta.fullLabel}</strong>
              </div>
              <p>{selectedExperimentMeta.description}</p>
            </div>
            <div className="experiment-design-fields">
              <InfoRow label="决策模式" value={selectedExperimentDesign.decision_regime} />
              <InfoRow label="目标画像" value={selectedExperimentDesign.agent_objective_profile} />
              <InfoRow label="约束层级" value={selectedExperimentDesign.constraint_level} />
              <InfoRow label="正式轮次" value={formalExperimentConfig.total_steps || localForm.agentRunSteps} />
              <InfoRow label="主分析窗口" value={formatEvaluationWindow(formalExperimentConfig)} />
              {getMultiScenarioGroupId(selectedScenario) === 'cobweb' && (
                <>
                  <InfoRow label="实验角色" value={getFormalExperimentRoleLabel(selectedScenario)} />
                  <InfoRow label="参数区间" value={formalExperimentConfig.parameter_regime || '探索'} />
                  <InfoRow label="响应控制器" value={cobwebConfig.production_response_mode || '-'} />
                  <InfoRow label="决策画像" value={cobwebConfig.decision_profile || '-'} />
                  <InfoRow
                    label="供给反馈"
                    value={`${cobwebConfig.endogenous_supply_source || '-'} / lag ${cobwebConfig.endogenous_supply_lag_rounds ?? '-'}`}
                  />
                  <InfoRow
                    label="机制引导"
                    value={cobwebGuidancePolicy.enabled ? '开启' : '关闭'}
                  />
                </>
              )}
              <InfoRow label="需求商品" value={getScenarioDemandProduct(selectedScenario)} />
              <InfoRow label="注入目标" value={formatExternalOrderTargets(selectedScenario)} />
              <InfoRow
                label="商品校验"
                value={externalOrderIntegrity.enabled
                  ? (externalOrderIntegrity.ok ? '通过' : '不匹配')
                  : '-'}
              />
              <InfoRow
                label="长跑策略"
                value={longRunPolicy.enabled
                  ? `启用 / ${longRunPolicy.history_days || '-'} 轮历史`
                  : (formalExperimentConfig.ready_for_formal_run ? '正式 40 轮' : '-')}
              />
              {externalEnvironmentPolicy.enabled && (
                <InfoRow
                  label="外部扰动"
                  value={(externalEnvironmentPolicy.events || [])
                    .map((event) => `Turn ${event.turn}: ${event.label}`)
                    .join(' / ')}
                />
              )}
              <InfoRow
                label="目标函数"
                value={profitObjectivePolicy.enabled
                  ? formatObjectiveWeights(profitObjectivePolicy.objective_weights)
                  : '-'}
              />
            </div>
          </section>

          <section>
            <h4>固定运行配置</h4>
            <div className="experiment-preset-switch">
              {Object.values(CONTROL_PRESETS)
                .filter((preset) => !evolutionScenario || preset.id === 'agent')
                .map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  className={controlPreset === preset.id ? 'active' : ''}
                  onClick={() => handlePresetChange(preset.id)}
                  disabled={disabled}
                >
                  <strong>{preset.label}</strong>
                  <span>{preset.description}</span>
                </button>
              ))}
            </div>
            {agentRunLocked && (
              <p className="experiment-ops-note warning">
                当前已有 Agent Skill 任务 {formatShortRunId(activeAgentJob.job_id)} 处于
                {STATUS_LABELS[activeAgentJob.status] || activeAgentJob.status} 状态。Agent Skill
                样例同一时间仅允许执行一个；切换为“固定规则脚本”可并发运行。
              </p>
            )}
            <p className="experiment-ops-note">
              当前展示的是已有配置快照。点击“修改配置”后只会临时编辑本次启动参数，关闭弹窗后不会写回配置中心。
            </p>
          </section>

          {scenarioVariants.length > 1 && (
            <section>
              <h4>实验配置选择</h4>
              <div className="experiment-ops-config-grid">
                <label className="experiment-config-wide-field">
                  <span>场景变种 / 对照组</span>
                  <select
                    value={getScenarioKey(selectedScenario)}
                    onChange={(event) => onVariantChange(event.target.value)}
                    disabled={disabled}
                  >
                    {scenarioVariants.map((variant) => (
                      <option key={getScenarioKey(variant)} value={getScenarioKey(variant)}>
                        {getExperimentGroupLabel(variant)} · {getFormalExperimentRoleLabel(variant)} · {getScenarioLabel(variant)} · {getScenarioKey(variant)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </section>
          )}

          <section>
            <h4>运行节奏与并发</h4>
            <div className="experiment-ops-config-grid">
              <ConfigField
                label="需求/市场模式"
                value={localForm.marketDemandMode}
                onChange={(value) => handleFieldChange('marketDemandMode', value)}
                disabled
              />
              <ConfigField
                label="Agent 轮次"
                type="number"
                min="1"
                value={localForm.agentRunSteps}
                onChange={(value) => handleFieldChange('agentRunSteps', value)}
                disabled={fieldDisabled || evolutionScenario}
              />
              <ConfigField
                label="环境总轮次"
                type="number"
                min="1"
                value={localForm.serviceTotalSteps}
                onChange={(value) => handleFieldChange('serviceTotalSteps', value)}
                disabled={fieldDisabled || evolutionScenario}
              />
              <ConfigField
                label="企业并发"
                type="number"
                min="1"
                value={localForm.maxEnterpriseConcurrency}
                onChange={(value) => handleFieldChange('maxEnterpriseConcurrency', value)}
                disabled={fieldDisabled}
              />
              <ConfigField
                label="部门并发"
                type="number"
                min="1"
                value={localForm.maxDepartmentConcurrency}
                onChange={(value) => handleFieldChange('maxDepartmentConcurrency', value)}
                disabled={fieldDisabled}
              />
            </div>
          </section>

          <section>
            <h4>Auto 部门规则</h4>
            <div className="experiment-ops-config-grid">
              <ConfigField
                label="HR 招聘阈值"
                type="number"
                step="0.01"
                value={localForm.hrRecruitThreshold}
                onChange={(value) => handleFieldChange('hrRecruitThreshold', value)}
                disabled={fieldDisabled}
              />
              <ConfigField
                label="HR 招聘比例"
                type="number"
                step="0.01"
                value={localForm.hrRecruitRatio}
                onChange={(value) => handleFieldChange('hrRecruitRatio', value)}
                disabled={fieldDisabled}
              />
              <ConfigField
                label="库存扩仓阈值"
                type="number"
                step="0.01"
                value={localForm.inventoryExpandThreshold}
                onChange={(value) => handleFieldChange('inventoryExpandThreshold', value)}
                disabled={fieldDisabled}
              />
              <ConfigField
                label="库存扩仓比例"
                type="number"
                step="0.01"
                value={localForm.inventoryExpandRatio}
                onChange={(value) => handleFieldChange('inventoryExpandRatio', value)}
                disabled={fieldDisabled}
              />
            </div>
          </section>

          <section>
            <h4>结算与规则脚本</h4>
            <div className="experiment-ops-config-grid">
              <ConfigField
                label="工资周期"
                type="number"
                min="1"
                value={localForm.salaryInterval}
                onChange={(value) => handleFieldChange('salaryInterval', value)}
                disabled={fieldDisabled}
              />
              <label>
                <span>库存成本逐轮结算</span>
                <select
                  value={localForm.inventoryCostDaily}
                  onChange={(event) => handleFieldChange('inventoryCostDaily', event.target.value)}
                  disabled={fieldDisabled || evolutionScenario}
                >
                  <option value="true">开启</option>
                  <option value="false">关闭</option>
                </select>
              </label>
              <label>
                <span>Scripted Rule</span>
                <select
                  value={localForm.scriptedEnabled}
                  onChange={(event) => handleFieldChange('scriptedEnabled', event.target.value)}
                  disabled={fieldDisabled || evolutionScenario}
                >
                  <option value="true">开启</option>
                  <option value="false">关闭</option>
                </select>
              </label>
              <ConfigField
                label="规则模式"
                value={localForm.scriptedMode}
                onChange={(value) => handleFieldChange('scriptedMode', value)}
                disabled={fieldDisabled || evolutionScenario}
              />
            </div>
          </section>

          <section>
            <h4>生产脚本参数</h4>
            <div className="experiment-ops-config-grid">
              <ConfigField
                label="基础产量"
                type="number"
                value={localForm.productionBaseQuantity}
                onChange={(value) => handleFieldChange('productionBaseQuantity', value)}
                disabled={fieldDisabled}
              />
              <ConfigField
                label="波动幅度"
                type="number"
                step="0.01"
                value={localForm.productionOscillationAmplitude}
                onChange={(value) => handleFieldChange('productionOscillationAmplitude', value)}
                disabled={fieldDisabled}
              />
              <ConfigField
                label="增长率"
                type="number"
                step="0.01"
                value={localForm.productionGrowthRate}
                onChange={(value) => handleFieldChange('productionGrowthRate', value)}
                disabled={fieldDisabled}
              />
              <ConfigField
                label="同业信号敏感度"
                type="number"
                step="0.01"
                value={localForm.productionPeerSignalSensitivity}
                onChange={(value) => handleFieldChange('productionPeerSignalSensitivity', value)}
                disabled={fieldDisabled}
              />
            </div>
          </section>

          {isSingle && (
            <section>
              <h4>单企业 Case 交接</h4>
              <div className="experiment-ops-config-grid">
                <ConfigField
                  label="预热轮次"
                  type="number"
                  min="0"
                  value={localForm.singlePrewarmRounds}
                  onChange={(value) => handleFieldChange('singlePrewarmRounds', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="交接轮次"
                  type="number"
                  min="0"
                  value={localForm.singleHandoffDay}
                  onChange={(value) => handleFieldChange('singleHandoffDay', value)}
                  disabled={fieldDisabled}
                />
              </div>
            </section>
          )}

          {isSingle && (
            <section>
              <h4>单企业 Case 关键影响要素</h4>
              <div className="experiment-ops-config-grid">
                <ConfigField
                  label="每轮接单上限"
                  type="number"
                  min="0"
                  value={localForm.singleAcceptOrdersPerRound}
                  onChange={(value) => handleFieldChange('singleAcceptOrdersPerRound', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="市场开发轮次"
                  placeholder="例：0,3"
                  value={localForm.singleMarketDevelopmentRounds}
                  onChange={(value) => handleFieldChange('singleMarketDevelopmentRounds', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="市场开发人数"
                  type="number"
                  min="0"
                  value={localForm.singleMarketDevelopmentWorkers}
                  onChange={(value) => handleFieldChange('singleMarketDevelopmentWorkers', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="生产间隔轮次"
                  type="number"
                  min="1"
                  value={localForm.singleProductionRoundInterval}
                  onChange={(value) => handleFieldChange('singleProductionRoundInterval', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="目标生产量"
                  type="number"
                  min="0"
                  value={localForm.singleProductionQuantity}
                  onChange={(value) => handleFieldChange('singleProductionQuantity', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="每轮产能上限"
                  type="number"
                  min="0"
                  value={localForm.singleProductionDailyCapacity}
                  onChange={(value) => handleFieldChange('singleProductionDailyCapacity', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="建线轮次"
                  placeholder="例：0,2"
                  value={localForm.singleBuildLineRounds}
                  onChange={(value) => handleFieldChange('singleBuildLineRounds', value)}
                  disabled={fieldDisabled}
                />
                <label>
                  <span>建线类型</span>
                  <select
                    value={localForm.singleBuildLineType}
                    onChange={(event) => handleFieldChange('singleBuildLineType', event.target.value)}
                    disabled={fieldDisabled}
                  >
                    <option value="small">small</option>
                    <option value="medium">medium</option>
                    <option value="large">large</option>
                  </select>
                </label>
                <label>
                  <span>采购策略</span>
                  <select
                    value={localForm.singleProcurementStrategy}
                    onChange={(event) => handleFieldChange('singleProcurementStrategy', event.target.value)}
                    disabled={fieldDisabled}
                  >
                    <option value="pass">pass</option>
                    <option value="emergency_gap_fill">emergency_gap_fill</option>
                    <option value="quiet_support">quiet_support</option>
                  </select>
                </label>
                <ConfigField
                  label="原料覆盖目标"
                  type="number"
                  min="0"
                  value={localForm.singleMaterialCoverageTargetQuantity}
                  onChange={(value) => handleFieldChange('singleMaterialCoverageTargetQuantity', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="补货倍率"
                  type="number"
                  step="0.01"
                  min="0"
                  value={localForm.singleMaterialOrderMultiplier}
                  onChange={(value) => handleFieldChange('singleMaterialOrderMultiplier', value)}
                  disabled={fieldDisabled}
                />
                <label>
                  <span>物流方式</span>
                  <select
                    value={localForm.singlePreferredLogisticsMode}
                    onChange={(event) => handleFieldChange('singlePreferredLogisticsMode', event.target.value)}
                    disabled={fieldDisabled}
                  >
                    <option value="dynamic">dynamic</option>
                    <option value="road">road</option>
                    <option value="rail">rail</option>
                    <option value="air">air</option>
                  </select>
                </label>
                <ConfigField
                  label="招聘轮次"
                  placeholder="例：0,2"
                  value={localForm.singleHrRecruitRounds}
                  onChange={(value) => handleFieldChange('singleHrRecruitRounds', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="招聘部门"
                  value={localForm.singleHrTargetDepartment}
                  onChange={(value) => handleFieldChange('singleHrTargetDepartment', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="招聘人数"
                  type="number"
                  min="0"
                  value={localForm.singleHrRecruitPeople}
                  onChange={(value) => handleFieldChange('singleHrRecruitPeople', value)}
                  disabled={fieldDisabled}
                />
                <ConfigField
                  label="现金保护阈值"
                  type="number"
                  min="0"
                  value={localForm.singleCashGuardThreshold}
                  onChange={(value) => handleFieldChange('singleCashGuardThreshold', value)}
                  disabled={fieldDisabled}
                />
                <label>
                  <span>禁止资本开支</span>
                  <select
                    value={localForm.singleAvoidCapexActions}
                    onChange={(event) => handleFieldChange('singleAvoidCapexActions', event.target.value)}
                    disabled={fieldDisabled}
                  >
                    <option value="true">开启</option>
                    <option value="false">关闭</option>
                  </select>
                </label>
              </div>
            </section>
          )}
        </div>

        <footer className="experiment-config-modal-actions">
          <button type="button" className="experiment-ops-secondary-action ghost" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="experiment-ops-secondary-action ghost"
            disabled={disabled}
            onClick={handleEditToggle}
          >
            {isEditing ? '查看只读配置' : '修改配置'}
          </button>
          <button
            type="button"
            className="experiment-ops-primary-action"
            disabled={runDisabled}
            onClick={() => onRun({ form: localForm, preset: controlPreset })}
          >
            直接运行
          </button>
        </footer>
      </div>
    </div>
  );
};

const RunDetailModal = ({
  scenario,
  jobs = [],
  runs = [],
  submittingAction = '',
  onDeleteJob,
  onStopJob,
  onResumeJob,
  onResumeArtifact,
  onRefreshJobs,
  onClose,
}) => {
  const [expandedJobIds, setExpandedJobIds] = useState(new Set());
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const [jobSummaries, setJobSummaries] = useState({});
  const [summaryLoadingIds, setSummaryLoadingIds] = useState(new Set());
  const [summaryErrors, setSummaryErrors] = useState({});

  const expandedJobIdList = useMemo(
    () => Array.from(expandedJobIds),
    [expandedJobIds]
  );

  const loadJobSummary = async (jobId) => {
    if (!jobId) {
      return;
    }
    setSummaryLoadingIds((previous) => new Set(previous).add(jobId));
    const result = await getOperationsJobSummary(jobId);
    if (result.available && result.summary) {
      setJobSummaries((previous) => ({
        ...previous,
        [jobId]: result.summary,
      }));
      setSummaryErrors((previous) => {
        const next = { ...previous };
        delete next[jobId];
        return next;
      });
    } else {
      setSummaryErrors((previous) => ({
        ...previous,
        [jobId]: result.error || '无法读取运行摘要',
      }));
    }
    setSummaryLoadingIds((previous) => {
      const next = new Set(previous);
      next.delete(jobId);
      return next;
    });
  };

  const toggleJobDetails = (jobId) => {
    setExpandedJobIds((previous) => {
      const next = new Set(previous);
      if (next.has(jobId)) {
        next.delete(jobId);
      } else {
        next.add(jobId);
        loadJobSummary(jobId);
      }
      return next;
    });
  };

  useEffect(() => {
    if (expandedJobIdList.length === 0) {
      return undefined;
    }
    const refresh = () => {
      onRefreshJobs?.();
      expandedJobIdList.forEach((jobId) => loadJobSummary(jobId));
    };
    refresh();
    const timer = window.setInterval(refresh, 3500);
    return () => window.clearInterval(timer);
  }, [expandedJobIdList.join('|')]);

  const confirmDeleteJob = async () => {
    if (!deleteCandidate) {
      return;
    }
    const target = deleteCandidate;
    setDeleteCandidate(null);
    await onDeleteJob?.(target);
  };

  return (
    <div className="experiment-config-modal-backdrop" role="presentation">
      <div className="experiment-config-modal run-detail-modal" role="dialog" aria-modal="true" aria-label="运行详情">
        <header className="experiment-config-modal-header">
          <div>
            <span>运行详情</span>
            <strong>{getScenarioLabel(scenario)}</strong>
          </div>
          <button type="button" className="experiment-config-close" onClick={onClose}>
            关闭
          </button>
        </header>

        <div className="experiment-config-modal-body">
          <section>
            <h4>任务记录</h4>
            {jobs.length > 0 ? (
              <div className="run-detail-list">
                {jobs.map((job) => {
                  const jobError = getJobErrorText(job);
                  const jobNotice = getJobNoticeText(job);
                  const isExpanded = expandedJobIds.has(job.job_id);
                  const status = normalizeJobStatus(job.status);
                  const canStop = STOPPABLE_STATUSES.has(status);
                  const isStopRequested = status === 'stop_requested';
                  const canResume = (
                    job.scenario_id === 'long_horizon_evolution'
                    && ['stopped', 'failed'].includes(status)
                    && Number(job.completed_steps || 0) > 0
                    && Number(job.completed_steps || 0) < Math.max(Number(job.planned_total_steps || 0), 200)
                  );
                  return (
                    <div
                      key={job.job_id}
                      className={`run-detail-row ${status} ${jobError ? 'has-error' : ''}`}
                    >
                      <strong className={`experiment-ops-status ${status}`}>
                        {STATUS_LABELS[job.status] || formatValue(job.status)}
                      </strong>
                      <span>{formatValue(job.scenario_id)}</span>
                      <small>{formatTime(job.updated_at || job.created_at)}</small>
                      <code>{formatValue(job.job_id)}</code>
                      <div className="run-detail-actions">
                        {(canStop || isStopRequested) && (
                          <button
                            type="button"
                            className="experiment-ops-warning-action"
                            disabled={isStopRequested || submittingAction === `stop-${job.job_id}`}
                            onClick={() => onStopJob?.(job)}
                            title={isStopRequested ? '中止请求已提交，等待轮次封口' : '请求中止当前模拟'}
                          >
                            {isStopRequested ? '正在停止' : '中止模拟'}
                          </button>
                        )}
                        {canResume && (
                          <button
                            type="button"
                            className="experiment-ops-primary-action"
                            disabled={submittingAction === `resume-${job.job_id}`}
                            onClick={() => onResumeJob?.(job)}
                            title={`从 Turn ${Number(job.last_complete_round ?? job.completed_steps - 1) + 1} 继续到 Turn 199`}
                          >
                            {submittingAction === `resume-${job.job_id}` ? '准备恢复' : '继续运行'}
                          </button>
                        )}
                        <button
                          type="button"
                          className="experiment-ops-secondary-action ghost"
                          onClick={() => toggleJobDetails(job.job_id)}
                        >
                          {isExpanded ? '收起详情' : '查看详情'}
                        </button>
                        <button
                          type="button"
                          className="experiment-ops-danger-action"
                          disabled={submittingAction === `delete-${job.job_id}`}
                          onClick={() => setDeleteCandidate(job)}
                          title="强制终止并删除任务记录"
                        >
                          删除记录
                        </button>
                      </div>
                      {jobError && (
                        <p className="run-detail-error">
                          {jobError}
                        </p>
                      )}
                      {!jobError && jobNotice && (
                        <p className="run-detail-notice">
                          {jobNotice}
                        </p>
                      )}
                      {isExpanded && (
                        <JobRoundSummary
                          summary={jobSummaries[job.job_id]}
                          loading={summaryLoadingIds.has(job.job_id)}
                          error={summaryErrors[job.job_id]}
                          fallbackJob={job}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="experiment-ops-empty">
                <strong>暂无任务记录</strong>
              </div>
            )}
          </section>

          <section>
            <h4>运行结果</h4>
            {runs.length > 0 ? (
              <div className="run-detail-list">
                {runs.map((run) => {
                  const runStatus = normalizeJobStatus(run.meta?.status);
                  const alreadyRegistered = jobs.some((job) => (
                    job.job_id === run.meta?.job_id
                    || (job.run_id && job.run_id === run.meta?.run_id)
                  ));
                  const canResumeArtifact = (
                    run.source === 'workspace_jobs'
                    && getScenarioId(run.meta) === 'long_horizon_evolution'
                    && ['stopped', 'failed'].includes(runStatus)
                    && Number(run.max_day) >= 0
                    && Number(run.max_day) < 199
                    && !alreadyRegistered
                  );
                  return (
                    <div key={run.id} className="run-detail-row">
                      <strong>{getScenarioId(run.meta)}</strong>
                      <span>{run.sourceLabel || run.id}</span>
                      <small>{formatTime(run.meta?.finished_at || run.meta?.archived_at || run.meta?.started_at)}</small>
                      <code>{formatValue(run.meta?.status)}</code>
                      {canResumeArtifact && (
                        <button
                          type="button"
                          className="experiment-ops-primary-action"
                          disabled={submittingAction === `resume-artifact-${run.id}`}
                          onClick={() => onResumeArtifact?.(run)}
                          title={`导入归档并从 Turn ${Number(run.max_day) + 1} 继续`}
                        >
                          {submittingAction === `resume-artifact-${run.id}` ? '正在导入' : '导入并继续'}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="experiment-ops-empty">
                <strong>暂无运行结果</strong>
              </div>
            )}
          </section>
        </div>
      </div>
      {deleteCandidate && (
        <ConfirmModal
          title="确认删除任务记录"
          message={`将强制终止并删除任务记录 ${deleteCandidate.job_id}。运行归档结果不会被删除。`}
          detail={TERMINAL_STATUSES.has(normalizeJobStatus(deleteCandidate.status))
            ? '该任务已结束，将直接删除 operations 记录。'
            : '该任务尚未结束，将先尝试终止关联进程，再删除 operations 记录。'}
          confirmLabel="强制删除"
          cancelLabel="取消"
          danger
          onCancel={() => setDeleteCandidate(null)}
          onConfirm={confirmDeleteJob}
        />
      )}
    </div>
  );
};

const JobRoundSummary = ({ summary, loading = false, error = '', fallbackJob }) => {
  const completedSteps = summary?.completed_steps ?? fallbackJob?.completed_steps ?? 0;
  const plannedTotalSteps = summary?.planned_total_steps ?? fallbackJob?.planned_total_steps ?? '-';
  const enterprises = Array.isArray(summary?.enterprises) ? summary.enterprises : [];
  const isCompleted = normalizeJobStatus(summary?.status || fallbackJob?.status) === 'completed';
  return (
    <div className="job-round-summary">
      <div className="job-round-summary-head">
        <div>
          <span>运行进度</span>
          <strong>{formatValue(completedSteps)} / {formatValue(plannedTotalSteps)} 轮</strong>
        </div>
        <div>
          <span>当前可观察轮次</span>
          <strong>{summary?.current_round_label || '尚未完成首轮'}</strong>
        </div>
        <div>
          <span>企业资金总数</span>
          <strong>{formatMoney(summary?.total_cash)}</strong>
        </div>
      </div>

      {loading && <p className="job-round-summary-muted">正在刷新运行摘要...</p>}
      {error && <p className="run-detail-error">{error}</p>}
      {!loading && !error && summary?.message && (
        <p className="job-round-summary-muted">{summary.message}</p>
      )}

      {isCompleted ? null : enterprises.length > 0 ? (
        <div className="job-enterprise-summary-list">
          {enterprises.map((enterprise) => (
            <section key={enterprise.enterprise_id} className="job-enterprise-summary">
              <header>
                <strong>{enterprise.enterprise_id}</strong>
                <span>资金 {formatMoney(enterprise.cash)}</span>
              </header>
              {enterprise.departments?.length > 0 ? (
                <div className="job-department-action-list">
                  {enterprise.departments.map((department) => (
                    <div key={`${enterprise.enterprise_id}-${department.department}`} className="job-department-action-row">
                      <div className="job-department-action-head">
                        <strong>{department.department_label || department.department}</strong>
                        <span className={`job-action-status ${department.success === false ? 'failed' : department.success === true ? 'success' : 'pending'}`}>
                          {department.success === false ? '失败' : department.success === true ? '成功' : '待确认'}
                        </span>
                      </div>
                      <div className="job-action-chips">
                        {(department.actions || []).slice(0, 4).map((action, index) => (
                          <span key={`${action.action_name}-${index}`}>
                            {getActionDisplayName(action.action_name)}
                            {action.detail ? ` · ${action.detail}` : ''}
                          </span>
                        ))}
                      </div>
                      {(department.actions || [])[0]?.reason && (
                        <small>{department.actions[0].reason}</small>
                      )}
                      {department.message && (
                        <small>{department.message}</small>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="job-round-summary-muted">当前轮次未读取到部门动作。</p>
              )}
            </section>
          ))}
        </div>
      ) : (
        !loading && !error && (
          <p className="job-round-summary-muted">暂无可展示的企业部门动作。</p>
        )
      )}
    </div>
  );
};

const ConfirmModal = ({
  title,
  message,
  detail,
  confirmLabel = '确认',
  cancelLabel = '取消',
  danger = false,
  onConfirm,
  onCancel,
}) => (
  <div className="experiment-confirm-backdrop" role="presentation">
    <div className="experiment-confirm-modal" role="dialog" aria-modal="true" aria-label={title}>
      <strong>{title}</strong>
      <p>{message}</p>
      {detail && <small>{detail}</small>}
      <div className="experiment-confirm-actions">
        <button
          type="button"
          className="experiment-ops-secondary-action ghost"
          onClick={onCancel}
        >
          {cancelLabel}
        </button>
        <button
          type="button"
          className={danger ? 'experiment-ops-danger-action' : 'experiment-ops-primary-action'}
          onClick={onConfirm}
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  </div>
);

const ConfigField = ({
  label,
  value,
  onChange,
  disabled,
  type = 'text',
  min,
  step,
  ...inputProps
}) => (
  <label>
    <span>{label}</span>
    <input
      type={type}
      min={min}
      step={step}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      {...inputProps}
    />
  </label>
);

export default ExperimentOperationsView;
