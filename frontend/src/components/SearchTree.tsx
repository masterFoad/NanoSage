// frontend/src/components/SearchTree.tsx

import React, { useState } from 'react';
import { TOCNode } from '../types';

interface SearchTreeProps {
  tree: TOCNode;
}

interface TreeNodeProps {
  node: TOCNode;
  depth: number;
}

const TreeNode: React.FC<TreeNodeProps> = ({ node, depth }) => {
  const [isExpanded, setIsExpanded] = useState(depth === 0);

  const hasChildren = node.children && node.children.length > 0;

  const toggleExpand = () => {
    if (hasChildren) {
      setIsExpanded(!isExpanded);
    }
  };

  const relevanceColor = (score: number) => {
    if (score >= 0.8) return '#27ae60';
    if (score >= 0.6) return '#f39c12';
    if (score >= 0.4) return '#e67e22';
    return '#e74c3c';
  };

  return (
    <div className="tree-node" style={{ marginLeft: `${depth * 20}px` }}>
      <div className="tree-node-header" onClick={toggleExpand}>
        {hasChildren && (
          <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
        )}
        {!hasChildren && <span className="expand-placeholder"></span>}

        <div className="tree-node-content">
          <div className="tree-node-title">
            <span className="query-text">{node.query_text}</span>
            <span
              className="relevance-badge"
              style={{ backgroundColor: relevanceColor(node.relevance_score) }}
            >
              {(node.relevance_score * 100).toFixed(0)}%
            </span>
          </div>

          {node.summary && (
            <div className="tree-node-summary">{node.summary}</div>
          )}

          {node.metrics && (
            <div className="tree-node-metrics">
              <span>Web: {node.metrics.web_results_count}</span>
              <span>Docs: {node.metrics.corpus_entries_count}</span>
              {node.metrics.processing_time_ms > 0 && (
                <span>Time: {node.metrics.processing_time_ms}ms</span>
              )}
            </div>
          )}
        </div>
      </div>

      {isExpanded && hasChildren && (
        <div className="tree-node-children">
          {node.children.map((child, index) => (
            <TreeNode key={child.node_id || index} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

const SearchTree: React.FC<SearchTreeProps> = ({ tree }) => {
  return (
    <div className="search-tree">
      <div className="search-tree-header">
        <h3>Search Tree</h3>
        <p>Explore how NanoSage navigated through your query</p>
      </div>

      <div className="search-tree-content">
        <TreeNode node={tree} depth={0} />
      </div>
    </div>
  );
};

export default SearchTree;
