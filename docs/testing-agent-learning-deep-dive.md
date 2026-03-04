# Testing Agent Deep Dive (Learns Like a Junior QA Engineer)

## 1. Product Behavior You Want

A production testing agent should:

1. Read API spec and generate test scripts.
2. Execute as many meaningful cases as budget allows.
3. Detect misses and mistakes from the last run.
4. Learn patterns of failure and improve selection/mutations next run.
5. Emit a clear report that explains what changed and why.

## 2. “Junior QA” Learning Model

Treat the agent like a junior engineer:

1. First run: broad but imperfect.
2. It misses some edge cases or mis-asserts statuses.
3. Feedback loop records those misses.
4. Next run: focuses more on prior weak spots while still exploring.
5. Over time: fewer repeated misses, better scenario targeting.

## 3. Core Components

1. Spec Understanding Module:
   - Parses operations, auth, request/response schemas, constraints.
2. Scenario Generator:
   - Builds base scenarios (happy + negative + boundary + auth).
3. Mutation Engine (RL-guided):
   - Creates variants of weak scenarios (missing fields, type fuzz, auth variants, path/query boundary variants).
4. Selector Policy (RL-guided):
   - Picks best scenarios under budget using risk + uncertainty + novelty + historical misses.
5. Executor:
   - Runs scripts/calls in isolated env (mock/staging profiles).
6. Evaluator:
   - Scores pass/fail + quality of assertions + reproducibility.
7. Memory + Research (GAM):
   - Stores run artifacts/insights and retrieves actionable context for next prompt.
8. Trainer (Agent Lightning):
   - Updates policy from per-scenario traces and persists checkpoint.

## 4. Data That Must Be Saved Every Run

1. Scenario-level outcome:
   - fingerprint, expected_status, actual_status, duration, passed.
2. Decision context:
   - why selected, uncertainty score, failure-priority score, mutation strategy.
3. Learning signals:
   - reward decomposition per scenario and run-level reward.
4. Memory artifacts:
   - weak patterns, trend deltas, repaired assertions, risky endpoints.
5. Script artifacts:
   - generated files and execution summaries.

Without this data, the agent cannot truly improve.

## 5. Learning Loop (Run-to-Run)

1. Before generation:
   - retrieve weak-pattern memory and trend deltas.
2. During planning:
   - convert memory into prompt focus points + policy priors.
3. During selection:
   - allocate budget to known weak areas plus uncertainty exploration.
4. After execution:
   - compute rewards and update scenario stats/policy.
5. Before next run:
   - persist checkpoint and derived insights.

## 6. What “Improvement” Means (Not Just Higher Pass Rate)

Good improvement signals:

1. New failure modes discovered.
2. Previously failing patterns become reproducible and then fixed.
3. Fewer redundant easy-pass scenarios.
4. Better risk coverage per same budget.
5. Better assertion quality (fewer wrong expected statuses).

Bad signal:

1. Pass rate rises only because agent avoids hard tests.

## 7. Junior Mistakes and How Agent Should Correct

Typical junior mistakes:

1. Wrong expectation (e.g., expecting 400 where endpoint returns 401/404 by contract).
2. Repeating same generic auth tests without endpoint-specific depth.
3. Overfitting to one endpoint and ignoring others.
4. Not distinguishing schema vs auth vs method errors.

Correction logic:

1. Detect mismatch clusters by fingerprint.
2. Canonicalize pattern by operation + test_type + expected class.
3. Re-sample and mutate around failure cluster.
4. Adjust future priority/weights.
5. Record “what changed” in report and memory.

## 8. Script Generation and Execution Strategy

1. Generate one primary executable script (customer-selected language).
2. Optionally generate additional language artifacts as non-blocking outputs.
3. Validate script quality:
   - endpoint resolution correctness
   - auth header behavior
   - payload validity/invalidity by intent
4. Execute and capture:
   - request, response status, response excerpt, timings.

## 9. GAM + RL Split of Responsibilities

GAM:

1. Research and retrieve context.
2. Keep evolving memory of weak patterns and trends.
3. Feed actionable context into prompt.

RL:

1. Decide where to spend testing budget.
2. Decide which mutations are likely useful.
3. Learn from reward/penalty to reduce repeated misses.

Both together:

1. GAM gives the agent memory and context.
2. RL gives the agent adaptive decision-making.

## 10. Report That Proves Learning (Must-Have Sections)

1. Scenario Source Breakdown:
   - llm_base vs rl_mutation vs history_seed.
2. Weak Pattern Delta:
   - previous failure_rate vs current failure_rate per fingerprint.
3. Selection Rationale:
   - why each scenario was selected.
4. Missed-Last-Time -> Covered-This-Time:
   - explicit mapping.
5. Reward Trace:
   - per-scenario reward and run reward components.
6. Next-Run Focus:
   - 3 highest-priority patterns to reinforce.

## 11. Production Readiness Checklist

1. Checkpoint save/load verified across restarts.
2. No static memory-only prompt dominance.
3. Deterministic fingerprinting and spec-scope isolation.
4. Flaky-test detection and downweighting.
5. Safety policy by environment tier.
6. UI glass-box trace for every major state.

## 12. Acceptance Criteria for “Agent Is Learning”

Over N consecutive runs on same API:

1. At least one weak-pattern metric changes in expected direction.
2. Selection portfolio changes with reasoned trace (not random drift).
3. Repeated misses either:
   - get resolved by improved assertions, or
   - remain flagged with stronger focus and mutation depth.
4. Report clearly explains what was learned and what remains weak.
