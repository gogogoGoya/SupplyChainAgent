import { convertQuantityByItem } from './productEquivalent';

const EXTERNAL_SALE_SOURCE_TYPES = new Set(['external_market', 'market']);

const toArray = (value) => {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  return [value];
};

const uniqueByOrderId = (orders) => {
  const seen = new Set();
  return (orders || []).filter((order) => {
    const orderId = order?.order_id;
    if (!orderId || seen.has(orderId)) {
      return false;
    }
    seen.add(orderId);
    return true;
  });
};

const flattenOrderBuckets = (orderBuckets) =>
  Object.values(orderBuckets || {}).flatMap((bucket) => toArray(bucket));

export const collectExternalProcurementOrders = (procurementState) => {
  const externalSupplierIds = new Set(
    [
      ...(procurementState?.suppliers_detail || []),
      ...(procurementState?.suppliers || []),
    ]
      .filter((supplier) => supplier?.supplier_type === 'external')
      .map((supplier) => supplier?.supplier_id)
      .filter(Boolean)
  );

  return uniqueByOrderId(
    flattenOrderBuckets(procurementState?.orders).filter((order) =>
      externalSupplierIds.has(order?.supplier_id)
    )
  );
};

export const collectExternalSalesOrders = (salesState) =>
  uniqueByOrderId(
    flattenOrderBuckets(salesState?.sales_orders).filter((order) =>
      EXTERNAL_SALE_SOURCE_TYPES.has(order?.source_type)
    )
  );

const buildSeriesFromOrders = (
  orders,
  availableDays,
  quantityView,
  roundField,
  quantityField,
  itemField
) => {
  const byRound = new Map();
  (orders || []).forEach((order) => {
    const round = Number(order?.[roundField]);
    if (!Number.isFinite(round)) {
      return;
    }
    const quantity = convertQuantityByItem(order?.[quantityField], order?.[itemField], quantityView);
    byRound.set(round, (byRound.get(round) || 0) + quantity);
  });
  return availableDays.map((day) => byRound.get(day) || 0);
};

const buildCountSeriesFromOrders = (orders, availableDays, roundField) => {
  const byRound = new Map();
  (orders || []).forEach((order) => {
    const round = Number(order?.[roundField]);
    if (!Number.isFinite(round)) {
      return;
    }
    byRound.set(round, (byRound.get(round) || 0) + 1);
  });
  return availableDays.map((day) => byRound.get(day) || 0);
};

export const buildExternalFlowSeries = ({
  availableDays,
  quantityView,
  procurementState,
  salesState,
}) => {
  const upstreamProcurementOrders = collectExternalProcurementOrders(procurementState);
  const downstreamSalesOrders = collectExternalSalesOrders(salesState);

  return {
    upstreamProcurementOrders,
    downstreamSalesOrders,
    upstreamQuantitySeries: buildSeriesFromOrders(
      upstreamProcurementOrders,
      availableDays,
      quantityView,
      'order_time',
      'quantity',
      'material_id'
    ),
    downstreamQuantitySeries: buildSeriesFromOrders(
      downstreamSalesOrders,
      availableDays,
      quantityView,
      'created_time',
      'quantity',
      'product_id'
    ),
    upstreamCountSeries: buildCountSeriesFromOrders(
      upstreamProcurementOrders,
      availableDays,
      'order_time'
    ),
    downstreamCountSeries: buildCountSeriesFromOrders(
      downstreamSalesOrders,
      availableDays,
      'created_time'
    ),
  };
};

