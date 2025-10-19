// frontend/src/App.tsx

import React, { useState, useEffect, useRef } from 'react';
import QueryForm from './components/QueryForm';
import ResultsDisplay from './components/ResultsDisplay';
import ProgressTracker from './components/ProgressTracker';
import QueryHistory from './components/QueryHistory';
import { QueryParameters, QueryResult, ProgressUpdate, QueryStatus } from './types';
import { queryAPI } from './services/api';
import './App.css';

const App: React.FC = () => {
  const [currentQueryId, setCurrentQueryId] = useState<string | null>(null);
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [progressUpdates, setProgressUpdates] = useState<ProgressUpdate[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Cleanup WebSocket on unmount
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const handleSubmitQuery = async (parameters: QueryParameters) => {
    setIsLoading(true);
    setError(null);
    setQueryResult(null);
    setProgressUpdates([]);

    try {
      // Submit query
      const response = await queryAPI.submitQuery(parameters);
      const queryId = response.query_id;
      setCurrentQueryId(queryId);

      // Connect to WebSocket for real-time updates
      connectWebSocket(queryId);

      // Fetch initial status (one-time only, no continuous polling)
      // WebSocket will handle real-time updates
      pollQueryStatus(queryId);
    } catch (err: any) {
      console.error('Error submitting query:', err);
      setError(err.response?.data?.detail || err.message || 'Failed to submit query');
      setIsLoading(false);
    }
  };

  const connectWebSocket = (queryId: string) => {
    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    // Create new WebSocket connection
    wsRef.current = queryAPI.connectWebSocket(
      queryId,
      (update: ProgressUpdate) => {
        console.log('WebSocket update:', update);
        setProgressUpdates((prev) => [...prev, update]);

        // Update query result status
        if (update.status === QueryStatus.COMPLETED || update.status === QueryStatus.FAILED) {
          pollQueryStatus(queryId, true); // Force final fetch
        }
      },
      (error: Event) => {
        console.error('WebSocket error:', error);
      },
      (event: CloseEvent) => {
        console.log('WebSocket closed:', event);
      }
    );
  };

  const pollQueryStatus = async (queryId: string, forceFetch: boolean = false) => {
    try {
      const result = await queryAPI.getQuery(queryId);
      setQueryResult(result);

      if (result.status === QueryStatus.COMPLETED || result.status === QueryStatus.FAILED) {
        setIsLoading(false);
        if (wsRef.current) {
          wsRef.current.close();
        }
      } else if (!forceFetch) {
        // Only poll if WebSocket is not connected (fallback mechanism)
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          console.log('WebSocket not connected, falling back to polling');
          setTimeout(() => pollQueryStatus(queryId), 2000);
        }
        // Otherwise, rely on WebSocket for updates
      }
    } catch (err: any) {
      console.error('Error fetching query status:', err);
      setError(err.response?.data?.detail || err.message || 'Failed to fetch query status');
      setIsLoading(false);
    }
  };

  const handleSelectHistoryQuery = async (queryId: string) => {
    setIsLoading(true);
    setError(null);
    setProgressUpdates([]);
    setCurrentQueryId(queryId);

    try {
      // Try to load from history first
      const response = await fetch(`http://localhost:8000/api/history/${queryId}`);

      if (response.ok) {
        const result = await response.json();
        setQueryResult(result);
        setIsLoading(false);
      } else if (response.status === 404) {
        // Query not found in history, try active queries
        try {
          const result = await queryAPI.getQuery(queryId);
          setQueryResult(result);
          setIsLoading(false);
        } catch {
          // Query doesn't exist anywhere
          setError(`Query ${queryId.substring(0, 8)} not found. It may have been auto-deleted from history.`);
          setIsLoading(false);
          // Clear from localStorage
          localStorage.removeItem('lastSelectedQuery');
        }
      } else {
        // Other error
        const errorData = await response.json();
        setError(errorData.error || 'Failed to load query from history');
        setIsLoading(false);
      }
    } catch (err: any) {
      console.error('Error loading query from history:', err);
      setError(err.message || 'Failed to load query from history');
      setIsLoading(false);
    }
  };

  return (
    <div className={`app ${historyOpen ? 'with-sidebar' : ''}`}>
      {/* Query History Sidebar */}
      <QueryHistory
        onSelectQuery={handleSelectHistoryQuery}
        isOpen={historyOpen}
        onToggle={() => setHistoryOpen(!historyOpen)}
        currentQueryId={currentQueryId || undefined}
      />

      {/* Header */}
      <header className="app-header">
        <div className="container">
          <h1>🧙‍♂️ NanoSage</h1>
          <p className="tagline">Advanced Recursive Search & Report Generation</p>
        </div>
      </header>

      {/* Main Content */}
      <main className="app-main">
        <div className="container">
          {/* Error Banner */}
          {error && (
            <div className="error-banner global-error">
              <strong>Error:</strong> {error}
              <button onClick={() => setError(null)} className="close-button">
                ×
              </button>
            </div>
          )}

          {/* Query Form */}
          <section className="query-section">
            <QueryForm onSubmit={handleSubmitQuery} isLoading={isLoading} />
          </section>

          {/* Progress Tracker */}
          {isLoading && (
            <section className="progress-section">
              <ProgressTracker
                updates={progressUpdates}
                currentStatus={queryResult?.status || QueryStatus.PROCESSING}
              />
            </section>
          )}

          {/* Results */}
          {queryResult && queryResult.status === QueryStatus.COMPLETED && (
            <section className="results-section">
              <ResultsDisplay result={queryResult} />
            </section>
          )}

          {/* Failed State */}
          {queryResult && queryResult.status === QueryStatus.FAILED && (
            <section className="results-section">
              <div className="error-state">
                <h2>Query Failed</h2>
                <p>{queryResult.error_message || 'An unknown error occurred'}</p>
                <button
                  onClick={() => {
                    setQueryResult(null);
                    setIsLoading(false);
                    setCurrentQueryId(null);
                  }}
                  className="retry-button"
                >
                  Try Again
                </button>
              </div>
            </section>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="app-footer">
        <div className="container">
          <p>
            Powered by NanoSage | Open Source Research Assistant |{' '}
            <a
              href="https://github.com/masterFoad/NanoSage"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
};

export default App;
