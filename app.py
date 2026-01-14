# app.py

import asyncio
import os
import yaml
import streamlit as st

from search_session import SearchSession


def load_config(config_path: str):
    if not config_path or not os.path.isfile(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_search_session(
    query: str,
    config: dict,
    corpus_dir: str,
    device: str,
    retrieval_model: str,
    top_k: int,
    web_search_enabled: bool,
    personality: str,
    rag_model: str,
    max_depth: int,
    llm_provider: str,
    llm_model: str,
    faiss_index_path: str,
    faiss_meta_path: str,
    faiss_root_dir: str,
):
    session = SearchSession(
        query=query,
        config=config,
        corpus_dir=corpus_dir or None,
        device=device,
        retrieval_model=retrieval_model,
        top_k=top_k,
        web_search_enabled=web_search_enabled,
        personality=personality or None,
        rag_model=rag_model,
        max_depth=max_depth,
        llm_provider=llm_provider,
        llm_model=llm_model or None,
        faiss_index_path=faiss_index_path or None,
        faiss_meta_path=faiss_meta_path or None,
        faiss_root_dir=faiss_root_dir or None,
    )
    final_answer = asyncio.run(session.run_session())
    output_path = session.save_report(final_answer)
    return final_answer, output_path


st.set_page_config(page_title="NanoSage UI", layout="wide")
st.title("NanoSage UI")

with st.sidebar:
    st.header("Configuration")
    config_path = st.text_input("Config path", value="config.yaml")
    device = st.selectbox("Device", ["cpu", "cuda"], index=0)
    retrieval_model = st.selectbox(
        "Retrieval model",
        ["colpali", "all-minilm", "siglip", "clip"],
        index=1,
    )
    top_k = st.number_input("Top K", min_value=1, max_value=20, value=3, step=1)
    web_search_enabled = st.checkbox("Enable web search", value=False)
    personality = st.text_input("Personality (optional)")
    rag_model = st.text_input("RAG model", value="gemma")
    max_depth = st.number_input("Max depth", min_value=0, max_value=5, value=1, step=1)
    llm_provider = st.selectbox("LLM provider", ["ollama", "openai", "anthropic"], index=0)
    llm_model = st.text_input("LLM model (optional)")

st.subheader("Query")
query = st.text_area("Enter your question", height=120)

st.subheader("Local Data Sources")
corpus_dir = st.text_input("Corpus folder (optional)")
faiss_root_dir = st.text_input("FAISS root folder (optional)")
faiss_index_path = st.text_input("FAISS index path (optional)")
faiss_meta_path = st.text_input("FAISS meta.jsonl path (optional)")

run_button = st.button("Run Search")

if run_button:
    if not query.strip():
        st.error("Please enter a query.")
    elif faiss_root_dir and (faiss_index_path or faiss_meta_path):
        st.error("Provide either a FAISS root folder or a single FAISS index/meta pair, not both.")
    elif (faiss_index_path and not faiss_meta_path) or (faiss_meta_path and not faiss_index_path):
        st.error("Provide both FAISS index and metadata paths together.")
    else:
        try:
            config = load_config(config_path)
            if web_search_enabled:
                config.update({
                    "web_concurrency": config.get("web_concurrency", 8),
                    "include_wikipedia": config.get("include_wikipedia", False),
                })
            with st.spinner("Running search..."):
                answer, output_path = run_search_session(
                    query=query.strip(),
                    config=config,
                    corpus_dir=corpus_dir,
                    device=device,
                    retrieval_model=retrieval_model,
                    top_k=top_k,
                    web_search_enabled=web_search_enabled,
                    personality=personality,
                    rag_model=rag_model,
                    max_depth=max_depth,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    faiss_index_path=faiss_index_path,
                    faiss_meta_path=faiss_meta_path,
                    faiss_root_dir=faiss_root_dir,
                )
            st.success(f"Report saved to: {output_path}")
            st.markdown("### Final Answer")
            st.write(answer)
        except Exception as exc:
            st.error(f"Error: {exc}")
