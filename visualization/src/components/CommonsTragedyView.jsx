import React, { useEffect, useMemo, useState } from 'react';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';

const ENTERPRISE_COLORS = {
  Miner_A: '#2f6f73',
  Miner_B: '#d18b2c',
  Miner_C: '#b84a32',
  Miner_D: '#5b7f3a',
};

const COMMONS_COLORS = {
  stock: '#2f6f73',
  quality: '#b84a32',
  sustainable: '#6f7d72',
  planned: '#b84a32',
  effective: '#2f6f73',
  yield: '#d18b2c',
  depletion: '#7d3f2a',
  overuse: '#c56f2d',
  cash: '#2f6f73',
  profit: '#7b4f86',
  blocked: '#9e5f4a',
};

const SVG_WIDTH = 920;
const SVG_HEIGHT = 320;
const PADDING = { top: 34, right: 28, bottom: 44, left: 58 };

const toNumber = (value, fallback = null) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const formatNumber = (value, digits = 2) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: digits }).format(numeric);
};

const formatPercent = (value, digits = 1) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  return `${formatNumber(numeric * 100, digits)}%`;
};

const average = (values) => {
  const finite = values.map(Number).filter(Number.isFinite);
  if (finite.length === 0) {
    return null;
  }
  return finite.reduce((sum, value) => sum + value, 0) / finite.length;
};

const getEnterpriseId = (spec) => spec?.enterprise_id || spec?.id || spec?.name;

const normalizeMetricRow = (row) => {
  const source = row || {};
  const enterprises = Object.fromEntries(
    Object.entries(source.enterprises || {}).map(([enterpriseId, record]) => ([
      enterpriseId,
      {
        ...record,
        planned_acquisition: toNumber(record?.planned_acquisition, 0),
        effective_acquisition: toNumber(record?.effective_acquisition, 0),
        raw_effective_acquisition: toNumber(record?.raw_effective_acquisition, 0),
        gross_profit: toNumber(record?.gross_profit, 0),
      },
    ]))
  );

  return {
    ...source,
    round: toNumber(source.round, 0),
    resource_stock_before: toNumber(source.resource_stock_before, 0),
    resource_stock: toNumber(source.resource_stock, 0),
    resource_stock_ratio: toNumber(source.resource_stock_ratio, 0),
    resource_quality: toNumber(source.resource_quality, 0),
    total_planned_acquisition: toNumber(source.total_planned_acquisition, 0),
    total_effective_acquisition: toNumber(source.total_effective_acquisition, 0),
    sustainable_total_acquisition: toNumber(source.sustainable_total_acquisition, 0),
    overuse_quantity: toNumber(source.overuse_quantity, 0),
    resource_shortage_compression_ratio: toNumber(source.resource_shortage_compression_ratio, 1),
    enterprises,
  };
};

const normalizeFinanceRow = (payload, enterpriseId, day) => {
  const source = payload?.self_state || payload?.data?.self_state || payload || {};
  const indicators = source.financial_indicators || {};
  return {
    enterpriseId,
    round: day,
    cash: toNumber(source.cash, null),
    totalRevenue: toNumber(source.total_revenue, null),
    totalCost: toNumber(source.total_cost, null),
    netProfit: toNumber(indicators.net_profit ?? source.net_profit, null),
    grossProfit: toNumber(indicators.gross_profit ?? source.gross_profit, null),
  };
};

const loadMetricsForDays = async (dataRoot, availableDays) => {
  const rows = [];
  for (const day of availableDays) {
    const payload = await safeFetchJson(
      buildDataUrl(dataRoot, `public/exchange/day${day}/end_of_day/shared_resource_metrics.json`)
    ) || await safeFetchJson(
      buildDataUrl(dataRoot, `public/exchange/day${day}/shared_resource_metrics.json`)
    );
    if (payload) {
      rows.push(normalizeMetricRow(payload?.data || payload));
    }
  }
  return rows.sort((a, b) => Number(a?.round ?? 0) - Number(b?.round ?? 0));
};

const loadFinalObservers = async (dataRoot, finalDay, enterpriseIds) => {
  const entries = await Promise.all(
    enterpriseIds.map(async (enterpriseId) => {
      const payload = await safeFetchJson(
        buildDataUrl(dataRoot, `public/observer_state/day${finalDay}/end_of_day/${enterpriseId}.json`)
      );
      return [enterpriseId, payload?.observation || payload?.data?.observation || null];
    })
  );
  return Object.fromEntries(entries.filter(([, payload]) => payload));
};

