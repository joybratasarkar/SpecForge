from __future__ import annotations

import json
from pathlib import Path

from spec_test_pilot.qa_specialist_agent import (
    DEFAULT_ENVIRONMENT_PROFILE,
    QASpecialistAgent,
)
from spec_test_pilot.runtime_settings import (
    get_learning_policy,
    get_runtime_settings,
    reset_runtime_settings_cache,
)


def _clear_runtime_env(monkeypatch) -> None:
    for key in (
        "QA_DEFAULT_BASE_URL",
        "QA_DEFAULT_ENVIRONMENT_PROFILE",
        "QA_DYNAMIC_MOCK_HOST",
        "QA_DYNAMIC_MOCK_PORT",
        "QA_UI_HOST",
        "QA_UI_PORT",
        "QA_AUTH_VALID_TOKEN",
        "QA_AUTH_ADMIN_TOKEN",
        "QA_AUTH_INVALID_TOKEN",
        "QA_AUTH_EXPIRED_TOKEN",
        "QA_CHAOS_ONCE_503_MODE",
        "QA_CHAOS_ONCE_TIMEOUT_MODE",
        "QA_CHAOS_CONCURRENCY_MODE",
        "QA_SSRF_PROBE_URL",
        "QA_MCP_MAX_CALLS_TOTAL",
        "QA_MCP_ALLOWED_TOOLS_JSON",
        "QA_MCP_REQUIRE_ALLOWLIST",
        "QA_MCP_ALLOW_MUTATING_TOOLS",
        "QA_LEARNING_POLICY_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_runtime_settings_cache()


def test_runtime_settings_defaults(monkeypatch) -> None:
    _clear_runtime_env(monkeypatch)
    settings = get_runtime_settings()

    assert settings.default_base_url == "http://localhost:8000"
    assert settings.default_environment_profile == "mock"
    assert settings.dynamic_mock_host == "127.0.0.1"
    assert settings.dynamic_mock_port == 8000
    assert settings.auth_token_valid == "valid_token_123"
    assert settings.auth_token_invalid == "invalid"
    assert settings.chaos_once_503_mode == "once_503"
    assert settings.chaos_once_timeout_mode == "once_timeout"
    assert settings.chaos_concurrency_mode == "concurrency_conflict"
    assert settings.mcp_max_calls_total >= 1
    assert settings.mcp_require_allowlist is True
    assert settings.mcp_allow_mutating_tools is False


def test_runtime_settings_env_overrides(monkeypatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("QA_DEFAULT_BASE_URL", "https://api.example.internal")
    monkeypatch.setenv("QA_AUTH_VALID_TOKEN", "token_ok")
    monkeypatch.setenv("QA_AUTH_INVALID_TOKEN", "token_bad")
    monkeypatch.setenv("QA_CHAOS_ONCE_503_MODE", "chaos_retry")
    monkeypatch.setenv("QA_MCP_MAX_CALLS_TOTAL", "3")
    monkeypatch.setenv("QA_MCP_REQUIRE_ALLOWLIST", "0")
    monkeypatch.setenv("QA_MCP_ALLOW_MUTATING_TOOLS", "1")
    monkeypatch.setenv(
        "QA_MCP_ALLOWED_TOOLS_JSON",
        json.dumps({"fake_docs": ["search_*"], "*": ["lookup"]}),
    )
    reset_runtime_settings_cache()

    settings = get_runtime_settings()
    assert settings.default_base_url == "https://api.example.internal"
    assert settings.auth_token_valid == "token_ok"
    assert settings.auth_token_invalid == "token_bad"
    assert settings.chaos_once_503_mode == "chaos_retry"
    assert settings.mcp_max_calls_total == 3
    assert settings.mcp_allowed_tools_by_server.get("fake_docs") == ["search_*"]
    assert settings.mcp_allowed_tools_by_server.get("*") == ["lookup"]
    assert settings.mcp_require_allowlist is False
    assert settings.mcp_allow_mutating_tools is True


def test_learning_policy_override_file(monkeypatch, tmp_path: Path) -> None:
    _clear_runtime_env(monkeypatch)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "version": "qa_learning_policy.test",
                "rl_mutation_target_limit": 7,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_LEARNING_POLICY_FILE", str(policy_path))
    reset_runtime_settings_cache()

    policy = get_learning_policy()
    assert policy.get("version") == "qa_learning_policy.test"
    assert int(policy.get("rl_mutation_target_limit", 0)) == 7
    # Missing keys should still fall back to defaults.
    assert int(policy.get("flaky_rerun_max_attempts", 0)) == 3


def test_environment_profile_boundaries(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text("openapi: 3.0.0\ninfo:\n  title: T\n  version: v1\npaths: {}\n", encoding="utf-8")

    prod_agent = QASpecialistAgent(
        spec_path=str(spec_path),
        output_dir=str(tmp_path / "out_prod"),
        environment_profile="prod_safe",
    )
    assert prod_agent.environment_profile == "prod_safe"
    assert prod_agent._is_safe_method_for_profile("GET") is True
    assert prod_agent._is_safe_method_for_profile("POST") is False

    invalid_agent = QASpecialistAgent(
        spec_path=str(spec_path),
        output_dir=str(tmp_path / "out_invalid"),
        environment_profile="not_a_profile",
    )
    assert invalid_agent.environment_profile == DEFAULT_ENVIRONMENT_PROFILE
