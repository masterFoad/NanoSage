// frontend/src/components/ProgressTracker.tsx

import React from 'react';
import { ProgressUpdate, QueryStatus } from '../types';

interface ProgressTrackerProps {
  updates: ProgressUpdate[];
  currentStatus: QueryStatus;
}

const ProgressTracker: React.FC<ProgressTrackerProps> = ({ updates, currentStatus }) => {
  const latestUpdate = updates.length > 0 ? updates[updates.length - 1] : null;

  const getStatusColor = (status: QueryStatus) => {
    switch (status) {
      case QueryStatus.PENDING:
        return '#95a5a6';
      case QueryStatus.PROCESSING:
        return '#3498db';
      case QueryStatus.COMPLETED:
        return '#27ae60';
      case QueryStatus.FAILED:
        return '#e74c3c';
      default:
        return '#95a5a6';
    }
  };

  const getStatusIcon = (status: QueryStatus) => {
    switch (status) {
      case QueryStatus.PENDING:
        return '⏳';
      case QueryStatus.PROCESSING:
        return '🔄';
      case QueryStatus.COMPLETED:
        return '✓';
      case QueryStatus.FAILED:
        return '✗';
      default:
        return '•';
    }
  };

  return (
    <div className="progress-tracker">
      <div className="progress-header">
        <h3>
          <span className="status-icon">{getStatusIcon(currentStatus)}</span>
          Query Progress
        </h3>
        <span
          className="status-badge"
          style={{ backgroundColor: getStatusColor(currentStatus) }}
        >
          {currentStatus.toUpperCase()}
        </span>
      </div>

      {/* Progress Bar */}
      {latestUpdate && latestUpdate.progress_percentage !== undefined && (
        <div className="progress-bar-container">
          <div
            className="progress-bar"
            style={{
              width: `${latestUpdate.progress_percentage}%`,
              backgroundColor: getStatusColor(currentStatus),
            }}
          >
            <span className="progress-text">{latestUpdate.progress_percentage}%</span>
          </div>
        </div>
      )}

      {/* Current Message */}
      {latestUpdate && (
        <div className="current-message">
          <p>{latestUpdate.message}</p>
          {latestUpdate.current_step && (
            <p className="step-info">
              Step: {latestUpdate.current_step}
              {latestUpdate.total_steps && ` (${latestUpdate.completed_steps || 0} / ${latestUpdate.total_steps})`}
            </p>
          )}
        </div>
      )}

      {/* Spinner for Processing */}
      {currentStatus === QueryStatus.PROCESSING && (
        <div className="spinner-container">
          <div className="spinner-large"></div>
        </div>
      )}

      {/* Update Timeline */}
      <div className="update-timeline">
        <h4>Activity Log</h4>
        <div className="timeline-list">
          {updates.slice().reverse().map((update, index) => (
            <div key={index} className="timeline-item">
              <span className="timeline-time">
                {new Date(update.timestamp).toLocaleTimeString()}
              </span>
              <span className="timeline-message">{update.message}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ProgressTracker;
