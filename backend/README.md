# Backend Guide

This directory contains the QA runtime, API services, and learning components.

## Key Components

1. `qa_customer_api.py`: customer-facing FastAPI job API
2. `qa_agent_runner.py`: domain execution entrypoint
3. `spec_test_pilot/qa_specialist_agent.py`: core orchestration pipeline
4. `spec_test_pilot/agent_lightning_v2.py`: RL training runtime
5. `spec_test_pilot/memory/gam.py`: GAM memory and research layer

## Setup

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

## Run Backend API

```bash
./backend/start-backend.sh
```

Startup policy:

1. Periodic RL scheduler is enabled by default on every restart.
2. `QA_RL_PERIODIC_ENABLED` is enforced to `1` by `run_customer_backend_fastapi.sh`.
3. Interval and batch knobs can be tuned with:
   - `QA_RL_PERIODIC_INTERVAL_SEC` (default `300`)
   - `QA_RL_PERIODIC_MAX_STEPS` (default `25`)
   - `QA_RL_PERIODIC_MIN_BUFFER` (default `32`)
4. Scenario volume defaults to `64` in the customer API and can auto-expand by spec size.
5. Real-world suites are enabled in-agent (resiliency retry/timeout/503, p95/p99 probes, BOLA/SSRF/data-leakage checks, concurrency conflict, backward-compat and payload-drift probes).
6. Contract verification can run in strict mode with `QA_STRICT_CONTRACT_CHECKS=1` (default strict for non-`mock` profiles).

Default endpoint:

```text
http://127.0.0.1:8787
```

## Run QA Agent (CLI)

Recommended mode:

```bash
./backend/run_qa_domain.sh --domain ecommerce --customer-mode --verify-persistence --rl-train-mode periodic
```

Advanced mode:

```bash
./backend/run_qa_domain.sh \
  --domain ecommerce \
  --action both \
  --output-dir /tmp/qa_ecommerce_run \
  --rl-checkpoint /tmp/agent_lightning_ecommerce.pt \
  --rl-train-mode periodic
```

Frontend contract smoke (uses full frontend payload shape with advanced scope, API-key auth, and mutation rules):

```bash
cd backend
./.venv/bin/python smoke_frontend_sync.py
```

Periodic background trainer:

```bash
python backend/rl_periodic_trainer.py \
  --checkpoint /tmp/agent_lightning_ecommerce.pt \
  --train-mode periodic \
  --max-steps 25 \
  --min-buffer 32
```

RL mode:

1. `periodic` (mandatory): collect transitions during runs, train later in scheduled batches.

## Backend API Endpoints

Base URL: `http://127.0.0.1:8787`

1. `POST /api/jobs`: create a QA job
2. `GET /api/jobs`: list jobs
3. `GET /api/jobs/{job_id}`: job snapshot
4. `GET /api/jobs/{job_id}/events`: SSE events
5. `GET /api/jobs/{job_id}/report/{domain}?format=json|md&view=full|executive|summary|technical`: run reports
6. `GET /api/jobs/{job_id}/generated-tests/{domain}`: generated files
7. `GET /api/jobs/{job_id}/generated-tests/{domain}/{kind}`: script content
8. `GET /api/system/periodic-rl`: periodic RL worker health + latest summary
9. `POST /api/system/periodic-rl/run-now`: trigger one periodic RL training tick immediately

## Important Environment Variables

