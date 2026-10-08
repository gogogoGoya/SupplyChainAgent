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
            phases.push({ label: 'Pre-execution', payload: preActionData });
          }
          if (actionData) {
            phases.push({ label: 'Execution', payload: actionData });
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
          // Some scenarios do not instantiate every department.
        }
      }

      setActions(actionList);
    } catch (error) {
      console.error('Failed to load action data:', error);
      setError('Failed to load action data: ' + error.message);
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
    return <div className="loading">Loading...</div>;
  }

  if (error) {
    return <div className="error">{error}</div>;
  }

  if (actions.length === 0) {
    return <div className="loading">No action data available</div>;
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
      return <div className="action-detail-item">No details available</div>;
    }

    // A pass-only response explains why no action was submitted.
    const hasPassReason = actions.some(item => item.pass_reason);
    const hasAction = actions.some(item => item.action);

    if (hasPassReason && !hasAction) {
      return (
        <div className="action-details">
          <div className="pass-reason-section">
            <h4>{actionType}{actionType ? ' - ' : ''}Reason Not Executed</h4>
            {actions.map((item, idx) => (
              <div key={idx} className="pass-reason-item">
                <div className="pass-reason-content">{item.pass_reason || 'None provided'}</div>
              </div>
            ))}
          </div>
        </div>
      );
    }

    return (
      <div className="action-details">
        {/* Executed action details */}
        <div className="action-section">
          <h4>{actionType}{actionType ? ' - ' : ''}Executed Actions</h4>
          {actions.length > 0 ? (
            actions.map((action, idx) => (
              <div key={idx} className="action-detail-item">
                {action.action ? (
                  <>
                    <div className="action-name">
                      <strong>Action:</strong> {getActionDisplayName(action.action?.action_name)}
                    </div>
                    {action.action?.action_param && typeof action.action.action_param === 'object' && !Array.isArray(action.action.action_param) ? (
                      <div className="action-params">
                        <strong>Parameters:</strong>
                        {Object.entries(action.action.action_param).map(([key, value], paramIdx) => (
                          <span key={paramIdx} className="action-param">
                            {key}: {formatValue(value)}
                          </span>
                        ))}
                      </div>
                    ) : action.action?.action_param ? (
                      <div className="action-reason">
                        <strong>Parameters:</strong> {formatValue(action.action.action_param)}
                      </div>
                    )}
                    <div className="action-reason">
                      <strong>Reason:</strong> {action.action_reason || 'None provided'}
                    </div>
                    <div className="action-meta">
                      <span className="module-type">Module: {action.module_type || 'Unknown'}</span>
                      <span className="executor">Executor: {action.executor_id || 'Unknown'}</span>
                    </div>
                  </>
                ) : action.pass_reason ? (
                  <div className="pass-reason-content">
                    <strong>Reason Not Executed:</strong> {action.pass_reason}
                  </div>
                ) : (
                  <div className="action-detail-item">No executed action</div>
                )}
              </div>
            ))
          ) : (
            <div className="action-detail-item">No executed action</div>
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
            {action.department.toUpperCase()} Department Actions
            {action.hasPreAction && action.hasAction && <span className="action-phase-indicator"> (Pre-execution + Execution)</span>}
            {action.hasPreAction && !action.hasAction && <span className="action-phase-indicator"> (Pre-execution)</span>}
            {!action.hasPreAction && action.hasAction && <span className="action-phase-indicator"> (Execution)</span>}
          </div>
          <div className="action-content">Click to view details</div>
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
