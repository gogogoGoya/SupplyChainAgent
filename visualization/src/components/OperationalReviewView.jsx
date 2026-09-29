import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';
import {
  convertQuantityByItem,
  getDisplayItemLabel,
  getQuantityAxisLabel,
  getQuantityColumnLabel,
  sumConvertedFieldByItemMap,
} from '../utils/productEquivalent';

const FLOW_COLORS = ['#4f7cff', '#21a67a', '#f2994a', '#d14d72', '#9b51e0', '#56ccf2'];

const formatNumber = (value) => {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(numeric);
};

const formatPercent = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  return `${(numeric * 100).toFixed(1)}%`;
};

const getState = (payload) => payload?.self_state || {};

const toNumber = (value, fallback = 0) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const sumField = (items, field) =>
  Object.values(items || {}).reduce((sum, item) => sum + toNumber(item?.[field]), 0);

const indexByItemId = (items) =>
  (items || []).reduce((map, item) => {
    if (item?.item_id) {
      map[item.item_id] = item;
    }
    return map;
  }, {});

const indexLatestByMaterial = (items) =>
  (items || []).reduce((map, item) => {
    if (item?.material_id) {
      map[item.material_id] = item;
    }
    return map;
  }, {});

const deriveSalesSummary = (salesState) => {
  if (salesState?.service_level_summary) {
    return salesState.service_level_summary;
  }

  const metrics = salesState?.sales_metrics || {};
  const backlogByProduct = salesState?.demand_backlog?.by_product || {};
  const totalDemand = toNumber(
    metrics.total_downstream_demand,
    sumField(backlogByProduct, 'received_quantity')
  );
  const fulfilledDemand = toNumber(
    metrics.fulfilled_downstream_demand,
    sumField(backlogByProduct, 'fulfilled_quantity')
  );
  const backlogQuantity = toNumber(
    metrics.backlog_quantity,
    sumField(backlogByProduct, 'backlog_quantity')
  );
  const lostSalesQuantity = toNumber(
    metrics.lost_sales_quantity,
    sumField(backlogByProduct, 'lost_sales_quantity')
  );
  const fillRate = totalDemand > 0
    ? fulfilledDemand / totalDemand
    : toNumber(metrics.order_fulfillment_rate);

  return {
    fill_rate: fillRate,
    backlog_quantity: backlogQuantity,
    lost_sales_quantity: lostSalesQuantity,
    total_downstream_demand: totalDemand,
    fulfilled_downstream_demand: fulfilledDemand,
    backlog_by_product: backlogByProduct,
    lost_sales_by_product: Object.fromEntries(
      Object.entries(backlogByProduct).map(([productId, detail]) => [
        productId,
        toNumber(detail?.lost_sales_quantity)
      ])
    )
  };
};

const deriveOperationalSummary = (procurementState, inventoryState) => {
  const replenishment = procurementState?.replenishment || {};
  const latestHistoryByMaterial = indexLatestByMaterial(replenishment.history);
  const latestRequestByMaterial = indexLatestByMaterial(replenishment.requests);
  const inventoryItemMap = indexByItemId(inventoryState?.inventory_items);

  const fallbackMaterials = new Set([
    ...Object.keys(latestHistoryByMaterial),
    ...Object.keys(replenishment.pending_by_material || {}),
    ...Object.keys(inventoryItemMap),
    ...(procurementState?.purchasable_materials_idList || [])
  ]);

  const fallbackInventoryByMaterial = {};
  const fallbackLatestReplenishmentByMaterial = {};

  for (const materialId of fallbackMaterials) {
    const history = latestHistoryByMaterial[materialId] || {};
    const inventoryItem = inventoryItemMap[materialId] || {};
    const onHand = toNumber(history.on_hand_quantity, toNumber(inventoryItem.quantity));
    const incoming = toNumber(history.incoming_quantity);
    const backlog = toNumber(history.backlog_quantity);
    const inventoryPosition = toNumber(history.inventory_position, onHand + incoming - backlog);
    const safetyStock = toNumber(history.safety_stock);
    const reorderPoint = toNumber(history.reorder_point, safetyStock);

    fallbackInventoryByMaterial[materialId] = {
      on_hand: onHand,
      incoming,
      backlog,
      inventory_position: inventoryPosition,
      safety_stock: safetyStock,
      reorder_point: reorderPoint
    };

    fallbackLatestReplenishmentByMaterial[materialId] = {
      suggested_order_quantity: toNumber(history.suggested_order_quantity),
      expected_due_round: history.expected_due_round ?? '-',
      created_request: Boolean(history.created_request || latestRequestByMaterial[materialId]),
      request_id: history.request_id || latestRequestByMaterial[materialId]?.request_id || null
    };
  }

  return {
    pending_by_material:
      procurementState?.operational_summary?.pending_by_material ||
      replenishment.pending_by_material ||
      {},
    inventory_position_by_material:
      procurementState?.operational_summary?.inventory_position_by_material ||
      fallbackInventoryByMaterial,
    latest_replenishment_by_material:
      procurementState?.operational_summary?.latest_replenishment_by_material ||
      fallbackLatestReplenishmentByMaterial
  };
};

