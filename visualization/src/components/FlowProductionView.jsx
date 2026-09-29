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

const groupByProduct = (orders) => {
  const grouped = {};
  orders.forEach((order) => {
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
    grouped[key].quantity += Number(order.displayQuantity || 0);
    grouped[key].originalQuantity += Number(order.quantity || 0);
  });
  return Object.values(grouped);
};

const getDailyProduction = (currentProduction, previousProduction) => {
  const currentTotal = Number(currentProduction?.self_state?.production_metrics?.total_production || 0);
  const previousTotal = Number(previousProduction?.self_state?.production_metrics?.total_production || 0);
  return Math.max(0, currentTotal - previousTotal);
};

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
    bottomCompanyName: companyNameMap[companies[companies.length - 1]] || companies[companies.length - 1] || 'Bottom tier',
    productionNodeId: productionSpec?.enterprise_id || productionSpec?.id || '',
    productionNodeName: productionSpec?.enterprise_name || productionSpec?.name || productionSpec?.enterprise_id || productionSpec?.id || '',
  };
};

const FlowProductionView = ({
  availableDays,
  currentDay = null,
  dataRoot,
  quantityView,
  includeUpstreamExternalSupplierMode = false,
  includeDownstreamExternalMarketMode = false,
  enterpriseSpecs = [],
}) => {
  const [flowRows, setFlowRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const sankeyRef = useRef(null);
  const trendRef = useRef(null);
  const sankeyInstanceRef = useRef(null);
  const trendInstanceRef = useRef(null);
  const flowMeta = useMemo(() => buildFlowMeta(enterpriseSpecs), [enterpriseSpecs]);

  const latestDay = useMemo(
    () => (availableDays.length > 0 ? availableDays[availableDays.length - 1] : 0),
    [availableDays]
  );

  const effectiveDay = currentDay ?? latestDay;

  const daysToLoad = useMemo(
    () => availableDays.filter((day) => day <= effectiveDay),
    [availableDays, effectiveDay]
  );

  useEffect(() => {
    loadFlowData();
  }, [
    daysToLoad.join(','),
    effectiveDay,
    dataRoot,
    quantityView,
    includeUpstreamExternalSupplierMode,
    includeDownstreamExternalMarketMode,
    flowMeta.companies.join(','),
  ]);

  useEffect(() => {
    renderSankey();
    renderTrend();

    const handleResize = () => {
      sankeyInstanceRef.current?.resize();
      trendInstanceRef.current?.resize();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [flowRows, effectiveDay, flowMeta, includeUpstreamExternalSupplierMode, includeDownstreamExternalMarketMode]);

  useEffect(() => () => {
    sankeyInstanceRef.current?.dispose();
    trendInstanceRef.current?.dispose();
  }, []);

  const loadFlowData = async () => {
    setLoading(true);
    const rows = [];

    for (const day of daysToLoad) {
      const [
        exchangeData,
        productionData,
        topProcurement,
        bottomSales,
        previousProductionData,
      ] = await Promise.all([
        safeFetchJson(buildDataUrl(dataRoot, `public/exchange/day${day}/exchange.json`)),
        flowMeta.productionNodeId
          ? safeFetchJson(buildDataUrl(dataRoot, `enterprises/${flowMeta.productionNodeId}/department/production/day${day}/production.json`))
          : null,
        flowMeta.topCompanyId
          ? safeFetchJson(buildDataUrl(dataRoot, `enterprises/${flowMeta.topCompanyId}/department/procurement/day${day}/procurement.json`))
          : null,
        flowMeta.bottomCompanyId
          ? safeFetchJson(buildDataUrl(dataRoot, `enterprises/${flowMeta.bottomCompanyId}/department/sales/day${day}/sales.json`))
          : null,
        day > 0 && flowMeta.productionNodeId
          ? safeFetchJson(buildDataUrl(dataRoot, `enterprises/${flowMeta.productionNodeId}/department/production/day${day - 1}/production.json`))
          : null,
      ]);
      const exchanges = exchangeData?.data?.exchanges || {};
      const currentOrders = Object.entries(exchanges).flatMap(([exchangeId, exchange]) => (
        (exchange.orders?.list || [])
          .filter((order) => Number(order.created_round) === Number(day))
          .map((order) => ({
            ...order,
            exchangeId,
            displayQuantity: convertQuantityByItem(order.quantity, order.product_id, quantityView),
          }))
      ));
      const externalFlows = buildExternalFlowSeries({
        availableDays: [day],
        quantityView,
        procurementState: topProcurement?.self_state || {},
        salesState: bottomSales?.self_state || {},
      });

      const dailyProduction = flowMeta.productionNodeId
        ? getDailyProduction(productionData, previousProductionData)
        : 0;
      const capacity = Number(productionData?.self_state?.production_lines?.total_capacity || 0);

      rows.push({
        day,
        currentOrders,
        groupedFlows: groupByProduct(currentOrders),
        upstreamExternalQuantity: externalFlows.upstreamQuantitySeries[0] || 0,
        downstreamExternalQuantity: externalFlows.downstreamQuantitySeries[0] || 0,
        upstreamExternalOrders: externalFlows.upstreamProcurementOrders,
        downstreamExternalOrders: externalFlows.downstreamSalesOrders,
        dailyProduction,
        cumulativeProduction: Number(productionData?.self_state?.production_metrics?.total_production || 0),
        capacity,
      });
    }

    setFlowRows(rows);
    setLoading(false);
  };

  const getCurrentRow = () => flowRows.find((row) => row.day === effectiveDay);

  const renderSankey = () => {
    if (!sankeyRef.current || flowRows.length === 0) {
      return;
    }

    if (sankeyInstanceRef.current) {
      sankeyInstanceRef.current.dispose();
    }
    sankeyInstanceRef.current = echarts.init(sankeyRef.current);

    const currentRow = getCurrentRow();
    const links = (currentRow?.groupedFlows || []).map((flow) => ({
      source: flowMeta.companyNameMap[flow.source] || flow.source,
      target: flowMeta.companyNameMap[flow.target] || flow.target,
      value: Math.max(flow.quantity, 0.01),
      product: flow.product,
      rawQuantity: flow.quantity,
      originalQuantity: flow.originalQuantity,
      converted: isConvertibleRawMaterial(flow.product, quantityView),
      lineStyle: {
        color: flow.product === 'beer' ? '#2f80ed' : '#8a6f3d',
        opacity: 0.55,
      },
    }));

    if (flowMeta.productionNodeId && (currentRow?.dailyProduction || 0) > 0) {
      links.push({
        source: flowMeta.productionNodeName,
        target: `${flowMeta.productionNodeName} Production`,
        value: currentRow.dailyProduction,
        product: 'produced_goods',
        rawQuantity: currentRow.dailyProduction,
        lineStyle: { color: '#21a67a', opacity: 0.6 },
      });
    }

    if (includeUpstreamExternalSupplierMode && (currentRow?.upstreamExternalQuantity || 0) > 0) {
      links.push({
        source: 'External Upstream',
        target: flowMeta.topCompanyName,
        value: Math.max(currentRow.upstreamExternalQuantity, 0.01),
        product: quantityView?.enabled ? `${quantityView.productId} equivalent` : 'external procurement',
        rawQuantity: currentRow.upstreamExternalQuantity,
        converted: Boolean(quantityView?.enabled),
        lineStyle: { color: '#3c8f5f', opacity: 0.55 },
      });
    }

    if (includeDownstreamExternalMarketMode && (currentRow?.downstreamExternalQuantity || 0) > 0) {
      links.push({
        source: flowMeta.bottomCompanyName,
        target: 'External Market',
        value: Math.max(currentRow.downstreamExternalQuantity, 0.01),
        product: 'beer',
        rawQuantity: currentRow.downstreamExternalQuantity,
        lineStyle: { color: '#d14d72', opacity: 0.55 },
      });
    }

    const nodeNames = [...new Set([
      ...(includeUpstreamExternalSupplierMode ? ['External Upstream'] : []),
      ...(includeDownstreamExternalMarketMode ? ['External Market'] : []),
      ...flowMeta.companies.map((company) => flowMeta.companyNameMap[company] || company),
      ...links.flatMap((link) => [link.source, link.target]),
    ])];

    sankeyInstanceRef.current.setOption({
      tooltip: {
        trigger: 'item',
        formatter: (params) => {
          if (params.dataType === 'edge') {
            const productLabel = getDisplayItemLabel(params.data.product, quantityView);
            if (params.data.converted) {
              return `${params.data.source} → ${params.data.target}<br/>${productLabel}: ${formatNumber(params.data.rawQuantity)}<br/>原始数量: ${formatNumber(params.data.originalQuantity)}`;
            }
            return `${params.data.source} → ${params.data.target}<br/>${productLabel}: ${formatNumber(params.data.rawQuantity)}`;
          }
          return params.name;
        },
      },
      series: [
        {
          type: 'sankey',
          nodeWidth: 18,
          nodeGap: 14,
          draggable: false,
          emphasis: { focus: 'adjacency' },
          label: { fontSize: 12 },
          data: nodeNames.map((name) => ({ name })),
          links,
        },
      ],
    });
  };

  const renderTrend = () => {
    if (!trendRef.current || flowRows.length === 0) {
      return;
    }

    if (trendInstanceRef.current) {
      trendInstanceRef.current.dispose();
    }
    trendInstanceRef.current = echarts.init(trendRef.current);

    const days = flowRows.map((row) => `Turn ${row.day}`);
    const exchangeSeries = flowMeta.exchangeEntries.map(({ exchangeId, label }) => ({
      name: label,
      type: 'bar',
      stack: 'flow',
      data: flowRows.map((row) => row.currentOrders
        .filter((order) => order.exchangeId === exchangeId)
        .reduce((sum, order) => sum + Number(order.displayQuantity || 0), 0)),
    }));

    if (includeUpstreamExternalSupplierMode) {
      exchangeSeries.push({
        name: `External Upstream → ${flowMeta.topCompanyName}`,
        type: 'bar',
        stack: 'flow',
        data: flowRows.map((row) => row.upstreamExternalQuantity || 0),
      });
    }

    if (includeDownstreamExternalMarketMode) {
      exchangeSeries.push({
        name: `${flowMeta.bottomCompanyName} → External Market`,
        type: 'bar',
        stack: 'flow',
        data: flowRows.map((row) => row.downstreamExternalQuantity || 0),
      });
    }

    trendInstanceRef.current.setOption({
      tooltip: { trigger: 'axis' },
      legend: {
        type: 'scroll',
        bottom: 0,
        textStyle: { fontSize: 10 },
      },
      grid: {
        left: 36,
        right: 18,
        top: 28,
        bottom: 54,
      },
      xAxis: { type: 'category', data: days },
      yAxis: { type: 'value', name: getQuantityAxisLabel('数量', quantityView) },
      series: [
        ...exchangeSeries,
        ...(flowMeta.productionNodeId ? [{
          name: `${flowMeta.productionNodeName} daily production`,
          type: 'line',
          smooth: true,
          symbolSize: 6,
          data: flowRows.map((row) => row.dailyProduction),
          lineStyle: { width: 3, color: '#21a67a' },
          itemStyle: { color: '#21a67a' },
        }] : []),
      ],
    });
  };

  if (loading) {
    return <div className="loading">加载流通与生产数据...</div>;
  }

  const externalLabels = [
    includeUpstreamExternalSupplierMode ? '上游外部采购' : null,
    includeDownstreamExternalMarketMode ? '下游外部销售' : null,
  ].filter(Boolean);

  return (
    <div className="flow-production-view">
      <div className="flow-chart-card">
        <div className="flow-card-header">
          <strong>{currentDay === null ? '末轮流向快照' : '当前轮流向'}</strong>
          <span>Turn {effectiveDay}</span>
        </div>
        <div className="flow-sankey-chart" ref={sankeyRef} />
      </div>

      <div className="flow-chart-card">
        <div className="flow-card-header">
          <strong>{quantityView?.enabled ? '流量与生产趋势（原料层折合成品）' : '流量与生产趋势'}</strong>
          <span>{externalLabels.length > 0 ? `订单流量 + ${externalLabels.join(' + ')}${flowMeta.productionNodeId ? ' + 日产量' : ''}` : `订单流量${flowMeta.productionNodeId ? ' + 日产量' : ''}`}</span>
        </div>
        <div className="flow-trend-chart" ref={trendRef} />
      </div>
    </div>
  );
};

export default FlowProductionView;
