import React, { useState, useEffect } from 'react';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';
import { getActionDisplayName } from '../utils/actionLabels';

const ActionList = ({ company, day, dataRoot }) => {
  const [actions, setActions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedIndex, setExpandedIndex] = useState(null);

  useEffect(() => {
    loadActions();
  }, [company, day, dataRoot]);

  const loadActions = async () => {
    try {
      setLoading(true);
      setError(null);

      const departments = ['finance', 'sales', 'inventory', 'procurement', 'hr', 'production'];
      const actionList = [];

      for (const dept of departments) {
        try {
          const phases = [];
          const [preActionData, actionData] = await Promise.all([
            safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/${dept}/day${day}/pre_${dept}_action.json`)),
            safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/department/${dept}/day${day}/${dept}_action.json`)),
          ]);

          if (preActionData) {
            phases.push({ label: '预执行阶段', payload: preActionData });
          }
          if (actionData) {
            phases.push({ label: '执行阶段', payload: actionData });
          }
          if (phases.length > 0) {
            actionList.push({
              department: dept,
              action: phases,
              hasPreAction: Boolean(preActionData),
              hasAction: Boolean(actionData)
            });
          }
        } catch (e) {
          // 忽略不存在的部门
        }
      }

      setActions(actionList);
    } catch (error) {
      console.error('加载动作数据失败:', error);
      setError('加载动作数据失败: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleDetails = (index) => {
    setExpandedIndex(expandedIndex === index ? null : index);
  };

  const formatValue = (value) => {
    if (value === null || value === undefined || value === '') {
      return '-';
    }
    if (typeof value === 'object') {
      return JSON.stringify(value);
    }
    return String(value);
  };

  if (loading) {
    return <div className="loading">加载中...</div>;
  }

  if (error) {
    return <div className="error">{error}</div>;
  }

  if (actions.length === 0) {
    return <div className="loading">暂无动作数据</div>;
  }

  const normalizeActionItems = (actionData) => {
    if (!Array.isArray(actionData)) {
      return [];
    }
    if (actionData.length === 1 && Array.isArray(actionData[0])) {
      return actionData[0];
    }
    return actionData.filter((item) => item && typeof item === 'object');
  };

  const renderActionDetails = (actionData, actionType = '') => {
    const actions = normalizeActionItems(actionData);

    if (actions.length === 0) {
      return <div className="action-detail-item">暂无详细信息</div>;
    }

    // 检查是否有 pass_reason
    const hasPassReason = actions.some(item => item.pass_reason);
    const hasAction = actions.some(item => item.action);

    if (hasPassReason && !hasAction) {
      // 只显示未执行原因
      return (
        <div className="action-details">
          <div className="pass-reason-section">
            <h4>{actionType}{actionType ? ' - ' : ''}未执行原因</h4>
            {actions.map((item, idx) => (
              <div key={idx} className="pass-reason-item">
                <div className="pass-reason-content">{item.pass_reason || '无'}</div>
              </div>
            ))}
          </div>
        </div>
      );
    }

    return (
      <div className="action-details">
        {/* 执行的动作信息 */}
        <div className="action-section">
          <h4>{actionType}{actionType ? ' - ' : ''}执行的动作</h4>
          {actions.length > 0 ? (
            actions.map((action, idx) => (
              <div key={idx} className="action-detail-item">
                {action.action ? (
                  <>
                    <div className="action-name">
                      <strong>动作:</strong> {getActionDisplayName(action.action?.action_name)}
                    </div>
                    {action.action?.action_param && typeof action.action.action_param === 'object' && !Array.isArray(action.action.action_param) ? (
                      <div className="action-params">
                        <strong>参数:</strong> 
                        {Object.entries(action.action.action_param).map(([key, value], paramIdx) => (
                          <span key={paramIdx} className="action-param">
                            {key}: {formatValue(value)}
                          </span>
                        ))}
                      </div>
                    ) : action.action?.action_param ? (
                      <div className="action-reason">
                        <strong>参数:</strong> {formatValue(action.action.action_param)}
                      </div>
                    )}
                    <div className="action-reason">
                      <strong>原因:</strong> {action.action_reason || '无'}
                    </div>
                    <div className="action-meta">
                      <span className="module-type">模块: {action.module_type || '未知'}</span>
                      <span className="executor">执行: {action.executor_id || '未知'}</span>
                    </div>
                  </>
                ) : action.pass_reason ? (
                  <div className="pass-reason-content">
                    <strong>未执行原因:</strong> {action.pass_reason}
                  </div>
                ) : (
                  <div className="action-detail-item">暂无执行动作</div>
                )}
              </div>
            ))
          ) : (
            <div className="action-detail-item">暂无执行动作</div>
          )}
        </div>

      </div>
    );
  };

  return (
    <div className="action-list">
      {actions.map((action, index) => (
        <div className="action-item" key={index} onClick={() => toggleDetails(index)}>
          <div className="action-header">
            {action.department.toUpperCase()} 部门动作
            {action.hasPreAction && action.hasAction && <span className="action-phase-indicator"> (预执行 + 执行)</span>}
            {action.hasPreAction && !action.hasAction && <span className="action-phase-indicator"> (预执行)</span>}
            {!action.hasPreAction && action.hasAction && <span className="action-phase-indicator"> (执行)</span>}
          </div>
          <div className="action-content">点击查看详情</div>
          <div className={`details-panel ${expandedIndex === index ? 'active' : ''}`}>
            {Array.isArray(action.action) && action.action.map((phase) => (
              <React.Fragment key={phase.label}>
                {renderActionDetails(phase.payload, phase.label)}
              </React.Fragment>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

export default ActionList;
