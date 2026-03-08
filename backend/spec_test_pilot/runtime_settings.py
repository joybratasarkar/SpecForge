"""Centralized runtime settings and learning-policy loading."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping


def env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except Exception:
        value = int(default)
    return max(int(minimum), value)


def env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = float(raw)
    except Exception:
        value = float(default)
    return max(float(minimum), value)


def env_str(name: str, default: str) -> str:
    raw = str(os.getenv(name, default)).strip()
    return raw or str(default)


def _safe_token(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip().lower()
    out_chars: List[str] = []
    for ch in text:
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in {"_", "-", "*"}:
            out_chars.append(ch)
        else:
            out_chars.append("_")
    token = "".join(out_chars).strip("_")
    if token:
        return token
    return fallback


def _load_tool_allowlist_from_env(env_var: str) -> Dict[str, List[str]]:
    raw = str(os.getenv(env_var, "")).strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for server_name, tools in payload.items():
        server_token = _safe_token(server_name)
        if not server_token:
            continue
        values: List[str] = []
        if isinstance(tools, list):
            for item in tools:
                token = _safe_token(item)
                if token:
                    values.append(token)
        out[server_token] = sorted(set(values))
    return out


@dataclass(frozen=True)
class RuntimeSettings:
    settings_version: str
    default_base_url: str
    default_environment_profile: str
    supported_environment_profiles: tuple[str, ...]
    dynamic_mock_host: str
    dynamic_mock_port: int
    qa_ui_host: str
    qa_ui_port: int
    live_request_timeout_sec: float
    script_exec_max_runtime_sec: float
    script_exec_base_url_hint: str
    auth_token_valid: str
    auth_token_admin: str
    auth_token_invalid: str
    auth_token_expired: str
    chaos_once_503_mode: str
    chaos_once_timeout_mode: str
    chaos_concurrency_mode: str
    ssrf_probe_url: str
    mcp_max_calls_total: int
    mcp_allowed_tools_by_server: Dict[str, List[str]]
    mcp_require_allowlist: bool
    mcp_allow_mutating_tools: bool

    def bearer_valid(self) -> str:
        return f"Bearer {self.auth_token_valid}"

    def bearer_admin(self) -> str:
        return f"Bearer {self.auth_token_admin}"

    def bearer_invalid(self) -> str:
        return f"Bearer {self.auth_token_invalid}"

    def bearer_expired(self) -> str:
        return f"Bearer {self.auth_token_expired}"


DEFAULT_LEARNING_POLICY_FILENAME = "qa_learning_policy.v1.json"
DEFAULT_LEARNING_POLICY_PATH = (
    Path(__file__).resolve().parent / "policies" / DEFAULT_LEARNING_POLICY_FILENAME
)
DEFAULT_LEARNING_POLICY: Dict[str, Any] = {
    "version": "qa_learning_policy.v1",
    "uncertainty_coverage_quantile": 0.75,
    "repair_rule_min_attempts": 3,
    "repair_rule_min_failure_rate": 0.85,
    "repair_rule_dominant_ratio": 0.70,
    "repair_rule_max_items": 500,
    "default_decision_weight": 1.0,
    "min_decision_weight": 0.2,
    "max_decision_weight": 5.0,
    "decision_learning_rate": 0.20,
    "learning_history_limit": 200,
    "scenario_stats_limit": 4000,
    "selection_trace_limit": 60,
    "gam_context_min_quality": 0.55,
    "rl_mutation_target_limit": 20,
    "rl_mutation_per_target_limit": 2,
    "rl_mutation_max_variants_per_target": 5,
    "rl_mutation_max_new_scenarios": 48,
    "rl_mutation_min_priority": 0.08,
    "rl_history_seed_target_limit": 20,
    "rl_history_seed_max_new_scenarios": 24,
    "rl_history_seed_min_attempts": 1,
    "rl_history_seed_min_priority": 0.12,
    "rl_weak_min_attempts": 3,
    "rl_weak_failure_rate_threshold": 0.20,
    "portfolio_stable_ratio": 0.70,
    "portfolio_focus_ratio": 0.20,
    "portfolio_explore_ratio": 0.10,
    "forced_replay_cadence_runs": 2,
    "gam_recent_focus_window": 3,
    "gam_recent_focus_limit": 40,
    "flaky_rerun_max_attempts": 3,
    "runtime_repair_suggestion_limit": 50,
    "real_life_mandatory_strategies": [
        "real_life_retry_on_503",
        "real_life_timeout_retry",
        "real_life_p95_p99_probe",
        "real_life_bola_probe",
        "real_life_ssrf_probe",
        "real_life_data_leakage_probe",
        "real_life_concurrency_conflict",
        "real_life_old_client_compat",
        "real_life_payload_drift_probe",
    ],
}


def _coerce_learning_policy(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return dict(DEFAULT_LEARNING_POLICY)
    policy = dict(DEFAULT_LEARNING_POLICY)
    for key, value in raw.items():
        policy[str(key)] = value
    if not isinstance(policy.get("real_life_mandatory_strategies"), list):
        policy["real_life_mandatory_strategies"] = list(
            DEFAULT_LEARNING_POLICY["real_life_mandatory_strategies"]
        )
    policy["real_life_mandatory_strategies"] = [
        str(item).strip()
        for item in list(policy.get("real_life_mandatory_strategies") or [])
        if str(item).strip()
    ]
    return policy


@lru_cache(maxsize=1)
def get_learning_policy() -> Dict[str, Any]:
    configured = str(os.getenv("QA_LEARNING_POLICY_FILE", "")).strip()
    policy_path = (
        Path(configured).expanduser().resolve()
        if configured
        else DEFAULT_LEARNING_POLICY_PATH.resolve()
    )
    try:
        loaded = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_LEARNING_POLICY)
    return _coerce_learning_policy(loaded)


@lru_cache(maxsize=1)
def get_runtime_settings() -> RuntimeSettings:
    supported_profiles = ("mock", "staging", "prod_safe")
    return RuntimeSettings(
        settings_version=env_str("QA_RUNTIME_SETTINGS_VERSION", "v1"),
        default_base_url=env_str("QA_DEFAULT_BASE_URL", "http://localhost:8000"),
        default_environment_profile=env_str(
            "QA_DEFAULT_ENVIRONMENT_PROFILE", "mock"
        ).lower(),
        supported_environment_profiles=supported_profiles,
        dynamic_mock_host=env_str("QA_DYNAMIC_MOCK_HOST", "127.0.0.1"),
        dynamic_mock_port=env_int("QA_DYNAMIC_MOCK_PORT", 8000, minimum=1),
        qa_ui_host=env_str("QA_UI_HOST", "127.0.0.1"),
        qa_ui_port=env_int("QA_UI_PORT", 8787, minimum=1),
        live_request_timeout_sec=env_float(
            "QA_LIVE_REQUEST_TIMEOUT_SEC",
            12.0,
            minimum=0.1,
        ),
        script_exec_max_runtime_sec=env_float(
            "QA_SCRIPT_EXEC_MAX_RUNTIME_SEC",
            120.0,
            minimum=1.0,
        ),
        script_exec_base_url_hint=env_str(
            "QA_SCRIPT_EXEC_BASE_URL_HINT",
            "http://testserver",
        ),
        auth_token_valid=env_str("QA_AUTH_VALID_TOKEN", "valid_token_123"),
        auth_token_admin=env_str("QA_AUTH_ADMIN_TOKEN", "admin_token_123"),
        auth_token_invalid=env_str("QA_AUTH_INVALID_TOKEN", "invalid"),
        auth_token_expired=env_str("QA_AUTH_EXPIRED_TOKEN", "expired"),
        chaos_once_503_mode=_safe_token(
            env_str("QA_CHAOS_ONCE_503_MODE", "once_503"),
            fallback="once_503",
        ),
        chaos_once_timeout_mode=_safe_token(
            env_str("QA_CHAOS_ONCE_TIMEOUT_MODE", "once_timeout"),
            fallback="once_timeout",
        ),
        chaos_concurrency_mode=_safe_token(
            env_str("QA_CHAOS_CONCURRENCY_MODE", "concurrency_conflict"),
            fallback="concurrency_conflict",
        ),
        ssrf_probe_url=env_str(
            "QA_SSRF_PROBE_URL",
            "http://169.254.169.254/latest/meta-data",
        ),
        mcp_max_calls_total=env_int("QA_MCP_MAX_CALLS_TOTAL", 12, minimum=1),
        mcp_allowed_tools_by_server=_load_tool_allowlist_from_env(
            "QA_MCP_ALLOWED_TOOLS_JSON"
        ),
        mcp_require_allowlist=env_bool("QA_MCP_REQUIRE_ALLOWLIST", True),
        mcp_allow_mutating_tools=env_bool("QA_MCP_ALLOW_MUTATING_TOOLS", False),
    )


def reset_runtime_settings_cache() -> None:
    """Test helper to force settings reload after env changes."""
    get_runtime_settings.cache_clear()
    get_learning_policy.cache_clear()


def runtime_settings_snapshot() -> Dict[str, Any]:
    settings = get_runtime_settings()
    policy = get_learning_policy()
    snapshot: Dict[str, Any] = {
        "settings_version": settings.settings_version,
        "default_base_url": settings.default_base_url,
        "default_environment_profile": settings.default_environment_profile,
        "supported_environment_profiles": list(settings.supported_environment_profiles),
        "dynamic_mock_host": settings.dynamic_mock_host,
        "dynamic_mock_port": settings.dynamic_mock_port,
        "qa_ui_host": settings.qa_ui_host,
        "qa_ui_port": settings.qa_ui_port,
        "live_request_timeout_sec": settings.live_request_timeout_sec,
        "script_exec_max_runtime_sec": settings.script_exec_max_runtime_sec,
        "auth_token_valid": settings.auth_token_valid,
        "auth_token_admin": settings.auth_token_admin,
        "auth_token_invalid": settings.auth_token_invalid,
        "auth_token_expired": settings.auth_token_expired,
        "chaos_modes": {
            "once_503": settings.chaos_once_503_mode,
            "once_timeout": settings.chaos_once_timeout_mode,
            "concurrency_conflict": settings.chaos_concurrency_mode,
        },
        "ssrf_probe_url": settings.ssrf_probe_url,
        "mcp_max_calls_total": settings.mcp_max_calls_total,
        "mcp_allowed_tools_by_server": dict(settings.mcp_allowed_tools_by_server),
        "learning_policy_version": str(policy.get("version", "")),
        "learning_policy_path_default": str(DEFAULT_LEARNING_POLICY_PATH),
    }
    return snapshot
