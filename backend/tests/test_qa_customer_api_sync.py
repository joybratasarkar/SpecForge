"""Contract checks for frontend->backend key synchronization in qa_customer_api."""

from __future__ import annotations

from pathlib import Path

import yaml

from qa_customer_api import (
    RunRequest,
    _build_scoped_spec_for_domain,
    _compose_prompt_with_runtime_scope,
    _project_report_payload,
)


def _write_spec(path: Path) -> None:
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Scope API", "version": "1.0.0"},
        "paths": {
            "/orders": {
                "get": {"responses": {"200": {"description": "ok"}}},
                "post": {"responses": {"201": {"description": "created"}}},
            },
            "/orders/{orderId}": {
                "get": {"responses": {"200": {"description": "ok"}}},
            },
        },
    }
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")


def test_run_request_accepts_frontend_scope_and_mutation_keys(tmp_path: Path) -> None:
    spec_path = tmp_path / "scope.yaml"
    _write_spec(spec_path)
    payload = {
        "domains": ["scope_api"],
        "specPaths": {"scope_api": str(spec_path)},
        "tenantId": "tenant_sync",
        "workspaceId": "tenant_sync",
        "authMode": "api_key",
        "authContext": {"apiKeyName": "X-API-Key", "apiKeyIn": "header"},
        "scopeMode": "advanced",
        "includeOperations": ["GET /orders", "post /orders"],
        "excludeOperations": ["GET /orders/{orderId}", "POST /orders"],
        "requestMutationRules": [
            {
                "operationId": "POST /orders",
                "requestMode": "auto",
                "fieldName": "email",
                "action": "set_empty",
                "value": "",
                "note": "customer forced mutation",
            }
        ],
        "customerIntent": "Cover key business risks with auth + payload checks.",
    }
    req = RunRequest.model_validate(payload)
    assert req.scope_mode == "advanced"
    assert req.include_operations == ["GET /orders", "POST /orders"]
    assert req.exclude_operations == ["GET /orders/{orderId}", "POST /orders"]
    assert len(req.request_mutation_rules) == 1
    assert req.request_mutation_rules[0]["operationId"] == "POST /orders"
    assert req.request_mutation_rules[0]["action"] == "set_empty"


def test_build_scoped_spec_filters_operations(tmp_path: Path) -> None:
    spec_path = tmp_path / "scope.yaml"
    _write_spec(spec_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    scoped_path, summary = _build_scoped_spec_for_domain(
        domain="scope_api",
        source_spec_path=str(spec_path),
        output_dir=out_dir,
        include_operations=["GET /orders", "POST /orders"],
        exclude_operations=["POST /orders"],
    )
    assert summary["applied"] is True
    assert int(summary["kept_operations"]) == 1
    scoped_doc = yaml.safe_load(Path(scoped_path).read_text(encoding="utf-8"))
    assert "paths" in scoped_doc
    assert "get" in scoped_doc["paths"]["/orders"]
    assert "post" not in scoped_doc["paths"]["/orders"]


def test_prompt_scope_section_contains_customer_inputs() -> None:
    prompt = _compose_prompt_with_runtime_scope(
        "Base QA prompt.",
        customer_intent="Focus payment refund regressions.",
        scope_mode="advanced",
        include_operations=["POST /refunds"],
        exclude_operations=["DELETE /refunds/{id}"],
        request_mutation_rules=[
            {
                "operationId": "POST /refunds",
                "fieldName": "amount",
                "action": "invalid_type",
            }
        ],
        critical_operations=["POST /refunds"],
        critical_assertions=[
            {"operationId": "POST /refunds", "expectedStatus": 201}
        ],
        report_mode="executive",
    )
    text = str(prompt or "")
    assert "Customer intent:" in text
    assert "Execution scope mode: advanced" in text
    assert "Include operations:" in text
    assert "Customer mutation rules:" in text
    assert "Critical operations:" in text
    assert "Critical assertions:" in text
    assert "Report mode:" in text


def test_run_request_accepts_production_controls(tmp_path: Path) -> None:
    spec_path = tmp_path / "scope.yaml"
    _write_spec(spec_path)
    req = RunRequest.model_validate(
        {
            "domains": ["scope_api"],
            "specPaths": {"scope_api": str(spec_path)},
            "environmentProfile": "staging",
            "environmentTargets": {"staging": "https://staging.example.internal"},
            "authProfiles": {
                "GET /orders": {"authMode": "api_key", "apiKeyName": "X-API-Key"}
            },
            "criticalOperations": ["GET /orders", "POST /orders"],
            "criticalAssertions": [
                {"operationId": "POST /orders", "expectedStatus": 201, "minPassCount": 1}
            ],
            "releaseGate": {"passFloor": 0.82, "safeModeOnFail": True},
            "resourceLimits": {"liveRequestTimeoutSec": 8, "llmRetries": 2},
            "reportMode": "executive",
        }
    )
    assert req.environment_targets.get("staging") == "https://staging.example.internal"
    assert req.auth_profiles.get("GET /orders", {}).get("authMode") == "api_key"
    assert req.critical_assertions[0]["operationId"] == "POST /orders"
    assert req.report_mode == "executive"


def test_project_report_payload_summary_mode() -> None:
    payload = {
        "summary": {
            "total_scenarios": 10,
            "passed_scenarios": 8,
            "failed_scenarios": 2,
            "pass_rate": 0.8,
            "pass_threshold": 0.7,
            "meets_quality_gate": True,
            "failed_examples": [{"name": "x"}],
            "failure_diagnosis": {
                "non_pass_total": 2,
                "owner_breakdown": {"service_or_spec_issue": 2},
            },
        },
        "metadata": {
            "spec_title": "Demo API",
            "script_kind": "python_pytest",
            "environment_profile": "staging",
            "runtime_auth_mode": "bearer",
        },
        "selection_policy": {"algorithm": "contextual_linear_ucb"},
    }
    projected = _project_report_payload(payload, "summary")
    assert "summary" in projected
    assert "metadata" in projected
    assert "selection_policy" not in projected
    assert int(projected["summary"]["failure_diagnosis"]["non_pass_total"]) == 2
