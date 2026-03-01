# QA Specialist Agent Architecture (SpecTestPilot + Agent Lightning + GAM)

## 1. Purpose
This document defines the production-ready architecture for a QA-specialist agent that:

1. Reads OpenAPI specs.
2. Generates human-like QA test scenarios.
3. Executes tests in isolated environments.
4. Produces structured reports.
5. Learns over time using Agent Lightning RL.
6. Retains contextual memory using GAM with tenant isolation.

## 2. Design Goals
1. Safety first: test execution must be isolated and deterministic by default.
2. Contract correctness: no invented endpoints, schema-valid outputs.
3. Explainability: every run must produce inspectable traces, memory artifacts, and reward breakdowns.
4. Learning loop: run outcomes must feed policy/value training.
5. Multi-tenant isolation: memory and retrieval must be scoped by tenant.

## 3. High-Level Architecture

```text
                               +-----------------------------+
                               |        Control Plane        |
                               | run API / CLI / scheduler   |
                               +--------------+--------------+
                                              |
                                              v
+----------------------+        +-------------+---------------+        +----------------------+
|   Memory Plane       |<------>|    Agent Runtime Plane      |<------>|   Isolation Plane    |
|   GAM                |        | parse -> plan -> generate   |        | mock API / sandbox   |
| page store / memo    |        | execute -> report           |        | per-run environment  |
+----------+-----------+        +-------------+---------------+        +-----------+----------+
           |                                  |
           |                                  v
           |                    +-------------+---------------+
           +------------------->|   Learning Plane            |
                                | Agent Lightning sidecar RL  |
                                | traces -> transitions       |
                                +-------------+---------------+
                                              |
                                              v
                                +-------------+---------------+
                                | Observability & Governance   |
                                | logs / metrics / quality     |
                                +-----------------------------+
```

## 4. Runtime Flow (Single Run)

```text
Input(spec, tenant, prompt)
  -> start GAM session
  -> GAM deep research (plan/search/integrate/reflect)
  -> scenario generation (human-style QA)
  -> multi-language test artifact generation
  -> isolated execution against dynamic mock API
  -> collect per-scenario results
  -> summarize pass/fail, latency, failures
  -> store transcript + artifacts + memo in GAM
  -> send run summary into Agent Lightning trainer
  -> receive RL training stats
  -> emit JSON + Markdown report
```

## 5. Component Responsibilities

### 5.1 Control Plane
Responsibilities:
1. Accept run requests and enforce tenant config.
2. Trigger pipeline execution.
3. Provide retry policy and scheduling.

Current implementation:
1. CLI entrypoint at `qa_specialist_runner.py`.
2. Core orchestration in `spec_test_pilot/qa_specialist_agent.py`.

### 5.2 Agent Runtime Plane
Responsibilities:
1. Parse and inspect OpenAPI.
2. Plan tests like QA engineers (happy path, auth, validation, boundary, error, security).
3. Generate executable assets.
4. Execute scenarios and aggregate outcomes.

Current implementation:
1. `QASpecialistAgent.run()` orchestrates end-to-end flow.
2. `HumanTesterSimulator` creates scenarios.
3. `MultiLanguageTestGenerator` writes Python/JS/Java/cURL artifacts.
4. Per-scenario execution records expected vs actual status and timing.

### 5.3 Isolation Plane
Responsibilities:
1. Never execute tests directly against shared host process state.
2. Use ephemeral API runtime per run.
3. Enforce deterministic baseline behavior.

Current implementation:
1. Dynamic FastAPI app created from spec (`agent_lightning_server.py`).
2. In-memory isolated execution via `fastapi.testclient.TestClient`.

Future hardening:
1. Add Docker/Firecracker mode for stronger filesystem/network isolation.
2. Add CPU/memory/time quotas per test batch.

### 5.4 Memory Plane (GAM)
Responsibilities:
1. Session lifecycle (`start_session`, `add_to_session`, `end_session_with_memo`).
2. Lossless storage of transcript/tool outputs/artifacts.
3. Retrieval with tenant isolation.
4. Deep-research loop: plan -> search -> integrate -> reflect.

Current implementation:
1. `PageStore`, `Memorizer`, `Researcher`, `GAMMemorySystem`.
2. Hybrid retrieval over BM25 + optional vector.
3. Retrieval tools in research path:
   - query retrieval
   - group/tag retrieval
   - page-id retrieval
4. Parallel retrieval execution and result merge.

### 5.5 Learning Plane (Agent Lightning)
Responsibilities:
1. Collect non-intrusive traces.
2. Assign credit over trajectories.
3. Convert traces into RL transitions.
4. Update value/policy models.

Current implementation:
1. `ObservabilityCollector` captures per-session traces.
2. `CreditAssignmentModule` distributes reward backward.
3. `LightningRLAlgorithm` stores transitions and runs `train_step`.
4. QA agent keeps a persistent trainer instance for within-process accumulation.

