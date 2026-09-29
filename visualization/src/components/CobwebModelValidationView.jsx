import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';

const CHART_COLORS = {
  price: '#255f63',
  supply: '#d99735',
  plan: '#4f9d69',
  deviation: '#c76538',
  tolerance: '#7c8b7b',
  inventory: '#2d6cdf',
  backlog: '#c04949',
  fillRate: '#2b9f8a',
  theory: '#9f7aea',
  agent: '#2f7d5b',
};

const ACTION_REASON_NOISE_TERMS = [
  'recommended_plan_quantity',
  'recommended_daily_capacity',
  '推荐量',
  '恢复推荐',
  'recovery_guard recommendation',
  'recovery_guard 推荐',
  '允许偏差',
  '偏差不超过',
  '±2',
  'affordable_recovery_candidates',
  'should_recover_now',
];

const toFiniteNumber = (value, fallback = null) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const formatNumber = (value, maximumFractionDigits = 2) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits }).format(numeric);
};

const formatPercent = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  return `${formatNumber(numeric * 100, 1)}%`;
};

const formatSigned = (value, maximumFractionDigits = 2) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  const absText = formatNumber(Math.abs(numeric), maximumFractionDigits);
  return numeric > 0 ? `+${absText}` : numeric < 0 ? `-${absText}` : '0';
};

const truncateText = (value, maxLength = 96) => {
  const text = String(value || '');
  if (text.length <= maxLength) {
    return text || '-';
  }
  return `${text.slice(0, maxLength)}...`;
};

const extractCobwebHistory = (payload) => {
  const history = (
    payload?.data?.history
    || payload?.history
    || payload?.data?.cobweb_history
    || payload?.cobweb_history
    || payload?.simulation_context?.cobweb_history
    || []
  );
  return Array.isArray(history) ? history : [];
};

const getDepartmentSelfState = (payload) => payload?.self_state || payload?.data?.self_state || {};

const getInventoryQuantity = (inventoryPayload, productId = 'beer') => {
  const selfState = getDepartmentSelfState(inventoryPayload);
  const items = Array.isArray(selfState.inventory_items) ? selfState.inventory_items : [];
  const item = items.find((entry) => String(entry?.item_id).toLowerCase() === String(productId).toLowerCase());
  return toFiniteNumber(item?.su_quantity, toFiniteNumber(item?.quantity));
};

const getPlanAction = (actionsPayload) => {
  const actions = Array.isArray(actionsPayload) ? actionsPayload : actionsPayload?.actions || [];
  return actions.find((entry) => entry?.action?.action_name === 'create_production_plan')
    || actions.find((entry) => entry?.action?.action_name && entry?.action?.action_name !== 'pass')
    || null;
};

const buildEquilibriumFromConfig = (cobwebConfig) => {
  const demandIntercept = toFiniteNumber(cobwebConfig?.demand_intercept);
  const demandSlope = toFiniteNumber(cobwebConfig?.demand_slope);
  const supplyIntercept = toFiniteNumber(cobwebConfig?.supply_intercept);
  const supplySlope = toFiniteNumber(cobwebConfig?.supply_slope);

  if (
    demandIntercept === null
    || demandSlope === null
    || supplyIntercept === null
    || supplySlope === null
    || demandSlope + supplySlope === 0
  ) {
    return { price: null, quantity: null };
  }

  const price = (demandIntercept - supplyIntercept) / (demandSlope + supplySlope);
  const quantity = supplyIntercept + supplySlope * price;
  return { price, quantity };
};

const getProducerSpec = (enterpriseSpecs = []) => (
  enterpriseSpecs.find((spec) => (spec?.enabled_functions || []).includes('production'))
  || enterpriseSpecs[0]
  || null
);

const mean = (values) => {
  const finite = values.filter((value) => Number.isFinite(Number(value)));
  if (finite.length === 0) {
    return null;
  }
  return finite.reduce((total, value) => total + Number(value), 0) / finite.length;
};

const getScenarioType = (runMeta) => {
  const scenarioId = String(runMeta?.scenario_id || '').toLowerCase();
  const stabilityLabel = String(
    runMeta?.cobweb_config?.stability_label
    || runMeta?.scenario_config?.simulation?.cobweb_config?.stability_label
    || ''
  ).toLowerCase();
  if (scenarioId.includes('divergent') || stabilityLabel === 'divergent') {
    return 'divergent';
  }
  if (scenarioId.includes('neutral') || stabilityLabel === 'neutral') {
    return 'neutral';
  }
  if (scenarioId.includes('convergent') || stabilityLabel === 'convergent') {
    return 'convergent';
  }
  return 'unknown';
};

