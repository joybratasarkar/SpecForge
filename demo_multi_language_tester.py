#!/usr/bin/env python3
"""
Demo: Multi-Language API Testing Agent
Shows how AI agent thinks like a human tester and generates tests in multiple languages
"""

import os
import json
from pathlib import Path
from spec_test_pilot.multi_language_tester import APITestingSandbox


def main():
    """Demonstrate the multi-language API testing agent."""
    
    print("🤖 AI API TESTING AGENT DEMONSTRATION")
    print("=" * 50)
    print("This agent thinks and acts like a professional API tester!")
    print("It will analyze your API and generate comprehensive tests in multiple languages.")
    print()
    
    # Check if example API exists
    banking_api = Path("examples/banking_api.yaml")
    if not banking_api.exists():
        print("❌ Banking API example not found. Creating a sample API spec...")
        create_sample_banking_api()
    
    print("📋 Step 1: Initialize AI Testing Agent")
    print("-" * 35)
    
    # Initialize the testing agent
    sandbox = APITestingSandbox(
        api_spec_path="examples/banking_api.yaml",
        base_url="https://api.bankingexample.com"
    )
    
    print("✅ AI Agent initialized with Banking API spec")
    print("✅ Sandbox environment created for safe test generation")
    print()
    
    print("🧠 Step 2: AI Agent Analysis")
    print("-" * 28)
    print("The AI agent is now thinking like a human tester...")
    print("- Analyzing API endpoints")
    print("- Identifying test scenarios")
    print("- Planning comprehensive test coverage")
    print()
    
    # Run the full test suite generation
    results = sandbox.run_full_test_suite()
    
    print("\n🎯 Step 3: Test Generation Results")
    print("-" * 33)
    
    print(f"📊 **ANALYSIS COMPLETE**")
    print(f"   - API Endpoints Analyzed: {results['total_endpoints']}")
    print(f"   - Test Scenarios Generated: {results['scenarios_generated']}")
    print(f"   - Sandbox Directory: {results['sandbox_directory']}")
    print()
    
    print("📝 **TEST BREAKDOWN**")
    for test_type, count in results['test_breakdown'].items():
        test_name = test_type.replace('_', ' ').title()
        print(f"   - {test_name}: {count} tests")
    print()
    
    print("🌍 **MULTI-LANGUAGE SUPPORT**")
    for language, file_path in results['test_files'].items():
        print(f"   - {language.title()}: {Path(file_path).name}")
    print()
    
    print("🔍 Step 4: Examining Generated Tests")
    print("-" * 35)
    
    # Show samples from each language
    show_test_samples(results)
    
    print("\n📚 Step 5: Usage Instructions")
    print("-" * 29)
    
    show_usage_instructions(results['sandbox_directory'])
    
    print("\n🎉 Step 6: Demo Complete!")
    print("-" * 23)
    print("Your AI API Testing Agent has successfully:")
    print("✅ Analyzed your API like a professional tester")
    print("✅ Generated comprehensive test scenarios")  
    print("✅ Created tests in multiple programming languages")
    print("✅ Provided ready-to-use test suites")
    print("✅ Included documentation and setup instructions")
    print()
    
    # Ask if user wants to keep files
    response = input("Keep generated test files? (y/N): ").lower().strip()
    if response != 'y':
        sandbox.cleanup()
        print("🧹 Sandbox cleaned up")
    else:
        print(f"📁 Test files preserved in: {results['sandbox_directory']}")
    
    print("✅ Demo complete!")


