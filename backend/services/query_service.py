# backend/services/query_service.py

import asyncio
import os
import sys
import yaml
from datetime import datetime
from typing import Dict, Any, Optional, Callable
import uuid

# Add parent directory to path to import NanoSage modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from search_session import SearchSession
from backend.api.models import QueryParameters, QueryResult, QueryStatus, TOCNodeResponse, WebResult, LocalResult
from backend.services.history_service import history_service
from backend.services.file_upload_service import file_upload_service
from backend.utils.log_streaming import setup_log_streaming, cleanup_log_streaming


class QueryService:
    """Service for managing query execution and results"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.active_queries: Dict[str, Dict[str, Any]] = {}
        self.completed_queries: Dict[str, QueryResult] = {}
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        if not os.path.isfile(self.config_path):
            return {}
        with open(self.config_path, "r") as f:
            return yaml.safe_load(f) or {}

    async def submit_query(
        self,
        parameters: QueryParameters,
        progress_callback: Optional[Callable] = None
    ) -> str:
        """
        Submit a new query for processing

        Args:
            parameters: Query parameters
            progress_callback: Optional callback for progress updates

        Returns:
            query_id: Unique identifier for the query
        """
        query_id = str(uuid.uuid4())

        # Store query info
        self.active_queries[query_id] = {
            'parameters': parameters,
            'status': QueryStatus.PENDING,
            'created_at': datetime.utcnow().isoformat(),
            'progress_callback': progress_callback,
            'log_handler': None  # Will be set when processing starts
        }

        # Start processing in background
        asyncio.create_task(self._process_query(query_id, parameters, progress_callback))

        return query_id

    async def _process_query(
        self,
        query_id: str,
        parameters: QueryParameters,
        progress_callback: Optional[Callable] = None
    ):
        """Process a query asynchronously"""
        start_time = datetime.utcnow()
        log_handler = None

        try:
            # Set up log streaming
            if progress_callback:
                # Get the CURRENT event loop (the one running this async function)
                import asyncio
                current_loop = asyncio.get_event_loop()
                log_handler = setup_log_streaming(query_id, progress_callback, current_loop)
                # Store handler reference so we can retrieve buffered logs later
                if query_id in self.active_queries:
                    self.active_queries[query_id]['log_handler'] = log_handler

            # Update status
            self.active_queries[query_id]['status'] = QueryStatus.PROCESSING

            if progress_callback:
                await progress_callback({
                    'query_id': query_id,
                    'status': QueryStatus.PROCESSING,
                    'message': 'Initializing search session...',
                    'progress_percentage': 10,
                    'timestamp': datetime.utcnow().isoformat()
                })

            # Prepare config
            config = self.config.copy()
            config.update({
                'web_concurrency': parameters.web_concurrency,
                'include_wikipedia': parameters.include_wikipedia
            })

            # Determine corpus directory
            corpus_dir = parameters.corpus_dir

            # If files are attached, use the upload directory
            if parameters.attached_file_ids and len(parameters.attached_file_ids) > 0:
                # Use upload directory as corpus directory
                corpus_dir = file_upload_service.get_upload_directory()

                # Optionally: Create a temporary directory with only the attached files
                # For now, we'll use the entire upload directory
                # In production, you might want to create a temp dir with only selected files

            # Create search session
            session = SearchSession(
                query=parameters.query,
                config=config,
                corpus_dir=corpus_dir,
                device="cpu",  # Default to CPU for web deployment
                retrieval_model=parameters.retrieval_model.value,
                top_k=parameters.top_k,
                web_search_enabled=parameters.web_search,
                personality=parameters.personality,
                rag_model=parameters.rag_model,
                max_depth=parameters.max_depth,
                llm_provider=parameters.llm_provider.value,
                llm_model=parameters.llm_model
            )

            if progress_callback:
                await progress_callback({
                    'query_id': query_id,
                    'status': QueryStatus.PROCESSING,
                    'message': 'Executing search and retrieval...',
                    'progress_percentage': 30,
                    'timestamp': datetime.utcnow().isoformat()
                })

            # Run the session
            final_answer = await session.run_session()

            if progress_callback:
                await progress_callback({
                    'query_id': query_id,
                    'status': QueryStatus.PROCESSING,
                    'message': 'Generating final report...',
                    'progress_percentage': 80,
                    'timestamp': datetime.utcnow().isoformat()
                })

            # Save report
            output_path = session.save_report(final_answer)

            # Build search tree from TOC
            search_tree = None
            toc_nodes = getattr(session, 'toc_tree', [])

            # Create a root node that contains all top-level nodes if there are multiple
            if toc_nodes:
                if len(toc_nodes) == 1:
                    # Single root node
                    search_tree = self._build_toc_response(toc_nodes[0])
                else:
                    # Multiple root nodes - create a synthetic root
                    # We'll just use the first one for search tree display
                    # but extract results from all nodes
                    search_tree = self._build_toc_response(toc_nodes[0])

            # Extract web and local results
            web_results = []
            local_results = []

            # Extract web results from all TOC nodes
            if toc_nodes:
                for node in toc_nodes:
                    web_results.extend(self._extract_web_results(node))

            # Extract local results from knowledge base
            if hasattr(session, 'kb') and session.kb:
                local_results = self._extract_local_results(session.kb)

            # Calculate processing time
            end_time = datetime.utcnow()
            processing_time_ms = int((end_time - start_time).total_seconds() * 1000)

            # Create result
            result = QueryResult(
                query_id=query_id,
                status=QueryStatus.COMPLETED,
                query_text=parameters.query,
                parameters=parameters,
                final_answer=final_answer,
                search_tree=search_tree,
                web_results=web_results,
                local_results=local_results,
                created_at=start_time.isoformat(),
                completed_at=end_time.isoformat(),
                processing_time_ms=processing_time_ms
            )

            # Store result
            self.completed_queries[query_id] = result
            del self.active_queries[query_id]

            # Automatically save to history when query completes
            history_service.add_query(result)

            if progress_callback:
                await progress_callback({
                    'query_id': query_id,
                    'status': QueryStatus.COMPLETED,
                    'message': 'Query completed successfully!',
                    'progress_percentage': 100,
                    'timestamp': datetime.utcnow().isoformat()
                })

        except Exception as e:
            # Handle error
            error_message = str(e)

            result = QueryResult(
                query_id=query_id,
                status=QueryStatus.FAILED,
                query_text=parameters.query,
                parameters=parameters,
                error_message=error_message,
                created_at=start_time.isoformat(),
                completed_at=datetime.utcnow().isoformat()
            )

            self.completed_queries[query_id] = result
            if query_id in self.active_queries:
                del self.active_queries[query_id]

            if progress_callback:
                await progress_callback({
                    'query_id': query_id,
                    'status': QueryStatus.FAILED,
                    'message': f'Query failed: {error_message}',
                    'progress_percentage': 0,
                    'timestamp': datetime.utcnow().isoformat()
                })

        finally:
            # Clean up log streaming
            if log_handler:
                cleanup_log_streaming(log_handler)

    def _build_toc_response(self, toc_node) -> TOCNodeResponse:
        """Convert TOCNode to TOCNodeResponse"""
        children = [self._build_toc_response(child) for child in toc_node.children]

        return TOCNodeResponse(
            node_id=getattr(toc_node, 'node_id', None),
            query_text=toc_node.query_text,
            depth=toc_node.depth,
            summary=toc_node.summary,
            relevance_score=toc_node.relevance_score,
            children=children,
            metrics=getattr(toc_node, 'metrics', None)
        )

    def _extract_web_results(self, toc_node, results=None) -> list:
        """Extract web results from TOC tree"""
        if results is None:
            results = []

        for web_result in toc_node.web_results:
            # Extract title, use URL domain as fallback if no title
            title = web_result.get('title', '')
            if not title or title.strip() == '':
                # Extract domain from URL as fallback
                url = web_result.get('url', '')
                if url:
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        title = parsed.netloc or 'No title'
                    except:
                        title = 'No title'
                else:
                    title = 'No title'

            results.append(WebResult(
                title=title,
                url=web_result.get('url', ''),
                snippet=web_result.get('snippet', '')[:200],
                relevance=web_result.get('relevance')
            ))

        for child in toc_node.children:
            self._extract_web_results(child, results)

        return results

    def _extract_local_results(self, knowledge_base) -> list:
        """Extract local results from knowledge base"""
        results = []

        if hasattr(knowledge_base, 'documents'):
            for doc in knowledge_base.documents[:10]:  # Limit to top 10
                results.append(LocalResult(
                    source=doc.get('source', 'Unknown'),
                    snippet=doc.get('text', '')[:200],
                    relevance=doc.get('score')
                ))

        return results

    def get_query_status(self, query_id: str) -> Optional[QueryResult]:
        """Get status of a query"""
        # Check completed queries first
        if query_id in self.completed_queries:
            return self.completed_queries[query_id]

        # Check active queries
        if query_id in self.active_queries:
            active = self.active_queries[query_id]
            return QueryResult(
                query_id=query_id,
                status=active['status'],
                query_text=active['parameters'].query,
                parameters=active['parameters'],
                created_at=active['created_at']
            )

        return None

    def list_queries(self, limit: int = 50) -> list:
        """List all queries (active and completed)"""
        all_queries = []

        # Add completed queries
        for query_id, result in list(self.completed_queries.items())[-limit:]:
            all_queries.append(result)

        # Add active queries
        for query_id, active in self.active_queries.items():
            all_queries.append(QueryResult(
                query_id=query_id,
                status=active['status'],
                query_text=active['parameters'].query,
                parameters=active['parameters'],
                created_at=active['created_at']
            ))

        return sorted(all_queries, key=lambda x: x.created_at or '', reverse=True)

    def get_buffered_logs(self, query_id: str) -> list:
        """Get buffered logs for a query"""
        if query_id in self.active_queries:
            log_handler_tuple = self.active_queries[query_id].get('log_handler')
            if log_handler_tuple and isinstance(log_handler_tuple, tuple) and len(log_handler_tuple) >= 2:
                # log_handler_tuple is (LogStreamHandler, PrintCapture, original_stdout)
                # PrintCapture has the actual logs from print() statements
                print_capture = log_handler_tuple[1]
                if hasattr(print_capture, 'get_logs'):
                    return print_capture.get_logs()
        return []


# Global instance
query_service = QueryService()
