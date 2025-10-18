# backend/services/history_service.py

import os
import json
import glob
import shutil
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from backend.api.models import QueryResult, QueryParameters, WebResult, LocalResult


class HistoryService:
    """
    Service for managing query history using the existing results/ folder.

    Reuses the results/{query_id}/ structure created by SearchSession:
    - results/{query_id}/toc_analysis.json - Full query data
    - results/{query_id}/final_report.md - Final report
    - results/{query_id}/{query_id}_output.md - Output file
    - exports/{filename}.md - Exported markdown (linked)

    Maintains a lightweight index and auto-cleanup (max 10 queries).
    """

    def __init__(
        self,
        results_dir: str = "results",
        exports_dir: str = "exports",
        max_queries: int = 10
    ):
        self.results_dir = results_dir
        self.exports_dir = exports_dir
        self.max_queries = max_queries

        # Create directories
        os.makedirs(results_dir, exist_ok=True)
        os.makedirs(exports_dir, exist_ok=True)

        # Index file stores lightweight metadata for quick access
        self.index_file = os.path.join(results_dir, "_history_index.json")
        self._ensure_index()

    def _ensure_index(self):
        """Ensure index file exists"""
        if not os.path.exists(self.index_file):
            self._save_index([])

    def _load_index(self) -> List[Dict[str, Any]]:
        """Load query index from file"""
        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_index(self, index: List[Dict[str, Any]]):
        """Save query index to file"""
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def add_query(self, result: QueryResult, export_filename: Optional[str] = None):
        """
        Add a query to history and perform cleanup if needed

        Args:
            result: Query result to add
            export_filename: Optional filename of exported markdown file
        """
        # Load index
        index = self._load_index()

        # Check if query already exists in index
        existing_index = next((i for i, q in enumerate(index) if q['query_id'] == result.query_id), None)

        # Create metadata entry
        metadata = {
            'query_id': result.query_id,
            'query_text': result.query_text,
            'status': result.status.value if hasattr(result.status, 'value') else result.status,
            'created_at': result.created_at,
            'completed_at': result.completed_at,
            'processing_time_ms': result.processing_time_ms,
            'export_file': export_filename,
            'results_dir': os.path.join(self.results_dir, result.query_id)
        }

        if existing_index is not None:
            # Update existing entry
            index[existing_index] = metadata
        else:
            # Add new entry (newest first)
            index.insert(0, metadata)

        # Perform cleanup if exceeding max_queries
        if len(index) > self.max_queries:
            # Remove oldest queries
            to_remove = index[self.max_queries:]
            index = index[:self.max_queries]

            for old_query in to_remove:
                self._delete_query_files(old_query)

        # Save updated index
        self._save_index(index)

    def _delete_query_files(self, metadata: Dict[str, Any]):
        """Delete all files associated with a query"""
        query_id = metadata['query_id']

        # Delete results directory (contains toc_analysis.json, reports, etc.)
        results_dir = os.path.join(self.results_dir, query_id)
        if os.path.exists(results_dir):
            try:
                shutil.rmtree(results_dir)
                print(f"[History] Deleted results directory: {results_dir}")
            except Exception as e:
                print(f"[History] Error deleting {results_dir}: {e}")

        # Delete export file if exists
        if metadata.get('export_file'):
            export_file = os.path.join(self.exports_dir, metadata['export_file'])
            if os.path.exists(export_file):
                try:
                    os.remove(export_file)
                    print(f"[History] Deleted export: {export_file}")
                except Exception as e:
                    print(f"[History] Error deleting {export_file}: {e}")

    def delete_query(self, query_id: str) -> bool:
        """
        Manually delete a query from history

        Args:
            query_id: ID of query to delete

        Returns:
            True if deleted, False if not found
        """
        index = self._load_index()

        # Find query in index
        query_metadata = None
        new_index = []

        for entry in index:
            if entry['query_id'] == query_id:
                query_metadata = entry
            else:
                new_index.append(entry)

        if query_metadata:
            self._delete_query_files(query_metadata)
            self._save_index(new_index)
            return True

        return False

    def get_query(self, query_id: str) -> Optional[QueryResult]:
        """
        Get full query result from history by loading from results folder

        Args:
            query_id: ID of query to retrieve

        Returns:
            QueryResult if found, None otherwise
        """
        results_dir = os.path.join(self.results_dir, query_id)
        toc_file = os.path.join(results_dir, "toc_analysis.json")

        if not os.path.exists(toc_file):
            return None

        try:
            # Load TOC analysis
            with open(toc_file, 'r', encoding='utf-8') as f:
                toc_data = json.load(f)

            # Load final report
            final_report_path = os.path.join(results_dir, "final_report.md")
            final_answer = ""
            if os.path.exists(final_report_path):
                with open(final_report_path, 'r', encoding='utf-8') as f:
                    final_answer = f.read()

            # Get metadata from index
            index = self._load_index()
            metadata = next((q for q in index if q['query_id'] == query_id), None)

            # Get basic info from TOC
            toc_tree = toc_data.get('toc_tree', [])
            root_node = toc_tree[0] if toc_tree else {}

            if not metadata:
                metadata = {
                    'query_id': query_id,
                    'query_text': root_node.get('query_text', ''),
                    'status': 'completed',
                    'created_at': root_node.get('timestamps', {}).get('created', ''),
                    'completed_at': root_node.get('timestamps', {}).get('completed', ''),
                    'processing_time_ms': root_node.get('metrics', {}).get('processing_time_ms', 0)
                }

            # Load web results from web_* directories
            web_results = []
            web_dirs = glob.glob(os.path.join(results_dir, "web_*"))

            for web_dir in web_dirs:
                if not os.path.isdir(web_dir):
                    continue

                # Find all .json files (not .html files)
                json_files = glob.glob(os.path.join(web_dir, "*.json"))

                for json_file in json_files:
                    # Skip .html.json files - we want the metadata files
                    if not json_file.endswith('.html.json'):
                        continue

                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            web_data = json.load(f)

                        # Extract relevant fields
                        title = web_data.get('title', 'No title')
                        url = web_data.get('url', '')
                        snippet = web_data.get('text_preview', '')[:200]

                        if url:  # Only add if we have a URL
                            web_results.append(WebResult(
                                title=title,
                                url=url,
                                snippet=snippet,
                                relevance=None
                            ))
                    except Exception as e:
                        print(f"[History] Error loading web result {json_file}: {e}")
                        continue

            # Create parameters object
            params = QueryParameters(
                query=metadata.get('query_text', ''),
                web_search=True,
                retrieval_model='siglip',
                top_k=3,
                max_depth=1,
                web_concurrency=3,
                include_wikipedia=False,
                personality='Researcher',
                rag_model='gpt-4',
                llm_provider='ollama',
                llm_model='gemma2:2b'
            )

            # Build and return QueryResult
            return QueryResult(
                query_id=query_id,
                status=metadata.get('status', 'completed'),
                query_text=metadata.get('query_text', ''),
                parameters=params,
                final_answer=final_answer,
                web_results=web_results,
                local_results=[],  # Local results not persisted to disk
                search_tree=root_node if root_node else None,
                created_at=metadata.get('created_at'),
                completed_at=metadata.get('completed_at'),
                processing_time_ms=metadata.get('processing_time_ms')
            )

        except Exception as e:
            print(f"[History] Error loading query {query_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def list_queries(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List all queries in history (newest first)

        Args:
            limit: Optional limit on number of results

        Returns:
            List of query metadata dictionaries
        """
        index = self._load_index()

        if limit:
            return index[:limit]

        return index

    def clear_all(self):
        """Clear all history (use with caution!)"""
        index = self._load_index()

        for entry in index:
            self._delete_query_files(entry)

        self._save_index([])

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about query history"""
        index = self._load_index()

        total = len(index)
        completed = sum(1 for q in index if q.get('status') == 'completed')
        failed = sum(1 for q in index if q.get('status') == 'failed')

        total_time_ms = sum(q.get('processing_time_ms', 0) for q in index if q.get('processing_time_ms'))
        avg_time_ms = total_time_ms / completed if completed > 0 else 0

        return {
            'total_queries': total,
            'completed': completed,
            'failed': failed,
            'average_processing_time_ms': round(avg_time_ms, 2),
            'max_queries': self.max_queries,
            'storage_path': self.results_dir
        }

    def sync_from_results_folder(self):
        """
        Sync index with existing results/ folders

        Useful for rebuilding the index from existing query results.
        """
        if not os.path.exists(self.results_dir):
            return

        # Get all query_id directories
        query_dirs = [d for d in os.listdir(self.results_dir)
                     if os.path.isdir(os.path.join(self.results_dir, d))
                     and not d.startswith('_')]

        index = []

        for query_id in query_dirs:
            toc_file = os.path.join(self.results_dir, query_id, "toc_analysis.json")

            if not os.path.exists(toc_file):
                continue

            try:
                with open(toc_file, 'r', encoding='utf-8') as f:
                    toc_data = json.load(f)

                root_node = toc_data.get('toc_tree', [{}])[0]

                metadata = {
                    'query_id': query_id,
                    'query_text': root_node.get('query_text', 'Unknown Query'),
                    'status': 'completed',
                    'created_at': root_node.get('timestamps', {}).get('created', ''),
                    'completed_at': root_node.get('timestamps', {}).get('completed', ''),
                    'processing_time_ms': root_node.get('metrics', {}).get('processing_time_ms', 0),
                    'export_file': None,
                    'results_dir': os.path.join(self.results_dir, query_id)
                }

                index.append(metadata)

            except Exception as e:
                print(f"[History] Error reading {query_id}: {e}")

        # Sort by creation time (newest first)
        index.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        # Keep only max_queries
        if len(index) > self.max_queries:
            # Remove oldest
            to_remove = index[self.max_queries:]
            index = index[:self.max_queries]

            for old_query in to_remove:
                self._delete_query_files(old_query)

        self._save_index(index)
        print(f"[History] Synced {len(index)} queries from results folder")


# Global instance
history_service = HistoryService()
