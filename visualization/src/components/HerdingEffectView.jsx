import React, { useEffect, useMemo, useState } from 'react';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';

const ENTERPRISE_COLORS = {
  Sensor_A: '#2c6f7d',
  Sensor_B: '#d0862c',
  Sensor_C: '#bc4f38',
  Sensor_D: '#5f7d42',
};

const HERDING_COLORS = {
  heat: '#f59e0b',
  demand: '#0f172a',
  marketHeat: '#7c3aed',
  planned: '#a93f32',
  inventory: '#6f5d8f',
  sync: '#007c89',
  herding: '#e11d48',
  threshold: '#8a979d',
};

const SVG_WIDTH = 920;
const SVG_HEIGHT = 320;
const PADDING = { top: 34, right: 28, bottom: 44, left: 58 };

const toNumber = (value, fallback = null) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const average = (values) => {
  const finite = values.map(Number).filter(Number.isFinite);
  if (finite.length === 0) {
    return null;
  }
  return finite.reduce((sum, value) => sum + value, 0) / finite.length;
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

const getEnterpriseId = (spec) => spec?.enterprise_id || spec?.id || spec?.name;

const normalizeMetricRow = (payload) => {
  const source = payload?.data || payload || {};
  const enterprises = Object.fromEntries(
    Object.entries(source.enterprises || {}).map(([enterpriseId, record]) => ([
      enterpriseId,
      {
        ...record,
        planned_quantity: toNumber(record?.planned_quantity, 0),
        ending_inventory: toNumber(record?.ending_inventory, 0),
        cash_balance: toNumber(record?.cash_balance, null),
      },
    ]))
  );

  return {
    ...source,
    round: toNumber(source.round, 0),
    true_demand_quantity: toNumber(source.true_demand_quantity, 0),
    visible_demand_signal: toNumber(source.visible_demand_signal, 0),
    market_heat: toNumber(source.market_heat, 0),
    total_planned_quantity: toNumber(source.total_planned_quantity, 0),
    overproduction_ratio: toNumber(source.overproduction_ratio, 0),
    overproduction_gap: toNumber(source.overproduction_gap, 0),
    synchronization_index: toNumber(source.synchronization_index, 0),
    herding_index: toNumber(source.herding_index, 0),
    inventory_pressure: toNumber(source.inventory_pressure, 0),
    peer_visibility_enabled: Boolean(source.peer_visibility_enabled),
    enterprises,
    externalDemandByEnterprise: {},
    salesByEnterprise: {},
  };
};

const loadMetricsForDays = async (dataRoot, availableDays) => {
  const rows = [];
  for (const day of availableDays) {
    const payload = await safeFetchJson(
      buildDataUrl(dataRoot, `public/exchange/day${day}/end_of_day/herding_metrics.json`)
    ) || await safeFetchJson(
      buildDataUrl(dataRoot, `public/exchange/day${day}/herding_metrics.json`)
    );
    if (payload) {
      rows.push(normalizeMetricRow(payload));
    }
  }
  return rows.sort((a, b) => Number(a.round) - Number(b.round));
};

const normalizeExternalDemandRow = (payload, day) => {
  const source = payload?.data || payload || {};
  const dayNumber = toNumber(day, day);
  const records = Array.isArray(source.history)
    ? source.history
    : Array.isArray(source.records)
      ? source.records
      : Array.isArray(source.demands)
        ? source.demands
        : [];
  const byEnterprise = {};

  records.forEach((record) => {
    const recordRound = toNumber(record?.round ?? record?.day, dayNumber);
    if (recordRound !== dayNumber) {
      return;
    }
    const enterpriseId = record?.enterprise_id || record?.enterpriseId || record?.seller_id || record?.target_enterprise_id;
    if (!enterpriseId) {
      return;
    }
    const existing = byEnterprise[enterpriseId] || {
      quantity: 0,
      plannedQuantity: 0,
      trueDemandQuantity: 0,
      visibleDemandSignal: 0,
      count: 0,
    };
    byEnterprise[enterpriseId] = {
      quantity: existing.quantity + toNumber(record?.quantity ?? record?.demand_quantity, 0),
      plannedQuantity: existing.plannedQuantity + toNumber(record?.planned_quantity, 0),
      trueDemandQuantity: existing.trueDemandQuantity + toNumber(record?.true_demand_quantity, 0),
      visibleDemandSignal: existing.visibleDemandSignal + toNumber(record?.visible_demand_signal, 0),
      count: existing.count + 1,
    };
  });

  return byEnterprise;
};

const loadExternalDemandForDays = async (dataRoot, availableDays) => {
  const byRound = {};
  for (const day of availableDays) {
    const payload = await safeFetchJson(
      buildDataUrl(dataRoot, `public/exchange/day${day}/end_of_day/external_demand.json`)
    ) || await safeFetchJson(
      buildDataUrl(dataRoot, `public/exchange/day${day}/external_demand.json`)
    );
    if (payload) {
      byRound[day] = normalizeExternalDemandRow(payload, day);
    }
  }
  return byRound;
};

const normalizeSalesRow = (payload) => {
  const source = payload?.data || payload || {};
  return {
    totalQuantitySold: toNumber(
      source.total_quantity_sold ?? source.total_sold_quantity ?? source.fulfilled_quantity,
      null
    ),
    backlogQuantity: toNumber(
      source.backlog_quantity ?? source.confirmed_order_backlog_quantity,
      null
    ),
    lostSalesQuantity: toNumber(source.lost_sales_quantity, null),
  };
};

const loadSalesForDays = async (dataRoot, availableDays, enterpriseIds) => {
  const byRound = {};
  for (const day of availableDays) {
    const roundSales = {};
    for (const enterpriseId of enterpriseIds) {
      const payload = await safeFetchJson(
        buildDataUrl(dataRoot, `enterprises/${enterpriseId}/department/sales/day${day}/sales.json`)
      );
      if (payload) {
        roundSales[enterpriseId] = normalizeSalesRow(payload);
      }
    }
    byRound[day] = roundSales;
  }
  return byRound;
};

const loadRunBundle = async (dataRoot, availableDays) => {
  const [runMeta, metrics, externalDemandByRound] = await Promise.all([
    safeFetchJson(buildDataUrl(dataRoot, 'run_meta.json')),
    loadMetricsForDays(dataRoot, availableDays),
    loadExternalDemandForDays(dataRoot, availableDays),
  ]);
  const enterpriseIds = Object.keys(metrics[0]?.enterprises || {});
  const salesByRound = await loadSalesForDays(dataRoot, availableDays, enterpriseIds);
  const enrichedMetrics = metrics.map((row) => ({
    ...row,
    externalDemandByEnterprise: externalDemandByRound[row.round] || {},
    salesByEnterprise: salesByRound[row.round] || {},
  }));
  return { runMeta, metrics: enrichedMetrics };
};

const getStrategyMap = (runMeta, enterpriseSpecs) => {
  const sources = [
    ...(enterpriseSpecs || []),
    ...(runMeta?.scenario_config?.enterprise_specs || []),
    ...(runMeta?.scenario_config?.enterprise_configs || []),
  ];
  return Object.fromEntries(
    sources
      .map((spec) => [getEnterpriseId(spec), spec?.strategy_profile || {}])
      .filter(([enterpriseId]) => Boolean(enterpriseId))
  );
};

const buildScale = (values, {
  min = null,
  max = null,
  floorZero = true,
  nice = true,
} = {}) => {
  const finite = values.map(Number).filter(Number.isFinite);
  if (finite.length === 0) {
    return { min: 0, max: 1 };
  }
  const rawMin = min ?? (floorZero ? Math.min(0, ...finite) : Math.min(...finite));
  const rawMax = max ?? Math.max(1, ...finite);
  if (!nice) {
    return { min: rawMin, max: rawMax || 1 };
  }
  const span = rawMax - rawMin;
  const padding = span === 0 ? Math.abs(rawMax) * 0.1 || 1 : span * 0.08;
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
    <g className="herding-svg-axis">
      <line x1={PADDING.left} y1={PADDING.top + height} x2={PADDING.left + width} y2={PADDING.top + height} />
      <line x1={PADDING.left} y1={PADDING.top} x2={PADDING.left} y2={PADDING.top + height} />
      {ticks.map((tick) => (
        <g key={tick}>
          <line x1={PADDING.left} y1={y(tick)} x2={PADDING.left + width} y2={y(tick)} className="herding-svg-grid-line" />
          <text x={PADDING.left - 8} y={y(tick) + 4} textAnchor="end">{formatter(tick)}</text>
        </g>
      ))}
      {labelIndexes.map((index) => (
        <text key={index} x={x(index)} y={PADDING.top + height + 24} textAnchor="middle">
          D{rows[index]?.round}
        </text>
      ))}
    </g>
  );
};