const derivePolicyByItem = (inventoryState, operationalSummary) => {
  if (inventoryState?.policy_by_item) {
    return inventoryState.policy_by_item;
  }

  const inventoryItemMap = indexByItemId(inventoryState?.inventory_items);
  const operationalByMaterial = operationalSummary?.inventory_position_by_material || {};
  const materialIds = new Set([
    ...Object.keys(inventoryItemMap),
    ...Object.keys(operationalByMaterial)
  ]);

  return Object.fromEntries(
    Array.from(materialIds).map((materialId) => {
      const inventoryItem = inventoryItemMap[materialId] || {};
      const operationalItem = operationalByMaterial[materialId] || {};
      const currentQuantity = toNumber(inventoryItem.quantity, toNumber(operationalItem.on_hand));
      const safetyStock = toNumber(operationalItem.safety_stock);
      const reorderPoint = toNumber(operationalItem.reorder_point);

      return [
        materialId,
        {
          current_quantity: currentQuantity,
          safety_stock: safetyStock,
          reorder_point: reorderPoint,
          is_low_stock: safetyStock > 0 && currentQuantity <= safetyStock,
          is_below_reorder_point: reorderPoint > 0 && currentQuantity <= reorderPoint
        }
      ];
    })
  );
};

const getPendingTotal = (pendingByMaterial, quantityView) =>
  Object.entries(pendingByMaterial || {}).reduce(
    (sum, [materialId, value]) => sum + convertQuantityByItem(value, materialId, quantityView),
    0
  );

const getInventoryPositionTotal = (inventoryByMaterial, quantityView) =>
  sumConvertedFieldByItemMap(inventoryByMaterial, 'inventory_position', quantityView);

const getLowStockCount = (policyByItem) =>
  Object.values(policyByItem || {}).filter((item) => item?.is_low_stock || item?.is_below_reorder_point).length;

const buildLatestSnapshotRows = (latestRows, quantityView) =>
  latestRows.flatMap((row) => {
    const procurementState = row.procurement || {};
    const inventoryByMaterial = procurementState.operational_summary?.inventory_position_by_material || {};
    const latestReplenishmentByMaterial = procurementState.operational_summary?.latest_replenishment_by_material || {};

    return Object.entries(inventoryByMaterial).map(([materialId, detail]) => ({
      company: row.company,
      materialId: getDisplayItemLabel(materialId, quantityView),
      onHand: convertQuantityByItem(detail?.on_hand, materialId, quantityView),
      incoming: convertQuantityByItem(detail?.incoming, materialId, quantityView),
      backlog: convertQuantityByItem(detail?.backlog, materialId, quantityView),
      inventoryPosition: convertQuantityByItem(detail?.inventory_position, materialId, quantityView),
      safetyStock: convertQuantityByItem(detail?.safety_stock, materialId, quantityView),
      reorderPoint: convertQuantityByItem(detail?.reorder_point, materialId, quantityView),
      suggestedOrderQuantity: convertQuantityByItem(
        latestReplenishmentByMaterial?.[materialId]?.suggested_order_quantity,
        materialId,
        quantityView
      ),
      expectedDueRound: latestReplenishmentByMaterial?.[materialId]?.expected_due_round ?? '-',
      createdRequest: latestReplenishmentByMaterial?.[materialId]?.created_request ? '是' : '否'
    }));
  });

