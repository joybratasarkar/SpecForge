#!/usr/bin/env python3
"""Run a frontend-contract smoke test through qa_customer_api job execution."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List


def _bootstrap_env() -> None:
    # Keep smoke deterministic and local.
    os.environ.setdefault("QA_SCENARIO_LLM_MODE", "off")
    os.environ.setdefault("QA_MCP_ENABLED", "0")
    os.environ.setdefault("QA_API_AUTH_MODE", "off")
    os.environ.setdefault("QA_RL_PERIODIC_ENABLED", "0")
    os.environ.setdefault("QA_UI_MAX_CONCURRENT_JOBS", "1")
    os.environ.setdefault("QA_UI_MAX_QUEUED_JOBS", "4")


def _print_job_snapshot(job: Dict[str, Any]) -> None:
    status = str(job.get("status", "unknown"))
    current_domain = str(job.get("current_domain", "") or "none")
    created_at = str(job.get("created_at", "") or "")
    started_at = str(job.get("started_at", "") or "")
    completed_at = str(job.get("completed_at", "") or "")
    print(
        json.dumps(
            {
                "status": status,
                "current_domain": current_domain,
                "created_at": created_at,
                "started_at": started_at,
                "completed_at": completed_at,
                "result_domains": sorted(list((job.get("results") or {}).keys())),
            },
            ensure_ascii=True,
        )
    )


def _build_profile_payload(
    *,
    profile: str,
    repo_root: Path,
    customer_root: Path,
    environment_profile: str,
    base_url: str,
) -> Dict[str, Any]:
    profile_name = str(profile or "").strip().lower()
    if profile_name not in {"api_key_advanced", "bearer_advanced", "api_key_full_spec"}:
        raise ValueError(
            "Unsupported profile. Use one of: api_key_advanced, bearer_advanced, api_key_full_spec"
        )

    if profile_name == "bearer_advanced":
        spec_path = (
            repo_root / "examples" / "openapi_smoke_types" / "bearer_inventory.yaml"
        ).resolve()
        domain = "bearer_inventory_smoke"
        return {
            "domains": [domain],
            "specPaths": {domain: str(spec_path)},
            "tenantId": "customer_sync_smoke_bearer",
            "workspaceId": "customer_sync_smoke_bearer",
            "scriptKind": "python_pytest",
            "maxScenarios": 18,
            "maxRuntimeSec": 300,
            "llmTokenCap": 512,
            "passThreshold": 0.60,
            "baseUrl": str(base_url),
            "environmentProfile": str(environment_profile),
            "customerMode": True,
            "customerRoot": str(customer_root),
            "verifyPersistence": False,
            "prompt": (
                "Run bearer-auth negative-first smoke. "
                "Focus auth handling, inventory validation, and multipart upload robustness."
            ),
            "customerIntent": (
                "Customer wants bearer-secured inventory APIs tested for auth and payload regressions."
            ),
            "authMode": "bearer",
            "authContext": {
                "bearerToken": "qa_bearer_live_123",
            },
            "scopeMode": "advanced",
            "includeOperations": [
                "GET /inventory",
                "POST /inventory",
                "PATCH /inventory/{itemId}",
                "POST /inventory/{itemId}/photo",
            ],
            "excludeOperations": [
                "DELETE /inventory/{itemId}",
            ],
            "requestMutationRules": [
                {
                    "operationId": "POST /inventory",
                    "requestMode": "body",
                    "fieldName": "sku",
                    "action": "set_empty",
                    "value": "",
                    "note": "force required field empty",
                },
                {
                    "operationId": "POST /inventory",
                    "requestMode": "body",
                    "fieldName": "quantity",
                    "action": "invalid_type",
                    "value": "",
                    "note": "force numeric type mismatch",
                },
            ],
        }

    spec_path = (repo_root / "examples" / "customer_frontend_sync_smoke_api.yaml").resolve()
    domain = "customer_frontend_sync"
    if profile_name == "api_key_full_spec":
        return {
            "domains": [domain],
            "specPaths": {domain: str(spec_path)},
            "tenantId": "customer_sync_smoke_full_spec",
            "workspaceId": "customer_sync_smoke_full_spec",
            "scriptKind": "python_pytest",
            "maxScenarios": 20,
            "maxRuntimeSec": 300,
            "llmTokenCap": 512,
            "passThreshold": 0.60,
            "baseUrl": str(base_url),
            "environmentProfile": str(environment_profile),
            "customerMode": True,
            "customerRoot": str(customer_root),
            "verifyPersistence": False,
            "prompt": (
                "Run full-spec API-key smoke. "
                "Cover complete contract with auth, validation, and form-data checks."
            ),
            "customerIntent": (
                "Customer wants complete full-spec baseline before narrowing endpoint scope."
            ),
            "authMode": "api_key",
            "authContext": {
                "apiKeyName": "X-API-Key",
                "apiKeyIn": "header",
                "apiKeyValue": "qa_live_key_123",
            },
            "scopeMode": "full_spec",
        }

    return {
        "domains": [domain],
        "specPaths": {domain: str(spec_path)},
        "tenantId": "customer_sync_smoke",
        "workspaceId": "customer_sync_smoke",
        "scriptKind": "python_pytest",
        "maxScenarios": 18,
        "maxRuntimeSec": 300,
        "llmTokenCap": 512,
        "passThreshold": 0.60,
        "baseUrl": str(base_url),
        "environmentProfile": str(environment_profile),
        "customerMode": True,
        "customerRoot": str(customer_root),
        "verifyPersistence": False,
        "prompt": (
            "Run a contract-focused negative-first smoke. "
            "Focus auth, form-data, mutation robustness, and schema validation."
        ),
        "customerIntent": (
            "Customer wants API-key-secured order APIs tested with realistic negative payload mutations "
            "and file-upload form-data checks."
        ),
        "authMode": "api_key",
        "authContext": {
            "apiKeyName": "X-API-Key",
            "apiKeyIn": "header",
            "apiKeyValue": "qa_live_key_123",
        },
        "scopeMode": "advanced",
        "includeOperations": [
            "GET /orders",
            "POST /orders",
            "PATCH /orders/{orderId}",
            "POST /orders/{orderId}/attachments",
        ],
        "excludeOperations": [
            "DELETE /orders/{orderId}",
        ],
        "requestMutationRules": [
            {
                "operationId": "POST /orders",
                "requestMode": "body",
                "fieldName": "customerEmail",
                "action": "set_empty",
                "value": "",
                "note": "force required field empty",
            },
            {
                "operationId": "POST /orders",
                "requestMode": "body",
                "fieldName": "amount",
                "action": "invalid_type",
                "value": "",
                "note": "force numeric field type mismatch",
            },
            {
                "operationId": "PATCH /orders/{orderId}",
                "requestMode": "body",
                "fieldName": "status",
                "action": "override_value",
                "value": "definitely_invalid_status",
                "note": "force enum mismatch",
            },
        ],
    }


def _validate_spec_files(spec_paths: Dict[str, str]) -> None:
    for domain, raw_path in (spec_paths or {}).items():
        path = Path(str(raw_path or "")).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Spec file not found for domain '{domain}': {path}")


def _run_single_profile(profile: str, *, environment_profile: str, base_url: str) -> int:
    _bootstrap_env()

    from qa_customer_api import RunRequest, create_job, _jobs, _jobs_lock

    repo_root = Path(__file__).resolve().parent
    customer_root = Path("/tmp/qa_customer_smoke_root").resolve()
    customer_root.mkdir(parents=True, exist_ok=True)
    payload = _build_profile_payload(
        profile=profile,
        repo_root=repo_root,
        customer_root=customer_root,
        environment_profile=environment_profile,
        base_url=base_url,
    )
    _validate_spec_files(payload.get("specPaths", {}))

    domains: List[str] = list(payload.get("domains", []) or [])
    domain = str(domains[0] if domains else "").strip()
    if not domain:
        print("[smoke] invalid payload: missing domain")
        return 2

    req = RunRequest.model_validate(payload)
    create_resp = create_job(req)
    job_id = str(create_resp.get("job_id", "") or "")
    if not job_id:
        print(f"[smoke] create_job did not return job_id: {create_resp}")
        return 2

    print(f"[smoke] profile={profile} started job: {job_id}")
    deadline = time.time() + 900.0
    last_status = ""
    while time.time() < deadline:
        with _jobs_lock:
            job = dict(_jobs.get(job_id) or {})
        status = str(job.get("status", "unknown"))
        if status != last_status:
            print(f"[smoke] status={status}")
            _print_job_snapshot(job)
            last_status = status
        if status in {"completed", "failed"}:
            break
        time.sleep(2.0)
    else:
        print("[smoke] timeout waiting for job completion")
        return 2

    with _jobs_lock:
        final_job = dict(_jobs.get(job_id) or {})

    request = final_job.get("request", {})
    results = final_job.get("results", {})
    result = results.get(domain, {}) if isinstance(results, dict) else {}
    summary = result.get("summary", {}) if isinstance(result, dict) else {}

    print("[smoke] normalized request contract snapshot:")
    print(
        json.dumps(
            {
                "scope_mode": request.get("scope_mode"),
                "auth_mode": request.get("auth_mode"),
                "include_operations": request.get("include_operations"),
                "exclude_operations": request.get("exclude_operations"),
                "mutation_rule_count": len(request.get("request_mutation_rules", []) or []),
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    print("[smoke] domain result snapshot:")
    print(
        json.dumps(
            {
                "return_code": result.get("return_code"),
                "scope_filter": result.get("scope_filter"),
                "report_json": result.get("report_json"),
                "total_scenarios": summary.get("total_scenarios"),
                "pass_rate": summary.get("pass_rate"),
                "failed_scenarios": summary.get("failed_scenarios"),
            },
            ensure_ascii=True,
            indent=2,
        )
    )

    if str(final_job.get("status", "")) != "completed":
        logs = list(final_job.get("logs", []) or [])
        tail = logs[-80:] if len(logs) > 80 else logs
        print("[smoke] job failed, log tail:")
        for line in tail:
            print(str(line))
        return 1

    report_json = Path(str(result.get("report_json", "")).strip())
    if not report_json.exists():
        print(f"[smoke] completed but report is missing: {report_json}")
        return 1

    print(f"[smoke] success: report={report_json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run frontend-contract smoke profiles through qa_customer_api"
    )
    parser.add_argument(
        "--profile",
        choices=["api_key_advanced", "bearer_advanced", "api_key_full_spec", "matrix"],
        default="api_key_advanced",
        help="Smoke profile to execute. Use 'matrix' to run all profiles sequentially.",
    )
    parser.add_argument(
        "--environment-profile",
        choices=["mock", "staging", "prod_safe"],
        default="mock",
        help="Execution environment profile passed to qa_customer_api.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL used by live execution profiles.",
    )
    args = parser.parse_args()

    profile = str(args.profile)
    environment_profile = str(args.environment_profile)
    base_url = str(args.base_url).strip()
    if profile == "matrix":
        profiles = ["api_key_advanced", "bearer_advanced", "api_key_full_spec"]
        failures: List[str] = []
        for item in profiles:
            rc = _run_single_profile(
                item,
                environment_profile=environment_profile,
                base_url=base_url,
            )
            if rc != 0:
                failures.append(item)
        if failures:
            print(f"[smoke] failed profiles: {', '.join(failures)}")
            return 1
        print("[smoke] all profiles passed")
        return 0
    return _run_single_profile(
        profile,
        environment_profile=environment_profile,
        base_url=base_url,
    )


if __name__ == "__main__":
    raise SystemExit(main())
