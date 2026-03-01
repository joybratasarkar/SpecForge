# SpecTestPilot: AI-Driven API Test Generation + Agent Lightning RL

SpecTestPilot with **Microsoft Agent Lightning** (arXiv:2508.03680) integration for reinforcement learning and **GAM** (arXiv:2511.18423) for intelligent memory.

## 🚀 Quick Start

```bash
# Install
pip install -r requirements.txt

# Generate tests (standard)
python run_agent.py examples/banking_api.yaml

# Train with RL (Agent Lightning + GAM)
python train_agent_lightning.py --epochs 5 --mock

# Test complete system
./run_complete_flow.sh

# Run tests
python -m pytest tests/ -v
```

## 🏗️ System Architecture Flow

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  SpecTestPilot  │───▶│ Agent Lightning  │───▶│  GAM Memory     │
│  (Your Agent)   │    │ (RL Training)    │    │  (Intelligence) │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│    Sandbox      │    │ Trace Collection │    │ Tenant Scoping  │
│ (Safe Testing)  │    │ (Sidecar Design) │    │ (Multi-tenant)  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 🔄 Complete Training Flow

### **Step 1: Task Submission** 📋
```python
# Task submitted to Agent Lightning server
task = {
    "openapi_spec": "banking_api.yaml",
    "spec_title": "Banking API", 
    "tenant_id": "bank_corp"
}
```

### **Step 2: Sidecar Monitoring** 🔍
```python
# Non-intrusive trace collection starts
monitor.record_trace(task_id, TraceType.STATE, agent_id, initial_state)
monitor.record_trace(task_id, TraceType.ACTION, agent_id, action_data)
```

### **Step 3: Agent Execution** 🤖
```python
# SpecTestPilot runs in sandbox environment
session_id = gam.start_session(tenant_id="bank_corp")
result = sandbox_agent.execute(task)  # Safe execution
lossless_pages, memo = gam.end_session_with_memo(...)
```

### **Step 4: GAM Integration** 📝
```python
# Lossless storage with intelligent memos
memo_content = f"""
Context: {contextual_header}
Decisions: OAuth 2.0 PKCE; Bearer tokens
Full session data: page_id:{lossless_page.id}
"""
```

### **Step 5: RL Processing** ⚡
```python
# Convert traces to RL transitions
transitions = organizer.organize_trajectory(traces, reward, success)
# Each transition: (state_t, action_t, reward_t, state_t+1)
```

### **Step 6: Credit Assignment** 🧠
```python
# Distribute rewards across actions with temporal discount
rewards = credit_assignment.assign_credit(traces, final_reward, success)
# Backward propagation: R_t = r_t + γ * R_{t+1}
```

### **Step 7: Neural Network Training** 🎯
```python
# Update policy based on performance
loss = criterion(predicted_values, target_rewards)
optimizer.step()  # Agent learns and improves
```

### **Step 8: Next Iteration** 🔄
```python
# Improved agent performance for next task
# GAM provides smarter context from previous sessions
# Agent Lightning enables continuous learning
```

## 🧠 Dual AI Architecture

### **GAM Memory System** (arXiv:2511.18423)
- ✅ Lossless session storage + contextual memos
- ✅ Multi-tenant isolation  
- ✅ Deep research: PLAN → SEARCH → INTEGRATE → REFLECT
- ✅ Intelligent chunking + page_id pointers

### **Agent Lightning RL** (arXiv:2508.03680)  
- ✅ Sidecar monitoring with trace collection
- ✅ Credit assignment + hierarchical RL
- ✅ Training-agent disaggregation
- ✅ Zero-code integration with existing agents

### **Sandbox Environment** 🏖️
- ✅ Isolated file system operations
- ✅ Mock LLM responses for safe training
- ✅ Deterministic outputs for reproducible RL
- ✅ Automatic cleanup prevents directory pollution

## 📁 Project Structure

```
spec_test_pilot/
├── graph.py                # Agent orchestration
├── parsers.py             # OpenAPI parsing  
├── schemas.py             # Data structures
├── agent_lightning.py     # Agent Lightning RL framework
└── memory/gam.py          # GAM memory system

train_agent_lightning.py   # RL training script
tests/                     # Test suite
examples/                  # Sample specs
```

## 🎯 RL Training

```bash
# Train with Agent Lightning + GAM
python train_agent_lightning.py \
    --epochs 10 \
    --data data/train.jsonl \
    --mock

# Features:
# - Non-intrusive trace collection
# - Hierarchical credit assignment  
# - GAM session integration
# - Multi-tenant training isolation
```

## 🔧 Standard Usage

```python
from spec_test_pilot.graph import run_agent

result = run_agent({
    "openapi_spec": "path/to/spec.yaml", 
    "output_format": "pytest"
})
```

## ⚡ Agent Lightning Usage

```python
from spec_test_pilot.memory.gam import GAMMemorySystem
from spec_test_pilot.agent_lightning import AgentLightningTrainer

# Initialize
gam = GAMMemorySystem()
trainer = AgentLightningTrainer(gam)

# Train
result = trainer.train_on_task(
    openapi_spec="examples/banking_api.yaml",
    spec_title="Banking API"
)
```

## 📊 API Server

```bash
python api_server.py
# POST to localhost:8000/generate-tests
```
