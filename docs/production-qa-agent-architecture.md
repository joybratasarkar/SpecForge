# Production QA Agent Architecture (GAM + RL + Agent Lightning)

## 1. Product Objective

1. Optimize for `defect discovery per test budget`, not raw pass-rate.
2. Run safely across `mock -> staging -> shadow prod` with explicit guardrails.
3. Keep every decision explainable in UI (`why selected`, `why mutated`, `what improved`).

## 2. Current Failure Modes

1. Reward is pass-rate-heavy, so the policy drifts toward safe/static tests.
2. GAM retrieval is often memo-heavy and generic, reducing useful variation.
3. Mutation policy is template-bounded, capping novelty.
4. Mock-only execution produces weak real-world learning signal.
5. Prompt pack has no strict diversity/actionability contract.

## 3. Target Agent Contract

1. Input: `OpenAPI + environment profile + historical memory + risk policy`.
2. Output: `ranked scenarios + generated scripts + execution outcomes + learning deltas`.
3. Hard guarantee: each run must show either:
   - new/changed focus and policy movement, or
   - an explicit reason that no movement occurred.

## 4. GAM Role (Memory + Research)

1. Maintain three memory layers:
   - `raw_run_artifacts`
   - `derived_insights`
   - `playbook_actions`
2. Use iterative research loop:
   - `plan -> retrieve(query/group/page_id) -> integrate -> info-check -> iterate`
3. Enforce retrieval pack contract (must include all):
   - one weak/failing pattern
   - one trend delta
   - one spec risk hint
   - one actionable test strategy
4. Drop low-signal memory by policy:
   - generic spec-only lines
   - repeated title duplicates
   - dense machine/log blobs

## 5. RL Role (Learning + Decisioning)

1. Policy A: scenario portfolio selection under budget.
2. Policy B: mutation action selection for candidate expansion.
3. Policy C (optional): repair strategy selection after repeated mismatches.
4. Train from per-scenario traces (dense rewards), not only run summary.

## 6. Reward Design (Production-Grade)

Positive reward:
1. New bug/failure mode discovered (`new fingerprint`).
2. Failure reproduced on rerun (stability signal).
3. Coverage gain on risky operations.

Negative reward:
1. Redundant safe pass on over-tested pattern.
2. Flaky/non-deterministic scenario.
3. Policy violations (unsafe payloads in protected environments).

## 7. Runtime Sequence

1. Normalize spec and build operation graph.
2. Run GAM retrieve/info-check loop until quality gate passes.
3. LLM generates base scenarios from spec + GAM pack.
4. RL mutation expands candidate pool.
5. RL selector ranks candidates by uncertainty, failure-focus, and diversity.
6. Execute in environment tier with isolation policy.
7. Update:
   - adaptive policy state
   - Agent Lightning replay/checkpoint
   - GAM derived insight pages
8. Emit glass-box report and run-over-run deltas.

## 8. Production KPIs

1. `new_failure_modes_per_100_tests`
2. `repeatability_rate_of_failures`
3. `unique_risky_operations_covered`
4. `redundancy_rate`
5. `time_to_actionable_bug_report`
6. `memory_actionability_score`
7. `rl_policy_delta_effect`

## 9. Minimum Services

1. Orchestrator service.
2. Memory service (GAM store + retriever + quality gate).
3. Policy service (selection + mutation + optional repair).
4. Execution service (mock/staging/prod-safe adapters).
5. Training service (Agent Lightning checkpoints + replay lifecycle).
6. Report API + UI service (full decision trace).

## 10. Implementation Roadmap

Phase 1:
1. Enforce GAM retrieval pack contract + quality gate.
2. Add strict rejection of low-actionable/generic memory packs.

Phase 2:
1. Replace pass-rate-heavy reward with discovery-weighted reward.
2. Add reproducibility scoring path.

Phase 3:
1. Introduce mutation policy plugin interface (beyond fixed templates).
2. Add adaptive mutation budget by risk and novelty.

Phase 4:
1. Add staging adapter + flaky detection.
2. Add environment safety policies.

Phase 5:
1. Add policy evaluation dashboard.
2. Add controlled rollout and regression gates.

## 11. Data Schemas to Add Next

1. `memory_page` (layer, source, scope, quality score, lineage).
2. `decision_trace` (candidate features, selected reason, uncertainty, expected value).
3. `reward_event` (per-scenario reward decomposition + penalties).
4. `policy_update` (weight deltas, checkpoint hash, replay stats).
5. `run_delta` (what changed since previous run and why).

## 12. Non-Goals

1. Maximizing pass-rate as primary success metric.
2. Generic static convention prompting without run-specific signals.
3. Black-box operation without decision-level introspection.