const buildFlowMeta = (enterpriseSpecs = []) => {
  const sorted = [...enterpriseSpecs]
    .filter((spec) => spec?.id || spec?.enterprise_id)
    .sort((left, right) => {
      const tierGap = Number(left?.tier ?? 0) - Number(right?.tier ?? 0);
      if (tierGap !== 0) {
        return tierGap;
      }
      return String(left?.id || left?.enterprise_id || '').localeCompare(String(right?.id || right?.enterprise_id || ''));
    });
  const companies = sorted.map((spec) => spec.enterprise_id || spec.id).filter(Boolean);
  const companyNameMap = Object.fromEntries(
    sorted.map((spec) => [
      spec.enterprise_id || spec.id,
      spec.enterprise_name || spec.name || spec.enterprise_id || spec.id,
    ])
  );
  const companyColors = Object.fromEntries(
    companies.map((company, index) => [company, FLOW_COLORS[index % FLOW_COLORS.length]])
  );
  return { companies, companyNameMap, companyColors };
};

const OperationalReviewView = ({ availableDays, dataRoot, quantityView, enterpriseSpecs = [] }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const backlogRef = useRef(null);
  const fillRateRef = useRef(null);
  const pendingRef = useRef(null);
  const inventoryPositionRef = useRef(null);
  const chartRefs = useRef([]);
  const flowMeta = useMemo(() => buildFlowMeta(enterpriseSpecs), [enterpriseSpecs]);

  const latestDay = availableDays.length > 0 ? Math.max(...availableDays) : 0;

  useEffect(() => {
    loadReviewData();
  }, [availableDays.join(','), dataRoot, flowMeta.companies.join(',')]);

  useEffect(() => {
    renderCharts();
    const handleResize = () => {
      chartRefs.current.forEach((chart) => chart?.resize());
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [rows, quantityView]);

  useEffect(() => () => {
    chartRefs.current.forEach((chart) => chart?.dispose());
    chartRefs.current = [];
  }, []);

  const loadReviewData = async () => {
    setLoading(true);
    const nextRows = [];

    for (const day of availableDays) {
      const companyRows = await Promise.all(flowMeta.companies.map(async (company) => {
        const [sales, procurement, inventory] = await Promise.all([
          safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/sales/day${day}/sales.json`)),
          safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/procurement/day${day}/procurement.json`)),
          safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/inventory/day${day}/inventory.json`))
        ]);

        const salesState = getState(sales);
        const procurementState = getState(procurement);
        const inventoryState = getState(inventory);
        const salesSummary = deriveSalesSummary(salesState);
        const operationalSummary = deriveOperationalSummary(procurementState, inventoryState);
        const policyByItem = derivePolicyByItem(inventoryState, operationalSummary);

        return {
          day,
          company,
          sales: {
            ...salesState,
            service_level_summary: salesSummary
          },
          procurement: {
            ...procurementState,
            operational_summary: operationalSummary
          },
          inventory: {
            ...inventoryState,
            policy_by_item: policyByItem
          }
        };
      }));

      nextRows.push(...companyRows);
    }

    setRows(nextRows);
    setLoading(false);
  };

  const resetCharts = () => {
    chartRefs.current.forEach((chart) => chart?.dispose());
    chartRefs.current = [];
  };

  const renderCharts = () => {
    if (rows.length === 0) {
      return;
    }
    resetCharts();
    renderBacklogChart();
    renderFillRateChart();
    renderPendingChart();
    renderInventoryPositionChart();
  };

  const renderBacklogChart = () => {
    const chart = echarts.init(backlogRef.current);
    chartRefs.current.push(chart);

    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', bottom: 0 },
      grid: { left: 44, right: 20, top: 24, bottom: 54 },
      xAxis: { type: 'category', data: availableDays.map((day) => `Turn ${day}`) },
      yAxis: { type: 'value', name: '数量' },
      series: flowMeta.companies.flatMap((company) => {
        const companyRows = availableDays.map((day) => rows.find((row) => row.company === company && row.day === day));
        return [
          {
            name: `${flowMeta.companyNameMap[company] || company} backlog`,
            type: 'line',
            smooth: true,
            data: companyRows.map((row) => toNumber(row?.sales?.service_level_summary?.backlog_quantity)),
            itemStyle: { color: flowMeta.companyColors[company] }
          },
          {
            name: `${flowMeta.companyNameMap[company] || company} lost sales`,
            type: 'line',
            smooth: true,
            lineStyle: { type: 'dashed' },
            data: companyRows.map((row) => toNumber(row?.sales?.service_level_summary?.lost_sales_quantity)),
            itemStyle: { color: flowMeta.companyColors[company] }
          }
        ];
      })
    });
  };

  const renderFillRateChart = () => {
    const chart = echarts.init(fillRateRef.current);
    chartRefs.current.push(chart);

    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', bottom: 0 },
      grid: { left: 44, right: 20, top: 24, bottom: 54 },
      xAxis: { type: 'category', data: availableDays.map((day) => `Turn ${day}`) },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1,
        axisLabel: {
          formatter: (value) => `${Math.round(value * 100)}%`
        }
      },
      series: flowMeta.companies.map((company) => ({
        name: `${flowMeta.companyNameMap[company] || company} fill rate`,
        type: 'line',
        smooth: true,
        data: availableDays.map((day) => {
          const row = rows.find((entry) => entry.company === company && entry.day === day);
          return toNumber(row?.sales?.service_level_summary?.fill_rate);
        }),
        itemStyle: { color: flowMeta.companyColors[company] }
      }))
    });
  };

  const renderPendingChart = () => {
    const chart = echarts.init(pendingRef.current);
    chartRefs.current.push(chart);

    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', bottom: 0 },
      grid: { left: 44, right: 20, top: 24, bottom: 54 },
      xAxis: { type: 'category', data: availableDays.map((day) => `Turn ${day}`) },
      yAxis: { type: 'value', name: getQuantityAxisLabel('在途总量', quantityView) },
      series: flowMeta.companies.map((company) => ({
        name: `${flowMeta.companyNameMap[company] || company} pending`,
        type: 'bar',
        data: availableDays.map((day) => {
          const row = rows.find((entry) => entry.company === company && entry.day === day);
          return getPendingTotal(row?.procurement?.operational_summary?.pending_by_material, quantityView);
        }),
        itemStyle: { color: flowMeta.companyColors[company] }
      }))
    });
  };

  const renderInventoryPositionChart = () => {
    const chart = echarts.init(inventoryPositionRef.current);
    chartRefs.current.push(chart);

    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', bottom: 0 },
      grid: { left: 44, right: 20, top: 24, bottom: 54 },
      xAxis: { type: 'category', data: availableDays.map((day) => `Turn ${day}`) },
      yAxis: { type: 'value', name: getQuantityAxisLabel('库存位置汇总', quantityView) },
      series: flowMeta.companies.map((company) => ({
        name: `${flowMeta.companyNameMap[company] || company} inventory position`,
        type: 'line',
        smooth: true,
        data: availableDays.map((day) => {
          const row = rows.find((entry) => entry.company === company && entry.day === day);
          return getInventoryPositionTotal(row?.procurement?.operational_summary?.inventory_position_by_material, quantityView);
        }),
        itemStyle: { color: flowMeta.companyColors[company] }
      }))
    });
  };

  const latestRows = useMemo(
    () => rows.filter((row) => row.day === latestDay),
    [rows, latestDay]
  );

  const kpis = useMemo(() => {
    const totalBacklog = latestRows.reduce(
      (sum, row) => sum + toNumber(row.sales?.service_level_summary?.backlog_quantity),
      0
    );
    const totalLostSales = latestRows.reduce(
      (sum, row) => sum + toNumber(row.sales?.service_level_summary?.lost_sales_quantity),
      0
    );
    const totalPending = latestRows.reduce(
      (sum, row) => sum + getPendingTotal(row.procurement?.operational_summary?.pending_by_material, quantityView),
      0
    );
    const lowStockAlerts = latestRows.reduce(
      (sum, row) => sum + getLowStockCount(row.inventory?.policy_by_item),
      0
    );
    const averageFillRate = latestRows.length > 0
      ? latestRows.reduce(
          (sum, row) => sum + toNumber(row.sales?.service_level_summary?.fill_rate),
          0
        ) / latestRows.length
      : 0;

    return {
      totalBacklog,
      totalLostSales,
      totalPending,
      lowStockAlerts,
      averageFillRate
    };
  }, [latestRows, quantityView]);

  const latestSnapshotRows = useMemo(
    () => buildLatestSnapshotRows(latestRows, quantityView),
    [latestRows, quantityView]
  );

  if (loading) {
    return <div className="loading">加载运营复盘数据...</div>;
  }

  return (
    <div className="operations-page">
      <div className="operations-kpi-grid">
        <div className="operations-kpi-card warning">
          <span>期末 backlog</span>
          <strong>{formatNumber(kpis.totalBacklog)}</strong>
        </div>
        <div className="operations-kpi-card warning">
          <span>期末 lost sales</span>
          <strong>{formatNumber(kpis.totalLostSales)}</strong>
        </div>
        <div className="operations-kpi-card">
          <span>期末在途总量</span>
          <strong>{formatNumber(kpis.totalPending)}</strong>
        </div>
        <div className="operations-kpi-card">
          <span>平均 fill rate</span>
          <strong>{formatPercent(kpis.averageFillRate)}</strong>
        </div>
        <div className="operations-kpi-card warning">
          <span>库存策略告警数</span>
          <strong>{formatNumber(kpis.lowStockAlerts)}</strong>
        </div>
      </div>

      <div className="operations-layout">
        <div className="operations-chart-card wide">
          <div className="operations-card-title">backlog 与 lost sales 趋势</div>
          <div className="operations-chart large" ref={backlogRef} />
        </div>

        <div className="operations-chart-card">
          <div className="operations-card-title">各企业 fill rate 趋势</div>
          <div className="operations-chart" ref={fillRateRef} />
        </div>

        <div className="operations-chart-card">
          <div className="operations-card-title">各企业在途采购总量</div>
          <div className="operations-chart" ref={pendingRef} />
        </div>

        <div className="operations-chart-card wide">
          <div className="operations-card-title">各企业库存位置汇总趋势</div>
          <div className="operations-chart" ref={inventoryPositionRef} />
        </div>

        <div className="operations-chart-card wide insight-card">
          <div className="operations-card-title">
            {quantityView?.enabled ? `最新轮次运营快照（原料折合 ${quantityView.productId}）` : '最新轮次运营快照'}
          </div>
          <div className="operations-table-wrapper">
            <table className="operations-table">
              <thead>
                <tr>
                  <th>企业</th>
                  <th>物料</th>
                  <th>{getQuantityColumnLabel('现货', quantityView)}</th>
                  <th>{getQuantityColumnLabel('在途', quantityView)}</th>
                  <th>{getQuantityColumnLabel('backlog', quantityView)}</th>
                  <th>{getQuantityColumnLabel('库存位置', quantityView)}</th>
                  <th>{getQuantityColumnLabel('安全库存', quantityView)}</th>
                  <th>{getQuantityColumnLabel('再订购点', quantityView)}</th>
                  <th>{getQuantityColumnLabel('建议补货', quantityView)}</th>
                  <th>到货轮次</th>
                  <th>已建请求</th>
                </tr>
              </thead>
              <tbody>
                {latestSnapshotRows.length === 0 ? (
                  <tr>
                    <td colSpan="11">暂无最新轮次物料快照</td>
                  </tr>
                ) : (
                  latestSnapshotRows.map((row, index) => (
                    <tr key={`${row.company}-${row.materialId}-${index}`}>
                      <td>{flowMeta.companyNameMap[row.company] || row.company}</td>
                      <td>{row.materialId}</td>
                      <td>{formatNumber(row.onHand)}</td>
                      <td>{formatNumber(row.incoming)}</td>
                      <td>{formatNumber(row.backlog)}</td>
                      <td>{formatNumber(row.inventoryPosition)}</td>
                      <td>{formatNumber(row.safetyStock)}</td>
                      <td>{formatNumber(row.reorderPoint)}</td>
                      <td>{formatNumber(row.suggestedOrderQuantity)}</td>
                      <td>{row.expectedDueRound}</td>
                      <td>{row.createdRequest}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OperationalReviewView;
