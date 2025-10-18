// frontend/src/components/QueryHistory.tsx - ChatGPT/Claude Style

import React, { useState, useEffect } from 'react';
import './QueryHistory.css';

interface HistoryItem {
  query_id: string;
  query_text: string;
  status: string;
  created_at: string;
  completed_at?: string;
  processing_time_ms?: number;
  export_file?: string;
}

interface QueryHistoryProps {
  onSelectQuery: (queryId: string) => void;
  isOpen: boolean;
  onToggle: () => void;
  currentQueryId?: string;
}

const QueryHistory: React.FC<QueryHistoryProps> = ({
  onSelectQuery,
  isOpen,
  onToggle,
  currentQueryId
}) => {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<any>(null);

  // Load history on mount and when opened
  useEffect(() => {
    if (isOpen) {
      loadHistory();
      loadStats();
    }
  }, [isOpen]);

  const loadHistory = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:8000/api/history?limit=10');

      if (!response.ok) {
        throw new Error('Failed to load history');
      }

      const data = await response.json();
      setHistory(data);

      // Also store in localStorage for quick access
      localStorage.setItem('queryHistory', JSON.stringify(data));
    } catch (err: any) {
      setError(err.message);

      // Try to load from localStorage as fallback (but don't use - server is source of truth)
      // localStorage cache is deprecated - always use server data
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/history/stats');
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (err) {
      console.error('Failed to load stats:', err);
    }
  };

  const handleSelectQuery = async (queryId: string) => {
    onSelectQuery(queryId);
    localStorage.setItem('lastSelectedQuery', queryId);
  };

  const handleDeleteQuery = async (queryId: string, event: React.MouseEvent) => {
    event.stopPropagation();

    if (!window.confirm('Delete this query from history?')) {
      return;
    }

    try {
      const response = await fetch(`http://localhost:8000/api/history/${queryId}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error('Failed to delete query');
      }

      // Reload history
      loadHistory();
      loadStats();
    } catch (err: any) {
      alert(`Error deleting query: ${err.message}`);
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm('Clear ALL query history? This cannot be undone!')) {
      return;
    }

    try {
      const response = await fetch('http://localhost:8000/api/history', {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error('Failed to clear history');
      }

      setHistory([]);
      localStorage.removeItem('queryHistory');
      loadStats();
    } catch (err: any) {
      alert(`Error clearing history: ${err.message}`);
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);

      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}d ago`;
      return date.toLocaleDateString();
    } catch {
      return dateStr;
    }
  };

  const formatDuration = (ms?: number) => {
    if (!ms) return null;
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <>
      <div className={`query-history ${isOpen ? 'open' : 'closed'}`}>
        {isOpen && (
          <>
            <div className="history-header">
              <h3>
                <span className="icon">💬</span>
                History
              </h3>
              <button className="toggle-btn" onClick={onToggle}>
                Close
              </button>
            </div>

            <div className="history-content">
              {/* Stats Section */}
              {stats && (
                <div className="history-stats">
                  <div className="stat-item">
                    <span className="stat-label">Queries</span>
                    <span className="stat-value">{stats.total_queries}</span>
                  </div>
                  <div className="stat-item">
                    <span className="stat-label">Avg Time</span>
                    <span className="stat-value">
                      {formatDuration(stats.average_processing_time_ms) || 'N/A'}
                    </span>
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="history-actions">
                <button onClick={loadHistory} disabled={loading}>
                  {loading ? 'Loading...' : 'Refresh'}
                </button>
                <button onClick={handleClearAll} className="btn-clear" disabled={history.length === 0}>
                  Clear All
                </button>
              </div>

              {/* Error Display */}
              {error && (
                <div className="history-error">
                  {error}
                </div>
              )}

              {/* History List */}
              <div className="history-list">
                {history.length === 0 ? (
                  <div className="empty-state">
                    <p>No history yet</p>
                    <p className="hint">Your queries will appear here</p>
                  </div>
                ) : (
                  history.map((item) => (
                    <div
                      key={item.query_id}
                      className={`history-item ${item.query_id === currentQueryId ? 'active' : ''}`}
                      onClick={() => handleSelectQuery(item.query_id)}
                    >
                      <div className="history-item-header">
                        <span className={`status-badge ${item.status}`}>
                          {item.status}
                        </span>
                        <button
                          className="btn-delete"
                          onClick={(e) => handleDeleteQuery(item.query_id, e)}
                          title="Delete"
                        >
                          ×
                        </button>
                      </div>

                      <div className="history-item-content">
                        <div className="query-text" title={item.query_text}>
                          {item.query_text}
                        </div>

                        <div className="query-meta">
                          <span className="meta-date">
                            {formatDate(item.created_at)}
                          </span>
                          {item.processing_time_ms && (
                            <span className="meta-time">
                              {formatDuration(item.processing_time_ms)}
                            </span>
                          )}
                          {item.export_file && (
                            <span className="meta-export" title="Exported"></span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Footer Info */}
              {stats && (
                <div className="history-footer">
                  Keeping last {stats.max_queries} queries
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Toggle button when sidebar is closed */}
      {!isOpen && (
        <button className="history-toggle-closed" onClick={onToggle} title="Open history">
          ☰
        </button>
      )}
    </>
  );
};

export default QueryHistory;
