import React from 'react';

const CompanySelector = ({ companies, companyNameMap = {}, currentCompany, onCompanyChange }) => {
  return (
    <div className="company-selector">
      <h3>Select enterprise</h3>
      <div className="company-buttons">
        {companies.map(company => (
          <button
            key={company}
            className={`company-btn ${currentCompany === company ? 'active' : ''}`}
            onClick={() => onCompanyChange(company)}
          >
            {companyNameMap[company] || company}
          </button>
        ))}
      </div>
    </div>
  );
};

export default CompanySelector;
