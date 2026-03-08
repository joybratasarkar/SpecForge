#!/usr/bin/env python3
"""Customer-facing UI to run multi-domain QA agent tests.

Launch:
    ./backend/run_customer_backend_fastapi.sh
Open:
    http://127.0.0.1:8787
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml

from spec_test_pilot.runtime_settings import get_runtime_settings


APP_TITLE = "SpecForge Customer QA UI"
DOMAIN_PRESETS = ["ecommerce", "healthcare", "logistics", "hr"]
DOMAIN_PRESET_SET = set(DOMAIN_PRESETS)
SUPPORTED_SCRIPT_KINDS = [
    "python_pytest",
    "javascript_jest",
    "curl_script",
    "java_restassured",
]
SUPPORTED_REPORT_MODES = {"full", "executive", "summary", "technical"}
REPO_ROOT = Path(__file__).resolve().parent
JOB_ROOT = Path("/tmp/qa_ui_runs")
CHECKPOINT_ROOT = Path("/tmp/qa_ui_checkpoints")
SPEC_UPLOAD_ROOT = Path("/tmp/qa_ui_uploaded_specs")
JOB_ROOT.mkdir(parents=True, exist_ok=True)
CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
SPEC_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
SPEC_UPLOAD_MAX_BYTES = max(
    32 * 1024,
    int(str(os.getenv("QA_UI_SPEC_UPLOAD_MAX_BYTES", str(5 * 1024 * 1024))).strip() or str(5 * 1024 * 1024)),
)
SPEC_UPLOAD_ALLOWED_EXTENSIONS = {".yaml", ".yml", ".json"}
JOB_STATE_PATH = Path(
    str(os.getenv("QA_UI_JOB_STATE_PATH", "/tmp/qa_ui_jobs_state.json")).strip()
).expanduser()
MAX_JOB_PERSIST_LOG_LINES = max(
    100, int(str(os.getenv("QA_UI_JOB_PERSIST_LOG_LINES", "1000")).strip() or "1000")
)
MAX_CONCURRENT_JOBS = max(
    1, int(str(os.getenv("QA_UI_MAX_CONCURRENT_JOBS", "3")).strip() or "3")
)
MAX_QUEUED_JOBS = max(
    1, int(str(os.getenv("QA_UI_MAX_QUEUED_JOBS", "64")).strip() or "64")
)
API_AUTH_MODE = str(
    os.getenv("QA_API_AUTH_MODE", "token_or_loopback")
).strip().lower()
if API_AUTH_MODE not in {"off", "token", "token_or_loopback"}:
    API_AUTH_MODE = "token_or_loopback"
API_AUTH_TOKEN = str(os.getenv("QA_API_AUTH_TOKEN", "")).strip()
API_AUTH_HEADER = "x-api-key"
RL_PERIODIC_ENABLED = str(os.getenv("QA_RL_PERIODIC_ENABLED", "1")).strip().lower() not in {"0", "false", "off"}
RL_PERIODIC_INTERVAL_SEC = max(30, int(os.getenv("QA_RL_PERIODIC_INTERVAL_SEC", "300") or 300))
RL_PERIODIC_MAX_STEPS = max(1, int(os.getenv("QA_RL_PERIODIC_MAX_STEPS", "25") or 25))
RL_PERIODIC_MIN_BUFFER = max(1, int(os.getenv("QA_RL_PERIODIC_MIN_BUFFER", "32") or 32))
RUNTIME_SETTINGS = get_runtime_settings()
DEFAULT_ENVIRONMENT_PROFILE = str(
    RUNTIME_SETTINGS.default_environment_profile or "mock"
).lower()
SUPPORTED_ENVIRONMENT_PROFILES = {
    str(item).strip().lower()
    for item in (RUNTIME_SETTINGS.supported_environment_profiles or ())
    if str(item).strip()
}
if DEFAULT_ENVIRONMENT_PROFILE not in SUPPORTED_ENVIRONMENT_PROFILES:
    DEFAULT_ENVIRONMENT_PROFILE = "mock"
DEFAULT_BASE_URL = str(RUNTIME_SETTINGS.default_base_url)


def _bootstrap_runtime_env() -> None:
    """Best-effort .env loading so API-launched jobs inherit OPENAI_API_KEY."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    candidates = [
        REPO_ROOT / ".env",
        REPO_ROOT.parent / ".env",
        Path.cwd() / ".env",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        env_path = candidate.expanduser().resolve()
        key = str(env_path)
        if key in seen:
            continue
        seen.add(key)
        if env_path.is_file():
            load_dotenv(dotenv_path=env_path, override=False)


_bootstrap_runtime_env()

MAX_LOG_LINES = 6000

app = FastAPI(title=APP_TITLE)


def _default_allowed_origins_csv() -> str:
    origins: List[str] = []
    for port in range(3000, 3011):
        origins.append(f"http://localhost:{port}")
        origins.append(f"http://127.0.0.1:{port}")
    return ",".join(origins)


_allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "QA_UI_ALLOWED_ORIGINS",
        _default_allowed_origins_csv(),
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _api_auth_guard(request: Request, call_next):
    path = str(request.url.path or "")
    if not path.startswith("/api/"):
        return await call_next(request)
    if path == "/api/ping" or API_AUTH_MODE == "off":
        return await call_next(request)

    if API_AUTH_MODE == "token":
        if not _request_has_valid_api_token(request):
            return JSONResponse(status_code=401, content={"detail": "missing_or_invalid_api_token"})
        return await call_next(request)

    # token_or_loopback
    if _is_loopback_client(request) or _request_has_valid_api_token(request):
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "api_access_restricted"})

_jobs_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}
_job_runtime_secrets: Dict[str, Dict[str, Any]] = {}
_periodic_lock = threading.Lock()
_periodic_tick_lock = threading.Lock()
_periodic_stop_event = threading.Event()
_periodic_thread: Optional[threading.Thread] = None
_job_executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_JOBS,
    thread_name_prefix="qa-job-runner",
)
_checkpoint_locks_guard = threading.Lock()
_checkpoint_locks: Dict[str, threading.Lock] = {}
_periodic_state: Dict[str, Any] = {
    "enabled": RL_PERIODIC_ENABLED,
    "interval_sec": RL_PERIODIC_INTERVAL_SEC,
    "max_steps": RL_PERIODIC_MAX_STEPS,
    "min_buffer": RL_PERIODIC_MIN_BUFFER,
    "running": False,
    "runs_total": 0,
    "runs_with_training": 0,
    "last_started_at": None,
    "last_completed_at": None,
    "last_trigger": None,
    "last_status": "idle",
    "last_error": "",
    "last_summary": {},
    "last_results": [],
}

DOMAIN_TOKEN_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
RUN_TOKEN_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _checkpoint_lock(path: Path) -> threading.Lock:
    key = str(path.expanduser().resolve())
    with _checkpoint_locks_guard:
        lock = _checkpoint_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _checkpoint_locks[key] = lock
        return lock


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.tmp.{uuid.uuid4().hex}")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    os.replace(tmp_path, target)


def _persist_jobs_state_unlocked() -> None:
    serialized_jobs: Dict[str, Dict[str, Any]] = {}
    for job_id, job in _jobs.items():
        if not isinstance(job, dict):
            continue
        item = dict(job)
        logs = list(item.get("logs", []) or [])
        if len(logs) > MAX_JOB_PERSIST_LOG_LINES:
            logs = logs[-MAX_JOB_PERSIST_LOG_LINES:]
        item["logs"] = logs
        serialized_jobs[str(job_id)] = item
    payload = {
        "version": 1,
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "jobs": serialized_jobs,
    }
    _atomic_write_json(JOB_STATE_PATH, payload)


def _persist_jobs_state() -> None:
    with _jobs_lock:
        _persist_jobs_state_unlocked()


