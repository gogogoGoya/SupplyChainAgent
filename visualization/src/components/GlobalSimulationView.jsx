import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';
import {
  convertQuantityByItem,
  getDisplayItemLabel,
  getQuantityAxisLabel,
  isConvertibleRawMaterial,
} from '../utils/productEquivalent';
import { buildExternalFlowSeries } from '../utils/externalMarketFlows';

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

const formatMoney = (value) => `¥${formatNumber(value)}`;

const toArray = (value) => {
  if (!value) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
};

const buildFlowMeta = (enterpriseSpecs = []) => {
  const sorted = [...enterpriseSpecs]
    .filter((spec) => spec?.enterprise_id || spec?.id)
    .sort((left, right) => {
      const tierGap = Number(left?.tier ?? 0) - Number(right?.tier ?? 0);
      if (tierGap !== 0) {
        return tierGap;
      }
      return String(left?.enterprise_id || left?.id || '').localeCompare(String(right?.enterprise_id || right?.id || ''));
    });

  const companies = sorted.map((spec) => spec.enterprise_id || spec.id);
  const companyNameMap = Object.fromEntries(
    sorted.map((spec) => [
      spec.enterprise_id || spec.id,
      spec.enterprise_name || spec.name || spec.enterprise_id || spec.id
    ])
  );
  const exchangeEntries = companies.slice(0, -1).map((companyId, index) => ({
    exchangeId: `${index}-${index + 1}_exchange`,
    sourceId: companyId,
    targetId: companies[index + 1],
    label: `${companyNameMap[companyId] || companyId} → ${companyNameMap[companies[index + 1]] || companies[index + 1]}`,
  }));
  const productionSpec =
    sorted.find((spec) => toArray(spec?.enabled_functions).includes('production'))
    || sorted.find((spec) => toArray(spec?.role_tags).includes('finished_goods_manufacturer'))
    || null;

  return {
    companies,
    companyNameMap,
    exchangeEntries,
    topCompanyId: companies[0] || '',
    bottomCompanyId: companies[companies.length - 1] || '',
    topCompanyName: companyNameMap[companies[0]] || companies[0] || 'Top tier',
    bottomCompanyName:
      companyNameMap[companies[companies.length - 1]] || companies[companies.length - 1] || 'Bottom tier',
    productionNodeId: productionSpec?.enterprise_id || productionSpec?.id || '',
    productionNodeName: productionSpec?.enterprise_name || productionSpec?.name || productionSpec?.enterprise_id || productionSpec?.id || '',
  };
};

