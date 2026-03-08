# QA Agent Runtime Step Map

This document maps the active QA runtime path step-by-step, including wrapper layers, core method boundaries, and persisted outputs.

## 1. Covered Runtime Path

1. Wrapper/API layer:
- `backend/qa_customer_api.py` (`POST /api/jobs`, worker `_run_job`)
- `backend/run_qa_domain.sh`

2. Core runner:
- `backend/qa_agent_runner.py`
- `backend/spec_test_pilot/qa_specialist_agent.py`

3. Learning/policy:
- `backend/spec_test_pilot/adaptive_policy.py`
- `backend/spec_test_pilot/agent_lightning_v2.py`

## 2. One-Page Flow

```mermaid
flowchart TD
    A[POST /api/jobs or CLI args] --> B[_run_job builds env + command]
    B --> C[run_qa_domain.sh]
    C --> D[qa_agent_runner.py main()]
    D --> E[QASpecialistAgent.__init__]
    E --> F[QASpecialistAgent.run()]
    F --> G[spec intelligence]
    G --> H[GAM research/context]
    H --> I[scenario generation]
    I --> J[mutation + selection + repair]
    J --> K[execute + verify]
    K --> L[summary + learning feedback]
    L --> M[RL buffer update + checkpoint]
    M --> N[write report JSON/MD]
```

## 3. Job API Contract (FastAPI)

`POST /api/jobs` request is validated by `RunRequest` in `backend/qa_customer_api.py`.

Key accepted fields:

1. Workload/scoping:
- `domains`, `specPaths`, `scopeMode`, `includeOperations`, `excludeOperations`, `requestMutationRules`

2. Runtime:
- `tenantId`, `workspaceId`, `environmentProfile`, `baseUrl`, `maxScenarios`, `maxRuntimeSec`, `llmTokenCap`

3. Auth:
- `authMode`, `authContext`, `authProfiles`

4. Gates/reporting:
- `passThreshold`, `releaseGate`, `resourceLimits`, `criticalOperations`, `criticalAssertions`, `reportMode`

5. Persistence mode:
- `customerMode`, `verifyPersistence`, `customerRoot`

Response:

```json
{"job_id":"<12-char>","status":"queued"}
```

## 4. Wrapper Step Map (`qa_customer_api.py` + `run_qa_domain.sh`)

1. `create_job(req)`
- normalizes request shape and redacts auth context
- stores runtime secrets separately (`_job_runtime_secrets`)
- queues threadpool task `_run_job(job_id)`

2. `_run_job(job_id)`
- per domain: builds command to `run_qa_domain.sh`
- injects runtime env vars (auth, scope, limits, report mode)
- streams child stdout to job logs
- reads report artifacts and stores domain result

3. `run_qa_domain.sh`
- optional spec generation for preset domains
- executes `qa_agent_runner.py`
- optional CI gate + safe-mode rollback behavior
- optional persistence verification second pass

## 5. Core Step Map (`QASpecialistAgent.run()`)

### Step 0: Initialization (`__init__`)

Inputs:

1. CLI/runtime args
2. env configuration (`runtime_settings`, learning policy, auth/scope env)

Creates:

1. `GAMMemorySystem`
2. `AgentLightningTrainer` (`agent_lightning_v2`)
3. learning state and adaptive policy from persisted files

Persistence side effects:

1. resolves checkpoint path and learning state path
2. cleans stale atomic temp files

### Step 1: Spec Intelligence

Methods:

1. `_load_spec`
2. `_build_auth_requirement_map`
3. `_build_operation_index`
4. `_build_spec_intelligence`

Outputs:

1. auth-required operation set
2. operation metadata index
3. dependency/workflow/risk intelligence block

### Step 2: GAM Memory Research

Methods:

1. `gam.start_session`
2. `_persist_rl_learning_signal_page`
3. `_persist_gam_spec_context_page`
4. `gam.research`
5. `_build_gam_context_pack`

Optional enrichment:

