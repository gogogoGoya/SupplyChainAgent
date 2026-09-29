import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';

const ENTERPRISE_COLORS = {
  Supplier: '#31708e',
  Manufacturer: '#b04a3a',
  Distributor: '#437a56',
  Retailer: '#a87517',
};

const PHASES = [
  { name: '稳定基线', start: 0, end: 39, strategy: '建立协同交易基线' },
  { name: '原料涨价', start: 40, end: 79, strategy: '补充缓冲并保护毛利' },
  { name: '制造成本冲击', start: 80, end: 119, strategy: '约束排产与订单边界' },
  { name: '贸易物流收紧', start: 120, end: 159, strategy: '收紧外采并保障履约' },
  { name: '需求软化与成本回落', start: 160, end: 199, strategy: '主动降速与控制敞口' },
];

const RESPONSE_ACTIONS = {
  procurement: ['create_purchase_order', 'create_purchase_demand', 'create_replenishment_order'],
  production: ['create_production_plan'],
  market: [
    'adjust_sales_demand',
    'accept_order',
    'reject_order',
    'accept_proposal_order',
    'reject_proposal_order',
  ],
};

const toNumber = (value, fallback = 0) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const formatNumber = (value, digits = 0) => new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: digits,
}).format(toNumber(value));

const formatCurrencyCompact = (value) => {
  const numeric = toNumber(value);
  if (Math.abs(numeric) >= 1000000) return `¥${formatNumber(numeric / 1000000, 2)}M`;
  if (Math.abs(numeric) >= 10000) return `¥${formatNumber(numeric / 10000, 1)}万`;
  return `¥${formatNumber(numeric)}`;
};

const chunkedLoad = async (turns, loader, chunkSize = 20) => {
  const rows = [];
  for (let index = 0; index < turns.length; index += chunkSize) {
    const chunk = turns.slice(index, index + chunkSize);
    const chunkRows = await Promise.all(chunk.map(loader));
    rows.push(...chunkRows);
  }
  return rows;
};

const readTurn = async (dataRoot, turn) => {
  const [environmentRoot, environmentEnd, metrics, enterpriseDaily, runtimeHealth] = await Promise.all([
    safeFetchJson(buildDataUrl(dataRoot, `public/exchange/day${turn}/external_environment.json`)),
    safeFetchJson(buildDataUrl(dataRoot, `public/exchange/day${turn}/end_of_day/external_environment.json`)),
    safeFetchJson(buildDataUrl(dataRoot, `projections/run_metrics/day${turn}/run_metrics_projection.json`)),
    safeFetchJson(buildDataUrl(
      dataRoot,
      `projections/multi_enterprise/day${turn}/enterprise_daily_metrics_projection.json`,
    )),
    safeFetchJson(buildDataUrl(dataRoot, `runtime_health/day${turn}_agent_timeout.json`)),
  ]);
  return {
    turn,
    environment: (
      environmentRoot?.enabled
        ? environmentRoot
        : environmentEnd?.enabled
          ? environmentEnd
          : metrics?.external_environment || {}
    ),
    metrics: metrics || {},
    enterpriseDaily: enterpriseDaily || {},
    runtimeHealth: runtimeHealth || {},
  };
};

const buildEventMarkLines = (rows) => {
  const seen = new Set();
  const events = [];
  rows.forEach((row) => {
    (row.environment?.triggered_events || []).forEach((event) => {
      const eventId = event.event_id || `${event.turn}:${event.label}`;
      if (seen.has(eventId)) return;
      seen.add(eventId);
      events.push({
        ...event,
        eventId,
        name: event.label || eventId,
        xAxis: Number(event.turn ?? row.turn),
      });
    });
  });
  return events;
};

const getRoundActionCounts = (row) => (
  row.metrics?.external_response_observability?.round_actions?.total_action_counts || {}
);

const sumActionGroup = (row, actionNames) => actionNames.reduce(
  (sum, actionName) => sum + toNumber(getRoundActionCounts(row)[actionName]),
  0,
);

const sumAllActions = (rows) => rows.reduce((sum, row) => (
  sum + Object.values(getRoundActionCounts(row)).reduce(
    (roundSum, count) => roundSum + toNumber(count),
    0,
  )
), 0);

const rollingActionCounts = (rows, actionNames, windowSize = 5) => rows.map((_, index) => {
  const start = Math.max(0, index - windowSize + 1);
  return rows.slice(start, index + 1).reduce(
    (sum, row) => sum + sumActionGroup(row, actionNames),
    0,
  );
});

