# backend/api/models.py

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from enum import Enum
from fastapi import UploadFile


class RetrievalModel(str, Enum):
    COLPALI = "colpali"
    ALL_MINILM = "all-minilm"
    SIGLIP = "siglip"
    CLIP = "clip"


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class ExportFormat(str, Enum):
    MARKDOWN = "markdown"
    TEXT = "text"
    PDF = "pdf"


class QueryParameters(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="The search query text")
    web_search: bool = Field(default=True, description="Enable web search")
    retrieval_model: RetrievalModel = Field(default=RetrievalModel.SIGLIP, description="Retrieval model to use")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of documents to retrieve")
    max_depth: int = Field(default=1, ge=1, le=3, description="Maximum search depth")
    corpus_dir: Optional[str] = Field(default=None, description="Path to local corpus directory")
    attached_file_ids: Optional[List[str]] = Field(default=None, description="IDs of uploaded files to include in corpus")
    personality: Optional[str] = Field(default=None, description="LLM personality (e.g., 'scientific')")
    rag_model: str = Field(default="gemma", description="RAG model to use")
    llm_provider: LLMProvider = Field(default=LLMProvider.OLLAMA, description="LLM provider")
    llm_model: Optional[str] = Field(default=None, description="Specific LLM model")
    web_concurrency: int = Field(default=8, ge=1, le=20, description="Concurrent web downloads")
    include_wikipedia: bool = Field(default=False, description="Include Wikipedia in search")

    @validator('query')
    def validate_query(cls, v):
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()


class QuerySubmitRequest(BaseModel):
    parameters: QueryParameters


class QuerySubmitResponse(BaseModel):
    query_id: str
    status: str
    message: str


class QueryStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TOCNodeResponse(BaseModel):
    node_id: Optional[str]
    query_text: str
    depth: int
    summary: str
    relevance_score: float
    children: List['TOCNodeResponse'] = []
    metrics: Optional[Dict[str, Any]] = None


TOCNodeResponse.update_forward_refs()


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str
    relevance: Optional[float] = None


class LocalResult(BaseModel):
    source: str
    snippet: str
    relevance: Optional[float] = None


class QueryResult(BaseModel):
    query_id: str
    status: QueryStatus
    query_text: str
    parameters: QueryParameters
    final_answer: Optional[str] = None
    search_tree: Optional[TOCNodeResponse] = None
    web_results: List[WebResult] = []
    local_results: List[LocalResult] = []
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    processing_time_ms: Optional[int] = None


class ExportRequest(BaseModel):
    query_id: str
    format: ExportFormat


class ExportResponse(BaseModel):
    download_url: str
    filename: str
    format: ExportFormat


class ProgressUpdate(BaseModel):
    query_id: str
    status: QueryStatus
    message: str
    progress_percentage: Optional[int] = None
    current_step: Optional[str] = None
    total_steps: Optional[int] = None
    completed_steps: Optional[int] = None
    timestamp: str


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    status_code: int


class FileUploadResponse(BaseModel):
    file_id: str
    filename: str
    file_type: str
    file_size: int
    message: str
