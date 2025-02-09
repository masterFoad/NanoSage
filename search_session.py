# search_session.py

import os
import uuid
import asyncio
import time
import re
import random
import yaml

from knowledge_base import KnowledgeBase, late_interaction_score, load_corpus_from_dir, load_retrieval_model, embed_text
from web_search import download_webpages_ddg, parse_html_to_text, group_web_results_by_domain, sanitize_filename
from aggregator import aggregate_results

#############################################
# LLM (Gemma) & Summarization / RAG utilities
#############################################

from ollama import chat, ChatResponse

def call_gemma(prompt, model="gemma2:2b", personality=None):
    system_message = ""
    if personality:
        system_message = f"You are a {personality} assistant.\n\n"
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})
    response: ChatResponse = chat(model=model, messages=messages)
    return response.message.content

def extract_final_query(text):
    marker = "Final Enhanced Query:"
    if marker in text:
        return text.split(marker)[-1].strip()
    return text.strip()

def chain_of_thought_query_enhancement(query, personality=None):
    prompt = (
        "You are an expert search strategist. Think step-by-step through the implications and nuances "
        "of the following query and produce a final, enhanced query that covers more angles.\n\n"
        f"Query: \"{query}\"\n\n"
        "After your reasoning, output only the final enhanced query on a single line - SHORT AND CONCISE.\n"
        "Provide your reasoning, and at the end output the line 'Final Enhanced Query:' followed by the enhanced query."
    )
    raw_output = call_gemma(prompt, personality=personality)
    return extract_final_query(raw_output)

def summarize_text(text, max_chars=6000, personality=None):
    if len(text) <= max_chars:
        prompt = f"Please summarize the following text succinctly:\n\n{text}"
        return call_gemma(prompt, personality=personality)
    # If text is longer than max_chars, chunk it
    chunks = [text[i:i+max_chars] for i in range(0, len(text), max_chars)]
    summaries = []
    for i, chunk in enumerate(chunks):
        prompt = f"Summarize part {i+1}/{len(chunks)}:\n\n{chunk}"
        summary = call_gemma(prompt, personality=personality)
        summaries.append(summary)
        time.sleep(1)
    combined = "\n".join(summaries)
    if len(combined) > max_chars:
        prompt = f"Combine these summaries into one concise summary:\n\n{combined}"
        combined = call_gemma(prompt, personality=personality)
    return combined

def rag_final_answer(aggregation_prompt, rag_model="gemma", personality=None):
    print("[INFO] Performing final RAG generation using model:", rag_model)
    if rag_model == "gemma":
        return call_gemma(aggregation_prompt, personality=personality)
    elif rag_model == "pali":
        modified_prompt = f"PALI mode analysis:\n\n{aggregation_prompt}"
        return call_gemma(modified_prompt, personality=personality)
    else:
        return call_gemma(aggregation_prompt, personality=personality)

def follow_up_conversation(follow_up_prompt, personality=None):
    return call_gemma(follow_up_prompt, personality=personality)

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

    def add_child(self, child_node):
        self.children.append(child_node)

    def __repr__(self):
        return f"TOCNode(query_text='{self.query_text}', depth={self.depth}, relevance_score={self.relevance_score:.2f}, children={len(self.children)})"

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

#########################################################
# The "SearchSession" class: orchestrate the entire pipeline,
# including optional Monte Carlo subquery sampling, recursive web search,
# TOC tracking, and relevance scoring.
#########################################################

