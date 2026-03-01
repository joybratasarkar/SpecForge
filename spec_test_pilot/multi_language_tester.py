#!/usr/bin/env python3
"""
Multi-Language API Testing Agent
Comprehensive API testing agent that thinks and acts like a human tester
Supports multiple programming languages and testing frameworks
"""

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import yaml
import requests
from pathlib import Path


class TestLanguage(Enum):
    """Supported testing languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    JAVA = "java"
    CSHARP = "csharp"
    GO = "go"
    RUST = "rust"
    CURL = "curl"
    POSTMAN = "postman"


class TestType(Enum):
    """Types of tests like a human tester would do."""
    HAPPY_PATH = "happy_path"
    ERROR_HANDLING = "error_handling"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    INPUT_VALIDATION = "input_validation"
    BOUNDARY_TESTING = "boundary_testing"
    PERFORMANCE = "performance"
    SECURITY = "security"
    EDGE_CASES = "edge_cases"
    INTEGRATION = "integration"


@dataclass
class TestScenario:
    """A test scenario like a human tester would design."""
    name: str
    description: str
    test_type: TestType
    endpoint: str
    method: str
    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    body: Optional[Dict[str, Any]] = None
    expected_status: int = 200
    expected_response_fields: List[str] = field(default_factory=list)
    assertions: List[str] = field(default_factory=list)


@dataclass
class APIEndpoint:
    """Parsed API endpoint information."""
    path: str
    method: str
    summary: str
    parameters: List[Dict[str, Any]]
    request_body: Optional[Dict[str, Any]]
    responses: Dict[str, Any]
    auth_required: bool = False
    auth_type: Optional[str] = None


class HumanTesterSimulator:
    """Simulates how a human tester would approach API testing."""
    
    def __init__(self, api_spec: Dict[str, Any], base_url: str = "https://api.example.com"):
        """Initialize with API specification."""
        self.api_spec = api_spec
        self.base_url = base_url
        self.endpoints = self._parse_endpoints()
        self.test_scenarios = []
        
    def _parse_endpoints(self) -> List[APIEndpoint]:
        """Parse OpenAPI spec like a human tester would analyze it."""
        endpoints = []
        
        if 'paths' not in self.api_spec:
            return endpoints
            
        for path, path_info in self.api_spec['paths'].items():
            for method, method_info in path_info.items():
                if method.lower() in ['get', 'post', 'put', 'delete', 'patch']:
                    
                    # Extract parameters
                    parameters = method_info.get('parameters', [])
                    
                    # Check authentication
                    auth_required = 'security' in method_info or 'security' in self.api_spec
                    auth_type = None
                    if auth_required:
                        security = method_info.get('security', self.api_spec.get('security', []))
                        if security:
                            auth_type = list(security[0].keys())[0] if security[0] else None
                    
                    endpoint = APIEndpoint(
                        path=path,
                        method=method.upper(),
                        summary=method_info.get('summary', f"{method.upper()} {path}"),
                        parameters=parameters,
                        request_body=method_info.get('requestBody'),
                        responses=method_info.get('responses', {}),
                        auth_required=auth_required,
                        auth_type=auth_type
                    )
                    endpoints.append(endpoint)
        
        return endpoints
    
    def think_like_tester(self) -> List[TestScenario]:
        """Think like a human tester and generate comprehensive test scenarios."""
        scenarios = []
        
        for endpoint in self.endpoints:
            # 1. Happy path testing (what should work)
            scenarios.extend(self._create_happy_path_tests(endpoint))
            
            # 2. Error handling (what should fail gracefully)
            scenarios.extend(self._create_error_tests(endpoint))
            
            # 3. Authentication/Authorization testing
            if endpoint.auth_required:
                scenarios.extend(self._create_auth_tests(endpoint))
            
            # 4. Input validation testing
            scenarios.extend(self._create_validation_tests(endpoint))
            
            # 5. Boundary testing
            scenarios.extend(self._create_boundary_tests(endpoint))
            
            # 6. Security testing
            scenarios.extend(self._create_security_tests(endpoint))
            
            # 7. Edge cases
            scenarios.extend(self._create_edge_case_tests(endpoint))
        
        return scenarios
    
    def _create_happy_path_tests(self, endpoint: APIEndpoint) -> List[TestScenario]:
        """Create happy path tests - the basic functionality."""
        scenarios = []
        
        # Basic successful request
        scenario = TestScenario(
            name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_success",
            description=f"Test successful {endpoint.method} request to {endpoint.path}",
            test_type=TestType.HAPPY_PATH,
            endpoint=endpoint.path,
            method=endpoint.method,
            expected_status=200 if endpoint.method == 'GET' else (201 if endpoint.method == 'POST' else 200)
        )
        
        # Add required parameters
        for param in endpoint.parameters:
            if param.get('required', False):
                if param['in'] == 'query':
                    scenario.params[param['name']] = self._generate_sample_value(param)
                elif param['in'] == 'header':
                    scenario.headers[param['name']] = self._generate_sample_value(param)
        
        # Add request body for POST/PUT
        if endpoint.method in ['POST', 'PUT', 'PATCH'] and endpoint.request_body:
            scenario.body = self._generate_sample_body(endpoint.request_body)
        
        scenarios.append(scenario)
        return scenarios
    
    def _create_error_tests(self, endpoint: APIEndpoint) -> List[TestScenario]:
        """Create error handling tests."""
        scenarios = []
        
        # Test 404 - Non-existent resource
        if '{id}' in endpoint.path or '{' in endpoint.path:
            scenarios.append(TestScenario(
                name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_not_found",
                description=f"Test {endpoint.method} request with non-existent ID",
                test_type=TestType.ERROR_HANDLING,
                endpoint=endpoint.path.replace('{id}', '99999').replace('{userId}', '99999'),
                method=endpoint.method,
                expected_status=404,
                assertions=["Response contains error message", "Error format is consistent"]
            ))
        
        # Test 400 - Bad request
        if endpoint.method in ['POST', 'PUT', 'PATCH']:
            scenarios.append(TestScenario(
                name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_bad_request",
                description=f"Test {endpoint.method} request with invalid data",
                test_type=TestType.ERROR_HANDLING,
                endpoint=endpoint.path,
                method=endpoint.method,
                body={"invalid_field": "invalid_value"},
                expected_status=400,
                assertions=["Response explains validation errors", "Error details are provided"]
            ))
        
        return scenarios
    
    def _create_auth_tests(self, endpoint: APIEndpoint) -> List[TestScenario]:
        """Create authentication/authorization tests."""
        scenarios = []
        
        # Test 401 - No authentication
        scenarios.append(TestScenario(
            name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_unauthorized",
            description=f"Test {endpoint.method} request without authentication",
            test_type=TestType.AUTHENTICATION,
            endpoint=endpoint.path,
            method=endpoint.method,
            expected_status=401,
            assertions=["Unauthorized access is properly rejected"]
        ))
        
        # Test 403 - Invalid token
        scenarios.append(TestScenario(
            name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_forbidden",
            description=f"Test {endpoint.method} request with invalid token",
            test_type=TestType.AUTHORIZATION,
            endpoint=endpoint.path,
            method=endpoint.method,
            headers={"Authorization": "Bearer invalid_token_12345"},
            expected_status=403,
            assertions=["Invalid token is rejected", "Proper error message returned"]
        ))
        
        return scenarios
    
    def _create_validation_tests(self, endpoint: APIEndpoint) -> List[TestScenario]:
        """Create input validation tests."""
        scenarios = []
        
        # Test missing required parameters
        for param in endpoint.parameters:
            if param.get('required', False):
                scenario = TestScenario(
                    name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_missing_{param['name']}",
                    description=f"Test {endpoint.method} request missing required parameter {param['name']}",
                    test_type=TestType.INPUT_VALIDATION,
                    endpoint=endpoint.path,
                    method=endpoint.method,
                    expected_status=400,
                    assertions=[f"Missing {param['name']} parameter is detected"]
                )
                scenarios.append(scenario)
        
        return scenarios
    
    def _create_boundary_tests(self, endpoint: APIEndpoint) -> List[TestScenario]:
        """Create boundary value tests."""
        scenarios = []
        
        # Test very long strings, extreme numbers, etc.
        if endpoint.method in ['POST', 'PUT', 'PATCH']:
            scenarios.append(TestScenario(
                name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_max_length",
                description=f"Test {endpoint.method} with maximum length inputs",
                test_type=TestType.BOUNDARY_TESTING,
                endpoint=endpoint.path,
                method=endpoint.method,
                body={"description": "A" * 10000},  # Very long string
                expected_status=400,
                assertions=["Long inputs are handled gracefully"]
            ))
        
        return scenarios
    
    def _create_security_tests(self, endpoint: APIEndpoint) -> List[TestScenario]:
        """Create security-focused tests."""
        scenarios = []
        
        # SQL Injection test
        if endpoint.parameters:
            scenarios.append(TestScenario(
                name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_sql_injection",
                description=f"Test {endpoint.method} for SQL injection vulnerability",
                test_type=TestType.SECURITY,
                endpoint=endpoint.path,
                method=endpoint.method,
                params={"q": "'; DROP TABLE users; --"},
                expected_status=400,
                assertions=["SQL injection attempts are blocked"]
            ))
        
        # XSS test
        if endpoint.method in ['POST', 'PUT', 'PATCH']:
            scenarios.append(TestScenario(
                name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_xss_protection",
                description=f"Test {endpoint.method} for XSS vulnerability",
                test_type=TestType.SECURITY,
                endpoint=endpoint.path,
                method=endpoint.method,
                body={"comment": "<script>alert('xss')</script>"},
                expected_status=400,
                assertions=["XSS attempts are sanitized"]
            ))
        
        return scenarios
    
    def _create_edge_case_tests(self, endpoint: APIEndpoint) -> List[TestScenario]:
        """Create edge case tests."""
        scenarios = []
        
        # Empty body test
        if endpoint.method in ['POST', 'PUT', 'PATCH']:
            scenarios.append(TestScenario(
                name=f"test_{endpoint.method.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_empty_body",
                description=f"Test {endpoint.method} with empty request body",
                test_type=TestType.EDGE_CASES,
                endpoint=endpoint.path,
                method=endpoint.method,
                body={},
                expected_status=400,
                assertions=["Empty body is handled appropriately"]
            ))
        
        return scenarios
    
    def _generate_sample_value(self, param: Dict[str, Any]) -> Any:
        """Generate sample values for parameters."""
        param_type = param.get('type', 'string')
        param_name = param.get('name', '').lower()
        
        if param_type == 'integer':
            if 'id' in param_name:
                return 123
            return 10
        elif param_type == 'boolean':
            return True
        elif param_type == 'array':
            return ["sample1", "sample2"]
        else:  # string
            if 'email' in param_name:
                return "test@example.com"
            elif 'id' in param_name:
                return "abc123"
            elif 'token' in param_name:
                return "bearer_token_12345"
            return "sample_value"
    
    def _generate_sample_body(self, request_body: Dict[str, Any]) -> Dict[str, Any]:
        """Generate sample request body."""
        # This is a simplified version - in reality, you'd parse the schema
        return {
            "name": "Test User",
            "email": "test@example.com",
            "description": "Sample description"
        }


class MultiLanguageTestGenerator:
    """Generates tests in multiple programming languages."""
    
    def __init__(self, scenarios: List[TestScenario], base_url: str):
        """Initialize with test scenarios."""
        self.scenarios = scenarios
        self.base_url = base_url
    
    def generate_python_tests(self) -> str:
        """Generate Python pytest tests."""
        code = '''import pytest
import requests
import json

BASE_URL = "{}"

class TestAPI:
    """Comprehensive API tests generated by AI agent."""

'''.format(self.base_url)
        
        for scenario in self.scenarios:
            code += self._generate_python_test_method(scenario)
        
        return code
    
    def _generate_python_test_method(self, scenario: TestScenario) -> str:
        """Generate a single Python test method."""
        method_code = f'''    def {scenario.name}(self):
        """{scenario.description}"""
        url = BASE_URL + "{scenario.endpoint}"
        
'''
        
        # Add headers
        if scenario.headers:
            method_code += f"        headers = {json.dumps(scenario.headers, indent=8)}\n"
        else:
            method_code += "        headers = {}\n"
        
        # Add params
        if scenario.params:
            method_code += f"        params = {json.dumps(scenario.params, indent=8)}\n"
        else:
            method_code += "        params = {}\n"
        
        # Add request
        if scenario.method == 'GET':
            method_code += "        response = requests.get(url, headers=headers, params=params)\n"
        elif scenario.method == 'POST':
            if scenario.body:
                method_code += f"        data = {json.dumps(scenario.body, indent=8)}\n"
                method_code += "        response = requests.post(url, headers=headers, params=params, json=data)\n"
            else:
                method_code += "        response = requests.post(url, headers=headers, params=params)\n"
        elif scenario.method == 'PUT':
            if scenario.body:
                method_code += f"        data = {json.dumps(scenario.body, indent=8)}\n"
                method_code += "        response = requests.put(url, headers=headers, params=params, json=data)\n"
            else:
                method_code += "        response = requests.put(url, headers=headers, params=params)\n"
        elif scenario.method == 'DELETE':
            method_code += "        response = requests.delete(url, headers=headers, params=params)\n"
        
        # Add assertions
        method_code += f"        assert response.status_code == {scenario.expected_status}\n"
        
        for assertion in scenario.assertions:
            if "error message" in assertion.lower():
                method_code += '        assert "error" in response.json() or "message" in response.json()\n'
            elif "response contains" in assertion.lower():
                method_code += "        assert response.json() is not None\n"
        
        method_code += "\n"
        return method_code
    
    def generate_javascript_tests(self) -> str:
        """Generate JavaScript tests using Jest/Axios."""
        code = f'''const axios = require('axios');

const BASE_URL = '{self.base_url}';

describe('API Tests', () => {{

'''
        
        for scenario in self.scenarios:
            code += self._generate_javascript_test_method(scenario)
        
        code += "});\n"
        return code
    
    def _generate_javascript_test_method(self, scenario: TestScenario) -> str:
        """Generate JavaScript test method."""
        method_code = f'''  test('{scenario.description}', async () => {{
    const url = BASE_URL + '{scenario.endpoint}';
    const config = {{
      method: '{scenario.method.lower()}',
      url: url,
'''
        
        if scenario.headers:
            method_code += f"      headers: {json.dumps(scenario.headers, indent=6)},\n"
        
        if scenario.params:
            method_code += f"      params: {json.dumps(scenario.params, indent=6)},\n"
        
        if scenario.body:
            method_code += f"      data: {json.dumps(scenario.body, indent=6)},\n"
        
        method_code += "      validateStatus: () => true  // Don't throw on non-2xx\n"
        method_code += "    };\n\n"
        method_code += "    const response = await axios(config);\n"
        method_code += f"    expect(response.status).toBe({scenario.expected_status});\n"
        
        for assertion in scenario.assertions:
            if "error message" in assertion.lower():
                method_code += "    expect(response.data).toHaveProperty('error');\n"
        
        method_code += "  });\n\n"
        return method_code
    
    def generate_curl_tests(self) -> str:
        """Generate cURL commands for manual testing."""
        code = "#!/bin/bash\n# API Test Suite - cURL Commands\n\n"
        
        for scenario in self.scenarios:
            code += f"# {scenario.description}\n"
            
            curl_cmd = f"curl -X {scenario.method}"
            
            # Add headers
            for key, value in scenario.headers.items():
                curl_cmd += f' -H "{key}: {value}"'
            
            # Add data
            if scenario.body:
                curl_cmd += f" -d '{json.dumps(scenario.body)}'"
                curl_cmd += ' -H "Content-Type: application/json"'
            
            # Add URL
            url = self.base_url + scenario.endpoint
            if scenario.params:
                param_str = "&".join([f"{k}={v}" for k, v in scenario.params.items()])
                url += f"?{param_str}"
            
            curl_cmd += f' "{url}"'
            
            code += f"{curl_cmd}\n"
            code += f"# Expected status: {scenario.expected_status}\n\n"
        
        return code
    
    def generate_java_tests(self) -> str:
        """Generate Java tests using RestAssured."""
        code = f'''import io.restassured.RestAssured;
import org.junit.jupiter.api.Test;
import static io.restassured.RestAssured.*;
import static org.hamcrest.Matchers.*;

public class APITests {{
    private static final String BASE_URL = "{self.base_url}";

'''
        
        for scenario in self.scenarios:
            code += self._generate_java_test_method(scenario)
        
        code += "}\n"
        return code
    
    def _generate_java_test_method(self, scenario: TestScenario) -> str:
        """Generate Java test method."""
        method_name = scenario.name.replace("test_", "")
        method_code = f'''    @Test
    public void {method_name}() {{
        given()
            .baseUri(BASE_URL)
'''
        
        # Add headers
        for key, value in scenario.headers.items():
            method_code += f'            .header("{key}", "{value}")\n'
        
        # Add params
        for key, value in scenario.params.items():
            method_code += f'            .param("{key}", "{value}")\n'
        
        # Add body
        if scenario.body:
            method_code += f'            .body({json.dumps(scenario.body)})\n'
            method_code += '            .contentType("application/json")\n'
        
        method_code += "        .when()\n"
        method_code += f'            .{scenario.method.lower()}("{scenario.endpoint}")\n'
        method_code += "        .then()\n"
        method_code += f"            .statusCode({scenario.expected_status});\n"
        method_code += "    }\n\n"
        
        return method_code


class APITestingSandbox:
    """Sandbox environment for executing API tests safely."""
    
    def __init__(self, api_spec_path: str, base_url: str = "https://api.example.com"):
        """Initialize testing sandbox."""
        self.api_spec_path = api_spec_path
        self.base_url = base_url
        self.sandbox_dir = Path(tempfile.mkdtemp(prefix="api_testing_sandbox_"))
        self.results = []
        
        # Load API spec
        with open(api_spec_path, 'r') as f:
            if api_spec_path.endswith('.yaml') or api_spec_path.endswith('.yml'):
                self.api_spec = yaml.safe_load(f)
            else:
                self.api_spec = json.load(f)
    
    def run_full_test_suite(self) -> Dict[str, Any]:
        """Run complete test suite like a professional tester."""
        print("🤖 AI API Testing Agent Starting...")
        print("=" * 50)
        
        # 1. Think like a human tester
        print("🧠 Phase 1: Analyzing API like a human tester...")
        tester = HumanTesterSimulator(self.api_spec, self.base_url)
        scenarios = tester.think_like_tester()
        
        print(f"   Generated {len(scenarios)} test scenarios:")
        test_type_counts = {}
        for scenario in scenarios:
            test_type = scenario.test_type.value
            test_type_counts[test_type] = test_type_counts.get(test_type, 0) + 1
        
        for test_type, count in test_type_counts.items():
            print(f"   - {test_type.replace('_', ' ').title()}: {count} tests")
        
        # 2. Generate tests in multiple languages
        print("\n⚡ Phase 2: Generating tests in multiple languages...")
        generator = MultiLanguageTestGenerator(scenarios, self.base_url)
        
        # Generate Python tests
        python_tests = generator.generate_python_tests()
        python_file = self.sandbox_dir / "test_api.py"
        with open(python_file, 'w') as f:
            f.write(python_tests)
        print(f"   ✅ Python tests: {python_file}")
        
        # Generate JavaScript tests
        js_tests = generator.generate_javascript_tests()
        js_file = self.sandbox_dir / "test_api.test.js"
        with open(js_file, 'w') as f:
            f.write(js_tests)
        print(f"   ✅ JavaScript tests: {js_file}")
        
        # Generate cURL tests
        curl_tests = generator.generate_curl_tests()
        curl_file = self.sandbox_dir / "test_api.sh"
        with open(curl_file, 'w') as f:
            f.write(curl_tests)
        os.chmod(curl_file, 0o755)
        print(f"   ✅ cURL tests: {curl_file}")
        
        # Generate Java tests
        java_tests = generator.generate_java_tests()
        java_file = self.sandbox_dir / "APITests.java"
        with open(java_file, 'w') as f:
            f.write(java_tests)
        print(f"   ✅ Java tests: {java_file}")
        
        # 3. Create test documentation
        print("\n📝 Phase 3: Creating test documentation...")
        doc_content = self._generate_test_documentation(scenarios)
        doc_file = self.sandbox_dir / "TEST_PLAN.md"
        with open(doc_file, 'w') as f:
            f.write(doc_content)
        print(f"   ✅ Test documentation: {doc_file}")
        
        # 4. Create package files
        print("\n📦 Phase 4: Creating package files...")
        self._create_package_files()
        
        return {
            "sandbox_directory": str(self.sandbox_dir),
            "scenarios_generated": len(scenarios),
            "test_files": {
                "python": str(python_file),
                "javascript": str(js_file),
                "curl": str(curl_file),
                "java": str(java_file),
                "documentation": str(doc_file)
            },
            "test_breakdown": test_type_counts,
            "total_endpoints": len(tester.endpoints)
        }
    
    def _generate_test_documentation(self, scenarios: List[TestScenario]) -> str:
        """Generate comprehensive test documentation."""
        doc = """# API Testing Plan