const loadFinanceRowsForDays = async (dataRoot, availableDays, enterpriseIds) => {
  const entries = await Promise.all(
    enterpriseIds.flatMap((enterpriseId) => (
      availableDays.map(async (day) => {
        const payload = await safeFetchJson(
          buildDataUrl(dataRoot, `enterprises/${enterpriseId}/department/finance/day${day}/finance.json`)
        );
        return payload ? normalizeFinanceRow(payload, enterpriseId, day) : null;
      })
    ))
  );
  return entries.filter(Boolean);
};

const loadProductionErrorRowsForDays = async (dataRoot, availableDays, enterpriseIds) => {
  const entries = await Promise.all(
    enterpriseIds.flatMap((enterpriseId) => (
      availableDays.map(async (day) => {
        let insufficientFundErrors = 0;
        const errorFileNames = [
          'production_error.json',
          ...Array.from({ length: 4 }, (_, index) => `production_error_${index}.json`),
        ];
        for (const fileName of errorFileNames) {
          const payload = await safeFetchJson(
            buildDataUrl(dataRoot, `enterprises/${enterpriseId}/department/production/day${day}/${fileName}`)
          );
          const text = payload ? JSON.stringify(payload) : '';
          if (text.includes('资金不足') || text.toLowerCase().includes('insufficient')) {
            insufficientFundErrors += 1;
          }
        }
        return { enterpriseId, round: day, insufficientFundErrors };
      })
    ))
  );
  return entries;
};

const buildEnterpriseRows = (metrics, finalObservers, enterpriseIds) => (
  enterpriseIds.map((enterpriseId) => {
    const records = metrics
      .map((metric) => metric?.enterprises?.[enterpriseId])
      .filter(Boolean);
    const plannedTotal = records.reduce((sum, record) => sum + Number(record?.planned_acquisition || 0), 0);
    const effectiveTotal = records.reduce((sum, record) => sum + Number(record?.effective_acquisition || 0), 0);
    const sourceCounts = records.reduce((counter, record) => {
      const source = record?.acquisition_source || 'unknown';
      counter[source] = (counter[source] || 0) + 1;
      return counter;
    }, {});
    const observer = finalObservers?.[enterpriseId] || {};
    const finance = observer.finance || {};
    const production = observer.production || {};
    const sales = observer.sales || {};
    const inventoryItems = observer.inventory?.inventory_items || [];
    const oreInventory = inventoryItems.find((item) => item?.item_id === 'copper_ore')?.quantity;

    return {
      enterpriseId,
      plannedTotal,
      effectiveTotal,
      averagePlanned: average(records.map((record) => record?.planned_acquisition)),
      averageEffective: average(records.map((record) => record?.effective_acquisition)),
      agentPlanRounds: sourceCounts.agent_production_plan_created || 0,
      coldStartRounds: sourceCounts.initial_reference_acquisition || 0,
      cash: finance?.cash,
      netProfit: finance?.financial_indicators?.net_profit,
      totalRevenue: finance?.total_revenue,
      totalProduction: production?.production_metrics?.total_production,
      failedPlans: production?.production_metrics?.failed_plans,
      completedOrders: sales?.sales_metrics?.completed_orders,
      breachedOrders: sales?.sales_metrics?.breached_orders,
      fulfillmentRate: sales?.sales_metrics?.order_fulfillment_rate,
      oreInventory,
    };
  })
);

const buildScale = (values, {
  min = null,
  max = null,
  nice = true,
  floorZero = true,
} = {}) => {
  const finite = values.map(Number).filter(Number.isFinite);
  if (finite.length === 0) {
    return { min: 0, max: 1 };
  }
  const rawMin = min ?? Math.min(...finite, 0);
  const rawMax = max ?? Math.max(...finite, 1);
  if (!nice) {
    return { min: rawMin, max: rawMax || 1 };
  }
  const span = rawMax - rawMin;
  const padding = span === 0 ? rawMax * 0.1 || 1 : span * 0.08;
  return {
    min: floorZero ? Math.max(0, rawMin - padding) : rawMin - padding,
    max: rawMax + padding,
  };
};

const createPointHelpers = (rows, scale) => {
  const width = SVG_WIDTH - PADDING.left - PADDING.right;
  const height = SVG_HEIGHT - PADDING.top - PADDING.bottom;
  const x = (index) => PADDING.left + (rows.length <= 1 ? width / 2 : (index / (rows.length - 1)) * width);
  const y = (value) => {
    const numeric = toNumber(value, 0);
    const range = scale.max - scale.min || 1;
    return PADDING.top + height - ((numeric - scale.min) / range) * height;
  };
  return { x, y, width, height };
};

const linePath = (points) => points
  .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
  .join(' ');

