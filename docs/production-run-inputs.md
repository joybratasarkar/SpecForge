# Production Run Inputs

Use these request keys with `POST /api/jobs` to run production-grade QA jobs.

## 1) Environment Targets
- `environmentProfile`: `mock|staging|prod_safe`
- `environmentTargets`: optional map for profile -> base URL.
- If `baseUrl` is not explicitly provided, backend resolves it from `environmentTargets[environmentProfile]`.

## 2) Auth Details
- `authMode` + `authContext`: global auth behavior.
- `authProfiles`: optional per-operation auth override map:
  - key: `"METHOD /path"`
  - value: `{ "authMode": "none|bearer|api_key", ... }`

## 3) Release Gate Policy
- `releaseGate.enabled`: enable/disable CI gate checks.
- `releaseGate.passFloor`: minimum pass-rate floor.
- `releaseGate.flakyThreshold`: max flaky overlap ratio.
- `releaseGate.maxPassDrop`: max pass-rate regression from baseline.
- `releaseGate.maxRewardDrop`: max reward regression.
- `releaseGate.minGamQuality`: minimum GAM context quality.
- `releaseGate.safeModeOnFail`: checkpoint rollback + safe-mode marker.

## 4) Critical Flows
- `criticalOperations`: list of must-cover operations.
- `criticalAssertions`: list of assertions:
  - `operationId` (required)
  - `expectedStatus` (optional)
  - `allowedStatuses` (optional)
  - `minPassCount` (default `1`)
  - `note` (optional)

If configured, quality gate fails when critical operations are uncovered or assertions fail.

## 5) Non-Functional Limits
- `resourceLimits.liveRequestTimeoutSec`
- `resourceLimits.scriptExecMaxRuntimeSec`
- `resourceLimits.llmTimeoutSec`
- `resourceLimits.llmRetries`

These are injected into runtime env for each job.

## 6) Report Mode
- `reportMode`: `full|technical|executive|summary`
- `GET /api/jobs/{job_id}/report/{domain}?format=json&view=<mode>`
  - `full/technical`: full payload
  - `executive/summary`: projected payload for business consumers

## Example
- See [backend/examples/production_run_template.json](/Users/sjoybrata/Desktop/reinforcement-agent/backend/examples/production_run_template.json)
