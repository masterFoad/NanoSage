// frontend/src/components/ResultsDisplay.tsx

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { QueryResult, WebResult, LocalResult } from '../types';
import SearchTree from './SearchTree';
import ExportPanel from './ExportPanel';

interface ResultsDisplayProps {
  result: QueryResult;
}

const ResultsDisplay: React.FC<ResultsDisplayProps> = ({ result }) => {
  const [activeTab, setActiveTab] = useState<'answer' | 'sources' | 'tree'>('answer');
  const [copied, setCopied] = useState(false);

  const handleCopyText = () => {
    if (result.final_answer) {
      navigator.clipboard.writeText(result.final_answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const formatProcessingTime = (ms?: number) => {
    if (!ms) return 'N/A';
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
  };

  return (
    <div className="results-display">
      {/* Header */}
      <div className="results-header">
        <h2>{result.query_text}</h2>

        <div className="results-meta">
          <span className={`status-badge status-${result.status}`}>
            {result.status.toUpperCase()}
          </span>

          {result.processing_time_ms && (
            <span className="meta-item">
              Processing Time: {formatProcessingTime(result.processing_time_ms)}
            </span>
          )}

          {result.created_at && (
            <span className="meta-item">
              Created: {new Date(result.created_at).toLocaleString()}
            </span>
          )}
        </div>
      </div>

      {/* Error Message */}
      {result.error_message && (
        <div className="error-banner">
          <strong>Error:</strong> {result.error_message}
        </div>
      )}

      {/* Tabs */}
      {result.status === 'completed' && result.final_answer && (
        <>
          <div className="results-tabs">
            <button
              className={activeTab === 'answer' ? 'active' : ''}
              onClick={() => setActiveTab('answer')}
            >
              Final Answer
            </button>
            <button
              className={activeTab === 'sources' ? 'active' : ''}
              onClick={() => setActiveTab('sources')}
            >
              Sources ({(result.web_results?.length || 0) + (result.local_results?.length || 0)})
            </button>
            {result.search_tree && (
              <button
                className={activeTab === 'tree' ? 'active' : ''}
                onClick={() => setActiveTab('tree')}
              >
                Search Tree
              </button>
            )}
          </div>

          {/* Tab Content */}
          <div className="tab-content">
            {activeTab === 'answer' && (
              <div className="answer-tab">
                <div className="answer-actions">
                  <button onClick={handleCopyText} className="copy-button">
                    {copied ? '✓ Copied!' : 'Copy Text'}
                  </button>
                </div>

                <div className="answer-content">
                  <ReactMarkdown>{result.final_answer}</ReactMarkdown>
                </div>

                <ExportPanel queryId={result.query_id} />
              </div>
            )}

            {activeTab === 'sources' && (
              <div className="sources-tab">
                {/* Web Results */}
                {result.web_results && result.web_results.length > 0 && (
                  <div className="source-section">
                    <h3>Web Sources ({result.web_results.length})</h3>
                    <div className="source-list">
                      {result.web_results.map((source: WebResult, index: number) => (
                        <div key={index} className="source-item web-source">
                          <div className="source-header">
                            <h4>
                              {index + 1}. {source.title}
                            </h4>
                            {source.relevance && (
                              <span className="relevance-score">
                                Relevance: {(source.relevance * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                          <a
                            href={source.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="source-url"
                          >
                            {source.url}
                          </a>
                          <p className="source-snippet">{source.snippet}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Local Results */}
                {result.local_results && result.local_results.length > 0 && (
                  <div className="source-section">
                    <h3>Local Sources ({result.local_results.length})</h3>
                    <div className="source-list">
                      {result.local_results.map((source: LocalResult, index: number) => (
                        <div key={index} className="source-item local-source">
                          <div className="source-header">
                            <h4>
                              {index + 1}. {source.source}
                            </h4>
                            {source.relevance && (
                              <span className="relevance-score">
                                Relevance: {(source.relevance * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                          <p className="source-snippet">{source.snippet}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {(!result.web_results || result.web_results.length === 0) &&
                 (!result.local_results || result.local_results.length === 0) && (
                  <div className="no-sources">
                    <p>No sources available</p>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'tree' && result.search_tree && (
              <div className="tree-tab">
                <SearchTree tree={result.search_tree} />
              </div>
            )}

            {activeTab === 'tree' && !result.search_tree && (
              <div className="no-tree">
                <p>Search tree unavailable</p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default ResultsDisplay;