const Axis = ({ rows, scale, formatter = (value) => formatNumber(value, 0) }) => {
  const { x, y, width, height } = createPointHelpers(rows, scale);
  const ticks = [scale.min, scale.min + (scale.max - scale.min) / 2, scale.max];
  const labelIndexes = rows.length <= 8
    ? rows.map((_, index) => index)
    : [0, Math.floor((rows.length - 1) / 2), rows.length - 1];

  return (
    <g className="commons-svg-axis">
      <line x1={PADDING.left} y1={PADDING.top + height} x2={PADDING.left + width} y2={PADDING.top + height} />
      <line x1={PADDING.left} y1={PADDING.top} x2={PADDING.left} y2={PADDING.top + height} />
      {ticks.map((tick) => (
        <g key={tick}>
          <line x1={PADDING.left} y1={y(tick)} x2={PADDING.left + width} y2={y(tick)} className="commons-svg-grid-line" />
          <text x={PADDING.left - 8} y={y(tick) + 4} textAnchor="end">{formatter(tick)}</text>
        </g>
      ))}
      {scale.min < 0 && scale.max > 0 && (
        <line x1={PADDING.left} y1={y(0)} x2={PADDING.left + width} y2={y(0)} className="commons-svg-zero-line" />
      )}
      {labelIndexes.map((index) => (
        <text key={index} x={x(index)} y={PADDING.top + height + 24} textAnchor="middle">
          D{rows[index]?.round}
        </text>
      ))}
    </g>
  );
};

const Legend = ({ items }) => (
  <div className="commons-svg-legend">
    {items.map((item) => (
      <span key={item.name}>
        <i style={{ background: item.color }} />
        {item.name}
      </span>
    ))}
  </div>
);

const EmptyChart = ({ message = '暂无可绘制数据', detail = null }) => (
  <div className="commons-svg-empty">
    <strong>{message}</strong>
    {detail && <span>{detail}</span>}
  </div>
);

