# search_session.py

from __future__ import annotations

import asyncio
import heapq
import time
import re
import random
from dataclasses import asdict
from datetime import datetime, timezone


from chunking import split_text_into_chunks
from knowledge_base import KnowledgeBase, late_interaction_score, load_corpus_from_dir, load_retrieval_model, embed_text, retrieve
from web_crawler import search_and_download, sanitize_filename
import json
from aggregator import aggregate_results
from agent_tools import HeuristicAgenticPolicy, LegacyOneShotPolicy, run_policy_tools
from evidence import (
    SearchBranch,
    audit_citations,
    blend_relevance,
    deduplicate_claims,
    make_evidence_item,
    mmr_rerank,
    novelty_against,
    refresh_search_branch,
    stable_id,
    verify_claims,
)
from local_fetch import BrowserBudget
from path_utils import ensure_dir_under, safe_resolve_under
from prompt_budget import (
    EvidenceTextBlock,
    chunk_result_to_block,
    group_blocks_for_coverage,
    render_budgeted_prompt,
    select_blocks_with_budget,
)
from sampling import (
    choose_frontier_index,
    partition_relative_scores,
    seed_from_query_id,
)
from structured_output import (
    derive_search_terms,
    generate_claims_with_fallback,
    generate_gap_subqueries_with_fallback,
    generate_subqueries_with_fallback,
)

#############################################
# LLM Interface - Modular provider system
#############################################

