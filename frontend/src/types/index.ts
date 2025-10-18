// frontend/src/types/index.ts

export enum RetrievalModel {
  COLPALI = 'colpali',
  ALL_MINILM = 'all-minilm',
  SIGLIP = 'siglip',
  CLIP = 'clip',
}

export enum LLMProvider {
  OLLAMA = 'ollama',
  OPENAI = 'openai',
  ANTHROPIC = 'anthropic',
}

export enum ExportFormat {
  MARKDOWN = 'markdown',
  TEXT = 'text',
  PDF = 'pdf',
}

export enum QueryStatus {
  PENDING = 'pending',
  PROCESSING = 'processing',
  COMPLETED = 'completed',
  FAILED = 'failed',
}

export interface QueryParameters {
  query: string;
  web_search: boolean;
  retrieval_model: RetrievalModel;
  top_k: number;
  max_depth: number;
  corpus_dir?: string;
  attached_file_ids?: string[];
  personality?: string;
  rag_model: string;
  llm_provider: LLMProvider;
  llm_model?: string;
  web_concurrency: number;
  include_wikipedia: boolean;
}

export interface TOCNode {
  node_id?: string;
  query_text: string;
  depth: number;
  summary: string;
  relevance_score: number;
  children: TOCNode[];
  metrics?: {
    web_results_count: number;
    corpus_entries_count: number;
    total_content_length: number;
    avg_similarity_score: number;
    max_similarity_score: number;
    min_similarity_score: number;
    monte_carlo_selected: boolean;
    monte_carlo_weight: number;
    processing_time_ms: number;
    subquery_expansion_count: number;
  };
}

export interface WebResult {
  title: string;
  url: string;
  snippet: string;
  relevance?: number;
}

export interface LocalResult {
  source: string;
  snippet: string;
  relevance?: number;
}

export interface QueryResult {
  query_id: string;
  status: QueryStatus;
  query_text: string;
  parameters: QueryParameters;
  final_answer?: string;
  search_tree?: TOCNode;
  web_results: WebResult[];
  local_results: LocalResult[];
  error_message?: string;
  created_at?: string;
  completed_at?: string;
  processing_time_ms?: number;
}

export interface ProgressUpdate {
  query_id: string;
  status: QueryStatus;
  message: string;
  progress_percentage?: number;
  current_step?: string;
  total_steps?: number;
  completed_steps?: number;
  timestamp: string;
}

export interface QuerySubmitResponse {
  query_id: string;
  status: string;
  message: string;
}

export interface ExportResponse {
  download_url: string;
  filename: string;
  format: ExportFormat;
}

export interface FileUploadResponse {
  file_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  message: string;
}

export interface UploadedFile {
  file_id: string;
  filename: string;
  file_type: string;
  file_size: number;
}
