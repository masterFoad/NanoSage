# search_session.py

import os
import uuid
import asyncio
import time
import re
import random
import yaml
import torch
from datetime import datetime

from knowledge_base import KnowledgeBase, late_interaction_score, load_corpus_from_dir, load_retrieval_model, embed_text
from web_crawler import search_and_download, parse_any_to_text, sanitize_filename
import json
from aggregator import aggregate_results

#############################################
# LLM Interface - Modular provider system
#############################################

from llm_interface import LLMManager, create_llm_manager

def clean_search_query(query):
    query = re.sub(r'[\*\_`]', '', query)
    query = re.sub(r'\s+', ' ', query)
    return query.strip()

def split_query(query, max_len=200):
    query = query.replace('"', '').replace("'", "")
    sentences = query.split('.')
    subqueries = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if not any(c.isalnum() for c in sentence):
            continue
        if len(current) + len(sentence) + 1 <= max_len:
            current += (". " if current else "") + sentence
        else:
            subqueries.append(current)
            current = sentence
    if current:
        subqueries.append(current)
    return [sq for sq in subqueries if sq.strip()]

##############################################
# TOC Node: Represents a branch in the search tree
##############################################

class TOCNode:
    def __init__(self, query_text, depth=1):
        self.query_text = query_text      # The subquery text for this branch
        self.depth = depth                # Depth level in the tree
        self.summary = ""                 # Summary of findings for this branch
        self.web_results = []             # Web search results for this branch
        self.corpus_entries = []          # Corpus entries generated from this branch
        self.children = []                # Child TOCNode objects for further subqueries
        self.relevance_score = 0.0        # Relevance score relative to the overall query
        
        # Enhanced metrics for debugging and analysis
        self.timestamps = {
            'created': None,
            'web_search_start': None,
            'web_search_end': None,
            'summary_generated': None,
            'completed': None
        }
        self.metrics = {
            'web_results_count': 0,
            'corpus_entries_count': 0,
            'total_content_length': 0,
            'avg_similarity_score': 0.0,
            'max_similarity_score': 0.0,
            'min_similarity_score': 0.0,
            'monte_carlo_selected': False,
            'monte_carlo_weight': 0.0,
            'processing_time_ms': 0,
            'subquery_expansion_count': 0
        }
        self.similarity_scores = []       # Individual similarity scores for debugging
        self.parent_query = None          # Reference to parent query for context
        self.node_id = None               # Unique identifier for this node

    def add_child(self, child_node):
        self.children.append(child_node)
        child_node.parent_query = self.query_text

    def to_dict(self):
        """Convert TOCNode to dictionary for JSON serialization"""
        return {
            'node_id': self.node_id,
            'query_text': self.query_text,
            'depth': self.depth,
            'summary': self.summary,
            'relevance_score': self.relevance_score,
            'timestamps': self.timestamps,
            'metrics': self.metrics,
            'similarity_scores': self.similarity_scores,
            'parent_query': self.parent_query,
            'web_results_count': len(self.web_results),
            'corpus_entries_count': len(self.corpus_entries),
            'children_count': len(self.children),
            'children': [child.to_dict() for child in self.children] if self.children else []
        }

    def update_metrics(self, **kwargs):
        """Update metrics with new values"""
        for key, value in kwargs.items():
            if key in self.metrics:
                self.metrics[key] = value

    def add_similarity_score(self, score):
        """Add a similarity score and update statistics"""
        self.similarity_scores.append(score)
        if self.similarity_scores:
            self.metrics['avg_similarity_score'] = sum(self.similarity_scores) / len(self.similarity_scores)
            self.metrics['max_similarity_score'] = max(self.similarity_scores)
            self.metrics['min_similarity_score'] = min(self.similarity_scores)

    def __repr__(self):
        return f"TOCNode(query_text='{self.query_text}', depth={self.depth}, relevance_score={self.relevance_score:.2f}, children={len(self.children)}, metrics={self.metrics})"

