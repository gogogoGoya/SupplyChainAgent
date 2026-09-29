import React from 'react';

const DaySelector = ({ availableDays, currentDay, onDayChange }) => {
  return (
    <div className="day-selector">
      <h3>选择轮次</h3>
      <div className="day-buttons">
        {availableDays.map(day => (
          <button
            key={day}
            className={`day-btn ${day === currentDay ? 'active' : ''}`}
            onClick={() => onDayChange(day)}
          >
            Turn {day}
          </button>
        ))}
      </div>
    </div>
  );
};

export default DaySelector;