## 6. Data Contracts

### 6.1 Input Contract
```json
{
  "spec_path": "examples/banking_api.yaml",
  "tenant_id": "qa_team",
  "prompt": "Generate auth and validation QA cases",
  "max_scenarios": 50,
  "pass_threshold": 0.70
}
```

### 6.2 Scenario Execution Contract
Each scenario yields:
1. `name`, `test_type`, `method`.
2. `endpoint_template`, `endpoint_resolved`.
3. `expected_status`, `actual_status`.
4. `passed`, `duration_ms`, `error`, `response_excerpt`.

### 6.3 Report Contract
Report includes:
1. Metadata (spec, tenant, timestamps, isolation mode).
2. Summary (pass rate, quality gate, breakdowns, failures).
3. Generated test file paths.
4. Scenario results.
5. GAM details (session, memo page, research evidence).
6. Agent Lightning results (training result + training stats).

## 7. Learning Loop: How “Smarter” Emerges

### 7.1 Short-term Improvement (Memory)
1. Prior failures and conventions are retrieved from GAM.
2. Retrieved excerpts are injected into prompt context.
3. Next run scenario emphasis shifts based on memory.

### 7.2 Medium-term Improvement (RL)
1. Outcome summary becomes reward signal.
2. Sidecar traces become transitions.
3. Replay buffer grows.
4. Value loss trends indicate model fitting progress.

### 7.3 Long-term Improvement (Needed)
Current gap: RL weights are not yet directly steering scenario generation policy in a strong closed loop.

Required next step:
1. Add explicit policy adapter where generation choices (test type mix, endpoint prioritization, retry strategy) are chosen from RL outputs.

## 8. Current State Assessment

### 8.1 What Is Working
1. End-to-end pipeline runs successfully.
2. Reports are generated (JSON + Markdown).
3. GAM sessions/memos/pages are created and searchable.
4. Agent Lightning training executes and accumulates within-process.
5. Test suite passes.

### 8.2 Improvement Needed
1. Persistent RL checkpoints across separate process runs.
2. Stronger reward shaping (coverage deltas, severity-weighted failures, flake penalty).
3. Real SUT mode in addition to mock mode.
4. Policy-action linkage from RL to generator decisions.
5. Trend analytics across runs (run-to-run quality regression detection).

## 9. Target Production Architecture (Recommended)

### Phase 1: Stable Baseline
1. Keep current flow.
2. Add persistent model/replay store.
3. Add run registry DB for report indexing.

### Phase 2: True Learning Control
1. Add policy gateway in scenario planner.
2. Feed RL output into scenario selection weights.
3. Add A/B policy rollout support.

### Phase 3: Enterprise Hardening
1. Containerized isolation for execution.
2. Strict per-tenant quotas and keys.
3. Full audit trail with artifact retention policy.
4. Quality gates integrated into CI.

## 10. Operational KPIs
1. Pass rate by endpoint category.
2. Coverage ratio by spec endpoints.
3. Defect detection density (unique failing patterns).
4. Mean test latency and timeout rate.
5. RL metrics: replay size, training steps, value loss trend.
6. GAM retrieval quality: hit rate of relevant pages.

## 11. Failure Modes and Controls
1. Spec parse failure
   - Control: fallback empty output + missing info contract.
2. Flaky execution
   - Control: deterministic mock mode baseline + re-run policy.
3. Memory contamination across tenants
   - Control: tenant_id scoped retrieval and storage checks.
4. RL drift
   - Control: checkpoint versioning + rollback.

## 12. Security and Tenant Isolation
1. Every run binds to `tenant_id`.
2. GAM retrieval honors tenant scope.
3. Artifacts are stored with source metadata and page references.
4. Sensitive data redaction should be added before long-term artifact retention.

## 13. File-to-Architecture Mapping
1. Orchestration: `spec_test_pilot/qa_specialist_agent.py`
2. CLI entrypoint: `qa_specialist_runner.py`
3. QA scenario design + codegen: `spec_test_pilot/multi_language_tester.py`
4. Isolated mock runtime: `agent_lightning_server.py`
5. Memory subsystem: `spec_test_pilot/memory/gam.py`
6. RL subsystem: `spec_test_pilot/agent_lightning_v2.py`

## 14. Recommended Next Technical Changes
1. Add `model_store/` for RL checkpoint save/load.
2. Add `reward_service.py` with explainable reward components.
3. Add `run_registry` persistence (SQLite/Postgres).
4. Add policy-action API between RL and scenario planner.
5. Add dashboard-ready metrics export (Prometheus/OpenTelemetry).

## 15. Summary
The current architecture is a strong v1: it executes the entire QA workflow with isolation, memory, and RL instrumentation.

To reach full autonomous improvement, the highest-value step is to connect RL outputs directly to generation decisions and persist model state across independent runs.