def build_toc_string(toc_nodes, indent=0):
    """
    Recursively build a string representation of the TOC tree.
    """
    toc_str = ""
    for node in toc_nodes:
        prefix = "  " * indent + "- "
        summary_snippet = (node.summary[:150] + "...") if node.summary else "No summary"
        toc_str += f"{prefix}{node.query_text} (Relevance: {node.relevance_score:.2f}, Summary: {summary_snippet})\n"
        if node.children:
            toc_str += build_toc_string(node.children, indent=indent+1)
    return toc_str

def analyze_toc_tree(toc_nodes):
    """
    Analyze the TOC tree and return comprehensive statistics and metrics.
    """
    if not toc_nodes:
        return {}
    
    def collect_all_nodes(nodes, all_nodes=None):
        if all_nodes is None:
            all_nodes = []
        for node in nodes:
            all_nodes.append(node)
            if node.children:
                collect_all_nodes(node.children, all_nodes)
        return all_nodes
    
    all_nodes = collect_all_nodes(toc_nodes)
    
    # Calculate tree statistics
    total_nodes = len(all_nodes)
    max_depth = max(node.depth for node in all_nodes) if all_nodes else 0
    avg_depth = sum(node.depth for node in all_nodes) / total_nodes if total_nodes else 0
    
    # Calculate relevance statistics
    relevance_scores = [node.relevance_score for node in all_nodes]
    avg_relevance = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0
    max_relevance = max(relevance_scores) if relevance_scores else 0
    min_relevance = min(relevance_scores) if relevance_scores else 0
    
    # Calculate Monte Carlo statistics
    monte_carlo_selected = sum(1 for node in all_nodes if node.metrics.get('monte_carlo_selected', False))
    monte_carlo_percentage = (monte_carlo_selected / total_nodes * 100) if total_nodes else 0
    
    # Calculate content statistics
    total_web_results = sum(node.metrics.get('web_results_count', 0) for node in all_nodes)
    total_corpus_entries = sum(node.metrics.get('corpus_entries_count', 0) for node in all_nodes)
    total_content_length = sum(node.metrics.get('total_content_length', 0) for node in all_nodes)
    
    # Calculate timing statistics
    processing_times = [node.metrics.get('processing_time_ms', 0) for node in all_nodes]
    total_processing_time = sum(processing_times)
    avg_processing_time = total_processing_time / total_nodes if total_nodes else 0
    
    # Calculate similarity statistics
    all_similarity_scores = []
    for node in all_nodes:
        all_similarity_scores.extend(node.similarity_scores)
    
    similarity_stats = {}
    if all_similarity_scores:
        similarity_stats = {
            'avg_similarity': sum(all_similarity_scores) / len(all_similarity_scores),
            'max_similarity': max(all_similarity_scores),
            'min_similarity': min(all_similarity_scores),
            'total_similarity_measurements': len(all_similarity_scores)
        }
    
    # Calculate branching factor
    nodes_with_children = [node for node in all_nodes if node.children]
    avg_branching_factor = sum(len(node.children) for node in nodes_with_children) / len(nodes_with_children) if nodes_with_children else 0
    
    return {
        'tree_structure': {
            'total_nodes': total_nodes,
            'max_depth': max_depth,
            'avg_depth': round(avg_depth, 2),
            'nodes_with_children': len(nodes_with_children),
            'avg_branching_factor': round(avg_branching_factor, 2)
        },
        'relevance_metrics': {
            'avg_relevance': round(avg_relevance, 3),
            'max_relevance': round(max_relevance, 3),
            'min_relevance': round(min_relevance, 3),
            'relevance_std': round((sum((x - avg_relevance) ** 2 for x in relevance_scores) / len(relevance_scores)) ** 0.5, 3) if relevance_scores else 0
        },
        'monte_carlo_metrics': {
            'selected_nodes': monte_carlo_selected,
            'selection_percentage': round(monte_carlo_percentage, 2),
            'total_candidates': total_nodes
        },
        'content_metrics': {
            'total_web_results': total_web_results,
            'total_corpus_entries': total_corpus_entries,
            'total_content_length': total_content_length,
            'avg_web_results_per_node': round(total_web_results / total_nodes, 2) if total_nodes else 0
        },
        'timing_metrics': {
            'total_processing_time_ms': total_processing_time,
            'avg_processing_time_ms': round(avg_processing_time, 2),
            'max_processing_time_ms': max(processing_times) if processing_times else 0,
            'min_processing_time_ms': min(processing_times) if processing_times else 0
        },
        'similarity_metrics': similarity_stats,
        'generated_at': datetime.now().isoformat()
    }

