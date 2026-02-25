# Quick Reference Card

## 🚀 **Essential Commands**

### **Setup (One Time)**
```bash
git clone https://github.com/joybratasarkar/spec-test-pilot-.git
cd spec-test-pilot-
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### **Basic Usage**
```bash
# Generate API tests
python run_agent.py --spec sample_api.yaml --verbose

# Run all tests
./run_tests.sh

# Test GAM memory
python gam_implementation.py

# Test Agent Lightning
python final_agent_lightning_test.py

# Full system demo
python spectestpilot_with_gam.py
```

---

## 🎯 **Core Components**

| Component | Command | Purpose |
|-----------|---------|---------|
| **SpecTestPilot** | `python run_agent.py --spec api.yaml` | Generate API test cases |
| **Agent Lightning** | `python train_agent_lightning_real.py --algorithm ppo` | RL training |
| **GAM Memory** | `python gam_implementation.py` | Persistent memory system |
| **Full Integration** | `python spectestpilot_with_gam.py` | All components together |

---

## 📊 **Expected Results**

- **Tests Generated**: 15-25 per API
- **Quality Score**: 0.5-0.8 (Good to Very Good)
- **Execution Time**: 20-40 seconds
- **All Tests Pass**: 31/31 ✅

---

## 🔧 **Training Options**

```bash
# Educational (Free)
python train_agent_lightning.py --mock --epochs 5

# Production (Costs $)
python train_agent_lightning_real.py --algorithm ppo --epochs 10
```

---

## 🧠 **Memory Queries**

```python
from gam_implementation import GeneralAgenticMemory
gam = GeneralAgenticMemory()
result = gam.query("API testing patterns")
print(f"Found {len(result.pages)} pages, confidence: {result.confidence_score:.3f}")
```

---

## 🚨 **Troubleshooting**

| Issue | Solution |
|-------|----------|
| Import errors | `source venv/bin/activate && pip install -r requirements.txt` |
| Agent Lightning missing | `pip install agentlightning` |
| OpenAI key missing | `export OPENAI_API_KEY=your_key` |
| Low quality scores | Check API spec is well-formed |

---

## ✅ **Success Indicators**

- ✅ 31/31 tests passing
- ✅ Quality scores > 0.5
- ✅ GAM confidence > 0.8
- ✅ No import errors
- ✅ Consistent performance