const readCompanyDay = async (company, day, dataRoot) => {
  const [finance, sales, inventory, production, procurement] = await Promise.all([
    safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/finance/day${day}/finance.json`)),
    safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/sales/day${day}/sales.json`)),
    safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/inventory/day${day}/inventory.json`)),
    safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/production/day${day}/production.json`)),
    safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/procurement/day${day}/procurement.json`)),
  ]);

  return {
    company,
    day,
    finance: finance?.self_state || {},
    sales: sales?.self_state || {},
    inventory: inventory?.self_state || {},
    production: production?.self_state || {},
    procurement: procurement?.self_state || {},
  };
};

const getInventoryQuantity = (inventory, itemId) => {
  const item = (inventory?.inventory_items || []).find((entry) => entry.item_id === itemId);
  return Number(item?.quantity || 0);
};

const getPrimaryFinishedGoodItemId = (inventory) => {
  const items = inventory?.inventory_items || [];
  const finished = items.find((entry) => !isConvertibleRawMaterial(entry?.item_id));
  return finished?.item_id || items[0]?.item_id || 'beer';
};

const getPrimaryRawMaterialItemId = (inventory) => {
  const items = inventory?.inventory_items || [];
  const raw = items.find((entry) => isConvertibleRawMaterial(entry?.item_id));
  return raw?.item_id || '';
};

const GlobalSimulationView = ({
  availableDays,
  dataRoot,
  quantityView,
  includeUpstreamExternalSupplierMode = false,
  includeDownstreamExternalMarketMode = false,
  enterpriseSpecs = [],
}) => {
  const [rows, setRows] = useState([]);
  const [exchangeRows, setExchangeRows] = useState([]);
  const [externalFlowSnapshot, setExternalFlowSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const financeRef = useRef(null);
  const exchangeRef = useRef(null);
  const productionRef = useRef(null);
  const sankeyRef = useRef(null);
  const chartRefs = useRef([]);

  const latestDay = availableDays.length > 0 ? Math.max(...availableDays) : 0;
  const flowMeta = useMemo(() => buildFlowMeta(enterpriseSpecs), [enterpriseSpecs]);

  const latestCompanyRows = useMemo(
    () => rows.filter((row) => row.day === latestDay),
    [rows, latestDay]
  );

  useEffect(() => {
    loadGlobalData();
  }, [
    availableDays.join(','),
    dataRoot,
    quantityView,
    includeUpstreamExternalSupplierMode,
    includeDownstreamExternalMarketMode,
    flowMeta.companies.join(','),
  ]);

  useEffect(() => {
    renderCharts();
    const handleResize = () => {
      chartRefs.current.forEach((chart) => chart?.resize());
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [rows, exchangeRows, externalFlowSnapshot, includeUpstreamExternalSupplierMode, includeDownstreamExternalMarketMode, flowMeta]);

  useEffect(() => () => {
    chartRefs.current.forEach((chart) => chart?.dispose());
    chartRefs.current = [];
  }, []);

  const loadGlobalData = async () => {
    setLoading(true);

    const companyRows = [];
    for (const day of availableDays) {
      const dayRows = await Promise.all(flowMeta.companies.map((company) => readCompanyDay(company, day, dataRoot)));
      companyRows.push(...dayRows);
    }

    const exchanges = [];
    for (const day of availableDays) {
      const data = await safeFetchJson(buildDataUrl(dataRoot, `public/exchange/day${day}/exchange.json`));
      const dayExchanges = {};
      Object.entries(data?.data?.exchanges || {}).forEach(([exchangeId, exchange]) => {
        const ordersList = exchange.orders?.list || [];
        dayExchanges[exchangeId] = {
          orders: exchange.orders?.count || 0,
          proposals: exchange.proposals?.count || 0,
          orderQuantity: ordersList.reduce(
            (sum, order) => sum + convertQuantityByItem(order.quantity, order.product_id, quantityView),
            0
          ),
          orderValue: exchange.orders?.total_value || 0,
          ordersList,
        };
      });
      exchanges.push({ day, exchanges: dayExchanges });
    }

    const latestTopRow = companyRows.find((row) => row.company === flowMeta.topCompanyId && row.day === latestDay);
    const latestBottomRow = companyRows.find((row) => row.company === flowMeta.bottomCompanyId && row.day === latestDay);
    const externalFlows = buildExternalFlowSeries({
      availableDays,
      quantityView,
      procurementState: latestTopRow?.procurement || {},
      salesState: latestBottomRow?.sales || {},
    });

    setRows(companyRows);
    setExchangeRows(exchanges);
    setExternalFlowSnapshot(externalFlows);
    setLoading(false);
  };

  const resetCharts = () => {
    chartRefs.current.forEach((chart) => chart?.dispose());
    chartRefs.current = [];
  };

  const renderCharts = () => {
    if (rows.length === 0 || exchangeRows.length === 0) {
      return;
    }

    resetCharts();
    renderFinanceChart();
    renderExchangeChart();
    if (flowMeta.productionNodeId) {
      renderProductionChart();
    }
    renderFinalSankey();
  };

  const renderFinanceChart = () => {
    const chart = echarts.init(financeRef.current);
    chartRefs.current.push(chart);

    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', bottom: 0 },
      grid: { left: 44, right: 20, top: 24, bottom: 54 },
      xAxis: { type: 'category', data: availableDays.map((day) => `Turn ${day}`) },
      yAxis: { type: 'value' },
      series: flowMeta.companies.map((company) => ({
        name: `${flowMeta.companyNameMap[company] || company} Cash`,
        type: 'line',
        smooth: true,
        data: availableDays.map((day) => rows.find((row) => row.company === company && row.day === day)?.finance.cash || 0),
      })),
    });
  };

  const renderExchangeChart = () => {
    const chart = echarts.init(exchangeRef.current);
    chartRefs.current.push(chart);

    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', bottom: 0 },
      grid: { left: 44, right: 20, top: 24, bottom: 54 },
      xAxis: { type: 'category', data: availableDays.map((day) => `Turn ${day}`) },
      yAxis: { type: 'value', name: getQuantityAxisLabel('Order Quantity', quantityView) },
      series: [
        ...flowMeta.exchangeEntries.flatMap(({ exchangeId, label }) => [
          {
            name: `${label} Order Quantity`,
            type: 'line',
            smooth: true,
            data: exchangeRows.map((row) => row.exchanges[exchangeId]?.orderQuantity || 0),
          },
          {
            name: `${label} Proposals`,
            type: 'line',
            smooth: true,
            lineStyle: { type: 'dashed' },
            data: exchangeRows.map((row) => row.exchanges[exchangeId]?.proposals || 0),
          },
        ]),
        ...(includeUpstreamExternalSupplierMode ? [{
          name: `External Upstream → ${flowMeta.topCompanyName}`,
          type: 'line',
          smooth: true,
          data: externalFlowSnapshot?.upstreamQuantitySeries || [],
        }] : []),
        ...(includeDownstreamExternalMarketMode ? [{
          name: `${flowMeta.bottomCompanyName} → External Market`,
          type: 'line',
          smooth: true,
          data: externalFlowSnapshot?.downstreamQuantitySeries || [],
        }] : []),
      ],
    });
  };

  const renderProductionChart = () => {
    const chart = echarts.init(productionRef.current);
    chartRefs.current.push(chart);

    const productionRows = availableDays.map((day) => rows.find((row) => row.company === flowMeta.productionNodeId && row.day === day));
    const latestProductionInventory = latestCompanyRows.find((row) => row.company === flowMeta.productionNodeId)?.inventory || {};
    const outputItemId = getPrimaryFinishedGoodItemId(latestProductionInventory);
    const rawItemId = getPrimaryRawMaterialItemId(latestProductionInventory);

    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0 },
      grid: { left: 44, right: 20, top: 24, bottom: 54 },
      xAxis: { type: 'category', data: availableDays.map((day) => `Turn ${day}`) },
      yAxis: { type: 'value' },
      series: [
        {
          name: 'Cumulative Output',
          type: 'line',
          smooth: true,
          data: productionRows.map((row) => row?.production.production_metrics?.total_production || 0),
        },
        {
          name: `${getDisplayItemLabel(outputItemId, quantityView)} Inventory`,
          type: 'line',
          smooth: true,
          data: productionRows.map((row) => convertQuantityByItem(getInventoryQuantity(row?.inventory, outputItemId), outputItemId, quantityView)),
        },
        ...(rawItemId ? [{
          name: `${getDisplayItemLabel(rawItemId, quantityView)} Inventory`,
          type: 'bar',
          data: productionRows.map((row) => convertQuantityByItem(getInventoryQuantity(row?.inventory, rawItemId), rawItemId, quantityView)),
        }] : []),
      ],
    });
  };

  const renderFinalSankey = () => {
    const chart = echarts.init(sankeyRef.current);
    chartRefs.current.push(chart);

    const latestExchange = exchangeRows.find((row) => row.day === latestDay);
    const grouped = {};
    Object.values(latestExchange?.exchanges || {}).forEach((exchange) => {
      exchange.ordersList.forEach((order) => {
        const key = `${order.seller_company_id}->${order.buyer_company_id}:${order.product_id}`;
        if (!grouped[key]) {
          grouped[key] = {
            source: order.seller_company_id,
            target: order.buyer_company_id,
            product: order.product_id,
            quantity: 0,
            originalQuantity: 0,
          };
        }
        grouped[key].quantity += convertQuantityByItem(order.quantity, order.product_id, quantityView);
        grouped[key].originalQuantity += Number(order.quantity || 0);
      });
    });

    if (includeUpstreamExternalSupplierMode) {
      (externalFlowSnapshot?.upstreamProcurementOrders || []).forEach((order) => {
        const key = `External Upstream->${flowMeta.topCompanyId}:${order.material_id}`;
        if (!grouped[key]) {
          grouped[key] = {
            source: 'External Upstream',
            target: flowMeta.topCompanyId,
            product: order.material_id,
            quantity: 0,
            originalQuantity: 0,
          };
        }
        grouped[key].quantity += convertQuantityByItem(order.quantity, order.material_id, quantityView);
        grouped[key].originalQuantity += Number(order.quantity || 0);
      });
    }

    if (includeDownstreamExternalMarketMode) {
      (externalFlowSnapshot?.downstreamSalesOrders || []).forEach((order) => {
        const key = `${flowMeta.bottomCompanyId}->External Market:${order.product_id}`;
        if (!grouped[key]) {
          grouped[key] = {
            source: flowMeta.bottomCompanyId,
            target: 'External Market',
            product: order.product_id,
            quantity: 0,
            originalQuantity: 0,
          };
        }
        grouped[key].quantity += convertQuantityByItem(order.quantity, order.product_id, quantityView);
        grouped[key].originalQuantity += Number(order.quantity || 0);
      });
    }

    const links = Object.values(grouped).map((flow) => ({
      source: flowMeta.companyNameMap[flow.source] || flow.source,
      target: flowMeta.companyNameMap[flow.target] || flow.target,
      value: Math.max(flow.quantity, 0.01),
      rawQuantity: flow.quantity,
      originalQuantity: flow.originalQuantity,
      product: flow.product,
      converted: isConvertibleRawMaterial(flow.product, quantityView),
      lineStyle: {
        color: flow.product === 'beer' ? '#2f80ed' : '#8a6f3d',
        opacity: 0.55,
      },
    }));
    if (links.length === 0) {
      const latestExchanges = Object.values(latestExchange?.exchanges || {});
      const proposalCount = latestExchanges.reduce((sum, exchange) => (
        sum + Number(exchange.proposals || 0)
      ), 0);
      chart.setOption({
        title: {
          text: 'No Confirmed Order Flow',
          subtext: proposalCount > 0
            ? `The latest turn contains ${proposalCount} trade proposals but no confirmed orders.`
            : 'The latest turn contains no inter-enterprise orders to visualize.',
          left: 'center',
          top: 'middle',
          textStyle: { color: '#475569', fontSize: 18, fontWeight: 700 },
          subtextStyle: { color: '#64748b', fontSize: 13 },
        },
        series: [],
      });
      return;
    }
    const nodeNames = [...new Set(links.flatMap((link) => [link.source, link.target]))];

    chart.setOption({
      tooltip: {
        trigger: 'item',
        formatter: (params) => {
          if (params.dataType === 'edge') {
            const productLabel = getDisplayItemLabel(params.data.product, quantityView);
            if (params.data.converted) {
              return `${params.data.source} → ${params.data.target}<br/>${productLabel}: ${formatNumber(params.data.rawQuantity)}<br/>Original quantity: ${formatNumber(params.data.originalQuantity)}`;
            }
            return `${params.data.source} → ${params.data.target}<br/>${productLabel}: ${formatNumber(params.data.rawQuantity)}`;
          }
          return params.name;
        },
      },
      series: [{
        type: 'sankey',
        nodeWidth: 18,
        nodeGap: 16,
        draggable: false,
        label: { fontSize: 12 },
        emphasis: { focus: 'adjacency' },
        data: nodeNames.map((name) => ({ name })),
        links,
      }],
    });
  };

  const latestExchangeRow = exchangeRows.find((row) => row.day === latestDay);
  const bottomRow = latestCompanyRows.find((row) => row.company === flowMeta.bottomCompanyId);
  const productionRow = latestCompanyRows.find((row) => row.company === flowMeta.productionNodeId);
  const downstreamExchange = latestExchangeRow?.exchanges?.[flowMeta.exchangeEntries[flowMeta.exchangeEntries.length - 1]?.exchangeId];
  const productionInventory = productionRow?.inventory || {};
  const outputItemId = getPrimaryFinishedGoodItemId(productionInventory);
  const rawItemId = getPrimaryRawMaterialItemId(productionInventory);
  const productionOutputInventory = flowMeta.productionNodeId
    ? convertQuantityByItem(getInventoryQuantity(productionInventory, outputItemId), outputItemId, quantityView)
    : 0;
  const productionRawInventory = rawItemId
    ? convertQuantityByItem(getInventoryQuantity(productionInventory, rawItemId), rawItemId, quantityView)
    : 0;

  if (loading) {
    return <div className="loading">Loading global review data...</div>;
  }

  return (
    <div className="global-page">
      <div className="global-kpi-grid">
        <div className="global-kpi-card">
          <span>Simulated Turns</span>
          <strong>{availableDays.length}</strong>
        </div>
        <div className="global-kpi-card">
          <span>{flowMeta.bottomCompanyName} Ending Cash</span>
          <strong>{formatMoney(bottomRow?.finance.cash)}</strong>
        </div>
        <div className="global-kpi-card">
          <span>Downstream Cumulative Orders</span>
          <strong>{formatNumber(downstreamExchange?.orderQuantity || 0)}</strong>
        </div>
        {flowMeta.productionNodeId ? (
          <>
            <div className="global-kpi-card">
              <span>{flowMeta.productionNodeName} {getDisplayItemLabel(outputItemId, quantityView)} Inventory</span>
              <strong>{formatNumber(productionOutputInventory)}</strong>
            </div>
            <div className="global-kpi-card warning">
              <span>{flowMeta.productionNodeName} {getDisplayItemLabel(rawItemId || 'raw', quantityView)} Inventory</span>
              <strong>{formatNumber(productionRawInventory)}</strong>
            </div>
          </>
        ) : (
          <div className="global-kpi-card">
            <span>{flowMeta.topCompanyName} Ending Cash</span>
            <strong>{formatMoney(latestCompanyRows.find((row) => row.company === flowMeta.topCompanyId)?.finance.cash)}</strong>
          </div>
        )}
      </div>

      <div className="global-layout">
        <div className="global-chart-card wide">
          <div className="global-card-title">Cumulative End-to-End Flow</div>
          <div className="global-sankey-chart" ref={sankeyRef} />
        </div>
        <div className="global-chart-card">
          <div className="global-card-title">Enterprise Cash Trends</div>
          <div className="global-chart" ref={financeRef} />
        </div>
        <div className="global-chart-card">
          <div className="global-card-title">
            {(includeUpstreamExternalSupplierMode || includeDownstreamExternalMarketMode)
              ? (quantityView?.enabled
                ? `Exchange and External Order Trends (Raw Materials as ${quantityView.productId} Equivalents)`
                : 'Exchange and External Order Trends')
              : (quantityView?.enabled
                ? `Exchange Orders and Proposal Backlog (Raw Materials as ${quantityView.productId} Equivalents)`
                : 'Exchange Orders and Proposal Backlog')}
          </div>
          <div className="global-chart" ref={exchangeRef} />
        </div>
        <div className="global-chart-card">
          <div className="global-card-title">
            {flowMeta.productionNodeId ? `${flowMeta.productionNodeName} Production and Key Inventory` : 'Production-Node Overview'}
          </div>
          {flowMeta.productionNodeId ? (
            <div className="global-chart" ref={productionRef} />
          ) : (
            <div className="global-empty-state">This scenario has no production node, so the production view is omitted.</div>
          )}
        </div>
        <div className="global-chart-card insight-card">
          <div className="global-card-title">System-Level Observations</div>
          <ul>
            <li>Orders and proposals on the downstream link `{flowMeta.exchangeEntries[flowMeta.exchangeEntries.length - 1]?.label || 'N/A'}` reveal terminal fulfillment pressure.</li>
            <li>The end-to-end cash chart identifies which tier bears the greatest financial pressure as fluctuations propagate.</li>
            <li>When a production node is present, its inventory and cumulative output indicate whether supply constraints interrupt amplification.</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default GlobalSimulationView;