const LineSvgChart = ({
  rows,
  series,
  max = null,
  min = null,
  percent = false,
  floorZero = true,
  emptyMessage = '暂无可绘制数据',
  emptyDetail = null,
}) => {
  if (!rows.length || !series.length) {
    return <EmptyChart message={emptyMessage} detail={emptyDetail} />;
  }
  const values = series.flatMap((entry) => rows.map((row) => entry.value(row)));
  const scale = buildScale(values, {
    min: min ?? (floorZero ? 0 : null),
    max,
    nice: max === null || min === null,
    floorZero,
  });
  const helpers = createPointHelpers(rows, scale);

  return (
    <div className="commons-svg-chart-wrap">
      <Legend items={series} />
      <svg className="commons-svg-chart" viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`} role="img">
        <Axis
          rows={rows}
          scale={scale}
          formatter={(value) => (percent ? formatPercent(value, 0) : formatNumber(value, 0))}
        />
        {series.map((entry) => {
          const points = rows.map((row, index) => ({
            x: helpers.x(index),
            y: helpers.y(entry.value(row)),
          }));
          return (
            <g key={entry.name}>
              <path
                d={linePath(points)}
                fill="none"
                stroke={entry.color}
                strokeWidth="3"
                strokeDasharray={entry.dashed ? '7 6' : undefined}
              />
              {!entry.dashed && points.map((point, index) => (
                <circle key={index} cx={point.x} cy={point.y} r="3.8" fill={entry.color}>
                  <title>{`${entry.name} D${rows[index].round}: ${percent ? formatPercent(entry.value(rows[index])) : formatNumber(entry.value(rows[index]), 2)}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
};

const buildCausalityRows = (metrics) => {
  if (!metrics.length) {
    return [];
  }
  const initialStock = toNumber(metrics[0].resource_stock_before, metrics[0].resource_stock);
  let cumulativeOveruse = 0;
  const rawRows = metrics.map((row) => {
    cumulativeOveruse += Number(row.overuse_quantity || 0);
    return {
      round: row.round,
      cumulativeOveruse,
      depletionRatio: initialStock > 0
        ? Math.max(0, (initialStock - Number(row.resource_stock || 0)) / initialStock)
        : 0,
      stockRatio: row.resource_stock_ratio,
    };
  });
  const maxOveruse = Math.max(...rawRows.map((row) => row.cumulativeOveruse), 1);
  return rawRows.map((row) => ({
    ...row,
    cumulativeOveruseIndex: row.cumulativeOveruse / maxOveruse,
  }));
};

const buildFinanceTimeRows = (financeRows, enterpriseIds, metricName) => {
  const grouped = new Map();
  financeRows.forEach((row) => {
    if (!grouped.has(row.round)) {
      grouped.set(row.round, { round: row.round });
    }
    grouped.get(row.round)[row.enterpriseId] = row?.[metricName];
  });
  return Array.from(grouped.values())
    .sort((a, b) => Number(a.round) - Number(b.round))
    .filter((row) => enterpriseIds.some((enterpriseId) => Number.isFinite(Number(row[enterpriseId]))));
};

const buildCumulativeErrorRows = (errorRows, enterpriseIds) => {
  const totals = Object.fromEntries(enterpriseIds.map((enterpriseId) => [enterpriseId, 0]));
  errorRows.forEach((row) => {
    if (Object.prototype.hasOwnProperty.call(totals, row.enterpriseId)) {
      totals[row.enterpriseId] += Number(row.insufficientFundErrors || 0);
    }
  });
  return totals;
};

const buildStrategyRows = (enterpriseRows, runMeta) => {
  const configs = runMeta?.scenario_config?.enterprise_configs || runMeta?.scenario_config?.enterprise_specs || [];
  const configMap = Object.fromEntries(
    configs.map((config) => [config?.id || config?.enterprise_id || config?.name, config])
  );
  return enterpriseRows
    .map((row) => {
      const profile = configMap[row.enterpriseId]?.strategy_profile || {};
      return {
        ...row,
        strategyLabel: profile.label || profile.profile_id || '默认策略',
        acquisitionBias: profile.acquisition_bias || '未声明',
        preferredBand: Array.isArray(profile.preferred_acquisition_band)
          ? profile.preferred_acquisition_band
          : [],
        riskSensitivity: toNumber(profile.resource_risk_sensitivity, null),
        growthPriority: toNumber(profile.growth_priority, null),
      };
    })
    .sort((a, b) => Number(b.plannedTotal || 0) - Number(a.plannedTotal || 0));
};

const AcquisitionSvgChart = ({ rows }) => {
  if (!rows.length) {
    return <EmptyChart />;
  }
  const values = rows.flatMap((row) => [
    row.total_planned_acquisition,
    row.total_effective_acquisition,
    row.sustainable_total_acquisition,
  ]);
  const scale = buildScale(values);
  const helpers = createPointHelpers(rows, scale);
  const band = helpers.width / Math.max(rows.length, 1);
  const barWidth = Math.max(6, Math.min(24, band * 0.56));
  const chartBottom = PADDING.top + helpers.height;

  return (
    <div className="commons-svg-chart-wrap">
      <Legend
        items={[
          { name: '计划获取量', color: COMMONS_COLORS.planned },
          { name: '有效获取量', color: COMMONS_COLORS.effective },
          { name: '可持续线', color: COMMONS_COLORS.sustainable },
        ]}
      />
      <svg className="commons-svg-chart" viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`} role="img">
        <Axis rows={rows} scale={scale} />
        {rows.map((row, index) => {
          const x = helpers.x(index) - barWidth / 2;
          const y = helpers.y(row.total_planned_acquisition);
          const height = chartBottom - y;
          return (
            <rect key={row.round} x={x} y={y} width={barWidth} height={height} rx="4" fill={COMMONS_COLORS.planned} opacity="0.76">
              <title>{`D${row.round} 计划获取量: ${formatNumber(row.total_planned_acquisition, 2)}`}</title>
            </rect>
          );
        })}
        {[
          { name: '有效获取量', color: COMMONS_COLORS.effective, value: (row) => row.total_effective_acquisition },
          { name: '可持续线', color: COMMONS_COLORS.sustainable, value: (row) => row.sustainable_total_acquisition, dashed: true },
        ].map((entry) => {
          const points = rows.map((row, index) => ({
            x: helpers.x(index),
            y: helpers.y(entry.value(row)),
          }));
          return (
            <path
              key={entry.name}
              d={linePath(points)}
              fill="none"
              stroke={entry.color}
              strokeWidth="3"
              strokeDasharray={entry.dashed ? '7 6' : undefined}
            />
          );
        })}
      </svg>
    </div>
  );
};

const StackedEnterpriseSvgChart = ({ rows, enterpriseIds }) => {
  if (!rows.length || !enterpriseIds.length) {
    return <EmptyChart />;
  }
  const totals = rows.map((row) => enterpriseIds.reduce(
    (sum, enterpriseId) => sum + Number(row?.enterprises?.[enterpriseId]?.planned_acquisition || 0),
    0
  ));
  const scale = buildScale(totals);
  const helpers = createPointHelpers(rows, scale);
  const band = helpers.width / Math.max(rows.length, 1);
  const barWidth = Math.max(6, Math.min(26, band * 0.62));
  const chartBottom = PADDING.top + helpers.height;

  return (
    <div className="commons-svg-chart-wrap">
      <Legend items={enterpriseIds.map((id) => ({ name: id, color: ENTERPRISE_COLORS[id] || '#506f85' }))} />
      <svg className="commons-svg-chart" viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`} role="img">
        <Axis rows={rows} scale={scale} />
        {rows.map((row, rowIndex) => {
          let stackedValue = 0;
          return enterpriseIds.map((enterpriseId) => {
            const value = Number(row?.enterprises?.[enterpriseId]?.planned_acquisition || 0);
            const yTop = helpers.y(stackedValue + value);
            const yBottom = helpers.y(stackedValue);
            stackedValue += value;
            return (
              <rect
                key={`${row.round}-${enterpriseId}`}
                x={helpers.x(rowIndex) - barWidth / 2}
                y={yTop}
                width={barWidth}
                height={Math.max(0, yBottom - yTop)}
                fill={ENTERPRISE_COLORS[enterpriseId] || '#506f85'}
                opacity="0.86"
              >
                <title>{`${enterpriseId} D${row.round}: ${formatNumber(value, 2)}`}</title>
              </rect>
            );
          });
        })}
      </svg>
    </div>
  );
};

