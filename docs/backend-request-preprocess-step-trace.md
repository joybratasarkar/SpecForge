# Backend Request Preprocessing Step Trace (`create_job`)

This file shows what the backend receives, what preprocessing it performs, and what output shape is produced at each stage.

Source code:

1. `backend/qa_customer_api.py`
2. `RunRequest` validators
3. `create_job(req: RunRequest)`
4. `_run_job(job_id)` command/env assembly

Generated at: 2026-03-08T04:54:50.367665Z

## Step 0: Raw Input Payload (from frontend)

```json
{
  "domains": [
    "public_form_webhooks_smoke"
  ],
  "specPaths": {
    "public_form_webhooks_smoke": "/Users/sjoybrata/Desktop/reinforcement-agent/backend/examples/openapi_smoke_types/public_form_webhooks.yaml"
  },
  "tenantId": "customer_payload_test",
  "workspaceId": "customer_payload_test",
  "scriptKind": "python_pytest",
  "prompt": "Run public form-data + webhook smoke with schema and negative validation checks.",
  "customerIntent": "Validate public multipart form intake and webhook payload validation on unauthenticated endpoints.",
  "maxScenarios": 6,
  "maxRuntimeSec": 180,
  "llmTokenCap": 512,
  "environmentProfile": "mock",
  "baseUrl": "http://127.0.0.1:8000",
  "passThreshold": 0.6,
  "authMode": "none",
  "scopeMode": "full_spec",
  "releaseGate": {
    "enabled": false,
    "safeModeOnFail": false
  },
  "resourceLimits": {
    "liveRequestTimeoutSec": 12,
    "scriptExecMaxRuntimeSec": 120,
    "llmTimeoutSec": 45,
    "llmRetries": 1
  },
  "reportMode": "summary",
  "customerMode": true,
  "verifyPersistence": false,
  "customerRoot": "/tmp/specforge_customer"
}
```

## Step 1: After FastAPI + Pydantic (`RunRequest.model_validate` + validators)

```json
{
  "domains": [
    "public_form_webhooks_smoke"
  ],
  "spec_paths": {
    "public_form_webhooks_smoke": "/Users/sjoybrata/Desktop/reinforcement-agent/backend/examples/openapi_smoke_types/public_form_webhooks.yaml"
  },
  "tenant_id": "customer_payload_test",
  "workspace_id": "customer_payload_test",
  "prompt": "Run public form-data + webhook smoke with schema and negative validation checks.",
  "script_kind": "python_pytest",
  "max_scenarios": 6,
  "max_runtime_sec": 180,
  "llm_token_cap": 512,
  "environment_profile": "mock",
  "environment_targets": {},
  "auth_mode": "none",
  "auth_context": {},
  "auth_profiles": {},
  "customer_intent": "Validate public multipart form intake and webhook payload validation on unauthenticated endpoints.",
  "scope_mode": "full_spec",
  "include_operations": [],
  "exclude_operations": [],
  "request_mutation_rules": [],
  "critical_operations": [],
  "critical_assertions": [],
  "rl_train_mode": "periodic",
  "release_gate": {
    "enabled": false,
    "passFloor": 0.7,
    "flakyThreshold": 0.15,
    "maxPassDrop": 0.08,
    "maxRewardDrop": 0.1,
    "minGamQuality": 0.55,
    "safeModeOnFail": false
  },
  "resource_limits": {
    "liveRequestTimeoutSec": 12.0,
    "scriptExecMaxRuntimeSec": 120.0,
    "llmTimeoutSec": 45,
    "llmRetries": 1
  },
  "report_mode": "summary",
  "pass_threshold": 0.6,
  "base_url": "http://127.0.0.1:8000",
  "customer_mode": true,
  "verify_persistence": false,
  "customer_root": "/private/tmp/specforge_customer"
}
```

## Step 2: `create_job` auth preprocessing (runtime secrets + redacted request auth)

```json
{
  "auth_mode": "none",
  "runtime_auth_secrets": {},
  "req_payload_auth_fields": {
    "auth_mode": "none",
    "auth_context": {},
    "auth_profiles": {}
  }
}
```

