#!/usr/bin/env python3
"""Render a NanoSage run directory as a standalone local HTML dashboard."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def latest_run(workspace: Path) -> Path:
    results = workspace / "results"
    if not results.is_dir():
        raise SystemExit(f"No results directory found under {workspace}")
    runs = [path for path in results.iterdir() if path.is_dir()]
    if not runs:
        raise SystemExit(f"No run directories found under {results}")
    return max(runs, key=lambda path: path.stat().st_mtime)


def score_bar(score: float) -> str:
    pct = max(0, min(100, int(round(float(score or 0) * 100))))
    return f'<div class="bar"><span style="width:{pct}%"></span></div><b>{pct}%</b>'


def render_tool_results(tool_results: list[dict]) -> str:
    if not tool_results:
        return "<p>No tool results found.</p>"
    cards = []
    for item in sorted(tool_results, key=lambda row: row.get("score", 0), reverse=True):
        content = html.escape((item.get("content") or "")[:4000])
        args = html.escape(json.dumps(item.get("args") or {}, indent=2))
        metadata = html.escape(json.dumps(item.get("metadata") or {}, indent=2))
        cards.append(f"""
        <article class="card">
          <header><h3>{html.escape(item.get('name', 'tool'))}</h3>{score_bar(item.get('score', 0))}</header>
          <p><b>Status:</b> {html.escape(str(item.get('ok')))} &nbsp; <b>ID:</b> <code>{html.escape(item.get('evidence_id', ''))}</code></p>
          <p>{html.escape(item.get('summary', ''))}</p>
          <details><summary>Arguments</summary><pre>{args}</pre></details>
          <details open><summary>Content preview</summary><pre>{content}</pre></details>
          <details><summary>Metadata</summary><pre>{metadata}</pre></details>
        </article>
        """)
    return "\n".join(cards)


def render_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return "<p>No evidence ledger found for this run.</p>"
    rows = []
    for item in evidence:
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(item.get('evidence_id', ''))}</code></td>"
            f"<td>{html.escape(item.get('branch_query', ''))}</td>"
            f"<td>{html.escape(item.get('source_engine', ''))}</td>"
            f"<td><a href='{html.escape(item.get('url', ''))}'>{html.escape(item.get('title') or item.get('url', ''))}</a></td>"
            f"<td>{html.escape((item.get('snippet') or '')[:240])}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>ID</th><th>Branch</th><th>Source</th><th>URL</th><th>Snippet</th></tr></thead><tbody>" + "\n".join(rows) + "</tbody></table>"


def render_toc(toc: dict) -> str:
    nodes = toc.get("toc_tree", []) if isinstance(toc, dict) else []
    analytics = toc.get("analytics", {}) if isinstance(toc, dict) else {}
    if not nodes and not analytics:
        return "<p>No TOC analysis found for this run.</p>"

    def node_html(node: dict) -> str:
        children = "".join(node_html(child) for child in node.get("children", []))
        metrics = node.get("metrics", {})
        return f"""
        <li>
          <b>{html.escape(node.get('query_text', ''))}</b>
          <span class="pill">relevance {float(node.get('relevance_score') or 0):.3f}</span>
          <span class="pill">priority {float(metrics.get('branch_priority') or 0):.3f}</span>
          <span class="pill">novelty {float(metrics.get('branch_novelty') or 0):.3f}</span>
          <p>{html.escape((node.get('summary') or '')[:500])}</p>
          <ul>{children}</ul>
        </li>
        """

    analytics_html = html.escape(json.dumps(analytics, indent=2))
    tree_html = "<ul>" + "".join(node_html(node) for node in nodes) + "</ul>"
    return f"<details><summary>Analytics JSON</summary><pre>{analytics_html}</pre></details>{tree_html}"


def render_agent_trace(trace: dict) -> str:
    if not trace:
        return "<p>No agent trace found for this run.</p>"
    rounds = trace.get("rounds", [])
    parts = [
        f"<p><b>Stop reason:</b> <code>{html.escape(str(trace.get('stop_reason', '')))}</code> "
        f"<b>Calls:</b> {html.escape(str(trace.get('calls_used', 0)))} / {html.escape(str(trace.get('max_calls', 0)))}</p>"
    ]
    for agent_round in rounds:
        observations = "".join(f"<li>{html.escape(obs)}</li>" for obs in agent_round.get("observations", []))
        requests = html.escape(json.dumps(agent_round.get("requests", []), indent=2))
        parts.append(
            f"<article class='card'><h3>Round {html.escape(str(agent_round.get('round_index')))}</h3>"
            f"<ul>{observations}</ul><details><summary>Requests</summary><pre>{requests}</pre></details></article>"
        )
    return "\n".join(parts)


def render(workspace: Path, run_dir: Path, output: Path) -> Path:
    tool_results = load_json(run_dir / "tool_results.json", [])
    agent_trace = load_json(run_dir / "agent_trace.json", {})
    evidence = load_json(run_dir / "evidence_ledger.json", [])
    toc = load_json(run_dir / "toc_analysis.json", {})
    report_path = next(run_dir.glob("*_output.md"), None)
    report_preview = html.escape(report_path.read_text(encoding="utf-8", errors="replace")[:5000]) if report_path else ""

    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>NanoSage Run Dashboard - {html.escape(run_dir.name)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0b1020; color: #e8ecff; }}
    a {{ color: #8bd5ff; }}
    code, pre {{ background: #151b31; color: #d9e2ff; border-radius: 8px; }}
    pre {{ padding: 1rem; overflow-x: auto; white-space: pre-wrap; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; }}
    .card {{ background: #10162a; border: 1px solid #273253; border-radius: 14px; padding: 1rem; }}
    .card header {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem; }}
    .bar {{ width: 120px; height: 10px; background: #273253; border-radius: 999px; overflow: hidden; display: inline-block; margin-right: .5rem; }}
    .bar span {{ display: block; height: 100%; background: linear-gradient(90deg, #6ee7b7, #60a5fa); }}
    .pill {{ display: inline-block; padding: .15rem .45rem; margin: .15rem; background: #24304f; border-radius: 999px; font-size: .85rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #273253; padding: .5rem; vertical-align: top; }}
    section {{ margin: 2rem 0; }}
  </style>
</head>
<body>
  <h1>NanoSage Run Dashboard</h1>
  <p><b>Workspace:</b> <code>{html.escape(str(workspace))}</code></p>
  <p><b>Run:</b> <code>{html.escape(str(run_dir))}</code></p>

  <section>
    <h2>Scored Local Tool Results</h2>
    <div class="grid">{render_tool_results(tool_results)}</div>
  </section>

  <section>
    <h2>Agent Trace</h2>
    {render_agent_trace(agent_trace)}
  </section>

  <section>
    <h2>Evidence Ledger</h2>
    {render_evidence(evidence)}
  </section>

  <section>
    <h2>Search / TOC Tree</h2>
    {render_toc(toc)}
  </section>

  <section>
    <h2>Report Preview</h2>
    <pre>{report_preview}</pre>
  </section>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(doc, encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a NanoSage run dashboard as standalone HTML.")
    parser.add_argument("--workspace", default=".", help="Workspace containing results/ (default: current directory)")
    parser.add_argument("--run", default="latest", help="Run id under results/, a run path, or 'latest'")
    parser.add_argument("--output", default=None, help="HTML output path (default: <run>/dashboard.html)")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if args.run == "latest":
        run_dir = latest_run(workspace)
    else:
        candidate = Path(args.run)
        run_dir = candidate.resolve() if candidate.exists() else (workspace / "results" / args.run).resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"Run directory not found: {run_dir}")
    output = Path(args.output).resolve() if args.output else run_dir / "dashboard.html"
    path = render(workspace, run_dir, output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
