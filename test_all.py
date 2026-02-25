#!/usr/bin/env python3
"""
Comprehensive test script for SpecTestPilot.

Run this to test all components of the system.
"""

import json
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()


def print_header(title: str):
    """Print a section header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_result(name: str, passed: bool, details: str = ""):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {name}")
    if details:
        print(f"       {details}")


def test_imports():
    """Test that all modules can be imported."""
    print_header("TEST 1: Module Imports")
    
    tests = [
        ("schemas", "from spec_test_pilot.schemas import SpecTestPilotOutput"),
        ("openapi_parse", "from spec_test_pilot.openapi_parse import parse_openapi_spec"),
        ("memory/gam", "from spec_test_pilot.memory.gam import GAMMemorySystem"),
        ("graph", "from spec_test_pilot.graph import run_agent"),
        ("reward", "from spec_test_pilot.reward import compute_reward"),
    ]
    
    all_passed = True
    for name, import_stmt in tests:
        try:
            exec(import_stmt)
            print_result(f"Import {name}", True)
        except Exception as e:
            print_result(f"Import {name}", False, str(e))
            all_passed = False
    
    return all_passed


def test_openapi_parsing():
    """Test OpenAPI spec parsing."""
    print_header("TEST 2: OpenAPI Parsing")
    
    from spec_test_pilot.openapi_parse import parse_openapi_spec
    
    # Test with sample spec
    sample_spec = Path("sample_api.yaml").read_text()
    parsed = parse_openapi_spec(sample_spec)
    
    tests = [
        ("Title parsed", parsed.title == "Pet Store API", f"Got: {parsed.title}"),
        ("Version parsed", parsed.version == "1.0.0", f"Got: {parsed.version}"),
        ("Base URL parsed", "petstore" in parsed.base_url, f"Got: {parsed.base_url}"),
        ("Auth detected", parsed.auth.type == "bearer", f"Got: {parsed.auth.type}"),
        ("Endpoints found", len(parsed.endpoints) >= 6, f"Found: {len(parsed.endpoints)} endpoints"),
    ]
    
    all_passed = True
    for name, passed, details in tests:
        print_result(name, passed, details)
        if not passed:
            all_passed = False
    
    # Print detected endpoints
    print("\n  Detected endpoints:")
    for ep in parsed.endpoints:
        print(f"    - {ep.method} {ep.path} ({ep.operation_id})")
    
    return all_passed


def test_empty_spec_handling():
    """Test empty/invalid spec handling."""
    print_header("TEST 3: Empty Spec Handling")
    
    from spec_test_pilot.graph import run_agent
    
    # Test empty spec
    result = run_agent("")
    output = result["output"]
    
    tests = [
        ("Empty endpoints", len(output["spec_summary"]["endpoints_detected"]) == 0, ""),
        ("Empty test_suite", len(output["test_suite"]) == 0, ""),
        ("Has missing_info", len(output["missing_info"]) >= 3, f"Got {len(output['missing_info'])} items"),
        ("Coverage unknown", output["coverage_checklist"]["happy_paths"] == "unknown", ""),
    ]
    
    all_passed = True
    for name, passed, details in tests:
        print_result(name, passed, details)
        if not passed:
            all_passed = False
    
    print("\n  Missing info items:")
    for item in output["missing_info"]:
        print(f"    - {item}")
    
    return all_passed


def test_gam_memory():
    """Test GAM memory system."""
    print_header("TEST 4: GAM Memory System")
    
    from spec_test_pilot.memory.gam import GAMMemorySystem
    
    # Create memory system (without vector search for speed)
    memory = GAMMemorySystem(use_vector_search=False)
    
    # Test research
    context = {
        "spec_title": "Pet Store API",
        "auth_type": "bearer",
        "endpoints": [
            {"method": "GET", "path": "/pets"},
            {"method": "POST", "path": "/pets"}
        ]
    }
    
    result = memory.research(context)
    
    tests = [
        ("Has plan", len(result.plan) > 0, f"Plan steps: {len(result.plan)}"),
        ("Has excerpts", len(result.memory_excerpts) > 0, f"Excerpts: {len(result.memory_excerpts)}"),
        ("Has reflection", len(result.reflection) > 0, ""),
        ("Max 2 iterations", result.iteration <= 2, f"Iterations: {result.iteration}"),
    ]
    
    all_passed = True
    for name, passed, details in tests:
        print_result(name, passed, details)
        if not passed:
            all_passed = False
    
    print("\n  Research plan:")
    for step in result.plan:
        print(f"    - {step}")
    
    return all_passed


def test_full_agent_run():
    """Test full agent run on sample spec."""
    print_header("TEST 5: Full Agent Run")
    
    from spec_test_pilot.graph import run_agent
    
    # Load sample spec
    sample_spec = Path("sample_api.yaml").read_text()
    
    # Run agent
    result = run_agent(sample_spec, verbose=False)
    output = result["output"]
    reward = result["reward"]
    
    # Basic checks
    endpoints = output["spec_summary"]["endpoints_detected"]
    tests_generated = output["test_suite"]
    
    tests = [
        ("Endpoints detected", len(endpoints) >= 6, f"Found: {len(endpoints)}"),
        ("Tests generated", len(tests_generated) >= 10, f"Generated: {len(tests_generated)}"),
        ("Reward > 0", reward > 0, f"Reward: {reward:.4f}"),
        ("Valid JSON", isinstance(output, dict), ""),
    ]
    
    all_passed = True
    for name, passed, details in tests:
        print_result(name, passed, details)
        if not passed:
            all_passed = False
    
    # Check no invented endpoints
    detected_set = {(e["method"], e["path"]) for e in endpoints}
    test_endpoints = {(t["endpoint"]["method"], t["endpoint"]["path"]) for t in tests_generated}
    invented = test_endpoints - detected_set
    
    print_result("No invented endpoints", len(invented) == 0, 
                 f"Invented: {invented}" if invented else "")
    if invented:
        all_passed = False
    
    # Print summary
    print(f"\n  Summary:")
    print(f"    Spec: {output['spec_summary']['title']}")
    print(f"    Endpoints: {len(endpoints)}")
    print(f"    Tests: {len(tests_generated)}")
    print(f"    Reward: {reward:.4f}")
    
    print(f"\n  Coverage checklist:")
    for key, value in output["coverage_checklist"].items():
        print(f"    {key}: {value}")
    
    return all_passed


def test_reward_function():
    """Test reward function."""
    print_header("TEST 6: Reward Function")
    
    from spec_test_pilot.graph import run_agent
    from spec_test_pilot.openapi_parse import parse_openapi_spec
    from spec_test_pilot.reward import compute_reward
    
    # Load sample spec
    sample_spec = Path("sample_api.yaml").read_text()
    parsed = parse_openapi_spec(sample_spec)
    
    # Run agent
    result = run_agent(sample_spec)
    output = result["output"]
    
    # Compute reward
    reward, breakdown = compute_reward(output, parsed)
    
    tests = [
        ("Valid JSON gate", breakdown.valid_json, ""),
        ("Pydantic valid gate", breakdown.pydantic_valid, ""),
        ("No invented endpoints gate", breakdown.no_invented_endpoints, ""),
        ("Endpoint coverage > 0", breakdown.endpoint_coverage > 0, f"{breakdown.endpoint_coverage:.2f}"),
        ("Total reward > 0", breakdown.total_reward > 0, f"{breakdown.total_reward:.4f}"),
    ]
    
    all_passed = True
    for name, passed, details in tests:
        print_result(name, passed, details)
        if not passed:
            all_passed = False
    
    print(f"\n  Reward breakdown:")
    print(f"    Endpoint coverage: {breakdown.endpoint_coverage:.4f}")
    print(f"    Negative quality: {breakdown.negative_quality:.4f}")
    print(f"    Auth negative: {breakdown.auth_negative:.4f}")
    print(f"    Missing info quality: {breakdown.missing_info_quality:.4f}")
    print(f"    Total reward: {breakdown.total_reward:.4f}")
    
    return all_passed


def test_pydantic_validation():
    """Test Pydantic schema validation."""
    print_header("TEST 7: Pydantic Validation")
    
    from pydantic import ValidationError
    from spec_test_pilot.schemas import (
        SpecTestPilotOutput, TestCase, EndpointInfo, 
        TestEndpoint, Assertion
    )
    
    all_passed = True
    
    # Test valid test ID
    try:
        test = TestCase(
            test_id="T001",
            name="GET /pets happy path",
            endpoint=TestEndpoint(method="GET", path="/pets"),
            objective="Test listing pets",
            assertions=[Assertion(type="status_code", expected=200)]
        )
        print_result("Valid test_id T001", True, "")
    except ValidationError as e:
        print_result("Valid test_id T001", False, str(e))
        all_passed = False
    
    # Test invalid test ID
    try:
        test = TestCase(
            test_id="invalid",
            name="Test",
            endpoint=TestEndpoint(method="GET", path="/test"),
            objective="Test",
            assertions=[Assertion(type="status_code", expected=200)]
        )
        print_result("Invalid test_id rejected", False, "Should have raised error")
        all_passed = False
    except ValidationError:
        print_result("Invalid test_id rejected", True, "")
    
    # Test invalid HTTP method
    try:
        endpoint = EndpointInfo(method="INVALID", path="/test")
        print_result("Invalid method rejected", False, "Should have raised error")
        all_passed = False
    except ValidationError:
        print_result("Invalid method rejected", True, "")
    
    # Test valid methods
    for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
        try:
            endpoint = EndpointInfo(method=method, path="/test")
            print_result(f"Valid method {method}", True, "")
        except ValidationError as e:
            print_result(f"Valid method {method}", False, str(e))
            all_passed = False
    
    return all_passed


def test_output_json():
    """Test that output is valid JSON."""
    print_header("TEST 8: JSON Output")
    
    from spec_test_pilot.graph import run_agent
    import json
    
    sample_spec = Path("sample_api.yaml").read_text()
    result = run_agent(sample_spec)
    output = result["output"]
    
    # Test JSON serialization
    try:
        json_str = json.dumps(output, indent=2)
        parsed_back = json.loads(json_str)
        print_result("JSON serializable", True, f"{len(json_str)} bytes")
        
        # Verify round-trip
        if parsed_back == output:
            print_result("JSON round-trip", True, "")
        else:
            print_result("JSON round-trip", False, "Data changed after round-trip")
            return False
            
    except Exception as e:
        print_result("JSON serializable", False, str(e))
        return False
    
    # Save output to file
    output_path = Path("test_output.json")
    output_path.write_text(json_str)
    print(f"\n  Output saved to: {output_path}")
    
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  SPECTESTPILOT - COMPREHENSIVE TEST SUITE")
    print("=" * 60)
    
    results = []
    
    # Run all tests
    results.append(("Module Imports", test_imports()))
    results.append(("OpenAPI Parsing", test_openapi_parsing()))
    results.append(("Empty Spec Handling", test_empty_spec_handling()))
    results.append(("GAM Memory System", test_gam_memory()))
    results.append(("Full Agent Run", test_full_agent_run()))
    results.append(("Reward Function", test_reward_function()))
    results.append(("Pydantic Validation", test_pydantic_validation()))
    results.append(("JSON Output", test_output_json()))
    
    # Summary
    print_header("TEST SUMMARY")
    
    passed = sum(1 for _, p in results if p)
    total = len(results)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"  {status} {name}")
    
    print(f"\n  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n  🎉 All tests passed!")
        return 0
    else:
        print(f"\n  ⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
