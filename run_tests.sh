#!/bin/bash
# SpecTestPilot - Complete Test Suite
# Run: ./run_tests.sh

cd "$(dirname "$0")"
source venv/bin/activate

echo "=============================================="
echo "  SpecTestPilot - Running All Tests"
echo "=============================================="

echo ""
echo ">>> Running comprehensive tests..."
python3 test_all.py

echo ""
echo ">>> Running pytest..."
pytest tests/ -v --tb=short

echo ""
echo ">>> Running agent on sample spec..."
python3 run_agent.py --spec sample_api.yaml --verbose

echo ""
echo "=============================================="
echo "  All tests complete!"
echo "=============================================="
