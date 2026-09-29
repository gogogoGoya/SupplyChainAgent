import React, { useState, useEffect } from 'react';
import { buildDataUrl, safeFetchJson } from '../utils/dataSource';

const DEPARTMENTS = ['analyst', 'finance', 'sales', 'procurement', 'inventory', 'production', 'hr'];

const DEPARTMENT_LABELS = {
  analyst: '分析师',
  finance: '财务部门',
  sales: '销售部门',
  procurement: '采购部门',
  inventory: '库存部门',
  production: '生产部门',
  hr: '人力部门',
};

const formatMessageContent = (content) => {
  if (content === null || content === undefined) {
    return '';
  }
  if (typeof content === 'string') {
    return content;
  }
  if (Array.isArray(content)) {
    return content.map((item) => item?.text || item?.content || JSON.stringify(item)).join('\n');
  }
  return JSON.stringify(content, null, 2);
};

const DepartmentMessages = ({ company, day, dataRoot }) => {
  const [messages, setMessages] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('analyst');

  useEffect(() => {
    loadDepartmentMessages();
  }, [company, day, dataRoot]);

  const loadDepartmentMessages = async () => {
    try {
      setLoading(true);
      setError(null);

      const messagesData = {};

      await Promise.all(DEPARTMENTS.map(async (dept) => {
        const [normalMessages, scriptedMessages] = await Promise.all([
          safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/model_messages/day${day}/${dept}_messages.json`)),
          safeFetchJson(buildDataUrl(dataRoot, `enterprises/${company}/model_messages/day${day}/scripted_${dept}_messages.json`)),
        ]);
        const combinedMessages = [
          ...(Array.isArray(normalMessages) ? normalMessages : []),
          ...(Array.isArray(scriptedMessages) ? scriptedMessages : []),
        ];
        if (combinedMessages.length > 0) {
          messagesData[dept] = combinedMessages;
        }
      }));

      setMessages(messagesData);
    } catch (error) {
      console.error('加载部门消息失败:', error);
      setError('加载部门消息失败: ' + error.message);
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

  const tabs = DEPARTMENTS.filter((dept) => messages[dept]);

  if (tabs.length === 0) {
    return <div className="loading">暂无部门消息</div>;
  }

  return (
    <div className="department-messages">
      <div className="tabs">
        {tabs.map(tab => (
          <div
            key={tab}
            className={`tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {DEPARTMENT_LABELS[tab] || tab}
          </div>
        ))}
      </div>

      <div className="messages-list">
        {messages[activeTab] && messages[activeTab].map((message, index) => (
          <div className="message-item" key={index}>
            <div className="message-header">
              <div className="message-role">{message.role}</div>
            </div>
            <div className="message-content">
              {formatMessageContent(message.content)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default DepartmentMessages;