const getScenarioExpectation = (scenarioType) => {
  if (scenarioType === 'convergent') {
    return {
      title: '收敛型：偏离应逐步缩小',
      detail: '供给曲线斜率小于需求曲线斜率，价格和供给应围绕均衡点逐步收敛。',
    };
  }
  if (scenarioType === 'neutral') {
    return {
      title: '等幅型：教材预期为循环',
      detail: '供需斜率接近，机械供给函数下会出现等幅震荡；若 Agent 主动稳到均衡，说明企业理性产生阻尼。',
    };
  }
  if (scenarioType === 'divergent') {
    return {
      title: '发散型：偏离应放大或形成强震荡',
      detail: '供给曲线斜率大于需求曲线斜率，理论上会放大偏离；企业约束可能把它压成有界强震荡。',
    };
  }
  return {
    title: '蛛网场景',
    detail: '根据价格-滞后供给反馈判断当前运行是否呈现蛛网效应。',
  };
};

const getCobwebControllerMeta = (runMeta) => {
  const cobwebConfig = runMeta?.cobweb_config || runMeta?.scenario_config?.simulation?.cobweb_config || {};
  const scripted = cobwebConfig.production_response_mode === 'scripted_formula'
    || String(runMeta?.scenario_id || '').endsWith('_scripted');
  return scripted
    ? {
      mode: 'scripted',
      label: 'Scripted',
      expectedSupplySource: 'scripted_production_plan_created',
      inputFilterRequired: false,
    }
    : {
      mode: 'agent',
      label: 'Agent',
      expectedSupplySource: 'agent_production_plan_created',
      inputFilterRequired: true,
    };
};

const buildSummary = (rows, runMeta, producerId) => {
  const scenarioType = getScenarioType(runMeta);
  const scenarioExpectation = getScenarioExpectation(scenarioType);
  const controller = getCobwebControllerMeta(runMeta);
  const planRows = rows.filter((row) => row.planQuantity !== null);
  const latestRow = rows[rows.length - 1] || {};
  const equilibriumPrice = rows.find((row) => row.equilibriumPrice !== null)?.equilibriumPrice ?? null;
  const equilibriumQuantity = rows.find((row) => row.equilibriumQuantity !== null)?.equilibriumQuantity ?? null;
  const finalPriceGap = latestRow.price !== null && equilibriumPrice !== null
    ? latestRow.price - equilibriumPrice
    : null;
  const finalQuantityGap = latestRow.marketSupply !== null && equilibriumQuantity !== null
    ? latestRow.marketSupply - equilibriumQuantity
    : null;
  const priceDeviationRows = rows
    .map((row) => row.priceDeviationAbs)
    .filter((value) => Number.isFinite(Number(value)));
  const postDay0PriceDeviation = rows
    .filter((row) => row.day !== 0)
    .map((row) => row.priceDeviationAbs)
    .filter((value) => Number.isFinite(Number(value)));
  const splitIndex = Math.max(1, Math.floor(postDay0PriceDeviation.length / 2));
  const firstHalfDeviation = postDay0PriceDeviation.slice(0, splitIndex);
  const secondHalfDeviation = postDay0PriceDeviation.slice(splitIndex);
  const firstHalfMeanAbsPrice = mean(firstHalfDeviation);
  const secondHalfMeanAbsPrice = mean(secondHalfDeviation);
  const lastSixMeanAbsPrice = mean(priceDeviationRows.slice(-6));
  const normalizationAppliedCount = rows.filter((row) => row.targetNormalizationApplied).length;
  const controllerSupplyCount = rows.filter((row) => (
    row.marketSupplySource === controller.expectedSupplySource
  )).length;
  const fallbackSupplyCount = rows.filter((row) => (
    row.marketSupplySource && row.marketSupplySource !== controller.expectedSupplySource
  )).length;
  const agentInputFilterCount = rows.filter((row) => row.agentInputFilterApplied).length;
  const residualNoiseCount = rows.filter((row) => row.actionReasonNoiseTerms.length > 0).length;
  const directionRows = planRows.filter((row) => row.directionOk !== null);
  const directionOkCount = directionRows.filter((row) => row.directionOk).length;
  const pricesPostDay0 = rows.filter((row) => row.day !== 0).map((row) => row.price).filter((value) => value !== null);
  const suppliesPostDay0 = rows.filter((row) => row.day !== 0).map((row) => row.marketSupply).filter((value) => value !== null);
  const priceRangePostDay0 = pricesPostDay0.length > 0 ? Math.max(...pricesPostDay0) - Math.min(...pricesPostDay0) : null;
  const supplyRangePostDay0 = suppliesPostDay0.length > 0 ? Math.max(...suppliesPostDay0) - Math.min(...suppliesPostDay0) : null;
  const engineeringReady = rows.length > 0
    && controllerSupplyCount >= Math.max(0, rows.length - 1)
    && planRows.length === rows.length
    && (!controller.inputFilterRequired || agentInputFilterCount === rows.length);
  const agentAligned = directionRows.length > 0 && directionOkCount === directionRows.length && residualNoiseCount === 0;

  let effectExplanation = `当前运行已加载蛛网数据，但还需要结合价格偏离和${controller.label}行为判断。`;
  if (scenarioType === 'convergent') {
    const converged = (
      secondHalfMeanAbsPrice !== null
      && firstHalfMeanAbsPrice !== null
      && secondHalfMeanAbsPrice < firstHalfMeanAbsPrice
      && lastSixMeanAbsPrice !== null
      && lastSixMeanAbsPrice <= Math.max(4, firstHalfMeanAbsPrice * 0.45)
    );
    effectExplanation = converged
      ? '后半段价格偏离显著低于前半段，且末段围绕均衡小幅波动。'
      : '价格尚未稳定靠近均衡，建议延长轮次或检查生产理由。';
  } else if (scenarioType === 'neutral') {
    const stabilized = lastSixMeanAbsPrice !== null && lastSixMeanAbsPrice <= 1;
    effectExplanation = stabilized
      ? (controller.mode === 'scripted'
        ? '公式轨迹意外稳定到均衡附近，需要检查供给来源和递推参数。'
        : '教材式等幅冲击被 Agent 快速吸收到均衡点，说明企业理性产生阻尼。')
      : '仍存在等幅或多状态循环，可继续观察振幅是否稳定。';
  } else if (scenarioType === 'divergent') {
    const highVolatility = (
      priceRangePostDay0 !== null
      && lastSixMeanAbsPrice !== null
      && priceRangePostDay0 >= 100
      && lastSixMeanAbsPrice >= 20
    );
    effectExplanation = highVolatility
      ? (controller.mode === 'scripted'
        ? '发散参数与价格/数量边界共同形成了有界强震荡。'
        : '发散参数制造了显著价格波动，但 Agent 经营约束把轨迹压成有界震荡。')
      : (controller.mode === 'scripted'
        ? '公式基线的波动不够强，需要检查脚本供给来源、递推参数或边界配置。'
        : '价格波动不够强，可能被 Agent 平滑或边界配置抑制。');
  }

  return {
    runId: runMeta?.run_id || '-',
    scenarioName: runMeta?.scenario_meta?.name || runMeta?.scenario_id || '-',
    scenarioType,
    scenarioExpectation,
    producerId,
    planCount: planRows.length,
    normalizationAppliedCount,
    controllerMode: controller.mode,
    controllerLabel: controller.label,
    expectedSupplySource: controller.expectedSupplySource,
    controllerSupplyCount,
    fallbackSupplyCount,
    agentInputFilterCount,
    directionOkCount,
    directionTotal: directionRows.length,
    residualNoiseCount,
    finalPriceGap,
    finalQuantityGap,
    firstHalfMeanAbsPrice,
    secondHalfMeanAbsPrice,
    lastSixMeanAbsPrice,
    priceRangePostDay0,
    supplyRangePostDay0,
    latestRow,
    equilibriumPrice,
    equilibriumQuantity,
    engineeringReady,
    agentAligned,
    effectExplanation,
  };
};