const getTradeSnapshot = (row) => {
  const enterpriseMetrics = row.enterpriseDaily?.enterprise_metrics || {};
  return Object.values(enterpriseMetrics).reduce((totals, enterprise) => {
    const participation = enterprise?.order_participation || {};
    return {
      orderCount: totals.orderCount + toNumber(participation.sold_order_count),
      orderQuantity: totals.orderQuantity + toNumber(participation.sold_quantity),
      orderValue: totals.orderValue + toNumber(participation.sold_value),
    };
  }, { orderCount: 0, orderQuantity: 0, orderValue: 0 });
};

const getAuditStats = (row) => {
  const totals = row.metrics?.round_integrity?.totals || {};
  const valid = toNumber(totals.skill_audit_valid);
  const fallback = toNumber(totals.skill_audit_fallback);
  return { valid, fallback, direct: Math.max(0, valid - fallback) };
};

const formatFactorSummary = (event) => {
  const factorLabels = {
    external_material_price: '原料',
    production_conversion_cost: '制造',
    external_logistics_cost: '物流',
    external_demand_quantity: '需求',
    external_customer_price: '终端价',
  };
  return Object.entries(event.factor_updates || {})
    .map(([key, value]) => `${factorLabels[key] || key} ${formatNumber(value, 2)}x`)
    .join(' · ');
};

