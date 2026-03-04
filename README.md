# Reinforcement QA Agent

This project is organized into two customer-facing entry folders:

1. `backend/` - FastAPI backend and QA agent runtime
2. `frontend/` - Next.js frontend (customer UI)

The code is physically separated:

1. backend Python runtime and agent code live under `backend/`
2. frontend Next.js application lives under `frontend/customer-ui-next/`

## Folder Guide

1. Backend guide: `backend/README.md`
2. Frontend guide: `frontend/README.md`
3. Technical deep docs: `docs/README.md`

## Quick Start (split FE/BE)

1. Create backend environment (first time):
```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

2. Start backend:
```bash
./backend/start-backend.sh
```

3. Start frontend (new terminal):
```bash
./frontend/start-frontend.sh
```

4. Open UI:
```text
http://localhost:3001
```

## One-command UI mode

If you want frontend with built-in local API routes only:

```bash
./frontend/start-full-next.sh
```

## How Scenario Learning Works (LLM + GAM + RL)

This is the behavior you asked about:

1. Test type labels can stay the same while scenarios change.
2. `Coverage By Test Type` is category-level (`authentication`, `error_handling`, etc.), not exact scenario payload/name comparison.

### Runtime flow

1. LLM creates base scenario candidates from the OpenAPI spec and prompt.
   - Controlled by `QA_SCENARIO_LLM_MODE` (`auto|on|off`), with heuristic fallback.
2. GAM (memory/research) enriches the prompt context for scenario generation.
   - GAM planner/reflection mode is enforced to `on`.
   - With `OPENAI_API_KEY` set, GAM uses LLM planning/reflection; without key or on call failure it falls back to heuristic behavior.
   - GAM reflection depth is configurable with `GAM_MAX_REFLECTIONS`.
3. RL does not fine-tune LLM weights here. RL is used to:
   - mutate/add candidates
   - prioritize/select which scenarios execute
   - update future scoring from reward/penalty history

### Cross-domain safety

When multiple domains share the same tenant/checkpoint, GAM and RL are spec-scoped:

1. Memo retrieval is filtered by current spec tags.
2. RL scenario stats are filtered by current spec key before prompt focus, mutation, and selection.
3. Convention guidance remains global by design.

### Where to verify in JSON report

1. LLM base count: `selection_policy.base_candidate_count`
2. RL added count: `mutation_policy.mutated_candidates_added`
3. GAM influence: `gam.research_plan`, `gam.research_excerpt_count`
   - GAM engine mode: `gam.research_engine.plan_modes`, `gam.research_engine.reflect_modes`
   - GAM LLM call stats: `gam.research_engine.llm_stats`
4. Scenario generation engine trace: `prompt_trace.scenario_generation`
5. Per-scenario reward/penalty: `learning.feedback.decision_signals`
6. Run-to-run learning deltas: `learning.state_snapshot.improvement_deltas`
7. RL mutation mix and adaptive generation:
   - `mutation_policy.mutation_strategy_breakdown`
   - `mutation_policy.top_targets`
   - `mutation_policy.applied_examples` (`strategy`, `mutation_budget`, `operation_failure_rate`)

### Where to verify in UI

1. `Scenario Influence Map (LLM vs GAM vs RL)`
2. `RL Improvement Over Time`
3. `State-by-State API Output (Glass Box)`
4. `Executed Scenarios By Source` (LLM base vs RL mutation vs RL history-seed)

### Why coverage can look unchanged

If only scenario internals changed (payload values, auth headers, params, edge variants), category totals can remain similar even though the executed scenario set is different.
