# Customer UI API and Runtime Flow

This document explains exactly how the customer-facing UI triggers the QA agent and how data moves between frontend, backend, and runner.

## Connection Modes

1. Next.js only mode:
- frontend calls Next API routes on the same origin (`/api/jobs`, etc.)
- Next API routes execute `run_qa_domain.sh`

2. Split mode (recommended for FastAPI backend):
- frontend calls FastAPI directly using `NEXT_PUBLIC_BACKEND_BASE_URL=http://127.0.0.1:8787`
- FastAPI routes execute `run_qa_domain.sh`

Both modes use the same request/response shape.

## API Endpoints

1. `POST /api/jobs`
- Purpose: start one QA job across selected domains.
- Request body:
```json
{
  "domains": ["ecommerce", "healthcare"],
  "tenantId": "customer_default",
  "prompt": "optional context",
  "maxScenarios": 16,
  "passThreshold": 0.7,
  "baseUrl": "http://localhost:8000",
  "customerMode": true,
  "verifyPersistence": true,
  "customerRoot": "~/.spec_test_pilot"
}
```
- Response:
```json
{
  "jobId": "abc123",
  "status": "queued"
}
```

2. `GET /api/jobs`
- Purpose: list jobs and top-level status.

3. `GET /api/jobs/{jobId}?tail=1200`
- Purpose: snapshot of one job.
- Includes:
  - run status and timestamps
  - current domain in progress
  - per-domain result map
  - recent log lines

4. `GET /api/jobs/{jobId}/events`
- Purpose: realtime stream over SSE.
- Events:
  - `snapshot`: full incremental job snapshot
  - `done`: terminal signal when run finishes

5. `GET /api/jobs/{jobId}/report/{domain}?format=json|md`
- Purpose: fetch final report payload for one domain.
- JSON is used for parsed interactive viewer.
- Markdown is used for raw readable report view.

6. `GET /api/jobs/{jobId}/generated-tests/{domain}`
- Purpose: list generated test scripts for one domain.
- Response includes:
  - `kind` (`python_pytest`, `javascript_jest`, `curl_script`, `java_restassured`)
  - `path`
  - `exists`
  - `size_bytes`
  - `safe_to_read`

7. `GET /api/jobs/{jobId}/generated-tests/{domain}/{kind}`
- Purpose: return script content for preview/download in UI.

## Runtime Sequence

1. User clicks `Run QA Agent` in frontend.
2. Frontend sends `POST /api/jobs`.
3. Backend creates `jobId`, stores job as `queued`, returns immediately.
4. Worker starts domain loop:
- builds command for `run_qa_domain.sh`
- executes process
- streams logs into job store
- reads `qa_execution_report.json`
- stores per-domain summary + report paths
5. Frontend subscribes to `GET /api/jobs/{jobId}/events`.
6. UI updates:
- runtime status
- step map
- domain cards
- report viewer
- generated scripts panel
- Agent R&D panel
- flow step telemetry (for example: `selected=<x> / candidates=<y>` for Scenario Selection)
7. On terminal state (`completed` or `failed`), backend emits `done`.

## Report Viewer Mapping

The interactive report viewer reads these JSON keys:

1. Summary cards:
- `summary.total_scenarios`
- `summary.pass_rate`
- `summary.meets_quality_gate`
- `agent_lightning.training_stats.rl_training_steps`
- `agent_lightning.training_stats.rl_buffer_size`
- `learning.feedback.run_reward`

2. Scenario table:
- `scenario_results[]` entries:
  - `name`, `test_type`, `method`, `endpoint_template`
  - `expected_status`, `actual_status`
  - `passed`, `duration_ms`

3. Raw view:
- complete JSON/Markdown body for audit/debug

4. Generated scripts panel:
- list and preview based on `generated_test_files`
- secure script fetch through backend endpoint (path safety check)

5. Agent R&D panel:
- `selection_policy` (algorithm, candidate/selected counts, top decisions)
- `learning.feedback` (run reward, reward breakdown, decision counts)
- `learning.state_snapshot.weakest_patterns`

## Field Compatibility

The Next UI handles both field conventions:

1. FastAPI shape:
- `current_domain`, `started_at`, `completed_at`
- `return_code`, `pass_rate`, `total_scenarios`, ...

2. Next API route shape:
- `currentDomain`, `startedAt`, `completedAt`
- `exitCode`, `passRate`, `totalScenarios`, ...

This compatibility layer prevents blank cards when switching backend mode.