## Step 3: `create_job` scope/intent/gate/resource normalization

```json
{
  "customer_intent": "Validate public multipart form intake and webhook payload validation on unauthenticated endpoints.",
  "scope_mode": "full_spec",
  "report_mode": "summary",
  "include_operations": [],
  "exclude_operations": [],
  "request_mutation_rules": [],
  "critical_operations": [],
  "critical_assertions": [],
  "release_gate": {
    "enabled": false,
    "passFloor": 0.7,
    "flakyThreshold": 0.15,
    "maxPassDrop": 0.08,
    "maxRewardDrop": 0.1,
    "minGamQuality": 0.55,
    "safeModeOnFail": false
  },
  "resource_limits": {
    "liveRequestTimeoutSec": 12.0,
    "scriptExecMaxRuntimeSec": 120.0,
    "llmTimeoutSec": 45,
    "llmRetries": 1
  },
  "environment_targets": {},
  "explicit_base_url_in_request": true
}
```

## Step 4: `create_job` prompt composition + final normalized request payload

```json
{
  "prompt_after_compose_prompt_with_runtime_scope": "Run public form-data + webhook smoke with schema and negative validation checks.\n\nBackend Runtime Scope\nCustomer intent: Validate public multipart form intake and webhook payload validation on unauthenticated endpoints.\nExecution scope mode: full_openapi_spec\nReport mode: summary",
  "workspace_id_final": "customer_payload_test",
  "domains_final": [
    "public_form_webhooks_smoke"
  ],
  "base_url_final": "http://127.0.0.1:8000",
  "report_mode_final": "summary",
  "rl_train_mode_final": "periodic"
}
```

## Step 5: Job object stored in backend state (`_jobs[job_id]` shape)

```json
{
  "id": "<generated_12_char_job_id>",
  "status": "queued",
  "created_at": "<utc_iso8601>",
  "started_at": null,
  "completed_at": null,
  "current_domain": null,
  "request": {
    "domains": [
      "public_form_webhooks_smoke"
    ],
    "spec_paths": {
      "public_form_webhooks_smoke": "/Users/sjoybrata/Desktop/reinforcement-agent/backend/examples/openapi_smoke_types/public_form_webhooks.yaml"
    },
    "tenant_id": "customer_payload_test",
    "workspace_id": "customer_payload_test",
    "prompt": "Run public form-data + webhook smoke with schema and negative validation checks.\n\nBackend Runtime Scope\nCustomer intent: Validate public multipart form intake and webhook payload validation on unauthenticated endpoints.\nExecution scope mode: full_openapi_spec\nReport mode: summary",
    "script_kind": "python_pytest",
    "max_scenarios": 6,
    "max_runtime_sec": 180,
    "llm_token_cap": 512,
    "environment_profile": "mock",
    "environment_targets": {},
    "auth_mode": "none",
    "auth_context": {},
    "auth_profiles": {},
    "customer_intent": "Validate public multipart form intake and webhook payload validation on unauthenticated endpoints.",
    "scope_mode": "full_spec",
    "include_operations": [],
    "exclude_operations": [],
    "request_mutation_rules": [],
    "critical_operations": [],
    "critical_assertions": [],
    "rl_train_mode": "periodic",
    "release_gate": {
      "enabled": false,
      "passFloor": 0.7,
      "flakyThreshold": 0.15,
      "maxPassDrop": 0.08,
      "maxRewardDrop": 0.1,
      "minGamQuality": 0.55,
      "safeModeOnFail": false
    },
    "resource_limits": {
      "liveRequestTimeoutSec": 12.0,
      "scriptExecMaxRuntimeSec": 120.0,
      "llmTimeoutSec": 45,
      "llmRetries": 1
    },
    "report_mode": "summary",
    "pass_threshold": 0.6,
    "base_url": "http://127.0.0.1:8000",
    "customer_mode": true,
    "verify_persistence": false,
    "customer_root": "/private/tmp/specforge_customer"
  },
  "logs": [],
  "results": {}
}
```

