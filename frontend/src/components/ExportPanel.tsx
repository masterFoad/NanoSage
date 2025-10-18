// frontend/src/components/ExportPanel.tsx

import React, { useState } from 'react';
import { ExportFormat } from '../types';
import { queryAPI } from '../services/api';

interface ExportPanelProps {
  queryId: string;
}

const ExportPanel: React.FC<ExportPanelProps> = ({ queryId }) => {
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>(ExportFormat.MARKDOWN);
  const [isExporting, setIsExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState<string>('');

  const handleExport = async () => {
    setIsExporting(true);
    setExportStatus('');

    try {
      const response = await queryAPI.exportQuery(queryId, selectedFormat);

      // Download the file
      const downloadUrl = `${process.env.REACT_APP_API_URL || 'http://localhost:8000'}${response.download_url}`;
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = response.filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      setExportStatus('Export completed successfully!');
      setTimeout(() => setExportStatus(''), 3000);
    } catch (error: any) {
      console.error('Export error:', error);
      setExportStatus(
        `Export failed: ${error.response?.data?.detail || error.message || 'Unknown error'}`
      );
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="export-panel">
      <h3>Export Results</h3>

      <div className="export-controls">
        <div className="format-selector">
          <label>
            <input
              type="radio"
              value={ExportFormat.MARKDOWN}
              checked={selectedFormat === ExportFormat.MARKDOWN}
              onChange={(e) => setSelectedFormat(e.target.value as ExportFormat)}
              disabled={isExporting}
            />
            Markdown
          </label>

          <label>
            <input
              type="radio"
              value={ExportFormat.TEXT}
              checked={selectedFormat === ExportFormat.TEXT}
              onChange={(e) => setSelectedFormat(e.target.value as ExportFormat)}
              disabled={isExporting}
            />
            Plain Text
          </label>

          <label>
            <input
              type="radio"
              value={ExportFormat.PDF}
              checked={selectedFormat === ExportFormat.PDF}
              onChange={(e) => setSelectedFormat(e.target.value as ExportFormat)}
              disabled={isExporting}
            />
            PDF
          </label>
        </div>

        <button
          className="export-button"
          onClick={handleExport}
          disabled={isExporting}
        >
          {isExporting ? (
            <>
              <span className="spinner-small"></span>
              Exporting...
            </>
          ) : (
            'Export'
          )}
        </button>
      </div>

      {exportStatus && (
        <div className={`export-status ${exportStatus.includes('failed') ? 'error' : 'success'}`}>
          {exportStatus}
        </div>
      )}
    </div>
  );
};

export default ExportPanel;
