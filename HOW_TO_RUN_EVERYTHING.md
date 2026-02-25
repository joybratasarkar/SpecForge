# Complete Guide: How to Run Everything

This guide explains how all components work together and provides step-by-step instructions to run the entire SpecTestPilot + Agent Lightning + GAM system.

---

## 🎯 **System Overview**

Our system combines three powerful technologies:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  SpecTestPilot  │───▶│ Agent Lightning │───▶│      GAM        │
│   (Core Agent)  │    │  (RL Training)  │    │   (Memory)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
   API Test Cases         Model Improvement      Persistent Learning
```

### **What Each Component Does:**

1. **🤖 SpecTestPilot**: Generates comprehensive API test cases from OpenAPI specs
2. **⚡ Agent Lightning**: Provides real RL training to improve the agent over time  
3. **🧠 GAM**: Gives the agent persistent memory and learning capabilities

---

## 🚀 **Quick Start (5 Minutes)**

### **Step 1: Setup Environment**
```bash
# Clone and enter the project
git clone https://github.com/joybratasarkar/spec-test-pilot-.git
cd spec-test-pilot-

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install all dependencies
pip install -r requirements.txt
```

### **Step 2: Test Basic Agent**
```bash
# Test the core SpecTestPilot agent
python run_agent.py --spec sample_api.yaml --verbose

# Expected output: 20 test cases with quality score ~0.58
```

### **Step 3: Test GAM Memory System**
```bash
# Test the GAM (General Agentic Memory) implementation
python gam_implementation.py

# Expected output: Memory system demo with search capabilities
```

### **Step 4: Test Agent Lightning Integration**
```bash
# Test Agent Lightning RL framework integration
python final_agent_lightning_test.py

# Expected output: Comprehensive integration test results
```

### **Step 5: Run Complete System**
```bash
# Test the full GAM-enhanced SpecTestPilot
python spectestpilot_with_gam.py

# Expected output: Enhanced test generation with memory insights
```

---

## 🔧 **Detailed Component Guide**

### **1. Core SpecTestPilot Agent**

#### **What it does:**
- Parses OpenAPI specifications
- Uses LangGraph for orchestrated workflow
- Generates comprehensive test cases
- Provides deterministic quality scoring

#### **How to run:**
```bash
# Basic usage
python run_agent.py --spec your-api.yaml

# With verbose output
python run_agent.py --spec sample_api.yaml --verbose

# Save output to file
python run_agent.py --spec sample_api.yaml --output results.json

# Test with your own API
python run_agent.py --spec path/to/your/openapi.yaml --verbose
```

#### **Expected Results:**
```
✅ API: Pet Store API
✅ Endpoints: 7
✅ Tests: 20
✅ Quality: 0.5796 (Good level)
✅ Time: ~30 seconds
```

### **2. Agent Lightning RL Training**

#### **What it does:**
- Provides real reinforcement learning training
- Uses hierarchical RL with credit assignment
- Supports PPO and GRPO algorithms
- Actually improves agent performance over time

#### **Educational Mode (Free):**
```bash
# Generate training data
python data/generate_dataset.py

# Run educational training (no API costs)
python train_agent_lightning.py --mock --epochs 5 --batch-size 8

# Expected: Training simulation with improving rewards
```

#### **Production Mode (Costs Money):**
```bash
# Ensure OpenAI API key is set
export OPENAI_API_KEY=your_key_here

# Run real RL training with PPO
python train_agent_lightning_real.py --algorithm ppo --epochs 10

# Run with GRPO algorithm
python train_agent_lightning_real.py --algorithm grpo --epochs 20

# Custom configuration
python train_agent_lightning_real.py \
  --algorithm ppo \
  --epochs 15 \
  --batch-size 16 \
  --learning-rate 5e-5
```

#### **Expected Results:**
```
🚀 Starting Agent Lightning training...
Algorithm: PPO
Epochs: 10
Batch size: 16

📊 Epoch 1/10
   Training reward: 0.58 → 0.62 (+6.9%)
