"""Scored local tools for NanoSage's agentic evidence policy."""

from __future__ import annotations

import os
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from evidence import lexical_similarity, stable_id, tokenize
from path_utils import safe_resolve_under


SKIP_DIRS = {".git", "__pycache__", ".audit-runs", "results", "downloaded_webpages", ".pytest_cache"}
TEXT_EXTENSIONS = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}


@dataclass(frozen=True)
class ToolRequest:
    name: str
    args: dict[str, Any]
    reason: str = ""

    def key(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        return self.name, tuple(sorted((str(key), str(value)) for key, value in self.args.items()))


@dataclass(frozen=True)
class ToolResult:
    name: str
    args: dict[str, Any]
    ok: bool
    score: float
    summary: str
    content: str = ""
    evidence_id: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return data


@dataclass
class AgentRound:
    round_index: int
    requests: list[ToolRequest] = field(default_factory=list)
    results: list[ToolResult] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "requests": [asdict(request) for request in self.requests],
            "results": [result.to_dict() for result in self.results],
            "observations": self.observations,
        }


@dataclass
class AgentMemory:
    query: str
    workspace: Path
    max_rounds: int
    max_calls: int
    min_score: float
    executed_keys: set[tuple[str, tuple[tuple[str, str], ...]]] = field(default_factory=set)
    rounds: list[AgentRound] = field(default_factory=list)
    results: list[ToolResult] = field(default_factory=list)
    stop_reason: str = "not_started"

    @property
    def calls_used(self) -> int:
        return len(self.results)

    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self.calls_used)

    def add_round(self, agent_round: AgentRound) -> None:
        self.rounds.append(agent_round)
        self.results.extend(agent_round.results)
        for request in agent_round.requests:
            self.executed_keys.add(request.key())

    def to_trace(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "workspace": str(self.workspace),
            "max_rounds": self.max_rounds,
            "max_calls": self.max_calls,
            "min_score": self.min_score,
            "calls_used": self.calls_used,
            "stop_reason": self.stop_reason,
            "rounds": [agent_round.to_dict() for agent_round in self.rounds],
            "results": [result.to_dict() for result in sorted(self.results, key=lambda item: item.score, reverse=True)],
        }


class ScoredTool(ABC):
    name: str
    description: str

    @abstractmethod
    def execute(self, workspace: Path, request: ToolRequest, query: str) -> ToolResult:
        """Execute a bounded read-only tool call."""

    def score_text(self, query: str, text: str, *, base: float = 0.2) -> float:
        if not text.strip():
            return 0.0
        query_tokens = " ".join(sorted(tokenize(query)))
        score = lexical_similarity(query_tokens, text[:4000])
        return min(1.0, base + score)

    def result(self, request: ToolRequest, ok: bool, score: float, summary: str, content: str = "", **metadata: Any) -> ToolResult:
        evidence_id = stable_id(self.name, request.args, content[:500], prefix="tool")
        return ToolResult(
            name=self.name,
            args=request.args,
            ok=ok,
            score=round(max(0.0, min(1.0, score)), 6),
            summary=summary,
            content=content,
            evidence_id=evidence_id,
            metadata=metadata,
        )


class ReadFileLinesTool(ScoredTool):
    name = "read_file_lines"
    description = "Read a bounded line range from a workspace file."

    def execute(self, workspace: Path, request: ToolRequest, query: str) -> ToolResult:
        rel_path = request.args.get("path", "")
        start = max(1, int(request.args.get("start", 1)))
        max_lines = max(1, min(int(request.args.get("max_lines", 120)), 300))
        end = request.args.get("end")
        end = min(int(end), start + max_lines - 1) if end is not None else start + max_lines - 1
        try:
            path = safe_resolve_under(workspace, rel_path)
            if not path.is_file():
                return self.result(request, False, 0.0, f"File not found: {rel_path}", path=str(path))
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[start - 1:end]
            numbered = "\n".join(f"{idx}: {line}" for idx, line in enumerate(selected, start=start))
            score = self.score_text(query, numbered, base=0.25)
            return self.result(request, True, score, f"Read {len(selected)} lines from {rel_path}", numbered, path=str(path), start=start, end=end)
        except Exception as exc:
            return self.result(request, False, 0.0, f"read_file_lines failed: {exc}")