## Step 6: `_run_job` first-domain preprocessing preview

```json
{
  "domain": "public_form_webhooks_smoke",
  "spec_path_override": "/Users/sjoybrata/Desktop/reinforcement-agent/backend/examples/openapi_smoke_types/public_form_webhooks.yaml",
  "scope_filter_summary": {
    "applied": false,
    "reason": "not_requested",
    "scope_mode": "full_spec",
    "requested_include_operations": 0,
    "requested_exclude_operations": 0
  },
  "checkpoint_path": "/tmp/qa_ui_checkpoints/customer_payload_test_public_form_webhooks_smoke.pt",
  "output_dir": "/tmp/qa_ui_runs/YYYYMMDD_HHMMSS_example_job_abc123_public_form_webhooks_smoke",
  "report_mode": "summary",
  "release_gate": {
    "enabled": false,
    "passFloor": 0.7,
    "flakyThreshold": 0.15,
    "maxPassDrop": 0.08,
    "maxRewardDrop": 0.1,
    "minGamQuality": 0.55,
    "safeModeOnFail": false
  },
  "resource_limits": {
    "liveRequestTimeoutSec": 12.0,
    "scriptExecMaxRuntimeSec": 120.0,
    "llmTimeoutSec": 45,
    "llmRetries": 1
  }
}
```

## Step 7: Runner Command Preview (`run_qa_domain.sh`)

```bash
bash /Users/sjoybrata/Desktop/reinforcement-agent/backend/run_qa_domain.sh --domain public_form_webhooks_smoke --tenant-id customer_payload_test --base-url http://127.0.0.1:8000 --output-dir /tmp/qa_ui_runs/YYYYMMDD_HHMMSS_example_job_abc123_public_form_webhooks_smoke --max-scenarios 6 --pass-threshold 0.6 --script-kind python_pytest --environment-profile mock --rl-train-mode periodic --rl-checkpoint /tmp/qa_ui_checkpoints/customer_payload_test_public_form_webhooks_smoke.pt --workspace-id customer_payload_test --max-runtime-sec 180 --llm-token-cap 512 --no-ci-gate --ci-pass-floor 0.7 --ci-flaky-threshold 0.15 --ci-max-pass-drop 0.08 --ci-max-reward-drop 0.1 --ci-min-gam-quality 0.55 --no-safe-mode-on-fail --action run --spec-path /Users/sjoybrata/Desktop/reinforcement-agent/backend/examples/openapi_smoke_types/public_form_webhooks.yaml --prompt Run public form-data + webhook smoke with schema and negative validation checks.

Backend Runtime Scope
Customer intent: Validate public multipart form intake and webhook payload validation on unauthenticated endpoints.
Execution scope mode: full_openapi_spec
Report mode: summary --customer-mode --customer-root /private/tmp/specforge_customer
```

## Step 8: Child Environment Overrides Preview (subset)

```json
{
  "QA_AUTH_MODE": "none",
  "QA_SCOPE_MODE": "full_spec",
  "QA_INCLUDE_OPERATIONS_JSON": "[]",
  "QA_EXCLUDE_OPERATIONS_JSON": "[]",
  "QA_REPORT_MODE": "summary",
  "QA_LIVE_REQUEST_TIMEOUT_SEC": "12.0",
  "QA_SCRIPT_EXEC_MAX_RUNTIME_SEC": "120.0",
  "QA_SCENARIO_LLM_TIMEOUT_SECONDS": "45",
  "QA_SCENARIO_LLM_MAX_RETRIES": "1",
  "QA_CUSTOMER_INTENT": "Validate public multipart form intake and webhook payload validation on unauthenticated endpoints."
}
```

## Step 9: API Output

`create_job` returns this JSON immediately after queueing:

```json
{
  "job_id": "<generated_12_char_job_id>",
  "status": "queued"
}
```

## Step 10: Runtime Output (after worker finishes)

`GET /api/jobs/{job_id}` will then include:

1. `status` (`running` -> `completed|failed`)
2. `results[domain]` with `return_code`, `summary`, report paths, generated tests
3. `logs` tail from process output