const Legend = ({ items }) => (
  <div className="herding-svg-legend">
    {items.map((item) => (
      <span key={item.name}>
        <i style={{ background: item.color }} />
        {item.name}
      </span>
    ))}
  </div>
);

const EmptyChart = ({ message = '暂无可绘制数据', detail = null }) => (
  <div className="herding-svg-empty">
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
  const scale = buildScale(values, { min, max, floorZero, nice: max === null || min === null });
  const helpers = createPointHelpers(rows, scale);

  return (
    <div className="herding-svg-chart-wrap">
      <Legend items={series} />
      <svg className="herding-svg-chart" viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`} role="img">
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
                strokeWidth={entry.bold ? '4' : '3'}
                strokeDasharray={entry.dashed ? '7 6' : undefined}
                opacity={entry.opacity ?? 1}
              />
              {!entry.dashed && points.map((point, index) => (
                <circle key={index} cx={point.x} cy={point.y} r="3.6" fill={entry.color}>
                  <title>
                    {`${entry.name} D${rows[index].round}: ${percent ? formatPercent(entry.value(rows[index])) : formatNumber(entry.value(rows[index]), 2)}`}
                  </title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
};

const BarLineSvgChart = ({ rows }) => {
  if (!rows.length) {
    return <EmptyChart />;
  }
  const values = rows.flatMap((row) => [
    row.total_planned_quantity,
    row.true_demand_quantity,
    row.visible_demand_signal,
  ]);
  const scale = buildScale(values);
  const helpers = createPointHelpers(rows, scale);
  const band = helpers.width / Math.max(rows.length, 1);
  const barWidth = Math.max(6, Math.min(26, band * 0.58));
  const chartBottom = PADDING.top + helpers.height;

  return (
    <div className="herding-svg-chart-wrap">
      <Legend
        items={[
          { name: '总计划量', color: HERDING_COLORS.planned },
          { name: '真实需求', color: HERDING_COLORS.demand },
          { name: '可见需求信号', color: HERDING_COLORS.heat },
        ]}
      />
      <svg className="herding-svg-chart" viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`} role="img">
        <Axis rows={rows} scale={scale} />
        {rows.map((row, index) => {
          const y = helpers.y(row.total_planned_quantity);
          const height = chartBottom - y;
          return (
            <rect
              key={row.round}
              x={helpers.x(index) - barWidth / 2}
              y={y}
              width={barWidth}
              height={Math.max(0, height)}
              rx="4"
              fill={HERDING_COLORS.planned}
              opacity="0.72"
            >
              <title>{`D${row.round} 总计划量: ${formatNumber(row.total_planned_quantity, 2)}`}</title>
            </rect>
          );
        })}
        {[
          { name: '真实需求', color: HERDING_COLORS.demand, value: (row) => row.true_demand_quantity },
          { name: '可见需求信号', color: HERDING_COLORS.heat, value: (row) => row.visible_demand_signal, dashed: true },
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

const EnterprisePlanChart = ({ rows, enterpriseIds }) => (
  <LineSvgChart
    rows={rows}
    series={enterpriseIds.map((enterpriseId) => ({
      name: enterpriseId,
      color: ENTERPRISE_COLORS[enterpriseId] || '#52616a',
      value: (row) => row?.enterprises?.[enterpriseId]?.planned_quantity,
    }))}
  />
);

const buildEnterpriseConvergenceRows = (metrics, enterpriseIds) => (
  metrics.map((row) => {
    const values = enterpriseIds.map((enterpriseId) => (
      Number(row?.enterprises?.[enterpriseId]?.planned_quantity || 0)
    ));
    const mean = average(values) ?? 0;
    const variance = average(values.map((value) => (value - mean) ** 2)) ?? 0;
    const coefficientVariation = mean > 0 ? Math.sqrt(variance) / mean : 0;
    const range = values.length > 0 ? Math.max(...values) - Math.min(...values) : 0;
    const rangeRatio = mean > 0 ? range / mean : 0;
    return {
      ...row,
      productionDifference: Math.max(0, Math.min(1, coefficientVariation)),
      productionSpread: Math.max(0, Math.min(1, rangeRatio / 2)),
    };
  })
);

const EnterpriseConvergenceChart = ({ rows, enterpriseIds }) => {
  const convergenceRows = buildEnterpriseConvergenceRows(rows, enterpriseIds);
  return (
    <LineSvgChart
      rows={convergenceRows}
      max={1}
      min={0}
      percent
      series={[
        {
          name: '生产差异度',
          color: HERDING_COLORS.herding,
          value: (row) => row.productionDifference,
          bold: true,
        },
        {
          name: '极差差异度',
          color: HERDING_COLORS.heat,
          value: (row) => row.productionSpread,
          dashed: true,
        },
        {
          name: '行为同步度',
          color: HERDING_COLORS.sync,
          value: (row) => row.synchronization_index,
          bold: true,
        },
      ]}
    />
  );
};

const MiniOperationTrend = ({ rows, enterpriseId, enterpriseCount }) => {
  const hasSalesData = rows.some((row) => {
    const value = row?.salesByEnterprise?.[enterpriseId]?.totalQuantitySold;
    return value !== null && value !== undefined && Number.isFinite(Number(value));
  });
  const points = rows.map((row) => {
    const directDemand = row?.externalDemandByEnterprise?.[enterpriseId]?.quantity;
    return {
      round: row.round,
      planned: toNumber(row?.enterprises?.[enterpriseId]?.planned_quantity, 0),
      salesOrDemand: hasSalesData
        ? toNumber(row?.salesByEnterprise?.[enterpriseId]?.totalQuantitySold, 0)
        : toNumber(directDemand, Number(row.true_demand_quantity || 0) / Math.max(enterpriseCount, 1)),
      inventory: toNumber(row?.enterprises?.[enterpriseId]?.ending_inventory, 0),
    };
  });
  const series = [
    { key: 'planned', name: '生产计划', color: HERDING_COLORS.planned },
    { key: 'salesOrDemand', name: hasSalesData ? '销售完成' : '需求输入', color: HERDING_COLORS.demand },
    { key: 'inventory', name: '期末库存', color: HERDING_COLORS.inventory },
  ];
  const values = points.flatMap((point) => series.map((entry) => point[entry.key]));
  const scale = buildScale(values);
  const width = 360;
  const height = 118;
  const padding = { top: 12, right: 12, bottom: 20, left: 34 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (points.length <= 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = (value) => padding.top + innerHeight - ((Number(value || 0) - scale.min) / (scale.max - scale.min || 1)) * innerHeight;
  const labelIndexes = points.length <= 6
    ? points.map((_, index) => index)
    : [0, Math.floor((points.length - 1) / 2), points.length - 1];

  return (
    <div className="herding-mini-trend">
      <div className="herding-mini-legend">
        {series.map((entry) => (
          <span key={entry.key}>
            <i style={{ background: entry.color }} />
            {entry.name}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        <line x1={padding.left} y1={padding.top + innerHeight} x2={padding.left + innerWidth} y2={padding.top + innerHeight} />
        <line x1={padding.left} y1={padding.top} x2={padding.left} y2={padding.top + innerHeight} />
        {[scale.min, scale.max].map((tick) => (
          <g key={tick}>
            <line x1={padding.left} y1={y(tick)} x2={padding.left + innerWidth} y2={y(tick)} className="herding-mini-grid" />
            <text x={padding.left - 7} y={y(tick) + 4} textAnchor="end">{formatNumber(tick, 0)}</text>
          </g>
        ))}
        {series.map((entry) => {
          const path = linePath(points.map((point, index) => ({
            x: x(index),
            y: y(point[entry.key]),
          })));
          return (
            <path
              key={entry.key}
              d={path}
              fill="none"
              stroke={entry.color}
              strokeWidth={entry.key === 'planned' ? '3' : '2.3'}
              opacity={entry.key === 'inventory' ? 0.78 : 1}
            />
          );
        })}
        {labelIndexes.map((index) => (
          <text key={index} x={x(index)} y={height - 4} textAnchor="middle">D{points[index]?.round}</text>
        ))}
      </svg>
    </div>
  );
};

const EnterpriseOperationMatrix = ({ rows, enterpriseIds, strategyMap }) => {
  if (!rows.length || !enterpriseIds.length) {
    return <EmptyChart message="暂无企业运营数据" />;
  }
  return (
    <div className="herding-operation-matrix">
      {enterpriseIds.map((enterpriseId) => {
        const finalRow = rows[rows.length - 1] || {};
        const cumulativePlanned = rows.reduce(
          (sum, row) => sum + Number(row?.enterprises?.[enterpriseId]?.planned_quantity || 0),
          0
        );
        const cumulativeDemand = rows.reduce((sum, row) => (
          sum + Number(
            row?.salesByEnterprise?.[enterpriseId]?.totalQuantitySold
            ?? row?.externalDemandByEnterprise?.[enterpriseId]?.quantity
            ?? 0
          )
        ), 0);
        const finalInventory = finalRow?.enterprises?.[enterpriseId]?.ending_inventory;
        const profile = strategyMap[enterpriseId] || {};
        return (
          <div className="herding-operation-card" key={enterpriseId}>
            <div className="herding-operation-head">
              <span>
                <i style={{ background: ENTERPRISE_COLORS[enterpriseId] || '#52616a' }} />
                {enterpriseId}
              </span>
              <strong>{profile?.label || profile?.profile_id || '未声明策略'}</strong>
            </div>
            <MiniOperationTrend rows={rows} enterpriseId={enterpriseId} enterpriseCount={enterpriseIds.length} />
            <div className="herding-operation-values">
              <span>累计生产计划 {formatNumber(cumulativePlanned, 0)}</span>
              <span>累计销售/需求 {formatNumber(cumulativeDemand, 0)}</span>
              <span>期末库存 {formatNumber(finalInventory, 0)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const buildWindowStats = (rows, windows) => (
  windows.map((window) => {
    const selected = rows.filter((row) => row.round >= window.start && row.round <= window.end);
    return {
      ...window,
      herding: average(selected.map((row) => row.herding_index)),
      sync: average(selected.map((row) => row.synchronization_index)),
      overRatio: average(selected.map((row) => row.overproduction_ratio)),
      total: average(selected.map((row) => row.total_planned_quantity)),
      inventoryPressure: average(selected.map((row) => row.inventory_pressure)),
    };
  })
);

const buildEnterpriseBehaviorRows = (metrics, enterpriseIds, strategyMap) => {
  const totalPlannedAll = metrics.reduce((sum, row) => sum + Number(row.total_planned_quantity || 0), 0);
  return enterpriseIds.map((enterpriseId) => {
    const values = metrics.map((row) => Number(row?.enterprises?.[enterpriseId]?.planned_quantity || 0));
    const cumulativePlanned = values.reduce((sum, value) => sum + value, 0);
    const activeRounds = values.filter((value) => value > 0).length;
    const highOutputRounds = metrics.filter((row) => (
      Number(row?.enterprises?.[enterpriseId]?.planned_quantity || 0) > Number(row.true_demand_quantity || 0) / Math.max(enterpriseIds.length, 1)
    )).length;
    const avgDemandShareGap = average(metrics.map((row) => {
      const demandShare = Number(row.true_demand_quantity || 0) / Math.max(enterpriseIds.length, 1);
      return Number(row?.enterprises?.[enterpriseId]?.planned_quantity || 0) - demandShare;
    }));
    const profile = strategyMap[enterpriseId] || {};
    return {
      enterpriseId,
      profile,
      cumulativePlanned,
      averagePlanned: average(values),
      maxPlanned: Math.max(...values, 0),
      activeRounds,
      highOutputRounds,
      avgDemandShareGap,
      totalShare: totalPlannedAll > 0 ? cumulativePlanned / totalPlannedAll : 0,
      finalInventory: metrics[metrics.length - 1]?.enterprises?.[enterpriseId]?.ending_inventory,
    };
  }).sort((a, b) => Number(b.cumulativePlanned || 0) - Number(a.cumulativePlanned || 0));
};

const buildSummary = (metrics, enterpriseIds, behaviorRows) => {
  const windows = [
    { key: 'heatRise', label: '热度上升', start: 3, end: 5 },
    { key: 'herding', label: '羊群窗口', start: 6, end: 9 },
    { key: 'late', label: '后段低热度', start: 10, end: 16 },
  ];
  const windowStats = buildWindowStats(metrics, windows);
  const last = metrics[metrics.length - 1] || {};
  const leading = behaviorRows[0] || null;
  const cautious = behaviorRows.reduce((best, row) => (
    !best || Number(row.profile?.inventory_risk_sensitivity || 0) > Number(best.profile?.inventory_risk_sensitivity || 0)
      ? row
      : best
  ), null);

  return {
    roundCount: metrics.length,
    finalRound: last.round,
    productId: metrics[0]?.product_id || 'smart_sensor',
    peerVisible: metrics[0]?.peer_visibility_enabled === true,
    avgSync: average(metrics.slice(3).map((row) => row.synchronization_index)),
    avgHerding: average(metrics.slice(3).map((row) => row.herding_index)),
    maxOverRatio: Math.max(...metrics.map((row) => Number(row.overproduction_ratio || 0)), 0),
    overProductionRounds: metrics.filter((row) => Number(row.overproduction_ratio || 0) > 1.15).length,
    finalInventoryPressure: last.inventory_pressure,
    windowStats,
    leading,
    cautious,
    enterpriseCount: enterpriseIds.length,
  };
};

const StrategySensitivityBars = ({ profile }) => {
  const items = [
    ['市场热度', profile?.market_heat_sensitivity],
    ['同业信号', profile?.peer_signal_sensitivity],
    ['库存风险', profile?.inventory_risk_sensitivity],
    ['现金风险', profile?.cash_risk_sensitivity],
  ];
  return (
    <div className="herding-sensitivity-bars">
      {items.map(([label, value]) => (
        <div className="herding-sensitivity-row" key={label}>
          <span>{label}</span>
          <b>
            <i style={{ width: `${Math.max(2, Math.min(1, Number(value || 0)) * 100)}%` }} />
          </b>
          <em>{formatNumber(value, 2)}</em>
        </div>
      ))}
    </div>
  );
};

const StrategyBehaviorPanel = ({ rows }) => {
  if (!rows.length) {
    return <EmptyChart message="暂无企业策略数据" detail="当前运行元数据没有 strategy_profile，无法展示策略差异。" />;
  }
  const maxPlanned = Math.max(...rows.map((row) => Number(row.cumulativePlanned || 0)), 1);
  return (
    <div className="herding-strategy-panel">
      {rows.map((row) => (
        <div className="herding-strategy-card" key={row.enterpriseId}>
          <div className="herding-strategy-head">
            <span>
              <i style={{ background: ENTERPRISE_COLORS[row.enterpriseId] || '#52616a' }} />
              {row.enterpriseId}
            </span>
            <strong>{row.profile?.label || row.profile?.profile_id || '未声明策略'}</strong>
          </div>
          <StrategySensitivityBars profile={row.profile} />
          <div className="herding-strategy-output">
            <div className="herding-strategy-track">
              <b
                style={{
                  width: `${Math.max(3, (Number(row.cumulativePlanned || 0) / maxPlanned) * 100)}%`,
                  background: ENTERPRISE_COLORS[row.enterpriseId] || '#52616a',
                }}
              />
            </div>
            <div className="herding-strategy-values">
              <span>累计计划 {formatNumber(row.cumulativePlanned, 0)}</span>
              <span>峰值 {formatNumber(row.maxPlanned, 0)}</span>
              <span>高于需求份额 {row.highOutputRounds} 轮</span>
              <span>最终库存 {formatNumber(row.finalInventory, 0)}</span>
            </div>
          </div>
          {row.profile?.decision_note && (
            <p>{row.profile.decision_note}</p>
          )}
        </div>
      ))}
    </div>
  );
};

const EnterpriseContributionRecords = ({ rows }) => {
  if (!rows.length) {
    return null;
  }
  return (
    <section className="herding-contribution-records" aria-label="不同企业累计扩产贡献记录">
      <div className="herding-records-title">
        <span>不同企业累计扩产贡献</span>
        <small>由各企业逐轮生产计划累计得到，用于判断哪类策略贡献了更多扩产。</small>
      </div>
      <div className="herding-record-grid">
        {rows.map((row) => (
          <div className="herding-record-card" key={row.enterpriseId}>
            <div className="herding-record-head">
              <span>
                <i style={{ background: ENTERPRISE_COLORS[row.enterpriseId] || '#52616a' }} />
                {row.enterpriseId}
              </span>
              <strong>{formatPercent(row.totalShare)}</strong>
            </div>
            <dl>
              <dt>累计计划</dt>
              <dd>{formatNumber(row.cumulativePlanned, 0)}</dd>
              <dt>平均计划</dt>
              <dd>{formatNumber(row.averagePlanned, 1)}</dd>
              <dt>需求份额差</dt>
              <dd className={Number(row.avgDemandShareGap || 0) > 0 ? 'warning' : ''}>
                {formatNumber(row.avgDemandShareGap, 1)}
              </dd>
              <dt>最终库存</dt>
              <dd>{formatNumber(row.finalInventory, 0)}</dd>
            </dl>
            <small>{row.profile?.label || row.profile?.profile_id || '未声明策略'}</small>
          </div>
        ))}
      </div>
    </section>
  );
};

const WindowStatsPanel = ({ rows }) => (
  <div className="herding-window-panel">
    {rows.map((row) => (
      <div className="herding-window-card" key={row.key}>
        <div>
          <span>{row.label}</span>
          <strong>D{row.start}-D{row.end}</strong>
        </div>
        <dl>
          <dt>同步度</dt>
          <dd>{formatNumber(row.sync, 3)}</dd>
          <dt>羊群指数</dt>
          <dd>{formatNumber(row.herding, 3)}</dd>
          <dt>过度生产比</dt>
          <dd>{formatNumber(row.overRatio, 2)}</dd>
          <dt>总计划均值</dt>
          <dd>{formatNumber(row.total, 1)}</dd>
        </dl>
      </div>
    ))}
  </div>
);

const EnterpriseHeatTable = ({ rows, enterpriseIds }) => {
  if (!rows.length || !enterpriseIds.length) {
    return <EmptyChart message="暂无企业计划数据" />;
  }
  const maxPlan = Math.max(
    ...rows.flatMap((row) => enterpriseIds.map((enterpriseId) => Number(row?.enterprises?.[enterpriseId]?.planned_quantity || 0))),
    1
  );
  return (
    <div className="herding-table-wrapper">
      <table className="herding-table">
        <thead>
          <tr>
            <th>轮次</th>
            {enterpriseIds.map((enterpriseId) => (
              <th key={enterpriseId}>{enterpriseId}</th>
            ))}
            <th>同步度</th>
            <th>总计划 / 真实需求</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.round}>
              <td>D{row.round}</td>
              {enterpriseIds.map((enterpriseId) => {
                const value = Number(row?.enterprises?.[enterpriseId]?.planned_quantity || 0);
                const alpha = 0.12 + (value / maxPlan) * 0.7;
                return (
                  <td key={enterpriseId}>
                    <span
                      className="herding-heat-cell"
                      style={{
                        background: `rgba(31, 111, 122, ${alpha})`,
                        color: alpha > 0.5 ? '#fff' : '#1c2d34',
                      }}
                    >
                      {formatNumber(value, 0)}
                    </span>
                  </td>
                );
              })}
              <td className={row.synchronization_index >= 0.72 ? 'herding-strong-cell' : ''}>
                {formatNumber(row.synchronization_index, 3)}
              </td>
              <td className={row.overproduction_ratio > 1.15 ? 'herding-warning-cell' : ''}>
                {formatNumber(row.overproduction_ratio, 2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

function HerdingEffectView({
  availableDays = [],
  dataRoot,
  enterpriseSpecs = [],
  currentRunId,
  currentRunSourceLabel,
}) {
  const [bundle, setBundle] = useState({ runMeta: null, metrics: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const days = useMemo(() => (
    availableDays.length > 0 ? availableDays : Array.from({ length: 18 }, (_, index) => index)
  ), [availableDays]);

  useEffect(() => {
    let cancelled = false;
    const loadData = async () => {
      setLoading(true);
      setError(null);
      try {
        const current = await loadRunBundle(dataRoot, days);
        if (!cancelled) {
          setBundle(current);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError.message || '加载羊群效应数据失败');
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
  }, [days, dataRoot]);

  const enterpriseIds = useMemo(() => {
    const fromSpecs = enterpriseSpecs.map(getEnterpriseId).filter(Boolean);
    if (fromSpecs.length > 0) {
      return fromSpecs;
    }
    return Object.keys(bundle.metrics[0]?.enterprises || {});
  }, [enterpriseSpecs, bundle.metrics]);

  const strategyMap = useMemo(
    () => getStrategyMap(bundle.runMeta, enterpriseSpecs),
    [bundle.runMeta, enterpriseSpecs]
  );

  const behaviorRows = useMemo(
    () => buildEnterpriseBehaviorRows(bundle.metrics, enterpriseIds, strategyMap),
    [bundle.metrics, enterpriseIds, strategyMap]
  );

  const summary = useMemo(
    () => buildSummary(bundle.metrics, enterpriseIds, behaviorRows),
    [bundle.metrics, enterpriseIds, behaviorRows]
  );

  const scenarioId = bundle.runMeta?.scenario_id || bundle.runMeta?.scenario_config?.meta?.scenario_id;
  const herdingConfig = bundle.runMeta?.scenario_config?.simulation?.herding_config || {};
  const peerVisibleLabel = summary.peerVisible ? '同业摘要可见' : '仅市场热度可见';

  if (loading) {
    return <div className="herding-empty-state">正在加载羊群效应实验数据...</div>;
  }

  if (error) {
    return <div className="herding-empty-state warning">{error}</div>;
  }

  if (!bundle.metrics.length) {
    return (
      <div className="herding-empty-state warning">
        当前任务未读取到 `herding_metrics.json`，请选择 herding_market 场景。
      </div>
    );
  }

  return (
    <div className="herding-page">
      <section className="herding-hero">
        <div className="herding-hero-copy">
          <span className="herding-eyebrow">Herding Effect</span>
          <h2>羊群效应单组运行分析</h2>
          <p>
            本页面只读取当前选中的模拟任务，展示该组实验内部的市场信号、生产同步、过度生产和企业策略差异。
            是否能验证羊群效应，需要观察：同业信号是否可见、同步度是否在市场回落后仍维持、以及不同策略企业是否呈现不同扩产强度。
          </p>
          <div className="herding-source-strip">
            <span>当前任务：{currentRunId || bundle.runMeta?.run_id || '-'}</span>
            <span>当前来源：{currentRunSourceLabel || dataRoot}</span>
            <span>当前场景：{scenarioId || '-'}</span>
            <span>商品：{herdingConfig.product_id || summary.productId}</span>
            <span>同业信号：{peerVisibleLabel}</span>
          </div>
        </div>
        <aside className="herding-proof-card">
          <span>本组读数</span>
          <strong>{summary.peerVisible ? '可观察羊群形成' : '观察无同业对照'}</strong>
          <p>
            D3 后平均同步度 {formatNumber(summary.avgSync, 3)}，平均羊群指数 {formatNumber(summary.avgHerding, 3)}。
            过度生产轮次 {summary.overProductionRounds}/{summary.roundCount}，最高过度生产比 {formatNumber(summary.maxOverRatio, 2)}。
          </p>
        </aside>
      </section>

      <section className="herding-kpi-grid">
        <div className="herding-kpi-card accent">
          <span>当前场景类型</span>
          <strong>{peerVisibleLabel}</strong>
          <small>{scenarioId || '-'}</small>
        </div>
        <div className="herding-kpi-card">
          <span>D3 后平均同步度</span>
          <strong>{formatNumber(summary.avgSync, 3)}</strong>
          <small>0.72 以上代表高度趋同</small>
        </div>
        <div className="herding-kpi-card">
          <span>D3 后平均羊群指数</span>
          <strong>{formatNumber(summary.avgHerding, 3)}</strong>
          <small>综合同步、热度与过度生产</small>
        </div>
        <div className="herding-kpi-card warning">
          <span>过度生产轮次</span>
          <strong>{summary.overProductionRounds}/{summary.roundCount}</strong>
          <small>阈值：总计划 / 真实需求 &gt; 1.15</small>
        </div>
        <div className="herding-kpi-card">
          <span>主要扩产企业</span>
          <strong>{summary.leading?.enterpriseId || '-'}</strong>
          <small>累计计划 {formatNumber(summary.leading?.cumulativePlanned, 0)}</small>
        </div>
        <div className="herding-kpi-card accent">
          <span>最高风险敏感</span>
          <strong>{summary.cautious?.enterpriseId || '-'}</strong>
          <small>{summary.cautious?.profile?.label || '未声明策略'}</small>
        </div>
      </section>

      <EnterpriseContributionRecords rows={behaviorRows} />

      <section className="herding-layout">
        <article className="herding-chart-card evidence-card">
          <div className="herding-card-title">市场背景：真实需求与可见信号</div>
          <p className="herding-card-note">
            保留外部环境变化作为参照：真实需求、Agent 可见需求信号与市场热度。企业行为差异放到右侧矩阵中观察。
          </p>
          <LineSvgChart
            rows={bundle.metrics}
            series={[
              { name: '真实需求', color: HERDING_COLORS.demand, value: (row) => row.true_demand_quantity, bold: true },
              { name: '可见需求信号', color: HERDING_COLORS.heat, value: (row) => row.visible_demand_signal, dashed: true },
              { name: '市场热度 ×100', color: HERDING_COLORS.marketHeat, value: (row) => Number(row.market_heat || 0) * 100, opacity: 0.82 },
            ]}
          />
        </article>

        <article className="herding-chart-card evidence-card">
          <div className="herding-card-title">企业生产-销售-库存差异</div>
          <p className="herding-card-note">
            每个小面板对应一家企业，展示生产计划、销售完成或需求输入、期末库存的连续变化，用来观察不同策略是否带来不同经营轨迹。
          </p>
          <EnterpriseOperationMatrix rows={bundle.metrics} enterpriseIds={enterpriseIds} strategyMap={strategyMap} />
        </article>

        <article className="herding-chart-card">
          <div className="herding-card-title">同步度与羊群指数</div>
          <p className="herding-card-note">
            同步度直接描述企业计划是否趋同；羊群指数用于综合识别同步扩产、热度和过度生产。
          </p>
          <LineSvgChart
            rows={bundle.metrics}
            max={1}
            min={0}
            percent
            series={[
              { name: '同步度', color: HERDING_COLORS.sync, value: (row) => row.synchronization_index, bold: true },
              { name: '羊群指数', color: HERDING_COLORS.herding, value: (row) => row.herding_index },
              { name: '同步阈值 0.72', color: HERDING_COLORS.threshold, value: () => 0.72, dashed: true },
            ]}
          />
        </article>

        <article className="herding-chart-card">
          <div className="herding-card-title">企业差异到趋同路径</div>
          <p className="herding-card-note">
            红线表示企业生产计划的离散程度，蓝线表示行为同步度。若红线从高位回落、蓝线同步上升，就能直观看到“原本有差异，随后被羊群效应推向趋同”的过程。
          </p>
          <EnterpriseConvergenceChart rows={bundle.metrics} enterpriseIds={enterpriseIds} />
        </article>

        <article className="herding-chart-card">
          <div className="herding-card-title">阶段窗口读数</div>
          <p className="herding-card-note">
            将本组运行分为热度上升、羊群窗口和后段低热度，便于判断同步是否只是短期共同信号，还是持续惯性。
          </p>
          <WindowStatsPanel rows={summary.windowStats} />
        </article>

        <article className="herding-chart-card">
          <div className="herding-card-title">企业生产计划曲线</div>
          <p className="herding-card-note">
            若曲线聚拢，说明企业行为趋同；若曲线分叉，说明策略、库存或风险约束让企业出现差异化反应。
          </p>
          <EnterprisePlanChart rows={bundle.metrics} enterpriseIds={enterpriseIds} />
        </article>

        <article className="herding-chart-card wide">
          <div className="herding-card-title">策略画像 vs 实际生产行为</div>
          <p className="herding-card-note">
            左侧是配置中心写入 Agent 观察层的策略偏好，右侧是本次运行实际计划量。用它判断不同策略是否真的带来不同企业行为。
          </p>
          <StrategyBehaviorPanel rows={behaviorRows} />
        </article>

        <article className="herding-chart-card">
          <div className="herding-card-title">库存压力与过度生产</div>
          <p className="herding-card-note">
            如果过度生产比上升后库存压力也上行，说明同步扩产开始传导为经营后果。
          </p>
          <LineSvgChart
            rows={bundle.metrics}
            series={[
              { name: '过度生产比', color: HERDING_COLORS.planned, value: (row) => row.overproduction_ratio },
              { name: '库存压力', color: HERDING_COLORS.inventory, value: (row) => row.inventory_pressure },
              { name: '过度生产阈值 1.15', color: HERDING_COLORS.threshold, value: () => 1.15, dashed: true },
            ]}
          />
        </article>

        <article className="herding-chart-card">
          <div className="herding-card-title">逐轮企业计划热力表</div>
          <p className="herding-card-note">
            颜色越深表示该企业该轮计划量越高；同步度和过度生产比高亮用于定位羊群窗口。
          </p>
          <EnterpriseHeatTable rows={bundle.metrics} enterpriseIds={enterpriseIds} />
        </article>
      </section>
    </div>
  );
}

export default HerdingEffectView;