def create_sample_banking_api():
    """Create a sample banking API for demonstration."""
    
    banking_api_spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Banking API",
            "version": "1.0.0",
            "description": "Comprehensive banking API for demonstration"
        },
        "servers": [
            {"url": "https://api.bankingexample.com/v1"}
        ],
        "security": [
            {"bearerAuth": []}
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT"
                }
            }
        },
        "paths": {
            "/accounts": {
                "get": {
                    "summary": "List user accounts",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer"},
                            "description": "Number of accounts to return"
                        }
                    ],
                    "responses": {
                        "200": {"description": "List of accounts"},
                        "401": {"description": "Unauthorized"}
                    }
                },
                "post": {
                    "summary": "Create new account",
                    "security": [{"bearerAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["account_type", "initial_balance"],
                                    "properties": {
                                        "account_type": {"type": "string"},
                                        "initial_balance": {"type": "number"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Account created"},
                        "400": {"description": "Invalid input"},
                        "401": {"description": "Unauthorized"}
                    }
                }
            },
            "/accounts/{accountId}/transactions": {
                "get": {
                    "summary": "Get account transactions",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {
                            "name": "accountId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"}
                        },
                        {
                            "name": "start_date",
                            "in": "query",
                            "schema": {"type": "string", "format": "date"}
                        }
                    ],
                    "responses": {
                        "200": {"description": "Transaction list"},
                        "404": {"description": "Account not found"},
                        "401": {"description": "Unauthorized"}
                    }
                }
            },
            "/transfer": {
                "post": {
                    "summary": "Transfer money between accounts",
                    "security": [{"bearerAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["from_account", "to_account", "amount"],
                                    "properties": {
                                        "from_account": {"type": "string"},
                                        "to_account": {"type": "string"},
                                        "amount": {"type": "number"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Transfer successful"},
                        "400": {"description": "Invalid transfer"},
                        "401": {"description": "Unauthorized"},
                        "403": {"description": "Insufficient funds"}
                    }
                }
            }
        }
    }
    
    os.makedirs("examples", exist_ok=True)
    with open("examples/banking_api.yaml", 'w') as f:
        import yaml
        yaml.dump(banking_api_spec, f, default_flow_style=False)


def show_test_samples(results: dict):
    """Show sample tests from each language."""
    
    sandbox_dir = Path(results['sandbox_directory'])
    
    print("🐍 **Python Test Sample:**")
    python_file = sandbox_dir / "test_api.py"
    if python_file.exists():
        with open(python_file, 'r') as f:
            lines = f.readlines()
            # Show first test method
            in_method = False
            method_lines = []
            for line in lines:
                if 'def test_' in line and not in_method:
                    in_method = True
                    method_lines.append(line)
                elif in_method:
                    if line.strip() and not line.startswith('    ') and not line.startswith('\t'):
                        break
                    method_lines.append(line)
                    if len(method_lines) > 15:  # Limit output
                        method_lines.append("        # ... more assertions ...\n")
                        break
            
            for line in method_lines:
                print(f"   {line.rstrip()}")
    print()
    
    print("🟨 **JavaScript Test Sample:**") 
    js_file = sandbox_dir / "test_api.test.js"
    if js_file.exists():
        with open(js_file, 'r') as f:
            lines = f.readlines()
            # Show first few lines
            for i, line in enumerate(lines[4:19]):  # Skip header, show test
                print(f"   {line.rstrip()}")
    print()
    
    print("🌐 **cURL Test Sample:**")
    curl_file = sandbox_dir / "test_api.sh"
    if curl_file.exists():
        with open(curl_file, 'r') as f:
            lines = f.readlines()
            # Show first curl command
            for line in lines[3:8]:  # Skip header
                print(f"   {line.rstrip()}")
    print()


def show_usage_instructions(sandbox_dir: str):
    """Show how to use the generated tests."""
    
    print("**To run the Python tests:**")
    print(f"   cd {sandbox_dir}")
    print("   pip install -r requirements.txt")
    print("   pytest test_api.py -v")
    print()
    
    print("**To run the JavaScript tests:**")
    print(f"   cd {sandbox_dir}")
    print("   npm install")
    print("   npm test")
    print()
    
    print("**To run the cURL tests manually:**")
    print(f"   cd {sandbox_dir}")
    print("   chmod +x test_api.sh")
    print("   ./test_api.sh")
    print()
    
    print("**To use the Java tests:**")
    print(f"   cd {sandbox_dir}")
    print("   mvn test")
    print()
    
    print("**Documentation:**")
    print(f"   cat {sandbox_dir}/TEST_PLAN.md")


if __name__ == "__main__":
    main()
