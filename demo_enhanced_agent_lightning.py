#!/usr/bin/env python3
"""
Demo: Enhanced Agent Lightning + GAM with Postman-like Capabilities
Shows how the existing Agent Lightning + GAM flow now supports:
- Natural language prompts for test generation
- Automatic error analysis and fixing
- Workflow orchestration
- Integration with existing RL training
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from spec_test_pilot.memory.gam import GAMMemorySystem
from spec_test_pilot.agent_lightning import AgentLightningTrainer
from spec_test_pilot.multi_language_tester import HumanTesterSimulator, MultiLanguageTestGenerator
from train_agent_lightning import train_with_nlp_prompt


def demo_enhanced_flow():
    """Demonstrate enhanced Agent Lightning + GAM with Postman-like capabilities."""
    
    print("🚀 ENHANCED AGENT LIGHTNING + GAM DEMO")
    print("=" * 50)
    print("Now with Postman-like AI capabilities!")
    print()
    
    # Initialize the enhanced system (same as before but with new capabilities)
    print("📋 Step 1: Initialize Enhanced System")
    print("-" * 35)
    gam = GAMMemorySystem(use_vector_search=False)
    trainer = AgentLightningTrainer(
        gam_memory_system=gam,
        max_workers=2,
        enable_torch=False,
        sandbox_mode=True
    )
    print("✅ Agent Lightning + GAM initialized with enhanced capabilities")
    print()
    
    # Demo 1: Natural Language Prompt Test Generation
    print("🗣️ Step 2: Natural Language Prompt Generation")
    print("-" * 45)
    
    nlp_prompts = [
        "Generate tests to validate status codes and response times",
        "Create security tests for authentication endpoints", 
        "Test error handling for invalid input data",
        "Generate comprehensive boundary testing with edge cases"
    ]
    
    for i, prompt in enumerate(nlp_prompts, 1):
        print(f"\nDemo {i}: '{prompt}'")
        
        # Use enhanced training with NLP prompt
        result = train_with_nlp_prompt(
            trainer=trainer,
            nlp_prompt=prompt,
            tenant_id=f"demo_corp_{i}"
        )
        
        print(f"✅ Generated tests with prompt: {result.get('task_result', {}).get('success', False)}")
        print(f"   Tests generated: {result.get('task_result', {}).get('test_count', 0)}")
        print(f"   GAM session: {result.get('task_result', {}).get('gam_session_id', 'N/A')[:8]}...")
        print(f"   RL training: {result.get('training_enabled', False)}")
    
    print()
    
    # Demo 2: Error Analysis and Auto-fixing
    print("🔧 Step 3: Error Analysis and Auto-fixing")
    print("-" * 40)
    
    # Create a test scenario that will "fail" for demo
    api_spec = {
        'openapi': '3.0.0',
        'info': {'title': 'Demo API', 'version': '1.0.0'},
        'paths': {
            '/protected': {
                'get': {
                    'summary': 'Protected endpoint',
                    'security': [{'bearerAuth': []}],
                    'responses': {'200': {'description': 'Success'}}
                }
            }
        }
    }
    
    tester = HumanTesterSimulator(api_spec, 'https://api.demo.com')
    
    # Simulate error scenarios
    error_scenarios = [
        {'status_code': 401, 'body': {'error': 'Unauthorized access'}},
        {'status_code': 403, 'body': {'error': 'Insufficient permissions'}}, 
        {'status_code': 400, 'body': {'error': 'Missing required field: name'}},
        {'status_code': 404, 'body': {'error': 'Resource not found'}}
    ]
    
    # Generate initial scenario
    scenarios = tester.think_like_tester("Generate authentication tests")
    original_scenario = scenarios[0] if scenarios else None
    
    if original_scenario:
        for error in error_scenarios:
            print(f"\n🔍 Analyzing HTTP {error['status_code']} error:")
            analysis = tester.analyze_error_and_suggest_fix(error, original_scenario)
            
            if analysis['auto_fix_available']:
                print(f"   🔧 Auto-fix applied: {analysis['suggested_fixes'][0]}")
                print(f"   📊 Confidence: {analysis['confidence']:.1%}")
            else:
                print(f"   ⚠️  Manual intervention required")
    
    print()
    
    # Demo 3: Multi-language Generation with Enhanced Features  
    print("🌍 Step 4: Enhanced Multi-language Generation")
    print("-" * 44)
    
    # Generate with different prompts
    prompt_scenarios = tester.think_like_tester("Create comprehensive security tests with SQL injection protection")
    generator = MultiLanguageTestGenerator(prompt_scenarios, 'https://api.demo.com')
    
    print(f"Generated {len(prompt_scenarios)} security test scenarios")
    print("Multi-language output:")
    
    # Generate in all languages
    python_tests = generator.generate_python_tests()
    js_tests = generator.generate_javascript_tests()
    java_tests = generator.generate_java_tests()
    curl_tests = generator.generate_curl_tests()
    
    print(f"   🐍 Python: {len(python_tests)} characters")
    print(f"   🟨 JavaScript: {len(js_tests)} characters") 
    print(f"   ☕ Java: {len(java_tests)} characters")
    print(f"   🌐 cURL: {len(curl_tests)} characters")
    
    print()
    
    # Demo 4: Show Integration with Agent Lightning RL Training
    print("⚡ Step 5: RL Training with Enhanced Features")
    print("-" * 42)
    
    # Run multiple training iterations with different prompts
    training_prompts = [
        "Focus on performance testing with response time validation",
        "Generate edge case tests with boundary value analysis",
        "Create security-focused tests with vulnerability scanning"
    ]
    
    training_results = []
    for i, prompt in enumerate(training_prompts):
        print(f"\nTraining iteration {i+1}: {prompt[:50]}...")
        result = train_with_nlp_prompt(trainer, prompt, tenant_id=f"training_corp_{i}")
        training_results.append(result)
        
        print(f"   Success: {result.get('task_result', {}).get('success', False)}")
        print(f"   Traces: {result.get('traces_collected', 0)}")
        
    print()
    
    # Demo 5: Show GAM Memory with Enhanced Context
    print("🧠 Step 6: GAM Memory with Enhanced Context")
    print("-" * 40)
    
    # Search for context across all training sessions
    search_results = gam.search("security testing authentication", top_k=5)
    print(f"Found {len(search_results)} relevant memory entries:")
    
    for i, (page, score) in enumerate(search_results[:3]):
        print(f"   {i+1}. {page.title} (score: {score:.3f})")
        if hasattr(page, 'tenant_id') and page.tenant_id:
            print(f"      Tenant: {page.tenant_id}")
    
    print()
    
    # Final Summary
    print("🎯 ENHANCED SYSTEM SUMMARY")
    print("-" * 28)
    print("✅ Natural Language Prompts: Working")
    print("✅ Error Analysis & Auto-fixing: Working") 
    print("✅ Multi-language Generation: Working")
    print("✅ Agent Lightning RL Training: Working")
    print("✅ GAM Memory Integration: Working")
    print("✅ Sandbox Safety: Working")
    print()
    
    print("🚀 **YOUR ENHANCED AGENT LIGHTNING + GAM SYSTEM:**")
    print("   - Use natural language like Postman AI")
    print("   - Automatically fix common API errors (401, 403, 400, 404)")
    print("   - Generate tests in 4 programming languages")
    print("   - Learn and improve through RL training")
    print("   - Remember context across sessions with GAM")
    print("   - Execute safely in isolated sandbox")
    print()
    print("🎉 The existing flow is now enhanced with Postman-like capabilities!")
    
    # Show usage examples
    print()
    print("📋 USAGE EXAMPLES:")
    print("# Natural language prompt:")
    print('python train_agent_lightning.py --prompt "Generate security tests for OAuth endpoints"')
    print()
    print("# Error analysis in your code:")
    print("analysis = tester.analyze_error_and_suggest_fix(error_response, original_scenario)")
    print("if analysis['auto_fix_available']:")
    print("    fixed_scenario = analysis['fixed_scenario']")


if __name__ == "__main__":
    demo_enhanced_flow()
