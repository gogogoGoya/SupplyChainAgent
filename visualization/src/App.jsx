import React, { useState, useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts';
import CompanySelector from './components/CompanySelector';
import DaySelector from './components/DaySelector';
import CompanyInfo from './components/CompanyInfo';
import ExchangeInfo from './components/ExchangeInfo';
import CEOAnalysis from './components/CEOAnalysis';
import ExchangeEnterprisePanel from './components/ExchangeEnterprisePanel';
import RunSummary from './components/RunSummary';
import FlowProductionView from './components/FlowProductionView';
import GlobalSimulationView from './components/GlobalSimulationView';
import BullwhipEffectView from './components/BullwhipEffectView';
import CobwebModelValidationView from './components/CobwebModelValidationView';
import CommonsTragedyView from './components/CommonsTragedyView';
import HerdingEffectView from './components/HerdingEffectView';
import EvolutionExperimentView from './components/EvolutionExperimentView';
import OperationalReviewView from './components/OperationalReviewView';
import ExperimentOperationsView from './components/ExperimentOperationsView';
import DemandPropagationView from './components/DemandPropagationView';
import SingleEnterprisePerformanceView from './components/SingleEnterprisePerformanceView';
import SingleEnterpriseActionList from './components/SingleEnterpriseActionList';
import { LATEST_RUN_ID, buildDataUrl, resolveDataRoot, resolveWorkspaceJobRoot, safeFetchJson } from './utils/dataSource';
import { listArtifactRuns, listOperationsJobs } from './utils/operationsApi';
import { buildQuantityView } from './utils/productEquivalent';

const formatNumber = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(numeric);
};

const formatCurrency = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  return `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(numeric)}`;
};

const getRunTimeSortValue = (meta) => (
  meta?.finished_at
  || meta?.archived_at
  || meta?.started_at
  || ''
);

