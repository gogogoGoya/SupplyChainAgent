import React, { useState, useEffect } from 'react';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';

const CEOAnalysis = ({ company, day, dataRoot }) => {
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadCEOAnalysis();
  }, [company, day, dataRoot]);

  const loadCEOAnalysis = async () => {
    try {
      setLoading(true);
      setError(null);

      const data = (
        await safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/records/day${day}/analysis.json`))
        || await safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/analysis.json`))
      );
      if (!data) {
        throw new Error('无法加载CEO分析数据');
      }
      setAnalysis(data);
    } catch (error) {
      console.error('加载CEO分析数据失败:', error);
      setError('加载CEO分析数据失败: ' + error.message);
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

  if (!analysis) {
    return <div className="loading">暂无CEO分析数据</div>;
  }

  return (
    <div className="ceo-analysis">
      <h4>CEO分析</h4>
      <div className="ceo-summary">
        {analysis.enterprise_summarys}
      </div>
      {analysis.department_targets && (
        <div className="department-targets">
          <h5>部门目标</h5>
          {Object.entries(analysis.department_targets).map(([dept, target]) => (
            <div className="target-item" key={dept}>
              <div className="target-header">{dept.toUpperCase()}</div>
              <div className="target-content">{target.target}</div>
              <div className="target-content">评估标准: {target.evaluation}</div>
              <div className="target-reason">原因: {target.reason}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default CEOAnalysis;
