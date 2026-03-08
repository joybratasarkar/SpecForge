# Project File Organization

This document lists the active runtime file layout for SpecForge and points to the files that matter most during execution.

## 1. Top-Level Layout

1. `backend/`
- FastAPI services, QA orchestrator, dynamic mock runtime, RL/GAM modules, tests, example specs

2. `frontend/`
- Next.js customer UI app and launcher scripts

3. `docs/`
- architecture, runtime, learning, and API flow references

4. `data/`
- local dataset/experience files used by training utilities

## 2. Runtime Entry Points

## 2.1 Backend API (split mode)

1. `backend/start-backend.sh`
2. `backend/run_customer_backend_fastapi.sh`
3. `backend/qa_customer_api.py`

Main service URL default:

1. `http://127.0.0.1:8787`

## 2.2 Domain Runner (CLI or worker-launched)

1. `backend/run_qa_domain.sh`
2. `backend/qa_agent_runner.py`
3. `backend/spec_test_pilot/qa_specialist_agent.py`

## 2.3 Frontend Launchers

1. `frontend/start-frontend.sh` (split mode)
2. `frontend/start-full-next.sh` (full Next mode)
3. `frontend/run_customer_ui_next.sh`
4. `frontend/run_customer_frontend_next.sh`

## 3. Core Backend Modules

## 3.1 Orchestration and Execution

1. `backend/spec_test_pilot/qa_specialist_agent.py`
- primary end-to-end orchestrator

2. `backend/spec_test_pilot/multi_language_tester.py`
- scenario generation + script generation

3. `backend/dynamic_mock_server.py`
- dynamic OpenAPI-backed mock runtime + request validation/auth checks

4. `backend/spec_test_pilot/script_runner.py`
- script execution utilities

## 3.2 Learning and Policy

1. `backend/spec_test_pilot/adaptive_policy.py`
- contextual linear-UCB policy state/updates

2. `backend/spec_test_pilot/agent_lightning_v2.py`
- RL trace collection, replay buffer, checkpointing, periodic training

3. `backend/rl_periodic_trainer.py`
- standalone periodic RL batch trainer

4. `backend/spec_test_pilot/policies/qa_learning_policy.v1.json`
- default learning-policy knobs

## 3.3 Memory and Context

1. `backend/spec_test_pilot/memory/gam.py`
- GAM page store, memo/session handling, research/reflection loop

2. `backend/spec_test_pilot/mcp_tools.py`
- optional MCP context enrichment layer

3. `backend/spec_test_pilot/runtime_settings.py`
- central env-backed runtime settings and policy loading

## 4. Frontend Application Structure

1. `frontend/customer-ui-next/app/page.js`
- primary UI and diagnostics views

2. `frontend/customer-ui-next/lib/store.js`
- request normalization + job store state

3. `frontend/customer-ui-next/lib/runner.js`
- local job execution in full Next mode

4. `frontend/customer-ui-next/app/api/**`
- Next API route handlers for jobs/runs/report/scripts/spec-upload

## 5. Example Inputs and Smoke Assets

1. `backend/examples/openapi_smoke_types/`
- `bearer_inventory.yaml`
- `api_key_query_analytics.yaml`
- `public_form_webhooks.yaml`

2. `backend/examples/customer_frontend_sync_smoke_api.yaml`
- richer frontend contract smoke fixture

3. `backend/smoke_frontend_sync.py`
- programmatic smoke runner for frontend-shaped payloads

## 6. Test Suite Organization

1. `backend/tests/test_qa_specialist_auth_flow.py`
- large functional behavior coverage for orchestration, auth, mutation, selection

2. `backend/tests/test_dynamic_mock_server_validation.py`
- mock server validation/security/path behavior

3. `backend/tests/test_agent_lightning_checkpoint.py`
- RL checkpoint/replay behavior

4. `backend/tests/test_qa_customer_api_sync.py`
- API payload normalization and sync expectations

5. `backend/tests/test_mcp_tools.py`
- MCP integration behavior

6. `backend/tests/test_runtime_settings_contract.py`
- settings/policy env contract

## 7. Runtime Artifact Locations (Typical)

1. FastAPI job outputs:
- `/tmp/qa_ui_runs/<timestamp>_<jobid>_<domain>/`

2. FastAPI checkpoints:
- `/tmp/qa_ui_checkpoints/<tenant>_<domain>.pt`

3. Uploaded specs:
- FastAPI: `/tmp/qa_ui_uploaded_specs/`
- Next full mode: `/tmp/qa_ui_next_uploaded_specs/`

4. Next full-mode run outputs/checkpoints:
- `/tmp/qa_ui_next_runs/`
- `/tmp/qa_ui_next_checkpoints/`

## 8. Related Docs

1. `docs/agent-architecture-flow-in-depth.md`
2. `docs/qa-agent-runtime-step-map.md`
3. `docs/qa-agent-learning-data-flow.md`
4. `docs/customer-ui-api-flow.md`
5. `docs/production-run-inputs.md`
