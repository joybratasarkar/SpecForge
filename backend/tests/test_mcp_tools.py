from __future__ import annotations

import json
import sys

from spec_test_pilot.mcp_tools import (
    build_tool_arguments_for_query,
    collect_mcp_tool_excerpts,
    load_mcp_server_configs_from_env,
)


def test_load_mcp_server_configs_from_env_parses_servers(monkeypatch) -> None:
    monkeypatch.setenv(
        "QA_MCP_SERVERS_JSON",
        '[{"name":"docs","command":"npx","args":["-y","server"],"timeout_sec":9}]',
    )
    configs, errors = load_mcp_server_configs_from_env()
    assert errors == []
    assert len(configs) == 1
    config = configs[0]
    assert config.name == "docs"
    assert config.command == "npx"
    assert config.args == ["-y", "server"]
    assert config.timeout_sec == 9.0


def test_build_tool_arguments_for_query_uses_schema_hints() -> None:
    tool = {
        "name": "search_docs",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "strict": {"type": "boolean", "default": True},
                "tenant": {"type": "string"},
            },
            "required": ["query", "tenant"],
        },
    }
    args = build_tool_arguments_for_query(
        tool,
        query_text="auth negative scenario mismatch",
    )
    assert args["query"] == "auth negative scenario mismatch"
    assert args["limit"] == 5
    assert args["strict"] is True
    assert args["tenant"] == "qa_context"


def test_collect_mcp_tool_excerpts_disabled_is_noop(monkeypatch) -> None:
    monkeypatch.delenv("QA_MCP_SERVERS_JSON", raising=False)
    status = collect_mcp_tool_excerpts(
        enabled=False,
        spec_title="E-commerce API",
        auth_type="bearer",
        endpoint_metadata=[],
        learning_hints=[],
    )
    assert status["enabled"] is False
    assert status["configured_servers"] == 0
    assert status["excerpts"] == []


def test_collect_mcp_tool_excerpts_with_fake_stdio_server(
    monkeypatch,
    tmp_path,
) -> None:
    server_path = tmp_path / "fake_mcp_server.py"
    server_path.write_text(
        """
import json
import sys


def read_msg():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\\r\\n", b"\\n"):
            break
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.decode("ascii", errors="ignore").strip().lower()] = v.decode("ascii", errors="ignore").strip()
    size = int(headers.get("content-length", "0"))
    if size <= 0:
        return None
    body = sys.stdin.buffer.read(size)
    return json.loads(body.decode("utf-8"))


def write_msg(payload):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\\r\\n\\r\\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


while True:
    msg = read_msg()
    if msg is None:
        break
    method = msg.get("method", "")
    req_id = msg.get("id")
    if method == "initialize":
        write_msg(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake_mcp", "version": "0.0.1"},
                },
            }
        )
    elif method == "tools/list":
        write_msg(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "search_docs",
                            "description": "Search docs by query",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string"},
                                    "limit": {"type": "integer"},
                                },
                                "required": ["query"],
                            },
                        }
                    ]
                },
            }
        )
    elif method == "tools/call":
        params = msg.get("params", {}) or {}
        args = params.get("arguments", {}) or {}
        query = str(args.get("query", ""))
        write_msg(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"MCP synthetic guidance for query={query}",
                        }
                    ]
                },
            }
        )
    elif req_id is not None:
        write_msg({"jsonrpc": "2.0", "id": req_id, "result": {}})
""",
        encoding="utf-8",
    )
    server_cfg = json.dumps(
        [
            {
                "name": "fake_docs",
                "command": sys.executable,
                "args": ["-u", str(server_path)],
                "env": {},
                "timeout_sec": 4,
            }
        ]
    )
    monkeypatch.setenv("QA_MCP_SERVERS_JSON", server_cfg)
    status = collect_mcp_tool_excerpts(
        enabled=True,
        spec_title="E-commerce API",
        auth_type="bearer",
        endpoint_metadata=[{"method": "GET", "path": "/products"}],
        learning_hints=[{"method": "POST", "endpoint": "/orders", "test_type": "validation"}],
        allowed_tools_by_server={"fake_docs": ["search_*"]},
    )
    assert status["enabled"] is True
    assert status["configured_servers"] == 1
    assert status["connected_servers"] == 1
    assert status["tool_calls_attempted"] >= 1
    assert status["tool_calls_succeeded"] >= 1
    assert len(status["excerpts"]) >= 1
    first = status["excerpts"][0]
    assert first.get("source") == "mcp_tool"
    assert first.get("server") == "fake_docs"
    assert first.get("tool_name") == "search_docs"
    assert "MCP synthetic guidance" in str(first.get("excerpt", ""))


def test_collect_mcp_tool_excerpts_requires_allowlist_by_default(monkeypatch) -> None:
    monkeypatch.delenv("QA_MCP_SERVERS_JSON", raising=False)
    status = collect_mcp_tool_excerpts(
        enabled=True,
        spec_title="API",
        auth_type="bearer",
        endpoint_metadata=[],
        learning_hints=[],
    )
    assert status["enabled"] is True
    assert status["configured_servers"] == 0
    assert "mcp_allowlist_required_but_missing" in status["errors"]


def test_collect_mcp_tool_excerpts_respects_allowlist_and_call_budget(
    monkeypatch,
    tmp_path,
) -> None:
    server_path = tmp_path / "fake_mcp_server_allowlist.py"
    server_path.write_text(
        """
import json
import sys


def read_msg():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\\r\\n", b"\\n"):
            break
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.decode("ascii", errors="ignore").strip().lower()] = v.decode("ascii", errors="ignore").strip()
    size = int(headers.get("content-length", "0"))
    if size <= 0:
        return None
    body = sys.stdin.buffer.read(size)
    return json.loads(body.decode("utf-8"))


def write_msg(payload):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\\r\\n\\r\\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


while True:
    msg = read_msg()
    if msg is None:
        break
    method = msg.get("method", "")
    req_id = msg.get("id")
    if method == "initialize":
        write_msg({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "tools/list":
        write_msg(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {"name": "search_docs", "description": "Search docs", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
                        {"name": "write_docs", "description": "Write docs", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
                    ]
                },
            }
        )
    elif method == "tools/call":
        params = msg.get("params", {}) or {}
        write_msg({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"called={params.get('name')}"}]}})
    else:
        write_msg({"jsonrpc": "2.0", "id": req_id, "result": {}})
""",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "QA_MCP_SERVERS_JSON",
        json.dumps(
            [
                {
                    "name": "fake_docs",
                    "command": sys.executable,
                    "args": ["-u", str(server_path)],
                    "timeout_sec": 4,
                }
            ]
        ),
    )
    status = collect_mcp_tool_excerpts(
        enabled=True,
        spec_title="E-commerce API",
        auth_type="bearer",
        endpoint_metadata=[{"method": "GET", "path": "/products"}],
        learning_hints=[],
        max_tools_per_server=3,
        max_calls_total=2,
        allowed_tools_by_server={"fake_docs": ["search_*"]},
    )
    assert status["tool_calls_attempted"] == 1
    assert status["tool_calls_succeeded"] == 1
    assert len(status["excerpts"]) == 1
    assert status["excerpts"][0]["tool_name"] == "search_docs"
    trace = status["server_traces"][0]
    blocked = [item for item in trace.get("tools_called", []) if item.get("status") == "blocked"]
    assert blocked
    assert blocked[0]["name"] == "write_docs"