Generated by AI Testing Agent

## Overview
This test suite provides comprehensive coverage of the API from the perspective of a professional tester.

## Test Categories

"""
        
        # Group by test type
        by_type = {}
        for scenario in scenarios:
            test_type = scenario.test_type.value
            if test_type not in by_type:
                by_type[test_type] = []
            by_type[test_type].append(scenario)
        
        for test_type, tests in by_type.items():
            doc += f"### {test_type.replace('_', ' ').title()}\n"
            doc += f"**Purpose**: {self._get_test_type_description(test_type)}\n"
            doc += f"**Test Count**: {len(tests)}\n\n"
            
            for test in tests[:3]:  # Show first 3 as examples
                doc += f"- **{test.name}**: {test.description}\n"
            
            if len(tests) > 3:
                doc += f"- ... and {len(tests) - 3} more\n"
            
            doc += "\n"
        
        doc += """## How to Run Tests

### Python (pytest)
```bash
pip install pytest requests
pytest test_api.py -v
```

### JavaScript (Jest)
```bash
npm install jest axios
npm test
```

### cURL (Manual)
```bash
chmod +x test_api.sh
./test_api.sh
```

### Java (Maven)
```bash
mvn test
```

## Expected Behavior
- All happy path tests should pass
- Error tests should return appropriate error codes
- Security tests should block malicious inputs
- Authentication tests should enforce proper access control
"""
        
        return doc
    
    def _get_test_type_description(self, test_type: str) -> str:
        """Get description for test type."""
        descriptions = {
            "happy_path": "Verify basic functionality works as expected",
            "error_handling": "Ensure graceful handling of error conditions",
            "authentication": "Verify authentication mechanisms work properly", 
            "authorization": "Test access control and permissions",
            "input_validation": "Ensure invalid inputs are properly rejected",
            "boundary_testing": "Test limits and edge values",
            "performance": "Verify response times and throughput",
            "security": "Test for common security vulnerabilities",
            "edge_cases": "Handle unusual but valid scenarios",
            "integration": "Test end-to-end workflows"
        }
        return descriptions.get(test_type, "Test specific functionality")
    
    def _create_package_files(self):
        """Create package management files."""
        
        # Python requirements.txt
        with open(self.sandbox_dir / "requirements.txt", 'w') as f:
            f.write("pytest>=7.0.0\nrequests>=2.25.0\n")
        
        # JavaScript package.json
        package_json = {
            "name": "api-tests",
            "version": "1.0.0",
            "scripts": {
                "test": "jest"
            },
            "dependencies": {
                "axios": "^0.27.0",
                "jest": "^28.0.0"
            }
        }
        with open(self.sandbox_dir / "package.json", 'w') as f:
            json.dump(package_json, f, indent=2)
        
        # Java pom.xml
        pom_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>api-tests</artifactId>
    <version>1.0.0</version>
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
    </properties>
    <dependencies>
        <dependency>
            <groupId>io.rest-assured</groupId>
            <artifactId>rest-assured</artifactId>
            <version>5.1.1</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter</artifactId>
            <version>5.8.2</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
</project>'''
        with open(self.sandbox_dir / "pom.xml", 'w') as f:
            f.write(pom_xml)
    
    def cleanup(self):
        """Clean up sandbox directory."""
        import shutil
        try:
            shutil.rmtree(self.sandbox_dir)
        except Exception:
            pass


if __name__ == "__main__":
    # Example usage
    sandbox = APITestingSandbox("examples/banking_api.yaml", "https://api.bankingexample.com")
    results = sandbox.run_full_test_suite()
    
    print("\n🎉 AI API Testing Complete!")
    print("=" * 30)
    print(f"Sandbox Directory: {results['sandbox_directory']}")
    print(f"Total Scenarios: {results['scenarios_generated']}")
    print(f"Endpoints Covered: {results['total_endpoints']}")
    print()
    print("Generated Test Files:")
    for lang, file_path in results['test_files'].items():
        print(f"  {lang.title()}: {file_path}")
    
    input("\nPress Enter to cleanup sandbox...")
    sandbox.cleanup()
    print("✅ Cleanup complete!")