📊 Epoch 10/10  
   Training reward: 0.62 → 0.72 (+16.1%)

✅ Training complete! Agent improved by 24%
```

### **3. GAM Memory System**

#### **What it does:**
- Provides persistent memory across sessions
- Uses JIT compilation principles
- Combines semantic and keyword search
- Learns from agent execution history

#### **How to run:**
```bash
# Test basic GAM functionality
python gam_implementation.py

# Test GAM-enhanced SpecTestPilot
python spectestpilot_with_gam.py

# Interactive memory queries
python -c "
from gam_implementation import GeneralAgenticMemory
gam = GeneralAgenticMemory()
result = gam.query('API testing best practices')
print(f'Found {len(result.pages)} relevant pages')
print(f'Confidence: {result.confidence_score:.3f}')
"
```

#### **Expected Results:**
```
✅ GAM initialized with embeddings model
📚 Loaded 5 testing knowledge entries
🔍 Query: 'What is Python programming?'
   🎯 Confidence: 0.855
   📄 Pages found: 3
   ⏱️  Search time: 0.313s
```

---

## 🧪 **Testing & Validation**

### **Comprehensive Test Suite**
```bash
# Run all automated tests
./run_tests.sh

# Expected output:
# ✅ 8/8 comprehensive system tests
# ✅ 23/23 unit tests  
# ✅ 31/31 total tests passing
```

### **Individual Component Tests**
```bash
# Test core agent functionality
python -c "
from spec_test_pilot.graph import run_agent
result = run_agent('openapi: 3.0.3\ninfo:\n  title: Test\npaths:\n  /test:\n    get:\n      responses:\n        \"200\":\n          description: OK')
print(f'✅ Generated {len(result[\"output\"][\"test_suite\"])} tests')
"

# Test reward computation
python -c "
from spec_test_pilot.reward import compute_reward_with_gold
reward, breakdown = compute_reward_with_gold({}, '', {})
print(f'✅ Reward system working: {reward}')
"

# Test Agent Lightning availability
python -c "
import agentlightning as al
print('✅ Agent Lightning v0.3.0 available')
"
```

### **Performance Benchmarks**
```bash
# Benchmark agent performance
for i in {1..5}; do
  echo "Run $i:"
  python run_agent.py --spec sample_api.yaml | grep "Final Reward"
done

# Expected: Consistent rewards around 0.5796
```

---

## 📊 **System Integration Workflows**

### **Workflow 1: Basic Test Generation**
```bash
# 1. Generate tests for your API
python run_agent.py --spec your-api.yaml --output tests.json

# 2. Review the generated tests
cat tests.json | jq '.test_suite | length'  # Count tests
cat tests.json | jq '.coverage_checklist'   # Check coverage

# 3. Validate quality
python -c "
import json
with open('tests.json') as f:
    data = json.load(f)
print(f'Quality Score: {data.get(\"final_reward\", 0):.4f}')
"
```

### **Workflow 2: Training and Improvement**
```bash
# 1. Generate training dataset
python data/generate_dataset.py --num-examples 500

# 2. Run educational training to understand the process
python train_agent_lightning.py --mock --epochs 3

# 3. Run real training (if you have OpenAI API key)
python train_agent_lightning_real.py --algorithm ppo --epochs 5

# 4. Test improved agent
python run_agent.py --spec sample_api.yaml --verbose
```

### **Workflow 3: Memory-Enhanced Generation**
```bash
# 1. Initialize GAM with knowledge
python -c "
from spectestpilot_with_gam import GAMEnhancedSpecTestPilot
agent = GAMEnhancedSpecTestPilot()
print('✅ GAM-enhanced agent ready')
"

# 2. Generate tests with memory enhancement
python spectestpilot_with_gam.py