const EvolutionExperimentView = ({ availableDays = [], dataRoot, enterpriseSpecs = [] }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const factorRef = useRef(null);
  const revenueRef = useRef(null);
  const tradeRef = useRef(null);
  const serviceRef = useRef(null);
  const qualityRef = useRef(null);
  const responseRef = useRef(null);
  const chartsRef = useRef([]);

  const enterpriseIds = useMemo(() => (
    enterpriseSpecs.map((item) => item.enterprise_id || item.id).filter(Boolean)
  ), [enterpriseSpecs]);
  const visibleEnterpriseIds = enterpriseIds.length
    ? enterpriseIds
    : ['Supplier', 'Manufacturer', 'Distributor', 'Retailer'];

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const loaded = await chunkedLoad(availableDays, (turn) => readTurn(dataRoot, turn));
      if (!cancelled) {
        setRows(loaded);
        setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [availableDays.join(','), dataRoot]);

  useEffect(() => {
    chartsRef.current.forEach((chart) => chart?.dispose());
    chartsRef.current = [];
    if (!rows.length) return undefined;

    const turns = rows.map((row) => row.turn);
    const eventLines = buildEventMarkLines(rows);
    const commonMarkLine = {
      silent: true,
      symbol: 'none',
      label: { formatter: '{b}', color: '#6b3f34', fontSize: 10 },
      lineStyle: { color: '#c77865', type: 'dashed', width: 1 },
      data: eventLines,
    };
    const baseOption = {
      animation: false,
      tooltip: { trigger: 'axis' },
      grid: { left: 64, right: 42, top: 52, bottom: 48 },
      xAxis: {
        type: 'category',
        name: 'Turn',
        data: turns,
        axisLabel: { hideOverlap: true },
      },
      textStyle: { fontFamily: 'Inter, system-ui, sans-serif' },
    };

    const factorChart = echarts.init(factorRef.current);
    factorChart.setOption({
      ...baseOption,
      legend: { top: 4 },
      yAxis: { type: 'value', name: '相对基线', axisLabel: { formatter: '{value}x' } },
      series: [
        ['原料价格', 'external_material_price'],
        ['制造成本', 'production_conversion_cost'],
        ['贸易物流', 'external_logistics_cost'],
        ['终端需求', 'external_demand_quantity'],
        ['终端价格', 'external_customer_price'],
      ].map(([name, key], index) => ({
        name,
        type: 'line',
        showSymbol: false,
        data: rows.map((row) => toNumber(row.environment?.active_factors?.[key], 1)),
        markLine: index === 0 ? commonMarkLine : undefined,
      })),
    });

    const revenueChart = echarts.init(revenueRef.current);
    revenueChart.setOption({
      ...baseOption,
      legend: { top: 4 },
      yAxis: { type: 'value', name: '累计营收', axisLabel: { formatter: (value) => `${value / 10000}万` } },
      series: visibleEnterpriseIds.map((enterpriseId, index) => ({
        name: enterpriseId,
        type: 'line',
        showSymbol: false,
        color: ENTERPRISE_COLORS[enterpriseId],
        data: rows.map((row) => (
          row.metrics?.enterprise_metrics?.[enterpriseId]?.finance?.total_revenue ?? null
        )),
        markLine: index === 0 ? commonMarkLine : undefined,
      })),
    });

    const tradeChart = echarts.init(tradeRef.current);
    tradeChart.setOption({
      ...baseOption,
      legend: { top: 4 },
      yAxis: [
        { type: 'value', name: '累计订单' },
        { type: 'value', name: '累计成交额', axisLabel: { formatter: (value) => `${value / 10000}万` } },
      ],
      series: [
        {
          name: '链内订单',
          type: 'line',
          showSymbol: false,
          data: rows.map((row) => getTradeSnapshot(row).orderCount),
          markLine: commonMarkLine,
        },
        {
          name: '链内成交额',
          type: 'line',
          yAxisIndex: 1,
          areaStyle: { opacity: 0.08 },
          showSymbol: false,
          data: rows.map((row) => getTradeSnapshot(row).orderValue),
        },
      ],
    });

    const serviceChart = echarts.init(serviceRef.current);
    serviceChart.setOption({
      ...baseOption,
      legend: { top: 4 },
      yAxis: {
        type: 'value',
        name: '累计履约率',
        min: 0,
        max: 1,
        axisLabel: { formatter: (value) => `${Math.round(value * 100)}%` },
      },
      series: ['Supplier', 'Manufacturer', 'Distributor'].map((enterpriseId, index) => ({
        name: enterpriseId,
        type: 'line',
        showSymbol: false,
        color: ENTERPRISE_COLORS[enterpriseId],
        data: rows.map((row) => (
          row.metrics?.enterprise_metrics?.[enterpriseId]?.sales?.fill_rate ?? null
        )),
        markLine: index === 0 ? commonMarkLine : undefined,
      })),
    });

    let cumulativeValid = 0;
    let cumulativeDirect = 0;
    const currentDirectRates = [];
    const cumulativeDirectRates = [];
    rows.forEach((row) => {
      const audit = getAuditStats(row);
      cumulativeValid += audit.valid;
      cumulativeDirect += audit.direct;
      currentDirectRates.push(audit.valid ? (audit.direct / audit.valid) * 100 : null);
      cumulativeDirectRates.push(cumulativeValid ? (cumulativeDirect / cumulativeValid) * 100 : null);
    });
    const qualityChart = echarts.init(qualityRef.current);
    qualityChart.setOption({
      ...baseOption,
      legend: { top: 4 },
      yAxis: {
        type: 'value',
        name: 'Agent 直出率',
        min: 75,
        max: 100,
        axisLabel: { formatter: '{value}%' },
      },
      series: [
        {
          name: '当前轮直出率',
          type: 'line',
          step: 'end',
          showSymbol: false,
          data: currentDirectRates,
          markLine: commonMarkLine,
        },
        {
          name: '累计直出率',
          type: 'line',
          showSymbol: false,
          lineStyle: { width: 3 },
          data: cumulativeDirectRates,
        },
      ],
    });

    const responseChart = echarts.init(responseRef.current);
    responseChart.setOption({
      ...baseOption,
      legend: { top: 4 },
      yAxis: { type: 'value', name: '近5轮动作数', minInterval: 1 },
      series: [
        ['采购与补货', RESPONSE_ACTIONS.procurement, '#31708e'],
        ['生产调整', RESPONSE_ACTIONS.production, '#b04a3a'],
        ['订单与市场取舍', RESPONSE_ACTIONS.market, '#a87517'],
      ].map(([name, actionNames, color], index) => ({
        name,
        type: 'line',
        stack: 'response',
        areaStyle: { opacity: 0.16 },
        showSymbol: false,
        color,
        data: rollingActionCounts(rows, actionNames),
        markLine: index === 0 ? commonMarkLine : undefined,
      })),
    });

    chartsRef.current = [
      factorChart,
      revenueChart,
      tradeChart,
      serviceChart,
      qualityChart,
      responseChart,
    ];
    const handleResize = () => chartsRef.current.forEach((chart) => chart?.resize());
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chartsRef.current.forEach((chart) => chart?.dispose());
      chartsRef.current = [];
    };
  }, [rows, visibleEnterpriseIds.join('|')]);

  const latest = rows[rows.length - 1] || {};
  const latestMetrics = latest.metrics || {};
  const eventLines = buildEventMarkLines(rows);
  const totalActions = sumAllActions(rows);
  const latestTrade = getTradeSnapshot(latest);
  const auditTotals = rows.reduce((totals, row) => {
    const audit = getAuditStats(row);
    return { valid: totals.valid + audit.valid, direct: totals.direct + audit.direct };
  }, { valid: 0, direct: 0 });
  const directRate = auditTotals.valid ? (auditTotals.direct / auditTotals.valid) * 100 : 0;
  const allTimeoutTurns = rows.filter((row) => row.runtimeHealth?.all_agent_calls_timed_out).length;
  const eventResponses = eventLines.map((event) => ({
    ...event,
    responseActions: sumAllActions(rows.filter(
      (row) => row.turn >= event.xAxis && row.turn <= event.xAxis + 9,
    )),
  }));
  const phaseSummaries = PHASES.map((phase, index) => {
    const phaseRows = rows.filter((row) => row.turn >= phase.start && row.turn <= phase.end);
    const endRow = phaseRows[phaseRows.length - 1];
    const previousRows = rows.filter((row) => row.turn < phase.start);
    const previousTrade = getTradeSnapshot(previousRows[previousRows.length - 1] || {});
    const endTrade = getTradeSnapshot(endRow || {});
    const serviceRates = ['Supplier', 'Manufacturer', 'Distributor']
      .map((enterpriseId) => toNumber(
        endRow?.metrics?.enterprise_metrics?.[enterpriseId]?.sales?.fill_rate,
        NaN,
      ))
      .filter(Number.isFinite);
    return {
      ...phase,
      index,
      actions: sumAllActions(phaseRows),
      newOrders: endTrade.orderCount - previousTrade.orderCount,
      tradeValue: endTrade.orderValue - previousTrade.orderValue,
      serviceRate: serviceRates.length
        ? serviceRates.reduce((sum, value) => sum + value, 0) / serviceRates.length
        : null,
    };
  }).filter((phase) => phase.actions || phase.newOrders || phase.index === 0);

  if (loading) {
    return <div className="loading">正在加载持续演变长跑数据...</div>;
  }

  return (
    <div className="evolution-view">
      <section className="evolution-summary-band">
        <div><span>完整运行</span><strong>{latestMetrics.completed_steps || rows.length} / {latestMetrics.planned_total_steps || 200}</strong></div>
        <div><span>部门 Agent 直出</span><strong>{formatNumber(directRate, 1)}%</strong></div>
        <div><span>全体超时轮次</span><strong>{allTimeoutTurns}</strong></div>
        <div><span>经营动作</span><strong>{formatNumber(totalActions)}</strong></div>
        <div><span>链内成交</span><strong>{formatNumber(latestTrade.orderCount)} 笔</strong></div>
        <div><span>链内成交额</span><strong>{formatCurrencyCompact(latestTrade.orderValue)}</strong></div>
      </section>

      <section className="evolution-event-strip">
        {eventResponses.length ? eventResponses.map((event) => (
          <div key={`${event.xAxis}:${event.name}`}>
            <span>Turn {event.xAxis}</span>
            <strong>{event.name}</strong>
            <small>{formatFactorSummary(event)}</small>
            <small>后 10 轮 {formatNumber(event.responseActions)} 次经营响应</small>
          </div>
        )) : <p>Turn 40 起将显示已触发的外部环境变化。</p>}
      </section>

      <section className="evolution-phase-table-wrap">
        <h3>阶段自适应画像</h3>
        <div className="evolution-phase-table-scroll">
          <table className="evolution-phase-table">
            <thead>
              <tr>
                <th>阶段</th>
                <th>策略取向</th>
                <th>经营动作</th>
                <th>新增链内订单</th>
                <th>新增成交额</th>
                <th>B2B 平均履约率</th>
              </tr>
            </thead>
            <tbody>
              {phaseSummaries.map((phase) => (
                <tr key={phase.name}>
                  <td><strong>{phase.name}</strong><small>Turn {phase.start}-{phase.end}</small></td>
                  <td>{phase.strategy}</td>
                  <td>{formatNumber(phase.actions)}</td>
                  <td>{formatNumber(phase.newOrders)}</td>
                  <td>{formatCurrencyCompact(phase.tradeValue)}</td>
                  <td>{phase.serviceRate === null ? '-' : `${formatNumber(phase.serviceRate * 100, 1)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="evolution-chart-grid">
        <article><h3>外部环境演变</h3><div ref={factorRef} className="evolution-chart" /></article>
        <article><h3>企业累计营收成长</h3><div ref={revenueRef} className="evolution-chart" /></article>
        <article><h3>供应链成交规模</h3><div ref={tradeRef} className="evolution-chart" /></article>
        <article><h3>B2B 链路履约韧性</h3><div ref={serviceRef} className="evolution-chart" /></article>
        <article><h3>Agent 长跑直出稳定性</h3><div ref={qualityRef} className="evolution-chart" /></article>
        <article><h3>扰动后经营动作组合</h3><div ref={responseRef} className="evolution-chart" /></article>
      </section>
    </div>
  );
};

export default EvolutionExperimentView;