def _load_jobs_state() -> None:
    if not JOB_STATE_PATH.exists():
        return
    try:
        payload = json.loads(JOB_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    loaded = payload.get("jobs", {}) if isinstance(payload, dict) else {}
    if not isinstance(loaded, dict):
        return
    with _jobs_lock:
        for job_id, item in loaded.items():
            if not isinstance(item, dict):
                continue
            job_key = str(job_id).strip()
            if not job_key:
                continue
            _jobs[job_key] = {
                "id": str(item.get("id", job_key) or job_key),
                "status": str(item.get("status", "failed") or "failed"),
                "created_at": str(item.get("created_at", "") or ""),
                "started_at": item.get("started_at"),
                "completed_at": item.get("completed_at"),
                "current_domain": item.get("current_domain"),
                "request": item.get("request", {}) if isinstance(item.get("request", {}), dict) else {},
                "logs": list(item.get("logs", []) or []),
                "results": item.get("results", {}) if isinstance(item.get("results", {}), dict) else {},
            }


def _request_has_valid_api_token(request: Request) -> bool:
    if not API_AUTH_TOKEN:
        return False
    token = str(request.headers.get(API_AUTH_HEADER, "")).strip()
    if token == API_AUTH_TOKEN:
        return True
    auth_header = str(request.headers.get("authorization", "")).strip()
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header.split(" ", 1)[1].strip()
        return candidate == API_AUTH_TOKEN
    return False


def _is_loopback_client(request: Request) -> bool:
    host = str((request.client.host if request.client else "") or "").strip().lower()
    return host in {"127.0.0.1", "::1", "localhost"}


def _sanitize_domain_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    token = re.sub(r"[^a-z0-9_-]+", "_", token)
    token = re.sub(r"_+", "_", token).strip("_")
    if not token:
        return ""
    return token[:64]


def _normalize_spec_path(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return str(Path(raw).expanduser().resolve())


OPENAPI_HTTP_METHODS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "options",
    "head",
    "trace",
}


def _normalize_operation_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = raw.split(None, 1)
    if len(parts) != 2:
        return ""
    method = str(parts[0]).strip().upper()
    path = str(parts[1]).strip()
    if method.lower() not in OPENAPI_HTTP_METHODS:
        return ""
    if not path:
        return ""
    if not path.startswith("/"):
        path = "/" + path
    return f"{method} {path}"


def _normalize_operation_selection(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        operation_id = _normalize_operation_id(item)
        if operation_id:
            out.append(operation_id)
    return list(dict.fromkeys(out))


def _normalize_request_mutation_rules(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    allowed_actions = {"delete", "set_empty", "invalid_type", "override_value"}
    for row in value:
        if not isinstance(row, dict):
            continue
        operation_id = _normalize_operation_id(row.get("operationId", ""))
        field_name = str(row.get("fieldName", "")).strip()
        action = str(row.get("action", "")).strip().lower()
        if not operation_id or not field_name or action not in allowed_actions:
            continue
        request_mode = str(row.get("requestMode", "auto")).strip() or "auto"
        out.append(
            {
                "operationId": operation_id,
                "requestMode": request_mode,
                "fieldName": field_name,
                "action": action,
                "value": str(row.get("value", "")),
                "note": str(row.get("note", "")).strip(),
            }
        )
        if len(out) >= 200:
            break
    return out


def _normalize_scope_mode(value: Any) -> str:
    raw = str(value or "full_spec").strip().lower()
    return "advanced" if raw == "advanced" else "full_spec"


def _normalize_customer_intent(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:4000]


def _normalize_environment_targets(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, str] = {}
    profile_alias = {
        "prod": "prod_safe",
        "production": "prod_safe",
        "prod_safe": "prod_safe",
        "staging": "staging",
        "mock": "mock",
    }
    for raw_profile, raw_url in list(value.items())[:16]:
        profile_key = str(raw_profile or "").strip().lower()
        profile = profile_alias.get(profile_key, profile_key)
        if profile not in SUPPORTED_ENVIRONMENT_PROFILES:
            continue
        url = str(raw_url or "").strip()
        if not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        out[profile] = url.rstrip("/")
    return out


def _normalize_release_gate(
    value: Any,
    *,
    pass_threshold: float,
) -> Dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    enabled = str(payload.get("enabled", "1")).strip().lower() not in {
        "0",
        "false",
        "off",
    }
    safe_mode = str(payload.get("safeModeOnFail", "1")).strip().lower() not in {
        "0",
        "false",
        "off",
    }

    def _clamped_number(
        raw: Any,
        *,
        default: float,
        minimum: float = 0.0,
        maximum: float = 1.0,
    ) -> float:
        try:
            num = float(raw)
        except Exception:
            num = float(default)
        return max(float(minimum), min(float(maximum), num))

    return {
        "enabled": bool(enabled),
        "passFloor": _clamped_number(
            payload.get("passFloor", pass_threshold),
            default=float(pass_threshold),
        ),
        "flakyThreshold": _clamped_number(
            payload.get("flakyThreshold", 0.15),
            default=0.15,
        ),
        "maxPassDrop": _clamped_number(
            payload.get("maxPassDrop", 0.08),
            default=0.08,
        ),
        "maxRewardDrop": _clamped_number(
            payload.get("maxRewardDrop", 0.10),
            default=0.10,
        ),
        "minGamQuality": _clamped_number(
            payload.get("minGamQuality", 0.55),
            default=0.55,
        ),
        "safeModeOnFail": bool(safe_mode),
    }


def _normalize_critical_assertions(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in value[:200]:
        if not isinstance(row, dict):
            continue
        operation_id = _normalize_operation_id(row.get("operationId", ""))
        if not operation_id:
            continue
        expected_status: Optional[int] = None
        try:
            if row.get("expectedStatus") is not None:
                expected_status = int(row.get("expectedStatus"))
        except Exception:
            expected_status = None
        allowed_statuses: List[int] = []
        if isinstance(row.get("allowedStatuses"), list):
            for raw_status in row.get("allowedStatuses", []):
                try:
                    allowed_statuses.append(int(raw_status))
                except Exception:
                    continue
        min_pass_count = 1
        try:
            min_pass_count = max(1, int(row.get("minPassCount", 1)))
        except Exception:
            min_pass_count = 1
        out.append(
            {
                "operationId": operation_id,
                "expectedStatus": expected_status,
                "allowedStatuses": sorted(set(allowed_statuses)),
                "minPassCount": int(min_pass_count),
                "note": str(row.get("note", "")).strip()[:300],
            }
        )
    return out


def _normalize_resource_limits(value: Any) -> Dict[str, Any]:
    payload = value if isinstance(value, dict) else {}

    def _bounded_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            value_int = int(raw)
        except Exception:
            value_int = int(default)
        return max(int(minimum), min(int(maximum), int(value_int)))

    def _bounded_float(raw: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            value_num = float(raw)
        except Exception:
            value_num = float(default)
        return max(float(minimum), min(float(maximum), float(value_num)))

    return {
        "liveRequestTimeoutSec": _bounded_float(
            payload.get("liveRequestTimeoutSec", 12.0),
            default=12.0,
            minimum=0.1,
            maximum=120.0,
        ),
        "scriptExecMaxRuntimeSec": _bounded_float(
            payload.get("scriptExecMaxRuntimeSec", 120.0),
            default=120.0,
            minimum=1.0,
            maximum=1800.0,
        ),
        "llmTimeoutSec": _bounded_int(
            payload.get("llmTimeoutSec", 45),
            default=45,
            minimum=1,
            maximum=600,
        ),
        "llmRetries": _bounded_int(
            payload.get("llmRetries", 1),
            default=1,
            minimum=0,
            maximum=5,
        ),
    }


def _normalize_report_mode(value: Any) -> str:
    mode = str(value or "full").strip().lower() or "full"
    return mode if mode in SUPPORTED_REPORT_MODES else "full"


def _normalize_auth_profiles(value: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for raw_operation, raw_profile in list(value.items())[:300]:
        operation_id = _normalize_operation_id(raw_operation)
        profile = raw_profile if isinstance(raw_profile, dict) else {}
        if not operation_id or not profile:
            continue
        mode = _normalize_auth_mode(profile.get("authMode", profile.get("mode", "none")))
        normalized: Dict[str, Any] = {"authMode": mode}
        if mode == "bearer":
            token = _strip_bearer_prefix(profile.get("bearerToken", ""))
            if token:
                normalized["bearerToken"] = token
        elif mode == "api_key":
            normalized["apiKeyName"] = str(
                profile.get("apiKeyName", "X-API-Key")
            ).strip() or "X-API-Key"
            normalized["apiKeyIn"] = (
                "query"
                if str(profile.get("apiKeyIn", "header")).strip().lower() == "query"
                else "header"
            )
            key_value = str(profile.get("apiKeyValue", "")).strip()
            if key_value:
                normalized["apiKeyValue"] = key_value
        out[operation_id] = normalized
    return out


def _redact_auth_profiles(auth_profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for operation_id, profile in (auth_profiles or {}).items():
        if not isinstance(profile, dict):
            continue
        mode = _normalize_auth_mode(profile.get("authMode", "none"))
        item: Dict[str, Any] = {"authMode": mode}
        if mode == "bearer":
            item["bearerTokenProvided"] = bool(
                _strip_bearer_prefix(profile.get("bearerToken", ""))
            )
        elif mode == "api_key":
            item["apiKeyName"] = str(profile.get("apiKeyName", "")).strip()
            item["apiKeyIn"] = (
                "query"
                if str(profile.get("apiKeyIn", "header")).strip().lower() == "query"
                else "header"
            )
            item["apiKeyValueProvided"] = bool(str(profile.get("apiKeyValue", "")).strip())
        out[str(operation_id)] = item
    return out


def _compose_prompt_with_runtime_scope(
    base_prompt: Optional[str],
    *,
    customer_intent: Optional[str],
    scope_mode: str,
    include_operations: List[str],
    exclude_operations: List[str],
    request_mutation_rules: List[Dict[str, Any]],
    critical_operations: Optional[List[str]] = None,
    critical_assertions: Optional[List[Dict[str, Any]]] = None,
    report_mode: Optional[str] = None,
) -> Optional[str]:
    prompt = str(base_prompt or "").strip()
    mode = str(scope_mode or "full_spec").strip().lower() or "full_spec"
    lines: List[str] = []
    if customer_intent and str(customer_intent).strip():
        lines.append(f"Customer intent: {str(customer_intent).strip()}")
    lines.append(
        "Execution scope mode: "
        + ("advanced" if mode == "advanced" else "full_openapi_spec")
    )
    if include_operations:
        lines.append(
            "Include operations: " + " | ".join(include_operations[:40])
        )
    if exclude_operations:
        lines.append(
            "Exclude operations: " + " | ".join(exclude_operations[:40])
        )
    if request_mutation_rules:
        compact = [
            (
                f"{item.get('operationId', '')} -> "
                + f"{item.get('action', '')}({item.get('fieldName', '')})"
            )
            for item in request_mutation_rules[:40]
            if isinstance(item, dict)
        ]
        if compact:
            lines.append("Customer mutation rules: " + " | ".join(compact))
    if critical_operations:
        lines.append(
            "Critical operations: " + " | ".join(list(critical_operations)[:40])
        )
    if critical_assertions:
        compact_assertions = []
        for item in list(critical_assertions)[:40]:
            if not isinstance(item, dict):
                continue
            operation_id = str(item.get("operationId", "")).strip()
            expected_status = item.get("expectedStatus")
            allowed_statuses = item.get("allowedStatuses", [])
            if expected_status is not None:
                compact_assertions.append(f"{operation_id} => expect {expected_status}")
            elif isinstance(allowed_statuses, list) and allowed_statuses:
                compact_assertions.append(
                    f"{operation_id} => allow {','.join(str(v) for v in allowed_statuses[:8])}"
                )
            else:
                compact_assertions.append(f"{operation_id} => require pass evidence")
        if compact_assertions:
            lines.append("Critical assertions: " + " | ".join(compact_assertions))
    if report_mode:
        lines.append(f"Report mode: {str(report_mode).strip().lower()}")

    if not lines:
        return prompt or None

    runtime_section = "\n".join(
        ["", "Backend Runtime Scope", *lines]
    ).strip()
    if runtime_section in prompt:
        return prompt
    if prompt:
        return f"{prompt}\n\n{runtime_section}".strip()
    return runtime_section.strip()


def _load_openapi_document(spec_path: Path) -> Tuple[Dict[str, Any], str]:
    raw = spec_path.read_text(encoding="utf-8")
    ext = spec_path.suffix.lower()
    if ext == ".json":
        return json.loads(raw), "json"
    if ext in {".yaml", ".yml"}:
        data = yaml.safe_load(raw)
        return (data if isinstance(data, dict) else {}), "yaml"
    # Fallback: try JSON then YAML.
    try:
        return json.loads(raw), "json"
    except Exception:
        data = yaml.safe_load(raw)
        return (data if isinstance(data, dict) else {}), "yaml"


def _filter_openapi_operations(
    payload: Dict[str, Any],
    include_operations: List[str],
    exclude_operations: List[str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    include_set = set(include_operations or [])
    exclude_set = set(exclude_operations or [])
    if not include_set and not exclude_set:
        return payload, {
            "total_operations": 0,
            "kept_operations": 0,
            "dropped_operations": 0,
            "applied": False,
            "reason": "no_scope_filters",
        }

    doc = copy.deepcopy(payload if isinstance(payload, dict) else {})
    paths = doc.get("paths", {})
    if not isinstance(paths, dict):
        return doc, {
            "total_operations": 0,
            "kept_operations": 0,
            "dropped_operations": 0,
            "applied": False,
            "reason": "paths_not_found",
        }

    new_paths: Dict[str, Any] = {}
    total_ops = 0
    kept_ops = 0
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        kept_item: Dict[str, Any] = {}
        path_level: Dict[str, Any] = {}
        for key, value in path_item.items():
            method = str(key or "").strip().lower()
            if method in OPENAPI_HTTP_METHODS:
                total_ops += 1
                operation_id = _normalize_operation_id(f"{method.upper()} {path}")
                include_ok = (not include_set) or (operation_id in include_set)
                exclude_ok = operation_id not in exclude_set
                if include_ok and exclude_ok:
                    kept_item[key] = value
                    kept_ops += 1
            else:
                path_level[key] = value
        if kept_item:
            new_paths[str(path)] = {**path_level, **kept_item}

    if total_ops > 0 and kept_ops == 0:
        return payload, {
            "total_operations": total_ops,
            "kept_operations": total_ops,
            "dropped_operations": 0,
            "applied": False,
            "reason": "scope_would_drop_all_operations",
        }

    doc["paths"] = new_paths
    return doc, {
        "total_operations": total_ops,
        "kept_operations": kept_ops,
        "dropped_operations": max(0, total_ops - kept_ops),
        "applied": total_ops > 0,
        "reason": "scope_applied",
    }


def _write_openapi_document(spec_path: Path, payload: Dict[str, Any], fmt: str) -> None:
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        spec_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return
    spec_path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _build_scoped_spec_for_domain(
    *,
    domain: str,
    source_spec_path: str,
    output_dir: Path,
    include_operations: List[str],
    exclude_operations: List[str],
) -> Tuple[str, Dict[str, Any]]:
    source = Path(source_spec_path).expanduser().resolve()
    payload, fmt = _load_openapi_document(source)
    filtered, summary = _filter_openapi_operations(
        payload,
        include_operations=include_operations,
        exclude_operations=exclude_operations,
    )
    if not bool(summary.get("applied", False)):
        summary["source_spec_path"] = str(source)
        return str(source), summary

    suffix = source.suffix.lower()
    if suffix not in {".json", ".yaml", ".yml"}:
        suffix = ".json" if fmt == "json" else ".yaml"
    scoped_name = f"{_sanitize_domain_token(domain) or 'domain'}_scoped_openapi{suffix}"
    scoped_path = output_dir / scoped_name
    _write_openapi_document(scoped_path, filtered, fmt)
    summary["source_spec_path"] = str(source)
    summary["scoped_spec_path"] = str(scoped_path.resolve())
    return str(scoped_path.resolve()), summary


def _normalize_auth_mode(value: Any) -> str:
    mode = str(value or "none").strip().lower()
    if mode in {"bearer", "api_key", "basic", "form"}:
        return mode
    return "none"


def _strip_bearer_prefix(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("bearer "):
        return raw.split(" ", 1)[1].strip()
    return raw


def _extract_runtime_auth_secrets(auth_mode: str, auth_context: Any) -> Dict[str, Any]:
    context = auth_context if isinstance(auth_context, dict) else {}
    mode = _normalize_auth_mode(auth_mode)
    if mode == "bearer":
        token = _strip_bearer_prefix(context.get("bearerToken", ""))
        if token:
            return {"bearerToken": token}
    if mode == "api_key":
        value = str(context.get("apiKeyValue", "")).strip()
        if value:
            return {"apiKeyValue": value}
    if mode == "basic":
        value = str(context.get("password", ""))
        if value:
            return {"password": value}
    if mode == "form":
        value = str(context.get("password", ""))
        if value:
            return {"password": value}
    return {}


def _redact_auth_context(auth_mode: str, auth_context: Any) -> Dict[str, Any]:
    context = auth_context if isinstance(auth_context, dict) else {}
    mode = _normalize_auth_mode(auth_mode)
    if mode == "bearer":
        token = _strip_bearer_prefix(context.get("bearerToken", ""))
        return {"bearerTokenProvided": bool(token)}
    if mode == "api_key":
        return {
            "apiKeyName": str(context.get("apiKeyName", "")).strip(),
            "apiKeyIn": "query"
            if str(context.get("apiKeyIn", "header")).strip().lower() == "query"
            else "header",
            "apiKeyValueProvided": bool(str(context.get("apiKeyValue", "")).strip()),
        }
    if mode == "basic":
        return {
            "username": str(context.get("username", "")).strip(),
            "passwordProvided": bool(str(context.get("password", ""))),
        }
    if mode == "form":
        return {
            "formLoginPath": str(context.get("formLoginPath", "")).strip(),
            "formMethod": str(context.get("formMethod", "POST")).strip().upper() or "POST",
            "usernameField": str(context.get("usernameField", "")).strip(),
            "passwordField": str(context.get("passwordField", "")).strip(),
            "username": str(context.get("username", "")).strip(),
            "tokenPath": str(context.get("tokenPath", "")).strip(),
            "passwordProvided": bool(str(context.get("password", ""))),
        }
    return {}


class RunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    domains: List[str] = Field(default_factory=lambda: ["ecommerce"])
    spec_paths: Dict[str, str] = Field(default_factory=dict, alias="specPaths")
    tenant_id: str = Field(default="customer_default", alias="tenantId")
    workspace_id: Optional[str] = Field(default=None, alias="workspaceId")
    prompt: Optional[str] = None
    script_kind: str = Field(default="python_pytest", alias="scriptKind")
    max_scenarios: int = Field(default=64, alias="maxScenarios")
    max_runtime_sec: Optional[int] = Field(default=None, alias="maxRuntimeSec")
    llm_token_cap: Optional[int] = Field(default=None, alias="llmTokenCap")
    environment_profile: str = Field(default=DEFAULT_ENVIRONMENT_PROFILE, alias="environmentProfile")
    environment_targets: Dict[str, str] = Field(default_factory=dict, alias="environmentTargets")
    auth_mode: str = Field(default="none", alias="authMode")
    auth_context: Dict[str, Any] = Field(default_factory=dict, alias="authContext")
    auth_profiles: Dict[str, Dict[str, Any]] = Field(default_factory=dict, alias="authProfiles")
    customer_intent: Optional[str] = Field(default=None, alias="customerIntent")
    scope_mode: str = Field(default="full_spec", alias="scopeMode")
    include_operations: List[str] = Field(default_factory=list, alias="includeOperations")
    exclude_operations: List[str] = Field(default_factory=list, alias="excludeOperations")
    request_mutation_rules: List[Dict[str, Any]] = Field(default_factory=list, alias="requestMutationRules")
    critical_operations: List[str] = Field(default_factory=list, alias="criticalOperations")
    critical_assertions: List[Dict[str, Any]] = Field(default_factory=list, alias="criticalAssertions")
    rl_train_mode: str = Field(default="periodic", alias="rlTrainMode")
    release_gate: Dict[str, Any] = Field(default_factory=dict, alias="releaseGate")
    resource_limits: Dict[str, Any] = Field(default_factory=dict, alias="resourceLimits")
    report_mode: str = Field(default="full", alias="reportMode")
    pass_threshold: float = Field(default=0.70, alias="passThreshold")
    base_url: str = Field(default=DEFAULT_BASE_URL, alias="baseUrl")
    customer_mode: bool = Field(default=True, alias="customerMode")
    verify_persistence: bool = Field(default=True, alias="verifyPersistence")
    customer_root: str = Field(default=str(Path.home() / ".spec_test_pilot"), alias="customerRoot")

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, value: List[str]) -> List[str]:
        normalized = [_sanitize_domain_token(v) for v in value if str(v).strip()]
        normalized = [token for token in normalized if token]
        if not normalized:
            raise ValueError("Select at least one domain")
        invalid = [v for v in normalized if not DOMAIN_TOKEN_PATTERN.match(v)]
        if invalid:
            raise ValueError(f"Invalid domain ids: {', '.join(invalid)}")
        return list(dict.fromkeys(normalized))

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            return "customer_default"
        if not RUN_TOKEN_PATTERN.match(token):
            raise ValueError("tenantId must match [a-zA-Z0-9_-]{1,64}")
        return token

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        if not token:
            return None
        if not RUN_TOKEN_PATTERN.match(token):
            raise ValueError("workspaceId must match [a-zA-Z0-9_-]{1,64}")
        return token

    @field_validator("spec_paths")
    @classmethod
    def validate_spec_paths(cls, value: Dict[str, str]) -> Dict[str, str]:
        if not isinstance(value, dict):
            return {}
        normalized: Dict[str, str] = {}
        for raw_domain, raw_path in value.items():
            domain = _sanitize_domain_token(raw_domain)
            if not domain:
                continue
            if not DOMAIN_TOKEN_PATTERN.match(domain):
                raise ValueError(f"Invalid domain id in specPaths: {raw_domain}")
            spec_path = _normalize_spec_path(raw_path)
            if not spec_path:
                continue
            if not Path(spec_path).exists():
                raise ValueError(f"Spec file not found for domain '{domain}': {spec_path}")
            normalized[domain] = spec_path
        return normalized

    @field_validator("max_scenarios")
    @classmethod
    def validate_max_scenarios(cls, value: int) -> int:
        if value < 1:
            return 1
        if value > 500:
            return 500
        return value

    @field_validator("max_runtime_sec")
    @classmethod
    def validate_max_runtime_sec(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        num = int(value)
        if num <= 0:
            return None
        return min(7200, num)

    @field_validator("llm_token_cap")
    @classmethod
    def validate_llm_token_cap(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        num = int(value)
        if num <= 0:
            return None
        return min(16000, max(64, num))

    @field_validator("environment_profile")
    @classmethod
    def validate_environment_profile(cls, value: str) -> str:
        profile = str(value or DEFAULT_ENVIRONMENT_PROFILE).strip().lower()
        if profile not in SUPPORTED_ENVIRONMENT_PROFILES:
            return DEFAULT_ENVIRONMENT_PROFILE
        return profile

    @field_validator("environment_targets")
    @classmethod
    def validate_environment_targets(cls, value: Dict[str, str]) -> Dict[str, str]:
        return _normalize_environment_targets(value)

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        return _normalize_auth_mode(value)

    @field_validator("auth_context")
    @classmethod
    def validate_auth_context(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return dict(value)

    @field_validator("auth_profiles")
    @classmethod
    def validate_auth_profiles(
        cls, value: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        return _normalize_auth_profiles(value)

    @field_validator("customer_intent")
    @classmethod
    def validate_customer_intent(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_customer_intent(value)

    @field_validator("scope_mode")
    @classmethod
    def validate_scope_mode(cls, value: str) -> str:
        return _normalize_scope_mode(value)

    @field_validator("include_operations")
    @classmethod
    def validate_include_operations(cls, value: List[str]) -> List[str]:
        return _normalize_operation_selection(value)

    @field_validator("exclude_operations")
    @classmethod
    def validate_exclude_operations(cls, value: List[str]) -> List[str]:
        return _normalize_operation_selection(value)

    @field_validator("request_mutation_rules")
    @classmethod
    def validate_request_mutation_rules(
        cls, value: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return _normalize_request_mutation_rules(value)

    @field_validator("critical_operations")
    @classmethod
    def validate_critical_operations(cls, value: List[str]) -> List[str]:
        return _normalize_operation_selection(value)

    @field_validator("critical_assertions")
    @classmethod
    def validate_critical_assertions(
        cls, value: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return _normalize_critical_assertions(value)

    @field_validator("script_kind")
    @classmethod
    def validate_script_kind(cls, value: str) -> str:
        normalized = str(value).strip().lower().replace("-", "_")
        if normalized not in SUPPORTED_SCRIPT_KINDS:
            allowed = ", ".join(SUPPORTED_SCRIPT_KINDS)
            raise ValueError(f"Unsupported script kind: {value}. Allowed: {allowed}")
        return normalized

    @field_validator("rl_train_mode")
    @classmethod
    def validate_rl_train_mode(cls, value: str) -> str:
        normalized = str(value or "periodic").strip().lower()
        return "periodic" if normalized != "periodic" else normalized

    @field_validator("release_gate")
    @classmethod
    def validate_release_gate(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _normalize_release_gate(value, pass_threshold=0.70)

    @field_validator("resource_limits")
    @classmethod
    def validate_resource_limits(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _normalize_resource_limits(value)

    @field_validator("report_mode")
    @classmethod
    def validate_report_mode(cls, value: str) -> str:
        return _normalize_report_mode(value)

    @field_validator("pass_threshold")
    @classmethod
    def validate_pass_threshold(cls, value: float) -> float:
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return float(value)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        raw = str(value or DEFAULT_BASE_URL).strip()
        if not raw:
            return DEFAULT_BASE_URL
        if not (raw.startswith("http://") or raw.startswith("https://")):
            raise ValueError("baseUrl must start with http:// or https://")
        return raw.rstrip("/")

    @field_validator("customer_root")
    @classmethod
    def validate_customer_root(cls, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return str(Path.home() / ".spec_test_pilot")
        resolved = Path(raw).expanduser().resolve()
        return str(resolved)


def _append_log(job: Dict[str, Any], line: str) -> None:
    logs = job.setdefault("logs", [])
    logs.append(line.rstrip("\n"))
    if len(logs) > MAX_LOG_LINES:
        del logs[: len(logs) - MAX_LOG_LINES]


def _load_report_artifacts(report_json_path: Path) -> Tuple[Dict[str, Any], Dict[str, str]]:
    if not report_json_path.exists():
        return {}, {}
    try:
        payload = json.loads(report_json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}

    summary = payload.get("summary", {})
    training_stats = payload.get("agent_lightning", {}).get("training_stats", {})
    generated_raw = payload.get("generated_test_files", {})
    generated_tests: Dict[str, str] = {}
    if isinstance(generated_raw, dict):
        for key, value in generated_raw.items():
            if isinstance(value, str) and value.strip():
                generated_tests[str(key)] = str(value)

    summary_payload = {
        "total_scenarios": summary.get("total_scenarios"),
        "passed_scenarios": summary.get("passed_scenarios"),
        "failed_scenarios": summary.get("failed_scenarios"),
        "pass_rate": summary.get("pass_rate"),
        "meets_quality_gate": summary.get("meets_quality_gate"),
        "quality_gate_fail_reasons": summary.get("quality_gate_fail_reasons"),
        "quality_gate_warnings": summary.get("quality_gate_warnings"),
        "contract_checks_run": summary.get("contract_checks_run"),
        "contract_check_failures": summary.get("contract_check_failures"),
        "critical_gate": summary.get("critical_gate", {}),
        "corrected_expectations": summary.get("corrected_expectations"),
        "runtime_cap_hit": summary.get("runtime_cap_hit"),
        "runtime_skipped_scenarios": summary.get("runtime_skipped_scenarios"),
        "environment_profile": summary.get("environment_profile"),
        "script_kind": payload.get("metadata", {}).get("script_kind"),
        "rl_train_mode": payload.get("metadata", {}).get("rl_train_mode") or training_stats.get("train_mode"),
        "workspace_id": payload.get("metadata", {}).get("workspace_id"),
        "spec_key": payload.get("metadata", {}).get("spec_key"),
        "run_id": payload.get("metadata", {}).get("run_id"),
        "rl_training_steps": training_stats.get("rl_training_steps"),
        "rl_buffer_size": training_stats.get("rl_buffer_size"),
        "selection_algorithm": payload.get("selection_policy", {}).get("algorithm"),
        "selection_selected_count": payload.get("selection_policy", {}).get("selected_count"),
        "selection_candidate_count": payload.get("selection_policy", {}).get("candidate_count"),
        "run_reward": payload.get("learning", {}).get("feedback", {}).get("run_reward"),
        "learning_delta_status": payload.get("learning", {}).get("learning_delta_status"),
        "gam_context_quality": (payload.get("gam_context_pack", {}) or {}).get("quality_score"),
        "spec_operations_total": (payload.get("spec_intelligence", {}) or {}).get("operations_total"),
        "dependency_edge_count": ((payload.get("spec_intelligence", {}) or {}).get("dependency_graph", {}) or {}).get("edge_count"),
    }
    return summary_payload, generated_tests


def _read_report_payload(report_json_path: Path) -> Dict[str, Any]:
    if not report_json_path.exists():
        raise HTTPException(status_code=404, detail="report file missing")
    try:
        return json.loads(report_json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"invalid report json: {exc}") from exc


def _project_report_payload(payload: Dict[str, Any], view: str) -> Dict[str, Any]:
    mode = _normalize_report_mode(view)
    if mode in {"full", "technical"}:
        return payload

    summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}
    metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {}
    failed_examples = (
        list(summary.get("failed_examples", []) or [])[:10]
        if isinstance(summary, dict)
        else []
    )
    projected = {
        "summary": {
            "total_scenarios": summary.get("total_scenarios"),
            "passed_scenarios": summary.get("passed_scenarios"),
            "failed_scenarios": summary.get("failed_scenarios"),
            "pass_rate": summary.get("pass_rate"),
            "pass_threshold": summary.get("pass_threshold"),
            "meets_quality_gate": summary.get("meets_quality_gate"),
            "quality_gate_fail_reasons": summary.get("quality_gate_fail_reasons"),
            "quality_gate_warnings": summary.get("quality_gate_warnings"),
            "failure_taxonomy_breakdown": summary.get("failure_taxonomy_breakdown", {}),
            "failed_examples": failed_examples,
            "failure_diagnosis": summary.get("failure_diagnosis", {}),
        },
        "metadata": {
            "spec_title": metadata.get("spec_title"),
            "script_kind": metadata.get("script_kind"),
            "environment_profile": metadata.get("environment_profile"),
            "runtime_auth_mode": metadata.get("runtime_auth_mode"),
            "runtime_caps": metadata.get("runtime_caps", {}),
            "run_id": metadata.get("run_id"),
        },
    }
    if mode == "summary":
        return projected
    projected["selection_policy"] = payload.get("selection_policy", {})
    projected["learning"] = payload.get("learning", {})
    projected["critical_gate"] = summary.get("critical_gate", {})
    return projected


def _domain_result_or_404(job_id: str, domain: str) -> Dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        result = (job.get("results") or {}).get(domain)
    if not result:
        raise HTTPException(status_code=404, detail="domain result not found")
    return result


def _resolve_domain_for_run(job_id: str, domain: Optional[str]) -> str:
    chosen = str(domain or "").strip().lower()
    if chosen:
        return chosen
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        domains = [str(item).strip().lower() for item in (job.get("request", {}).get("domains", []) or []) if str(item).strip()]
        if not domains:
            raise HTTPException(status_code=404, detail="no domains found for run")
        return domains[0]


def _resolve_generated_tests(result: Dict[str, Any]) -> Dict[str, str]:
    cached = result.get("generated_tests")
    if isinstance(cached, dict) and cached:
        return {
            str(k): str(v)
            for k, v in cached.items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        }

    report_json = Path(result.get("report_json", "")).resolve()
    payload = _read_report_payload(report_json)
    generated_raw = payload.get("generated_test_files", {})
    if not isinstance(generated_raw, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in generated_raw.items()
        if isinstance(k, str) and isinstance(v, str) and v.strip()
    }


def _canonical_path(path_value: str | Path) -> Path:
    # Normalize symlinked tmp paths (/tmp vs /private/tmp) for safe path checks.
    expanded = os.path.expanduser(str(path_value))
    return Path(os.path.realpath(expanded))


def _resolve_safe_generated_script_path(result: Dict[str, Any], kind: str) -> Path:
    generated = _resolve_generated_tests(result)
    script_path_raw = generated.get(kind)
    if not script_path_raw:
        raise HTTPException(status_code=404, detail=f"generated test script kind not found: {kind}")

    script_path = _canonical_path(script_path_raw)
    output_dir_raw = str(result.get("output_dir", "")).strip()
    if not output_dir_raw:
        raise HTTPException(status_code=500, detail="missing output directory for this run result")
    output_dir = _canonical_path(output_dir_raw)
    if not script_path.is_relative_to(output_dir):
        raise HTTPException(status_code=400, detail="generated script path is outside output directory")
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="generated script file missing")
    return script_path


def _job_payload(job: Dict[str, Any], tail: int) -> Dict[str, Any]:
    return {
        "id": job["id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "current_domain": job["current_domain"],
        "request": job["request"],
        "results": job["results"],
        "logs": job["logs"][-tail:],
    }


def _discover_periodic_checkpoints() -> List[Path]:
    candidates: set[Path] = set()
    for path in CHECKPOINT_ROOT.glob("*.pt"):
        if path.is_file():
            candidates.add(path.resolve())

    with _jobs_lock:
        for job in _jobs.values():
            if not isinstance(job, dict):
                continue
            for result in (job.get("results") or {}).values():
                if not isinstance(result, dict):
                    continue
                raw = str(result.get("checkpoint", "")).strip()
                if not raw:
                    continue
                path = Path(raw).expanduser().resolve()
                if path.is_file():
                    candidates.add(path)
    return sorted(candidates, key=lambda p: str(p))


def _run_periodic_training_checkpoint(checkpoint_path: Path) -> Dict[str, Any]:
    from spec_test_pilot.agent_lightning_v2 import AgentLightningTrainer

    lock = _checkpoint_lock(checkpoint_path)
    if not lock.acquire(timeout=0.5):
        return {
            "checkpoint": str(checkpoint_path),
            "result": {"status": "busy", "reason": "checkpoint_lock_busy"},
            "stats": {},
        }
    try:
        trainer = AgentLightningTrainer(
            checkpoint_path=str(checkpoint_path),
            checkpoint_autosave=True,
            gam_writeback=False,
            train_mode="periodic",
        )
        result = trainer.run_periodic_training(
            max_steps=RL_PERIODIC_MAX_STEPS,
            min_buffer_size=RL_PERIODIC_MIN_BUFFER,
        )
        stats = trainer.get_training_stats()
        return {
            "checkpoint": str(checkpoint_path),
            "result": result,
            "stats": stats,
        }
    finally:
        lock.release()


def _run_periodic_rl_tick(trigger: str) -> Dict[str, Any]:
    if not RL_PERIODIC_ENABLED:
        return {
            "status": "disabled",
            "trigger": trigger,
            "checkpoints": 0,
            "trained": 0,
            "skipped": 0,
            "failed": 0,
            "results": [],
        }

    if not _periodic_tick_lock.acquire(blocking=False):
        return {
            "status": "busy",
            "trigger": trigger,
            "checkpoints": 0,
            "trained": 0,
            "skipped": 0,
            "failed": 0,
            "results": [],
        }

    started_at = datetime.utcnow().isoformat() + "Z"
    with _periodic_lock:
        _periodic_state["running"] = True
        _periodic_state["last_started_at"] = started_at
        _periodic_state["last_trigger"] = str(trigger)
        _periodic_state["last_status"] = "running"
        _periodic_state["last_error"] = ""

    results: List[Dict[str, Any]] = []
    status = "completed"
    error_message = ""
    try:
        checkpoints = _discover_periodic_checkpoints()
        for checkpoint in checkpoints:
            try:
                payload = _run_periodic_training_checkpoint(checkpoint)
            except Exception as exc:  # pragma: no cover - runtime dependency specific
                payload = {
                    "checkpoint": str(checkpoint),
                    "result": {"status": "error", "reason": str(exc)},
                    "stats": {},
                }
            results.append(payload)
    except Exception as exc:  # pragma: no cover - defensive
        status = "error"
        error_message = str(exc)
    finally:
        _periodic_tick_lock.release()

    trained = 0
    skipped = 0
    failed = 0
    for item in results:
        result = item.get("result") if isinstance(item, dict) else {}
        result = result if isinstance(result, dict) else {}
        item_status = str(result.get("status", ""))
        if item_status == "completed" and int(result.get("trained_steps", 0) or 0) > 0:
            trained += 1
        elif item_status in {"completed", "skipped"}:
            skipped += 1
        else:
            failed += 1
            if status != "error":
                status = "partial_error"

    completed_at = datetime.utcnow().isoformat() + "Z"
    summary = {
        "status": status,
        "trigger": str(trigger),
        "checkpoints": len(results),
        "trained": trained,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }
    with _periodic_lock:
        _periodic_state["running"] = False
        _periodic_state["runs_total"] = int(_periodic_state.get("runs_total", 0)) + 1
        _periodic_state["runs_with_training"] = int(_periodic_state.get("runs_with_training", 0)) + (
            1 if trained > 0 else 0
        )
        _periodic_state["last_completed_at"] = completed_at
        _periodic_state["last_status"] = status
        _periodic_state["last_error"] = error_message
        _periodic_state["last_summary"] = {
            "checkpoints": len(results),
            "trained": trained,
            "skipped": skipped,
            "failed": failed,
        }
        _periodic_state["last_results"] = results[-10:]
    return summary


def _periodic_rl_worker() -> None:
    while not _periodic_stop_event.wait(RL_PERIODIC_INTERVAL_SEC):
        _run_periodic_rl_tick(trigger="timer")


def _start_periodic_rl_worker() -> None:
    global _periodic_thread
    if not RL_PERIODIC_ENABLED:
        return
    if _periodic_thread and _periodic_thread.is_alive():
        return
    _periodic_stop_event.clear()
    thread = threading.Thread(target=_periodic_rl_worker, name="qa-periodic-rl", daemon=True)
    thread.start()
    _periodic_thread = thread


def _stop_periodic_rl_worker() -> None:
    global _periodic_thread
    _periodic_stop_event.set()
    thread = _periodic_thread
    _periodic_thread = None
    if thread and thread.is_alive():
        thread.join(timeout=2.0)


def _run_job(job_id: str) -> None:
    trigger_periodic_tick = False
    try:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return
            req = dict(job["request"])
            runtime_auth_secrets = dict(_job_runtime_secrets.get(job_id) or {})
            job["status"] = "running"
            job["started_at"] = datetime.utcnow().isoformat() + "Z"
            _persist_jobs_state_unlocked()

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        failures = 0
        auth_mode = _normalize_auth_mode(req.get("auth_mode", "none"))
        runtime_bearer_token = _strip_bearer_prefix(
            runtime_auth_secrets.get("bearerToken", "")
        )
        runtime_api_key_value = str(runtime_auth_secrets.get("apiKeyValue", "")).strip()
        runtime_api_key_name = (
            str(runtime_auth_secrets.get("apiKeyName", "")).strip() or "X-API-Key"
        )
        runtime_api_key_in = (
            "query"
            if str(runtime_auth_secrets.get("apiKeyIn", "header")).strip().lower()
            == "query"
            else "header"
        )
        include_operations = _normalize_operation_selection(
            req.get("include_operations", [])
        )
        exclude_operations = _normalize_operation_selection(
            req.get("exclude_operations", [])
        )
        request_mutation_rules = _normalize_request_mutation_rules(
            req.get("request_mutation_rules", [])
        )
        scope_mode = _normalize_scope_mode(req.get("scope_mode", "full_spec"))
        customer_intent = _normalize_customer_intent(req.get("customer_intent"))
        critical_operations = _normalize_operation_selection(
            req.get("critical_operations", [])
        )
        critical_assertions = _normalize_critical_assertions(
            req.get("critical_assertions", [])
        )
        release_gate = _normalize_release_gate(
            req.get("release_gate", {}),
            pass_threshold=float(req.get("pass_threshold", 0.70) or 0.70),
        )
        resource_limits = _normalize_resource_limits(req.get("resource_limits", {}))
        report_mode = _normalize_report_mode(req.get("report_mode", "full"))
        auth_profiles_runtime = runtime_auth_secrets.get("authProfiles", {})
        if auth_mode == "bearer" and not runtime_bearer_token:
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job:
                    _append_log(
                        job,
                        "[auth] Bearer auth selected but no runtime bearer token was provided; "
                        + "default QA_AUTH_VALID_TOKEN will be used.",
                    )
        if auth_mode == "api_key" and not runtime_api_key_value:
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job:
                    _append_log(
                        job,
                        "[auth] API key auth selected but no runtime API key value was provided; "
                        + "auth-required scenarios may fail with 401.",
                    )

        for domain in req["domains"]:
            output_dir = JOB_ROOT / f"{ts}_{job_id}_{domain}"
            checkpoint = CHECKPOINT_ROOT / f"{req['tenant_id']}_{domain}.pt"
            checkpoint_lock = _checkpoint_lock(checkpoint)
            spec_paths = req.get("spec_paths") or {}
            spec_path_override = str(spec_paths.get(domain, "")).strip()
            scoped_spec_summary: Dict[str, Any] = {
                "applied": False,
                "reason": "not_requested",
                "scope_mode": scope_mode,
                "requested_include_operations": int(len(include_operations)),
                "requested_exclude_operations": int(len(exclude_operations)),
            }
            if scope_mode == "advanced" and spec_path_override and (
                include_operations or exclude_operations
            ):
                output_dir.mkdir(parents=True, exist_ok=True)
                try:
                    scoped_spec_path, scoped_spec_summary = _build_scoped_spec_for_domain(
                        domain=domain,
                        source_spec_path=spec_path_override,
                        output_dir=output_dir,
                        include_operations=include_operations,
                        exclude_operations=exclude_operations,
                    )
                    spec_path_override = str(scoped_spec_path).strip()
                except Exception as exc:
                    scoped_spec_summary = {
                        "applied": False,
                        "reason": "scope_filter_error",
                        "error": str(exc),
                        "scope_mode": scope_mode,
                        "requested_include_operations": int(len(include_operations)),
                        "requested_exclude_operations": int(len(exclude_operations)),
                    }

            cmd = [
                "bash",
                str(REPO_ROOT / "run_qa_domain.sh"),
                "--domain",
                domain,
                "--tenant-id",
                req["tenant_id"],
                "--base-url",
                req["base_url"],
                "--output-dir",
                str(output_dir),
                "--max-scenarios",
                str(req["max_scenarios"]),
                "--pass-threshold",
                str(req["pass_threshold"]),
                "--script-kind",
                req["script_kind"],
                "--environment-profile",
                str(req.get("environment_profile", DEFAULT_ENVIRONMENT_PROFILE)),
                "--rl-train-mode",
                str(req.get("rl_train_mode", "periodic")),
                "--rl-checkpoint",
                str(checkpoint),
            ]
            workspace_id = str(req.get("workspace_id") or req.get("tenant_id") or "").strip()
            if workspace_id:
                cmd += ["--workspace-id", workspace_id]
            max_runtime_sec = req.get("max_runtime_sec")
            if isinstance(max_runtime_sec, int) and max_runtime_sec > 0:
                cmd += ["--max-runtime-sec", str(max_runtime_sec)]
            llm_token_cap = req.get("llm_token_cap")
            if isinstance(llm_token_cap, int) and llm_token_cap > 0:
                cmd += ["--llm-token-cap", str(llm_token_cap)]
            if bool(release_gate.get("enabled", True)):
                cmd += ["--ci-gate"]
            else:
                cmd += ["--no-ci-gate"]
            cmd += [
                "--ci-pass-floor",
                str(release_gate.get("passFloor", req.get("pass_threshold", 0.70))),
                "--ci-flaky-threshold",
                str(release_gate.get("flakyThreshold", 0.15)),
                "--ci-max-pass-drop",
                str(release_gate.get("maxPassDrop", 0.08)),
                "--ci-max-reward-drop",
                str(release_gate.get("maxRewardDrop", 0.10)),
                "--ci-min-gam-quality",
                str(release_gate.get("minGamQuality", 0.55)),
            ]
            if bool(release_gate.get("safeModeOnFail", True)):
                cmd += ["--safe-mode-on-fail"]
            else:
                cmd += ["--no-safe-mode-on-fail"]

            if spec_path_override:
                cmd += ["--action", "run", "--spec-path", spec_path_override]
            else:
                if scope_mode == "advanced" and (include_operations or exclude_operations):
                    scoped_spec_summary = {
                        "applied": False,
                        "reason": "scope_requires_spec_path",
                        "scope_mode": scope_mode,
                        "requested_include_operations": int(len(include_operations)),
                        "requested_exclude_operations": int(len(exclude_operations)),
                    }
                if domain not in DOMAIN_PRESET_SET:
                    with _jobs_lock:
                        job = _jobs[job_id]
                        _append_log(
                            job,
                            f"[{domain}] Unsupported preset domain without spec path. "
                            + "Provide specPaths.<domain>=/path/to/openapi.yaml",
                        )
                        job["results"][domain] = {
                            "domain": domain,
                            "return_code": 2,
                            "script_kind": req["script_kind"],
                            "output_dir": str(output_dir),
                            "checkpoint": str(checkpoint),
                            "spec_path": "",
                            "scope_filter": scoped_spec_summary,
                            "report_mode": report_mode,
                            "report_json": "",
                            "report_md": "",
                            "summary": {"error": "missing_spec_path_for_custom_domain"},
                            "generated_tests": {},
                        }
                    failures += 1
                    continue
                cmd += ["--action", "both"]

            if req.get("prompt"):
                cmd += ["--prompt", req["prompt"]]
            if req.get("customer_mode"):
                cmd += [
                    "--customer-mode",
                    "--customer-root",
                    req.get("customer_root", str(Path.home() / ".spec_test_pilot")),
                ]
            if req.get("verify_persistence"):
                cmd += ["--verify-persistence"]

            with _jobs_lock:
                job = _jobs[job_id]
                job["current_domain"] = domain
                _append_log(job, "")
                _append_log(job, f"===== DOMAIN: {domain} =====")
                if scoped_spec_summary:
                    _append_log(
                        job,
                        "[scope] " + json.dumps(scoped_spec_summary, ensure_ascii=True),
                    )
                _append_log(job, "$ " + " ".join(cmd))
                _persist_jobs_state_unlocked()

            if not checkpoint_lock.acquire(timeout=300.0):
                with _jobs_lock:
                    job = _jobs[job_id]
                    _append_log(job, f"[{domain}] Checkpoint lock timeout: {checkpoint}")
                    job["results"][domain] = {
                        "domain": domain,
                        "return_code": 2,
                        "script_kind": req["script_kind"],
                        "output_dir": str(output_dir),
                        "checkpoint": str(checkpoint),
                        "spec_path": spec_path_override,
                        "scope_filter": scoped_spec_summary,
                        "report_mode": report_mode,
                        "report_json": "",
                        "report_md": "",
                        "summary": {"error": "checkpoint_lock_timeout"},
                        "generated_tests": {},
                    }
                    _persist_jobs_state_unlocked()
                failures += 1
                continue

            try:
                child_env = dict(os.environ)
                child_env.setdefault("QA_SCENARIO_LLM_TIMEOUT_SECONDS", "45")
                child_env.setdefault("QA_SCENARIO_LLM_MAX_RETRIES", "1")
                child_env["QA_AUTH_MODE"] = auth_mode
                if auth_mode != "bearer":
                    child_env.pop("QA_AUTH_VALID_TOKEN", None)
                child_env.pop("QA_AUTH_API_KEY_NAME", None)
                child_env.pop("QA_AUTH_API_KEY_IN", None)
                child_env.pop("QA_AUTH_API_KEY_VALUE", None)
                child_env.pop("QA_AUTH_API_KEY_INVALID_VALUE", None)
                child_env.pop("QA_REQUEST_MUTATION_RULES_JSON", None)
                child_env.pop("QA_INCLUDE_OPERATIONS_JSON", None)
                child_env.pop("QA_EXCLUDE_OPERATIONS_JSON", None)
                child_env.pop("QA_CUSTOMER_INTENT", None)
                child_env.pop("QA_CRITICAL_OPERATIONS_JSON", None)
                child_env.pop("QA_CRITICAL_ASSERTIONS_JSON", None)
                child_env.pop("QA_AUTH_PROFILES_JSON", None)
                child_env.pop("QA_REPORT_MODE", None)
                child_env["QA_SCOPE_MODE"] = scope_mode
                child_env["QA_INCLUDE_OPERATIONS_JSON"] = json.dumps(
                    include_operations,
                    ensure_ascii=True,
                )
                child_env["QA_EXCLUDE_OPERATIONS_JSON"] = json.dumps(
                    exclude_operations,
                    ensure_ascii=True,
                )
                if request_mutation_rules:
                    child_env["QA_REQUEST_MUTATION_RULES_JSON"] = json.dumps(
                        request_mutation_rules,
                        ensure_ascii=True,
                    )
                if customer_intent:
                    child_env["QA_CUSTOMER_INTENT"] = customer_intent
                if critical_operations:
                    child_env["QA_CRITICAL_OPERATIONS_JSON"] = json.dumps(
                        critical_operations,
                        ensure_ascii=True,
                    )
                if critical_assertions:
                    child_env["QA_CRITICAL_ASSERTIONS_JSON"] = json.dumps(
                        critical_assertions,
                        ensure_ascii=True,
                    )
                if isinstance(auth_profiles_runtime, dict) and auth_profiles_runtime:
                    child_env["QA_AUTH_PROFILES_JSON"] = json.dumps(
                        auth_profiles_runtime,
                        ensure_ascii=True,
                    )
                child_env["QA_REPORT_MODE"] = report_mode
                child_env["QA_LIVE_REQUEST_TIMEOUT_SEC"] = str(
                    resource_limits.get("liveRequestTimeoutSec", 12.0)
                )
                child_env["QA_SCRIPT_EXEC_MAX_RUNTIME_SEC"] = str(
                    resource_limits.get("scriptExecMaxRuntimeSec", 120.0)
                )
                child_env["QA_SCENARIO_LLM_TIMEOUT_SECONDS"] = str(
                    resource_limits.get("llmTimeoutSec", 45)
                )
                child_env["QA_SCENARIO_LLM_MAX_RETRIES"] = str(
                    resource_limits.get("llmRetries", 1)
                )
                if auth_mode == "bearer":
                    if runtime_bearer_token:
                        child_env["QA_AUTH_VALID_TOKEN"] = runtime_bearer_token
                elif auth_mode == "api_key":
                    child_env["QA_AUTH_API_KEY_NAME"] = runtime_api_key_name
                    child_env["QA_AUTH_API_KEY_IN"] = runtime_api_key_in
                    if runtime_api_key_value:
                        child_env["QA_AUTH_API_KEY_VALUE"] = runtime_api_key_value
                    child_env["QA_AUTH_API_KEY_INVALID_VALUE"] = str(
                        os.getenv("QA_AUTH_API_KEY_INVALID_VALUE", "invalid_api_key")
                    ).strip() or "invalid_api_key"
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(REPO_ROOT),
                    env=child_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                assert proc.stdout is not None
                for line in proc.stdout:
                    with _jobs_lock:
                        live_job = _jobs.get(job_id)
                        if live_job:
                            _append_log(live_job, f"[{domain}] {line.rstrip()}")

                return_code = proc.wait()

                report_json = output_dir / "qa_execution_report.json"
                report_md = output_dir / "qa_execution_report.md"
                summary, generated_tests = _load_report_artifacts(report_json)
                if return_code != 0:
                    failures += 1

                with _jobs_lock:
                    job = _jobs[job_id]
                    job["results"][domain] = {
                        "domain": domain,
                        "return_code": return_code,
                        "script_kind": req["script_kind"],
                        "output_dir": str(output_dir),
                        "checkpoint": str(checkpoint),
                        "spec_path": spec_path_override,
                        "scope_filter": scoped_spec_summary,
                        "scope_mode": scope_mode,
                        "report_mode": report_mode,
                        "report_json": str(report_json),
                        "report_md": str(report_md),
                        "summary": summary,
                        "generated_tests": generated_tests,
                    }
                    _persist_jobs_state_unlocked()
            finally:
                checkpoint_lock.release()

        with _jobs_lock:
            job = _jobs[job_id]
            job["current_domain"] = None
            job["completed_at"] = datetime.utcnow().isoformat() + "Z"
            job["status"] = "completed" if failures == 0 else "failed"
            _persist_jobs_state_unlocked()
        trigger_periodic_tick = True
    except Exception as exc:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job:
                _append_log(job, f"[fatal] job execution crashed: {exc}")
                job["current_domain"] = None
                job["completed_at"] = datetime.utcnow().isoformat() + "Z"
                job["status"] = "failed"
                _persist_jobs_state_unlocked()
        trigger_periodic_tick = True
    finally:
        with _jobs_lock:
            _job_runtime_secrets.pop(job_id, None)
        if RL_PERIODIC_ENABLED and trigger_periodic_tick:
            threading.Thread(
                target=_run_periodic_rl_tick,
                args=("job_completion",),
                name=f"qa-periodic-rl-trigger-{job_id}",
                daemon=True,
            ).start()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (
        """
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>SpecForge Customer QA UI</title>
  <style>
    :root {
      --bg: #f8f7f2;
      --ink: #14213d;
      --muted: #415a77;
      --card: #ffffff;
      --accent: #e76f51;
      --ok: #2a9d8f;
      --bad: #c1121f;
      --line: #d7d7d7;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 10% 10%, #fff3e6 0%, var(--bg) 45%, #edf3ff 100%);
    }
    header {
      padding: 20px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,0.9);
      backdrop-filter: blur(6px);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    header h1 {
      margin: 0;
      font-size: 22px;
      letter-spacing: 0.4px;
    }
    .wrap {
      max-width: 1280px;
      margin: 18px auto;
      padding: 0 16px 24px;
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 16px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      box-shadow: 0 5px 20px rgba(20, 33, 61, 0.05);
    }
    .card h2 {
      margin: 0 0 12px;
      font-size: 15px;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: var(--muted);
    }
    .field { margin-bottom: 10px; }
    label { display: block; font-size: 12px; margin-bottom: 4px; color: var(--muted); }
    input[type=text], input[type=number], select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      font-size: 14px;
    }
    textarea { min-height: 80px; resize: vertical; }
    .domains { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 10px; }
    .domain-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px;
      background: #fafafa;
      font-size: 13px;
    }
    .checks { display: grid; gap: 6px; margin: 10px 0; }
    .btn {
      width: 100%;
      border: 0;
      border-radius: 9px;
      background: linear-gradient(120deg, #f4a261, var(--accent));
      color: #fff;
      font-size: 14px;
      font-weight: 600;
      padding: 10px;
      cursor: pointer;
    }
    .btn:disabled { opacity: 0.5; cursor: default; }
    .status {
      font-size: 13px;
      margin-bottom: 10px;
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: #999; }
    .dot.running { background: #f4a261; }
    .dot.completed { background: var(--ok); }
    .dot.failed { background: var(--bad); }
    .grid-right { display: grid; gap: 16px; }
    .steps { display: grid; gap: 6px; font-size: 13px; }
    .step { border-left: 4px solid #ddd; padding: 6px 8px; background: #fafafa; }
    .step.done { border-left-color: var(--ok); background: #f2fbf9; }
    .results { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
    .result-item { border: 1px solid var(--line); border-radius: 10px; padding: 10px; }
    .result-item h3 { margin: 0 0 8px; font-size: 15px; }
    .pill { display:inline-block; border-radius:999px; padding:2px 8px; font-size:11px; margin-left:6px; }
    .pill.ok { background:#d8f4ef; color:#0b6a5f; }
    .pill.bad { background:#ffe5e5; color:#8f0013; }
    .result-item button {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      padding: 6px 8px;
      margin-right: 6px;
      cursor: pointer;
    }
    pre {
      margin: 0;
      background: #0f172a;
      color: #e5e7eb;
      border-radius: 10px;
      padding: 10px;
      max-height: 360px;
      overflow: auto;
      font-size: 12px;
      line-height: 1.35;
      white-space: pre-wrap;
    }
    @media (max-width: 980px) {
      .wrap { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>SpecForge Customer QA Runner</h1>
  </header>

  <div class=\"wrap\">
    <section class=\"card\">
      <h2>Run Configuration</h2>
      <div class=\"field\">
        <label>Domains (comma or newline separated)</label>
        <textarea id=\"domainsInput\" style=\"min-height:72px;\" placeholder=\"ecommerce, healthcare\">ecommerce</textarea>
      </div>
      <div class=\"field\">
        <label>Spec Paths (optional, one per line: domain=/abs/path/openapi.yaml)</label>
        <textarea id=\"specPaths\" style=\"min-height:72px;\" placeholder=\"payments=/tmp/openapi_payments.yaml\"></textarea>
      </div>

      <div class=\"field\">
        <label>Tenant ID</label>
        <input id=\"tenant\" type=\"text\" value=\"customer_default\" />
      </div>
      <div class=\"field\">
        <label>Script Language</label>
        <select id=\"scriptKind\">
          <option value=\"python_pytest\" selected>Python / Pytest</option>
          <option value=\"javascript_jest\">JavaScript / Jest</option>
          <option value=\"curl_script\">cURL Script</option>
          <option value=\"java_restassured\">Java / RestAssured</option>
        </select>
      </div>
      <div class=\"field\">
        <label>Max Scenarios</label>
        <input id=\"max\" type=\"number\" value=\"64\" min=\"1\" max=\"500\" />
      </div>
      <div class=\"field\">
        <label>Pass Threshold (0-1)</label>
        <input id=\"threshold\" type=\"number\" value=\"0.7\" min=\"0\" max=\"1\" step=\"0.01\" />
      </div>
      <div class=\"field\">
        <label>Base URL</label>
        <input id=\"baseUrl\" type=\"text\" value=\"__DEFAULT_BASE_URL__\" />
      </div>
      <div class=\"field\">
        <label>Customer Root</label>
        <input id=\"customerRoot\" type=\"text\" value=\"~/.spec_test_pilot\" />
      </div>
      <div class=\"field\">
        <label>Prompt (optional)</label>
        <textarea id=\"prompt\" placeholder=\"Custom QA prompt\"></textarea>
      </div>

      <div class=\"checks\">
        <label><input id=\"customerMode\" type=\"checkbox\" checked> customer mode (persistent checkpoint/workspace)</label>
        <label><input id=\"verify\" type=\"checkbox\" checked> verify persistence (auto second pass)</label>
      </div>

      <button class=\"btn\" id=\"runBtn\" onclick=\"startRun()\">Run QA Agent</button>
    </section>

    <section class=\"grid-right\">
      <div class=\"card\">
        <h2>Runtime Status</h2>
        <div class=\"status\"><span id=\"statusDot\" class=\"dot\"></span><strong id=\"statusText\">idle</strong></div>
        <div id=\"jobMeta\" style=\"font-size:12px;color:#475569;\"></div>
        <div class=\"steps\" id=\"steps\"></div>
      </div>

      <div class=\"card\">
        <h2>Domain Results</h2>
        <div id=\"results\" class=\"results\"></div>
      </div>

      <div class=\"card\">
        <h2>Live Process Log</h2>
        <pre id=\"logs\">No run started yet.</pre>
      </div>

      <div class=\"card\">
        <h2>Report Viewer</h2>
        <pre id=\"reportView\">Select a report from Domain Results.</pre>
      </div>
    </section>
  </div>

  <script>
    let currentJobId = null;
    let pollHandle = null;

    const STEP_MARKERS = [
      { name: 'Spec Prepared', marker: '[OK] OpenAPI spec written' },
      { name: 'Run Started', marker: '[RUN] QA specialist agent' },
      { name: 'RL Session Started', marker: 'Started observability session' },
      { name: 'RL Training Executed', marker: 'RL training executed' },
      { name: 'QA Run Complete', marker: 'QA specialist run complete' },
      { name: 'Reports Written', marker: 'JSON report:' }
    ];

    function selectedDomains() {
      const raw = String(document.getElementById('domainsInput').value || '');
      const tokens = raw
        .split(/[\\n,]+/)
        .map(v => v.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_'))
        .filter(Boolean);
      return Array.from(new Set(tokens));
    }

    function parseSpecPaths() {
      const raw = String(document.getElementById('specPaths').value || '');
      const lines = raw.split(/\\n+/).map(v => v.trim()).filter(Boolean);
      const out = {};
      lines.forEach((line) => {
        const idx = line.indexOf('=');
        if (idx <= 0) return;
        const domain = line.slice(0, idx).trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_');
        const specPath = line.slice(idx + 1).trim();
        if (!domain || !specPath) return;
        out[domain] = specPath;
      });
      return out;
    }

    async function startRun() {
      const domains = selectedDomains();
      if (!domains.length) {
        alert('Select at least one domain.');
        return;
      }

      const body = {
        domains,
        spec_paths: parseSpecPaths(),
        tenant_id: document.getElementById('tenant').value.trim() || 'customer_default',
        script_kind: document.getElementById('scriptKind').value || 'python_pytest',
        rl_train_mode: 'periodic',
        prompt: document.getElementById('prompt').value.trim() || null,
        max_scenarios: Number(document.getElementById('max').value || 64),
        pass_threshold: Number(document.getElementById('threshold').value || 0.7),
        base_url: document.getElementById('baseUrl').value.trim() || '__DEFAULT_BASE_URL__',
        customer_mode: document.getElementById('customerMode').checked,
        verify_persistence: document.getElementById('verify').checked,
        customer_root: document.getElementById('customerRoot').value.trim() || '~/.spec_test_pilot'
      };

      const runBtn = document.getElementById('runBtn');
      runBtn.disabled = true;
      runBtn.textContent = 'Starting...';

      const resp = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      const payload = await resp.json();
      if (!resp.ok) {
        alert(payload.detail || 'Failed to start job');
        runBtn.disabled = false;
        runBtn.textContent = 'Run QA Agent';
        return;
      }

      currentJobId = payload.job_id;
      document.getElementById('logs').textContent = 'Job started...';
      document.getElementById('reportView').textContent = 'Select a report from Domain Results.';
      pollJob();
    }

    async function pollJob() {
      if (!currentJobId) return;
      if (pollHandle) clearTimeout(pollHandle);

      const resp = await fetch(`/api/jobs/${currentJobId}?tail=800`);
      const job = await resp.json();
      renderJob(job);

      if (job.status === 'running' || job.status === 'queued') {
        pollHandle = setTimeout(pollJob, 1500);
      } else {
        document.getElementById('runBtn').disabled = false;
        document.getElementById('runBtn').textContent = 'Run QA Agent';
      }
    }

    function renderJob(job) {
      const dot = document.getElementById('statusDot');
      dot.className = 'dot ' + (job.status || '');
      document.getElementById('statusText').textContent = job.status;

      const meta = [];
      meta.push(`job_id=${job.id}`);
      if (job.current_domain) meta.push(`current_domain=${job.current_domain}`);
      if (job.started_at) meta.push(`started_at=${job.started_at}`);
      if (job.completed_at) meta.push(`completed_at=${job.completed_at}`);
      document.getElementById('jobMeta').textContent = meta.join(' | ');

      const logs = job.logs || [];
      const logText = logs.join('\n');
      document.getElementById('logs').textContent = logText || 'No logs yet.';

      const stepsEl = document.getElementById('steps');
      stepsEl.innerHTML = '';
      STEP_MARKERS.forEach(step => {
        const done = logText.includes(step.marker);
        const el = document.createElement('div');
        el.className = 'step' + (done ? ' done' : '');
        el.textContent = (done ? '✓ ' : '• ') + step.name;
        stepsEl.appendChild(el);
      });

      const resultsEl = document.getElementById('results');
      resultsEl.innerHTML = '';
      const results = job.results || {};
      Object.keys(results).forEach(domain => {
        const r = results[domain];
        const card = document.createElement('div');
        card.className = 'result-item';
        const ok = Number(r.return_code) === 0;
        const s = r.summary || {};
        card.innerHTML = `
          <h3>${domain}<span class="pill ${ok ? 'ok':'bad'}">${ok ? 'ok':'failed'}</span></h3>
          <div style="font-size:12px; line-height:1.45; color:#475569;">
            pass_rate=${s.pass_rate ?? 'n/a'}<br/>
            total=${s.total_scenarios ?? 'n/a'} passed=${s.passed_scenarios ?? 'n/a'} failed=${s.failed_scenarios ?? 'n/a'}<br/>
            rl_steps=${s.rl_training_steps ?? 'n/a'} rl_buffer=${s.rl_buffer_size ?? 'n/a'}
          </div>
          <div style="margin-top:8px;">
            <button onclick="viewReport('${domain}','json')">View JSON</button>
            <button onclick="viewReport('${domain}','md')">View Markdown</button>
          </div>
        `;
        resultsEl.appendChild(card);
      });
    }

    async function viewReport(domain, format) {
      if (!currentJobId) return;
      const resp = await fetch(`/api/jobs/${currentJobId}/report/${domain}?format=${format}`);
      const target = document.getElementById('reportView');
      if (!resp.ok) {
        const err = await resp.text();
        target.textContent = `Failed to load report: ${err}`;
        return;
      }
      if (format === 'json') {
        const payload = await resp.json();
        target.textContent = JSON.stringify(payload, null, 2);
      } else {
        target.textContent = await resp.text();
      }
    }
  </script>
</body>
</html>
"""
    ).replace("__DEFAULT_BASE_URL__", DEFAULT_BASE_URL)


@app.post("/api/spec-upload")
async def upload_spec_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    filename_raw = str(getattr(file, "filename", "") or "").strip()
    if not filename_raw:
        raise HTTPException(status_code=400, detail="uploaded file name is empty")

    suffix = Path(filename_raw).suffix.lower()
    if suffix not in SPEC_UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="unsupported file extension (allowed: .yaml, .yml, .json)",
        )

    raw_bytes = await file.read(SPEC_UPLOAD_MAX_BYTES + 1)
    try:
        await file.close()
    except Exception:
        pass

    if not raw_bytes:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    if len(raw_bytes) > SPEC_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"uploaded file exceeds max size ({SPEC_UPLOAD_MAX_BYTES} bytes)",
        )

    stem = _sanitize_domain_token(Path(filename_raw).stem) or "openapi_spec"
    target = SPEC_UPLOAD_ROOT / (
        f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{stem}{suffix}"
    )
    target.write_bytes(raw_bytes)

    return {
        "spec_path": str(target.resolve()),
        "original_filename": filename_raw,
        "size_bytes": len(raw_bytes),
    }


@app.post("/api/jobs")
def create_job(req: RunRequest) -> Dict[str, Any]:
    req_payload = req.model_dump()
    # Persist normalized RL mode explicitly for job-level observability.
    req_payload["rl_train_mode"] = str(getattr(req, "rl_train_mode", "periodic") or "periodic").strip().lower()
    explicit_base_url = "base_url" in set(getattr(req, "model_fields_set", set()) or set())
    auth_mode = _normalize_auth_mode(req_payload.get("auth_mode", "none"))
    auth_context_raw = req_payload.get("auth_context", {})
    runtime_auth_secrets = _extract_runtime_auth_secrets(auth_mode, auth_context_raw)
    if auth_mode == "api_key":
        runtime_auth_secrets["apiKeyName"] = (
            str(auth_context_raw.get("apiKeyName", "")).strip() or "X-API-Key"
        )
        runtime_auth_secrets["apiKeyIn"] = (
            "query"
            if str(auth_context_raw.get("apiKeyIn", "header")).strip().lower() == "query"
            else "header"
        )
    req_payload["auth_mode"] = auth_mode
    req_payload["auth_context"] = _redact_auth_context(auth_mode, auth_context_raw)
    auth_profiles = _normalize_auth_profiles(req_payload.get("auth_profiles", {}))
    req_payload["auth_profiles"] = _redact_auth_profiles(auth_profiles)
    if auth_profiles:
        runtime_auth_secrets["authProfiles"] = auth_profiles
    environment_targets = _normalize_environment_targets(
        req_payload.get("environment_targets", {})
    )
    req_payload["environment_targets"] = environment_targets
    customer_intent = _normalize_customer_intent(req_payload.get("customer_intent"))
    scope_mode = _normalize_scope_mode(req_payload.get("scope_mode", "full_spec"))
    report_mode = _normalize_report_mode(req_payload.get("report_mode", "full"))
    req_payload["report_mode"] = report_mode
    include_operations = _normalize_operation_selection(req_payload.get("include_operations", []))
    include_set = set(include_operations)
    exclude_operations = [
        item
        for item in _normalize_operation_selection(req_payload.get("exclude_operations", []))
        if item not in include_set
    ]
    request_mutation_rules = _normalize_request_mutation_rules(
        req_payload.get("request_mutation_rules", [])
    )
    if include_set:
        request_mutation_rules = [
            item
            for item in request_mutation_rules
            if str(item.get("operationId", "")) in include_set
        ]
    if include_operations or exclude_operations or request_mutation_rules:
        scope_mode = "advanced"
    critical_operations = _normalize_operation_selection(
        req_payload.get("critical_operations", [])
    )
    critical_assertions = _normalize_critical_assertions(
        req_payload.get("critical_assertions", [])
    )
    assertion_operations = {
        str(item.get("operationId", "")).strip()
        for item in critical_assertions
        if isinstance(item, dict)
    }
    critical_operations = list(
        dict.fromkeys([*critical_operations, *[item for item in assertion_operations if item]])
    )
    release_gate = _normalize_release_gate(
        req_payload.get("release_gate", {}),
        pass_threshold=float(req_payload.get("pass_threshold", 0.70) or 0.70),
    )
    resource_limits = _normalize_resource_limits(req_payload.get("resource_limits", {}))
    req_payload["release_gate"] = release_gate
    req_payload["resource_limits"] = resource_limits
    req_payload["critical_operations"] = critical_operations
    req_payload["critical_assertions"] = critical_assertions
    req_payload["customer_intent"] = customer_intent
    req_payload["scope_mode"] = scope_mode
    req_payload["include_operations"] = include_operations
    req_payload["exclude_operations"] = exclude_operations
    req_payload["request_mutation_rules"] = request_mutation_rules
    selected_profile = str(
        req_payload.get("environment_profile", DEFAULT_ENVIRONMENT_PROFILE)
    ).strip().lower()
    if (
        not explicit_base_url
        and selected_profile in environment_targets
        and str(environment_targets[selected_profile]).strip()
    ):
        req_payload["base_url"] = str(environment_targets[selected_profile]).strip()
    req_payload["prompt"] = _compose_prompt_with_runtime_scope(
        req_payload.get("prompt"),
        customer_intent=customer_intent,
        scope_mode=scope_mode,
        include_operations=include_operations,
        exclude_operations=exclude_operations,
        request_mutation_rules=request_mutation_rules,
        critical_operations=critical_operations,
        critical_assertions=critical_assertions,
        report_mode=report_mode,
    )
    if not str(req_payload.get("workspace_id") or "").strip():
        req_payload["workspace_id"] = str(req_payload.get("tenant_id") or "customer_default")
    spec_paths = req_payload.get("spec_paths") or {}
    if isinstance(spec_paths, dict) and spec_paths:
        domain_set = {_sanitize_domain_token(item) for item in req_payload.get("domains", [])}
        domain_set = {item for item in domain_set if item}
        for domain in spec_paths.keys():
            token = _sanitize_domain_token(domain)
            if token:
                domain_set.add(token)
        req_payload["domains"] = sorted(domain_set)

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "started_at": None,
        "completed_at": None,
        "current_domain": None,
        "request": req_payload,
        "logs": [],
        "results": {},
    }

    with _jobs_lock:
        active_jobs = sum(
            1
            for item in _jobs.values()
            if str(item.get("status", "")).lower() in {"queued", "running"}
        )
        if active_jobs >= MAX_QUEUED_JOBS:
            raise HTTPException(
                status_code=429,
                detail=f"Too many active jobs ({active_jobs}). Try again later.",
            )
        _jobs[job_id] = job
        _job_runtime_secrets[job_id] = runtime_auth_secrets
        _persist_jobs_state_unlocked()

    _job_executor.submit(_run_job, job_id)

    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs")
def list_jobs() -> List[Dict[str, Any]]:
    with _jobs_lock:
        return [
            {
                "id": j["id"],
                "status": j["status"],
                "created_at": j["created_at"],
                "started_at": j["started_at"],
                "completed_at": j["completed_at"],
                "current_domain": j["current_domain"],
                "domains": j["request"].get("domains", []),
            }
            for j in _jobs.values()
        ]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, tail: int = Query(500, ge=50, le=3000)) -> Dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return _job_payload(job, tail)


@app.get("/api/jobs/{job_id}/events")
async def stream_job_events(job_id: str, tail: int = Query(1200, ge=50, le=3000)):
    async def event_generator():
        last_fingerprint = None

        while True:
            with _jobs_lock:
                job = _jobs.get(job_id)
                if not job:
                    payload = {"error": "job not found", "job_id": job_id}
                    yield f"event: error\ndata: {json.dumps(payload)}\n\n"
                    return
                payload = _job_payload(job, tail)

            fingerprint = (
                payload["status"],
                payload["current_domain"],
                payload["completed_at"],
                len(payload["logs"]),
                len(payload["results"]),
            )

            if fingerprint != last_fingerprint:
                last_fingerprint = fingerprint
                yield f"event: snapshot\ndata: {json.dumps(payload)}\n\n"

            if payload["status"] in {"completed", "failed"}:
                done_payload = {"job_id": job_id, "status": payload["status"]}
                yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
                return

            await asyncio.sleep(1.0)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


@app.get("/api/jobs/{job_id}/report/{domain}")
def get_report(
    job_id: str,
    domain: str,
    format: str = Query("json"),
    view: str = Query(""),
):
    if format not in {"json", "md"}:
        raise HTTPException(status_code=400, detail="format must be json or md")

    result = _domain_result_or_404(job_id, domain)

    report_path = Path(result["report_json"] if format == "json" else result["report_md"]).resolve()
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="report file missing")

    if format == "json":
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        selected_view = _normalize_report_mode(
            str(view or result.get("report_mode", "full")).strip().lower()
        )
        projected = _project_report_payload(payload, selected_view)
        return JSONResponse(projected)
    return PlainTextResponse(report_path.read_text(encoding="utf-8"))


@app.get("/api/jobs/{job_id}/generated-tests/{domain}")
def list_generated_tests(job_id: str, domain: str) -> Dict[str, Any]:
    result = _domain_result_or_404(job_id, domain)
    generated = _resolve_generated_tests(result)

    output_dir_raw = str(result.get("output_dir", "")).strip()
    output_dir = _canonical_path(output_dir_raw) if output_dir_raw else None
    items: List[Dict[str, Any]] = []
    for kind in sorted(generated.keys()):
        raw_path = generated[kind]
        resolved = _canonical_path(raw_path)
        is_within_output = bool(output_dir and resolved.is_relative_to(output_dir))
        exists = resolved.exists()
        size_bytes = resolved.stat().st_size if exists else None
        items.append(
            {
                "kind": kind,
                "path": raw_path,
                "exists": exists,
                "size_bytes": size_bytes,
                "safe_to_read": bool(is_within_output),
            }
        )

    return {
        "job_id": job_id,
        "domain": domain,
        "count": len(items),
        "generated_tests": items,
    }


@app.get("/api/jobs/{job_id}/generated-tests/{domain}/{kind}")
def get_generated_test_script(job_id: str, domain: str, kind: str):
    result = _domain_result_or_404(job_id, domain)
    script_path = _resolve_safe_generated_script_path(result, kind)
    return PlainTextResponse(script_path.read_text(encoding="utf-8"))


@app.get("/api/ping")
def api_ping() -> Dict[str, str]:
    return {
        "backend": "fastapi",
        "service": "qa_customer_api",
        "status": "ok",
    }


@app.get("/api/system/periodic-rl")
def get_periodic_rl_status() -> Dict[str, Any]:
    with _periodic_lock:
        snapshot = dict(_periodic_state)
        snapshot["thread_alive"] = bool(_periodic_thread and _periodic_thread.is_alive())
    last_completed_raw = str(snapshot.get("last_completed_at") or "").strip()
    age_seconds: Optional[float] = None
    if last_completed_raw:
        try:
            parsed = datetime.fromisoformat(last_completed_raw.replace("Z", "+00:00"))
            age_seconds = max(
                0.0,
                (datetime.now(parsed.tzinfo) - parsed).total_seconds(),
            )
        except Exception:
            age_seconds = None
    interval_sec = int(snapshot.get("interval_sec", RL_PERIODIC_INTERVAL_SEC) or RL_PERIODIC_INTERVAL_SEC)
    stale = bool(snapshot.get("enabled", False)) and not bool(snapshot.get("running", False))
    if age_seconds is None:
        stale = stale and bool(snapshot.get("runs_total", 0)) and not bool(snapshot.get("thread_alive", False))
    else:
        stale = stale and age_seconds > float(max(30, interval_sec * 2))
    snapshot["last_completed_age_sec"] = round(age_seconds, 3) if age_seconds is not None else None
    snapshot["next_tick_eta_sec"] = (
        max(0, int(interval_sec - age_seconds))
        if age_seconds is not None and bool(snapshot.get("thread_alive", False))
        else None
    )
    snapshot["stale"] = bool(stale)
    return snapshot


@app.post("/api/system/periodic-rl/run-now")
def run_periodic_rl_now() -> Dict[str, Any]:
    return _run_periodic_rl_tick(trigger="manual_api")


@app.post("/api/runs")
def create_run(req: RunRequest) -> Dict[str, Any]:
    response = create_job(req)
    return {"run_id": response.get("job_id"), "status": response.get("status", "queued")}


@app.get("/api/runs")
def list_runs() -> List[Dict[str, Any]]:
    rows = list_jobs()
    return [
        {
            "run_id": item.get("id"),
            "status": item.get("status"),
            "created_at": item.get("created_at"),
            "started_at": item.get("started_at"),
            "completed_at": item.get("completed_at"),
            "current_domain": item.get("current_domain"),
            "domains": item.get("domains", []),
        }
        for item in rows
    ]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, tail: int = Query(500, ge=50, le=3000)) -> Dict[str, Any]:
    payload = get_job(run_id, tail=tail)
    payload["run_id"] = payload.pop("id")
    return payload


@app.get("/api/runs/{run_id}/report")
def get_run_report(
    run_id: str,
    domain: Optional[str] = Query(default=None),
    format: str = Query("json"),
    view: str = Query(""),
):
    if format not in {"json", "md"}:
        raise HTTPException(status_code=400, detail="format must be json or md")
    resolved_domain = _resolve_domain_for_run(run_id, domain)
    return get_report(run_id, resolved_domain, format=format, view=view)


@app.get("/api/runs/{run_id}/scripts")
def get_run_script(
    run_id: str,
    language: str = Query("python"),
    domain: Optional[str] = Query(default=None),
):
    resolved_domain = _resolve_domain_for_run(run_id, domain)
    normalized = str(language or "").strip().lower()
    kind_map = {
        "python": "python_pytest",
        "javascript": "javascript_jest",
        "js": "javascript_jest",
        "java": "java_restassured",
        "curl": "curl_script",
    }
    kind = kind_map.get(normalized, normalized)
    if kind not in SUPPORTED_SCRIPT_KINDS:
        raise HTTPException(status_code=400, detail="unsupported language")
    return get_generated_test_script(run_id, resolved_domain, kind)


@app.get("/api/runs/{run_id}/gam-context")
def get_run_gam_context(run_id: str, domain: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    resolved_domain = _resolve_domain_for_run(run_id, domain)
    result = _domain_result_or_404(run_id, resolved_domain)
    report_json = _canonical_path(result.get("report_json", ""))
    payload = _read_report_payload(report_json)
    return {
        "run_id": run_id,
        "domain": resolved_domain,
        "gam_context_pack": payload.get("gam_context_pack", {}),
        "gam_diagnostics": (payload.get("gam", {}) or {}).get("diagnostics", {}),
        "research_engine": (payload.get("gam", {}) or {}).get("research_engine", {}),
    }


@app.get("/api/runs/{run_id}/rl-decisions")
def get_run_rl_decisions(run_id: str, domain: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    resolved_domain = _resolve_domain_for_run(run_id, domain)
    result = _domain_result_or_404(run_id, resolved_domain)
    report_json = _canonical_path(result.get("report_json", ""))
    payload = _read_report_payload(report_json)
    return {
        "run_id": run_id,
        "domain": resolved_domain,
        "selection_decision_trace": payload.get("selection_decision_trace", []),
        "mutation_decision_trace": payload.get("mutation_decision_trace", []),
        "selection_policy": payload.get("selection_policy", {}),
        "mutation_policy": payload.get("mutation_policy", {}),
        "learning_feedback": (payload.get("learning", {}) or {}).get("feedback", {}),
    }


@app.get("/api/runs/{run_id}/learning-delta")
def get_run_learning_delta(
    run_id: str,
    from_run: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    resolved_domain = _resolve_domain_for_run(run_id, domain)
    result = _domain_result_or_404(run_id, resolved_domain)
    current_report = _read_report_payload(_canonical_path(result.get("report_json", "")))
    learning = current_report.get("learning", {}) or {}
    summary = current_report.get("summary", {}) or {}
    weak_deltas = current_report.get("weak_pattern_deltas", {}) or {}
    base_payload: Dict[str, Any] = {
        "run_id": run_id,
        "domain": resolved_domain,
        "learning_delta_status": learning.get("learning_delta_status", "unchanged"),
        "improvement_deltas": (learning.get("state_snapshot", {}) or {}).get("improvement_deltas", {}),
        "weak_pattern_deltas": weak_deltas,
        "summary": {
            "pass_rate": summary.get("pass_rate"),
            "meets_quality_gate": summary.get("meets_quality_gate"),
            "total_scenarios": summary.get("total_scenarios"),
        },
    }

    if from_run:
        from_domain = _resolve_domain_for_run(from_run, resolved_domain)
        from_result = _domain_result_or_404(from_run, from_domain)
        from_report = _read_report_payload(_canonical_path(from_result.get("report_json", "")))
        from_summary = from_report.get("summary", {}) or {}
        base_payload["comparison"] = {
            "from_run": from_run,
            "from_domain": from_domain,
            "pass_rate_delta": round(
                float(summary.get("pass_rate", 0.0)) - float(from_summary.get("pass_rate", 0.0)),
                4,
            ),
            "failed_scenarios_delta": int(summary.get("failed_scenarios", 0))
            - int(from_summary.get("failed_scenarios", 0)),
        }

    return base_payload


@app.on_event("startup")
def _startup_periodic_services() -> None:
    _load_jobs_state()
    _start_periodic_rl_worker()


@app.on_event("shutdown")
def _shutdown_periodic_services() -> None:
    _persist_jobs_state()
    _stop_periodic_rl_worker()
    _job_executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "qa_customer_api:app",
        host=str(RUNTIME_SETTINGS.qa_ui_host),
        port=int(RUNTIME_SETTINGS.qa_ui_port),
        reload=False,
    )
