import React, { useState, useEffect } from 'react';
import { buildDataUrl, safeFetchText } from '../utils/dataSource';

const CompanyInfo = ({ company, day, dataRoot }) => {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadCompanyInfo();
  }, [company, day, dataRoot]);

  const loadCompanyInfo = async () => {
    try {
      setLoading(true);
      setError(null);

      const text = await safeFetchText(
        buildDataUrl(dataRoot, `enterprises/${company}/observations/observation_day${day}.txt`)
      );
      if (!text) {
        throw new Error('Unable to load observation data');
      }
      const data = JSON.parse(text);
      setInfo(data);
    } catch (error) {
      console.error('Failed to load enterprise information:', error);
      setError('Failed to load enterprise information: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (value) => {
    if (value === null || value === undefined || value === '') {
      return '¥-';
    }
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return '¥-';
    }
    return `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(numeric)}`;
  };

  if (loading) {
    return <div className="loading">Loading...</div>;
  }

  if (error) {
    return <div className="error">{error}</div>;
  }

  if (!info) {
    return <div className="loading">No data available</div>;
  }

  const finance = info.finance?.self_state || info.finance || {};
  const financialIndicators = finance.financial_indicators || {};

  return (
    <div className="company-info">
      <div className="metric-card">
        <div className="metric-label">Enterprise</div>
        <div className="metric-value">{company}</div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Cash balance</div>
        <div className="metric-value">{formatCurrency(finance.cash || 0)}</div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Total revenue</div>
        <div className="metric-value">{formatCurrency(finance.total_revenue || 0)}</div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Total cost</div>
        <div className="metric-value">{formatCurrency(finance.total_cost || 0)}</div>
      </div>
      {Object.keys(financialIndicators).length > 0 && (
        <div className="metric-card">
          <div className="metric-label">Net profit</div>
          <div className="metric-value">{formatCurrency(financialIndicators.net_profit || 0)}</div>
        </div>
      )}
    </div>
  );
};

export default CompanyInfo;
