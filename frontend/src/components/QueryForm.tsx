// frontend/src/components/QueryForm.tsx

import React, { useState, useRef } from 'react';
import { QueryParameters, RetrievalModel, LLMProvider, UploadedFile } from '../types';
import { queryAPI } from '../services/api';

interface QueryFormProps {
  onSubmit: (parameters: QueryParameters) => void;
  isLoading: boolean;
}

const QueryForm: React.FC<QueryFormProps> = ({ onSubmit, isLoading }) => {
  const [parameters, setParameters] = useState<QueryParameters>({
    query: '',
    web_search: true,
    retrieval_model: RetrievalModel.SIGLIP,
    top_k: 5,
    max_depth: 1,
    corpus_dir: '',
    attached_file_ids: [],
    personality: '',
    rag_model: 'gemma',
    llm_provider: LLMProvider.OLLAMA,
    llm_model: '',
    web_concurrency: 8,
    include_wikipedia: false,
  });

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!parameters.query.trim()) {
      newErrors.query = 'Enter a valid query';
    } else if (parameters.query.length > 500) {
      newErrors.query = 'Query must be 500 characters or less';
    }

    if (parameters.top_k < 1 || parameters.top_k > 20) {
      newErrors.top_k = 'Number of documents must be between 1 and 20';
    }

    if (parameters.max_depth < 1 || parameters.max_depth > 3) {
      newErrors.max_depth = 'Search depth must be between 1 and 3';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (validateForm()) {
      // Include uploaded file IDs in parameters
      const submitParams = {
        ...parameters,
        attached_file_ids: uploadedFiles.map(f => f.file_id),
      };
      onSubmit(submitParams);
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setIsUploading(true);
    setUploadError('');

    try {
      // Upload each file
      const uploadPromises = Array.from(files).map(file => queryAPI.uploadFile(file));
      const responses = await Promise.all(uploadPromises);

      // Add to uploaded files list
      const newFiles: UploadedFile[] = responses.map(res => ({
        file_id: res.file_id,
        filename: res.filename,
        file_type: res.file_type,
        file_size: res.file_size,
      }));

      setUploadedFiles(prev => [...prev, ...newFiles]);
    } catch (error: any) {
      setUploadError(error.response?.data?.detail || 'Failed to upload file(s)');
    } finally {
      setIsUploading(false);
      // Clear file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleRemoveFile = (fileId: string) => {
    setUploadedFiles(prev => prev.filter(f => f.file_id !== fileId));
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const handleChange = (field: keyof QueryParameters, value: any) => {
    setParameters((prev) => ({
      ...prev,
      [field]: value,
    }));

    // Clear error for this field
    if (errors[field]) {
      setErrors((prev) => {
        const newErrors = { ...prev };
        delete newErrors[field];
        return newErrors;
      });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="query-form">
      <div className="form-header">
        <h2>Submit Your Query</h2>
        <p>Enter your question and customize search parameters below</p>
      </div>

      {/* Query Input */}
      <div className="form-group">
        <label htmlFor="query">
          Query <span className="required">*</span>
        </label>
        <textarea
          id="query"
          value={parameters.query}
          onChange={(e) => handleChange('query', e.target.value)}
          placeholder="Enter your research question or topic..."
          rows={3}
          className={errors.query ? 'error' : ''}
          disabled={isLoading}
        />
        {errors.query && <span className="error-message">{errors.query}</span>}
        <span className="char-count">
          {parameters.query.length} / 500 characters
        </span>
      </div>

      {/* File Upload */}
      <div className="form-group file-upload-section">
        <label>
          Attach Files (Optional)
          <span className="file-hint"> - PDF, TXT, PNG, JPG/JPEG</span>
        </label>

        <div className="file-upload-area">
          <input
            ref={fileInputRef}
            type="file"
            id="file-upload"
            multiple
            accept=".pdf,.txt,.png,.jpg,.jpeg"
            onChange={handleFileSelect}
            disabled={isLoading || isUploading}
            style={{ display: 'none' }}
          />
          <button
            type="button"
            className="file-upload-button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading || isUploading}
          >
            {isUploading ? (
              <>
                <span className="spinner"></span>
                Uploading...
              </>
            ) : (
              <>
                📎 Choose Files
              </>
            )}
          </button>
        </div>

        {uploadError && (
          <div className="error-message">{uploadError}</div>
        )}

        {uploadedFiles.length > 0 && (
          <div className="uploaded-files-list">
            <h4>Attached Files ({uploadedFiles.length}):</h4>
            {uploadedFiles.map(file => (
              <div key={file.file_id} className="uploaded-file-item">
                <div className="file-info">
                  <span className="file-name">{file.filename}</span>
                  <span className="file-size">{formatFileSize(file.file_size)}</span>
                </div>
                <button
                  type="button"
                  className="remove-file-button"
                  onClick={() => handleRemoveFile(file.file_id)}
                  disabled={isLoading}
                  title="Remove file"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Basic Parameters */}
      <div className="form-row">
        <div className="form-group">
          <label htmlFor="web_search">
            <input
              type="checkbox"
              id="web_search"
              checked={parameters.web_search}
              onChange={(e) => handleChange('web_search', e.target.checked)}
              disabled={isLoading}
            />
            Enable Web Search
          </label>
        </div>

        <div className="form-group">
          <label htmlFor="include_wikipedia">
            <input
              type="checkbox"
              id="include_wikipedia"
              checked={parameters.include_wikipedia}
              onChange={(e) => handleChange('include_wikipedia', e.target.checked)}
              disabled={isLoading}
            />
            Include Wikipedia
          </label>
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label htmlFor="top_k">
            Number of Documents
          </label>
          <input
            type="number"
            id="top_k"
            value={parameters.top_k}
            onChange={(e) => handleChange('top_k', parseInt(e.target.value))}
            min={1}
            max={20}
            className={errors.top_k ? 'error' : ''}
            disabled={isLoading}
          />
          {errors.top_k && <span className="error-message">{errors.top_k}</span>}
        </div>

        <div className="form-group">
          <label htmlFor="max_depth">
            Search Depth
          </label>
          <input
            type="number"
            id="max_depth"
            value={parameters.max_depth}
            onChange={(e) => handleChange('max_depth', parseInt(e.target.value))}
            min={1}
            max={3}
            className={errors.max_depth ? 'error' : ''}
            disabled={isLoading}
          />
          {errors.max_depth && <span className="error-message">{errors.max_depth}</span>}
        </div>
      </div>

      {/* Advanced Parameters Toggle */}
      <button
        type="button"
        className="toggle-advanced"
        onClick={() => setShowAdvanced(!showAdvanced)}
        disabled={isLoading}
      >
        {showAdvanced ? '▼' : '▶'} Advanced Parameters
      </button>

      {showAdvanced && (
        <div className="advanced-params">
          <div className="form-group">
            <label htmlFor="retrieval_model">Retrieval Model</label>
            <select
              id="retrieval_model"
              value={parameters.retrieval_model}
              onChange={(e) => handleChange('retrieval_model', e.target.value as RetrievalModel)}
              disabled={isLoading}
            >
              <option value={RetrievalModel.SIGLIP}>SigLIP (Recommended)</option>
              <option value={RetrievalModel.CLIP}>CLIP</option>
              <option value={RetrievalModel.COLPALI}>ColPali</option>
              <option value={RetrievalModel.ALL_MINILM}>all-MiniLM (Fast)</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="llm_provider">LLM Provider</label>
            <select
              id="llm_provider"
              value={parameters.llm_provider}
              onChange={(e) => handleChange('llm_provider', e.target.value as LLMProvider)}
              disabled={isLoading}
            >
              <option value={LLMProvider.OLLAMA}>Ollama</option>
              <option value={LLMProvider.OPENAI}>OpenAI</option>
              <option value={LLMProvider.ANTHROPIC}>Anthropic</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="rag_model">RAG Model</label>
            <input
              type="text"
              id="rag_model"
              value={parameters.rag_model}
              onChange={(e) => handleChange('rag_model', e.target.value)}
              placeholder="gemma"
              disabled={isLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="personality">Personality (Optional)</label>
            <input
              type="text"
              id="personality"
              value={parameters.personality}
              onChange={(e) => handleChange('personality', e.target.value)}
              placeholder="e.g., scientific, cheerful"
              disabled={isLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="corpus_dir">Local Corpus Directory (Optional)</label>
            <input
              type="text"
              id="corpus_dir"
              value={parameters.corpus_dir}
              onChange={(e) => handleChange('corpus_dir', e.target.value)}
              placeholder="/path/to/local/documents"
              disabled={isLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="web_concurrency">Web Concurrency</label>
            <input
              type="number"
              id="web_concurrency"
              value={parameters.web_concurrency}
              onChange={(e) => handleChange('web_concurrency', parseInt(e.target.value))}
              min={1}
              max={20}
              disabled={isLoading}
            />
          </div>
        </div>
      )}

      {/* Submit Button */}
      <button
        type="submit"
        className="submit-button"
        disabled={isLoading}
      >
        {isLoading ? (
          <>
            <span className="spinner"></span>
            Processing...
          </>
        ) : (
          'Submit Query'
        )}
      </button>
    </form>
  );
};

export default QueryForm;
