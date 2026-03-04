# Backend

This folder is the backend entrypoint layer for the QA agent system.

Backend runtime code is now physically located in this folder:

1. FastAPI app: `qa_customer_api.py`
2. Domain runner: `run_qa_domain.sh`
3. QA agent core: `spec_test_pilot/qa_specialist_agent.py`
4. RL trainer: `spec_test_pilot/agent_lightning_v2.py`

## Start FastAPI backend

1. Create backend venv (first time):
```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

2. Start backend:
```bash
./backend/start-backend.sh
```

Default:

1. host: `127.0.0.1`
2. port: `8787`

## Run one domain from backend

```bash
./backend/run-domain.sh --domain ecommerce --customer-mode --verify-persistence
```

This writes:

1. generated test scripts
2. `qa_execution_report.json`
3. `qa_execution_report.md`
4. RL checkpoint (if provided)

## Memory + RL Scope (Important)

GAM memory retrieval and RL scenario history are now scoped per OpenAPI spec:

1. `scenario_stats` are filtered to the current spec before mutation/selection/prompt focus.
2. GAM memo pages (`spec_context`, `rl_signal`) are tagged with a spec scope key.
3. Research retrieval keeps conventions globally, but filters memo pages to current spec tags.

This prevents cross-domain leakage like `/orders/...` signals appearing while running a `/shipments/...` spec under the same tenant/checkpoint.

Paper-aligned GAM deep-research fields are now exposed in report JSON:

1. `gam.research_info_checks` (`request_status`, `missing`, `next_request`)
2. `gam.research_retrieval_trace` (iteration plan + retrieval tool usage summary)
3. `gam.research_iterations`
4. `gam.research_engine` (planner/reflector mode + LLM stats)

## Backend APIs (customer UI)

Base URL: `http://127.0.0.1:8787`

1. `POST /api/jobs` - create run job
2. `GET /api/jobs` - list jobs
3. `GET /api/jobs/{job_id}` - job snapshot
4. `GET /api/jobs/{job_id}/events` - SSE stream
5. `GET /api/jobs/{job_id}/report/{domain}?format=json|md` - reports
6. `GET /api/jobs/{job_id}/generated-tests/{domain}` - generated files
7. `GET /api/jobs/{job_id}/generated-tests/{domain}/{kind}` - script content

## Useful Environment Variables

1. `BACKEND_HOST`
2. `BACKEND_PORT`
3. `QA_UI_ALLOWED_ORIGINS`
4. `BACKEND_RELOAD` (`1` to enable uvicorn reload)
5. `OPENAI_API_KEY` (required for active GAM LLM calls)
6. `GAM_LLM_MODE` is enforced to `on` by runtime/scripts
7. `GAM_MEMO_LLM_MODE` is enforced to `on` by runtime/scripts
8. `GAM_OPENAI_MODEL` (default `gpt-4.1-mini`)
9. `GAM_LLM_TIMEOUT_SECONDS` (default `12`)
10. `GAM_MAX_REFLECTIONS` (default `2`, bounded `1..8`)
11. `GAM_MEMO_OPENAI_MODEL` (default inherits `GAM_OPENAI_MODEL`)
12. `QA_SCENARIO_LLM_MODE` (`auto`|`on`|`off`, default `auto`)
13. `QA_SCENARIO_LLM_MODEL` (default `gpt-4.1-mini`)
14. `QA_SCENARIO_LLM_TIMEOUT_SECONDS` (library default `20`, domain runner default `45`)
15. `QA_SCENARIO_LLM_MAX_RETRIES` (library default `1`, domain runner default `1`)
