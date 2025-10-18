// frontend/src/services/api.ts

import axios from 'axios';
import {
  QueryParameters,
  QueryResult,
  QuerySubmitResponse,
  ExportFormat,
  ExportResponse,
  ProgressUpdate,
  FileUploadResponse,
} from '../types';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const WS_BASE_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const queryAPI = {
  /**
   * Submit a new query
   */
  submitQuery: async (parameters: QueryParameters): Promise<QuerySubmitResponse> => {
    const response = await api.post<QuerySubmitResponse>('/api/query/submit', {
      parameters,
    });
    return response.data;
  },

  /**
   * Get query status and results
   */
  getQuery: async (queryId: string): Promise<QueryResult> => {
    const response = await api.get<QueryResult>(`/api/query/${queryId}`);
    return response.data;
  },

  /**
   * List all queries
   */
  listQueries: async (limit: number = 50): Promise<QueryResult[]> => {
    const response = await api.get<QueryResult[]>('/api/queries', {
      params: { limit },
    });
    return response.data;
  },

  /**
   * Export query results
   */
  exportQuery: async (queryId: string, format: ExportFormat): Promise<ExportResponse> => {
    const response = await api.post<ExportResponse>('/api/query/export', {
      query_id: queryId,
      format,
    });
    return response.data;
  },

  /**
   * Create WebSocket connection for real-time updates
   */
  connectWebSocket: (
    queryId: string,
    onMessage: (update: ProgressUpdate) => void,
    onError?: (error: Event) => void,
    onClose?: (event: CloseEvent) => void
  ): WebSocket => {
    const ws = new WebSocket(`${WS_BASE_URL}/ws/${queryId}`);

    ws.onopen = () => {
      console.log(`WebSocket connected for query: ${queryId}`);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      if (onError) onError(error);
    };

    ws.onclose = (event) => {
      console.log('WebSocket closed:', event);
      if (onClose) onClose(event);
    };

    return ws;
  },

  /**
   * Health check
   */
  healthCheck: async (): Promise<{ status: string; timestamp: string }> => {
    const response = await api.get('/health');
    return response.data;
  },

  /**
   * Upload a file
   */
  uploadFile: async (file: File): Promise<FileUploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await api.post<FileUploadResponse>('/api/files/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },
};

export default api;
