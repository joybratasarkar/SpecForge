You are an engineering coding agent. Generate a complete, runnable Python project that implements an RL-trainable “API Spec → Testcase JSON” agent using LangGraph + a GAM-style deep-research memory loop + an Agent Lightning training harness.

DELIVERABLE FORMAT (MANDATORY)
Return the project as multiple files. For EACH file:
1) Print the file path on a single line like: ### path/to/file.py
2) Then include the full file contents in a fenced code block.
Do not add extra commentary outside the files.

PROJECT GOAL
Build “SpecTestPilot” that:
- Takes an OpenAPI spec (YAML or JSON) as input
- Outputs ONLY valid JSON that matches the strict schema below
- Never invents endpoints/params/schemas/status codes/auth not present in the spec
- Uses a GAM-style memory system with a Researcher that runs: plan → search → integrate → reflect (max 2 iterations)
- Is RL-friendly with a deterministic reward function and a synthetic dataset generator
- Includes an Agent Lightning training script that runs in “mock mode” locally (no external keys required)

REQUIRED FILES (MUST CREATE ALL)
- README.md
- requirements.txt
- spec_test_pilot/__init__.py
- spec_test_pilot/schemas.py
- spec_test_pilot/openapi_parse.py
- spec_test_pilot/memory/gam.py
- spec_test_pilot/graph.py
- spec_test_pilot/reward.py
- data/generate_dataset.py
- train_agent_lightning.py
- run_agent.py
- tests/test_contract.py

STRICT JSON OUTPUT CONTRACT (MUST ENFORCE WITH PYDANTIC)
At runtime, the agent MUST output ONLY valid JSON matching EXACTLY:

{
  "spec_summary": {
    "title": "<string|unknown>",
    "version": "<string|unknown>",
    "base_url": "<string|unknown>",
    "auth": {
      "type": "<none|apiKey|bearer|oauth2|unknown>",
      "details": "<string|unknown>"
    },
    "endpoints_detected": [
      {"method": "GET|POST|PUT|PATCH|DELETE", "path": "/...", "operation_id": "<string|unknown>"}
    ]
  },
  "deep_research": {
    "plan": ["..."],
    "memory_excerpts": [
      {"source": "convention|existing_tests|runbook|validator|memo", "excerpt": "..."}
    ],
    "reflection": "..."
  },
  "test_suite": [
    {
      "test_id": "T001",
      "name": "<METHOD> <PATH> <case>",
      "endpoint": {"method": "GET|POST|PUT|PATCH|DELETE", "path": "/..."},
      "objective": "...",
      "preconditions": ["..."],
      "request": {
        "headers": {"Authorization": "<token|omit if none>", "Content-Type": "application/json"},
        "path_params": {"<name>": "<value>"},
        "query_params": {"<name>": "<value>"},
        "body": {"<field>": "<value>"}
      },
      "assertions": [
        {"type": "status_code", "expected": 200},
        {"type": "schema", "expected": "<schema name or inline minimal contract>"},
        {"type": "field", "path": "$.<field>", "rule": "exists"}
      ],
      "data_variants": [
        {"description": "optional", "overrides": {}}
      ],
      "notes": ""
    }
  ],
  "coverage_checklist": {
    "happy_paths": "<true|false|unknown>",
    "validation_negative": "<true|false|unknown>",
    "auth_negative": "<true|false|unknown>",
    "error_contract": "<true|false|unknown>",
    "idempotency": "<true|false|unknown>",
    "pagination_filtering": "<true|false|unknown>",
    "rate_limit": "<true|false|unknown>"
  },
  "missing_info": ["..."]
}

MISSING-SPEC BEHAVIOR (MANDATORY)
If the spec input is missing/empty/unparseable:
- endpoints_detected = []
- test_suite = []
- coverage_checklist fields = "unknown"
- missing_info MUST include at least:
  1) API spec content (OpenAPI/Swagger YAML/JSON)
  2) auth method details (if any)
  3) environment/base URL + required headers (if any)

NO-HALLUCINATION GUARANTEE (MUST ENFORCE)
- Parse endpoints strictly from the OpenAPI spec.
- Every test_suite[i].endpoint must match a detected endpoint.
- Do not add parameters/schemas/status codes unless present in the spec.
- If ambiguous/incomplete, use placeholders and record exactly what is missing in missing_info.

GAM-STYLE MEMORY (IMPLEMENT)
Implement a minimal GAM-like subsystem:
- PageStore: append-only pages (id, title, tags, content, timestamp)
- Memorizer: produces a short “memo” for each run; store memo + raw run artifacts as pages
- Researcher deep-research loop (max_reflections=2):
  1) plan: decide what conventions/templates are needed
  2) search: retrieve relevant pages using BOTH keyword search (BM25) AND vector search (sentence-transformers)
  3) integrate: produce <= 5 memory_excerpts, each <= 2 lines
  4) reflect: decide whether another search iteration is needed

LANGGRAPH REQUIREMENTS
Use LangGraph with a State model containing at least:
- spec_text, parsed_spec, endpoints
- research_plan, retrieved_pages, memory_excerpts, reflection_count
- draft_output, validated_output, missing_info
- reward (float)

Minimum nodes:
- parse_spec
- detect_endpoints
- deep_research_plan
- deep_research_search
- deep_research_integrate
- deep_research_reflect (loop controller)
- generate_tests
- finalize_and_validate_json (Pydantic validate; strict JSON only)

REWARD FUNCTION (RL-FRIENDLY)
Implement spec_test_pilot/reward.py:
reward(output_json, parsed_spec, gold) -> float
Hard-gates (return 0.0 if fail):
- Output is valid JSON and passes Pydantic validation
- No invented endpoints: every test_suite endpoint exists in parsed_spec endpoints
Positive components (sum then clip to [0,1]):
- endpoint_coverage: fraction of endpoints that have >= 3 tests (1 happy + 2 negative)
- negative_quality: has missing-field + invalid-type/format negatives
- auth_negative: if auth exists, includes an auth-negative test per endpoint
- missing_info_quality: if spec incomplete, missing_info contains required items
Also add optional intermediate reward hooks per node.

SYNTHETIC DATASET GENERATOR (BIG ENOUGH)
Implement data/generate_dataset.py to output:
- data/train.jsonl with >= 500 rows
- data/test.jsonl with >= 100 rows
Each row:
{
  "task_id": "...",
  "openapi_yaml": "...",
  "gold": {
    "title": "...",
    "version": "...",
    "base_url": "...",
    "auth_type": "...",
    "endpoints": [{"method":"GET","path":"/x","operation_id":"..."}],
    "notes": "..."
  }
}
Generator requirements:
- Random OpenAPI specs with 1–8 endpoints
- Variety: methods, params, request bodies, response shapes, auth modes
- Mix of complete and intentionally incomplete specs (to test missing_info behavior)
- gold must be deterministically derived from generated spec

AGENT LIGHTNING TRAINING HARNESS
Implement train_agent_lightning.py:
- Provide a “mock mode” that uses a deterministic stub LLM so everything runs locally
- Implement agent_run(task) that:
  - runs the LangGraph agent on task.openapi_yaml
  - computes reward using gold
  - returns scalar reward and (call, reward) trace data
- Include placeholders for real model endpoint config

TESTS
Implement tests/test_contract.py:
- Test missing-spec behavior (empty spec)
- Test no-invented-endpoints invariant
- Test JSON schema validation via Pydantic

QUALITY BAR
- Deterministic seeds
- Type hints + docstrings
- Minimal external deps
- README contains: setup, dataset generation, running agent, running training (mock mode), running tests

NOW: Generate the full project as files exactly as specified.