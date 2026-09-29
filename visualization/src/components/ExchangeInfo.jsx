import React, { useEffect, useState } from 'react';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';
import { convertQuantityByItem, getDisplayItemLabel, getQuantityColumnLabel } from '../utils/productEquivalent';

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

const formatCurrency = (value) => `¥${formatNumber(value)}`;

const ExchangeInfo = ({ day, selectedExchangeId, onSelectExchange, dataRoot, quantityView }) => {
  const [exchangeData, setExchangeData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadExchangeData();
  }, [day, dataRoot]);

  const loadExchangeData = async () => {
    try {
      setLoading(true);
      setError(null);

      const data = await safeFetchJson(buildDataUrl(dataRoot, `public/exchange/day${day}/exchange.json`));
      if (!data) {
        throw new Error('无法加载交易所数据');
      }
      setExchangeData(data);

      const exchanges = Object.values(data?.data?.exchanges || {});
      const selectedStillExists = exchanges.some((exchange) => exchange.id === selectedExchangeId);
      if ((!selectedExchangeId || !selectedStillExists) && exchanges.length > 0) {
        onSelectExchange?.(exchanges[0].id);
      }
    } catch (loadError) {
      console.error('加载交易所数据失败:', loadError);
      setError('加载交易所数据失败: ' + loadError.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="loading">加载中...</div>;
  }

  if (error) {
    return <div className="error">{error}</div>;
  }

  if (!exchangeData || !exchangeData.data) {
    return <div className="loading">暂无交易所数据</div>;
  }

  const { global_info = {}, exchanges = {} } = exchangeData.data;
  const exchangeList = Object.values(exchanges || {});

  const renderFieldGrid = (fields) => (
    <div className="order-field-grid">
      {fields.map((field) => (
        <div className="order-field-card" key={`${field.label}-${field.value}`}>
          <span>{field.label}</span>
          <strong>{field.value}</strong>
        </div>
      ))}
    </div>
  );

  const renderRequests = (requests, title) => {
    if (!requests || !requests.list || requests.list.length === 0) {
      return <div className="request-empty">暂无{title}</div>;
    }

    // 按轮次分组
    const requestsByRound = requests.list.reduce((acc, request) => {
      const round = request.created_round;
      if (!acc[round]) {
        acc[round] = [];
      }
      acc[round].push(request);
      return acc;
    }, {});

    const quantityLabel = getQuantityColumnLabel('数量', quantityView);
    const remainingLabel = getQuantityColumnLabel('剩余', quantityView);

    return (
      <div className="requests-section">
        <h4>{title}</h4>
        {Object.entries(requestsByRound).sort(([a], [b]) => a - b).map(([round, roundRequests]) => (
          <div key={`round-${round}`} className="round-section">
            <div className="round-header">轮次 {round}</div>
            {roundRequests.map((request) => (
              <div key={request.request_id} className="request-item">
                <div className="request-mainline">
                  <strong>{getDisplayItemLabel(request.product_id, quantityView)}</strong>
                  <span>{quantityLabel}: {formatNumber(convertQuantityByItem(request.quantity, request.product_id, quantityView))}</span>
                  <span>{remainingLabel}: {formatNumber(convertQuantityByItem(request.open_quantity, request.product_id, quantityView))}</span>
                </div>
                {renderFieldGrid([
                  { label: '请求ID', value: request.request_id },
                  { label: '企业', value: request.buyer_company_id || request.seller_company_id },
                  { label: '价格', value: formatCurrency(request.max_price ?? request.min_price) },
                  { label: '创建轮次', value: request.created_round },
                  { label: '状态', value: request.active ? '活跃' : '已关闭' }
                ])}
              </div>
            ))}
          </div>
        ))}
      </div>
    );
  };

  const renderProposals = (proposals) => {
    if (!proposals || !proposals.list || proposals.list.length === 0) {
      return <div className="request-empty">暂无提案</div>;
    }

    // 按轮次分组
    const proposalsByRound = proposals.list.reduce((acc, proposal) => {
      const round = proposal.created_round;
      if (!acc[round]) {
        acc[round] = [];
      }
      acc[round].push(proposal);
      return acc;
    }, {});

    const quantityLabel = getQuantityColumnLabel('数量', quantityView);

    return (
      <div className="proposals-section">
        <h4>提案</h4>
        {Object.entries(proposalsByRound).sort(([a], [b]) => a - b).map(([round, roundProposals]) => (
          <div key={`proposal-round-${round}`} className="round-section">
            <div className="round-header">轮次 {round}</div>
            {roundProposals.map((proposal) => (
              <div key={proposal.proposal_id} className="proposal-item">
                <div className="proposal-mainline">
                  <strong>{getDisplayItemLabel(proposal.product_id, quantityView)}</strong>
                  <span>{quantityLabel}: {formatNumber(convertQuantityByItem(proposal.quantity, proposal.product_id, quantityView))}</span>
                  <span>价格: {formatCurrency(proposal.proposed_price)}</span>
                </div>
                {renderFieldGrid([
                  { label: '提案ID', value: proposal.proposal_id },
                  { label: '买方', value: proposal.buyer_company_id },
                  { label: '卖方', value: proposal.seller_company_id },
                  { label: '创建轮次', value: proposal.created_round },
                  { label: '状态', value: proposal.status },
                  { label: '买方响应', value: proposal.buyer_response },
                  { label: '卖方响应', value: proposal.seller_response }
                ])}
              </div>
            ))}
          </div>
        ))}
      </div>
    );
  };

  const renderOrders = (orders) => {
    if (!orders || !orders.list || orders.list.length === 0) {
      return <div className="request-empty">暂无订单</div>;
    }

    // 按轮次分组
    const ordersByRound = orders.list.reduce((acc, order) => {
      const round = order.created_round;
      if (!acc[round]) {
        acc[round] = [];
      }
      acc[round].push(order);
      return acc;
    }, {});

    const quantityLabel = getQuantityColumnLabel('数量', quantityView);

    return (
      <div className="orders-section">
        <h4>最终订单</h4>
        {Object.entries(ordersByRound).sort(([a], [b]) => a - b).map(([round, roundOrders]) => (
          <div key={`order-round-${round}`} className="round-section">
            <div className="round-header">轮次 {round}</div>
            {roundOrders.map((order) => (
              <div key={order.order_id} className="order-item">
                <div className="order-mainline">
                  <strong>{getDisplayItemLabel(order.product_id, quantityView)}</strong>
                  <span>{quantityLabel}: {formatNumber(convertQuantityByItem(order.quantity, order.product_id, quantityView))}</span>
                  <span>价格: {formatCurrency(order.agreed_price)}</span>
                </div>
                {renderFieldGrid([
                  { label: '订单ID', value: order.order_id },
                  { label: '买方', value: order.buyer_company_id },
                  { label: '卖方', value: order.seller_company_id },
                  { label: '创建轮次', value: order.created_round },
                  { label: '计划交付轮次', value: order.planned_delivery_round },
                  { label: '状态', value: order.status }
                ])}
              </div>
            ))}
          </div>
        ))}
      </div>
    );
  };

  const renderProductStatistics = (statistics) => {
    if (!statistics) {
      return null;
    }

    return (
      <div className="product-statistics-section">
        <h4>产品统计</h4>
        {Object.entries(statistics).map(([product, stats]) => (
          <div key={product} className="product-statistics-item">
            <h5>{getDisplayItemLabel(product, quantityView)}</h5>
            {renderFieldGrid([
              { label: getQuantityColumnLabel('购买数量', quantityView), value: formatNumber(convertQuantityByItem(stats.buy_quantity, product, quantityView)) },
              { label: getQuantityColumnLabel('销售数量', quantityView), value: formatNumber(convertQuantityByItem(stats.sell_quantity, product, quantityView)) },
              { label: getQuantityColumnLabel('提案数量', quantityView), value: formatNumber(convertQuantityByItem(stats.proposal_quantity, product, quantityView)) },
              { label: getQuantityColumnLabel('订单数量', quantityView), value: formatNumber(convertQuantityByItem(stats.order_quantity, product, quantityView)) }
            ])}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="exchange-info">
      <div className="exchange-card exchange-global-card">
        <div className="exchange-header">全局信息</div>
        <div className="exchange-stats">
          <div className="stat-item">
            <div className="stat-label">总交易所</div>
            <div className="stat-value">{global_info.total_exchanges}</div>
          </div>
          <div className="stat-item">
            <div className="stat-label">注册企业数</div>
            <div className="stat-value">{global_info.total_registered_enterprises}</div>
          </div>
        </div>
      </div>

      {exchangeList.map((exchange) => {
        const isSelected = exchange.id === selectedExchangeId;

        return (
          <div
            className={`exchange-card exchange-card-selectable ${isSelected ? 'selected' : ''}`}
            key={exchange.id}
          >
            <button
              type="button"
              className="exchange-select-trigger"
              onClick={() => onSelectExchange?.(exchange.id)}
            >
              <div className="exchange-header">
                {exchange.id} - {exchange.upstream_layers.join(' → ')} → {exchange.downstream_layers.join(' → ')}
              </div>
              <div className="exchange-stats">
                <div className="stat-item">
                  <div className="stat-label">购买请求</div>
                  <div className="stat-value">{exchange.buy_requests?.count || 0}</div>
                </div>
                <div className="stat-item">
                  <div className="stat-label">销售请求</div>
                  <div className="stat-value">{exchange.sell_requests?.count || 0}</div>
                </div>
                <div className="stat-item">
                  <div className="stat-label">提案</div>
                  <div className="stat-value">{exchange.proposals?.count || 0}</div>
                </div>
                <div className="stat-item">
                  <div className="stat-label">订单</div>
                  <div className="stat-value">{exchange.orders?.count || 0}</div>
                </div>
              </div>
            </button>

            {isSelected && (
              <div className="exchange-details">
                {renderRequests(exchange.buy_requests, '采购请求')}
                {renderRequests(exchange.sell_requests, '销售请求')}
                {renderProposals(exchange.proposals)}
                {renderOrders(exchange.orders)}
                {renderProductStatistics(exchange.product_statistics)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default ExchangeInfo;
