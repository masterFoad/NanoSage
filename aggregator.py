# aggregator.py

import os

def aggregate_results(query_id, enhanced_query, web_results, local_results, final_answer, config,
                     grouped_web_results=None, previous_results=None, follow_up_conversation=None):
    """
    Write two markdown reports:
      1) <query_id>_output.md - Overall aggregator info, with final answer at the top.
      2) final_report.md - Contains only the final RAG answer.
    """
    base_dir = config.get("results_base_dir", "results")
    output_dir = os.path.join(base_dir, query_id)
    os.makedirs(output_dir, exist_ok=True)

    # 1) Save only the final answer to final_report.md
    final_report_path = os.path.join(output_dir, "final_report.md")
    with open(final_report_path, "w", encoding="utf-8") as fr:
        fr.write("# Final Aggregated Answer (RAG)\n\n")
        fr.write(final_answer.strip() + "\n")

    # 2) Create the main aggregator file with final RAG answer at the top
    aggregator_path = os.path.join(output_dir, f"{query_id}_output.md")
    with open(aggregator_path, "w", encoding="utf-8") as f:
        f.write(f"# Aggregated Results for Query ID: {query_id}\n\n")

        f.write("## Enhanced Query\n")
        f.write(f"{enhanced_query}\n\n")
        
        
        f.write(f"# Final Aggregated Answer (RAG)\n\n")
        f.write(final_answer.strip() + "\n\n")

        f.write("## Web Search Results\n")
        if web_results:
            for item in web_results:
                f.write(f"- **URL:** {item.get('url', '')}\n")
                f.write(f"  - **Snippet:** {item.get('snippet', '')}\n\n")
        else:
            f.write("_No web results found_\n\n")

        if grouped_web_results:
            f.write("## Grouped Web Results by Domain\n")
            for domain, items in grouped_web_results.items():
                f.write(f"### Domain: {domain}\n")
                for item in items:
                    f.write(f"- **URL:** {item.get('url', '')}\n")
                    f.write(f"  - **File Path:** {item.get('file_path', '')}\n")
                    f.write(f"  - **Content Type:** {item.get('content_type', '')}\n")
                f.write("\n")

        f.write("## Local Retrieval Results\n")
        for doc in local_results:
            meta = doc.get('metadata', {})
            f.write(f"- **File:** {meta.get('file_path', '')}\n")
            if 'page' in meta:
                f.write(f"  - **Page:** {meta.get('page')}\n")
            f.write(f"  - **Snippet:** {meta.get('snippet', '')}\n\n")

        if previous_results:
            f.write("## Previous Results Integrated\n")
            f.write(previous_results.strip() + "\n\n")

        if follow_up_conversation:
            f.write("## Follow-Up Conversation\n")
            f.write(follow_up_conversation.strip() + "\n")

    return aggregator_path
