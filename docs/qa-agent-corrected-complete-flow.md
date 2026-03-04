# QA Agent Corrected Complete Flow (GAM + RL + Agent Lightning)

## 1) Goal

Build a production QA testing agent that:

1. Generates meaningful test scenarios from any OpenAPI spec.
2. Executes tests in isolation and produces clear reports.
3. Learns from misses (wrong expectations, repeated failures, blind spots).
4. Improves future scenario generation, mutation, and selection.

## 2) Core Correction Points

These are the key fixes to enforce:

1. No static domain logic: everything must be spec-scoped (`spec_key`) and tenant-scoped.
2. GAM must store/retrieve actionable run insights, not repetitive generic text.
3. RL must optimize scenario decisions (mutation + selection), not just show training counters.
4. Report/UI must show evidence of learning deltas run-over-run.
5. Prompt context must contain dynamic weak-pattern + trend signals, not only static conventions.

## 3) Responsibilities Split

### GAM (Memory + Research)

1. Stores run artifacts and derived insights.
2. Runs planner/retriever/info-check loop to build high-value context.
3. Returns a compact context pack for scenario generation.

### RL / Agent Lightning (Policy Learning)

1. Learns which scenario types and mutations are most valuable.
2. Selects best scenarios under budget using uncertainty + failure-focus + diversity.
3. Updates policy using per-scenario reward signals and persists checkpoints.

### LLM (Scenario Synthesis)

1. Generates base scenarios from spec + GAM context + RL focus hints.
2. Should not be the only intelligence source.

## 4) Correct Runtime Flow (End-to-End)

## Stage 0: Scope Identity

Input:
1. `tenant_id`
2. `spec_path` (or uploaded spec)

Output:
1. `spec_key` (stable fingerprint from title/version/ops)
2. scoped storage paths (`.../<tenant>/<spec_key>/...`)

Rules:
1. Never mix memory/policy across specs.
2. Cross-spec retrieval is opt-in only.

## Stage 1: Spec Ingestion + Risk Graph

Input:
1. OpenAPI doc

Process:
1. Parse operations, auth, request schemas, path/query params, status expectations.
2. Build operation-risk graph (auth-heavy, write endpoints, id-based reads, pagination).

Output:
1. normalized operation list
2. risk hints used by GAM and selector

## Stage 2: GAM Writeback of Fresh Facts

Input:
1. previous run reports (if any)
2. current spec metadata
3. learning state snapshot

Process:
1. Write `raw_run_artifact` pages (facts only).
2. Write `derived_insight` pages (weak patterns, trend deltas, recurring misses).
3. Write `playbook_action` pages (what to try next run).

Output:
1. memory pages with tags: `tenant`, `spec_key`, `run_id`, `weak_pattern`, `trend`

## Stage 3: GAM Planner Loop (LLM Mode ON)

Input:
1. spec context
2. learning hints (top weak patterns + deltas)
3. memory index

Process:
1. Planner generates retrieval queries.
2. Retriever fetches candidate pages.
3. InfoCheck validates quality/actionability.
4. Repeat until quality gate or max reflections.

Output (`context pack` contract):
1. at least 1 weak pattern
2. at least 1 trend delta
3. at least 1 spec-specific risk hint
4. at least 1 concrete next-test action

Reject context packs that are only generic conventions.

## Stage 4: Base Scenario Generation (LLM)

Input:
1. normalized spec
2. GAM context pack
3. RL focus hints (weak fingerprints + targets)

Process:
1. Generate broad candidates across categories:
   - auth
   - input validation
   - boundary
   - error handling
   - happy-path
2. Attach provenance: `source=llm_base`.

Output:
1. candidate scenario pool with fingerprints and metadata

## Stage 5: RL Mutation + Selection

Input:
1. base candidates
2. policy state (`learning_state.json`)
3. checkpoint state (`agent_lightning_checkpoint.pt`)

Process A (mutation):
1. Expand weak areas with controlled mutations:
   - auth variants
   - schema mismatch variants
   - boundary/pagination variants
   - id/path edge variants
2. Attach provenance: `source=rl_mutation`, `mutation_strategy`.

Process B (selection):
1. Score each candidate using:
   - expected reward
   - uncertainty bonus
   - historical failure focus
   - diversity penalty
2. Select budget-constrained final set.

Output:
1. selected scenarios with full decision trace (`why selected`)

## Stage 6: Isolated Execution

Input:
1. selected scenarios
2. target env profile (`mock`, `staging`, etc.)

Process:
1. Execute scenario calls in isolated harness.
2. Capture request/response/timing/assertion details.

Output:
1. per-scenario results
2. generated scripts (customer-selected language + optional others)

## Stage 7: Evaluation + Rewarding

