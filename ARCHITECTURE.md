# SpecTestPilot Architecture Guide

A comprehensive guide to understanding the SpecTestPilot codebase - an RL-trainable agent that converts OpenAPI specs to test case JSON.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [File Structure](#file-structure)
3. [Core Components](#core-components)
   - [Schemas (Pydantic Models)](#1-schemas-pydantic-models)
   - [OpenAPI Parser](#2-openapi-parser)
   - [GAM Memory System](#3-gam-memory-system)
   - [LangGraph State Machine](#4-langgraph-state-machine)
   - [Reward Function](#5-reward-function)
4. [Data Flow](#data-flow)
5. [Training Pipeline](#training-pipeline)
6. [Quick Start](#quick-start)

---

## Project Overview

**SpecTestPilot** takes an OpenAPI specification (YAML/JSON) and generates comprehensive test cases in a strict JSON format. It uses:

- **LangGraph** for orchestrating the agent workflow
- **GAM-style memory** for deep research (plan → search → integrate → reflect)
- **Reinforcement Learning** compatible reward function for training

### Key Guarantees

| Guarantee | Description |
|-----------|-------------|
| **No Hallucination** | Only generates tests for endpoints that exist in the spec |
| **Strict Schema** | Output always matches the Pydantic-validated JSON contract |
| **Missing Spec Handling** | Returns structured "unknown" values when spec is empty/invalid |

---

## File Structure

```
reinforcement-agent/
├── README.md                    # Quick start guide
├── ARCHITECTURE.md              # This file - detailed documentation
├── requirements.txt             # Python dependencies
│
├── spec_test_pilot/             # Main package
│   ├── __init__.py              # Package exports
│   ├── schemas.py               # Pydantic models (JSON contract)
│   ├── openapi_parse.py         # OpenAPI spec parser
│   ├── graph.py                 # LangGraph state machine
│   ├── reward.py                # RL reward function
│   └── memory/
│       ├── __init__.py
│       └── gam.py               # GAM-style memory system
│
├── data/
│   └── generate_dataset.py      # Synthetic dataset generator
│
├── train_agent_lightning.py     # Training harness
├── run_agent.py                 # CLI entry point
│
└── tests/
    └── test_contract.py         # Contract tests
```

---

## Core Components

### 1. Schemas (Pydantic Models)

**File:** `spec_test_pilot/schemas.py`

Defines the strict JSON output contract using Pydantic v2.

#### Output Structure

```json
{
  "spec_summary": {
    "title": "Pet Store API",
    "version": "1.0.0",
    "base_url": "https://api.petstore.com/v1",
    "auth": {
      "type": "bearer",           // none | apiKey | bearer | oauth2 | unknown
      "details": "JWT token"
    },
    "endpoints_detected": [
      {"method": "GET", "path": "/pets", "operation_id": "listPets"}
    ]
  },
  
  "deep_research": {
    "plan": ["Search for REST conventions", "Find auth patterns"],
    "memory_excerpts": [
      {"source": "convention", "excerpt": "Every endpoint needs happy path..."}
    ],
    "reflection": "Found 5 relevant patterns"
  },
  
  "test_suite": [
    {
      "test_id": "T001",
      "name": "GET /pets happy path",
      "endpoint": {"method": "GET", "path": "/pets"},
      "objective": "Verify listing pets returns 200",
      "preconditions": ["Valid auth token"],
      "request": {
        "headers": {"Authorization": "Bearer <token>"},
        "path_params": {},
        "query_params": {"limit": "10"},
        "body": {}
      },
      "assertions": [
        {"type": "status_code", "expected": 200},
        {"type": "schema", "expected": "PetList"}
      ],
      "data_variants": [],
      "notes": ""
    }
  ],
  
  "coverage_checklist": {
    "happy_paths": "true",
    "validation_negative": "true",
    "auth_negative": "true",
    "error_contract": "true",
    "idempotency": "unknown",
    "pagination_filtering": "unknown",
    "rate_limit": "unknown"
  },
  
  "missing_info": []
}
```

#### Key Classes

| Class | Purpose |
|-------|---------|
| `SpecTestPilotOutput` | Root output model with validation |
| `SpecSummary` | Parsed spec metadata |
| `DeepResearch` | GAM research results |
| `TestCase` | Individual test specification |
| `CoverageChecklist` | Test coverage tracking |

#### No-Invented-Endpoints Validator

```python
@model_validator(mode="after")
def validate_no_invented_endpoints(self) -> "SpecTestPilotOutput":
    """Ensure all test endpoints exist in detected endpoints."""
    detected = {(e.method, e.path) for e in self.spec_summary.endpoints_detected}
    for test in self.test_suite:
        test_endpoint = (test.endpoint.method, test.endpoint.path)
        if test_endpoint not in detected:
            raise ValueError(f"Test references non-existent endpoint: {test_endpoint}")
    return self
```

---

### 2. OpenAPI Parser

**File:** `spec_test_pilot/openapi_parse.py`

Parses OpenAPI 3.x and Swagger 2.0 specifications.

#### Key Functions

```python
# Main entry point
parsed_spec = parse_openapi_spec(yaml_or_json_string)

# Access parsed data
parsed_spec.title          # "Pet Store API"
parsed_spec.version        # "1.0.0"
parsed_spec.base_url       # "https://api.petstore.com/v1"
parsed_spec.auth.type      # "bearer"
parsed_spec.endpoints      # List[ParsedEndpoint]
parsed_spec.schemas        # Dict of component schemas
parsed_spec.is_valid       # True if parsing succeeded
```

#### ParsedEndpoint Structure

```python
@dataclass
class ParsedEndpoint:
    method: str              # "GET", "POST", etc.
    path: str                # "/pets/{petId}"
    operation_id: str        # "getPet"
    summary: str             # "Get a pet by ID"
    parameters: List[...]    # Path, query, header params
    request_body: Optional   # For POST/PUT/PATCH
    responses: List[...]     # Expected responses
    security: List[...]      # Security requirements
```

---

### 3. GAM Memory System

**File:** `spec_test_pilot/memory/gam.py`

Implements a GAM-style (Generative Agents Memory) subsystem with:

- **PageStore**: Append-only storage with hybrid search
- **Memorizer**: Creates memos from agent runs
- **Researcher**: Deep research loop (max 2 iterations)

#### PageStore - Hybrid Search

```python
# Uses both BM25 (keyword) and vector (semantic) search
page_store = PageStore(
    embedding_model="all-MiniLM-L6-v2",  # sentence-transformers
    use_vector_search=True
)

# Add pages
page_store.add_page(
    title="REST API Conventions",
    tags=["convention", "rest"],
    content="Every endpoint needs a happy path test...",
    source="convention"  # convention | existing_tests | runbook | validator | memo
)

# Search
results = page_store.hybrid_search("authentication testing", top_k=5)
# Returns: List[(Page, score)]
```

#### Search Methods

| Method | Algorithm | Use Case |
|--------|-----------|----------|
| `search_bm25()` | BM25Okapi | Keyword matching |
| `search_vector()` | FAISS + sentence-transformers | Semantic similarity |
| `hybrid_search()` | Weighted combination | Best of both |

#### Researcher - Deep Research Loop

```
┌─────────────────────────────────────────────────────────┐
│                    RESEARCH LOOP                         │
│                   (max 2 iterations)                     │
│                                                          │
│   ┌──────┐    ┌────────┐    ┌───────────┐    ┌────────┐ │
│   │ PLAN │───▶│ SEARCH │───▶│ INTEGRATE │───▶│REFLECT │ │
│   └──────┘    └────────┘    └───────────┘    └────────┘ │
│       │                                           │      │
│       │           ◀── continue? ──────────────────┘      │
│       │                                                  │
│       └──────────────── done ───────────────────────────▶│
└─────────────────────────────────────────────────────────┘
```

```python
researcher = Researcher(page_store)
result = researcher.research(context={
    "spec_title": "Pet Store API",
    "auth_type": "bearer",
    "endpoints": [...]
})

# Returns ResearchResult:
#   - plan: ["Search for REST conventions", ...]
#   - memory_excerpts: [{"source": "convention", "excerpt": "..."}]
#   - reflection: "Found relevant patterns"
#   - iteration: 2
```

---

### 4. LangGraph State Machine

**File:** `spec_test_pilot/graph.py`

Orchestrates the agent workflow using LangGraph.

#### State Model

```python
class AgentState(TypedDict):
    # Input
    spec_text: str
    
    # Parsing
    parsed_spec: Optional[Dict]
    endpoints: List[Dict]
    parse_errors: List[str]
    
    # Research
    research_plan: List[str]
    retrieved_pages: List[Dict]
    memory_excerpts: List[Dict]
    reflection_count: int
    should_continue_research: bool
    
    # Generation
    draft_output: Optional[Dict]
    validated_output: Optional[Dict]
    missing_info: List[str]
    
    # RL
    reward: float
    intermediate_rewards: Dict[str, float]
```

#### Node Graph

```
                    ┌─────────────┐
                    │ parse_spec  │
                    └──────┬──────┘
                           │
                           ▼
                 ┌──────────────────┐
                 │ detect_endpoints │
                 └────────┬─────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │ deep_research_plan    │◀─────────┐
              └───────────┬───────────┘          │
                          │                      │
                          ▼                      │
              ┌───────────────────────┐          │
              │ deep_research_search  │          │
              └───────────┬───────────┘          │
                          │                      │
                          ▼                      │
              ┌───────────────────────┐          │
              │deep_research_integrate│          │
              └───────────┬───────────┘          │
                          │                      │
                          ▼                      │
              ┌───────────────────────┐   yes    │
              │ deep_research_reflect │──────────┘
              └───────────┬───────────┘
                          │ no (done)
                          ▼
                ┌─────────────────┐
                │ generate_tests  │
                └────────┬────────┘
                         │
                         ▼
            ┌─────────────────────────┐
            │ finalize_and_validate   │
            └─────────────────────────┘
                         │
                         ▼
                       [END]
```

#### Running the Agent

```python
from spec_test_pilot.graph import run_agent

result = run_agent(
    spec_text=openapi_yaml,
    run_id="my-run-001",
    verbose=True
)

# Returns:
# {
#     "output": {...},           # Validated JSON output
#     "reward": 0.85,            # Final reward
#     "intermediate_rewards": {  # Per-node rewards
#         "parse_spec": 0.5,
#         "detect_endpoints": 0.8,
#         ...
#     },
#     "run_id": "my-run-001"
# }
```

---

### 5. Reward Function

**File:** `spec_test_pilot/reward.py`

RL-friendly reward function with hard gates and positive components.

#### Reward Computation

```
                    ┌─────────────────────┐
                    │    HARD GATES       │
                    │  (must all pass)    │
                    └─────────┬───────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
            ▼                 ▼                 ▼
      ┌──────────┐    ┌─────────────┐   ┌──────────────┐
      │Valid JSON│    │  Pydantic   │   │No Invented   │
      │          │    │ Validation  │   │ Endpoints    │
      └────┬─────┘    └──────┬──────┘   └──────┬───────┘
           │                 │                  │
           └─────────────────┴──────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Any gate fails?  │
                    └─────────┬─────────┘
                              │
              ┌───────────────┴───────────────┐
              │ YES                           │ NO
              ▼                               ▼
        Return 0.0                  ┌─────────────────┐
                                    │POSITIVE COMPONENTS│
                                    └─────────┬───────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
          ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
          │Endpoint Coverage│      │Negative Quality │      │  Auth Negative  │
          │     (40%)       │      │     (20%)       │      │     (20%)       │
          └────────┬────────┘      └────────┬────────┘      └────────┬────────┘
                   │                        │                        │
                   └────────────────────────┴────────────────────────┘
                                            │
                                            ▼
                                  ┌─────────────────┐
                                  │Missing Info (20%)│
                                  └────────┬────────┘
                                           │
                                           ▼
                                    Sum & Clip [0,1]
```

#### Hard Gates (Return 0.0 if any fail)

| Gate | Check |
|------|-------|
| Valid JSON | Output is a valid dictionary |
| Pydantic Valid | Passes `SpecTestPilotOutput.model_validate()` |
| No Invented Endpoints | All test endpoints exist in detected endpoints |

#### Positive Components

| Component | Weight | Description |
|-----------|--------|-------------|
| Endpoint Coverage | 40% | Fraction of endpoints with ≥3 tests |
| Negative Quality | 20% | Has missing-field + invalid-type tests |
| Auth Negative | 20% | Has auth-negative tests if auth required |
| Missing Info Quality | 20% | Proper missing_info for incomplete specs |

#### Usage

```python
from spec_test_pilot.reward import compute_reward, compute_reward_with_gold

# Basic reward
reward, breakdown = compute_reward(output_dict, parsed_spec)

# With gold standard comparison
reward, breakdown = compute_reward_with_gold(output_dict, spec_text, gold)

# Breakdown contains:
# - breakdown.valid_json
# - breakdown.pydantic_valid
# - breakdown.no_invented_endpoints
# - breakdown.endpoint_coverage
# - breakdown.negative_quality
# - breakdown.auth_negative
# - breakdown.missing_info_quality
# - breakdown.total_reward
```

---

## Data Flow

```
┌──────────────────┐
│  OpenAPI Spec    │
│  (YAML/JSON)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────────┐
│  openapi_parse   │────▶│   ParsedSpec     │
│                  │     │  - endpoints     │
└──────────────────┘     │  - auth          │
                         │  - schemas       │
                         └────────┬─────────┘
                                  │
         ┌────────────────────────┴────────────────────────┐
         │                                                 │
         ▼                                                 ▼
┌──────────────────┐                            ┌──────────────────┐
│   GAM Memory     │                            │   LangGraph      │
│   Research       │◀──────────────────────────▶│   State Machine  │
│  - plan          │                            │  - parse         │
│  - search        │                            │  - detect        │
│  - integrate     │                            │  - research      │
│  - reflect       │                            │  - generate      │
└──────────────────┘                            │  - validate      │
                                                └────────┬─────────┘
                                                         │
                                                         ▼
                                                ┌──────────────────┐
                                                │  Pydantic        │
                                                │  Validation      │
                                                └────────┬─────────┘
                                                         │
                                                         ▼
                                                ┌──────────────────┐
                                                │  JSON Output     │
                                                │  + Reward        │
                                                └──────────────────┘
```

---

## Training Pipeline

**File:** `train_agent_lightning.py`

### Mock Mode (Local Training)

```bash
# Generate dataset first
python data/generate_dataset.py

# Train with mock LLM (no API keys needed)
python train_agent_lightning.py --mock --epochs 10 --batch-size 32
```

### Training Loop

```
┌─────────────────────────────────────────────────────────────┐
│                     TRAINING LOOP                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  for epoch in epochs:                                        │
│      for batch in batches:                                   │
│          for task in batch:                                  │
│              ┌─────────────────────────────────────────┐     │
│              │  1. Run agent on task.openapi_yaml      │     │
│              │  2. Get output JSON                     │     │
│              │  3. Compute reward using task.gold      │     │
│              │  4. Collect (call, reward) trace        │     │
│              └─────────────────────────────────────────┘     │
│          end                                                 │
│          Update metrics                                      │
│      end                                                     │
│      Evaluate on test set                                    │
│      Save checkpoint                                         │
│  end                                                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Dataset Format

```json
{
  "task_id": "train_0001_abc123",
  "openapi_yaml": "openapi: 3.0.3\ninfo:\n  title: ...",
  "gold": {
    "title": "Pet Store API",
    "version": "1.0.0",
    "base_url": "https://api.petstore.com",
    "auth_type": "bearer",
    "endpoints": [
      {"method": "GET", "path": "/pets", "operation_id": "listPets"}
    ],
    "notes": ""
  }
}
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Generate Training Data

```bash
python data/generate_dataset.py
# Creates data/train.jsonl (500 rows) and data/test.jsonl (100 rows)
```

### 3. Run Agent on a Spec

```bash
# From file
python run_agent.py --spec path/to/openapi.yaml --verbose

# From stdin
cat openapi.yaml | python run_agent.py --stdin

# Save output
python run_agent.py --spec api.yaml --output tests.json
```

### 4. Train (Mock Mode)

```bash
python train_agent_lightning.py --mock --epochs 10
```

### 5. Run Tests

```bash
pytest tests/ -v
```

---

## Key Design Decisions

### Why Pydantic?

- **Strict validation** at runtime ensures output always matches contract
- **No-invented-endpoints** check is a model validator
- **Type hints** provide IDE support and documentation

### Why GAM-style Memory?

- **Hybrid search** (BM25 + vector) finds both exact and semantic matches
- **Iterative refinement** with reflect loop improves research quality
- **Append-only pages** allow learning from past runs

### Why LangGraph?

- **Explicit state** makes debugging and testing easier
- **Conditional edges** enable the research loop
- **Intermediate rewards** can be computed per node

### Why Hard Gates in Reward?

- **Prevents reward hacking** - can't get partial credit for invalid output
- **Enforces invariants** - no invented endpoints is non-negotiable
- **Clear signal** - 0.0 means "fundamentally wrong"

---

## Troubleshooting

### "No module named 'pydantic'"

```bash
pip install -r requirements.txt
```

### "Training data not found"

```bash
python data/generate_dataset.py
```

### Vector search not working

```bash
# Install optional dependencies
pip install sentence-transformers faiss-cpu
```

If still failing, the system falls back to BM25-only search automatically.

---

## Further Reading

- [LangGraph Documentation](https://python.langchain.com/docs/langgraph)
- [Pydantic v2 Documentation](https://docs.pydantic.dev/)
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
- [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
- [Sentence Transformers](https://www.sbert.net/)