1. `BACKEND_HOST`
2. `BACKEND_PORT`
3. `BACKEND_RELOAD`
4. `QA_UI_ALLOWED_ORIGINS`
5. `OPENAI_API_KEY`
6. `QA_SCENARIO_LLM_MODE` (`auto|on|off`)
7. `QA_SCENARIO_LLM_MODEL`
8. `QA_SCENARIO_LLM_TIMEOUT_SECONDS`
9. `GAM_LLM_MODE`
10. `GAM_MEMO_LLM_MODE`
11. `GAM_OPENAI_MODEL`
12. `GAM_MAX_REFLECTIONS`
13. `RL_TRAIN_MODE` (`periodic`)
14. `QA_RL_PERIODIC_ENABLED` (`1`, enforced by startup script)
15. `QA_RL_PERIODIC_INTERVAL_SEC`
16. `QA_RL_PERIODIC_MAX_STEPS`
17. `QA_RL_PERIODIC_MIN_BUFFER`
18. `QA_AUTO_SCENARIO_EXPAND` (`1|0`, default `1`)
19. `QA_MIN_SCENARIOS_PER_OPERATION` (default `10`)
20. `QA_AUTO_SCENARIO_CAP` (default `240`)
21. `QA_STRICT_CONTRACT_CHECKS` (`1|0`, defaults to `1` for non-`mock` profiles)
22. `QA_STRICT_CONTRACT_REQUIRE_RESPONSE_SCHEMA` (`1|0`, default `0`; when `1`, missing response schema fails strict contract checks)
23. `QA_MCP_ENABLED` (`1|0`, default `0`) enables optional MCP tool enrichment
24. `QA_MCP_SERVERS_JSON` (JSON config for MCP stdio servers)
25. `QA_MCP_MAX_TOOLS_PER_SERVER` (default `2`)
26. `QA_MCP_MAX_EXCERPTS` (default `6`)
27. `QA_MCP_TIMEOUT_SECONDS` (default `8`)
28. `QA_MCP_MAX_CALLS_TOTAL` (default `12`, global MCP call budget per run)
29. `QA_MCP_ALLOWED_TOOLS_JSON` (allowlist map per MCP server, supports `*` wildcard server/tool patterns)
30. `QA_MCP_REQUIRE_ALLOWLIST` (`1|0`, default `1`)
31. `QA_MCP_ALLOW_MUTATING_TOOLS` (`1|0`, default `0`)
32. `QA_ALLOW_UNSAFE_CHECKPOINT_LOAD` (`1|0`, default `0`; only for trusted legacy RL checkpoints that fail safe load)
33. `QA_MOCK_ALLOWED_ORIGINS` (comma-separated origins for dynamic mock server CORS)
34. `QA_MOCK_CORS_ALLOW_CREDENTIALS` (`1|0`, default `0`; ignored when origin list contains `*`)
35. `QA_DEFAULT_BASE_URL` (default `http://localhost:8000`, shared base URL default for CLI/API)
36. `QA_DEFAULT_ENVIRONMENT_PROFILE` (default `mock`)
37. `QA_AUTH_VALID_TOKEN` / `QA_AUTH_ADMIN_TOKEN` / `QA_AUTH_INVALID_TOKEN` / `QA_AUTH_EXPIRED_TOKEN`
38. `QA_CHAOS_ONCE_503_MODE` / `QA_CHAOS_ONCE_TIMEOUT_MODE` / `QA_CHAOS_CONCURRENCY_MODE`
39. `QA_SSRF_PROBE_URL` (default `http://169.254.169.254/latest/meta-data`)
40. `QA_SCRIPT_EXEC_MAX_RUNTIME_SEC` (default `120`)
41. `QA_LIVE_PREFLIGHT_ENABLED` (`1|0`, default `1`; live profiles run connectivity preflight before scenario execution)
42. `QA_LEARNING_POLICY_FILE` (optional JSON policy override file path; default `backend/spec_test_pilot/policies/qa_learning_policy.v1.json`)

### Optional MCP Server Config Example

```bash
export QA_MCP_ENABLED=1
export QA_MCP_SERVERS_JSON='[
  {
    "name": "filesystem_docs",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/sjoybrata/Desktop/reinforcement-agent/docs"],
    "timeout_sec": 8
  }
]'
```

Notes:

1. MCP integration is best-effort and non-blocking; failed tool calls are reported but do not fail the QA run.
2. By default MCP requires an explicit allowlist (`QA_MCP_REQUIRE_ALLOWLIST=1`) and blocks mutating tools.
3. MCP outputs are converted to additional GAM context excerpts with source `mcp_tool`.

## Testing

Run backend tests:

```bash
backend/.venv/bin/pytest backend/tests -q
```

## Related Docs

1. `docs/agent-architecture-flow-in-depth.md`
2. `docs/qa-agent-learning-data-flow.md`
3. `docs/customer-ui-api-flow.md`
4. `docs/production-run-inputs.md`
