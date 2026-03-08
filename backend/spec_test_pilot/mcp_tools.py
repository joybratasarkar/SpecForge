"""
Optional MCP tool integration for QA specialist context enrichment.

This module keeps MCP usage best-effort and non-blocking for core QA runs:
- disabled by default
- all failures are captured as diagnostics, not raised
- tool output is converted into compact GAM excerpts
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


MCP_SERVERS_ENV = "QA_MCP_SERVERS_JSON"
DEFAULT_TIMEOUT_SEC = 8.0
DEFAULT_MAX_TOOLS_PER_SERVER = 2
DEFAULT_MAX_EXCERPTS = 6
DEFAULT_MAX_CALLS_TOTAL = 12
_HEADER_LIMIT_BYTES = 64 * 1024
_MUTATING_TOOL_TOKENS = {
    "create",
    "delete",
    "deploy",
    "drop",
    "exec",
    "execute",
    "insert",
    "modify",
    "patch",
    "publish",
    "remove",
    "run",
    "shell",
    "spawn",
    "terminal",
    "unlink",
    "update",
    "upsert",
    "write",
}


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    timeout_sec: float = DEFAULT_TIMEOUT_SEC


def _coerce_positive_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        number = int(value)
    except Exception:
        return int(default)
    return max(minimum, number)


def _coerce_positive_float(value: Any, default: float, minimum: float = 0.1) -> float:
    try:
        number = float(value)
    except Exception:
        return float(default)
    return max(minimum, number)


def _safe_token(value: Any, fallback: str = "mcp") -> str:
    text = str(value or "").strip().lower()
    out_chars: List[str] = []
    for ch in text:
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in {"_", "-"}:
            out_chars.append(ch)
        else:
            out_chars.append("_")
    token = "".join(out_chars).strip("_")
    return token or fallback


def load_mcp_server_configs_from_env(
    env_var: str = MCP_SERVERS_ENV,
) -> Tuple[List[MCPServerConfig], List[str]]:
    raw = str(os.getenv(env_var, "")).strip()
    if not raw:
        return [], []

    errors: List[str] = []
    try:
        payload = json.loads(raw)
    except Exception as exc:
        return [], [f"invalid_json:{env_var}:{exc}"]

    if isinstance(payload, dict):
        items = payload.get("servers", [])
    else:
        items = payload

    if not isinstance(items, list):
        return [], [f"invalid_schema:{env_var}:expected_list_or_object_with_servers"]

    configs: List[MCPServerConfig] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"server_{idx}:invalid_item_type")
            continue
        command = str(item.get("command", "")).strip()
        if not command:
            errors.append(f"server_{idx}:missing_command")
            continue

        name = _safe_token(item.get("name") or f"server_{idx}", fallback=f"server_{idx}")
        args_raw = item.get("args", [])
        args: List[str] = []
        if isinstance(args_raw, list):
            args = [str(arg) for arg in args_raw]
        env_raw = item.get("env", {})
        env_dict: Dict[str, str] = {}
        if isinstance(env_raw, dict):
            env_dict = {str(k): str(v) for k, v in env_raw.items()}
        cwd = str(item.get("cwd", "")).strip()
        timeout_sec = _coerce_positive_float(
            item.get("timeout_sec", DEFAULT_TIMEOUT_SEC),
            default=DEFAULT_TIMEOUT_SEC,
            minimum=0.5,
        )
        configs.append(
            MCPServerConfig(
                name=name,
                command=command,
                args=args,
                env=env_dict,
                cwd=cwd,
                timeout_sec=timeout_sec,
            )
        )

    return configs, errors


class _MCPStdIOClient:
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._stdout_fd: Optional[int] = None
        self._request_id = 1
        self._stderr_tail: List[str] = []
        self._stderr_thread: Optional[threading.Thread] = None

    @property
    def stderr_tail(self) -> List[str]:
        return list(self._stderr_tail[-20:])

    def start(self) -> None:
        command = [self.config.command, *self.config.args]
        child_env = {
            key: value
            for key in ("PATH", "HOME", "TMPDIR", "PYTHONPATH")
            for value in [str(os.getenv(key, ""))]
            if value
        }
        child_env.update(self.config.env)
        cwd: Optional[str] = None
        if self.config.cwd:
            try:
                cwd = str(Path(self.config.cwd).expanduser().resolve())
            except Exception:
                cwd = self.config.cwd
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env,
            cwd=cwd,
            bufsize=0,
        )
        if self._proc.stdout is None:
            raise RuntimeError("mcp_stdout_missing")
        self._stdout_fd = self._proc.stdout.fileno()
        self._start_stderr_drain()

    def _start_stderr_drain(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return

        def _drain() -> None:
            assert self._proc is not None
            assert self._proc.stderr is not None
            for raw in iter(self._proc.stderr.readline, b""):
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                self._stderr_tail.append(text)
                if len(self._stderr_tail) > 200:
                    del self._stderr_tail[:100]

        self._stderr_thread = threading.Thread(
            target=_drain,
            name=f"mcp-stderr-{self.config.name}",
            daemon=True,
        )
        self._stderr_thread.start()

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=1.5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=0.8)
            except Exception:
                pass

    def _send_message(self, payload: Dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("mcp_process_not_started")
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + body)
        self._proc.stdin.flush()

    def _read_bytes(self, size: int, deadline: float) -> bytes:
        if self._stdout_fd is None:
            raise RuntimeError("mcp_stdout_unavailable")
        out = bytearray()
        while len(out) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("mcp_read_timeout")
            ready, _, _ = select.select([self._stdout_fd], [], [], remaining)
            if not ready:
                raise TimeoutError("mcp_read_timeout")
            chunk = os.read(self._stdout_fd, size - len(out))
            if not chunk:
                raise RuntimeError("mcp_stdout_closed")
            out.extend(chunk)
        return bytes(out)

    def _read_message(self, timeout_sec: float) -> Dict[str, Any]:
        deadline = time.monotonic() + max(0.1, float(timeout_sec))
        header = bytearray()
        while b"\r\n\r\n" not in header and b"\n\n" not in header:
            if len(header) > _HEADER_LIMIT_BYTES:
                raise RuntimeError("mcp_header_too_large")
            header.extend(self._read_bytes(1, deadline))

        if b"\r\n\r\n" in header:
            raw_header = bytes(header).split(b"\r\n\r\n", 1)[0]
            header_lines = raw_header.split(b"\r\n")
        else:
            raw_header = bytes(header).split(b"\n\n", 1)[0]
            header_lines = raw_header.split(b"\n")

        content_length = None
        for line in header_lines:
            if b":" not in line:
                continue
            key_raw, value_raw = line.split(b":", 1)
            key = key_raw.decode("ascii", errors="ignore").strip().lower()
            if key != "content-length":
                continue
            try:
                content_length = int(value_raw.decode("ascii", errors="ignore").strip())
            except Exception:
                raise RuntimeError("mcp_invalid_content_length")
            break

        if content_length is None or content_length < 0:
            raise RuntimeError("mcp_missing_content_length")

        body = self._read_bytes(content_length, deadline)
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except Exception as exc:
            raise RuntimeError(f"mcp_invalid_json_body:{exc}")
        if not isinstance(payload, dict):
            raise RuntimeError("mcp_non_object_message")
        return payload

    def _request(self, method: str, params: Optional[Dict[str, Any]], timeout_sec: float) -> Dict[str, Any]:
        req_id = self._request_id
        self._request_id += 1
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": str(method),
        }
        if params is not None:
            payload["params"] = params
        self._send_message(payload)

        deadline = time.monotonic() + max(0.1, float(timeout_sec))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"mcp_request_timeout:{method}")
            message = self._read_message(remaining)
            if str(message.get("id", "")) != str(req_id):
                continue
            if "error" in message:
                error = message.get("error")
                raise RuntimeError(f"mcp_error:{method}:{error}")
            result = message.get("result", {})
            if isinstance(result, dict):
                return result
            return {"value": result}

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": str(method),
        }
        if params is not None:
            payload["params"] = params
        self._send_message(payload)

    def initialize(self, timeout_sec: float) -> Dict[str, Any]:
        result = self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {
                    "name": "specforge-qa-specialist",
                    "version": "0.1.0",
                },
            },
            timeout_sec=timeout_sec,
        )
        try:
            self._notify("notifications/initialized", {})
        except Exception:
            pass
        return result

    def list_tools(self, timeout_sec: float) -> List[Dict[str, Any]]:
        result = self._request("tools/list", {}, timeout_sec=timeout_sec)
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            return []
        return [item for item in tools if isinstance(item, dict)]

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout_sec: float) -> Dict[str, Any]:
        result = self._request(
            "tools/call",
            {"name": str(tool_name), "arguments": dict(arguments or {})},
            timeout_sec=timeout_sec,
        )
        return result if isinstance(result, dict) else {"value": result}


def _build_context_query(
    *,
    spec_title: str,
    auth_type: str,
    endpoint_metadata: List[Dict[str, Any]],
    learning_hints: List[Dict[str, Any]],
) -> str:
    endpoints: List[str] = []
    for item in endpoint_metadata[:12]:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method", "")).upper()
        path = str(item.get("path", "")).strip()
        if method and path:
            endpoints.append(f"{method} {path}")

    weak_patterns: List[str] = []
    for hint in learning_hints[:6]:
        if not isinstance(hint, dict):
            continue
        method = str(hint.get("method", "")).upper()
        endpoint = str(hint.get("endpoint", "")).strip()
        test_type = str(hint.get("test_type", "")).strip().lower()
        expected = hint.get("expected_status")
        if method and endpoint:
            weak_patterns.append(f"{method} {endpoint} ({test_type}, expected={expected})")

    sections = [
        f"Spec: {spec_title}",
        f"Auth: {auth_type}",
    ]
    if endpoints:
        sections.append("Endpoints: " + "; ".join(endpoints))
    if weak_patterns:
        sections.append("Weak patterns: " + "; ".join(weak_patterns))
    sections.append(
        "Need practical API QA guidance for auth negatives, validation mismatches, "
        "workflow dependencies, flaky detection, and contract reliability."
    )
    return " | ".join(sections)


def _tool_rank(tool: Dict[str, Any]) -> int:
    name = str(tool.get("name", "")).strip().lower()
    description = str(tool.get("description", "")).strip().lower()
    text = f"{name} {description}"
    score = 0
    for token, points in (
        ("search", 4),
        ("query", 4),
        ("lookup", 4),
        ("retrieve", 4),
        ("docs", 3),
        ("knowledge", 3),
        ("read", 2),
        ("fetch", 2),
        ("web", 2),
        ("api", 1),
    ):
        if token in text:
            score += points
    if "write" in text or "delete" in text or "update" in text:
        score -= 4
    return score


def _pick_tools_for_query(tools: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    ranked = sorted(
        [tool for tool in tools if isinstance(tool, dict) and str(tool.get("name", "")).strip()],
        key=lambda item: (_tool_rank(item), str(item.get("name", ""))),
        reverse=True,
    )
    return ranked[: max(1, int(limit))]


def _tool_allowed(
    *,
    server_name: str,
    tool_name: str,
    tool_description: str = "",
    allowed_tools_by_server: Optional[Dict[str, List[str]]] = None,
    require_allowlist: bool = True,
    allow_mutating_tools: bool = False,
) -> Tuple[bool, str]:
    if not allow_mutating_tools:
        words = {
            token
            for token in re.split(r"[^a-z0-9]+", f"{tool_name} {tool_description}".lower())
            if token
        }
        if words.intersection(_MUTATING_TOOL_TOKENS):
            return False, "mutating_tool_blocked"

    allow_map = allowed_tools_by_server or {}
    if not isinstance(allow_map, dict) or not allow_map:
        if require_allowlist:
            return False, "allowlist_required"
        return True, ""

    server_token = _safe_token(server_name, fallback="server")
    tool_token = _safe_token(tool_name, fallback="")
    if not tool_token:
        return False, "invalid_tool_name"

    server_patterns = list(allow_map.get(server_token, []))
    wildcard_patterns = list(allow_map.get("*", []))
    patterns = [str(item).strip().lower() for item in [*server_patterns, *wildcard_patterns] if str(item).strip()]
    if not patterns:
        return False, "not_in_allowlist"
    if any(fnmatch(tool_token, pattern) for pattern in patterns):
        return True, ""
    return False, "not_in_allowlist"


def build_tool_arguments_for_query(tool: Dict[str, Any], query_text: str) -> Dict[str, Any]:
    input_schema = tool.get("inputSchema", {})
    if not isinstance(input_schema, dict):
        return {"query": query_text}

    properties = input_schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    required_raw = input_schema.get("required", [])
    required = {
        str(item).strip()
        for item in required_raw
        if isinstance(item, str) and str(item).strip()
    }

    query_fields = {"query", "q", "text", "prompt", "search", "question", "keyword", "keywords"}
    limit_fields = {"limit", "topk", "top_k", "k", "max_results", "n"}

    args: Dict[str, Any] = {}
    for field_name, field_schema in properties.items():
        name = str(field_name).strip()
        if not name:
            continue
        lname = name.lower()
        schema = field_schema if isinstance(field_schema, dict) else {}
        if lname in query_fields:
            args[name] = query_text
            continue
        if lname in limit_fields:
            args[name] = 5
            continue
        if "default" in schema:
            args[name] = schema["default"]
            continue
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values:
            args[name] = enum_values[0]
            continue
        if name not in required:
            continue
        field_type = str(schema.get("type", "string")).strip().lower()
        if field_type == "string":
            args[name] = query_text if "query" in lname or "text" in lname else "qa_context"
        elif field_type in {"integer", "number"}:
            args[name] = 1
        elif field_type == "boolean":
            args[name] = False
        elif field_type == "array":
            args[name] = []
        elif field_type == "object":
            args[name] = {}
        else:
            args[name] = "qa_context"

    if not args:
        return {"query": query_text}
    return args


def _extract_tool_result_text(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return str(result)

    content = result.get("content")
    texts: List[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                item_text = item.get("text")
                if isinstance(item_text, str) and item_text.strip():
                    texts.append(item_text.strip())
                    continue
                if item.get("type") == "json":
                    try:
                        texts.append(json.dumps(item.get("json", {}), ensure_ascii=True))
                    except Exception:
                        pass
            elif isinstance(item, str) and item.strip():
                texts.append(item.strip())
    elif isinstance(content, str) and content.strip():
        texts.append(content.strip())

    structured = result.get("structuredContent")
    if isinstance(structured, dict) and structured:
        try:
            texts.append(json.dumps(structured, ensure_ascii=True))
        except Exception:
            pass

    if texts:
        merged = "\n".join(texts).strip()
        if len(merged) > 1800:
            return merged[:1799] + "..."
        return merged

    try:
        dumped = json.dumps(result, ensure_ascii=True)
    except Exception:
        dumped = str(result)
    dumped = dumped.strip()
    if len(dumped) > 1800:
        return dumped[:1799] + "..."
    return dumped


def collect_mcp_tool_excerpts(
    *,
    enabled: bool,
    spec_title: str,
    auth_type: str,
    endpoint_metadata: List[Dict[str, Any]],
    learning_hints: List[Dict[str, Any]],
    max_tools_per_server: int = DEFAULT_MAX_TOOLS_PER_SERVER,
    max_excerpts: int = DEFAULT_MAX_EXCERPTS,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    max_calls_total: int = DEFAULT_MAX_CALLS_TOTAL,
    allowed_tools_by_server: Optional[Dict[str, List[str]]] = None,
    require_allowlist: bool = True,
    allow_mutating_tools: bool = False,
) -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "enabled": bool(enabled),
        "configured_servers": 0,
        "connected_servers": 0,
        "tool_calls_attempted": 0,
        "tool_calls_succeeded": 0,
        "errors": [],
        "server_traces": [],
        "excerpts": [],
    }
    if not enabled:
        return status
    if require_allowlist and not (isinstance(allowed_tools_by_server, dict) and allowed_tools_by_server):
        status["errors"].append("mcp_allowlist_required_but_missing")
        return status

    configs, parse_errors = load_mcp_server_configs_from_env()
    status["configured_servers"] = int(len(configs))
    if parse_errors:
        status["errors"].extend(parse_errors)
    if not configs:
        status["errors"].append("mcp_not_configured")
        return status

    query_text = _build_context_query(
        spec_title=spec_title,
        auth_type=auth_type,
        endpoint_metadata=endpoint_metadata,
        learning_hints=learning_hints,
    )
    excerpt_limit = _coerce_positive_int(max_excerpts, default=DEFAULT_MAX_EXCERPTS, minimum=1)
    tool_limit = _coerce_positive_int(
        max_tools_per_server,
        default=DEFAULT_MAX_TOOLS_PER_SERVER,
        minimum=1,
    )
    timeout_default = _coerce_positive_float(timeout_sec, default=DEFAULT_TIMEOUT_SEC, minimum=0.5)
    call_budget_total = _coerce_positive_int(
        max_calls_total,
        default=DEFAULT_MAX_CALLS_TOTAL,
        minimum=1,
    )

    excerpts: List[Dict[str, Any]] = []
    total_calls = 0
    for config in configs:
        if len(excerpts) >= excerpt_limit:
            break
        if total_calls >= call_budget_total:
            status["errors"].append("mcp_call_budget_exhausted")
            break
        client = _MCPStdIOClient(config)
        server_trace: Dict[str, Any] = {
            "server": config.name,
            "status": "init",
            "tools_listed": 0,
            "tools_called": [],
            "errors": [],
            "trace_id": uuid.uuid4().hex,
        }
        call_timeout = max(timeout_default, float(config.timeout_sec))
        try:
            client.start()
            client.initialize(timeout_sec=call_timeout)
            status["connected_servers"] = int(status["connected_servers"]) + 1
            tools = client.list_tools(timeout_sec=call_timeout)
            server_trace["tools_listed"] = int(len(tools))
            selected_tools = _pick_tools_for_query(tools, limit=tool_limit)
            for tool in selected_tools:
                if len(excerpts) >= excerpt_limit:
                    break
                if total_calls >= call_budget_total:
                    server_trace["errors"].append("call_budget_exhausted")
                    break
                tool_name = str(tool.get("name", "")).strip()
                if not tool_name:
                    continue
                allowed, blocked_reason = _tool_allowed(
                    server_name=config.name,
                    tool_name=tool_name,
                    tool_description=str(tool.get("description", "")),
                    allowed_tools_by_server=allowed_tools_by_server,
                    require_allowlist=require_allowlist,
                    allow_mutating_tools=allow_mutating_tools,
                )
                if not allowed:
                    server_trace["tools_called"].append(
                        {
                            "name": tool_name,
                            "status": "blocked",
                            "reason": blocked_reason or "blocked",
                            "trace_id": uuid.uuid4().hex,
                        }
                    )
                    continue
                args = build_tool_arguments_for_query(tool, query_text=query_text)
                status["tool_calls_attempted"] = int(status["tool_calls_attempted"]) + 1
                total_calls += 1
                trace_id = uuid.uuid4().hex
                try:
                    result = client.call_tool(tool_name, args, timeout_sec=call_timeout)
                    text = _extract_tool_result_text(result)
                    if text:
                        excerpts.append(
                            {
                                "title": f"MCP {config.name}:{tool_name}",
                                "source": "mcp_tool",
                                "tags": ["mcp", config.name, tool_name],
                                "excerpt": text,
                                "similarity": 0.0,
                                "server": config.name,
                                "tool_name": tool_name,
                                "trace_id": trace_id,
                            }
                        )
                        status["tool_calls_succeeded"] = int(status["tool_calls_succeeded"]) + 1
                    server_trace["tools_called"].append(
                        {
                            "name": tool_name,
                            "status": "ok",
                            "args_keys": sorted(list(args.keys())),
                            "trace_id": trace_id,
                        }
                    )
                except Exception as exc:
                    server_trace["tools_called"].append(
                        {
                            "name": tool_name,
                            "status": "error",
                            "error": str(exc),
                            "trace_id": trace_id,
                        }
                    )
            server_trace["status"] = "ok"
        except Exception as exc:
            server_trace["status"] = "error"
            server_trace["errors"].append(str(exc))
            status["errors"].append(f"{config.name}:{exc}")
        finally:
            stderr_tail = client.stderr_tail
            if stderr_tail:
                server_trace["stderr_tail"] = stderr_tail
            client.close()
            status["server_traces"].append(server_trace)

    status["excerpts"] = excerpts[:excerpt_limit]
    return status