from llm_interface import LLMGenerationError, create_llm_manager, default_model_for_provider


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

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
            'frontier_sampled': False,
            'frontier_sample_weight': 0.0,
            'processing_time_ms': 0,
            'subquery_expansion_count': 0,
            'search_terms': '',
            'verified_claim_count': 0,
            'rejected_claim_count': 0,
            'claim_extraction_calls': 0,
            'claim_extraction_chunks_covered': 0,
        }
        self.similarity_scores = []       # Individual similarity scores for debugging
        self.parent_query = None          # Reference to parent query for context
        self.node_id = None               # Unique identifier for this node

    def add_child(self, child_node):
        self.children.append(child_node)
        child_node.parent_query = self.query_text

    def mark_timestamp(self, name):
        if name not in self.timestamps:
            raise KeyError(f"Unknown timestamp field: {name}")
        self.timestamps[name] = utc_now_iso()

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
    
    # Calculate frontier sampling statistics
    frontier_sampled = sum(1 for node in all_nodes if node.metrics.get('frontier_sampled', False))
    frontier_sampled_percentage = (frontier_sampled / total_nodes * 100) if total_nodes else 0
    verified_claims = sum(int(node.metrics.get('verified_claim_count', 0)) for node in all_nodes)
    rejected_claims = sum(int(node.metrics.get('rejected_claim_count', 0)) for node in all_nodes)
    
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
        'frontier_sampling_metrics': {
            'sampled_nodes': frontier_sampled,
            'sampling_percentage': round(frontier_sampled_percentage, 2),
            'total_candidates': total_nodes
        },
        'claim_metrics': {
            'verified_claims': verified_claims,
            'rejected_claims': rejected_claims,
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

def save_toc_to_json(toc_nodes, output_path, include_analytics=True, pruned_branches=None, run_metadata=None):
    """
    Save the TOC tree to a JSON file with optional analytics.
    """
    toc_data = {
        'toc_tree': [node.to_dict() for node in toc_nodes] if toc_nodes else [],
        'pruned_branches': pruned_branches or [],
        'metadata': {
            'total_nodes': len([node for node in toc_nodes]) if toc_nodes else 0,
            'exported_at': datetime.now().isoformat(),
            'version': '1.0',
            'run': run_metadata or {},
        }
    }
    
    if include_analytics:
        toc_data['analytics'] = analyze_toc_tree(toc_nodes)
        toc_data['analytics']['branch_selection_metrics'] = {
            'pruned_branches': len(pruned_branches or []),
        }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(toc_data, f, indent=2, ensure_ascii=False)
    
    return output_path

#########################################################
# The "SearchSession" class: orchestrate the entire pipeline,
# including optional frontier sampling, recursive web search,
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
        configured_llm = config.get("llm", {}) if isinstance(config.get("llm", {}), dict) else {}
        llm_config = {
            **configured_llm,
            "provider": llm_provider,
            "model": llm_model or self._get_default_model(llm_provider, rag_model),
            "personality": personality or configured_llm.get("personality")
        }
        self.llm_manager = create_llm_manager(**llm_config)

        self.query_id = str(config.get("query_id") or stable_id(self.query, prefix="run"))
        configured_seed = self.config.get("seed")
        self.seed = int(configured_seed) if configured_seed is not None else seed_from_query_id(self.query_id)
        self.rng = random.Random(self.seed)
        self.results_base_dir = self.config.get("results_base_dir", "results")
        self.base_result_dir = str(ensure_dir_under(self.results_base_dir, self.query_id))
        self.max_chunks_per_doc_in_results = int(self.config.get("max_chunks_per_doc_in_results", 3))

        print(f"[INFO] Initializing SearchSession for query_id={self.query_id}, seed={self.seed}")

        # Enhance the query via chain-of-thought.
        self.enhanced_query = self.llm_manager.enhance_query(self.query)
        # Every downstream prompt sees only the enhanced query, so a truncated
        # or garbled enhancement sends the whole run after a hallucinated topic.
        if len((self.enhanced_query or "").strip()) < 20:
            print(f"[WARN] Query enhancement returned {self.enhanced_query!r}; using the original query.")
            self.enhanced_query = self.query

        # Load retrieval only when the run can actually use it. This keeps
        # LiteLLM/local-tool smoke runs from requiring embedding dependencies.
        self.retrieval_active = bool(self.corpus_dir or self.web_search_enabled)
        self.model = None
        self.processor = None
        self.model_type = self.retrieval_model
        self.text_model = None
        self.enhanced_query_embedding = None
        if self.retrieval_active:
            self.model, self.processor, self.model_type = load_retrieval_model(
                model_choice=self.retrieval_model,
                device=self.device
            )

            # Keep a single retrieval vector space per session. Earlier hybrid
            # MiniLM-for-text + SigLIP/CLIP-for-vision paths could mix dimensions.
            self.text_model = None

            # Compute the overall enhanced query embedding once.
            print("[INFO] Computing embedding for enhanced query...")
            self.enhanced_query_embedding = embed_text(self.enhanced_query, self.model, self.processor, self.model_type, self.device)
        else:
            print("[INFO] Retrieval inactive: no corpus_dir and web search disabled.")

        # Create a knowledge base.
        print("[INFO] Creating KnowledgeBase...")
        self.kb = KnowledgeBase(
            self.model,
            self.processor,
            model_type=self.model_type,
            device=self.device,
            text_model=self.text_model,
            max_chunks_per_doc_in_results=self.max_chunks_per_doc_in_results,
        )

        # Load local corpus if available.
        self.corpus = []
        if self.corpus_dir:
            print(f"[INFO] Loading local documents from {self.corpus_dir}")
            local_docs = load_corpus_from_dir(
                self.corpus_dir,
                self.model,
                self.processor,
                self.device,
                self.model_type,
                chunk_chars=int(self.config.get("chunk_chars", 1200)),
                chunk_overlap=int(self.config.get("chunk_overlap", 200)),
                max_chunks_per_doc=int(self.config.get("max_chunks_per_doc", 40)),
            )
            self.corpus.extend(local_docs)
        self.kb.add_documents(self.corpus)

        # Placeholders for web search results and TOC tree.
        self.web_results = []
        self.evidence_items = []
        self.claim_ledger = {"kept": [], "rejected": [], "generation_failures": []}
        # Sources fetched but dropped before chunking, and branches whose summary
        # call failed. Both were previously invisible: a dropped page looked like
        # a page that was never found, and a failed summary looked like a summary.
        self.dropped_sources = []
        self.summary_failures = []
        self.citation_audit = {}
        self.tool_results = []
        self.agent_trace = {}
        self.grouped_web_results = {}
        self.local_results = []
        self.pruned_branches = []
        # Browser escalation is expensive, so the allowance is shared across the
        # whole run and spent in branch-priority order rather than per page.
        self.browser_budget = BrowserBudget(int(self.config.get("browser_escalation_limit", 0)))
        self.toc_tree = []  # List of TOCNode objects for the initial subqueries

    def _get_default_model(self, provider, rag_model):
        """Get default model for the specified provider."""
        return default_model_for_provider(provider, rag_model)

    async def run_session(self):
        """
        Main entry point: perform recursive web search (if enabled) and then local retrieval.
        """
        print(f"[INFO] Starting session with query_id={self.query_id}, max_depth={self.max_depth}")
        plain_enhanced_query = clean_search_query(self.enhanced_query)

        if self._agentic_tools_active():
            self.tool_results = await asyncio.to_thread(self._run_agentic_tools, plain_enhanced_query)

        # 1) Generate subqueries from the enhanced query
        initial_subqueries = self._generate_subqueries(plain_enhanced_query)
        print(f"[INFO] Generated {len(initial_subqueries)} initial subqueries from the enhanced query.")

        # 3) If web search is enabled and max_depth >= 1, do the recursive expansion
        if self.web_search_enabled and self.max_depth >= 1:
            web_results, web_entries, grouped, toc_nodes = await self.perform_recursive_web_searches(initial_subqueries, current_depth=1)
            self.web_results = web_results
            self.grouped_web_results = grouped
            self.toc_tree = toc_nodes
            # Branch exploration adds chunk entries to the knowledge base as they are produced.
            self.corpus.extend(web_entries)
        else:
            print("[INFO] Web search is disabled or max_depth < 1, skipping web expansion.")

        # 4) Local retrieval
        print(f"[INFO] Retrieving top {self.top_k} local documents for final answer.")
        self.local_results = self.kb.search(self.enhanced_query, top_k=self.top_k) if self.kb.corpus else []

        # 5) Summaries and final RAG generation
        summarized_web = await asyncio.to_thread(self._summarize_web_results, self.web_results)
        summarized_local = await asyncio.to_thread(self._summarize_local_results, self.local_results)
        summarized_tools = self._summarize_tool_results(self.tool_results)
        final_answer = await asyncio.to_thread(self._build_final_answer, summarized_web, summarized_local, summarized_tools)
        print("[INFO] Finished building final advanced report.")
        return final_answer

    def save_diagnostics(self):
        """Persist every ledger, without writing a report.

        Called on its own when final generation fails: the branch tree, evidence
        and verified claims are the expensive part of a run and stay usable for a
        retry, but nothing that is not a report gets written as one.
        """
        if self.toc_tree or self.pruned_branches:
            toc_json_path = safe_resolve_under(self.base_result_dir, "toc_analysis.json")
            try:
                save_toc_to_json(
                    self.toc_tree,
                    toc_json_path,
                    include_analytics=True,
                    pruned_branches=self.pruned_branches,
                    run_metadata={"query_id": self.query_id, "seed": self.seed},
                )
                print(f"[INFO] TOC analysis saved to: {toc_json_path}")
            except Exception as e:
                print(f"[WARN] Failed to save TOC JSON: {e}")

        self._write_json("run_metadata.json", {"query_id": self.query_id, "seed": self.seed}, "Run metadata")
        if self.evidence_items:
            self._write_json("evidence_ledger.json", [asdict(item) for item in self.evidence_items], "Evidence ledger")
        if self.dropped_sources:
            self._write_json("dropped_sources.json", self.dropped_sources, "Dropped source ledger")
        if self.citation_audit:
            self._write_json("citation_audit.json", self.citation_audit, "Citation audit")
        self._write_json(
            "claim_ledger.json",
            {
                "metadata": {"query_id": self.query_id, "seed": self.seed},
                **self.claim_ledger,
                "summary_failures": self.summary_failures,
            },
            "Claim ledger",
        )
        if self.tool_results:
            self._write_json("tool_results.json", [result.to_dict() for result in self.tool_results], "Tool results")
        if self.agent_trace:
            self._write_json("agent_trace.json", self.agent_trace, "Agent trace")

    def _write_json(self, filename, payload, label):
        path = safe_resolve_under(self.base_result_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            print(f"[INFO] {label} saved to: {path}")
        except Exception as e:
            print(f"[WARN] Failed to save {label.lower()}: {e}")

    def _agentic_tools_active(self):
        """Local read-only tools only help when the run is about local material.

        With `workspace: "."` and no corpus, a question about GPU inference spent
        eight calls grepping NanoSage's own source and fed the results to the
        report as evidence.
        """
        tool_config = self.config.get("agentic_tools", {})
        if not tool_config.get("enabled", False):
            return False
        if bool(tool_config.get("require_corpus", True)) and not self.corpus_dir:
            print("[INFO] Agentic tools skipped: no corpus_dir (set agentic_tools.require_corpus: false to force).")
            return False
        return True

    def _run_agentic_tools(self, query):
        tool_config = self.config.get("agentic_tools", {})
        max_calls = int(tool_config.get("max_calls", 5))
        max_rounds = int(tool_config.get("max_rounds", 3))
        min_score = float(tool_config.get("min_score", 0.05))
        workspace = safe_resolve_under(tool_config.get("workspace", ".")) if tool_config.get("workspace") else safe_resolve_under(".")
        mode = str(tool_config.get("mode", "iterative")).lower()
        policy = LegacyOneShotPolicy() if mode == "one-shot" else HeuristicAgenticPolicy()
        results, trace = run_policy_tools(
            query,
            workspace,
            policy,
            max_rounds=max_rounds,
            max_calls=max_calls,
            min_score=min_score,
        )
        self.agent_trace = trace
        print(f"[INFO] Agentic tool policy ran {len(results)} tool calls across {len(trace.get('rounds', []))} rounds; stop={trace.get('stop_reason')}.")
        for result in results:
            print(f"[DEBUG] tool={result.name} score={result.score:.3f} ok={result.ok} summary={result.summary}")
        return results

    def _generate_subqueries(self, query):
        legacy = split_query(query, max_len=self.config.get("max_query_length", 200))
        count = max(1, int(self.config.get("subquery_count", 5)))
        questions = generate_subqueries_with_fallback(
            self.llm_manager,
            query,
            count=count,
            fallback=legacy,
            enabled=bool(self.config.get("structured_subqueries", True)),
        )
        return [
            {
                "question": clean_search_query(item["question"]),
                "search_terms": clean_search_query(item.get("search_terms", "")),
            }
            for item in questions
            if clean_search_query(item["question"])
        ]

    def _build_claim_extraction_batches(self, branch_corpus_entries):
        blocks = []
        for entry in branch_corpus_entries:
            block = chunk_result_to_block(entry)
            if block is not None:
                blocks.append(block)
        grouped = group_blocks_for_coverage(
            blocks,
            int(self.config.get("claim_extraction_char_budget", 8000)),
            int(self.config.get("max_claim_extraction_calls_per_branch", 2)),
        )
        return [
            [f"{block.label}\n{block.text}" for block in group]
            for group in grouped
        ]

    def _extract_claims_for_branch(self, branch_query, branch_corpus_entries):
        batches = self._build_claim_extraction_batches(branch_corpus_entries)
        claims = []
        failures = []
        for call_index, chunk_segments in enumerate(batches, start=1):
            extracted, error = generate_claims_with_fallback(
                self.llm_manager,
                branch_query,
                chunk_segments,
            )
            claims.extend(extracted)
            if error:
                failures.append({"call_index": call_index, "reason": error})
        return (
            deduplicate_claims(claims),
            failures,
            len(batches),
            sum(len(batch) for batch in batches),
        )

    def _generate_branch_expansion(self, branch_query, branch_summary, kept_claims):
        claim_texts = [
            record.get("claim", {}).get("claim_text", "")
            for record in kept_claims
            if isinstance(record, dict)
        ]
        claim_texts = [text for text in claim_texts if isinstance(text, str) and text.strip()]
        count = max(1, int(self.config.get("subquery_count", 5)))
        has_findings = bool((branch_summary or "").strip() or claim_texts)
        if has_findings and bool(self.config.get("structured_subqueries", True)):
            questions = generate_gap_subqueries_with_fallback(
                self.llm_manager,
                branch_query,
                branch_summary,
                claim_texts,
                count=count,
                fallback=[],
            )
            expansion = [
                {
                    "question": clean_search_query(item["question"]),
                    "search_terms": clean_search_query(item.get("search_terms", "")),
                }
                for item in questions
                if clean_search_query(item["question"])
            ]
            if expansion:
                return expansion
            # A failed gap call must cost this branch better children, not all of
            # them: without this the branch expands to nothing at all, which is
            # worse than the enhancement path it replaced.
            print(f"[WARN] Gap expansion produced no questions for '{branch_query[:60]}'; using enhancement path.")

        # With no findings there is no evidence-grounded gap to describe, so the
        # legacy enhancement path remains the only useful expansion signal.
        additional_query = self.llm_manager.enhance_query(branch_query)
        if not additional_query or additional_query == branch_query:
            return []
        return self._generate_subqueries(additional_query)

    def _score_subqueries(self, subqueries, depth=1, parent_query=None, explored_queries=None):
        """Create relevance/novelty-scored search branches from subquery records.

        Accepts either `{"question", "search_terms"}` records or bare strings, so
        recursive expansions and legacy callers both work; missing search terms
        are derived deterministically.
        """
        seen = set()
        scored = []
        terms_by_query = {}
        # A depth-2 question about a mechanism is necessarily further from the
        # root query than a restatement of the root, so root-only scoring prunes
        # exactly the specific sub-questions deep search exists to reach. Blend
        # in similarity to the parent branch so a child is judged against what it
        # was spawned to investigate.
        parent_weight = float(self.config.get("parent_relevance_weight", 0.4))
        parent_weight = min(1.0, max(0.0, parent_weight))
        parent_embedding = None
        if parent_query and parent_weight > 0:
            parent_embedding = embed_text(parent_query, self.model, self.processor, self.model_type, self.device)
        for sq in subqueries:
            if isinstance(sq, dict):
                raw_question = sq.get("question", "")
                raw_terms = sq.get("search_terms", "")
            else:
                raw_question, raw_terms = sq, ""
            sq_clean = clean_search_query(raw_question)
            if not sq_clean or sq_clean in seen:
                continue
            seen.add(sq_clean)
            terms_by_query[sq_clean] = clean_search_query(raw_terms) or derive_search_terms(sq_clean)
            node_embedding = embed_text(sq_clean, self.model, self.processor, self.model_type, self.device)
            root_relevance = late_interaction_score(self.enhanced_query_embedding, node_embedding)
            relevance = blend_relevance(
                root_relevance,
                late_interaction_score(parent_embedding, node_embedding) if parent_embedding is not None else None,
                parent_weight,
            )
            scored.append((sq_clean, relevance))

        ranked = mmr_rerank(scored, lambda_relevance=self.config.get("branch_mmr_lambda", 0.72))
        explored_queries = explored_queries or []
        branches = []
        for query, relevance in ranked:
            novelty = novelty_against(query, explored_queries)
            branches.append(SearchBranch(
                query=query,
                depth=depth,
                relevance=relevance,
                parent_query=parent_query,
                novelty=novelty,
                search_terms=terms_by_query.get(query, ""),
            ))
        return branches

    def _push_branch(self, frontier, branch, counter):
        heapq.heappush(frontier, (-branch.priority, counter, branch))
        return counter + 1

    def _enqueue_branches(self, frontier, branches, counter, *, source):
        if not branches:
            return counter
        forced_count = max(1, int(self.config.get("min_branches_if_all_pruned", 3)))
        kept_indices, threshold, forced = partition_relative_scores(
            [branch.relevance for branch in branches],
            margin=max(0.0, float(self.config.get("min_relevance_margin", 0.25))),
            absolute_floor=self.config.get("min_relevance"),
            fallback_count=forced_count,
        )
        if forced:
            print(
                f"[WARN] All {len(branches)} branches would be pruned at relevance cutoff "
                f"{threshold:.3f}; forcing top {len(kept_indices)} candidates."
            )
        kept_index_set = set(kept_indices)
        for index, branch in enumerate(branches):
            if index in kept_index_set:
                counter = self._push_branch(frontier, branch, counter)
            else:
                reason = f"below_relative_relevance_cutoff:{threshold:.3f}"
                self.pruned_branches.append({
                    "query": branch.query,
                    "score": round(branch.relevance, 6),
                    "depth": branch.depth,
                    "source": source,
                    "reason": reason,
                })
                print(f"[INFO] Pruned branch '{branch.query}' ({branch.relevance:.3f} < {threshold:.3f}).")
        return counter

    def _pop_frontier_branch(self, frontier, explored_queries):
        if not frontier:
            return None, False, 0.0
        sample_enabled = bool(self.config.get("monte_carlo_search", True))
        sample_top_n = int(self.config.get("monte_carlo_samples", 3))
        if not sample_enabled or sample_top_n <= 1 or len(frontier) <= 1:
            _, _, branch = heapq.heappop(frontier)
            return branch, False, 0.0

        candidates = []
        for _ in range(min(sample_top_n, len(frontier))):
            candidates.append(heapq.heappop(frontier))
        branches = [entry[2] for entry in candidates]
        temperature = float(self.config.get("branch_temperature", 0.25))
        if temperature <= 0:
            print("[WARN] branch_temperature must be > 0; using deterministic frontier pop.")
            for entry in candidates[1:]:
                heapq.heappush(frontier, entry)
            return candidates[0][2], False, 0.0
        chosen_index, sampled, chosen_weight = choose_frontier_index(
            [branch.priority for branch in branches],
            window_size=len(branches),
            temperature=temperature,
            rng=self.rng,
        )
        chosen_branch = branches[chosen_index]
        for index, entry in enumerate(candidates):
            if index != chosen_index:
                heapq.heappush(frontier, entry)
        return chosen_branch, sampled, chosen_weight

    def _refresh_branch_priority(self, branch, explored_queries):
        return refresh_search_branch(
            branch,
            explored_queries,
            repush_delta=float(self.config.get("stale_priority_repush_delta", 1e-6)),
        )

    def _select_branch_sources(self, page_candidates):
        """Split a branch's fetched pages into kept and dropped.

        Returns `(kept, dropped, cutoff)`. With gating disabled every page is
        kept. `min_sources_per_branch` protects a branch that found only weak
        evidence from being emptied: a thin branch should report thin evidence,
        not silently vanish.
        """
        if not page_candidates:
            return [], [], 0.0
        margin = float(self.config.get("source_relevance_margin", 0.0))
        floor = self.config.get("min_source_relevance")
        if margin <= 0 and not floor:
            return list(page_candidates), [], 0.0
        keep_at_least = max(1, int(self.config.get("min_sources_per_branch", 2)))
        kept_indices, cutoff, forced = partition_relative_scores(
            [candidate["relevance"] for candidate in page_candidates],
            margin=max(0.0, margin),
            absolute_floor=float(floor) if floor else None,
            fallback_count=keep_at_least,
        )
        ranked = sorted(range(len(page_candidates)), key=lambda i: (-page_candidates[i]["relevance"], i))
        kept_index_set = set(kept_indices)
        # Top up rather than let a whole branch fall below an absolute floor.
        for index in ranked:
            if len(kept_index_set) >= keep_at_least:
                break
            kept_index_set.add(index)
        if forced:
            print(f"[WARN] All branch sources fell below cutoff {cutoff:.3f}; keeping the top {len(kept_index_set)}.")
        kept = [candidate for index, candidate in enumerate(page_candidates) if index in kept_index_set]
        dropped = [candidate for index, candidate in enumerate(page_candidates) if index not in kept_index_set]
        return kept, dropped, cutoff

    def _build_branch_summary_segments(self, branch_query, branch_corpus_entries):
        if not branch_corpus_entries:
            return []
        retrieved = retrieve(
            branch_query,
            branch_corpus_entries,
            self.model,
            self.processor,
            top_k=int(self.config.get("branch_summary_top_k", max(self.top_k, 8))),
            model_type=self.model_type,
            device=self.device,
            text_model=self.text_model,
            max_chunks_per_doc_in_results=int(self.config.get("max_chunks_per_doc_in_results", 3)),
        )
        blocks = []
        for entry in retrieved:
            block = chunk_result_to_block(entry)
            if block is not None:
                blocks.append(block)
        selected = select_blocks_with_budget(
            blocks,
            int(self.config.get("branch_summary_char_budget", 8000)),
        )
        return [f"{block.label}\n{block.text}" for block in selected]

    def _canonical_text_by_evidence_id(self, branch_corpus_entries):
        paths_by_id = {}
        for entry in branch_corpus_entries:
            meta = entry.get("metadata", {})
            evidence_id = meta.get("parent_evidence_id") or meta.get("evidence_id")
            path = meta.get("extracted_text_path")
            if evidence_id and path:
                paths_by_id[evidence_id] = path
        canonical = {}
        for evidence_id, path in paths_by_id.items():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    canonical[evidence_id] = f.read()
            except Exception as exc:
                print(f"[WARN] Failed to read canonical text for claim verification ({evidence_id}): {exc}")
        return canonical

    async def perform_recursive_web_searches(self, subqueries, current_depth=1, parent_query=None):
        """
        Perform evidence-guided branch search up to self.max_depth.

        This keeps the public return contract of the old recursive method, but
        explores a priority queue of relevant/novel branches instead of blindly
        walking depth-first in input order.
        """
        aggregated_web_results = []
        aggregated_corpus_entries = []
        root_nodes = []
        node_by_query = {}
        explored_queries = []
        frontier = []
        counter = 0
        max_branches = int(self.config.get("max_branches", 100))

        counter = self._enqueue_branches(
            frontier,
            self._score_subqueries(subqueries, current_depth, parent_query),
            counter,
            source="initial",
        )

        while frontier and len(explored_queries) < max_branches:
            branch, sampled, sample_weight = self._pop_frontier_branch(frontier, explored_queries)
            if branch is None:
                break
            branch, should_repush = self._refresh_branch_priority(branch, explored_queries)
            if should_repush:
                counter = self._push_branch(frontier, branch, counter)
                continue
            sq_clean = branch.query
            if sq_clean in node_by_query:
                continue

            # Create a TOC node with enhanced tracking
            toc_node = TOCNode(query_text=sq_clean, depth=branch.depth)
            toc_node.node_id = stable_id(sq_clean, branch.depth, branch.parent_query, prefix="node")
            toc_node.mark_timestamp('created')
            toc_node.parent_query = branch.parent_query if branch.parent_query else self.query
            toc_node.relevance_score = branch.relevance
            toc_node.add_similarity_score(branch.relevance)
            toc_node.metrics['branch_priority'] = round(branch.priority, 6)
            toc_node.metrics['branch_novelty'] = round(branch.novelty, 6)
            toc_node.metrics['frontier_sampled'] = sampled
            toc_node.metrics['frontier_sample_weight'] = round(sample_weight, 6)

            node_by_query[sq_clean] = toc_node
            if branch.parent_query and branch.parent_query in node_by_query:
                node_by_query[branch.parent_query].add_child(toc_node)
            else:
                root_nodes.append(toc_node)
            explored_queries.append(sq_clean)

            # Create subdirectory
            safe_subquery = sanitize_filename(sq_clean)[:30]
            subquery_dir = str(ensure_dir_under(self.base_result_dir, f"web_{safe_subquery}"))
            # Engines get keywords; the full question stays with the node for
            # scoring, summarization and claim extraction.
            search_terms = branch.search_terms or derive_search_terms(sq_clean)
            toc_node.metrics['search_terms'] = search_terms
            print(f"[DEBUG] Searching web for '{search_terms}' (branch: {sq_clean[:70]}...) "
                  f"at depth={branch.depth} priority={branch.priority:.3f}")

            # Track web search timing
            toc_node.mark_timestamp('web_search_start')
            web_search_start = time.time()

            pages = await search_and_download(
                keyword=search_terms,
                out_dir=subquery_dir,
                top_n=self.config.get("web_search_limit", 5),
                concurrency=self.config.get("web_concurrency", 8),
                include_wikipedia=self.config.get("include_wikipedia", False),
                browser_budget=self.browser_budget,
                scholarly_search=bool(self.config.get("scholarly_search", True)),
            )

            web_search_end = time.time()
            toc_node.mark_timestamp('web_search_end')
            toc_node.metrics['processing_time_ms'] += int((web_search_end - web_search_start) * 1000)
            branch_web_results = []
            branch_corpus_entries = []
            # Ranking decides what to download; nothing decided what to keep. Pages
            # that ranked top-N on domain reputation but are off-topic still cost a
            # summary and a claim-extraction call, and crowd out on-topic chunks.
            #
            # The cut is relative to the best page this branch actually found, the
            # same shape as branch pruning. An absolute threshold looks principled
            # and is not: measured page scores cluster tightly (0.45-0.71 on one
            # run), so a fixed cut lands mid-cluster and starves whole branches.
            source_margin = float(self.config.get("source_relevance_margin", 0.0))
            source_floor = self.config.get("min_source_relevance")
            gating_sources = source_margin > 0 or source_floor
            branch_embedding = (
                embed_text(sq_clean, self.model, self.processor, self.model_type, self.device)
                if gating_sources
                else None
            )
            page_candidates = []
            for page in pages:
                if not page:
                    continue
                file_path = page.get("file_path")
                url = page.get("url")
                meta = page.get("meta", {})
                if not file_path or not url:
                    continue

                canonical_path = meta.get("extracted_text_path") or f"{file_path}.extracted.txt"
                try:
                    with open(canonical_path, "r", encoding="utf-8") as f:
                        raw_text = f.read()
                except Exception as exc:
                    print(f"[WARN] Canonical extracted text unavailable for '{url}'; skipping page: {exc}")
                    continue
                if not raw_text.strip():
                    continue
                recorded_length = int(meta.get("extracted_text_length", len(raw_text)) or 0)
                if recorded_length != len(raw_text):
                    print(
                        f"[WARN] Canonical text length mismatch for '{url}' "
                        f"(metadata={recorded_length}, actual={len(raw_text)}); using persisted text."
                    )

                snippet = meta.get("text_preview", raw_text[:800] + "...")

                try:
                    evidence = make_evidence_item(page, meta, sq_clean, snippet)
                    chunks = split_text_into_chunks(
                        evidence.evidence_id,
                        raw_text,
                        chunk_chars=int(self.config.get("chunk_chars", 1200)),
                        chunk_overlap=int(self.config.get("chunk_overlap", 200)),
                        max_chunks_per_doc=int(self.config.get("max_chunks_per_doc", 40)),
                    )
                    page_entries = []
                    page_relevance = None
                    for chunk in chunks:
                        emb = embed_text(chunk.text, self.model, self.processor, self.model_type, self.device)
                        if branch_embedding is not None:
                            chunk_relevance = late_interaction_score(branch_embedding, emb)
                            page_relevance = chunk_relevance if page_relevance is None else max(page_relevance, chunk_relevance)
                        entry = {
                            "embedding": emb,
                            "metadata": {
                                "evidence_id": evidence.evidence_id,
                                "parent_evidence_id": evidence.evidence_id,
                                "chunk_id": f"{evidence.evidence_id}#chunk-{chunk.chunk_index}",
                                "chunk_index": chunk.chunk_index,
                                "char_start": chunk.char_start,
                                "char_end": chunk.char_end,
                                "file_path": file_path,
                                "extracted_text_path": canonical_path,
                                "type": "webchunk",
                                "text": chunk.text,
                                "snippet": chunk.text[:240],
                                "url": url,
                                "branch_query": sq_clean,
                                "source_engine": meta.get("source_engine", "unknown"),
                                "content_type": meta.get("content_type", ""),
                                "size": meta.get("size", 0),
                                "published_hint": meta.get("published_hint"),
                                "downloaded_at": meta.get("downloaded_at")
                            }
                        }
                        page_entries.append(entry)
                    # A page is judged by its best chunk: a long source with one
                    # directly relevant section is still worth keeping.
                    page_candidates.append({
                        "evidence": evidence,
                        "entries": page_entries,
                        "relevance": float(page_relevance) if page_relevance is not None else 0.0,
                        "web_result": {
                            "evidence_id": evidence.evidence_id,
                            "url": url,
                            "snippet": snippet,
                            "file_path": file_path,
                            "extracted_text_path": canonical_path,
                            "content_type": meta.get("content_type", ""),
                            "title": meta.get("title", ""),
                            "source_engine": meta.get("source_engine", "unknown")
                        },
                    })
                except Exception as e:
                    print(f"[WARN] Error embedding page '{url}': {e}")

            kept_pages, dropped_pages, source_cutoff = self._select_branch_sources(page_candidates)
            for candidate in kept_pages:
                self.evidence_items.append(candidate["evidence"])
                branch_corpus_entries.extend(candidate["entries"])
                branch_web_results.append(candidate["web_result"])
            for candidate in dropped_pages:
                result = candidate["web_result"]
                self.dropped_sources.append({
                    "branch_query": sq_clean,
                    "url": result["url"],
                    "title": result["title"],
                    "source_engine": result["source_engine"],
                    "relevance": round(candidate["relevance"], 6),
                    "cutoff": round(source_cutoff, 6),
                })
                print(f"[INFO] Dropped off-topic source ({candidate['relevance']:.3f} < {source_cutoff:.3f}): {result['url']}")

            # Summarize and update metrics
            if branch_corpus_entries:
                self.kb.add_documents(branch_corpus_entries)
            branch_segments = self._build_branch_summary_segments(sq_clean, branch_corpus_entries)
            summary_start = time.time()
            summary_input = "\n\n".join(branch_segments) or "No retrieved evidence chunks fit the branch summary budget."
            try:
                toc_node.summary = await asyncio.to_thread(
                    self.llm_manager.summarize_text,
                    summary_input,
                    int(self.config.get("branch_summary_char_budget", 8000)),
                    sq_clean,
                )
            except LLMGenerationError as exc:
                # An empty summary costs this branch's contribution to the report.
                # Writing the failure text as the summary would have fed it to the
                # report generator as evidence, so record it and move on.
                toc_node.summary = ""
                self.summary_failures.append({"branch_query": sq_clean, "reason": str(exc)})
                print(f"[WARN] Branch summary failed for '{sq_clean[:60]}': {exc}")
            summary_end = time.time()
            toc_node.mark_timestamp('summary_generated')
            toc_node.metrics['processing_time_ms'] += int((summary_end - summary_start) * 1000)
            claims, generation_failures, extraction_calls, covered_chunks = await asyncio.to_thread(
                self._extract_claims_for_branch,
                sq_clean,
                branch_corpus_entries,
            )
            canonical_text = self._canonical_text_by_evidence_id(branch_corpus_entries)
            kept_claims, rejected_claims = verify_claims(claims, canonical_text)
            for record in kept_claims:
                record["branch_query"] = sq_clean
            for record in rejected_claims:
                record["branch_query"] = sq_clean
            self.claim_ledger["kept"].extend(kept_claims)
            self.claim_ledger["rejected"].extend(rejected_claims)
            for failure in generation_failures:
                self.claim_ledger["generation_failures"].append({
                    "branch_query": sq_clean,
                    **failure,
                })
            toc_node.metrics['verified_claim_count'] = len(kept_claims)
            toc_node.metrics['rejected_claim_count'] = len(rejected_claims)
            toc_node.metrics['claim_extraction_calls'] = extraction_calls
            toc_node.metrics['claim_extraction_chunks_covered'] = covered_chunks

            # Update content metrics
            toc_node.web_results = branch_web_results
            toc_node.corpus_entries = branch_corpus_entries
            toc_node.metrics['web_results_count'] = len(branch_web_results)
            toc_node.metrics['corpus_entries_count'] = len(branch_corpus_entries)
            toc_node.metrics['total_content_length'] = sum(len(e.get("metadata", {}).get("snippet", "")) for e in branch_corpus_entries)

            additional_subqueries = []
            if branch.depth < self.max_depth:
                try:
                    additional_subqueries = await asyncio.to_thread(
                        self._generate_branch_expansion,
                        sq_clean,
                        toc_node.summary,
                        kept_claims,
                    )
                except LLMGenerationError as exc:
                    print(f"[WARN] Branch expansion skipped for '{sq_clean[:60]}': {exc}")

            if additional_subqueries:
                child_branches = self._score_subqueries(
                    additional_subqueries,
                    depth=branch.depth + 1,
                    parent_query=sq_clean,
                    explored_queries=explored_queries,
                )
                toc_node.metrics['subquery_expansion_count'] = len(child_branches)
                counter = self._enqueue_branches(frontier, child_branches, counter, source=sq_clean)

            # Mark node as completed
            toc_node.mark_timestamp('completed')

            aggregated_web_results.extend(branch_web_results)
            aggregated_corpus_entries.extend(branch_corpus_entries)

        # Group results by domain for reporting
        grouped = {}
        entry_by_parent = {}
        for e in aggregated_corpus_entries:
            meta = e.get("metadata", {})
            parent_id = meta.get("parent_evidence_id") or meta.get("evidence_id")
            if parent_id and parent_id not in entry_by_parent:
                entry_by_parent[parent_id] = e
        for r in aggregated_web_results:
            e = entry_by_parent.get(r.get("evidence_id"), {"metadata": {}})
            url = r.get("url", "")
            if url:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain not in grouped:
                    grouped[domain] = []
                meta = e.get("metadata", {})
                grouped[domain].append({
                    "evidence_id": r.get("evidence_id") or meta.get("parent_evidence_id", ""),
                    "url": url,
                    "file_path": meta.get("file_path", ""),
                    "content_type": meta.get("content_type", ""),
                    "title": r.get("title", ""),
                    "source_engine": r.get("source_engine", "unknown")
                })
        return aggregated_web_results, aggregated_corpus_entries, grouped, root_nodes

    def _summarize_web_results(self, web_results):
        self._reference_links = sorted({w.get('url') for w in web_results if w.get('url')})
        lines = []
        for node in self._all_toc_nodes():
            if node.summary:
                lines.append(
                    f"Branch: {node.query_text}\n"
                    f"Verified claims: {node.metrics.get('verified_claim_count', 0)}\n"
                    f"Summary: {node.summary}"
                )
        return "\n\n".join(lines) or "No web branch summaries were generated."

    def _all_toc_nodes(self):
        nodes = []
        pending = list(self.toc_tree)
        while pending:
            node = pending.pop(0)
            nodes.append(node)
            pending[0:0] = node.children
        return nodes

    def _summarize_local_results(self, local_results):
        blocks = []
        for doc in local_results:
            meta = doc.get('metadata', {})
            text = meta.get('text') or meta.get('snippet', '')
            if not text:
                continue
            label = (
                f"Retrieved source: {meta.get('file_path', '')}\n"
                f"Evidence ID: {meta.get('parent_evidence_id') or meta.get('evidence_id', '')}\n"
                f"URL: {meta.get('url', '')}"
            )
            blocks.append(EvidenceTextBlock(label, text, float(meta.get('search_score', 0.0))))
        selected = select_blocks_with_budget(
            blocks,
            int(self.config.get("final_retrieval_char_budget", 6000)),
        )
        return "\n\n".join(f"{block.label}\n{block.text}" for block in selected) or "No final retrieval results."

    def _summarize_tool_results(self, tool_results):
        if not tool_results:
            return "No local tool observations."
        lines = []
        for result in tool_results:
            lines.append(
                f"Tool: {result.name} | score={result.score:.3f} | ok={result.ok} | "
                f"summary={result.summary}\n{result.content[:1200]}"
            )
        return "\n\n".join(lines)

    def _build_final_answer(self, summarized_web, summarized_local, summarized_tools="", previous_results_content="", follow_up_convo=""):
        toc_str = build_toc_string(self.toc_tree) if self.toc_tree else "No TOC available."
        blocks = [EvidenceTextBlock("User Query:", self.enhanced_query, 100.0)]
        # Claims carry an evidence_id; the reference list carries URLs. Without a
        # mapping between them in the same prompt, the report is asked to cite
        # sources it has no way to attribute, so the URL travels with the claim.
        url_by_evidence_id = {item.evidence_id: item.url for item in self.evidence_items}
        for record in self.claim_ledger.get("kept", []):
            claim = record.get("claim", {})
            evidence_id = claim.get("evidence_id", "")
            source_url = url_by_evidence_id.get(evidence_id, "")
            blocks.append(EvidenceTextBlock(
                f"Verified Claim [{evidence_id}] source {source_url or 'unknown'} offsets "
                f"{claim.get('char_start', 0)}-{claim.get('char_end', 0)}:",
                f"{claim.get('claim_text', '')}\nExact quote: {claim.get('quote', '')}",
                90.0,
            ))
        for node in self._all_toc_nodes():
            if node.summary:
                blocks.append(EvidenceTextBlock(
                    f"Branch Summary: {node.query_text}\nVerified claims: "
                    f"{node.metrics.get('verified_claim_count', 0)}",
                    node.summary,
                    20.0 + float(node.relevance_score),
                ))
        if not self.toc_tree and summarized_web:
            blocks.append(EvidenceTextBlock("Web Summary:", summarized_web, 20.0))
        blocks.extend([
            EvidenceTextBlock("Table of Contents:", toc_str, 15.0),
            EvidenceTextBlock("Final Retrieved Evidence:", summarized_local, 12.0),
            EvidenceTextBlock("Local Agentic Tool Observations:", summarized_tools, 8.0),
        ])
        if previous_results_content:
            blocks.append(EvidenceTextBlock("Previous Results:", previous_results_content, 6.0))
        if follow_up_convo:
            blocks.append(EvidenceTextBlock("Follow-up Context:", follow_up_convo, 6.0))
        for index, link in enumerate(getattr(self, "_reference_links", [])):
            blocks.append(EvidenceTextBlock("Reference URL:", link, 1.0 - (index * 1e-6)))

        evidence_budget = int(self.config.get("final_report_char_budget", 20000))
        stable_instructions = (
            "You are an expert research analyst. Produce a comprehensive, advanced Markdown report "
            "of at least 3000 words using only the supplied NanoSage evidence.\n"
            "The report should include a detailed table of contents, multiple sections, in-depth "
            "analysis with citations, and a final reference section listing relevant URLs.\n"
            "Cover background, current findings, challenges, and future directions. Use section "
            "headings and subheadings. Do not invent evidence or citations.\n"
            "Cite every claim with the source URL given on its own Verified Claim line, or a URL "
            "from the Reference URL list. Those are the only citable sources: a URL that merely "
            "appears inside a page's text is that page's own outbound link and must never be "
            "cited. State plainly where the evidence does not settle a question rather than "
            "filling the gap.\n"
        )
        aggregation_prompt, _ = render_budgeted_prompt(
            stable_instructions,
            blocks,
            evidence_budget,
            evidence_heading="Variable NanoSage evidence follows:",
            suffix="Report:\n",
        )
        print("[DEBUG] Final RAG prompt constructed. Passing to LLM manager...")
        final_answer = self.llm_manager.generate_final_answer(aggregation_prompt)
        self.citation_audit = audit_citations(final_answer, url_by_evidence_id.values())
        off_ledger = self.citation_audit["cited_outside_ledger"]
        if off_ledger:
            print(f"[WARN] Report cited {len(off_ledger)} URL(s) that are not fetched sources: {', '.join(off_ledger[:3])}")
        return final_answer

    def save_report(self, final_answer, previous_results=None, follow_up_convo=None):
        print("[INFO] Saving final report to disk...")
        if not isinstance(final_answer, str) or not final_answer.strip():
            raise ValueError("refusing to save an empty final answer as a report")
        self.save_diagnostics()

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