const formatDisplayTime = (value) => {
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

const indexActionsByExecutor = (actions = []) => {
  return actions.reduce((acc, action) => {
    const executorId = action?.executor_id;
    if (!executorId) {
      return acc;
    }
    if (!acc[executorId]) {
      acc[executorId] = [];
    }
    acc[executorId].push(action);
    return acc;
  }, {});
};

const getEnterpriseSpecsFromMeta = (runMeta) => (
  runMeta?.scenario_config?.enterprise_specs
  || runMeta?.scenario_config?.enterprise_configs
  || []
);

const SCENARIO_ANALYSIS_PAGES = [
  { id: 'evolution', label: '持续演变', description: '长期经营与外部扰动响应' },
  { id: 'bullwhip', label: '牛鞭效应', description: '订单波动沿供应链放大' },
  { id: 'cobweb', label: '蛛网模型', description: '价格与滞后供给反馈' },
  { id: 'commons', label: '公地悲剧', description: '共享资源过度使用' },
  { id: 'herding', label: '羊群效应', description: '同业信号与同步扩产' },
];

const RUN_CATEGORY_CONFIGS = [
  ...SCENARIO_ANALYSIS_PAGES,
  { id: 'architecture', label: '基础结构验证', description: '链状、分支、网状产业链结构验证' },
  { id: 'other', label: '其它模拟', description: '未绑定专项场景分析页' },
];

const ANALYSIS_SCOPE_CONFIGS = [
  { id: 'multi', label: '多企业供应链模拟', description: '产业链结构、企业协同与经济效应复盘' },
  { id: 'single', label: '单企业性能模拟', description: '单企业标准 case、部门动作与能力测试复盘' },
];

const MULTI_ANALYSIS_PAGES = [
  { id: 'daily', label: '轮次观察' },
  { id: 'propagation', label: '链路复盘' },
  { id: 'global', label: '全局复盘' },
  { id: 'scenario', label: '场景分析' },
  { id: 'operations', label: '运营复盘' },
];

const SINGLE_ANALYSIS_PAGES = [
  { id: 'daily', label: '轮次观察' },
];

const SINGLE_CASE_FILTER_CONFIGS = [
  { id: 'all', label: '全部 Case' },
  { id: 'single_case_01_order_selection', label: 'Case 01 订单选择' },
  { id: 'single_case_02_material_shortage', label: 'Case 02 原料与供应商选择' },
  { id: 'single_case_03_capacity_bottleneck', label: 'Case 03 产能瓶颈' },
  { id: 'single_case_04_staff_shortage', label: 'Case 04 人员不足' },
  { id: 'single_case_05_cash_pressure', label: 'Case 05 现金压力' },
];

const MULTI_SCENARIO_FILTER_CONFIGS = [
  { id: 'all', label: '全部场景' },
  ...SCENARIO_ANALYSIS_PAGES,
];

const RUN_CONTROL_MODE_FILTER_CONFIGS = [
  { id: 'all', label: '全部模式' },
  { id: 'agent', label: 'Agent Skill' },
  { id: 'scripted', label: 'Scripted' },
];

const getScenarioIdFromMeta = (runMeta) => (
  runMeta?.scenario_id
  || runMeta?.scenario_meta?.scenario_id
  || runMeta?.scenario_config?.meta?.scenario_id
  || ''
);

const getMarketModeFromMeta = (runMeta) => (
  runMeta?.market_demand_mode
  || runMeta?.scenario_config?.simulation?.market_demand_mode
  || ''
);

const getSimulationProfileFromMeta = (runMeta) => {
  const scenarioId = String(getScenarioIdFromMeta(runMeta)).toLowerCase();
  return (
    runMeta?.integration_profiles?.simulation?.profile
    || runMeta?.scenario_config?.integration_profiles?.simulation?.profile
    || (scenarioId.startsWith('single_case_') ? 'single_enterprise' : 'multi_enterprise')
  );
};

const getAnalysisScopeFromMeta = (runMeta) => (
  getSimulationProfileFromMeta(runMeta) === 'single_enterprise' ? 'single' : 'multi'
);

const isMultiEnterpriseRun = (run) => (
  getAnalysisScopeFromMeta(run?.meta) === 'multi'
);

const pickPreferredRun = (
  runs = [],
  {
    candidateRunId = '',
    keepCandidate = true,
    preferredScope = 'multi',
  } = {}
) => {
  if (keepCandidate && candidateRunId) {
    const candidate = runs.find((run) => run.id === candidateRunId);
    const candidateScopeMatches = (
      !preferredScope
      || preferredScope === 'any'
      || (
        preferredScope === 'multi'
          ? isMultiEnterpriseRun(candidate)
          : getAnalysisScopeFromMeta(candidate?.meta) === preferredScope
      )
    );
    if (candidate && candidateScopeMatches) {
      return candidate;
    }
  }
  const scopedRun = runs.find((run) => (
    preferredScope === 'multi'
      ? isMultiEnterpriseRun(run)
      : getAnalysisScopeFromMeta(run?.meta) === preferredScope
  ));
  return scopedRun || runs[0] || null;
};

const getSingleCaseIdFromMeta = (runMeta) => {
  const scenarioId = String(getScenarioIdFromMeta(runMeta)).toLowerCase();
  if (!scenarioId.startsWith('single_case_')) {
    return '';
  }
  const baseId = scenarioId.replace(/_scripted$/, '');
  if (baseId === 'single_case_01_market_insufficient') {
    return 'single_case_01_order_selection';
  }
  return baseId;
};

const getRunControlModeFromMeta = (runMeta) => {
  const scenarioId = String(getScenarioIdFromMeta(runMeta)).toLowerCase();
  const scriptedPolicy = (
    runMeta?.scenario_config?.runtime_injection?.scripted_rule_policy
    || runMeta?.runtime_injection?.scripted_rule_policy
    || {}
  );
  const operationsJob = runMeta?.operations_job || runMeta?.job || {};
  const executionMode = String(
    runMeta?.execution_mode
    || operationsJob?.execution_mode
    || operationsJob?.process_execution_mode
    || ''
  ).toLowerCase();
  const tags = [
    ...(Array.isArray(runMeta?.tags) ? runMeta.tags : []),
    ...(Array.isArray(operationsJob?.tags) ? operationsJob.tags : []),
  ].map((tag) => String(tag).toLowerCase());
  if (
    scenarioId.endsWith('_scripted')
    || scriptedPolicy.enabled === true
    || executionMode.includes('scripted')
    || tags.includes('preset:scripted')
  ) {
    return 'scripted';
  }
  return 'agent';
};

const getRunControlModeLabel = (runMeta) => (
  getRunControlModeFromMeta(runMeta) === 'scripted' ? 'Scripted' : 'Agent Skill'
);

const detectScenarioPage = (runMeta) => {
  if (getAnalysisScopeFromMeta(runMeta) !== 'multi') {
    return null;
  }
  const scenarioId = String(getScenarioIdFromMeta(runMeta)).toLowerCase();
  const marketMode = String(getMarketModeFromMeta(runMeta)).toLowerCase();
  const experimentFamily = String(
    runMeta?.scenario_meta?.experiment_family
    || runMeta?.scenario_config?.meta?.experiment_family
    || ''
  ).toLowerCase();
  if (
    experimentFamily === 'long_horizon_evolution'
    || scenarioId === 'long_horizon_evolution'
  ) {
    return 'evolution';
  }
  if (
    experimentFamily === 'architecture_complexity_validation'
    || scenarioId.startsWith('architecture_')
    || runMeta?.scenario_config?.simulation?.architecture_validation_config?.enabled === true
  ) {
    return null;
  }
  if (marketMode === 'cobweb' || scenarioId.includes('cobweb')) {
    return 'cobweb';
  }
  if (marketMode === 'shared_resource_market' || scenarioId.includes('commons')) {
    return 'commons';
  }
  if (marketMode === 'herding_market' || scenarioId.includes('herding')) {
    return 'herding';
  }
  return 'bullwhip';
};

const getScenarioPageConfig = (pageId) => (
  SCENARIO_ANALYSIS_PAGES.find((page) => page.id === pageId) || SCENARIO_ANALYSIS_PAGES[0]
);

const detectRunCategory = (runMeta) => {
  const scenarioPage = detectScenarioPage(runMeta);
  if (scenarioPage) {
    return scenarioPage;
  }
  const scenarioId = String(getScenarioIdFromMeta(runMeta)).toLowerCase();
  const experimentFamily = String(
    runMeta?.scenario_meta?.experiment_family
    || runMeta?.scenario_config?.meta?.experiment_family
    || ''
  ).toLowerCase();
  if (
    experimentFamily === 'architecture_complexity_validation'
    || scenarioId.startsWith('architecture_')
    || runMeta?.scenario_config?.simulation?.architecture_validation_config?.enabled === true
  ) {
    return 'architecture';
  }
  return 'other';
};

const getRunCategoryConfig = (categoryId) => (
  RUN_CATEGORY_CONFIGS.find((category) => category.id === categoryId) || RUN_CATEGORY_CONFIGS[RUN_CATEGORY_CONFIGS.length - 1]
);

const getScenarioCategoryLabel = (runMeta) => getRunCategoryConfig(detectRunCategory(runMeta)).label;

const hasScenarioAnalysisPage = (runMeta) => Boolean(detectScenarioPage(runMeta));

const extractRunExperimentTag = (value) => {
  const name = String(value || '').split('/').filter(Boolean).pop() || '';
  if (!name) {
    return '';
  }
  const workspaceJobMatch = name.match(
    /^run_[A-Za-z0-9]+__started_\d{4}-\d{2}-\d{2}T\d{2}_\d{2}_\d{2}_(.+)$/
  );
  if (workspaceJobMatch?.[1]) {
    return workspaceJobMatch[1];
  }
  const legacyMatch = name.match(/^run_\d{4}-\d{2}-\d{2}_\d{6}_(.+)$/);
  return legacyMatch?.[1] || '';
};

const getRunExperimentTag = (...values) => {
  for (const value of values) {
    const tag = extractRunExperimentTag(value);
    if (tag) {
      return tag;
    }
  }
  return '';
};

const formatExperimentTag = (tag) => String(tag || '').replace(/_/g, ' ');

const formatRunTimeShort = (run) => {
  const metaTime = run?.meta?.finished_at || run?.meta?.archived_at || run?.meta?.started_at || '';
  if (metaTime) {
    return formatDisplayTime(metaTime);
  }
  const match = String(run?.id || '').match(/^run_(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (!match) {
    return run?.id || '-';
  }
  return `${match[1]} ${match[2]}:${match[3]}:${match[4]}`;
};

const formatScenarioRunOptionLabel = (run) => {
  const scenarioId = getScenarioIdFromMeta(run?.meta) || 'unknown_scenario';
  const tag = run?.experimentTag ? formatExperimentTag(run.experimentTag) : '';
  const marker = run?.experimentTag ? '★ ' : '';
  return `${marker}${formatRunTimeShort(run)} · ${getRunControlModeLabel(run?.meta)} · ${tag || scenarioId}`;
};

const getRunRecordTimeValue = (run) => (
  run?.meta?.finished_at
  || run?.meta?.archived_at
  || run?.meta?.started_at
  || ''
);

const getRunRecordDateValue = (run) => {
  const value = getRunRecordTimeValue(run);
  if (!value) {
    return '';
  }
  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toISOString().slice(0, 10);
  }
  return String(value).slice(0, 10);
};

const getRunRecordLastRound = (run) => {
  const meta = run?.meta || {};
  const completed = Number(meta.completed_steps || meta.total_steps || meta.planned_total_steps || 0);
  return Number.isFinite(completed) && completed > 0 ? completed - 1 : 0;
};

const getRunRecordStorageLabel = (run) => (
  run?.dataRoot || run?.meta?.artifact_root || run?.sourceLabel || '-'
);

const buildRunRecordFileLinks = (run) => {
  const root = run?.dataRoot || '';
  const lastRound = getRunRecordLastRound(run);
  if (!root) {
    return [];
  }
  const fileSpecs = [
    ['run_meta', 'run_meta.json'],
    ['末轮交易', `public/exchange/day${lastRound}/exchange.json`],
    ['轮次完整性', `round_integrity/day${lastRound}.json`],
    ['运行指标', `projections/run_metrics/day${lastRound}/run_metrics_projection.json`],
    ['订单链路', `projections/multi_enterprise/day${lastRound}/order_lifecycle_projection.json`],
  ];
  return fileSpecs.map(([label, relativePath]) => ({
    label,
    relativePath,
    url: buildDataUrl(root, relativePath),
  }));
};

const buildRunArchiveUrl = (run) => {
  const dataRoot = String(run?.dataRoot || '');
  if (dataRoot === '/workspace_multi') {
    return '/operations/artifacts/archive?source=workspace_multi';
  }
  const workspacePrefix = '/workspace_jobs/';
  if (dataRoot.startsWith(workspacePrefix)) {
    return `/operations/artifacts/archive?source=workspace_jobs&name=${encodeURIComponent(decodeURIComponent(dataRoot.slice(workspacePrefix.length)))}`;
  }
  const simulationRunsPrefix = '/simulation_runs/';
  if (dataRoot.startsWith(simulationRunsPrefix)) {
    return `/operations/artifacts/archive?source=simulation_runs&name=${encodeURIComponent(decodeURIComponent(dataRoot.slice(simulationRunsPrefix.length)))}`;
  }
  const jobId = run?.meta?.job_id || run?.meta?.operations_job?.job_id || '';
  if (jobId) {
    return `/operations/jobs/${encodeURIComponent(jobId)}/archive`;
  }
  return '';
};

const sanitizeDownloadPart = (value) => (
  String(value || 'run-records').replace(/[^A-Za-z0-9_.=-]+/g, '_').replace(/^_+|_+$/g, '') || 'run-records'
);

const downloadJson = (filename, payload) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

const downloadUrl = (url) => {
  if (!url) {
    return;
  }
  const link = document.createElement('a');
  link.href = url;
  link.download = '';
  document.body.appendChild(link);
  link.click();
  link.remove();
};

const getWorkspaceNameFromArtifactRoot = (artifactRoot) => {
  const normalized = String(artifactRoot || '')
    .replace(/^file:\/\//, '')
    .replace(/\\/g, '/');
  if (!normalized) {
    return '';
  }
  const marker = '/workspace_jobs/';
  const markerIndex = normalized.lastIndexOf(marker);
  if (markerIndex >= 0) {
    return normalized.slice(markerIndex + marker.length).split('/').filter(Boolean)[0] || '';
  }
  return normalized.split('/').filter(Boolean).pop() || '';
};

const buildRunMetaFromOperationsJob = (job) => ({
  run_id: job?.run_id || job?.job_id || '',
  job_id: job?.job_id || '',
  scenario_id: job?.scenario_id || '',
  scenario_meta: job?.scenario_meta || job?.scenario_config?.meta || {},
  scenario_config: job?.scenario_config || {},
  integration_profiles: job?.integration_profiles || job?.scenario_config?.integration_profiles || {},
  status: job?.status || '',
  planned_total_steps: job?.planned_total_steps,
  completed_steps: job?.completed_steps,
  started_at: job?.started_at,
  finished_at: job?.finished_at,
  archived_at: job?.archived_at,
  artifact_root: job?.artifact_root,
  operations_job: job || {},
  tags: job?.tags || [],
});

const formatRunLabel = (runId, meta, isLatest = false, experimentTag = '') => {
  const scenarioId = meta?.scenario_id || 'unknown_scenario';
  const scenarioCategory = getScenarioCategoryLabel(meta);
  const controlMode = getRunControlModeLabel(meta);
  const finishedAt = meta?.finished_at || meta?.archived_at || meta?.started_at || '';
  const stepLabel = meta?.completed_steps || meta?.total_steps || meta?.planned_total_steps;
  const prefix = experimentTag ? `★ ${isLatest ? 'latest' : runId}` : (isLatest ? 'latest' : runId);
  const tagSuffix = experimentTag ? ` · 标注:${formatExperimentTag(experimentTag)}` : '';
  const timeSuffix = finishedAt ? ` · ${formatDisplayTime(finishedAt)}` : '';
  const stepsSuffix = stepLabel ? ` · ${stepLabel} steps` : '';
  return `${prefix} · [${scenarioCategory}] [${controlMode}] ${scenarioId}${tagSuffix}${stepsSuffix}${timeSuffix}`;
};

const finalizeRunCatalog = (runs = []) => {
  const seenRunKeys = new Set();
  return runs.filter((run) => {
    const baseRunKey = run?.meta?.run_id
      || run?.meta?.job_id
      || run?.resolvedRunId
      || run?.sourceLabel
      || run?.id
      || run?.dataRoot;
    const logicalRunKey = run?.experimentTag
      ? `${baseRunKey || ''}::${run?.sourceLabel || run?.id || run?.dataRoot || run?.experimentTag}`
      : baseRunKey;
    if (!logicalRunKey || seenRunKeys.has(logicalRunKey)) {
      return false;
    }
    seenRunKeys.add(logicalRunKey);
    return true;
  }).sort((left, right) => {
    const leftTime = getRunTimeSortValue(left.meta);
    const rightTime = getRunTimeSortValue(right.meta);
    return String(rightTime).localeCompare(String(leftTime)) || right.id.localeCompare(left.id);
  });
};

const buildRunEntriesFromArtifactIndex = (entries = []) => (
  entries.map((entry) => {
    const meta = {
      ...(entry?.meta || {}),
      _visualization_max_day: entry?.max_day,
    };
    const runId = meta.run_id || entry?.resolved_run_id || entry?.name || entry?.id || '';
    const sourceLabel = entry?.source_label || entry?.name || runId;
    const dataRoot = entry?.data_root || '';
    const experimentTag = getRunExperimentTag(sourceLabel, runId, dataRoot);
    const id = entry?.id || (
      entry?.source === 'workspace_jobs'
        ? `workspace_job:${sourceLabel}`
        : entry?.source === 'simulation_runs'
          ? sourceLabel
          : entry?.source === 'workspace_multi'
            ? 'workspace_current'
            : `${entry?.source || 'run'}:${sourceLabel}`
    );
    return {
      id,
      label: formatRunLabel(runId || id, meta, id === 'workspace_current', experimentTag),
      meta,
      dataRoot,
      sourceLabel,
      resolvedRunId: runId,
      experimentTag,
      maxDay: Number.isFinite(Number(entry?.max_day)) ? Number(entry.max_day) : undefined,
    };
  }).filter((run) => run.meta && run.dataRoot)
);

const getEnterpriseId = (spec) => spec?.enterprise_id || spec?.id || '';

const getTopologyEdgesFromSpecs = (enterpriseSpecs = []) => {
  const ids = new Set(enterpriseSpecs.map(getEnterpriseId).filter(Boolean));
  const edges = [];
  enterpriseSpecs.forEach((spec) => {
    const target = getEnterpriseId(spec);
    (spec?.supplier_name_list || []).forEach((source) => {
      if (ids.has(source) && target) {
        edges.push({ source, target });
      }
    });
  });
  if (edges.length > 0) {
    return edges;
  }
  return enterpriseSpecs.slice(0, -1).map((spec, index) => ({
    source: getEnterpriseId(spec),
    target: getEnterpriseId(enterpriseSpecs[index + 1]),
  })).filter((edge) => edge.source && edge.target);
};

const getExchangeEdgeMetrics = (exchangeData) => {
  const metrics = {};
  Object.values(exchangeData?.data?.exchanges || {}).forEach((exchange) => {
    (exchange?.orders?.list || []).forEach((order) => {
      const source = order?.seller_company_id;
      const target = order?.buyer_company_id;
      if (!source || !target) {
        return;
      }
      const key = `${source}->${target}`;
      const quantity = Number(order?.quantity || 0);
      const value = quantity * Number(order?.agreed_price || 0);
      if (!metrics[key]) {
        metrics[key] = { orders: 0, quantity: 0, value: 0, products: new Set() };
      }
      metrics[key].orders += 1;
      metrics[key].quantity += quantity;
      metrics[key].value += value;
      if (order?.product_id) {
        metrics[key].products.add(order.product_id);
      }
    });
  });
  return metrics;
};

const buildTopologyGraph = (enterpriseSpecs = [], currentCompany, companyNameMap, exchangeData) => {
  const tierGroups = new Map();
  enterpriseSpecs.forEach((spec, index) => {
    const enterpriseId = getEnterpriseId(spec);
    if (!enterpriseId) {
      return;
    }
    const tier = Number.isFinite(Number(spec?.tier)) ? Number(spec.tier) : index;
    if (!tierGroups.has(tier)) {
      tierGroups.set(tier, []);
    }
    tierGroups.get(tier).push(spec);
  });

  const tiers = Array.from(tierGroups.keys()).sort((a, b) => a - b);
  const maxRows = Math.max(1, ...Array.from(tierGroups.values()).map((group) => group.length));
  const xGap = tiers.length <= 1 ? 0 : 760 / Math.max(1, tiers.length - 1);
  const yGap = maxRows <= 1 ? 0 : 260 / Math.max(1, maxRows - 1);
  const edgeMetrics = getExchangeEdgeMetrics(exchangeData);

  const nodes = tiers.flatMap((tier, tierIndex) => {
    const group = tierGroups.get(tier) || [];
    const groupHeight = (group.length - 1) * yGap;
    return group.map((spec, rowIndex) => {
      const enterpriseId = getEnterpriseId(spec);
      const isCurrent = currentCompany === enterpriseId;
      return {
        name: enterpriseId,
        x: 90 + tierIndex * xGap,
        y: 80 + (maxRows <= 1 ? 120 : rowIndex * yGap + (260 - groupHeight) / 2),
        symbolSize: isCurrent ? 78 : 62,
        itemStyle: {
          color: isCurrent ? '#1f6feb' : '#8aa0b6',
          borderColor: isCurrent ? '#0b3f88' : '#d7e0ea',
          borderWidth: isCurrent ? 3 : 1,
        },
        label: {
          formatter: companyNameMap[enterpriseId] || enterpriseId,
        },
        tooltip: {
          formatter: [
            `<strong>${companyNameMap[enterpriseId] || enterpriseId}</strong>`,
            `Tier ${tier}`,
            `采购: ${(spec?.purchasable_materials_idList || []).join(', ') || '-'}`,
            `销售: ${(spec?.salable_products_idList || []).join(', ') || '-'}`,
          ].join('<br/>'),
        },
      };
    });
  });

  const links = getTopologyEdgesFromSpecs(enterpriseSpecs).map((edge) => {
    const metric = edgeMetrics[`${edge.source}->${edge.target}`];
    const hasTrade = Boolean(metric?.orders);
    return {
      source: edge.source,
      target: edge.target,
      value: metric?.quantity || 0,
      label: {
        show: true,
        formatter: hasTrade ? `${formatNumber(metric.quantity)} / ${metric.orders}单` : '配置链路',
      },
      lineStyle: {
        width: hasTrade ? Math.min(6, 2 + Math.log10(metric.quantity + 1)) : 1.5,
        opacity: hasTrade ? 0.9 : 0.35,
        color: hasTrade ? '#2f80ed' : '#aab6c4',
      },
      tooltip: {
        formatter: hasTrade
          ? `${edge.source} -> ${edge.target}<br/>订单: ${metric.orders}<br/>数量: ${formatNumber(metric.quantity)}<br/>金额: ${formatCurrency(metric.value)}<br/>商品: ${Array.from(metric.products).join(', ')}`
          : `${edge.source} -> ${edge.target}<br/>配置链路，当前轮暂无成交`,
      },
    };
  });

  return { nodes, links };
};

const normalizeActionItems = (payload) => {
  if (!Array.isArray(payload)) {
    return [];
  }
  if (payload.length === 1 && Array.isArray(payload[0])) {
    return payload[0];
  }
  return payload.filter((item) => item && typeof item === 'object');
};

const summarizeActionNames = (payload) => (
  normalizeActionItems(payload)
    .map((item) => item?.action?.action_name || (item?.pass_reason ? 'action_pass' : ''))
    .filter(Boolean)
);

const RoundEnterpriseBoard = ({
  enterpriseSpecs,
  currentCompany,
  currentDay,
  dataRoot,
  onCompanyChange,
  companyNameMap,
  includeSingleCaseSeedActions = false,
}) => {
  const [rows, setRows] = useState([]);

  useEffect(() => {
    let cancelled = false;
    const departments = ['finance', 'sales', 'procurement', 'inventory', 'production'];
    const loadRows = async () => {
      const nextRows = await Promise.all((enterpriseSpecs || []).map(async (spec) => {
        const enterpriseId = getEnterpriseId(spec);
        const departmentData = {};
        await Promise.all(departments.map(async (dept) => {
          departmentData[dept] = await safeFetchJson(
            buildDataUrl(dataRoot, `enterprises/${enterpriseId}/department/${dept}/day${currentDay}/${dept}.json`)
          );
        }));

        const actionNames = [];
        await Promise.all(departments.map(async (dept) => {
          const [preAction, action, marketSeedAction] = await Promise.all([
            safeFetchJson(buildDataUrl(dataRoot, `enterprises/${enterpriseId}/department/${dept}/day${currentDay}/pre_${dept}_action.json`)),
            safeFetchJson(buildDataUrl(dataRoot, `enterprises/${enterpriseId}/department/${dept}/day${currentDay}/${dept}_action.json`)),
            includeSingleCaseSeedActions && dept === 'sales'
              ? safeFetchJson(buildDataUrl(dataRoot, `enterprises/${enterpriseId}/department/${dept}/day${currentDay}/sales_market_seed_action.json`))
              : Promise.resolve(null),
          ]);
          summarizeActionNames(preAction).forEach((name) => actionNames.push(`${dept}:${name}`));
          summarizeActionNames(action).forEach((name) => actionNames.push(`${dept}:${name}`));
          summarizeActionNames(marketSeedAction).forEach((name) => actionNames.push(`${dept}:prewarm_seed:${name}`));
        }));

        const finance = departmentData.finance?.self_state || {};
        const inventory = departmentData.inventory?.self_state || {};
        const production = departmentData.production?.self_state || {};
        const procurement = departmentData.procurement?.self_state || {};
        const sales = departmentData.sales?.self_state || {};
        const inventoryItems = inventory.inventory_items || [];
        const lowStockCount = inventoryItems.filter((item) => item?.is_low_stock || item?.is_below_reorder_point).length;

        return {
          enterpriseId,
          tier: spec?.tier,
          cash: finance.cash,
          netProfit: finance.financial_indicators?.net_profit,
          lowStockCount,
          inventoryKinds: inventoryItems.length,
          productionQuantity: production.production_metrics?.total_production,
          salesOrders: sales.sales_metrics?.total_orders,
          procurementOrders: procurement.procurement_metrics?.total_orders,
          actionNames,
        };
      }));
      if (!cancelled) {
        setRows(nextRows);
      }
    };
    loadRows();
    return () => {
      cancelled = true;
    };
  }, [enterpriseSpecs, currentDay, dataRoot]);

  if (!rows.length) {
    return null;
  }

  return (
    <section className="round-overview-panel">
      <div className="round-overview-header">
        <div>
          <span>Round Snapshot</span>
          <strong>Turn {currentDay} 企业状态与动作概览</strong>
        </div>
        <small>点击企业卡片切换下方详情；库存预警、产量和动作名称用于快速定位本轮变化。</small>
      </div>
      <div className="round-enterprise-grid">
        {rows.map((row) => (
          <button
            type="button"
            key={row.enterpriseId}
            className={`round-enterprise-card ${currentCompany === row.enterpriseId ? 'active' : ''} ${row.lowStockCount > 0 ? 'warning' : ''}`}
            onClick={() => onCompanyChange(row.enterpriseId)}
          >
            <div className="round-enterprise-head">
              <span>{companyNameMap[row.enterpriseId] || row.enterpriseId}</span>
              <small>Tier {row.tier ?? '-'}</small>
            </div>
            <div className="round-enterprise-metrics">
              <span>现金 <strong>{formatCurrency(row.cash)}</strong></span>
              <span>利润 <strong className={Number(row.netProfit || 0) < 0 ? 'negative' : 'positive'}>{formatCurrency(row.netProfit)}</strong></span>
              <span>库存预警 <strong>{row.lowStockCount}/{row.inventoryKinds}</strong></span>
              <span>产量 <strong>{formatNumber(row.productionQuantity)}</strong></span>
              <span>采购单 <strong>{formatNumber(row.procurementOrders)}</strong></span>
              <span>销售单 <strong>{formatNumber(row.salesOrders)}</strong></span>
            </div>
            <div className="round-action-strip">
              {row.actionNames.length > 0 ? row.actionNames.slice(0, 4).map((name, index) => (
                <em key={`${row.enterpriseId}-${name}-${index}`}>{name}</em>
              )) : (
                <em>暂无动作</em>
              )}
              {row.actionNames.length > 4 && <em>+{row.actionNames.length - 4}</em>}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
};

function App() {
  const [currentCompany, setCurrentCompany] = useState('');
  const [currentDay, setCurrentDay] = useState(0);
  const [currentPage, setCurrentPage] = useState('daily');
  const [selectedExchangeId, setSelectedExchangeId] = useState(null);
  const [availableDays, setAvailableDays] = useState([]);
  const [availableRuns, setAvailableRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [selectedRunMeta, setSelectedRunMeta] = useState(null);
  const [activeRunId, setActiveRunId] = useState(null);
  const [activeRunMeta, setActiveRunMeta] = useState(null);
  const [scenarioFilter, setScenarioFilter] = useState('all');
  const [analysisScope, setAnalysisScope] = useState('multi');
  const [singleCaseFilter, setSingleCaseFilter] = useState('all');
  const [multiScenarioFilter, setMultiScenarioFilter] = useState('all');
  const [analysisControlModeFilter, setAnalysisControlModeFilter] = useState('all');
  const [runRecordFilters, setRunRecordFilters] = useState({
    scope: 'all',
    category: 'all',
    scenarioId: 'all',
    mode: 'all',
    dateFrom: '',
    dateTo: '',
  });
  const [selectedRunRecordIds, setSelectedRunRecordIds] = useState(new Set());
  const [scenarioPage, setScenarioPage] = useState('bullwhip');
  const [singlePerformanceMode, setSinglePerformanceMode] = useState('trend');
  const [dailyExchangeData, setDailyExchangeData] = useState(null);
  const [productEquivalentMode, setProductEquivalentMode] = useState(false);
  const [includeUpstreamExternalSupplierMode, setIncludeUpstreamExternalSupplierMode] = useState(false);
  const [includeDownstreamExternalMarketMode, setIncludeDownstreamExternalMarketMode] = useState(false);
  const [viewMode, setViewMode] = useState('welcome');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const chartRef = useRef(null);
  const chartInstance = useRef(null);
  const selectedRunEntry = useMemo(
    () => availableRuns.find((run) => run.id === selectedRunId) || null,
    [availableRuns, selectedRunId]
  );
  const activeRunEntry = useMemo(
    () => availableRuns.find((run) => run.id === activeRunId) || null,
    [availableRuns, activeRunId]
  );
  const filteredAvailableRuns = useMemo(
    () => (
      scenarioFilter === 'all'
        ? availableRuns
        : availableRuns.filter((run) => detectRunCategory(run.meta) === scenarioFilter)
    ),
    [availableRuns, scenarioFilter]
  );
  const analysisScopeRuns = useMemo(
    () => availableRuns.filter((run) => {
      if (getAnalysisScopeFromMeta(run.meta) !== analysisScope) {
        return false;
      }
      if (
        analysisControlModeFilter !== 'all'
        && getRunControlModeFromMeta(run.meta) !== analysisControlModeFilter
      ) {
        return false;
      }
      if (analysisScope !== 'single' || singleCaseFilter === 'all') {
        if (analysisScope === 'multi' && multiScenarioFilter !== 'all') {
          return detectScenarioPage(run.meta) === multiScenarioFilter;
        }
        return true;
      }
      return getSingleCaseIdFromMeta(run.meta) === singleCaseFilter;
    }),
    [availableRuns, analysisScope, singleCaseFilter, multiScenarioFilter, analysisControlModeFilter]
  );
  const availableSingleCaseFilterIds = useMemo(
    () => new Set(
      availableRuns
        .filter((run) => getAnalysisScopeFromMeta(run.meta) === 'single')
        .filter((run) => (
          analysisControlModeFilter === 'all'
          || getRunControlModeFromMeta(run.meta) === analysisControlModeFilter
        ))
        .map((run) => getSingleCaseIdFromMeta(run.meta))
        .filter(Boolean)
    ),
    [availableRuns, analysisControlModeFilter]
  );
  const availableAnalysisControlModeIds = useMemo(
    () => new Set(
      availableRuns
        .filter((run) => getAnalysisScopeFromMeta(run.meta) === analysisScope)
        .filter((run) => (
          analysisScope !== 'single'
          || singleCaseFilter === 'all'
          || getSingleCaseIdFromMeta(run.meta) === singleCaseFilter
        ))
        .filter((run) => (
          analysisScope !== 'multi'
          || multiScenarioFilter === 'all'
          || detectScenarioPage(run.meta) === multiScenarioFilter
        ))
        .map((run) => getRunControlModeFromMeta(run.meta))
        .filter(Boolean)
    ),
    [availableRuns, analysisScope, singleCaseFilter, multiScenarioFilter]
  );
  const availableMultiScenarioFilterIds = useMemo(
    () => new Set(
      availableRuns
        .filter((run) => getAnalysisScopeFromMeta(run.meta) === 'multi')
        .filter((run) => (
          analysisControlModeFilter === 'all'
          || getRunControlModeFromMeta(run.meta) === analysisControlModeFilter
        ))
        .map((run) => detectScenarioPage(run.meta))
        .filter(Boolean)
    ),
    [availableRuns, analysisControlModeFilter]
  );
  const runRecordScenarioIds = useMemo(
    () => Array.from(new Set(
      availableRuns
        .map((run) => getScenarioIdFromMeta(run.meta))
        .filter(Boolean)
    )).sort(),
    [availableRuns]
  );
  const filteredRunRecords = useMemo(
    () => availableRuns.filter((run) => {
      const scope = getAnalysisScopeFromMeta(run.meta);
      const category = detectRunCategory(run.meta);
      const scenarioId = getScenarioIdFromMeta(run.meta);
      const mode = getRunControlModeFromMeta(run.meta);
      const dateValue = getRunRecordDateValue(run);
      if (runRecordFilters.scope !== 'all' && scope !== runRecordFilters.scope) {
        return false;
      }
      if (runRecordFilters.category !== 'all' && category !== runRecordFilters.category) {
        return false;
      }
      if (runRecordFilters.scenarioId !== 'all' && scenarioId !== runRecordFilters.scenarioId) {
        return false;
      }
      if (runRecordFilters.mode !== 'all' && mode !== runRecordFilters.mode) {
        return false;
      }
      if (runRecordFilters.dateFrom && (!dateValue || dateValue < runRecordFilters.dateFrom)) {
        return false;
      }
      if (runRecordFilters.dateTo && (!dateValue || dateValue > runRecordFilters.dateTo)) {
        return false;
      }
      return true;
    }),
    [availableRuns, runRecordFilters]
  );
  const selectedRunRecords = useMemo(
    () => availableRuns.filter((run) => selectedRunRecordIds.has(run.id)),
    [availableRuns, selectedRunRecordIds]
  );
  const visibleAnalysisPages = useMemo(
    () => (analysisScope === 'single' ? SINGLE_ANALYSIS_PAGES : MULTI_ANALYSIS_PAGES),
    [analysisScope]
  );
  const activeRunHasScenarioAnalysis = useMemo(
    () => analysisScope === 'multi' && hasScenarioAnalysisPage(activeRunMeta || selectedRunMeta),
    [analysisScope, activeRunMeta, selectedRunMeta]
  );
  const dataRoot = activeRunEntry?.dataRoot || selectedRunEntry?.dataRoot || '/workspace_multi';
  const quantityView = useMemo(
    () => buildQuantityView(productEquivalentMode, activeRunMeta || selectedRunMeta),
    [productEquivalentMode, activeRunMeta, selectedRunMeta]
  );
  const selectedEnterpriseSpecs = useMemo(
    () => getEnterpriseSpecsFromMeta(selectedRunMeta),
    [selectedRunMeta]
  );
  const activeEnterpriseSpecs = useMemo(
    () => getEnterpriseSpecsFromMeta(activeRunMeta || selectedRunMeta),
    [activeRunMeta, selectedRunMeta]
  );
  const companies = useMemo(
    () => activeEnterpriseSpecs.map((spec) => spec.enterprise_id || spec.id).filter(Boolean),
    [activeEnterpriseSpecs]
  );
  const companyNameMap = useMemo(
    () => Object.fromEntries(
      activeEnterpriseSpecs.map((spec) => [
        spec.enterprise_id || spec.id,
        spec.enterprise_name || spec.name || spec.enterprise_id || spec.id,
      ])
    ),
    [activeEnterpriseSpecs]
  );
  const topEnterpriseName = activeEnterpriseSpecs[0]?.enterprise_name
    || activeEnterpriseSpecs[0]?.name
    || activeEnterpriseSpecs[0]?.enterprise_id
    || activeEnterpriseSpecs[0]?.id
    || 'Top';
  const secondEnterpriseName = activeEnterpriseSpecs[1]?.enterprise_name
    || activeEnterpriseSpecs[1]?.name
    || activeEnterpriseSpecs[1]?.enterprise_id
    || activeEnterpriseSpecs[1]?.id
    || 'Next';
  const bottomEnterpriseName = activeEnterpriseSpecs[activeEnterpriseSpecs.length - 1]?.enterprise_name
    || activeEnterpriseSpecs[activeEnterpriseSpecs.length - 1]?.name
    || activeEnterpriseSpecs[activeEnterpriseSpecs.length - 1]?.enterprise_id
    || activeEnterpriseSpecs[activeEnterpriseSpecs.length - 1]?.id
    || 'Retail';

  useEffect(() => {
    loadRunCatalog();
  }, []);

  useEffect(() => {
    setSelectedRunMeta(selectedRunEntry?.meta || null);
  }, [selectedRunEntry]);

  useEffect(() => {
    if (filteredAvailableRuns.length === 0) {
      return;
    }
    if (!filteredAvailableRuns.some((run) => run.id === selectedRunId)) {
      const preferredRun = pickPreferredRun(filteredAvailableRuns, {
        keepCandidate: false,
        preferredScope: 'multi',
      });
      setSelectedRunId(preferredRun?.id || '');
      setSelectedRunMeta(preferredRun?.meta || null);
    }
  }, [filteredAvailableRuns, selectedRunId]);

  useEffect(() => {
    if (!activeRunId || viewMode !== 'analysis') {
      return;
    }
    loadAnalysisData(activeRunId);
  }, [activeRunId, viewMode]);

  useEffect(() => {
    if (viewMode !== 'analysis') {
      return;
    }
    if (!visibleAnalysisPages.some((page) => page.id === currentPage)) {
      setCurrentPage(visibleAnalysisPages[0]?.id || 'daily');
    }
  }, [viewMode, visibleAnalysisPages, currentPage]);

  useEffect(() => {
    if (!loading && currentPage === 'daily' && analysisScope === 'multi') {
      return initCompanyNetwork();
    }
  }, [currentCompany, loading, currentPage, viewMode, activeEnterpriseSpecs, dailyExchangeData, analysisScope]);

  useEffect(() => {
    if (viewMode !== 'analysis' || currentPage !== 'daily') {
      return;
    }
    let cancelled = false;
    const loadDailyExchangeSnapshot = async () => {
      const payload = await safeFetchJson(buildDataUrl(dataRoot, `public/exchange/day${currentDay}/exchange.json`));
      if (!cancelled) {
        setDailyExchangeData(payload || null);
      }
    };
    loadDailyExchangeSnapshot();
    return () => {
      cancelled = true;
    };
  }, [viewMode, currentPage, dataRoot, currentDay]);

  useEffect(() => {
    if (companies.length === 0) {
      return;
    }
    if (!currentCompany || !companies.includes(currentCompany)) {
      setCurrentCompany(companies[0]);
    }
  }, [companies, currentCompany]);

  const loadRunCatalog = async ({
    preferredRunId,
    preferLatest = false,
    preferredScope = 'multi',
  } = {}) => {
    try {
      setLoading(true);
      setError(null);

      const runs = await detectAvailableRuns();
      setAvailableRuns(runs);
      const candidateRunId = preferredRunId || selectedRunId;
      const shouldKeepSelection = !preferLatest && candidateRunId && candidateRunId !== 'workspace_current';
      const preferredRun = pickPreferredRun(runs, {
        candidateRunId,
        keepCandidate: shouldKeepSelection,
        preferredScope,
      });
      const resolvedRunId = preferredRun?.id || '';
      const resolvedRunMeta = preferredRun?.meta || null;
      setSelectedRunId(resolvedRunId);
      setSelectedRunMeta(resolvedRunMeta);

      setLoading(false);
      return { runs, resolvedRunId, resolvedRunMeta };
    } catch (error) {
      console.error('加载任务目录失败:', error);
      setError('加载任务目录失败: ' + error.message);
      setLoading(false);
      return { runs: [], resolvedRunId: '', resolvedRunMeta: null };
    }
  };

  const loadAnalysisData = async (runId) => {
    try {
      setLoading(true);
      setError(null);

      const runEntry = availableRuns.find((run) => run.id === runId) || null;
      const rootPath = runEntry?.dataRoot || resolveDataRoot(runId);
      const maxDay = await detectMaxDay(rootPath, runEntry?.meta || selectedRunMeta || null);
      setAvailableDays(Array.from({ length: maxDay + 1 }, (_, i) => i));
      setCurrentDay(maxDay < 0 ? 0 : maxDay);
      setSelectedExchangeId(null);
      setActiveRunMeta(runEntry?.meta || selectedRunMeta || null);
      setAnalysisScope(getAnalysisScopeFromMeta(runEntry?.meta || selectedRunMeta));
      setScenarioPage(detectScenarioPage(runEntry?.meta || selectedRunMeta) || 'bullwhip');
      setLoading(false);
    } catch (loadError) {
      console.error('加载模拟数据失败:', loadError);
      setError('加载模拟数据失败: ' + loadError.message);
      setLoading(false);
    }
  };

  const detectAvailableRuns = async () => {
    const artifactRunsResult = await listArtifactRuns({ limit: 500 });
    if (artifactRunsResult.available && artifactRunsResult.entries.length > 0) {
      return finalizeRunCatalog(buildRunEntriesFromArtifactIndex(artifactRunsResult.entries));
    }

    const workspaceMeta = await safeFetchJson(buildDataUrl(resolveDataRoot(LATEST_RUN_ID), 'run_meta.json'), { forceRefresh: true });
    const simulationRunsListing = await safeFetchJson('/simulation_runs/', { forceRefresh: true });
    const operationsJobResult = await listOperationsJobs({ limit: 500 });
    const runDirs = Object.entries(simulationRunsListing || {})
      .filter(([, type]) => type === 'directory')
      .map(([name]) => name);
    const workspaceJobsListing = await safeFetchJson('/workspace_jobs/', { forceRefresh: true });
    const jobWorkspaceDirs = Object.entries(workspaceJobsListing || {})
      .filter(([, type]) => type === 'directory')
      .map(([name]) => name);

    const historicalRuns = await Promise.all(
      runDirs.map(async (runId) => {
        const meta = await safeFetchJson(
          buildDataUrl(resolveDataRoot(runId), 'run_meta.json'),
          { forceRefresh: true }
        );
        const experimentTag = getRunExperimentTag(runId);
        return {
          id: runId,
          label: formatRunLabel(runId, meta, false, experimentTag),
          meta,
          dataRoot: resolveDataRoot(runId),
          sourceLabel: runId,
          experimentTag,
        };
      })
    );
    const workspaceJobRuns = (await Promise.all(
      jobWorkspaceDirs.map(async (workspaceName) => {
        const dataRoot = resolveWorkspaceJobRoot(workspaceName);
        const meta = await safeFetchJson(
          buildDataUrl(dataRoot, 'run_meta.json'),
          { forceRefresh: true }
        );
        if (!meta) {
          return null;
        }
        const runId = meta.run_id || workspaceName;
        const entryId = `workspace_job:${workspaceName}`;
        const experimentTag = getRunExperimentTag(workspaceName, runId);
        return {
          id: entryId,
          label: formatRunLabel(runId, meta, false, experimentTag),
          meta,
          dataRoot,
          sourceLabel: workspaceName,
          resolvedRunId: runId,
          experimentTag,
        };
      })
    )).filter(Boolean);
    const operationsJobRuns = (await Promise.all(
      (operationsJobResult.jobs || []).map(async (job) => {
        const workspaceName = getWorkspaceNameFromArtifactRoot(job?.artifact_root);
        if (!workspaceName) {
          return null;
        }
        const dataRoot = resolveWorkspaceJobRoot(workspaceName);
        const meta = (
          await safeFetchJson(buildDataUrl(dataRoot, 'run_meta.json'), { forceRefresh: true })
        ) || buildRunMetaFromOperationsJob(job);
        const runId = meta.run_id || job.run_id || job.job_id || workspaceName;
        const experimentTag = getRunExperimentTag(workspaceName, runId, job?.artifact_root);
        return {
          id: `operations_job:${job.job_id || workspaceName}`,
          label: formatRunLabel(runId, meta, false, experimentTag),
          meta,
          dataRoot,
          sourceLabel: workspaceName,
          resolvedRunId: runId,
          experimentTag,
        };
      })
    )).filter(Boolean);

    const workspaceEntry = workspaceMeta ? {
      id: 'workspace_current',
      label: formatRunLabel('workspace_current', workspaceMeta),
      meta: workspaceMeta,
      dataRoot: '/workspace_multi',
      sourceLabel: 'workspace_multi',
      experimentTag: '',
    } : null;

    const allHistoricalRuns = [
      ...workspaceJobRuns,
      ...operationsJobRuns,
      ...historicalRuns,
      workspaceEntry,
    ].filter(Boolean);
    return finalizeRunCatalog(allHistoricalRuns);
  };

  const renderRunMetaValue = (value) => {
    if (value === null || value === undefined || value === '') {
      return '-';
    }
    return String(value);
  };

  const renderRunTimeValue = (value) => {
    if (value === null || value === undefined || value === '') {
      return '-';
    }
    return formatDisplayTime(value);
  };

  const renderScenarioConfigSummary = (runMeta) => {
    const scenarioConfig = runMeta?.scenario_config || {};
    const simulation = scenarioConfig.simulation || {};
    const runtimeInjection = scenarioConfig.runtime_injection || {};
    const autoPolicy = scenarioConfig.auto_policy || {};
    const enterpriseConfigs = scenarioConfig.enterprise_configs || [];
    const initialActionBatches = scenarioConfig.initial_action_batches || {};
    const demandSeries = simulation.beer_game_demand_series || [];
    const initStaffingByEnterprise = indexActionsByExecutor(initialActionBatches.init_action_1 || []);
    const initInventoryByEnterprise = indexActionsByExecutor(initialActionBatches.init_action_2 || []);
    const initPoliciesByEnterprise = indexActionsByExecutor(initialActionBatches.init_action_3 || []);

    const enterpriseSnapshots = enterpriseConfigs.map((enterprise) => {
      const enterpriseId = enterprise.id;
      const staffingAction = (initStaffingByEnterprise[enterpriseId] || []).find(
        (item) => item?.action?.action_name === 'initialize_staffing'
      );
      const capacityAction = (initStaffingByEnterprise[enterpriseId] || []).find(
        (item) => item?.action?.action_name === 'set_capacity'
      );
      const inventoryItems = (initInventoryByEnterprise[enterpriseId] || [])
        .filter((item) => item?.action?.action_name === 'add_inventory')
        .map((item) => item.action.action_param || {});
      const policyItems = (initPoliciesByEnterprise[enterpriseId] || [])
        .filter((item) => item?.action?.action_name === 'set_inventory_policy')
        .map((item) => item.action.action_param || {});

      return {
        enterprise,
        staffing: staffingAction?.action?.action_param?.initial_staffing || {},
        capacity: capacityAction?.action?.action_param?.capacity,
        inventoryItems,
        policyItems,
      };
    });

    const productionSnapshots = enterpriseSnapshots
      .map((snapshot) => {
        const enterpriseId = snapshot.enterprise.id;
        const enterpriseInitActions = initPoliciesByEnterprise[enterpriseId] || [];
        const recipeAction = enterpriseInitActions.find((item) => item?.action?.action_name === 'set_product_recipe');
        const lineActions = enterpriseInitActions.filter((item) => item?.action?.action_name === 'build_production_line');
        return {
          enterpriseId,
          enterpriseName: snapshot.enterprise.name || enterpriseId,
          recipeAction,
          lineActions,
        };
      })
      .filter((snapshot) => snapshot.recipeAction || snapshot.lineActions.length > 0);

    return (
      <div className="welcome-config-sections">
        <section className="welcome-config-section">
          <div className="welcome-config-section-header">
            <h3>场景概览</h3>
            <span>这部分说明本次模拟的轮次、市场节奏和基本运行模式。</span>
          </div>
          <div className="welcome-meaning-grid">
            <div className="meaning-card">
              <span>服务总轮次</span>
              <strong>{renderRunMetaValue(simulation.service_total_steps)}</strong>
              <p>环境总共推进多少个模拟轮次。</p>
            </div>
            <div className="meaning-card">
              <span>Agent 运行轮次</span>
              <strong>{renderRunMetaValue(simulation.agent_run_steps)}</strong>
              <p>企业 Agent 会参与决策的轮次数量。</p>
            </div>
            <div className="meaning-card">
              <span>终端单价</span>
              <strong>{renderRunMetaValue(simulation.beer_game_unit_price)}</strong>
              <p>{(selectedEnterpriseSpecs[selectedEnterpriseSpecs.length - 1]?.enterprise_name || selectedEnterpriseSpecs[selectedEnterpriseSpecs.length - 1]?.name || '终端企业')} 面向基础外部需求市场的终端价格。</p>
            </div>
            <div className="meaning-card">
              <span>客户交付提前期</span>
              <strong>{renderRunMetaValue(simulation.beer_game_customer_delivery_lead_time)}</strong>
              <p>外部市场订单从下达到交付的基础轮次间隔。</p>
            </div>
          </div>
        </section>

        <section className="welcome-config-section">
          <div className="welcome-config-section-header">
            <h3>需求路径</h3>
            <span>展示基础外部需求如何在每轮输入系统，是多类实验共享的需求补给基线。</span>
          </div>
          <div className="demand-series-panel">
            {(demandSeries || []).map((value, index) => (
              <div key={`${index}-${value}`} className="demand-chip">
                <span>Turn {index}</span>
                <strong>{formatNumber(value)}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="welcome-config-section">
          <div className="welcome-config-section-header">
            <h3>企业初始盘面</h3>
            <span>这部分把每家企业一开始拥有什么拆开说明，包括钱、仓容、人手、库存和库存阈值。</span>
          </div>
          <div className="enterprise-config-cards">
            {enterpriseSnapshots.map(({ enterprise, staffing, capacity, inventoryItems, policyItems }) => (
              <article key={enterprise.id} className="enterprise-detail-card">
                <div className="enterprise-detail-header">
                  <h4>{enterprise.name || enterprise.id}</h4>
                  <span>Tier {renderRunMetaValue(enterprise.tier)}</span>
                </div>

                <div className="enterprise-detail-grid">
                  <div className="enterprise-detail-item">
                    <span>初始资金</span>
                    <strong>{formatCurrency(enterprise.initial_capital)}</strong>
                    <p>企业在第 0 轮开始时可用于经营和交易的现金基础。</p>
                  </div>
                  <div className="enterprise-detail-item">
                    <span>初始仓容</span>
                    <strong>{renderRunMetaValue(capacity)}</strong>
                    <p>仓库总容量上限，决定库存能容纳多少标准存储单位。</p>
                  </div>
                  <div className="enterprise-detail-item">
                    <span>采购范围</span>
                    <strong>{(enterprise.purchasable_materials_idList || []).join(', ') || '-'}</strong>
                    <p>该企业能向上游采购哪些物料或成品。</p>
                  </div>
                  <div className="enterprise-detail-item">
                    <span>销售范围</span>
                    <strong>{(enterprise.salable_products_idList || []).join(', ') || '-'}</strong>
                    <p>该企业能向下游或市场出售哪些产品。</p>
                  </div>
                </div>

                <div className="enterprise-detail-subsection">
                  <h5>初始 staffing</h5>
                  <div className="inline-chip-list">
                    {Object.entries(staffing).length > 0 ? (
                      Object.entries(staffing).map(([department, count]) => (
                        <span key={`${enterprise.id}-${department}`}>{department}: {count}</span>
                      ))
                    ) : (
                      <span>-</span>
                    )}
                  </div>
                </div>

                <div className="enterprise-detail-subsection">
                  <h5>初始库存</h5>
                  <div className="mini-table">
                    <div className="mini-table-row mini-table-head">
                      <span>物料</span>
                      <span>数量</span>
                      <span>类型</span>
                    </div>
                    {inventoryItems.length > 0 ? (
                      inventoryItems.map((item, index) => (
                        <div key={`${enterprise.id}-${item.item_id}-${index}`} className="mini-table-row">
                          <span>{item.item_id}</span>
                          <span>{formatNumber(item.quantity)}</span>
                          <span>{item.item_type}</span>
                        </div>
                      ))
                    ) : (
                      <div className="mini-table-row">
                        <span>-</span>
                        <span>-</span>
                        <span>-</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="enterprise-detail-subsection">
                  <h5>库存策略阈值</h5>
                  <div className="mini-table">
                    <div className="mini-table-row mini-table-head">
                      <span>物料</span>
                      <span>再订购点</span>
                      <span>安全库存</span>
                    </div>
                    {policyItems.length > 0 ? (
                      policyItems.map((item, index) => (
                        <div key={`${enterprise.id}-policy-${item.item_id}-${index}`} className="mini-table-row">
                          <span>{item.item_id}</span>
                          <span>{formatNumber(item.reorder_point)}</span>
                          <span>{formatNumber(item.safety_stock)}</span>
                        </div>
                      ))
                    ) : (
                      <div className="mini-table-row">
                        <span>-</span>
                        <span>-</span>
                        <span>-</span>
                      </div>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

        {productionSnapshots.length > 0 && (
          <section className="welcome-config-section">
            <div className="welcome-config-section-header">
              <h3>生产节点设置</h3>
              <span>仅当场景中存在 production 模块时才显示，用于说明哪些企业具备制造能力及其初始配置。</span>
            </div>
            {productionSnapshots.map((snapshot) => (
              <div key={snapshot.enterpriseId} className="recipe-panel">
                <h5>{snapshot.enterpriseName}</h5>
                <div className="welcome-meaning-grid">
                  <div className="meaning-card">
                    <span>生产线数量</span>
                    <strong>{renderRunMetaValue(snapshot.lineActions.length)}</strong>
                    <p>该企业启动时已经建好的产线条数。</p>
                  </div>
                  <div className="meaning-card">
                    <span>产线类型</span>
                    <strong>{snapshot.lineActions.map((item) => item?.action?.action_param?.line_type).filter(Boolean).join(', ') || '-'}</strong>
                    <p>系统初始化时为该企业建好的产线规格。</p>
                  </div>
                  <div className="meaning-card">
                    <span>目标产品</span>
                    <strong>{renderRunMetaValue(snapshot.recipeAction?.action?.action_param?.product_id)}</strong>
                    <p>该生产节点负责制造的主要成品。</p>
                  </div>
                  <div className="meaning-card">
                    <span>单位转换成本</span>
                    <strong>
                      {formatNumber(
                        Number(snapshot.recipeAction?.action?.action_param?.labor_cost_per_unit || 0)
                        + Number(snapshot.recipeAction?.action?.action_param?.equipment_cost_per_unit || 0)
                      )}
                    </strong>
                    <p>每生产 1 单位成品时，人工和设备合计的加工成本。</p>
                  </div>
                </div>
                <div className="inline-chip-list">
                  {Object.entries(snapshot.recipeAction?.action?.action_param?.raw_materials || {}).map(([material, amount]) => (
                    <span key={`${snapshot.enterpriseId}-recipe-${material}`}>{material}: {formatNumber(amount)}</span>
                  ))}
                </div>
              </div>
            ))}
          </section>
        )}

        <section className="welcome-config-section">
          <div className="welcome-config-section-header">
            <h3>系统自动规则</h3>
            <span>这部分描述 Auto HR / Auto Inventory 何时会自动招人或扩仓，会影响模拟中的自动干预强度。</span>
          </div>
          <div className="welcome-meaning-grid">
            <div className="meaning-card">
              <span>HR 招聘触发阈值</span>
              <strong>{renderRunMetaValue(autoPolicy.hr?.recruit_trigger_threshold)}</strong>
              <p>部门压力达到该阈值后，Auto HR 更倾向自动发起招聘。</p>
            </div>
            <div className="meaning-card">
              <span>HR 单次招聘比例</span>
              <strong>{renderRunMetaValue(autoPolicy.hr?.recruit_ratio)}</strong>
              <p>当触发招聘时，自动补人动作的大致力度。</p>
            </div>
            <div className="meaning-card">
              <span>库存扩仓阈值</span>
              <strong>{renderRunMetaValue(autoPolicy.inventory?.expand_trigger_threshold)}</strong>
              <p>仓库利用率超过该值后，Auto Inventory 更倾向扩容。</p>
            </div>
            <div className="meaning-card">
              <span>库存扩仓比例</span>
              <strong>{renderRunMetaValue(autoPolicy.inventory?.expand_ratio)}</strong>
              <p>自动扩仓时的增量力度参考值。</p>
            </div>
          </div>
        </section>

        <section className="welcome-config-section">
          <div className="welcome-config-section-header">
            <h3>系统注入与结算</h3>
            <span>这部分说明 daily 阶段系统会自动追加哪些结算动作，例如工资发放和库存成本计提。</span>
          </div>
          <div className="welcome-meaning-grid">
            <div className="meaning-card">
              <span>工资结算周期</span>
              <strong>{renderRunMetaValue(runtimeInjection.salary_payment_interval_days)}</strong>
              <p>每隔多少轮自动为配置企业执行一次工资发放。</p>
            </div>
            <div className="meaning-card">
              <span>工资结算企业</span>
              <strong>{(runtimeInjection.salary_payment_enterprise_ids || []).join(', ') || '-'}</strong>
              <p>会被系统自动执行工资支付的企业范围。</p>
            </div>
            <div className="meaning-card">
              <span>库存成本逐轮结算</span>
              <strong>{runtimeInjection.inventory_cost_daily_settlement_enabled ? '开启' : '关闭'}</strong>
              <p>决定库存维护/运营成本是否会在 daily 主链路里自动结转。</p>
            </div>
            <div className="meaning-card">
              <span>库存成本作用企业</span>
              <strong>{(runtimeInjection.inventory_cost_enterprise_ids || []).join(', ') || '-'}</strong>
              <p>启用库存成本结转时，具体作用到哪些企业。</p>
            </div>
          </div>
        </section>

        <details className="welcome-config-raw">
          <summary>查看原始场景 JSON</summary>
          <pre>{JSON.stringify(scenarioConfig, null, 2)}</pre>
        </details>
      </div>
    );
  };

  const handleEnterAnalysis = async () => {
    const preferredScope = selectedRunMeta
      ? getAnalysisScopeFromMeta(selectedRunMeta)
      : 'multi';
    const refreshedCatalog = await loadRunCatalog({ preferredRunId: selectedRunId, preferredScope });
    const nextRunId = refreshedCatalog.resolvedRunId || selectedRunId;
    const nextRunMeta = refreshedCatalog.resolvedRunMeta || selectedRunMeta;
    const nextScenarioPage = detectScenarioPage(nextRunMeta);
    const nextAnalysisScope = getAnalysisScopeFromMeta(nextRunMeta);
    setLoading(true);
    setActiveRunId(nextRunId);
    setActiveRunMeta(nextRunMeta);
    setAnalysisScope(nextAnalysisScope);
    setScenarioPage(nextScenarioPage || 'bullwhip');
    setCurrentPage(nextScenarioPage && nextAnalysisScope === 'multi' ? 'scenario' : 'daily');
    const nextEnterpriseSpecs = getEnterpriseSpecsFromMeta(nextRunMeta);
    setCurrentCompany(nextEnterpriseSpecs[0]?.enterprise_id || nextEnterpriseSpecs[0]?.id || '');
    setViewMode('analysis');
  };

  const handleEnterExperimentOps = () => {
    setViewMode('experimentOps');
  };

  const handleBackToWelcome = () => {
    setViewMode('welcome');
    loadRunCatalog({ preferLatest: true });
  };

  const handleScenarioFilterChange = (filterValue) => {
    setScenarioFilter(filterValue);
    const nextRuns = filterValue === 'all'
      ? availableRuns
      : availableRuns.filter((run) => detectRunCategory(run.meta) === filterValue);
    if (nextRuns.length > 0 && !nextRuns.some((run) => run.id === selectedRunId)) {
      const preferredRun = pickPreferredRun(nextRuns, {
        keepCandidate: false,
        preferredScope: 'multi',
      });
      setSelectedRunId(preferredRun?.id || '');
      setSelectedRunMeta(preferredRun?.meta || null);
    }
  };

  const updateRunRecordFilter = (field, value) => {
    setRunRecordFilters((previous) => ({
      ...previous,
      [field]: value,
    }));
  };

  const resetRunRecordFilters = () => {
    setRunRecordFilters({
      scope: 'all',
      category: 'all',
      scenarioId: 'all',
      mode: 'all',
      dateFrom: '',
      dateTo: '',
    });
  };

  const toggleRunRecordSelection = (runId) => {
    setSelectedRunRecordIds((previous) => {
      const next = new Set(previous);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  };

  const selectFilteredRunRecords = () => {
    setSelectedRunRecordIds((previous) => {
      const next = new Set(previous);
      filteredRunRecords.forEach((run) => next.add(run.id));
      return next;
    });
  };

  const clearRunRecordSelection = () => {
    setSelectedRunRecordIds(new Set());
  };

  const buildRunRecordExportPayload = (runs) => ({
    schema_version: 'visualization_run_record_export.v1',
    exported_at: new Date().toISOString(),
    total_records: runs.length,
    records: runs.map((run) => ({
      id: run.id,
      source_label: run.sourceLabel,
      resolved_run_id: run.resolvedRunId || run.meta?.run_id || run.id,
      scenario_id: getScenarioIdFromMeta(run.meta),
      scenario_category: detectRunCategory(run.meta),
      analysis_scope: getAnalysisScopeFromMeta(run.meta),
      control_mode: getRunControlModeFromMeta(run.meta),
      is_starred: Boolean(run.experimentTag),
      experiment_tag: run.experimentTag || '',
      experiment_tag_label: run.experimentTag ? formatExperimentTag(run.experimentTag) : '',
      status: run.meta?.status || '',
      completed_steps: run.meta?.completed_steps,
      planned_total_steps: run.meta?.planned_total_steps,
      started_at: run.meta?.started_at,
      finished_at: run.meta?.finished_at || run.meta?.archived_at,
      data_root: run.dataRoot,
      storage: getRunRecordStorageLabel(run),
      archive_url: buildRunArchiveUrl(run),
      files: buildRunRecordFileLinks(run),
      meta: run.meta,
    })),
  });

  const downloadRunRecords = (runs) => {
    if (!runs.length) {
      return;
    }
    const firstScenarioId = getScenarioIdFromMeta(runs[0].meta) || 'mixed';
    downloadJson(
      `${sanitizeDownloadPart(firstScenarioId)}_${runs.length}_run_records.json`,
      buildRunRecordExportPayload(runs)
    );
  };

  const downloadRunArchives = (runs) => {
    runs.forEach((run, index) => {
      const archiveUrl = buildRunArchiveUrl(run);
      if (!archiveUrl) {
        return;
      }
      window.setTimeout(() => downloadUrl(archiveUrl), index * 250);
    });
  };

  const handleAnalysisRunChange = (runId) => {
    const runEntry = availableRuns.find((run) => run.id === runId) || null;
    if (!runEntry) {
      return;
    }
    const nextAnalysisScope = getAnalysisScopeFromMeta(runEntry?.meta);
    setSelectedRunId(runId);
    setSelectedRunMeta(runEntry?.meta || null);
    setActiveRunId(runId);
    setActiveRunMeta(runEntry?.meta || null);
    setAnalysisScope(nextAnalysisScope);
    setScenarioPage(detectScenarioPage(runEntry?.meta) || 'bullwhip');
    setCurrentPage(hasScenarioAnalysisPage(runEntry?.meta) && nextAnalysisScope === 'multi' ? 'scenario' : 'daily');
    setSelectedExchangeId(null);
  };

  const handleSingleCaseFilterChange = (filterValue) => {
    setSingleCaseFilter(filterValue);
    const nextRuns = availableRuns.filter((run) => (
      getAnalysisScopeFromMeta(run.meta) === 'single'
      && (filterValue === 'all' || getSingleCaseIdFromMeta(run.meta) === filterValue)
      && (
        analysisControlModeFilter === 'all'
        || getRunControlModeFromMeta(run.meta) === analysisControlModeFilter
      )
    ));
    const currentRunId = activeRunId || selectedRunId;
    if (nextRuns.length > 0 && !nextRuns.some((run) => run.id === currentRunId)) {
      handleAnalysisRunChange(nextRuns[0].id);
    }
  };

  const handleMultiScenarioFilterChange = (filterValue) => {
    setMultiScenarioFilter(filterValue);
    const nextRuns = availableRuns.filter((run) => (
      getAnalysisScopeFromMeta(run.meta) === 'multi'
      && (filterValue === 'all' || detectScenarioPage(run.meta) === filterValue)
      && (
        analysisControlModeFilter === 'all'
        || getRunControlModeFromMeta(run.meta) === analysisControlModeFilter
      )
    ));
    const currentRunId = activeRunId || selectedRunId;
    if (nextRuns.length > 0 && !nextRuns.some((run) => run.id === currentRunId)) {
      handleAnalysisRunChange(nextRuns[0].id);
    }
  };

  const handleAnalysisControlModeFilterChange = (filterValue) => {
    setAnalysisControlModeFilter(filterValue);
    const nextRuns = availableRuns.filter((run) => (
      getAnalysisScopeFromMeta(run.meta) === analysisScope
      && (
        filterValue === 'all'
        || getRunControlModeFromMeta(run.meta) === filterValue
      )
      && (
        analysisScope !== 'single'
        || singleCaseFilter === 'all'
        || getSingleCaseIdFromMeta(run.meta) === singleCaseFilter
      )
      && (
        analysisScope !== 'multi'
        || multiScenarioFilter === 'all'
        || detectScenarioPage(run.meta) === multiScenarioFilter
      )
    ));
    const currentRunId = activeRunId || selectedRunId;
    if (nextRuns.length > 0 && !nextRuns.some((run) => run.id === currentRunId)) {
      handleAnalysisRunChange(nextRuns[0].id);
    }
  };

  const handleAnalysisScopeChange = (nextScope) => {
    setAnalysisScope(nextScope);
    let nextRuns = availableRuns.filter((run) => (
      getAnalysisScopeFromMeta(run.meta) === nextScope
      && (
        analysisControlModeFilter === 'all'
        || getRunControlModeFromMeta(run.meta) === analysisControlModeFilter
      )
      && (
        nextScope !== 'single'
        || singleCaseFilter === 'all'
        || getSingleCaseIdFromMeta(run.meta) === singleCaseFilter
      )
      && (
        nextScope !== 'multi'
        || multiScenarioFilter === 'all'
        || detectScenarioPage(run.meta) === multiScenarioFilter
      )
    ));
    if (nextScope === 'single' && nextRuns.length === 0 && singleCaseFilter !== 'all') {
      setSingleCaseFilter('all');
      nextRuns = availableRuns.filter((run) => (
        getAnalysisScopeFromMeta(run.meta) === nextScope
        && (
          analysisControlModeFilter === 'all'
          || getRunControlModeFromMeta(run.meta) === analysisControlModeFilter
        )
      ));
    }
    if (nextScope === 'multi' && nextRuns.length === 0 && multiScenarioFilter !== 'all') {
      setMultiScenarioFilter('all');
      nextRuns = availableRuns.filter((run) => (
        getAnalysisScopeFromMeta(run.meta) === nextScope
        && (
          analysisControlModeFilter === 'all'
          || getRunControlModeFromMeta(run.meta) === analysisControlModeFilter
        )
      ));
    }
    if (nextRuns.length === 0 && analysisControlModeFilter !== 'all') {
      setAnalysisControlModeFilter('all');
      nextRuns = availableRuns.filter((run) => (
        getAnalysisScopeFromMeta(run.meta) === nextScope
        && (
          nextScope !== 'single'
          || singleCaseFilter === 'all'
          || getSingleCaseIdFromMeta(run.meta) === singleCaseFilter
        )
      ));
    }
    if (nextRuns.length > 0 && !nextRuns.some((run) => run.id === activeRunId)) {
      const preferredRun = pickPreferredRun(nextRuns, {
        keepCandidate: false,
        preferredScope: nextScope,
      });
      handleAnalysisRunChange(preferredRun?.id || nextRuns[0].id);
      return;
    }
    if (nextScope === 'single' && currentPage === 'scenario') {
      setCurrentPage('daily');
    }
  };

  const handleScenarioPageChange = (pageId) => {
    setScenarioPage(pageId);
    setMultiScenarioFilter(pageId);
    const matchingRuns = availableRuns.filter((run) => (
      getAnalysisScopeFromMeta(run.meta) === 'multi'
      &&
      detectScenarioPage(run.meta) === pageId
      && (
        analysisControlModeFilter === 'all'
        || getRunControlModeFromMeta(run.meta) === analysisControlModeFilter
      )
    ));
    const currentRunStillMatches = matchingRuns.some((run) => run.id === activeRunId);
    if (!currentRunStillMatches && matchingRuns[0]) {
      handleAnalysisRunChange(matchingRuns[0].id);
    }
  };

  const detectMaxDay = async (rootPath, runMeta = null) => {
    const indexedMaxDay = Number(runMeta?._visualization_max_day);
    if (Number.isFinite(indexedMaxDay) && indexedMaxDay >= 0) {
      return indexedMaxDay;
    }
    const knownSteps = Number(runMeta?.completed_steps || runMeta?.total_steps || 0);
    if (Number.isFinite(knownSteps) && knownSteps > 0) {
      return knownSteps - 1;
    }
    const runStatus = String(runMeta?.status || '').toLowerCase();
    const plannedSteps = Number(runMeta?.planned_total_steps || 0);
    if (
      ['completed', 'stopped', 'stopped_by_guard', 'failed'].includes(runStatus)
      && Number.isFinite(plannedSteps)
      && plannedSteps > 0
    ) {
      return plannedSteps - 1;
    }

    // 以公开 exchange 快照作为轮次来源，避免把 Vite 的 HTML fallback 误判为数据文件。
    let maxDay = -1;
    for (let i = 0; i < 100; i++) {
      try {
        const data = await safeFetchJson(buildDataUrl(rootPath, `public/exchange/day${i}/exchange.json`));
        if (data?.status !== 'success' || !data?.data) {
          break;
        }
        maxDay = i;
      } catch (e) {
        break;
      }
    }
    
    // 如果没有找到任何天数，尝试从 records 目录获取。
    if (maxDay === -1) {
      try {
        const runEnterpriseId = Array.isArray(runMeta?.enterprise_ids) ? runMeta.enterprise_ids[0] : '';
        const runEnterpriseSpec = (
          runMeta?.scenario_config?.enterprise_specs?.[0]
          || runMeta?.scenario_config?.enterprise_configs?.[0]
          || {}
        );
        const fallbackEnterpriseId = (
          runEnterpriseId
          || runEnterpriseSpec.enterprise_id
          || runEnterpriseSpec.id
          || selectedEnterpriseSpecs[0]?.enterprise_id
          || selectedEnterpriseSpecs[0]?.id
          || ''
        );
        const data = await safeFetchJson(buildDataUrl(rootPath, `enterprises/${fallbackEnterpriseId}/records/`));
        if (data) {
          const days = Object.keys(data).filter(key => key.startsWith('day'));
          if (days.length > 0) {
            maxDay = Math.max(...days.map(day => parseInt(day.replace('day', ''))));
          }
        }
      } catch (e) {
        // 忽略错误
      }
    }
    
    return maxDay;
  };

  const initCompanyNetwork = () => {
    if (!chartRef.current) return;

    if (chartInstance.current) {
      chartInstance.current.dispose();
    }

    chartInstance.current = echarts.init(chartRef.current);
    const topology = buildTopologyGraph(
      activeEnterpriseSpecs,
      currentCompany,
      companyNameMap,
      dailyExchangeData
    );

    const option = {
      title: {
        text: '',
        textStyle: {
          fontSize: 14,
          fontWeight: 'bold'
        }
      },
      tooltip: {
        trigger: 'item'
      },
      grid: { containLabel: true },
      animationDurationUpdate: 1500,
      animationEasingUpdate: 'quinticInOut',
      series: [
        {
          type: 'graph',
          layout: 'none',
          roam: false,
          draggable: false,
          label: {
            show: true,
            fontSize: 12,
            fontWeight: 'bold'
          },
          edgeSymbol: ['circle', 'arrow'],
          edgeSymbolSize: [4, 10],
          edgeLabel: {
            show: true,
            fontSize: 10,
            color: '#3d4b5c',
            backgroundColor: 'rgba(255,255,255,0.82)',
            borderRadius: 4,
            padding: [2, 4],
          },
          data: topology.nodes,
          links: topology.links,
          lineStyle: {
            opacity: 0.9,
            width: 2,
            curveness: 0.08
          },
          emphasis: {
            focus: 'adjacency',
            lineStyle: {
              width: 4
            }
          }
        }
      ]
    };

    chartInstance.current.setOption(option);

    // 点击节点切换公司
    chartInstance.current.on('click', function(params) {
      if (params.dataType === 'node') {
        const company = params.data.name;
        setCurrentCompany(company);
      }
    });

    const handleResize = () => {
      chartInstance.current?.resize();
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  };

  if (loading && viewMode === 'analysis') {
    return (
      <div className="app-container">
        <div className="loading">加载数据中...</div>
      </div>
    );
  }

  if (error && viewMode === 'analysis') {
    return (
      <div className="app-container">
        <div className="error">{error}</div>
      </div>
    );
  }

  if (viewMode === 'welcome') {
    return (
      <div className="welcome-shell">
        <div className="welcome-hero">
          <div className="welcome-badge">Supply Chain Simulation</div>
          <h1>供应链模拟复盘系统</h1>
          <p>
            先选择工作区：查看已完成模拟的运营结果，或进入实验运营界面创建、启动和停止模拟任务。
          </p>
        </div>

        <section className="welcome-entry-grid">
          <button
            type="button"
            className="welcome-entry-card result"
            onClick={handleEnterAnalysis}
            disabled={loading || !selectedRunId}
          >
            <span>Results Review</span>
            <strong>运营结果展示</strong>
            <p>进入轮次观察、链路复盘、全局复盘和专项经济效应分析。适合复盘已有 run 的企业状态、交易链路和实验结论。</p>
          </button>
          <button type="button" className="welcome-entry-card operations" onClick={handleEnterExperimentOps}>
            <span>Experiment Ops</span>
            <strong>实验运营操作</strong>
            <p>进入 operations 控制台，创建 queued job、启动本地 worker、请求安全停止，并查看 job / run 状态。</p>
          </button>
        </section>

        <div className="welcome-panel">
          {loading ? (
            <div className="loading">加载任务中...</div>
          ) : error ? (
            <div className="error">{error}</div>
          ) : (
            <>
            <section className="welcome-block welcome-selection-block">
                <div className="welcome-panel-header">
                  <div>
                    <h2>模拟任务选择栏</h2>
                    <span>支持当前 workspace、operations workspace_jobs 与 simulation_runs 历史任务。</span>
                  </div>
                  <button type="button" className="welcome-refresh-btn" onClick={loadRunCatalog}>
                    刷新任务列表
                  </button>
                </div>
                <div className="welcome-filter-block">
                  <label htmlFor="scenario-filter">场景筛选</label>
                  <div className="welcome-filter-tabs">
                    <button
                      type="button"
                      className={scenarioFilter === 'all' ? 'active' : ''}
                      onClick={() => handleScenarioFilterChange('all')}
                    >
                      全部
                    </button>
                    {RUN_CATEGORY_CONFIGS.map((page) => (
                      <button
                        type="button"
                        key={page.id}
                        className={scenarioFilter === page.id ? 'active' : ''}
                        onClick={() => handleScenarioFilterChange(page.id)}
                      >
                        {page.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="welcome-selector-block">
                  <label htmlFor="run-selector">模拟任务</label>
                  <select
                    id="run-selector"
                    value={selectedRunId}
                    onChange={(event) => setSelectedRunId(event.target.value)}
                  >
                    {filteredAvailableRuns.length > 0 ? (
                      filteredAvailableRuns.map((run) => (
                        <option key={run.id} value={run.id}>
                          {run.label}
                        </option>
                      ))
                    ) : (
                      <option value={selectedRunId} disabled>
                        当前筛选条件下没有可用模拟任务
                      </option>
                    )}
                  </select>
                  {filteredAvailableRuns.length === 0 && (
                    <small className="welcome-selector-hint">当前筛选条件下没有可用模拟任务。</small>
                  )}
                </div>

                {filteredAvailableRuns.some((run) => run.experimentTag) && (
                  <div className="welcome-key-runs">
                    <div className="welcome-key-runs-header">
                      <strong>关键实验标注</strong>
                      <span>目录名在时间戳后补充了实验后缀的 run 会在这里高亮。</span>
                    </div>
                    <div className="welcome-key-run-list">
                      {filteredAvailableRuns
                        .filter((run) => run.experimentTag)
                        .map((run) => (
                          <button
                            type="button"
                            key={run.id}
                            className={`welcome-key-run ${selectedRunId === run.id ? 'active' : ''}`}
                            onClick={() => setSelectedRunId(run.id)}
                          >
                            <span>{getScenarioCategoryLabel(run.meta)}</span>
                            <strong>{formatExperimentTag(run.experimentTag)}</strong>
                            <small>{run.id}</small>
                          </button>
                        ))}
                    </div>
                  </div>
                )}

                <div className="welcome-meta-grid">
                  <div className="welcome-meta-card accent">
                    <span>识别场景</span>
                    <strong>{getScenarioCategoryLabel(selectedRunMeta)}</strong>
                  </div>
                  {selectedRunEntry?.experimentTag && (
                    <div className="welcome-meta-card key-run">
                      <span>实验标注</span>
                      <strong>{formatExperimentTag(selectedRunEntry.experimentTag)}</strong>
                    </div>
                  )}
                  <div className="welcome-meta-card">
                    <span>任务 ID</span>
                    <strong>{renderRunMetaValue(selectedRunEntry?.sourceLabel || selectedRunEntry?.resolvedRunId || selectedRunMeta?.run_id || selectedRunId)}</strong>
                  </div>
                  <div className="welcome-meta-card">
                    <span>场景 ID</span>
                    <strong>{renderRunMetaValue(selectedRunMeta?.scenario_id)}</strong>
                  </div>
                  <div className="welcome-meta-card">
                    <span>场景名称</span>
                    <strong>{renderRunMetaValue(selectedRunMeta?.scenario_meta?.name)}</strong>
                  </div>
                  <div className="welcome-meta-card">
                    <span>计划轮次</span>
                    <strong>{renderRunMetaValue(selectedRunMeta?.completed_steps || selectedRunMeta?.total_steps || selectedRunMeta?.planned_total_steps)}</strong>
                  </div>
                  <div className="welcome-meta-card">
                    <span>启动时间</span>
                    <strong>{renderRunTimeValue(selectedRunMeta?.started_at)}</strong>
                  </div>
                  <div className="welcome-meta-card">
                    <span>完成时间</span>
                    <strong>{renderRunTimeValue(selectedRunMeta?.finished_at || selectedRunMeta?.archived_at)}</strong>
                  </div>
                  <div className="welcome-meta-card">
                    <span>需求模式</span>
                    <strong>{renderRunMetaValue(getMarketModeFromMeta(selectedRunMeta))}</strong>
                  </div>
                  <div className="welcome-meta-card">
                    <span>状态</span>
                    <strong>{renderRunMetaValue(selectedRunMeta?.status)}</strong>
                  </div>
                </div>
              </section>

              <section className="welcome-block run-record-library">
                <div className="welcome-panel-header">
                  <div>
                    <h2>运行记录库</h2>
                    <span>全量记录检索、批量导出，以及按存储位置打开常用模拟文件。</span>
                  </div>
                  <div className="run-record-actions">
                    <button
                      type="button"
                      className="welcome-refresh-btn"
                      onClick={selectFilteredRunRecords}
                      disabled={filteredRunRecords.length === 0}
                    >
                      选中当前筛选
                    </button>
                    <button
                      type="button"
                      className="welcome-refresh-btn"
                      onClick={clearRunRecordSelection}
                      disabled={selectedRunRecordIds.size === 0}
                    >
                      清空选择
                    </button>
                    <button
                      type="button"
                      className="welcome-enter-btn"
                      onClick={() => downloadRunRecords(selectedRunRecords)}
                      disabled={selectedRunRecords.length === 0}
                    >
                      下载选中清单
                    </button>
                    <button
                      type="button"
                      className="welcome-enter-btn"
                      onClick={() => downloadRunArchives(selectedRunRecords)}
                      disabled={selectedRunRecords.length === 0}
                    >
                      下载选中 ZIP
                    </button>
                  </div>
                </div>

                <div className="run-record-filter-grid">
                  <label>
                    <span>范围</span>
                    <select
                      value={runRecordFilters.scope}
                      onChange={(event) => updateRunRecordFilter('scope', event.target.value)}
                    >
                      <option value="all">全部</option>
                      {ANALYSIS_SCOPE_CONFIGS.map((config) => (
                        <option key={config.id} value={config.id}>{config.label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>场景</span>
                    <select
                      value={runRecordFilters.category}
                      onChange={(event) => updateRunRecordFilter('category', event.target.value)}
                    >
                      <option value="all">全部场景</option>
                      {RUN_CATEGORY_CONFIGS.map((config) => (
                        <option key={config.id} value={config.id}>{config.label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Scenario ID</span>
                    <select
                      value={runRecordFilters.scenarioId}
                      onChange={(event) => updateRunRecordFilter('scenarioId', event.target.value)}
                    >
                      <option value="all">全部 ID</option>
                      {runRecordScenarioIds.map((scenarioId) => (
                        <option key={scenarioId} value={scenarioId}>{scenarioId}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>运行模式</span>
                    <select
                      value={runRecordFilters.mode}
                      onChange={(event) => updateRunRecordFilter('mode', event.target.value)}
                    >
                      <option value="all">全部模式</option>
                      <option value="agent">Agent Skill</option>
                      <option value="scripted">Scripted</option>
                    </select>
                  </label>
                  <label>
                    <span>开始日期</span>
                    <input
                      type="date"
                      value={runRecordFilters.dateFrom}
                      onChange={(event) => updateRunRecordFilter('dateFrom', event.target.value)}
                    />
                  </label>
                  <label>
                    <span>结束日期</span>
                    <input
                      type="date"
                      value={runRecordFilters.dateTo}
                      onChange={(event) => updateRunRecordFilter('dateTo', event.target.value)}
                    />
                  </label>
                  <button type="button" className="run-record-reset" onClick={resetRunRecordFilters}>
                    重置筛选
                  </button>
                </div>

                <div className="run-record-summary">
                  <strong>{filteredRunRecords.length}</strong>
                  <span>条匹配记录，已选 {selectedRunRecordIds.size} 条。</span>
                </div>

                <div className="run-record-table">
                  {filteredRunRecords.length > 0 ? (
                    filteredRunRecords.map((run) => {
                      const scenarioId = getScenarioIdFromMeta(run.meta) || 'unknown_scenario';
                      const fileLinks = buildRunRecordFileLinks(run);
                      return (
                        <article
                          key={run.id}
                          className={`run-record-row ${selectedRunRecordIds.has(run.id) ? 'selected' : ''} ${run.experimentTag ? 'starred' : ''}`}
                        >
                          <label className="run-record-check">
                            <input
                              type="checkbox"
                              checked={selectedRunRecordIds.has(run.id)}
                              onChange={() => toggleRunRecordSelection(run.id)}
                            />
                          </label>
                          <div className="run-record-main">
                            <div className="run-record-title">
                              <strong>{scenarioId}</strong>
                              {run.experimentTag && (
                                <span className="run-record-star">★ {formatExperimentTag(run.experimentTag)}</span>
                              )}
                              <span>{getRunControlModeLabel(run.meta)}</span>
                              <span>{getScenarioCategoryLabel(run.meta)}</span>
                              <span>{getAnalysisScopeFromMeta(run.meta) === 'multi' ? '多企业' : '单企业'}</span>
                            </div>
                            <div className="run-record-meta">
                              <span>{formatDisplayTime(getRunRecordTimeValue(run))}</span>
                              <span>{renderRunMetaValue(run.meta?.status)}</span>
                              <span>{renderRunMetaValue(run.meta?.completed_steps || run.meta?.planned_total_steps)} steps</span>
                              <code>{getRunRecordStorageLabel(run)}</code>
                            </div>
                            <div className="run-record-files">
                              {fileLinks.map((file) => (
                                <a key={file.relativePath} href={file.url} target="_blank" rel="noreferrer" download>
                                  {file.label}
                                </a>
                              ))}
                            </div>
                          </div>
                          <div className="run-record-row-actions">
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedRunId(run.id);
                                setSelectedRunMeta(run.meta || null);
                              }}
                            >
                              设为当前
                            </button>
                            <button type="button" onClick={() => downloadRunRecords([run])}>
                              下载记录
                            </button>
                            {buildRunArchiveUrl(run) && (
                              <a href={buildRunArchiveUrl(run)} download>
                                完整 ZIP
                              </a>
                            )}
                          </div>
                        </article>
                      );
                    })
                  ) : (
                    <div className="run-record-empty">当前筛选条件下没有运行记录。</div>
                  )}
                </div>
              </section>

              <section className="welcome-block welcome-config-block">
                <div className="welcome-config-header">
                  <h3>详细配置信息</h3>
                  <span>{renderRunMetaValue(selectedRunMeta?.scenario_meta?.summary)}</span>
                </div>
                <div className="welcome-config-card">
                  {renderScenarioConfigSummary(selectedRunMeta)}
                </div>
              </section>
            </>
          )}
        </div>
        <div className="welcome-sticky-action">
          <button type="button" className="welcome-enter-panel secondary" onClick={handleEnterExperimentOps}>
            <strong>进入实验运营</strong>
          </button>
          <button
            type="button"
            className="welcome-enter-panel"
            onClick={handleEnterAnalysis}
            disabled={loading || !selectedRunId}
          >
            <strong>查看运营结果</strong>
          </button>
        </div>
      </div>
    );
  }

  if (viewMode === 'experimentOps') {
    return (
      <div className="app experiment-ops-shell">
        <div className="app-header experiment-ops-app-header">
          <div className="analysis-toolbar">
            <button type="button" className="back-to-welcome-btn" onClick={handleBackToWelcome}>
              返回入口页面
            </button>
            <button type="button" className="back-to-welcome-btn alt" onClick={handleEnterAnalysis}>
              查看运营结果
            </button>
          </div>
          <h1>实验运营操作界面</h1>
          <p>
            创建、启动、停止和追踪模拟任务。该页面独立于结果复盘页面，可直接管理 operations job。
          </p>
        </div>
        <div className="main-content-wrapper">
          <ExperimentOperationsView
            currentRunId={activeRunMeta?.run_id || activeRunEntry?.id || activeRunId || selectedRunId}
            currentRunMeta={activeRunMeta || selectedRunMeta}
            currentRunSourceLabel={activeRunEntry?.sourceLabel || selectedRunEntry?.sourceLabel || dataRoot}
            availableRuns={availableRuns}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <div className="app-header">
        <div className="analysis-toolbar">
          <button type="button" className="back-to-welcome-btn" onClick={handleBackToWelcome}>
            返回入口页面
          </button>
          <button type="button" className="back-to-welcome-btn alt" onClick={handleEnterExperimentOps}>
            实验运营操作
          </button>
        </div>
        <h1>供应链企业可视化系统</h1>
        <p>
          多企业上下游关系与运营数据展示
          {activeRunMeta?.run_id ? ` · ${activeRunMeta.run_id}` : ''}
          {activeRunMeta?.scenario_meta?.name ? ` · ${activeRunMeta.scenario_meta.name}` : activeRunMeta?.scenario_id ? ` · ${activeRunMeta.scenario_id}` : ''}
        </p>
        <div className="analysis-header-controls">
          <div className="analysis-scope-switcher">
            {ANALYSIS_SCOPE_CONFIGS.map((scope) => (
              <button
                type="button"
                key={scope.id}
                className={analysisScope === scope.id ? 'active' : ''}
                onClick={() => handleAnalysisScopeChange(scope.id)}
              >
                <strong>{scope.label}</strong>
                <small>{scope.description}</small>
              </button>
            ))}
          </div>
          {analysisScope === 'single' && (
            <label className="analysis-run-switcher case-filter">
              <span>按 Case 筛选</span>
              <select
                value={singleCaseFilter}
                onChange={(event) => handleSingleCaseFilterChange(event.target.value)}
              >
                {SINGLE_CASE_FILTER_CONFIGS.map((config) => (
                  <option
                    key={config.id}
                    value={config.id}
                    disabled={config.id !== 'all' && !availableSingleCaseFilterIds.has(config.id)}
                  >
                    {config.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {analysisScope === 'multi' && (
            <label className="analysis-run-switcher case-filter">
              <span>按场景筛选</span>
              <select
                value={multiScenarioFilter}
                onChange={(event) => handleMultiScenarioFilterChange(event.target.value)}
              >
                {MULTI_SCENARIO_FILTER_CONFIGS.map((config) => (
                  <option
                    key={config.id}
                    value={config.id}
                    disabled={config.id !== 'all' && !availableMultiScenarioFilterIds.has(config.id)}
                  >
                    {config.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="analysis-run-switcher case-filter">
            <span>运行模式</span>
            <select
              value={analysisControlModeFilter}
              onChange={(event) => handleAnalysisControlModeFilterChange(event.target.value)}
            >
              {RUN_CONTROL_MODE_FILTER_CONFIGS.map((config) => (
                <option
                  key={config.id}
                  value={config.id}
                  disabled={config.id !== 'all' && !availableAnalysisControlModeIds.has(config.id)}
                >
                  {config.label}
                </option>
              ))}
            </select>
          </label>
          <label className="analysis-run-switcher">
            <span>切换模拟任务</span>
            <select
              value={analysisScopeRuns.some((run) => run.id === (activeRunId || selectedRunId)) ? (activeRunId || selectedRunId) : ''}
              onChange={(event) => handleAnalysisRunChange(event.target.value)}
              disabled={analysisScopeRuns.length === 0}
            >
              {analysisScopeRuns.length > 0 ? (
                analysisScopeRuns.map((run) => (
                  <option key={run.id} value={run.id}>
                    {formatScenarioRunOptionLabel(run)}
                  </option>
                ))
              ) : (
                <option value="">当前展示范围暂无模拟任务</option>
              )}
            </select>
          </label>
          <div className="page-switcher">
            {visibleAnalysisPages.map((page) => {
              const scenarioPageDisabled = page.id === 'scenario' && !activeRunHasScenarioAnalysis;
              return (
                <button
                  type="button"
                  key={page.id}
                  className={`page-tab ${currentPage === page.id ? 'active' : ''} ${scenarioPageDisabled ? 'disabled' : ''}`}
                  disabled={scenarioPageDisabled}
                  onClick={() => {
                    if (page.id === 'scenario') {
                      const nextScenarioPage = detectScenarioPage(activeRunMeta || selectedRunMeta);
                      if (!nextScenarioPage) {
                        return;
                      }
                      setScenarioPage(nextScenarioPage);
                    }
                    setCurrentPage(page.id);
                  }}
                >
                  {scenarioPageDisabled ? '场景分析不适用' : page.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="analysis-toggle-anchor">
          <div className="analysis-external-toggle-stack">
            <label
              className={`analysis-quantity-toggle compact ${productEquivalentMode ? 'active' : ''}`}
            >
              <input
                type="checkbox"
                checked={productEquivalentMode}
                onChange={(event) => setProductEquivalentMode(event.target.checked)}
              />
              <span className="analysis-quantity-copy">
                <strong>原料折合成品</strong>
              </span>
              <span className="analysis-quantity-switch" aria-hidden="true">
                <span className="analysis-quantity-switch-knob" />
              </span>
            </label>

            <label
              className={`analysis-quantity-toggle medium ${includeUpstreamExternalSupplierMode ? 'active' : ''}`}
            >
              <input
                type="checkbox"
                checked={includeUpstreamExternalSupplierMode}
                onChange={(event) => setIncludeUpstreamExternalSupplierMode(event.target.checked)}
              />
              <span className="analysis-quantity-copy">
                <strong>上游外部供应商</strong>
              </span>
              <span className="analysis-quantity-switch" aria-hidden="true">
                <span className="analysis-quantity-switch-knob" />
              </span>
            </label>

            <label
              className={`analysis-quantity-toggle wide ${includeDownstreamExternalMarketMode ? 'active' : ''}`}
            >
              <input
                type="checkbox"
                checked={includeDownstreamExternalMarketMode}
                onChange={(event) => setIncludeDownstreamExternalMarketMode(event.target.checked)}
              />
              <span className="analysis-quantity-copy">
                <strong>下游外部市场</strong>
              </span>
              <span className="analysis-quantity-switch" aria-hidden="true">
                <span className="analysis-quantity-switch-knob" />
              </span>
            </label>
          </div>
        </div>
      </div>

      <div className="main-content-wrapper">
        {currentPage === 'daily' ? (
          <div className="daily-page">
            {analysisScope === 'single' ? (
              <>
                <RoundEnterpriseBoard
                  enterpriseSpecs={activeEnterpriseSpecs}
                  currentCompany={currentCompany}
                  currentDay={currentDay}
                  dataRoot={dataRoot}
                  onCompanyChange={setCurrentCompany}
                  companyNameMap={companyNameMap}
                  includeSingleCaseSeedActions
                />

                <div className="single-enterprise-workbench">
                  <aside className="single-workbench-left">
                    <div className="column-section compact-section">
                      <CompanySelector
                        companies={companies}
                        companyNameMap={companyNameMap}
                        currentCompany={currentCompany}
                        onCompanyChange={setCurrentCompany}
                      />
                    </div>

                    <div className="column-section compact-section">
                      <h3>企业基本信息</h3>
                      <CompanyInfo company={currentCompany} day={currentDay} dataRoot={dataRoot} />
                    </div>

                    <div className="column-section compact-section ceo-compact-section">
                      <h3>CEO分析</h3>
                      <CEOAnalysis company={currentCompany} day={currentDay} dataRoot={dataRoot} />
                    </div>

                    <SingleEnterpriseActionList
                      company={currentCompany}
                      currentDay={currentDay}
                      dataRoot={dataRoot}
                    />
                  </aside>

                  <SingleEnterprisePerformanceView
                    availableDays={availableDays}
                    currentDay={currentDay}
                    company={currentCompany}
                    dataRoot={dataRoot}
                    viewMode={singlePerformanceMode}
                    onViewModeChange={(nextMode) => {
                      setSinglePerformanceMode(nextMode);
                      if (nextMode === 'trend' && availableDays.length > 0) {
                        setCurrentDay(availableDays[availableDays.length - 1]);
                      }
                    }}
                  />
                </div>
              </>
            ) : (
              <>
                <div className="daily-hero-layout">
                  <aside className="daily-side-panel daily-left-panel">
                    <div className="column-section compact-section">
                      <CompanySelector
                        companies={companies}
                        companyNameMap={companyNameMap}
                        currentCompany={currentCompany}
                        onCompanyChange={setCurrentCompany}
                      />
                    </div>

                    <div className="column-section compact-section">
                      <h3>企业基本信息</h3>
                      <CompanyInfo company={currentCompany} day={currentDay} dataRoot={dataRoot} />
                    </div>

                    <div className="column-section compact-section ceo-compact-section">
                      <h3>CEO分析</h3>
                      <CEOAnalysis company={currentCompany} day={currentDay} dataRoot={dataRoot} />
                    </div>
                  </aside>

                  <section className="daily-topology-section">
                    <div className="daily-topology-header">
                      <div>
                        <strong>产业链空间结构</strong>
                      </div>
                    </div>
                    <div className="chart-container daily-topology-chart" ref={chartRef}></div>
                  </section>

                  <aside className="daily-side-panel daily-right-panel">
                    <ExchangeEnterprisePanel
                      day={currentDay}
                      coreCompany={currentCompany}
                      dataRoot={dataRoot}
                    />
                  </aside>
                </div>

                <RoundEnterpriseBoard
                  enterpriseSpecs={activeEnterpriseSpecs}
                  currentCompany={currentCompany}
                  currentDay={currentDay}
                  dataRoot={dataRoot}
                  onCompanyChange={setCurrentCompany}
                  companyNameMap={companyNameMap}
                />

                <div className="daily-lower-layout">
                  <div className="column-section">
                    <h3>交易所信息</h3>
                    <ExchangeInfo
                      day={currentDay}
                      dataRoot={dataRoot}
                      quantityView={quantityView}
                      selectedExchangeId={selectedExchangeId}
                      onSelectExchange={setSelectedExchangeId}
                    />
                  </div>
                </div>
              </>
            )}

            {!(analysisScope === 'single' && singlePerformanceMode === 'trend') && (
              <div className="fixed-day-selector">
                <DaySelector
                  availableDays={availableDays}
                  currentDay={currentDay}
                  onDayChange={setCurrentDay}
                />
              </div>
            )}
          </div>
        ) : currentPage === 'propagation' ? (
          <div className="propagation-page">
            <div className="flow-production-band">
              <div className="column-section">
                <h3>上下游流通与生产</h3>
                <FlowProductionView
                  availableDays={availableDays}
                  currentDay={currentDay}
                  dataRoot={dataRoot}
                  quantityView={quantityView}
                  enterpriseSpecs={activeEnterpriseSpecs}
                  includeUpstreamExternalSupplierMode={includeUpstreamExternalSupplierMode}
                  includeDownstreamExternalMarketMode={includeDownstreamExternalMarketMode}
                />
              </div>
            </div>

            <div className="column-section">
              <h3>运行概览</h3>
              <RunSummary
                availableDays={availableDays}
                dataRoot={dataRoot}
                quantityView={quantityView}
                includeUpstreamExternalSupplierMode={includeUpstreamExternalSupplierMode}
                includeDownstreamExternalMarketMode={includeDownstreamExternalMarketMode}
                enterpriseSpecs={activeEnterpriseSpecs}
              />
            </div>

            <div className="demand-propagation-band">
              <div className="column-section">
                <DemandPropagationView
                  availableDays={availableDays}
                  currentDay={currentDay}
                  dataRoot={dataRoot}
                  quantityView={quantityView}
                  enterpriseSpecs={activeEnterpriseSpecs}
                />
              </div>
            </div>
          </div>
        ) : currentPage === 'scenario' ? (
          <div className="scenario-analysis-page">
            <section className="scenario-analysis-control">
              <div className="scenario-analysis-copy">
                <span>Scenario Analysis</span>
                <strong>{getScenarioPageConfig(scenarioPage).label}</strong>
                <small>{getScenarioPageConfig(scenarioPage).description}</small>
              </div>
              <div className="scenario-inner-tabs">
                {SCENARIO_ANALYSIS_PAGES.map((page) => {
                  const isDetected = detectScenarioPage(activeRunMeta || selectedRunMeta) === page.id;
                  return (
                    <button
                      type="button"
                      key={page.id}
                      className={`${scenarioPage === page.id ? 'active' : ''} ${isDetected ? 'detected' : ''}`}
                      onClick={() => handleScenarioPageChange(page.id)}
                    >
                      <strong>{page.label}</strong>
                      <small>{isDetected ? '当前数据' : page.description}</small>
                    </button>
                  );
                })}
              </div>
            </section>

            {scenarioPage === 'evolution' ? (
              <EvolutionExperimentView
                availableDays={availableDays}
                dataRoot={dataRoot}
                enterpriseSpecs={activeEnterpriseSpecs}
              />
            ) : scenarioPage === 'bullwhip' ? (
              <BullwhipEffectView
                availableDays={availableDays}
                dataRoot={dataRoot}
                quantityView={quantityView}
                enterpriseSpecs={activeEnterpriseSpecs}
                includeUpstreamExternalSupplierMode={includeUpstreamExternalSupplierMode}
                includeDownstreamExternalMarketMode={includeDownstreamExternalMarketMode}
                currentRunId={activeRunMeta?.run_id || activeRunEntry?.id || activeRunId}
                currentRunSourceLabel={activeRunEntry?.sourceLabel || dataRoot}
              />
            ) : scenarioPage === 'cobweb' ? (
              <CobwebModelValidationView
                availableDays={availableDays}
                dataRoot={dataRoot}
                enterpriseSpecs={activeEnterpriseSpecs}
                currentRunId={activeRunMeta?.run_id || activeRunEntry?.id || activeRunId}
                currentRunSourceLabel={activeRunEntry?.sourceLabel || dataRoot}
              />
            ) : scenarioPage === 'commons' ? (
              <CommonsTragedyView
                availableDays={availableDays}
                dataRoot={dataRoot}
                enterpriseSpecs={activeEnterpriseSpecs}
                currentRunId={activeRunMeta?.run_id || activeRunEntry?.id || activeRunId}
                currentRunSourceLabel={activeRunEntry?.sourceLabel || dataRoot}
              />
            ) : (
              <HerdingEffectView
                availableDays={availableDays}
                dataRoot={dataRoot}
                enterpriseSpecs={activeEnterpriseSpecs}
                currentRunId={activeRunMeta?.run_id || activeRunEntry?.id || activeRunId}
                currentRunSourceLabel={activeRunEntry?.sourceLabel || dataRoot}
              />
            )}
          </div>
        ) : currentPage === 'operations' ? (
          <OperationalReviewView
            availableDays={availableDays}
            dataRoot={dataRoot}
            quantityView={quantityView}
            enterpriseSpecs={activeEnterpriseSpecs}
          />
        ) : (
          <GlobalSimulationView
            availableDays={availableDays}
            dataRoot={dataRoot}
            quantityView={quantityView}
            enterpriseSpecs={activeEnterpriseSpecs}
            includeUpstreamExternalSupplierMode={includeUpstreamExternalSupplierMode}
            includeDownstreamExternalMarketMode={includeDownstreamExternalMarketMode}
          />
        )}
      </div>
    </div>
  );
}

export default App;
