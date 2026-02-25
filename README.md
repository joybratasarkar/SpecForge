# SpecTestPilot

An RL-trainable agent that automatically generates comprehensive API test cases from OpenAPI specifications using LangGraph and GAM-style deep-research memory.

## ✨ Features

- **🎯 No Hallucination**: Only generates tests for endpoints that exist in the spec
- **📋 Strict JSON Contract**: Pydantic-validated output with guaranteed schema compliance
- **🧠 GAM-Style Memory**: Deep research loop with BM25 + vector search (plan → search → integrate → reflect)
- **🔄 LangGraph Orchestration**: 8-node state machine for reliable workflow
- **🎓 RL-Friendly**: Deterministic reward function with hard gates and positive components
- **🚀 Mock Mode Training**: Train locally without API keys using deterministic stub LLM
- **📊 Synthetic Dataset**: Built-in generator for 500+ training examples

## 🏗️ Architecture

- **Schemas**: Pydantic v2 models for strict validation
- **Parser**: OpenAPI 3.x + Swagger 2.0 support
- **Memory**: rank-bm25 + sentence-transformers + FAISS
- **Agent**: LangGraph state machine with conditional loops
- **Training**: Agent Lightning harness with mock/real modes

## 🚀 Quick Start

```bash
# Install
pip install -r requirements.txt

# Generate dataset
python data/generate_dataset.py

# Run agent
python run_agent.py --spec api.yaml --verbose

# Train (mock mode)
python train_agent_lightning.py --mock --epochs 10

# Test
./run_tests.sh