def save_toc_to_json(toc_nodes, output_path, include_analytics=True):
    """
    Save the TOC tree to a JSON file with optional analytics.
    """
    toc_data = {
        'toc_tree': [node.to_dict() for node in toc_nodes] if toc_nodes else [],
        'metadata': {
            'total_nodes': len([node for node in toc_nodes]) if toc_nodes else 0,
            'exported_at': datetime.now().isoformat(),
            'version': '1.0'
        }
    }
    
    if include_analytics:
        toc_data['analytics'] = analyze_toc_tree(toc_nodes)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(toc_data, f, indent=2, ensure_ascii=False)
    
    return output_path

#########################################################
# The "SearchSession" class: orchestrate the entire pipeline,
# including optional Monte Carlo subquery sampling, recursive web search,
# TOC tracking, and relevance scoring.
#########################################################

class SearchSession:
    def __init__(self, query, config, corpus_dir=None, device="cpu",
                 retrieval_model="colpali", top_k=3, web_search_enabled=False,
                 personality=None, rag_model="gemma", max_depth=1, llm_provider="ollama", llm_model=None):
        """
        :param max_depth: Maximum recursion depth for subquery expansion.
        :param llm_provider: LLM provider to use ("ollama", "openai", "anthropic")
        :param llm_model: Specific model to use (overrides default for provider)
        """
        self.query = query
        self.config = config
        self.corpus_dir = corpus_dir
        self.device = device
        self.retrieval_model = retrieval_model
        self.top_k = top_k
        self.web_search_enabled = web_search_enabled
        self.personality = personality
        self.rag_model = rag_model
        self.max_depth = max_depth
        
        # Initialize LLM manager
        llm_config = {
            "provider": llm_provider,
            "model": llm_model or self._get_default_model(llm_provider, rag_model),
            "personality": personality
        }
        self.llm_manager = create_llm_manager(**llm_config)

        self.query_id = str(uuid.uuid4())[:8]
        self.base_result_dir = os.path.join(self.config.get("results_base_dir", "results"), self.query_id)
        os.makedirs(self.base_result_dir, exist_ok=True)

        print(f"[INFO] Initializing SearchSession for query_id={self.query_id}")

        self.loop = None
        self.enhanced_query = self.llm_manager.enhance_query(self.query)
        if not self.enhanced_query:
            self.enhanced_query = self.query

        # Load retrieval model.
        self.model, self.processor, self.model_type = load_retrieval_model(
            model_choice=self.retrieval_model,
            device=self.device
        )

        self.text_model = None
        if self.model_type in ["siglip", "clip"]:
            from sentence_transformers import SentenceTransformer
            self.text_model = SentenceTransformer("all-MiniLM-L6-v2", device=self.device)

        # Compute the overall enhanced query embedding once.
        print("[INFO] Computing embedding for enhanced query...")
        if self.model_type in ["siglip", "clip"] and self.text_model:
            # Use text model for query embedding to match web content embeddings
            self.enhanced_query_embedding = self.text_model.encode(self.enhanced_query, convert_to_tensor=True)
        else:
            self.enhanced_query_embedding = embed_text(self.enhanced_query, self.model, self.processor, self.model_type, self.device)

        print("[INFO] Creating KnowledgeBase...")
        self.kb = KnowledgeBase(self.model, self.processor, model_type=self.model_type, device=self.device, text_model=self.text_model)

        self.corpus = []
        if self.corpus_dir:
            print(f"[INFO] Loading local documents from {self.corpus_dir}")
            local_docs = load_corpus_from_dir(
                self.corpus_dir,
                self.model,
                self.processor,
                self.device,
                self.model_type,
                text_model=self.text_model
            )
            self.corpus.extend(local_docs)
        self.kb.add_documents(self.corpus)

        self.web_results = []
        self.grouped_web_results = {}
        self.local_results = []
        self.toc_tree = []
        self.session_start_time = time.time()

    def _get_default_model(self, provider, rag_model):
        """Get default model for the specified provider."""
        if provider == "ollama":
            return "gemma2:2b" if rag_model == "gemma" else "gemma2:2b"
        elif provider == "openai":
            return "gpt-3.5-turbo"
        elif provider == "anthropic":
            return "claude-3-sonnet-20240229"
        else:
            return "gemma2:2b"

    async def run_session(self):
        """Main entry point: perform recursive web search (if enabled) and then local retrieval"""
        self.loop = asyncio.get_running_loop()

        print(f"[INFO] Starting session with query_id={self.query_id}, max_depth={self.max_depth}")
        plain_enhanced_query = clean_search_query(self.enhanced_query)

        initial_subqueries = split_query(plain_enhanced_query, max_len=self.config.get("max_query_length", 200))
        print(f"[INFO] Generated {len(initial_subqueries)} initial subqueries from the enhanced query.")

        if self.config.get("monte_carlo_search", True):
            print("[INFO] Using Monte Carlo approach to sample subqueries.")
            initial_subqueries = self.perform_monte_carlo_subqueries(plain_enhanced_query, initial_subqueries)

        if self.web_search_enabled and self.max_depth >= 1:
            web_results, web_entries, grouped, toc_nodes = await self.perform_recursive_web_searches(initial_subqueries, current_depth=1)
            self.web_results = web_results
            self.grouped_web_results = grouped
            self.toc_tree = toc_nodes
            self.corpus.extend(web_entries)
            self.kb.add_documents(web_entries)
        else:
            print("[INFO] Web search is disabled or max_depth < 1, skipping web expansion.")

        print(f"[INFO] Retrieving top {self.top_k} local documents for final answer.")
        self.local_results = self.kb.search(self.enhanced_query, top_k=self.top_k)

        summarized_web = await self.loop.run_in_executor(
            None,
            self._summarize_web_results,
            self.web_results
        )
        summarized_local = await self.loop.run_in_executor(
            None,
            self._summarize_local_results,
            self.local_results
        )

        final_answer = await self.loop.run_in_executor(
            None,
            self._build_final_answer,
            summarized_web,
            summarized_local
        )
        print("[INFO] Finished building final advanced report.")

        return final_answer

    def perform_monte_carlo_subqueries(self, parent_query, subqueries):
        """
        Simple Monte Carlo approach:
         1) Embed each subquery and compute a relevance score.
         2) Weighted random selection of a subset (k=3) based on relevance scores.
        """
        max_subqs = self.config.get("monte_carlo_samples", 3)
        print(f"[DEBUG] Monte Carlo: randomly picking up to {max_subqs} subqueries from {len(subqueries)} total.")
        scored_subqs = []
        monte_carlo_metrics = {
            'total_candidates': len(subqueries),
            'candidate_scores': [],
            'selection_weights': [],
            'selected_queries': []
        }
        
        for sq in subqueries:
            sq_clean = clean_search_query(sq)
            if not sq_clean:
                continue
            if self.model_type in ["siglip", "clip"] and self.text_model:
                node_emb = self.text_model.encode(sq_clean, convert_to_tensor=True)
            else:
                node_emb = embed_text(sq_clean, self.model, self.processor, self.model_type, self.device)
            score = late_interaction_score(self.enhanced_query_embedding, node_emb)
            scored_subqs.append((sq_clean, score))
            monte_carlo_metrics['candidate_scores'].append(score)

        if not scored_subqs:
            print("[WARN] No valid subqueries found for Monte Carlo. Returning original list.")
            return subqueries

        # Weighted random choice
        weights = [s for (_, s) in scored_subqs]
        monte_carlo_metrics['selection_weights'] = weights
        chosen = random.choices(
            population=scored_subqs,
            weights=weights,
            k=min(max_subqs, len(scored_subqs))
        )
        # Return just the chosen subqueries
        chosen_sqs = [ch[0] for ch in chosen]
        monte_carlo_metrics['selected_queries'] = chosen_sqs
        monte_carlo_metrics['avg_candidate_score'] = sum(monte_carlo_metrics['candidate_scores']) / len(monte_carlo_metrics['candidate_scores'])
        monte_carlo_metrics['avg_selected_score'] = sum(score for _, score in chosen) / len(chosen)
        
        # Store Monte Carlo metrics for later use
        self.monte_carlo_metrics = monte_carlo_metrics
        
        print(f"[DEBUG] Monte Carlo selected: {chosen_sqs}")
        print(f"[DEBUG] Monte Carlo metrics: avg_candidate_score={monte_carlo_metrics['avg_candidate_score']:.3f}, avg_selected_score={monte_carlo_metrics['avg_selected_score']:.3f}")
        return chosen_sqs

    async def perform_recursive_web_searches(self, subqueries, current_depth=1, parent_query=None):
        """
        Recursively perform web searches for each subquery up to self.max_depth.
        Returns:
          aggregated_web_results, aggregated_corpus_entries, grouped_results, toc_nodes
        """
        aggregated_web_results = []
        aggregated_corpus_entries = []
        toc_nodes = []
        min_relevance = self.config.get("min_relevance", 0.5)

        for sq in subqueries:
            sq_clean = clean_search_query(sq)
            if not sq_clean:
                continue

            # Create a TOC node with enhanced tracking
            toc_node = TOCNode(query_text=sq_clean, depth=current_depth)
            toc_node.node_id = str(uuid.uuid4())[:8]
            toc_node.timestamps['created'] = datetime.now().isoformat()
            toc_node.parent_query = parent_query if parent_query else self.query
            
            # Relevance calculation with similarity tracking
            if self.model_type in ["siglip", "clip"] and self.text_model:
                node_embedding = self.text_model.encode(sq_clean, convert_to_tensor=True)
            else:
                node_embedding = embed_text(sq_clean, self.model, self.processor, self.model_type, self.device)
            relevance = late_interaction_score(self.enhanced_query_embedding, node_embedding)
            toc_node.relevance_score = relevance
            toc_node.add_similarity_score(relevance)
            
            # Check if this node was selected by Monte Carlo
            if hasattr(self, 'monte_carlo_metrics') and sq_clean in self.monte_carlo_metrics.get('selected_queries', []):
                toc_node.metrics['monte_carlo_selected'] = True
                # Find the weight for this query
                for i, (query, score) in enumerate(zip(self.monte_carlo_metrics.get('selected_queries', []), 
                                                      self.monte_carlo_metrics.get('selection_weights', []))):
                    if query == sq_clean:
                        toc_node.metrics['monte_carlo_weight'] = score
                        break

            if relevance < min_relevance:
                print(f"[INFO] Skipping branch '{sq_clean}' due to low relevance ({relevance:.2f} < {min_relevance}).")
                continue

            # Create subdirectory
            safe_subquery = sanitize_filename(sq_clean)[:30]
            subquery_dir = os.path.join(self.base_result_dir, f"web_{safe_subquery}")
            os.makedirs(subquery_dir, exist_ok=True)
            print(f"[DEBUG] Searching web for subquery '{sq_clean}' at depth={current_depth}...")

            # Track web search timing
            toc_node.timestamps['web_search_start'] = datetime.now().isoformat()
            web_search_start = time.time()
            
            pages = await search_and_download(
                keyword=sq_clean, 
                out_dir=subquery_dir,
                top_n=self.config.get("web_search_limit", 5),
                concurrency=self.config.get("web_concurrency", 8),
                include_wikipedia=self.config.get("include_wikipedia", False)
            )
            
            web_search_end = time.time()
            toc_node.timestamps['web_search_end'] = datetime.now().isoformat()
            toc_node.metrics['processing_time_ms'] += int((web_search_end - web_search_start) * 1000)
            branch_web_results = []
            branch_corpus_entries = []
            for page in pages:
                if not page:
                    continue
                file_path = page.get("file_path")
                url = page.get("url")
                meta = page.get("meta", {})
                if not file_path or not url:
                    continue
                
                # Use the web crawler's robust parsing function
                raw_text = parse_any_to_text(file_path)
                if not raw_text.strip():
                    continue
                
                # Use metadata from sidecar JSON if available, otherwise create snippet
                snippet = meta.get("text_preview", raw_text[:100].replace('\n', ' ') + "...")
                limited_text = raw_text[:2048]
                
                try:
                    # For web content (HTML/text), always use fast text embeddings
                    # SigLIP/CLIP are only for vision tasks (images, PDFs)
                    if self.model_type in ["siglip", "clip"] and self.text_model:
                        # Use pre-loaded fast text model for web content
                        emb = self.text_model.encode(limited_text, convert_to_tensor=True)
                    elif self.model_type == "colpali":
                        inputs = self.processor(text=[limited_text], truncation=True, max_length=512, return_tensors="pt").to(self.device)
                        outputs = self.model(**inputs)
                        emb = outputs.embeddings.mean(dim=1).squeeze(0)
                    else:
                        # all-MiniLM or other text models
                        emb = self.model.encode(limited_text, convert_to_tensor=True)

                    # Validate embedding
                    if emb is None or (hasattr(emb, 'numel') and emb.numel() == 0):
                        print(f"[WARN] Empty embedding generated for '{url}', skipping...")
                        continue

                    entry = {
                        "embedding": emb,
                        "metadata": {
                            "file_path": file_path,
                            "type": "webhtml",
                            "snippet": snippet,
                            "url": url,
                            "source_engine": meta.get("source_engine", "unknown"),
                            "content_type": meta.get("content_type", ""),
                            "size": meta.get("size", 0),
                            "published_hint": meta.get("published_hint"),
                            "downloaded_at": meta.get("downloaded_at")
                        }
                    }
                    branch_corpus_entries.append(entry)
                    branch_web_results.append({
                        "url": url,
                        "snippet": snippet,
                        "title": meta.get("title", ""),
                        "source_engine": meta.get("source_engine", "unknown")
                    })
                except Exception as e:
                    print(f"[WARN] Error embedding page '{url}': {e}")
                    import traceback
                    print(f"[DEBUG] Traceback: {traceback.format_exc()}")

            # Summarize and update metrics (run in executor to keep event loop responsive)
            branch_snippets = " ".join([r.get("snippet", "") for r in branch_web_results])
            summary_start = time.time()

            # Run LLM summarization in thread executor
            if self.loop:
                toc_node.summary = await self.loop.run_in_executor(
                    None,
                    self.llm_manager.summarize_text,
                    branch_snippets
                )
            else:
                # Fallback if loop not available (shouldn't happen in normal flow)
                toc_node.summary = self.llm_manager.summarize_text(branch_snippets)

            summary_end = time.time()
            toc_node.timestamps['summary_generated'] = datetime.now().isoformat()
            toc_node.metrics['processing_time_ms'] += int((summary_end - summary_start) * 1000)
            
            # Update content metrics
            toc_node.web_results = branch_web_results
            toc_node.corpus_entries = branch_corpus_entries
            toc_node.metrics['web_results_count'] = len(branch_web_results)
            toc_node.metrics['corpus_entries_count'] = len(branch_corpus_entries)
            toc_node.metrics['total_content_length'] = sum(len(r.get("snippet", "")) for r in branch_web_results)

            additional_subqueries = []
            if current_depth < self.max_depth:
                # Run query enhancement in executor to keep event loop responsive
                if self.loop:
                    additional_query = await self.loop.run_in_executor(
                        None,
                        self.llm_manager.enhance_query,
                        sq_clean
                    )
                else:
                    additional_query = self.llm_manager.enhance_query(sq_clean)

                if additional_query and additional_query != sq_clean:
                    additional_subqueries = split_query(additional_query, max_len=self.config.get("max_query_length", 200))

            if additional_subqueries:
                toc_node.metrics['subquery_expansion_count'] = len(additional_subqueries)
                deeper_web_results, deeper_corpus_entries, _, deeper_toc_nodes = await self.perform_recursive_web_searches(additional_subqueries, current_depth=current_depth+1, parent_query=sq_clean)
                branch_web_results.extend(deeper_web_results)
                branch_corpus_entries.extend(deeper_corpus_entries)
                for child_node in deeper_toc_nodes:
                    toc_node.add_child(child_node)

            # Mark node as completed
            toc_node.timestamps['completed'] = datetime.now().isoformat()
            
            aggregated_web_results.extend(branch_web_results)
            aggregated_corpus_entries.extend(branch_corpus_entries)
            toc_nodes.append(toc_node)

        # Group results by domain for reporting
        grouped = {}
        for r, e in zip(aggregated_web_results, aggregated_corpus_entries):
            url = r.get("url", "")
            if url:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain not in grouped:
                    grouped[domain] = []
                grouped[domain].append({
                    "url": url, 
                    "file_path": e["metadata"]["file_path"], 
                    "content_type": e["metadata"].get("content_type", ""),
                    "title": r.get("title", ""),
                    "source_engine": r.get("source_engine", "unknown")
                })
        return aggregated_web_results, aggregated_corpus_entries, grouped, toc_nodes

    def _summarize_web_results(self, web_results):
        lines = []
        reference_urls = []
        for w in web_results:
            url = w.get('url')
            snippet = w.get('snippet')
            title = w.get('title', '')
            source_engine = w.get('source_engine', 'unknown')
            lines.append(f"URL: {url} - Title: {title} - Source: {source_engine} - snippet: {snippet}")
            reference_urls.append(url)
        text = "\n".join(lines)
        # We'll store reference URLs in self._reference_links for final prompt
        self._reference_links = list(set(reference_urls))  # unique
        return self.llm_manager.summarize_text(text)

    def _summarize_local_results(self, local_results):
        lines = []
        for doc in local_results:
            meta = doc.get('metadata', {})
            file_path = meta.get('file_path')
            snippet = meta.get('snippet', '')
            lines.append(f"File: {file_path} snippet: {snippet}")
        text = "\n".join(lines)
        return self.llm_manager.summarize_text(text)

    def _build_final_answer(self, summarized_web, summarized_local, previous_results_content="", follow_up_convo=""):
        toc_str = build_toc_string(self.toc_tree) if self.toc_tree else "No TOC available."
        # Build a reference links string from _reference_links, if available
        reference_links = ""
        if hasattr(self, "_reference_links"):
            reference_links = "\n".join(f"- {link}" for link in self._reference_links)

        # Construct final prompt
        aggregation_prompt = f"""
You are an expert research analyst. Using all of the data provided below, produce a comprehensive, advanced report of at least 3000 words on the topic. 
The report should include:
1) A detailed Table of Contents (based on the search branches), 
2) Multiple sections, 
3) In-depth analysis with citations,
4) A final reference section listing all relevant URLs.

User Query: {self.enhanced_query}

Table of Contents:
{toc_str}

Summarized Web Results:
{summarized_web}

Summarized Local Document Results:
{summarized_local}

Reference Links (unique URLs found):
{reference_links}

Additionally, incorporate any previously gathered information if available. 
Provide a thorough discussion covering background, current findings, challenges, and future directions.
Write the report in clear Markdown with section headings, subheadings, and references.

Report:
"""
        print("[DEBUG] Final RAG prompt constructed. Passing to LLM manager...")
        final_answer = self.llm_manager.generate_final_answer(aggregation_prompt)
        return final_answer

    def save_report(self, final_answer, previous_results=None, follow_up_convo=None):
        print("[INFO] Saving final report to disk...")
        
        # Save TOC as JSON for debugging and analysis
        if self.toc_tree:
            toc_json_path = os.path.join(self.base_result_dir, "toc_analysis.json")
            try:
                save_toc_to_json(self.toc_tree, toc_json_path, include_analytics=True)
                print(f"[INFO] TOC analysis saved to: {toc_json_path}")
            except Exception as e:
                print(f"[WARN] Failed to save TOC JSON: {e}")
        
        return aggregate_results(
            self.query_id,
            self.enhanced_query,
            self.web_results,
            self.local_results,
            final_answer,
            self.config,
            grouped_web_results=self.grouped_web_results,
            previous_results=previous_results,
            follow_up_conversation=follow_up_convo
        )