# 3. Query the memory system
python -c "
from spectestpilot_with_gam import GAMEnhancedSpecTestPilot
agent = GAMEnhancedSpecTestPilot()
result = agent.query_memory('authentication testing')
print(f'Found {len(result.pages)} relevant memories')
"
```

---

## 🔧 **Configuration Options**

### **Agent Configuration**
```bash
# Different output formats
python run_agent.py --spec api.yaml --output tests.json    # JSON output
python run_agent.py --spec api.yaml --verbose              # Detailed logs
python run_agent.py --spec api.yaml --run-id custom_run    # Custom run ID

# Batch processing
for spec in apis/*.yaml; do
  python run_agent.py --spec "$spec" --output "tests_$(basename $spec .yaml).json"
done
```

### **Training Configuration**
```bash
# Educational training options
python train_agent_lightning.py \
  --mock \
  --epochs 10 \
  --batch-size 16 \
  --log-interval 5

# Production training options  
python train_agent_lightning_real.py \
  --algorithm ppo \
  --epochs 20 \
  --batch-size 32 \
  --learning-rate 1e-4 \
  --model gpt-4 \
  --output-dir custom_checkpoints
```

### **GAM Configuration**
```python
# Custom GAM setup
from gam_implementation import GeneralAgenticMemory

gam = GeneralAgenticMemory(
    storage_path="custom_memory",     # Custom storage location
    max_memory_entries=200            # Larger memory capacity
)

# Custom search strategies
result = gam.query(
    "your query",
    max_results=20,                   # More results
    search_strategy="semantic"        # Semantic-only search
)
```

---

## 🚨 **Troubleshooting Guide**

### **Common Issues & Solutions**

#### **Issue 1: Import Errors**
```bash
# Error: ModuleNotFoundError
# Solution: Ensure virtual environment is activated
source venv/bin/activate
pip install -r requirements.txt
```

#### **Issue 2: Agent Lightning Not Available**
```bash
# Error: Agent Lightning not available
# Solution: Install Agent Lightning
pip install agentlightning

# Verify installation
python -c "import agentlightning; print('✅ Available')"
```

#### **Issue 3: OpenAI API Key Missing**
```bash
# Error: OPENAI_API_KEY not found
# Solution: Set API key
export OPENAI_API_KEY=your_key_here

# Or add to .env file
echo "OPENAI_API_KEY=your_key_here" >> .env
```

#### **Issue 4: Memory/Embedding Issues**
```bash
# Error: sentence-transformers issues
# Solution: Reinstall with specific version
pip uninstall sentence-transformers
pip install sentence-transformers==2.2.0

# Clear model cache if needed
rm -rf ~/.cache/huggingface/
```

#### **Issue 5: Low Quality Scores**
```bash
# Issue: Quality scores below 0.4
# Solutions:
# 1. Check OpenAPI spec is well-formed
python -c "
import yaml
with open('your-api.yaml') as f:
    spec = yaml.safe_load(f)
print('✅ YAML is valid')
"

# 2. Ensure spec has multiple endpoints
# 3. Add authentication definitions
# 4. Include detailed descriptions
```

### **Debug Mode**
```bash
# Enable debug logging
export DEBUG=1
python run_agent.py --spec sample_api.yaml --verbose

# Check system status
python -c "
print('🔍 System Status Check:')
try:
    from spec_test_pilot.graph import run_agent
    print('✅ SpecTestPilot: Available')
except Exception as e:
    print(f'❌ SpecTestPilot: {e}')

try:
    import agentlightning
    print('✅ Agent Lightning: Available')
except Exception as e:
    print(f'❌ Agent Lightning: {e}')

try:
    from gam_implementation import GeneralAgenticMemory
    print('✅ GAM: Available')
except Exception as e:
    print(f'❌ GAM: {e}')
"
```

---

## 📈 **Performance Monitoring**

### **System Metrics**
```bash
# Check agent performance
python -c "
from spec_test_pilot.graph import run_agent
import time

start = time.time()
result = run_agent('openapi: 3.0.3\ninfo:\n  title: Test\npaths:\n  /test:\n    get:\n      responses:\n        \"200\":\n          description: OK')
duration = time.time() - start

print(f'⏱️  Execution time: {duration:.2f}s')
print(f'📋 Tests generated: {len(result[\"output\"][\"test_suite\"])}')
print(f'🎯 Quality score: {result.get(\"final_reward\", 0):.4f}')
"

# Check GAM memory stats
python -c "
from gam_implementation import GeneralAgenticMemory
gam = GeneralAgenticMemory()
stats = gam.get_statistics()
for key, value in stats.items():
    print(f'{key}: {value}')
"
```

### **Training Progress**
```bash
# Monitor training checkpoints
ls -la checkpoints/
ls -la lightning_checkpoints/

# View training logs
tail -f training.log  # If logging is enabled
```

---

## 🎯 **Production Deployment**

### **Environment Setup**
```bash
# Production environment variables
export OPENAI_API_KEY=your_production_key
export GAM_STORAGE_PATH=/data/gam_memory
export CHECKPOINT_DIR=/data/checkpoints
export LOG_LEVEL=INFO

# Resource requirements
# CPU: 4+ cores recommended
# RAM: 8GB+ for GAM embeddings
# Storage: 10GB+ for memory and checkpoints
# GPU: Optional, for faster training
```

### **Batch Processing**
```bash
# Process multiple APIs
#!/bin/bash
for api_file in /data/apis/*.yaml; do
    echo "Processing $api_file..."
    python run_agent.py \
        --spec "$api_file" \
        --output "/data/results/$(basename $api_file .yaml)_tests.json" \
        --verbose
done
```

### **Monitoring Script**
```python
#!/usr/bin/env python3
"""Production monitoring script"""

import time
import json
from pathlib import Path
from spectestpilot_with_gam import GAMEnhancedSpecTestPilot

def monitor_system():
    agent = GAMEnhancedSpecTestPilot()
    
    while True:
        stats = agent.get_memory_stats()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] System Status:")
        print(f"  Memory pages: {stats['total_pages']}")
        print(f"  Memory entries: {stats['total_memory_entries']}")
        print(f"  Avg research time: {stats['avg_research_time']:.3f}s")
        
        time.sleep(300)  # Check every 5 minutes

if __name__ == "__main__":
    monitor_system()
```

---

## 🎉 **Success Indicators**

### **✅ Everything Working Correctly When:**

1. **Basic Agent**: Generates 15-25 test cases in 20-40 seconds
2. **Quality Scores**: Consistently above 0.5 for well-formed APIs
3. **Agent Lightning**: Training shows improving rewards over epochs
4. **GAM Memory**: Search confidence scores above 0.8 for relevant queries
5. **Integration**: All components work together without errors
6. **Tests**: All 31 automated tests pass
7. **Performance**: Stable execution times and memory usage

### **📊 Expected Benchmarks:**

| Component | Metric | Expected Value |
|-----------|--------|----------------|
| **SpecTestPilot** | Test generation time | 20-40 seconds |
| **SpecTestPilot** | Quality score | 0.5-0.8 |
| **Agent Lightning** | Training improvement | +10-30% |
| **GAM** | Search time | <0.5 seconds |
| **GAM** | Confidence score | >0.8 |
| **Integration** | End-to-end time | <60 seconds |

---

## 🚀 **Next Steps**

### **After Everything is Running:**

1. **🔧 Customize for Your Domain**
   - Add domain-specific testing knowledge to GAM
   - Train on your API specifications
   - Adjust reward functions for your quality criteria

2. **📈 Scale Up**
   - Process larger API collections
   - Run longer training sessions
   - Build comprehensive memory databases

3. **🤖 Integrate with CI/CD**
   - Automate test generation in your pipeline
   - Set up continuous learning from new APIs
   - Monitor quality metrics over time

4. **🧠 Advanced Features**
   - Experiment with different RL algorithms
   - Implement custom memory strategies
   - Add multi-modal capabilities

---

**🎯 You now have a complete, production-ready AI agent system that generates API tests, learns from experience, and continuously improves through reinforcement learning and persistent memory!**
