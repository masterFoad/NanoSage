"""Run the NanoSage query set and write comparable metrics.

Needs network and a live LLM, so this is a script rather than a unittest; the
pure parts it depends on live in `eval.metrics` and are covered offline.

    python eval/run_eval.py --config config.yaml --out eval/results/base.json
    python eval/run_eval.py --config other.yaml --out eval/results/candidate.json
    python eval/run_eval.py --diff eval/results/base.json eval/results/candidate.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import functools
import time
from pathlib import Path
from typing import Mapping

print = functools.partial(print, flush=True)  # progress must not sit in a buffer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.metrics import aggregate_metrics, check_must_mention, compute_run_metrics, diff_results  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_queries(path: Path, limit: int | None = None, names: list[str] | None = None) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    queries = payload.get("queries", [])
    if names:
        wanted = set(names)
        queries = [entry for entry in queries if entry.get("name") in wanted]
    if limit:
        queries = queries[:limit]
    return queries


def _group_is_empty(group: int | None) -> bool:
    """True when no process remains in `group` (signal 0 only probes)."""
    if group is None:
        return True
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _terminate_tree(process: subprocess.Popen) -> None:
    """Kill a query's whole process group, escalating to SIGKILL.

    The leader exiting is not proof the tree died: a descendant that ignores
    SIGTERM survives its parent and can keep the stdout pipe open, so the group
    itself is probed before deciding no SIGKILL is needed.
    """
    try:
        group = os.getpgid(process.pid)
    except (ProcessLookupError, PermissionError, AttributeError):
        group = None
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        try:
            if group is not None:
                os.killpg(group, signal_number)
            else:
                process.send_signal(signal_number)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            continue
        if _group_is_empty(group):
            return
    # Leader is gone but the group still holds survivors; make the last signal count.
    if group is not None and not _group_is_empty(group):
        try:
            os.killpg(group, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


_WARNING_LINE = re.compile(
    r"^\s*(warning|note)\b\s*:"          # "warning: the `fitz` API is deprecated"
    r"|^\s*\S*(Deprecation|User|Future|Runtime|Resource|Syntax)Warning\b"
    r"|\b\w*Warning\s*:",                 # "DeprecationWarning: ..."
    re.IGNORECASE,
)


def _is_warning_line(text: str) -> bool:
    """True for a warning *diagnostic*, not merely a line mentioning the word.

    `RuntimeError: warning budget exceeded` is a real failure and must survive.
    """
    return bool(_WARNING_LINE.search(text))


def _failure_reason(stdout: str, stderr: str) -> str:
    """The line that explains the failure, not merely the last line printed.

    Three things masquerade as the cause of a dead run: NanoSage's own [ERROR]
    line is the real one, an uncaught exception's final line is the next best,
    and library warnings printed afterwards are never it. A `swigvarlink`
    DeprecationWarning and a lowercase `fitz` warning have each been recorded as
    the reason a run died, sending me hunting the wrong bug both times.
    """
    combined = f"{stderr or ''}\n{stdout or ''}".strip().splitlines()
    for line in reversed(combined):
        if "[ERROR]" in line:
            return line.strip()[:300]
    # An uncaught exception: the last line of a traceback is the exception
    # itself, which is what actually explains the exit.
    if any("Traceback (most recent call last)" in line for line in combined):
        for line in reversed(combined):
            text = line.strip()
            if not text or _is_warning_line(text):
                continue
            if text.startswith(("File \"", "Traceback", "^", "~")):
                continue
            if line.startswith((" ", "\t")):  # traceback body, not the exception
                continue
            return text[:300]
    for line in reversed(combined):
        text = line.strip()
        if not text or text.startswith("warnings.warn"):
            continue
        if _is_warning_line(text):
            continue
        return text[:300]
    return "unknown failure"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def collect_artifacts(result_dir: Path, wall_seconds: float) -> dict:
    """Score a run from what it left on disk.

    A failed run writes ledgers but no report, and that distinction is the single
    most important thing the harness reports, so absence is measured rather than
    treated as a missing data point.
    """
    report_path = result_dir / "final_report.md"
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    produced = bool(report_text.strip()) and "Error generating response" not in report_text
    metrics = compute_run_metrics(
        toc=_read_json(result_dir / "toc_analysis.json", {}),
        evidence=_read_json(result_dir / "evidence_ledger.json", []),
        claims=_read_json(result_dir / "claim_ledger.json", {}),
        citation_audit=_read_json(result_dir / "citation_audit.json", {}),
        dropped_sources=_read_json(result_dir / "dropped_sources.json", []),
        coverage=_read_json(result_dir / "coverage_report.json", {}),
        report_words=len(report_text.split()),
        wall_seconds=wall_seconds,
        produced_report=produced,
    )
    return metrics, report_text


# A host suspend shorter than this is measurement noise (scheduler jitter,
# clock discipline); anything longer means the machine actually slept and the
# wall-clock duration is not a measurement of NanoSage.
SUSPEND_TOLERANCE_SECONDS = 60.0


_ATTEMPT_ARTIFACTS = ("final_report.md", "claim_ledger.json", "toc_analysis.json")


def _artifact_fingerprint(results_root: Path) -> dict[str, float]:
    """Modification times of every artifact that could be mistaken for fresh.

    Taken before the query runs. Comparing against this is exact, where a time
    tolerance is not: two attempts seconds apart are indistinguishable by clock
    alone, and a rapid rerun would inherit the previous run's report.
    """
    fingerprint: dict[str, float] = {}
    for directory in results_root.glob("run_*"):
        for name in _ATTEMPT_ARTIFACTS:
            path = directory / name
            try:
                fingerprint[str(path)] = path.stat().st_mtime
            except OSError:
                continue
    return fingerprint


def _artifacts_are_from_this_attempt(result_dir: Path, before: Mapping[str, float]) -> bool:
    """True when this attempt actually wrote the report in `result_dir`.

    Result directories are keyed by query, so a failed rerun lands in the same
    directory a previous SUCCESSFUL run left behind and would otherwise be scored
    with that older report -- a false pass, the most damaging thing an evaluation
    can do. The report must be absent beforehand or have changed since.
    """
    report = result_dir / "final_report.md"
    try:
        current = report.stat().st_mtime
    except OSError:
        return False
    previous = before.get(str(report))
    return previous is None or current != previous


def _stale_companion_artifacts(result_dir: Path, before: Mapping[str, float]) -> list[str]:
    """Artifacts beside a fresh report that this attempt did not rewrite.

    A report can be written while the ledger write fails, leaving metrics that
    describe a different run. Reported rather than silently scored.
    """
    stale = []
    for name in _ATTEMPT_ARTIFACTS[1:]:
        path = result_dir / name
        try:
            current = path.stat().st_mtime
        except OSError:
            continue
        if before.get(str(path)) == current:
            stale.append(name)
    return stale


def _timing_fields(wall: float, active: float, suspended: float) -> dict:
    """Timing for one query, separating elapsed wall clock from time it ran."""
    fields = {
        "wall_seconds": round(wall, 2),
        "active_seconds": round(active, 2),
        "suspended_seconds": round(suspended, 2),
        "host_suspended": suspended > SUSPEND_TOLERANCE_SECONDS,
    }
    if fields["host_suspended"]:
        fields["timing_warning"] = (
            f"host slept ~{suspended / 60:.0f} min during this query; "
            "wall_seconds is not a measurement"
        )
    return fields


def run_one(entry: dict, config: Path, results_root: Path, timeout: int) -> dict:
    name = entry.get("name") or "unnamed"
    query = entry["query"]
    started = time.time()
    started_monotonic = time.monotonic()
    artifacts_before = _artifact_fingerprint(results_root)
    env = dict(os.environ)
    command = [
        sys.executable, "-u", "main.py",
        "--config", str(config),
        "--query", query,
    ]
    failure = ""
    # `subprocess.run(timeout=...)` is not a reliable bound here: one query hung
    # for 6.4 hours inside a provider call that never returned, and the harness
    # waited with it. The child gets its own process group so a timeout can kill
    # the whole tree, and SIGKILL follows SIGTERM for anything that ignores it.
    stdout, stderr = "", ""
    process = subprocess.Popen(
        command, cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        exit_code = process.returncode
        if exit_code != 0:
            failure = _failure_reason(stdout, stderr)
    except subprocess.TimeoutExpired:
        _terminate_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        exit_code = -1
        failure = f"timed out after {timeout}s (killed)"
    wall = time.time() - started
    # On macOS `time.monotonic()` is mach_absolute_time(), which does not advance
    # while the machine is asleep -- and neither do the timeouts built on it. A
    # query once recorded 6.4 hours of wall clock because the Mac hibernated
    # mid-run, so the two clocks disagreeing is how we detect a suspended host
    # rather than a slow query.
    active = time.monotonic() - started_monotonic
    suspended = max(0.0, wall - active)

    result_dir = None
    for line in reversed(stdout.splitlines()):
        if "Final report saved to:" in line or "TOC analysis saved to:" in line:
            result_dir = Path(line.split(": ", 1)[1].strip()).parent
            break
    if result_dir is None:
        # The child announces its own identity at startup, so a crash after
        # initialization still tells us exactly which directory is OURS. This is
        # true attempt ownership -- no globbing can confuse it with a directory
        # another process wrote while we ran.
        match = re.search(r"query_id=(run_[0-9a-f]+(?:-[0-9A-Za-z]+)*)", stdout)
        if match:
            result_dir = results_root / match.group(1)
    # Run directories are unique per run now, but an explicit query_id in the
    # config still reuses one. Directory identity therefore proves nothing; what
    # matters is whether the ARTIFACTS inside it were written by this attempt.
    if result_dir is not None and not _artifacts_are_from_this_attempt(result_dir, artifacts_before):
        result_dir = None
        failure = failure or "result directory holds artifacts from an earlier attempt"
    if result_dir is None:
        # The fallback must apply the SAME freshness proof as the parsed path.
        # A directory whose mtime moved because this attempt dropped a log file
        # into it still holds the previous attempt's report, so recent
        # modification is not evidence that the report belongs to this run.
        candidates = [
            path for path in results_root.glob("run_*")
            if _artifacts_are_from_this_attempt(path, artifacts_before)
        ]
        candidates.sort(key=lambda path: (path / "final_report.md").stat().st_mtime)
        result_dir = candidates[-1] if candidates else None

    record = {"name": name, "type": entry.get("type", ""), "query": query, "exit_code": exit_code}
    if result_dir is None or not result_dir.exists():
        record.update(compute_run_metrics(wall_seconds=wall, produced_report=False))
        record.update(_timing_fields(wall, active, suspended))
        record["failure"] = failure or "no result directory"
        return record
    stale_companions = _stale_companion_artifacts(result_dir, artifacts_before)
    metrics, report_text = collect_artifacts(result_dir, wall)
    record.update(metrics)
    if stale_companions:
        record["stale_artifacts"] = stale_companions
        failure = failure or (
            "report is fresh but " + ", ".join(stale_companions) + " was not rewritten"
        )
    record.update(_timing_fields(wall, active, suspended))
    record.update(check_must_mention(report_text, entry.get("must_mention", [])))
    record["result_dir"] = str(result_dir)
    if failure:
        record["failure"] = failure
    return record


def _hold_wake_assertion():
    """Keep macOS awake for the run, so timings measure NanoSage and not sleep.

    `caffeinate -w <pid>` exits on its own when we do, so there is nothing to
    clean up if the harness is killed. This blocks idle and disk sleep; closing
    the lid still sleeps the machine, which is why the suspend detector above
    stays in place rather than being replaced by this.
    """
    if sys.platform != "darwin":
        return None
    try:
        return subprocess.Popen(
            ["caffeinate", "-i", "-s", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, FileNotFoundError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NanoSage evaluation query set.")
    parser.add_argument("--config", default="config.yaml", help="NanoSage config to evaluate")
    parser.add_argument("--queries", default=str(Path(__file__).parent / "queries.json"))
    parser.add_argument("--out", default=None, help="Where to write the result JSON")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N queries")
    parser.add_argument("--name", action="append", default=None, help="Run only these query names")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-query timeout in seconds")
    parser.add_argument("--diff", nargs=2, metavar=("BASELINE", "CANDIDATE"), default=None)
    args = parser.parse_args()

    if args.diff:
        baseline = json.loads(Path(args.diff[0]).read_text(encoding="utf-8"))
        candidate = json.loads(Path(args.diff[1]).read_text(encoding="utf-8"))
        report = diff_results(baseline.get("aggregate", {}), candidate.get("aggregate", {}))
        print(json.dumps(report, indent=2))
        print(f"\nimproved: {', '.join(report['improved']) or 'none'}")
        print(f"regressed: {', '.join(report['regressed']) or 'none'}")
        return 0

    config = Path(args.config)
    if not config.is_absolute():
        config = (REPO_ROOT / config).resolve()
    import yaml
    results_root = Path(yaml.safe_load(config.read_text(encoding="utf-8")).get("results_base_dir", "results"))
    if not results_root.is_absolute():
        results_root = (REPO_ROOT / results_root).resolve()

    queries = load_queries(Path(args.queries), args.limit, args.name)
    keep_awake = _hold_wake_assertion()
    print(f"[INFO] Evaluating {len(queries)} queries with config {config}"
          + (" (holding wake assertion)" if keep_awake else ""))
    records = []
    for index, entry in enumerate(queries, start=1):
        print(f"[INFO] ({index}/{len(queries)}) {entry.get('name')}")
        record = run_one(entry, config, results_root, args.timeout)
        records.append(record)
        print(
            f"       report={'yes' if record.get('produced_report') else 'NO'} "
            f"claims={record.get('verified_claims', 0)} "
            f"primitives={record.get('verified_primitives', 0)} "
            f"sources={record.get('sources_fetched', 0)} "
            f"coverage={record.get('chunk_coverage_ratio', 0)} "
            f"{record.get('wall_seconds', 0)}s"
            + (f" FAILURE: {record['failure']}" if record.get("failure") else "")
            + (f" [{record['timing_warning']}]" if record.get("timing_warning") else "")
        )

    payload = {"config": str(config), "queries": records, "aggregate": aggregate_metrics(records)}
    out = Path(args.out) if args.out else REPO_ROOT / "eval" / "results" / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n[INFO] Results written to {out}")

    aggregate = payload["aggregate"]
    print(f"[INFO] reports produced: {aggregate['reports_produced']}/{len(records)}")
    suspended = [r["name"] for r in records if r.get("host_suspended")]
    if suspended:
        # Say this loudly: a suspended query's duration is an artifact of the
        # machine, and silently averaging it in would corrupt every timing stat.
        print(f"[WARN] host slept during {len(suspended)} quer(y/ies): {', '.join(suspended)}")
        print("[WARN] their wall_seconds are not measurements -- re-run them")
    for key in ("verified_claims", "verified_primitives", "verified_evidence",
                "chunk_coverage_ratio", "starved_branch_ratio", "source_citation_ratio",
                "citations_outside_ledger", "claims_per_llm_call", "evidence_per_llm_call"):
        stats = aggregate.get(key)
        if stats:
            print(f"[INFO] {key}: mean={stats['mean']} median={stats['median']} min={stats['min']} max={stats['max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