const StrategyDifferenceChart = ({ rows }) => {
  if (!rows.length) {
    return <EmptyChart message="暂无策略画像数据" detail="当前运行元数据中没有企业策略配置，无法绘制策略差异。" />;
  }
  const maxPlanned = Math.max(...rows.map((row) => Number(row.plannedTotal || 0)), 1);

  return (
    <div className="commons-strategy-list">
      {rows.map((row) => {
        const plannedRatio = Math.max(0.02, Number(row.plannedTotal || 0) / maxPlanned);
        const effectiveRatio = Math.max(0.02, Number(row.effectiveTotal || 0) / maxPlanned);
        return (
          <div className="commons-strategy-row" key={row.enterpriseId}>
            <div className="commons-strategy-head">
              <span>
                <i style={{ background: ENTERPRISE_COLORS[row.enterpriseId] || '#506f85' }} />
                {row.enterpriseId}
              </span>
              <strong>{row.strategyLabel}</strong>
            </div>
            <div className="commons-strategy-meta">
              <span>偏好：{row.acquisitionBias}</span>
              <span>目标带：{row.preferredBand.length ? row.preferredBand.join('-') : '-'}</span>
            </div>
            <div className="commons-strategy-bars">
              <div className="commons-strategy-track">
                <b
                  className="planned"
                  style={{
                    width: `${plannedRatio * 100}%`,
                    background: ENTERPRISE_COLORS[row.enterpriseId] || '#506f85',
                  }}
                />
              </div>
              <div className="commons-strategy-track slim">
                <b
                  className="effective"
                  style={{ width: `${effectiveRatio * 100}%` }}
                />
              </div>
            </div>
            <div className="commons-strategy-values">
              <span>累计计划 {formatNumber(row.plannedTotal, 0)}</span>
              <span>累计有效 {formatNumber(row.effectiveTotal, 0)}</span>
              <span>风险敏感 {formatNumber(row.riskSensitivity, 2)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

function CommonsTragedyView({
  availableDays = [],
  dataRoot,
  enterpriseSpecs = [],
  currentRunId,
  currentRunSourceLabel,
}) {
  const [metrics, setMetrics] = useState([]);
  const [financeRows, setFinanceRows] = useState([]);
  const [productionErrorRows, setProductionErrorRows] = useState([]);
  const [runMeta, setRunMeta] = useState(null);
  const [finalObservers, setFinalObservers] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const enterpriseIds = useMemo(() => {
    const fromSpecs = enterpriseSpecs.map(getEnterpriseId).filter(Boolean);
    if (fromSpecs.length > 0) {
      return fromSpecs;
    }
    return metrics[0]?.enterprises ? Object.keys(metrics[0].enterprises) : [];
  }, [enterpriseSpecs, metrics]);

  useEffect(() => {
    let cancelled = false;
    const loadData = async () => {
      setLoading(true);
      setError(null);
      try {
        const [metaPayload, metricRows] = await Promise.all([
          safeFetchJson(buildDataUrl(dataRoot, 'run_meta.json')),
          loadMetricsForDays(dataRoot, availableDays),
        ]);
        if (cancelled) {
          return;
        }
        setRunMeta(metaPayload);
        setMetrics(metricRows);

        const finalDay = metricRows[metricRows.length - 1]?.round;
        const specEnterpriseIds = enterpriseSpecs.map(getEnterpriseId).filter(Boolean);
        const observerIds = specEnterpriseIds.length > 0
          ? specEnterpriseIds
          : Object.keys(metricRows[0]?.enterprises || {});
        if (Number.isFinite(Number(finalDay))) {
          const [observers, financeTimeline, productionErrors] = await Promise.all([
            loadFinalObservers(dataRoot, finalDay, observerIds),
            loadFinanceRowsForDays(dataRoot, availableDays, observerIds),
            loadProductionErrorRowsForDays(dataRoot, availableDays, observerIds),
          ]);
          if (!cancelled) {
            setFinalObservers(observers);
            setFinanceRows(financeTimeline);
            setProductionErrorRows(productionErrors);
          }
        } else if (!cancelled) {
          setFinalObservers({});
          setFinanceRows([]);
          setProductionErrorRows([]);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError.message || '加载公地悲剧数据失败');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    loadData();
    return () => {
      cancelled = true;
    };
  }, [availableDays, dataRoot, enterpriseSpecs]);

  const summary = useMemo(() => {
    const roundCount = metrics.length;
    const first = metrics[0] || {};
    const last = metrics[metrics.length - 1] || {};
    const overuseDays = metrics.filter((row) => Number(row?.overuse_quantity || 0) > 0).length;
    const initialStock = toNumber(first.resource_stock_before, toNumber(runMeta?.scenario_config?.simulation?.shared_resource_config?.initial_stock_quantity));
    const finalStock = toNumber(last.resource_stock);
    const initialQuality = toNumber(first.resource_quality);
    const finalQuality = toNumber(last.resource_quality);
    const insufficientFundFailures = buildCumulativeErrorRows(productionErrorRows, enterpriseIds);
    const enterpriseRows = buildEnterpriseRows(metrics, finalObservers, enterpriseIds)
      .map((row) => ({
        ...row,
        insufficientFundFailures: insufficientFundFailures[row.enterpriseId] || 0,
      }));
    const totalAgentRounds = enterpriseRows.reduce((sum, row) => sum + row.agentPlanRounds, 0);
    const totalDecisionRounds = enterpriseRows.reduce((sum, row) => sum + row.agentPlanRounds + row.coldStartRounds, 0);
    const leadingEnterprise = enterpriseRows.reduce((winner, row) => (
      !winner || row.plannedTotal > winner.plannedTotal ? row : winner
    ), null);

    return {
      roundCount,
      firstRound: first.round,
      finalRound: last.round,
      overuseDays,
      avgPlanned: average(metrics.map((row) => row.total_planned_acquisition)),
      avgEffective: average(metrics.map((row) => row.total_effective_acquisition)),
      avgOveruse: average(metrics.map((row) => row.overuse_quantity)),
      initialStock,
      finalStock,
      stockDrop: Number.isFinite(initialStock) && Number.isFinite(finalStock) ? initialStock - finalStock : null,
      firstRatio: first.resource_stock_ratio,
      finalRatio: last.resource_stock_ratio,
      initialQuality,
      finalQuality,
      qualityDrop: Number.isFinite(initialQuality) && Number.isFinite(finalQuality) ? initialQuality - finalQuality : null,
      sustainable: toNumber(last.sustainable_total_acquisition, toNumber(first.sustainable_total_acquisition)),
      warningLevel: last.warning_level,
      enterpriseRows,
      leadingEnterprise,
      agentDriven: totalDecisionRounds > 0 && totalAgentRounds / totalDecisionRounds > 0.85,
      totalAgentRounds,
      totalDecisionRounds,
    };
  }, [metrics, finalObservers, enterpriseIds, runMeta, productionErrorRows]);

  const causalityRows = useMemo(() => buildCausalityRows(metrics), [metrics]);
  const cashRows = useMemo(
    () => buildFinanceTimeRows(financeRows, enterpriseIds, 'cash'),
    [financeRows, enterpriseIds]
  );
  const profitRows = useMemo(
    () => buildFinanceTimeRows(financeRows, enterpriseIds, 'netProfit'),
    [financeRows, enterpriseIds]
  );
  const strategyRows = useMemo(
    () => buildStrategyRows(summary.enterpriseRows, runMeta),
    [summary.enterpriseRows, runMeta]
  );
  const highFailureThreshold = 5;
  const warningThreshold = toNumber(
    runMeta?.scenario_config?.simulation?.shared_resource_config?.warning_threshold_ratio,
    0.45
  );

  if (loading) {
    return <div className="commons-empty-state">正在加载公地悲剧实验数据...</div>;
  }

  if (error) {
    return <div className="commons-empty-state warning">{error}</div>;
  }

  if (metrics.length === 0) {
    return (
      <div className="commons-empty-state warning">
        当前任务未读取到 `shared_resource_metrics.json`，请选择 shared_resource_market 场景。
      </div>
    );
  }

  return (
    <div className="commons-page">
      <section className="commons-hero">
        <div className="commons-hero-copy">
          <span className="commons-eyebrow">Commons Tragedy</span>
          <h2>公地悲剧实验解释与验证</h2>
          <p>
            本页面关注同一个公共资源池如何被多家企业共同消耗。脚本只维护资源池、可持续线和结算后果；
            企业是否扩大获取量，由 Agent 在订单、利润、产能和资源状态之间自主决策。
          </p>
          <div className="commons-source-strip">
            <span>任务：{currentRunId || runMeta?.run_id || '-'}</span>
            <span>来源：{currentRunSourceLabel || dataRoot}</span>
            <span>场景：{runMeta?.scenario_id || runMeta?.scenario_config?.meta?.scenario_id || '-'}</span>
            <span>已读取指标：{metrics.length} 轮</span>
          </div>
        </div>
      </section>

      <section className="commons-kpi-grid">
        <div className="commons-kpi-card">
          <span>过度获取轮次</span>
          <strong>{summary.overuseDays}/{summary.roundCount}</strong>
          <small>计划获取量高于可持续线</small>
        </div>
        <div className="commons-kpi-card">
          <span>平均计划获取</span>
          <strong>{formatNumber(summary.avgPlanned, 1)}</strong>
          <small>可持续线：{formatNumber(summary.sustainable, 0)}</small>
        </div>
        <div className="commons-kpi-card warning">
          <span>资源存量下降</span>
          <strong>{formatNumber(summary.stockDrop, 1)}</strong>
          <small>{formatPercent(summary.firstRatio)} 到 {formatPercent(summary.finalRatio)}</small>
        </div>
        <div className="commons-kpi-card warning">
          <span>资源质量下降</span>
          <strong>{formatPercent(summary.qualityDrop)}</strong>
          <small>{formatPercent(summary.initialQuality)} 到 {formatPercent(summary.finalQuality)}</small>
        </div>
        <div className="commons-kpi-card">
          <span>Agent 获取轮次</span>
          <strong>{summary.totalAgentRounds}/{summary.totalDecisionRounds}</strong>
          <small>day0 之外由生产计划驱动</small>
        </div>
        <div className="commons-kpi-card accent">
          <span>主要获取者</span>
          <strong>{summary.leadingEnterprise?.enterpriseId || '-'}</strong>
          <small>累计计划 {formatNumber(summary.leadingEnterprise?.plannedTotal, 0)}</small>
        </div>
      </section>

      <section className="commons-layout">
        <article className="commons-chart-card compact">
          <div className="commons-card-title">资源池退化曲线</div>
          <p className="commons-card-note">
            资源存量比例与资源质量持续下行，是判断公共资源被长期过度使用的直接证据。
          </p>
          <LineSvgChart
            rows={metrics}
            max={1}
            percent
            series={[
              { name: '资源存量比例', color: COMMONS_COLORS.stock, value: (row) => row.resource_stock_ratio },
              { name: '资源质量', color: COMMONS_COLORS.quality, value: (row) => row.resource_quality },
              { name: '预警线', color: COMMONS_COLORS.sustainable, value: () => warningThreshold, dashed: true },
            ]}
          />
        </article>

        <article className="commons-chart-card compact">
          <div className="commons-card-title">计划获取量 vs 可持续线</div>
          <p className="commons-card-note">
            当柱状图长期高于虚线，说明企业合计获取量超过公共资源可持续恢复能力。
          </p>
          <AcquisitionSvgChart rows={metrics} />
        </article>

        <article className="commons-chart-card">
          <div className="commons-card-title">企业获取贡献</div>
          <p className="commons-card-note">
            堆叠柱越高，说明该轮公共资源承压越强；颜色可定位主要贡献企业。
          </p>
          <StackedEnterpriseSvgChart rows={metrics} enterpriseIds={enterpriseIds} />
        </article>

        <article className="commons-chart-card">
          <div className="commons-card-title">不同策略下的累计开采差异</div>
          <p className="commons-card-note">
            将企业策略画像与累计计划/有效获取量放在同一视图中，直观看出不同经营倾向带来的资源占用差异。
          </p>
          <StrategyDifferenceChart rows={strategyRows} />
        </article>

        <article className="commons-chart-card">
          <div className="commons-card-title">有效产出折损</div>
          <p className="commons-card-note">
            资源质量下降后，同样的计划获取量会转化为更低的有效产出。
          </p>
          <LineSvgChart
            rows={metrics}
            max={1}
            percent
            series={[
              {
                name: '有效/计划比',
                color: COMMONS_COLORS.yield,
                value: (row) => (
                  row.total_planned_acquisition > 0
                    ? row.total_effective_acquisition / row.total_planned_acquisition
                    : 0
                ),
              },
              { name: '资源质量', color: COMMONS_COLORS.stock, value: (row) => row.resource_quality },
            ]}
          />
        </article>

        <article className="commons-chart-card evidence-card">
          <div className="commons-card-title">因果链：过度获取累积 vs 资源耗尽</div>
          <p className="commons-card-note">
            橙线表示累计过度获取指数，红线表示资源耗尽比例。如果两条线同步上行，说明资源下降不是自然波动，
            而是企业计划获取量长期高于可持续线后的累积结果。
          </p>
          <LineSvgChart
            rows={causalityRows}
            max={1}
            percent
            series={[
              { name: '累计过度获取指数', color: COMMONS_COLORS.overuse, value: (row) => row.cumulativeOveruseIndex },
              { name: '资源耗尽比例', color: COMMONS_COLORS.depletion, value: (row) => row.depletionRatio },
            ]}
          />
        </article>

        <article className="commons-chart-card">
          <div className="commons-card-title">企业现金曲线</div>
          <p className="commons-card-note">
            现金跌破 0 表示资源退化和成本压力已经从公共资源层传导到企业经营层。
          </p>
          <LineSvgChart
            rows={cashRows}
            floorZero={false}
            series={enterpriseIds.map((enterpriseId) => ({
              name: enterpriseId,
              color: ENTERPRISE_COLORS[enterpriseId] || '#506f85',
              value: (row) => row[enterpriseId],
            }))}
          />
        </article>

        <article className="commons-chart-card">
          <div className="commons-card-title">企业净利润曲线</div>
          <p className="commons-card-note">
            净利润持续走低且转负，说明企业过度获取没有带来长期可持续收益。
          </p>
          <LineSvgChart
            rows={profitRows}
            floorZero={false}
            series={enterpriseIds.map((enterpriseId) => ({
              name: enterpriseId,
              color: ENTERPRISE_COLORS[enterpriseId] || '#506f85',
              value: (row) => row[enterpriseId],
            }))}
          />
        </article>

        <article className="commons-chart-card wide">
          <div className="commons-card-title">企业行为与收益对照</div>
          <div className="commons-table-wrapper">
            <table className="commons-table">
              <thead>
                <tr>
                  <th>企业</th>
                  <th>累计计划获取</th>
                  <th>累计有效获取</th>
                  <th>Agent 计划轮次</th>
                  <th>现金</th>
                  <th>净利润</th>
                  <th title={`累计资金不足失败达到 ${highFailureThreshold} 次及以上时加粗显示`}>资金不足失败</th>
                  <th>完成订单</th>
                  <th>违约订单</th>
                  <th>最终库存</th>
                </tr>
              </thead>
              <tbody>
                {summary.enterpriseRows.map((row) => (
                  <tr key={row.enterpriseId}>
                    <td>
                      <span
                        className="commons-enterprise-dot"
                        style={{ background: ENTERPRISE_COLORS[row.enterpriseId] || '#506f85' }}
                      />
                      {row.enterpriseId}
                    </td>
                    <td>{formatNumber(row.plannedTotal, 0)}</td>
                    <td>{formatNumber(row.effectiveTotal, 0)}</td>
                    <td>{row.agentPlanRounds}</td>
                    <td className={Number(row.cash || 0) < 0 ? 'commons-warning-cell' : ''}>
                      {formatNumber(row.cash, 0)}
                    </td>
                    <td>{formatNumber(row.netProfit, 0)}</td>
                    <td className={Number(row.insufficientFundFailures || 0) >= highFailureThreshold ? 'commons-strong-warning-cell' : ''}>
                      {formatNumber(row.insufficientFundFailures, 0)}
                    </td>
                    <td>{formatNumber(row.completedOrders, 0)}</td>
                    <td className={Number(row.breachedOrders || 0) > 0 ? 'commons-warning-cell' : ''}>
                      {formatNumber(row.breachedOrders, 0)}
                    </td>
                    <td>{formatNumber(row.oreInventory, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="commons-chart-card insight-card">
          <div className="commons-card-title">本次 baseline 说明了什么</div>
          <ul>
            <li>公共资源不是隐藏背景，而是通过 `shared_resource_metrics` 每轮结算并反馈给 Agent。</li>
            <li>无治理 baseline 中，企业可以为了订单和利润持续扩大或维持获取量。</li>
            <li>只要总计划获取量长期越过 `360`，资源存量和质量就会逐步下降。</li>
            <li>后续 quota/tax 场景应重点比较是否降低越线轮次、主要获取者贡献和质量下降速度。</li>
          </ul>
        </article>

        <article className="commons-chart-card insight-card">
          <div className="commons-card-title">对照实验预留判据</div>
          <ul>
            <li>配额组：总获取量应更接近 `360`，主要企业之间获取差异应缩小。</li>
            <li>税收组：过度获取仍可能存在，但平均过度获取量应低于 baseline。</li>
            <li>软提醒组：若仍长期越线，说明信息提示不足以解决公地悲剧。</li>
            <li>治理有效的核心证据是资源质量下降变慢，而不是单轮利润最高。</li>
          </ul>
        </article>
      </section>
    </div>
  );
}

export default CommonsTragedyView;