function CobwebModelValidationView({
  availableDays = [],
  dataRoot,
  enterpriseSpecs = [],
  currentRunId,
  currentRunSourceLabel,
}) {
  const convergenceRef = useRef(null);
  const productionRef = useRef(null);
  const deviationRef = useRef(null);
  const phaseRef = useRef(null);
  const operationsRef = useRef(null);
  const producerSpec = useMemo(() => getProducerSpec(enterpriseSpecs), [enterpriseSpecs]);
  const producerId = producerSpec?.enterprise_id || producerSpec?.id || 'Manufacturer';
  const [showCobwebDetails, setShowCobwebDetails] = useState(false);
  const [viewState, setViewState] = useState({
    loading: true,
    error: null,
    rows: [],
    runMeta: null,
  });

  useEffect(() => {
    let cancelled = false;

    const loadData = async () => {
      try {
        setViewState((prev) => ({ ...prev, loading: true, error: null }));
        const days = [...availableDays]
          .map((day) => Number(day))
          .filter((day) => Number.isFinite(day))
          .sort((left, right) => left - right);

        if (days.length === 0) {
          setViewState({ loading: false, error: null, rows: [], runMeta: null });
          return;
        }

        const runMeta = await safeFetchJson(buildDataUrl(dataRoot, 'run_meta.json'));
        const cobwebConfig = runMeta?.scenario_config?.simulation?.cobweb_config || {};
        const fallbackEquilibrium = buildEquilibriumFromConfig(cobwebConfig);
        const latestDay = days[days.length - 1];
        const demandPayload = await safeFetchJson(buildDataUrl(dataRoot, `public/exchange/day${latestDay}/external_demand.json`));
        const demandHistory = extractCobwebHistory(demandPayload);
        const demandByRound = new Map(demandHistory.map((entry) => [Number(entry?.round), entry]));

        const rows = await Promise.all(days.map(async (day) => {
          const [
            productionPayload,
            actionsPayload,
            inventoryPayload,
            salesPayload,
          ] = await Promise.all([
            safeFetchJson(buildDataUrl(dataRoot, `enterprises/${producerId}/department/production/day${day}/production.json`)),
            safeFetchJson(buildDataUrl(dataRoot, `enterprises/${producerId}/department/production/day${day}/production_action.json`)),
            safeFetchJson(buildDataUrl(dataRoot, `enterprises/${producerId}/department/inventory/day${day}/inventory.json`)),
            safeFetchJson(buildDataUrl(dataRoot, `enterprises/${producerId}/department/sales/day${day}/sales.json`)),
          ]);

          const productionSelfState = getDepartmentSelfState(productionPayload);
          const signal = productionSelfState?.cobweb_decision_signal || productionPayload?.cobweb_decision_signal || {};
          const productionHistory = extractCobwebHistory(productionPayload);
          const marketRecord = demandByRound.get(day)
            || productionHistory.find((entry) => Number(entry?.round) === day)
            || productionHistory[productionHistory.length - 1]
            || null;
          const planAction = getPlanAction(actionsPayload);
          const planQuantity = toFiniteNumber(planAction?.action?.action_param?.quantity);
          const theoreticalSupply = toFiniteNumber(
            marketRecord?.theoretical_planned_supply_quantity,
            toFiniteNumber(signal?.theoretical_supply_quantity)
          );
          const actualSupply = toFiniteNumber(
            marketRecord?.actual_supply_quantity,
            toFiniteNumber(signal?.actual_supply_quantity)
          );
          const marketSupply = toFiniteNumber(
            marketRecord?.market_supply_quantity,
            toFiniteNumber(marketRecord?.planned_supply_quantity, toFiniteNumber(signal?.market_supply_quantity))
          );
          const salesSelfState = getDepartmentSelfState(salesPayload);
          const serviceSummary = salesSelfState?.service_level_summary || {};
          const equilibriumPrice = toFiniteNumber(signal?.equilibrium_price, fallbackEquilibrium.price);
          const equilibriumQuantity = toFiniteNumber(signal?.equilibrium_quantity, fallbackEquilibrium.quantity);
          const price = toFiniteNumber(marketRecord?.unit_price, toFiniteNumber(signal?.current_market_price));
          const direction = signal?.suggested_supply_direction || '';
          const actionReason = planAction?.action_reason || '';
          const actionReasonNoiseTerms = ACTION_REASON_NOISE_TERMS.filter((term) => actionReason.includes(term));

          return {
            day,
            price,
            marketSupply,
            plannedSupply: marketSupply,
            marketDemandQuantity: toFiniteNumber(marketRecord?.quantity),
            actualSupply,
            theoreticalSupply,
            marketSupplySource: marketRecord?.market_supply_source || signal?.market_supply_source || '',
            planQuantity,
            planToMarketGap: planQuantity !== null && marketSupply !== null ? planQuantity - marketSupply : null,
            planToTheoryGap: planQuantity !== null && theoreticalSupply !== null ? planQuantity - theoreticalSupply : null,
            priceDeviation: price !== null && equilibriumPrice !== null ? price - equilibriumPrice : null,
            priceDeviationAbs: price !== null && equilibriumPrice !== null ? Math.abs(price - equilibriumPrice) : null,
            supplyDeviation: marketSupply !== null && equilibriumQuantity !== null ? marketSupply - equilibriumQuantity : null,
            supplyDeviationAbs: marketSupply !== null && equilibriumQuantity !== null ? Math.abs(marketSupply - equilibriumQuantity) : null,
            actionName: planAction?.action?.action_name || '无生产计划动作',
            actionReason,
            actionReasonNoiseTerms,
            direction,
            directionOk: null,
            equilibriumPrice,
            equilibriumQuantity,
            target: productionPayload?.target || '',
            rawTarget: productionPayload?.raw_target || '',
            targetNormalizationApplied: Boolean(productionPayload?.target_normalization?.applied),
            targetNormalizationSource: productionPayload?.target_normalization?.source || '',
            targetPriority: productionPayload?.target_normalization?.non_cobweb_target_priority || '',
            agentInputFilterApplied: Boolean(productionSelfState?.agent_input_filter?.applied),
            inventoryQuantity: getInventoryQuantity(inventoryPayload, signal?.product_id || cobwebConfig?.product_id || 'beer'),
            fillRate: toFiniteNumber(serviceSummary?.fill_rate),
            backlogQuantity: toFiniteNumber(serviceSummary?.confirmed_order_backlog_quantity, toFiniteNumber(serviceSummary?.backlog_quantity)),
            totalProduction: toFiniteNumber(productionSelfState?.production_metrics?.total_production),
          };
        }));
        let previousPlanQuantity = null;
        const rowsWithDirection = rows.map((row) => {
          let directionOk = null;
          if (row.planQuantity !== null && previousPlanQuantity !== null) {
            if (row.priceDeviation > 0) {
              directionOk = row.planQuantity >= previousPlanQuantity;
            } else if (row.priceDeviation < 0) {
              directionOk = row.planQuantity <= previousPlanQuantity;
            } else {
              directionOk = true;
            }
          } else if (row.planQuantity !== null) {
            directionOk = true;
          }
          if (row.planQuantity !== null) {
            previousPlanQuantity = row.planQuantity;
          }
          return { ...row, directionOk };
        });

        if (!cancelled) {
          setViewState({
            loading: false,
            error: null,
            rows: rowsWithDirection.filter((row) => (
              row.price !== null
              || row.marketSupply !== null
              || row.planQuantity !== null
              || row.theoreticalSupply !== null
            )),
            runMeta,
          });
        }
      } catch (error) {
        if (!cancelled) {
          setViewState({
            loading: false,
            error: `加载蛛网模型验证数据失败: ${error.message}`,
            rows: [],
            runMeta: null,
          });
        }
      }
    };

    loadData();
    return () => {
      cancelled = true;
    };
  }, [availableDays, dataRoot, producerId]);

  const summary = useMemo(
    () => buildSummary(viewState.rows, viewState.runMeta, producerId),
    [viewState.rows, viewState.runMeta, producerId]
  );

  useEffect(() => {
    const rows = viewState.rows;
    if (rows.length === 0) {
      return undefined;
    }

    const days = rows.map((row) => `D${row.day}`);
    const finitePriceDeviations = rows
      .map((row) => row.priceDeviationAbs)
      .filter((value) => Number.isFinite(Number(value)));
    const instances = [
      {
        ref: convergenceRef,
        option: {
          color: [CHART_COLORS.price, CHART_COLORS.supply, CHART_COLORS.agent, '#8aa09a', '#cbb07a'],
          tooltip: { trigger: 'axis' },
          legend: { top: 0 },
          grid: { left: 52, right: 56, top: 48, bottom: 36 },
          xAxis: { type: 'category', data: days, boundaryGap: false },
          yAxis: [
            { type: 'value', name: '价格', scale: true },
            { type: 'value', name: '供给量', scale: true },
          ],
          series: [
            {
              name: '市场价格',
              type: 'line',
              smooth: true,
              symbolSize: 7,
              data: rows.map((row) => row.price),
            },
            {
              name: '计划供给',
              type: 'line',
              yAxisIndex: 1,
              smooth: true,
              symbolSize: 7,
              data: rows.map((row) => row.marketSupply),
            },
            {
              name: `${summary.controllerLabel}生产计划`,
              type: 'bar',
              yAxisIndex: 1,
              barMaxWidth: 18,
              data: rows.map((row) => row.planQuantity),
            },
            {
              name: '均衡价格',
              type: 'line',
              symbol: 'none',
              lineStyle: { type: 'dashed', width: 2 },
              data: rows.map((row) => row.equilibriumPrice),
            },
            {
              name: '均衡数量',
              type: 'line',
              yAxisIndex: 1,
              symbol: 'none',
              lineStyle: { type: 'dashed', width: 2 },
              data: rows.map((row) => row.equilibriumQuantity),
            },
          ],
        },
      },
      {
        ref: productionRef,
        option: {
          color: [CHART_COLORS.plan, CHART_COLORS.supply, CHART_COLORS.theory],
          tooltip: { trigger: 'axis' },
          legend: { top: 0 },
          grid: { left: 48, right: 18, top: 48, bottom: 36 },
          xAxis: { type: 'category', data: days },
          yAxis: { type: 'value', name: '数量', scale: true },
          series: [
            {
              name: `${summary.controllerLabel}生产计划`,
              type: 'line',
              smooth: true,
              symbolSize: 7,
              data: rows.map((row) => row.planQuantity),
            },
            {
              name: '市场采用供给',
              type: 'line',
              smooth: true,
              symbolSize: 7,
              data: rows.map((row) => row.marketSupply),
            },
            {
              name: '理论参考供给',
              type: 'line',
              smooth: true,
              symbolSize: 5,
              lineStyle: { type: 'dotted' },
              data: rows.map((row) => row.theoreticalSupply),
            },
          ],
        },
      },
      {
        ref: deviationRef,
        option: {
          color: [CHART_COLORS.deviation, CHART_COLORS.supply],
          tooltip: { trigger: 'axis' },
          legend: { top: 0 },
          grid: { left: 56, right: 52, top: 48, bottom: 36 },
          xAxis: { type: 'category', data: days },
          yAxis: [
            { type: 'value', name: '价格偏离', scale: true },
            { type: 'value', name: '供给偏离', scale: true },
          ],
          series: [
            {
              name: '|价格 - 均衡价|',
              type: 'bar',
              barMaxWidth: 22,
              data: rows.map((row) => row.priceDeviationAbs),
              itemStyle: { color: CHART_COLORS.deviation },
            },
            {
              name: '|供给 - 均衡量|',
              type: 'line',
              yAxisIndex: 1,
              smooth: true,
              symbolSize: 7,
              data: rows.map((row) => row.supplyDeviationAbs),
              itemStyle: { color: CHART_COLORS.supply },
              markLine: {
                symbol: 'none',
                lineStyle: { type: 'dashed', color: '#91a39a' },
                data: finitePriceDeviations.length > 0 ? [{ yAxis: 0, name: '均衡' }] : [],
              },
            },
          ],
        },
      },
      {
        ref: phaseRef,
        option: {
          color: [CHART_COLORS.price, CHART_COLORS.supply],
          tooltip: {
            trigger: 'item',
            formatter: (params) => {
              const row = rows[params.dataIndex];
              return `D${row?.day}<br/>供给量: ${formatNumber(row?.marketSupply)}<br/>价格: ${formatNumber(row?.price)}<br/>来源: ${row?.marketSupplySource || '-'}`;
            },
          },
          grid: { left: 56, right: 24, top: 24, bottom: 44 },
          xAxis: { type: 'value', name: '市场供给量', scale: true },
          yAxis: { type: 'value', name: '价格', scale: true },
          series: [
            {
              name: '蛛网轨迹',
              type: 'line',
              smooth: false,
              symbolSize: 9,
              data: rows.map((row) => [row.marketSupply, row.price]),
              markPoint: {
                symbolSize: 58,
                data: summary.equilibriumQuantity !== null && summary.equilibriumPrice !== null
                  ? [{ name: '均衡点', coord: [summary.equilibriumQuantity, summary.equilibriumPrice] }]
                  : [],
              },
            },
          ],
        },
      },
      {
        ref: operationsRef,
        option: {
          color: [CHART_COLORS.inventory, CHART_COLORS.backlog, CHART_COLORS.fillRate],
          tooltip: { trigger: 'axis' },
          legend: { top: 0 },
          grid: { left: 54, right: 52, top: 48, bottom: 36 },
          xAxis: { type: 'category', data: days },
          yAxis: [
            { type: 'value', name: '数量', scale: true },
            { type: 'value', name: '履约率', min: 0, max: 1, axisLabel: { formatter: '{value}' } },
          ],
          series: [
            {
              name: '成品库存',
              type: 'line',
              smooth: true,
              data: rows.map((row) => row.inventoryQuantity),
            },
            {
              name: '确认积压',
              type: 'line',
              smooth: true,
              data: rows.map((row) => row.backlogQuantity),
            },
            {
              name: '履约率',
              type: 'line',
              yAxisIndex: 1,
              smooth: true,
              data: rows.map((row) => row.fillRate),
            },
          ],
        },
      },
    ].map(({ ref, option }) => {
      if (!ref.current) {
        return null;
      }
      const chart = echarts.init(ref.current);
      chart.setOption(option);
      return chart;
    }).filter(Boolean);

    const resizeCharts = () => instances.forEach((chart) => chart.resize());
    window.addEventListener('resize', resizeCharts);
    return () => {
      window.removeEventListener('resize', resizeCharts);
      instances.forEach((chart) => chart.dispose());
    };
  }, [viewState.rows, summary]);

  if (viewState.loading) {
    return (
      <div className="cobweb-page">
        <div className="cobweb-empty-state">正在加载蛛网模型验证数据...</div>
      </div>
    );
  }

  if (viewState.error) {
    return (
      <div className="cobweb-page">
        <div className="cobweb-empty-state warning">{viewState.error}</div>
      </div>
    );
  }

  if (viewState.rows.length === 0) {
    return (
      <div className="cobweb-page">
        <div className="cobweb-empty-state">
          当前运行未检测到蛛网模型数据。请确认场景启用了 market_demand_mode=cobweb。
        </div>
      </div>
    );
  }

  const latestRow = summary.latestRow || {};
  const cobwebConfig = viewState.runMeta?.cobweb_config || viewState.runMeta?.scenario_config?.simulation?.cobweb_config || {};
  const slopeRelation = toFiniteNumber(cobwebConfig?.supply_slope) !== null && toFiniteNumber(cobwebConfig?.demand_slope) !== null
    ? `${formatNumber(cobwebConfig.supply_slope, 2)} / ${formatNumber(cobwebConfig.demand_slope, 2)}`
    : '-';
  const cobwebTypeLabel = {
    convergent: '收敛型',
    neutral: '均衡型',
    divergent: '发散型',
    unknown: '待识别',
  }[summary.scenarioType] || '待识别';
  const cobwebTypeNote = summary.scenarioType === 'unknown'
    ? '当前运行缺少可识别的蛛网场景标识'
    : `由 d / b = ${slopeRelation} 判定：小于 1 收敛，等于 1 均衡，大于 1 发散`;
  const scenarioEffectTitle = String(summary.scenarioExpectation.title || '').replace(/^.*?[：:]\s*/, '');
  const scenarioEffectText = [scenarioEffectTitle, summary.effectExplanation]
    .filter(Boolean)
    .join('，');
  const cobwebParameterCards = [
    {
      label: 'a 需求截距',
      value: formatNumber(cobwebConfig?.demand_intercept, 2),
      note: '价格为 0 时的理论市场需求上限',
    },
    {
      label: 'b 需求斜率',
      value: formatNumber(cobwebConfig?.demand_slope, 2),
      note: '价格每上升 1 单位，需求减少多少',
    },
    {
      label: 'c 供给截距',
      value: formatNumber(cobwebConfig?.supply_intercept, 2),
      note: '滞后价格为 0 时的理论基础供给',
    },
    {
      label: 'd 供给斜率',
      value: formatNumber(cobwebConfig?.supply_slope, 2),
      note: '上一期价格每上升 1 单位，理论供给增加多少',
    },
    {
      label: 'd / b 稳定关系',
      value: slopeRelation,
      note: '小于 1 收敛，等于 1 等幅，大于 1 发散',
    },
    {
      label: 'P0 初始价格',
      value: formatNumber(cobwebConfig?.initial_price, 2),
      note: 'day0 冷启动时使用的上一期价格信号',
    },
    {
      label: '供给滞后',
      value: `${formatNumber(cobwebConfig?.endogenous_supply_lag_rounds, 0)} 轮`,
      note: `市场读取上一轮${summary.controllerLabel}生产计划作为供给`,
    },
    {
      label: '供给来源',
      value: cobwebConfig?.endogenous_supply_source || '-',
      note: `当前使用${summary.controllerLabel}创建的生产计划量`,
    },
  ];

  return (
    <div className="cobweb-page">
      <section className="cobweb-hero">
        <div className="cobweb-hero-main">
          <span className="cobweb-eyebrow">Cobweb Validation</span>
          <div className="cobweb-hero-title-row">
            <h2>蛛网模型实验解释与验证</h2>
          </div>
          <p>
            本项目中的蛛网模型使用 <strong>Qd_t = a - b * P_t</strong> 表示需求曲线，
            使用 <strong>Q_ref,t = c + d * P_(t-1)</strong> 作为理论供给参考；
            实验模式为 <strong>{cobwebConfig?.production_response_mode || '-'}</strong>，
            市场实际采用 <strong>{summary.controllerLabel}生产计划量</strong> 反推本期价格。
          </p>
        </div>
        <aside className={`cobweb-hero-summary cobweb-type-card ${summary.scenarioType}`}>
          <span>蛛网类型</span>
          <div className="cobweb-summary-heading">
            <strong>{cobwebTypeLabel}</strong>
            <p>{scenarioEffectText}</p>
          </div>
          <small>{cobwebTypeNote}</small>
          <button
            className="cobweb-detail-toggle"
            type="button"
            aria-expanded={showCobwebDetails}
            onClick={() => setShowCobwebDetails((current) => !current)}
          >
            {showCobwebDetails ? '收起参数详情' : '展开参数详情'}
          </button>
        </aside>
        {showCobwebDetails && (
          <div className="cobweb-param-grid">
            {cobwebParameterCards.map((item) => (
              <div className="cobweb-param-card" key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.note}</small>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="cobweb-source-strip">
        <span>运行: {currentRunId || summary.runId}</span>
        <span>场景: {summary.scenarioName}</span>
        <span>生产企业: {summary.producerId}</span>
        <span>数据源: {currentRunSourceLabel || dataRoot}</span>
      </div>

      <section className="cobweb-kpi-grid">
        <div className="cobweb-kpi-card">
          <span>最终价格偏离均衡</span>
          <strong>{formatSigned(summary.finalPriceGap, 4)}</strong>
          <small>P* = {formatNumber(summary.equilibriumPrice, 2)}</small>
        </div>
        <div className="cobweb-kpi-card">
          <span>最终供给偏离均衡</span>
          <strong>{formatSigned(summary.finalQuantityGap, 4)}</strong>
          <small>Q* = {formatNumber(summary.equilibriumQuantity, 2)}</small>
        </div>
        <div className="cobweb-kpi-card">
          <span>{summary.controllerLabel}供给接入</span>
          <strong>{summary.controllerSupplyCount}/{viewState.rows.length}</strong>
          <small>fallback {summary.fallbackSupplyCount} 轮</small>
        </div>
        <div className="cobweb-kpi-card">
          <span>后段平均价格偏离</span>
          <strong>{formatNumber(summary.lastSixMeanAbsPrice, 2)}</strong>
          <small>前半 {formatNumber(summary.firstHalfMeanAbsPrice, 2)} / 后半 {formatNumber(summary.secondHalfMeanAbsPrice, 2)}</small>
        </div>
        <div className="cobweb-kpi-card">
          <span>生产方向一致</span>
          <strong>{summary.directionOkCount}/{summary.directionTotal}</strong>
          <small>高价扩产，低价缩产</small>
        </div>
        <div className="cobweb-kpi-card">
          <span>最终库存 / 履约</span>
          <strong>{formatNumber(latestRow.inventoryQuantity, 0)} / {formatPercent(latestRow.fillRate)}</strong>
          <small>积压 {formatNumber(latestRow.backlogQuantity, 0)}</small>
        </div>
      </section>

      <section className="cobweb-layout">
        <article className="cobweb-chart-card wide">
          <div className="cobweb-card-title">价格与 {summary.controllerLabel} 供给轨迹</div>
          <div className="cobweb-card-note">
            用均衡线对照市场端是否呈现蛛网模型的核心轨迹。柱形为{summary.controllerLabel}生产计划，供给线为市场实际采用的定价供给。
          </div>
          <div className="cobweb-chart large" ref={convergenceRef} />
        </article>

        <article className="cobweb-chart-card">
          <div className="cobweb-card-title">{summary.controllerLabel}计划 vs 市场供给 vs 理论参考</div>
          <div className="cobweb-card-note">
            检查实际计划是否进入市场，并与当前控制器的价格响应规则保持一致。
          </div>
          <div className="cobweb-chart" ref={productionRef} />
        </article>

        <article className="cobweb-chart-card">
          <div className="cobweb-card-title">均衡偏离幅度</div>
          <div className="cobweb-card-note">
            收敛型应后段显著降低；等幅型应保持近似稳定；发散型应扩大或维持高振幅。
          </div>
          <div className="cobweb-chart" ref={deviationRef} />
        </article>

        <article className="cobweb-chart-card">
          <div className="cobweb-card-title">价格-供给相图</div>
          <div className="cobweb-chart" ref={phaseRef} />
        </article>

        <article className="cobweb-chart-card">
          <div className="cobweb-card-title">库存与履约背景</div>
          <div className="cobweb-card-note">
            这组指标不是严格蛛网目标本身，用于确认服务/库存没有反向主导生产决策。
          </div>
          <div className="cobweb-chart" ref={operationsRef} />
        </article>

        <article className="cobweb-chart-card wide">
          <div className="cobweb-card-title">逐轮证据审计表</div>
          <div className="cobweb-card-note">
            每轮检查供给来源、控制器计划、理论参考、方向一致性和输入过滤，判断轨迹是否来自已配置的决策链路。
          </div>
          <div className="cobweb-table-wrapper">
            <table className="cobweb-table">
              <thead>
                <tr>
                  <th>轮次</th>
                  <th>价格</th>
                  <th>市场供给</th>
                  <th>{summary.controllerLabel}计划</th>
                  <th>理论参考</th>
                  <th>供给来源</th>
                  <th>方向</th>
                  <th>输入过滤</th>
                  <th>生产理由摘要</th>
                </tr>
              </thead>
              <tbody>
                {viewState.rows.map((row) => (
                  <tr key={row.day}>
                    <td>D{row.day}</td>
                    <td>{formatNumber(row.price, 2)}</td>
                    <td>{formatNumber(row.marketSupply, 0)}</td>
                    <td>{formatNumber(row.planQuantity, 0)}</td>
                    <td>{formatNumber(row.theoreticalSupply, 1)}</td>
                    <td>
                      <span className={`cobweb-pill ${row.marketSupplySource === summary.expectedSupplySource ? 'success' : 'muted'}`}>
                        {row.marketSupplySource || '-'}
                      </span>
                    </td>
                    <td className={row.directionOk ? 'cobweb-ok-cell' : 'cobweb-warning-cell'}>
                      {row.direction || '-'}
                    </td>
                    <td>
                      <span className={`cobweb-pill ${row.agentInputFilterApplied ? 'success' : 'muted'}`}>
                        {summary.controllerMode === 'scripted'
                          ? '不适用'
                          : (row.agentInputFilterApplied ? '已过滤' : '未过滤')}
                      </span>
                    </td>
                    <td title={row.actionReason}>
                      {truncateText(row.actionReason, 120)}
                      {row.actionReasonNoiseTerms.length > 0 && (
                        <span className="cobweb-noise-mark">含干扰词</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </div>
  );
}

export default CobwebModelValidationView;