Input:
1. execution results
2. selection trace

Process:
1. Compute per-scenario reward (not pass-rate only).
2. Reward examples:
   - new reproducible failure
   - coverage gain on risky operation
3. Penalty examples:
   - redundant safe pass on over-tested pattern
   - flaky result
   - repeated wrong expectation without correction

Output:
1. `learning.feedback.decision_signals`
2. run reward decomposition

## Stage 8: Agent Lightning Training (Disaggregated)

Input:
1. trajectory traces from stage 5-7

Process:
1. Add to replay buffer.
2. Train policy/value updates.
3. Save checkpoint atomically.

Output:
1. updated policy weights
2. checkpoint metadata (steps, buffer size, losses)

## Stage 9: Persist + Explainability Output

Persist:
1. `qa_execution_report.json`
2. `qa_execution_report.md`
3. `learning_state.json`
4. RL checkpoint
5. GAM memory pages

Must include run-over-run deltas:
1. weak pattern improved/worsened
2. scenario portfolio changes
3. top policy movements

## 5) Data Contract per Stage

1. `spec_ingest` -> `operations[]`, `auth_model`, `schema_map`, `risk_graph`
2. `gam_context_pack` -> `weak_patterns[]`, `trend_deltas[]`, `spec_risks[]`, `actions[]`
3. `scenario_pool` -> `scenario_id`, `fingerprint`, `source`, `test_type`, `expected_status`
4. `selection_trace` -> `score`, `uncertainty`, `historical_reward`, `selection_reason`
5. `execution_result` -> `actual_status`, `passed`, `response_excerpt`, `duration_ms`
6. `reward_event` -> `reward`, `breakdown`, `penalties`, `novelty`
7. `policy_update` -> `training_steps`, `buffer_size`, `losses`, `checkpoint_path`

## 6) Universal (Any Domain / Any OpenAPI) Rules

1. Domain input must come from uploaded spec or selected preset, never hardcoded branch logic.
2. All memories and RL stats are keyed by `tenant_id + spec_key`.
3. Prompt focus must be generated from spec-specific weak patterns, not reused global text.
4. If no weak pattern exists, switch to exploration mode and log why.

## 7) UI Requirements (Customer-Visible, No Black Box)

Show these panels every run:

1. Final prompt (hide/show).
2. GAM context pack with source page IDs and why each excerpt was selected.
3. RL usage panel:
   - where RL changed selection
   - where RL added mutations
   - what improved vs previous run
4. Scenario source breakdown (`llm_base`, `rl_mutation`, `history_seed`).
5. Weak-pattern delta table (`prev_failure_rate -> current_failure_rate`).
6. Generated script viewer (selected primary language first).

## 8) Definition of "Agent Is Learning"

A run is considered learning-positive only if at least one is true:

1. A known weak pattern failure rate moves in expected direction.
2. Selection portfolio changes with a clear policy reason.
3. New high-risk scenario family is introduced and evaluated.
4. Previous wrong expectation is corrected and stays stable on rerun.

If none happen, report must explicitly say: `no_learning_delta_detected` with reason.

## 9) Minimal Implementation Plan

1. Enforce strict GAM context-pack quality gate.
2. Enforce spec-scoped storage keys end-to-end.
3. Upgrade reward function toward defect discovery and reproducibility.
4. Ensure RL mutation strategies are actually used in scenario pool.
5. Add run-over-run delta sections in API + UI.

This is the target complete flow for a production-grade testing agent using GAM + Agent Lightning RL.

## 10) Implementation Status (Current Repo)

Implemented now:
1. Stage 0 scope and runtime caps are enforced in runtime metadata and execution controls.
2. Stage 1 spec intelligence is emitted in report (`spec_intelligence`) with dependency graph, workflow candidates, and risk map.
3. Stage 2 GAM context pack now includes selected + rejected pages, contract checks, quality score, and fallback trusted-doc excerpts when weak.
4. Stage 3 scenario generation now emits trace steps with `thought -> action -> observation_goal` and `source=llm_base`.
5. Stage 4 includes RL mutation plus learned schema-driven mutation proposals (beyond static buckets).
6. Stage 5 selection and mutation traces are emitted with scenario source breakdown.
7. Stage 6 execute-and-verify loop includes status correction checks, response-schema contract checks, and minimized repro payloads.
8. Stage 7 reward/training emits dense decision signals and run-over-run learning delta status.
9. Stage 8 reporting + UI expose glass-box fields and `/api/runs/*` APIs.

Adapter-ready OSS tooling visibility:
1. `oss_tooling` reports package/CLI availability.
2. `oss_checks` reports ready/skipped status for RESTler, Schemathesis, EvoMaster, Pact, ZAP, k6/Locust, and testcontainers paths.
