# Customer UI API and Runtime Flow

This document describes how the customer UI builds payloads, starts jobs, streams status, and reads artifacts in both supported UI modes.

## 1. Connection Modes

## 1.1 Split Mode (Recommended)

1. UI runs in Next.js.
2. Browser calls FastAPI directly using `NEXT_PUBLIC_BACKEND_BASE_URL`.
3. Backend APIs are served by `backend/qa_customer_api.py`.

Typical base URL:

1. `http://127.0.0.1:8787`

## 1.2 Full Next Mode

1. UI and API routes run inside Next.js.
2. `/api/jobs` is handled by `frontend/customer-ui-next/app/api/jobs/route.js`.
3. Node runner (`frontend/customer-ui-next/lib/runner.js`) executes `backend/run_qa_domain.sh` locally.

## 2. Frontend Request Assembly

UI page:

1. `frontend/customer-ui-next/app/page.js`

Normalization/storage helpers:

1. `frontend/customer-ui-next/lib/store.js`

Runner:

1. `frontend/customer-ui-next/lib/runner.js`

The UI builds a frontend-shaped payload (camelCase). Core fields:

1. Workload and scope:
- `domains`, `specPaths`, `scopeMode`, `includeOperations`, `excludeOperations`, `requestMutationRules`

2. Runtime knobs:
- `tenantId`, `workspaceId`, `scriptKind`, `maxScenarios`, `maxRuntimeSec`, `llmTokenCap`
- `environmentProfile`, `environmentTargets`, `baseUrl`

3. Auth:
- `authMode` (`none|bearer|api_key|basic|form` in frontend normalization)
- `authContext` (for bearer/api_key specifically used by backend runner path)
- `authProfiles` (operation-level overrides)

4. Gates and reporting:
- `passThreshold`, `releaseGate`, `criticalOperations`, `criticalAssertions`, `resourceLimits`, `reportMode`

5. Persistence mode:
- `customerMode`, `verifyPersistence`, `customerRoot`

Note:

1. UI enforces `customerIntent` and uploaded/pasted spec before submit.
2. For custom domains, `specPaths.<domain>` is required.

## 3. Split Mode FastAPI Endpoints

Base: `http://127.0.0.1:8787`

1. `POST /api/jobs`
- creates async job and returns `{"job_id":"...","status":"queued"}`

2. `GET /api/jobs`
- lists jobs

3. `GET /api/jobs/{job_id}`
- job snapshot (`status`, `current_domain`, `results`, `logs`, request payload)

4. `GET /api/jobs/{job_id}/events`
- SSE stream (`snapshot`, `done`)

5. `GET /api/jobs/{job_id}/report/{domain}`
- report JSON/Markdown
- supports `format=json|md` and `view=full|executive|summary|technical`

6. `GET /api/jobs/{job_id}/generated-tests/{domain}`
- list generated scripts and safety metadata

7. `GET /api/jobs/{job_id}/generated-tests/{domain}/{kind}`
- fetch script contents (path-safe)

8. Alias endpoints:
- `/api/runs*` mirrors `/api/jobs*`

9. Periodic RL endpoints:
- `GET /api/system/periodic-rl`
- `POST /api/system/periodic-rl/run-now`

## 4. Full Next Mode Endpoints

Next APIs mirror job behavior with local in-memory store:

1. `POST /api/jobs` and `GET /api/jobs`
2. `GET /api/jobs/{jobId}`
3. `GET /api/jobs/{jobId}/events` (SSE)
4. `GET /api/jobs/{jobId}/report/{domain}`
5. `GET /api/jobs/{jobId}/generated-tests/{domain}`
6. `GET /api/jobs/{jobId}/generated-tests/{domain}/{kind}`
7. `POST /api/spec-upload` for local file upload in Next mode

Run aliases also exist:

1. `/api/runs`
2. `/api/runs/{runId}`
3. `/api/runs/{runId}/events`

## 5. End-to-End Runtime Sequence (Split Mode)

1. User configures intent/auth/spec/scope in UI.
2. UI sends `POST /api/jobs`.
3. FastAPI validates via `RunRequest` and queues worker.
4. Worker executes domain loop:
- builds `run_qa_domain.sh` command
- injects auth/scope/limit env vars
- streams logs into job state
- loads report artifacts into `results[domain]`
5. UI consumes:
- SSE snapshots for live state
- report endpoint for summary/raw
- generated-tests endpoints for script listing/preview
6. Job ends as `completed` or `failed`.

## 6. Field Shape Compatibility in UI

UI reads both snake_case and camelCase to support both backends.

Examples:

1. job progress fields:
- `current_domain` (FastAPI)
- `currentDomain` (Next local)

2. timestamps:
- `started_at`/`completed_at`
- `startedAt`/`completedAt`

3. domain result status code:
- `return_code` (FastAPI)
- `exitCode` (Next local)

## 7. Auth and Secret Handling

Split mode FastAPI behavior:

1. request payload stores redacted auth context (`token provided` flags, not raw secrets)
2. runtime secrets are kept in memory (`_job_runtime_secrets`)
3. child process gets secrets only through environment variables during execution

Full Next mode behavior:

1. store keeps `runtimeSecrets` separately from public request fields
2. runner injects secrets into child env similarly

## 8. Generated Artifacts Exposed to UI

For each domain result:

1. `report_json` / `report_md` paths
2. `summary` object (pass rate, quality gate, RL/GAM summary counters)
3. `generated_tests` map (kind -> file path)

Generated script endpoints return only files within domain output directory.

## 9. Practical Payload Example

```json
{
  "domains": ["bearer_inventory_smoke"],
  "specPaths": {
    "bearer_inventory_smoke": ".../backend/examples/openapi_smoke_types/bearer_inventory.yaml"
  },
  "tenantId": "customer_payload_test",
  "workspaceId": "customer_payload_test",
  "scriptKind": "python_pytest",
  "maxScenarios": 8,
  "passThreshold": 0.6,
  "baseUrl": "http://127.0.0.1:8000",
  "environmentProfile": "mock",
  "authMode": "bearer",
  "authContext": {"bearerToken": "***"},
  "scopeMode": "advanced",
  "includeOperations": ["GET /inventory", "POST /inventory"],
  "releaseGate": {"enabled": false, "safeModeOnFail": false},
  "reportMode": "summary",
  "customerMode": true,
  "verifyPersistence": false,
  "customerRoot": "/tmp/specforge_customer"
}
```

## 10. Operational Validation Checklist

1. `POST /api/jobs` returns a job id.
2. `GET /api/jobs/{id}` transitions to terminal state.
3. `GET /api/jobs/{id}/report/{domain}` returns summary.
4. `GET /api/jobs/{id}/generated-tests/{domain}` shows at least one script kind.
5. `GET /api/jobs/{id}/generated-tests/{domain}/{kind}` returns script text.