1. trusted fallback excerpts
2. MCP tool excerpts (`_collect_mcp_tool_excerpts`)

Outputs:

1. memory excerpts
2. diagnostics and context pack
3. prompt focus points

### Step 3: Scenario Generation

Methods:

1. `HumanTesterSimulator.think_like_tester`
2. `_ensure_happy_path_coverage`
3. `_inject_workflow_sequence_scenarios`
4. `_inject_real_life_guardrail_scenarios`

Outputs:

1. base candidate scenarios
2. prompt trace + scenario generation trace

### Step 4: Mutation, Selection, and Repair

Methods:

1. `_augment_scenarios_with_rl_mutation`
2. `_select_scenarios_with_learning`
3. `_apply_scenario_repairs`
4. `_prepare_scenarios_for_execution_and_scripts`

Outputs:

1. selected executable scenario set
2. mutation and selection traces/summaries
3. repair summary

### Step 5: Execute and Verify

Methods:

1. `_execute_scenarios`
2. `_execute_in_isolated_mock` or `_execute_against_live_api`
3. `_verify_then_correct_result`
4. `_verify_response_contract`
5. `_apply_failure_triage_and_rerun`
6. `_build_failure_diagnosis`

Outputs:

1. `ScenarioExecutionResult[]`
2. verification payloads (status/contract/flaky/taxonomy)

### Step 6: Script Generation and Script Execution

Methods:

1. `_generate_test_files`
2. `_execute_generated_script`

Notes:

1. one primary script kind per run (`python_pytest`, `javascript_jest`, `curl_script`, or `java_restassured`)
2. script safety checks are enforced before execution

### Step 7: Summary and Learning Update

Methods:

1. `_build_summary`
2. `_build_repro_artifacts`
3. `_compute_learning_feedback`
4. `_update_learning_state`
5. `_compute_learning_delta_summary`
6. `_save_learning_state`

Outputs:

1. summary and quality-gate verdict
2. reward and decision signals
3. updated learning state snapshot

### Step 8: RL Adapter Call + Report Write

Methods:

1. `_run_agent_lightning_training`
2. `_write_reports`

Important behavior:

1. `train_agent(...)` in this path buffers transitions and autosaves checkpoint
2. heavy RL optimization runs in periodic batches (`run_periodic_training`)

Outputs:

1. `agent_lightning.training_result`
2. `agent_lightning.training_stats`
3. final report files and paths

## 6. Persisted Artifacts

Per run output directory:

1. `qa_execution_report.json`
2. `qa_execution_report.md`
3. `generated_tests/*`
4. `llm_scenario_debug.jsonl`
5. `openapi_under_test.yaml` (mock execution path)

Across runs:

1. RL checkpoint (`*.pt`)
2. learning state (`*_learning_state.json`)
3. GAM memory pages JSON

## 7. Periodic RL Runtime Map

FastAPI periodic worker (`qa_customer_api.py`):

1. discovers checkpoints from `/tmp/qa_ui_checkpoints/*.pt` and known job results
2. for each checkpoint:
- loads trainer
- runs `run_periodic_training(max_steps, min_buffer_size)`
- autosaves checkpoint

Control knobs:

1. `QA_RL_PERIODIC_ENABLED`
2. `QA_RL_PERIODIC_INTERVAL_SEC`
3. `QA_RL_PERIODIC_MAX_STEPS`
4. `QA_RL_PERIODIC_MIN_BUFFER`

APIs:

1. `GET /api/system/periodic-rl`
2. `POST /api/system/periodic-rl/run-now`

## 8. Minimal Runtime Validation Checklist

1. Job accepted: `POST /api/jobs` returns `job_id`.
2. Job progresses: `queued -> running -> completed|failed`.
3. Domain result contains non-empty `report_json` and `generated_tests`.
4. Report includes:
- `metadata.stage_metrics_ms`
- `summary`
- `learning.feedback`
- `agent_lightning.training_stats`
5. Periodic RL endpoint reports non-zero `runs_total` over time when enabled.