class SearchSession:
    def __init__(self, query, config, corpus_dir=None, device="cpu",
                 retrieval_model="colpali", top_k=3, web_search_enabled=False,
                 personality=None, rag_model="gemma", max_depth=1):
        """
        :param max_depth: Maximum recursion depth for subquery expansion.
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

        self.query_id = str(uuid.uuid4())[:8]
        self.base_result_dir = os.path.join(self.config.get("results_base_dir", "results"), self.query_id)
        os.makedirs(self.base_result_dir, exist_ok=True)

        print(f"[INFO] Initializing SearchSession for query_id={self.query_id}")

        # Enhance the query via chain-of-thought.
        self.enhanced_query = chain_of_thought_query_enhancement(self.query, personality=self.personality)
        if not self.enhanced_query:
            self.enhanced_query = self.query

        # Load retrieval model.
        self.model, self.processor, self.model_type = load_retrieval_model(
            model_choice=self.retrieval_model,
            device=self.device
        )

        # Compute the overall enhanced query embedding once.
        print("[INFO] Computing embedding for enhanced query...")
        self.enhanced_query_embedding = embed_text(self.enhanced_query, self.model, self.processor, self.model_type, self.device)

        # Create a knowledge base.
        print("[INFO] Creating KnowledgeBase...")
        self.kb = KnowledgeBase(self.model, self.processor, model_type=self.model_type, device=self.device)

        # Load local corpus if available.
        self.corpus = []
        if self.corpus_dir:
            print(f"[INFO] Loading local documents from {self.corpus_dir}")
            local_docs = load_corpus_from_dir(self.corpus_dir, self.model, self.processor, self.device, self.model_type)
            self.corpus.extend(local_docs)
        self.kb.add_documents(self.corpus)

        # Placeholders for web search results and TOC tree.
        self.web_results = []
        self.grouped_web_results = {}
        self.local_results = []
        self.toc_tree = []  # List of TOCNode objects for the initial subqueries

    async def run_session(self):
        """
        Main entry point: perform recursive web search (if enabled) and then local retrieval.
        """
        print(f"[INFO] Starting session with query_id={self.query_id}, max_depth={self.max_depth}")
        plain_enhanced_query = clean_search_query(self.enhanced_query)

        # 1) Generate subqueries from the enhanced query
        initial_subqueries = split_query(plain_enhanced_query, max_len=self.config.get("max_query_length", 200))
        print(f"[INFO] Generated {len(initial_subqueries)} initial subqueries from the enhanced query.")

        # 2) Optionally do a Monte Carlo approach to sample subqueries
        if self.config.get("monte_carlo_search", True):
            print("[INFO] Using Monte Carlo approach to sample subqueries.")
            initial_subqueries = self.perform_monte_carlo_subqueries(plain_enhanced_query, initial_subqueries)

        # 3) If web search is enabled and max_depth >= 1, do the recursive expansion
        if self.web_search_enabled and self.max_depth >= 1:
            web_results, web_entries, grouped, toc_nodes = await self.perform_recursive_web_searches(initial_subqueries, current_depth=1)
            self.web_results = web_results
            self.grouped_web_results = grouped
            self.toc_tree = toc_nodes
            # Add new entries to the knowledge base
            self.corpus.extend(web_entries)
            self.kb.add_documents(web_entries)
        else:
            print("[INFO] Web search is disabled or max_depth < 1, skipping web expansion.")

        # 4) Local retrieval
        print(f"[INFO] Retrieving top {self.top_k} local documents for final answer.")
        self.local_results = self.kb.search(self.enhanced_query, top_k=self.top_k)

        # 5) Summaries and final RAG generation
        summarized_web = self._summarize_web_results(self.web_results)
        summarized_local = self._summarize_local_results(self.local_results)
        final_answer = self._build_final_answer(summarized_web, summarized_local)
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
        for sq in subqueries:
            sq_clean = clean_search_query(sq)
            if not sq_clean:
                continue
            node_emb = embed_text(sq_clean, self.model, self.processor, self.model_type, self.device)
            score = late_interaction_score(self.enhanced_query_embedding, node_emb)
            scored_subqs.append((sq_clean, score))

        if not scored_subqs:
            print("[WARN] No valid subqueries found for Monte Carlo. Returning original list.")
            return subqueries

        # Weighted random choice
        chosen = random.choices(
            population=scored_subqs,
            weights=[s for (_, s) in scored_subqs],
            k=min(max_subqs, len(scored_subqs))
        )
        # Return just the chosen subqueries
        chosen_sqs = [ch[0] for ch in chosen]
        print(f"[DEBUG] Monte Carlo selected: {chosen_sqs}")
        return chosen_sqs

    async def perform_recursive_web_searches(self, subqueries, current_depth=1):
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

            # Create a TOC node
            toc_node = TOCNode(query_text=sq_clean, depth=current_depth)
            # Relevance
            node_embedding = embed_text(sq_clean, self.model, self.processor, self.model_type, self.device)
            relevance = late_interaction_score(self.enhanced_query_embedding, node_embedding)
            toc_node.relevance_score = relevance

            if relevance < min_relevance:
                print(f"[INFO] Skipping branch '{sq_clean}' due to low relevance ({relevance:.2f} < {min_relevance}).")
                continue

            # Create subdirectory
            safe_subquery = sanitize_filename(sq_clean)[:30]
            subquery_dir = os.path.join(self.base_result_dir, f"web_{safe_subquery}")
            os.makedirs(subquery_dir, exist_ok=True)
            print(f"[DEBUG] Searching web for subquery '{sq_clean}' at depth={current_depth}...")

            pages = await download_webpages_ddg(sq_clean, limit=self.config.get("web_search_limit", 5), output_dir=subquery_dir)
            branch_web_results = []
            branch_corpus_entries = []
            for page in pages:
                if not page:
                    continue
                file_path = page.get("file_path")
                url = page.get("url")
                if not file_path or not url:
                    continue
                raw_text = parse_html_to_text(file_path)
                if not raw_text.strip():
                    continue
                snippet = raw_text[:100].replace('\n', ' ') + "..."
                limited_text = raw_text[:2048]
                try:
                    if self.model_type == "colpali":
                        inputs = self.processor(text=[limited_text], truncation=True, max_length=512, return_tensors="pt").to(self.device)
                        outputs = self.model(**inputs)
                        emb = outputs.embeddings.mean(dim=1).squeeze(0)
                    else:
                        emb = self.model.encode(limited_text, convert_to_tensor=True)
                    entry = {
                        "embedding": emb,
                        "metadata": {
                            "file_path": file_path,
                            "type": "webhtml",
                            "snippet": snippet,
                            "url": url
                        }
                    }
                    branch_corpus_entries.append(entry)
                    branch_web_results.append({"url": url, "snippet": snippet})
                except Exception as e:
                    print(f"[WARN] Error embedding page '{url}': {e}")

            # Summarize
            branch_snippets = " ".join([r.get("snippet", "") for r in branch_web_results])
            toc_node.summary = summarize_text(branch_snippets, personality=self.personality)
            toc_node.web_results = branch_web_results
            toc_node.corpus_entries = branch_corpus_entries

            additional_subqueries = []
            if current_depth < self.max_depth:
                additional_query = chain_of_thought_query_enhancement(sq_clean, personality=self.personality)
                if additional_query and additional_query != sq_clean:
                    additional_subqueries = split_query(additional_query, max_len=self.config.get("max_query_length", 200))

            if additional_subqueries:
                deeper_web_results, deeper_corpus_entries, _, deeper_toc_nodes = await self.perform_recursive_web_searches(additional_subqueries, current_depth=current_depth+1)
                branch_web_results.extend(deeper_web_results)
                branch_corpus_entries.extend(deeper_corpus_entries)
                for child_node in deeper_toc_nodes:
                    toc_node.add_child(child_node)

            aggregated_web_results.extend(branch_web_results)
            aggregated_corpus_entries.extend(branch_corpus_entries)
            toc_nodes.append(toc_node)

        grouped = group_web_results_by_domain(
            [{"url": r["url"], "file_path": e["metadata"]["file_path"], "content_type": e["metadata"].get("content_type", "")}
             for r, e in zip(aggregated_web_results, aggregated_corpus_entries)]
        )
        return aggregated_web_results, aggregated_corpus_entries, grouped, toc_nodes

    def _summarize_web_results(self, web_results):
        lines = []
        reference_urls = []
        for w in web_results:
            url = w.get('url')
            snippet = w.get('snippet')
            lines.append(f"URL: {url} - snippet: {snippet}")
            reference_urls.append(url)
        text = "\n".join(lines)
        # We'll store reference URLs in self._reference_links for final prompt
        self._reference_links = list(set(reference_urls))  # unique
        return summarize_text(text, personality=self.personality)

    def _summarize_local_results(self, local_results):
        lines = []
        for doc in local_results:
            meta = doc.get('metadata', {})
            file_path = meta.get('file_path')
            snippet = meta.get('snippet', '')
            lines.append(f"File: {file_path} snippet: {snippet}")
        text = "\n".join(lines)
        return summarize_text(text, personality=self.personality)

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
        print("[DEBUG] Final RAG prompt constructed. Passing to rag_final_answer()...")
        final_answer = rag_final_answer(aggregation_prompt, rag_model=self.rag_model, personality=self.personality)
        return final_answer

    def save_report(self, final_answer, previous_results=None, follow_up_convo=None):
        print("[INFO] Saving final report to disk...")
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