class GrepTool(ScoredTool):
    name = "grep"
    description = "Search workspace text files for a regex pattern with bounded results."

    def execute(self, workspace: Path, request: ToolRequest, query: str) -> ToolResult:
        pattern = request.args.get("pattern", "")
        rel_path = request.args.get("path", ".")
        max_matches = max(1, min(int(request.args.get("max_matches", 50)), 200))
        if not pattern:
            return self.result(request, False, 0.0, "grep pattern is empty")
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return self.result(request, False, 0.0, f"invalid grep regex: {exc}")
        matches: list[str] = []
        root = None
        try:
            root = safe_resolve_under(workspace, rel_path)
            # Report paths relative to the *resolved* workspace. safe_resolve_under resolves
            # symlinks (on macOS /var -> /private/var), so relative_to(workspace) would raise
            # for an unresolved workspace argument.
            display_base = Path(workspace).expanduser().resolve()
            files = [root] if root.is_file() else self._iter_text_files(root)
            for path in files:
                try:
                    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                        if regex.search(line):
                            matches.append(f"{path.relative_to(display_base)}:{lineno}: {line[:220]}")
                            if len(matches) >= max_matches:
                                raise StopIteration
                except UnicodeDecodeError:
                    continue
                except StopIteration:
                    raise
            content = "\n".join(matches)
            score = min(1.0, 0.25 + (len(matches) / max_matches) * 0.45 + self.score_text(query, content, base=0.0))
            return self.result(request, True, score, f"Found {len(matches)} matches for /{pattern}/", content, pattern=pattern, path=str(root))
        except StopIteration:
            content = "\n".join(matches)
            return self.result(request, True, 1.0, f"Found at least {len(matches)} matches for /{pattern}/", content, pattern=pattern, path=str(root))
        except Exception as exc:
            return self.result(request, False, 0.0, f"grep failed: {exc}")

    def _iter_text_files(self, root: Path) -> Iterable[Path]:
        if not root.exists():
            return []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.suffix.lower() in TEXT_EXTENSIONS:
                    yield path


class GitExploreTool(ScoredTool):
    name = "git_explore"
    description = "Run read-only git exploration: status, recent log, tracked files, or show."

    def execute(self, workspace: Path, request: ToolRequest, query: str) -> ToolResult:
        mode = request.args.get("mode", "status")
        try:
            if mode == "status":
                cmd = ["git", "status", "--short", "--branch"]
            elif mode == "log":
                limit = str(max(1, min(int(request.args.get("limit", 5)), 20)))
                cmd = ["git", "log", f"-{limit}", "--oneline", "--decorate"]
            elif mode == "tracked_files":
                cmd = ["git", "ls-files"]
            elif mode == "show":
                ref = request.args.get("ref", "HEAD")
                path = request.args.get("path")
                cmd = ["git", "show", "--stat", "--oneline", str(ref)]
                if path:
                    cmd.extend(["--", str(path)])
            else:
                return self.result(request, False, 0.0, f"unsupported git_explore mode: {mode}")
            proc = subprocess.run(cmd, cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
            content = (proc.stdout or proc.stderr).strip()
            ok = proc.returncode == 0
            score = self.score_text(query, content, base=0.2 if ok else 0.0)
            return self.result(request, ok, score, f"git {mode} exited {proc.returncode}", content[:8000], mode=mode, returncode=proc.returncode)
        except Exception as exc:
            return self.result(request, False, 0.0, f"git_explore failed: {exc}", mode=mode)


class AgenticPolicy(ABC):
    """Overridable policy that chooses scored tool calls round by round."""

    @abstractmethod
    def initial_requests(self, memory: AgentMemory, tools: dict[str, ScoredTool]) -> list[ToolRequest]:
        pass

    @abstractmethod
    def next_requests(self, memory: AgentMemory, tools: dict[str, ScoredTool]) -> list[ToolRequest]:
        pass

    def should_stop(self, memory: AgentMemory) -> str | None:
        if memory.calls_used >= memory.max_calls:
            return "max_calls_reached"
        if len(memory.rounds) >= memory.max_rounds:
            return "max_rounds_reached"
        return None


class HeuristicAgenticPolicy(AgenticPolicy):
    """Deterministic iterative policy; subclass or replace for LLM-guided tool choice."""

    def initial_requests(self, memory: AgentMemory, tools: dict[str, ScoredTool]) -> list[ToolRequest]:
        requests: list[ToolRequest] = []
        workspace = memory.workspace
        if "git_explore" in tools:
            requests.append(ToolRequest("git_explore", {"mode": "status"}, "understand workspace state"))
        if "read_file_lines" in tools:
            for candidate in ("README.md", "config.example.yaml"):
                if (workspace / candidate).is_file():
                    requests.append(ToolRequest("read_file_lines", {"path": candidate, "start": 1, "max_lines": 120}, f"read {candidate}"))
        if "grep" in tools:
            pattern = self._query_pattern(memory.query)
            if pattern:
                requests.append(ToolRequest("grep", {"pattern": pattern, "path": ".", "max_matches": 40}, "find query-relevant code/docs"))
        if "git_explore" in tools:
            requests.append(ToolRequest("git_explore", {"mode": "tracked_files"}, "map tracked project files"))
        return requests

    def next_requests(self, memory: AgentMemory, tools: dict[str, ScoredTool]) -> list[ToolRequest]:
        requests: list[ToolRequest] = []
        if "read_file_lines" not in tools:
            return requests
        for result in sorted(memory.results, key=lambda item: item.score, reverse=True):
            if result.name == "grep" and result.ok:
                requests.extend(self._read_requests_from_grep(result))
            elif result.name == "git_explore" and result.args.get("mode") == "tracked_files" and result.ok:
                requests.extend(self._read_requests_from_tracked_files(memory.query, result))
            if len(requests) >= memory.remaining_calls():
                break
        return requests

    def _query_pattern(self, query: str) -> str:
        tokens = [token for token in tokenize(query) if len(token) >= 4]
        if not tokens:
            return "TODO|FIXME|class|def"
        return "|".join(re.escape(token) for token in sorted(tokens, key=len, reverse=True)[:8])

    def _read_requests_from_grep(self, result: ToolResult) -> list[ToolRequest]:
        requests: list[ToolRequest] = []
        seen_paths: set[str] = set()
        for line in result.content.splitlines():
            match = re.match(r"([^:\n]+):(\d+):", line)
            if not match:
                continue
            path, lineno_s = match.groups()
            if path in seen_paths:
                continue
            seen_paths.add(path)
            lineno = int(lineno_s)
            start = max(1, lineno - 20)
            requests.append(ToolRequest(
                "read_file_lines",
                {"path": path, "start": start, "max_lines": 80},
                f"follow grep hit in {path}:{lineno}",
            ))
        return requests

    def _read_requests_from_tracked_files(self, query: str, result: ToolResult) -> list[ToolRequest]:
        query_tokens = tokenize(query)
        scored: list[tuple[float, str]] = []
        for path in result.content.splitlines():
            if not path or Path(path).suffix.lower() not in TEXT_EXTENSIONS:
                continue
            basename_tokens = tokenize(Path(path).name)
            score = len(query_tokens & basename_tokens)
            if path in {"README.md", "config.example.yaml"}:
                score += 1
            if Path(path).suffix.lower() == ".py":
                score += 0.25
            scored.append((score, path))
        scored.sort(reverse=True)
        return [
            ToolRequest("read_file_lines", {"path": path, "start": 1, "max_lines": 120}, f"inspect tracked file {path}")
            for score, path in scored
            if score > 0
        ]


class LegacyOneShotPolicy(HeuristicAgenticPolicy):
    """Compatibility policy that only runs the initial planning round."""

    def should_stop(self, memory: AgentMemory) -> str | None:
        if memory.rounds:
            return "one_shot_complete"
        return super().should_stop(memory)


def default_tool_registry() -> dict[str, ScoredTool]:
    tools: list[ScoredTool] = [ReadFileLinesTool(), GrepTool(), GitExploreTool()]
    return {tool.name: tool for tool in tools}


def _dedupe_and_bound(requests: list[ToolRequest], memory: AgentMemory) -> list[ToolRequest]:
    selected: list[ToolRequest] = []
    seen = set(memory.executed_keys)
    for request in requests:
        key = request.key()
        if key in seen:
            continue
        seen.add(key)
        selected.append(request)
        if len(selected) >= memory.remaining_calls():
            break
    return selected


def run_policy_tools(
    query: str,
    workspace: Path,
    policy: AgenticPolicy | None = None,
    tools: dict[str, ScoredTool] | None = None,
    *,
    max_rounds: int = 3,
    max_calls: int = 8,
    min_score: float = 0.05,
) -> tuple[list[ToolResult], dict[str, Any]]:
    tools = tools or default_tool_registry()
    policy = policy or HeuristicAgenticPolicy()
    memory = AgentMemory(
        query=query,
        workspace=workspace,
        max_rounds=max(1, max_rounds),
        max_calls=max(0, max_calls),
        min_score=max(0.0, min_score),
    )

    while True:
        stop_reason = policy.should_stop(memory)
        if stop_reason:
            memory.stop_reason = stop_reason
            break
        planned = policy.initial_requests(memory, tools) if not memory.rounds else policy.next_requests(memory, tools)
        requests = _dedupe_and_bound(planned, memory)
        if not requests:
            memory.stop_reason = "no_new_requests"
            break
        agent_round = AgentRound(round_index=len(memory.rounds) + 1, requests=requests)
        for request in requests:
            tool = tools.get(request.name)
            if tool is None:
                agent_round.observations.append(f"missing tool: {request.name}")
                continue
            result = tool.execute(workspace, request, query)
            agent_round.results.append(result)
            if result.ok and result.score >= memory.min_score:
                agent_round.observations.append(f"useful {result.name}: score={result.score:.3f} {result.summary}")
            else:
                agent_round.observations.append(f"low-value {result.name}: score={result.score:.3f} {result.summary}")
        memory.add_round(agent_round)

    return sorted(memory.results, key=lambda result: result.score, reverse=True), memory.to_trace()
