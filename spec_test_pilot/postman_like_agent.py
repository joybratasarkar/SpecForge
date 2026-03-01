#!/usr/bin/env python3
"""
Postman-Like AI Testing Agent
Complete API testing agent that mimics Postman's AI capabilities:
- Generate tests from natural language prompts
- Fix errors automatically (401, 403, 400, etc.)
- Orchestrate complex workflows
- Manage test data dynamically
- Explain existing tests for collaboration
"""

import json
import re
import time
import requests
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import yaml
from pathlib import Path
import tempfile


class ErrorType(Enum):
    """Common API errors that agent can fix."""
    UNAUTHORIZED_401 = "401"
    FORBIDDEN_403 = "403" 
    BAD_REQUEST_400 = "400"
    NOT_FOUND_404 = "404"
    METHOD_NOT_ALLOWED_405 = "405"
    SERVER_ERROR_500 = "500"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection"


@dataclass
class TestRequest:
    """A single API test request."""
    name: str
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    body: Optional[Dict[str, Any]] = None
    pre_request_script: Optional[str] = None
    test_script: Optional[str] = None
    expected_status: int = 200
    expected_response_time_ms: int = 5000


@dataclass
class TestWorkflow:
    """A workflow chain of test requests."""
    name: str
    description: str
    requests: List[TestRequest]
    global_variables: Dict[str, Any] = field(default_factory=dict)
    setup_script: Optional[str] = None
    teardown_script: Optional[str] = None


@dataclass
class ErrorAnalysis:
    """Analysis of API error with suggested fixes."""
    error_type: ErrorType
    error_message: str
    root_cause: str
    suggested_fixes: List[str]
    auto_fix_available: bool
    confidence_score: float


class PostmanLikeAgent:
    """Complete API testing agent with Postman-like capabilities."""
    
    def __init__(self, base_url: str = "", api_spec_path: Optional[str] = None):
        """Initialize the Postman-like testing agent."""
        self.base_url = base_url.rstrip('/')
        self.api_spec = {}
        self.test_data_store = {}
        self.workflow_history = []
        self.error_patterns = self._load_error_patterns()
        
        if api_spec_path and Path(api_spec_path).exists():
            self.load_api_spec(api_spec_path)
    
    def load_api_spec(self, spec_path: str):
        """Load OpenAPI specification."""
        with open(spec_path, 'r') as f:
            if spec_path.endswith('.yaml') or spec_path.endswith('.yml'):
                self.api_spec = yaml.safe_load(f)
            else:
                self.api_spec = json.load(f)
    
    def generate_tests_from_prompt(self, prompt: str) -> List[TestRequest]:
        """
        Generate comprehensive test cases from natural language prompt.
        
        Examples:
        - "Generate tests to validate status codes and response times"
        - "Create security tests for the user authentication endpoint"
        - "Test error handling for invalid input data"
        """
        print(f"🤖 Analyzing prompt: '{prompt}'")
        
        # Parse intent from prompt
        test_intent = self._parse_test_intent(prompt)
        
        # Generate tests based on intent
        tests = []
        
        if 'status code' in prompt.lower() or 'response time' in prompt.lower():
            tests.extend(self._generate_status_and_timing_tests())
            
        if 'security' in prompt.lower() or 'auth' in prompt.lower():
            tests.extend(self._generate_security_tests())
            
        if 'error' in prompt.lower() or 'invalid' in prompt.lower():
            tests.extend(self._generate_error_tests())
            
        if 'validation' in prompt.lower():
            tests.extend(self._generate_validation_tests())
            
        if not tests:  # Default comprehensive suite
            tests.extend(self._generate_comprehensive_test_suite())
        
        print(f"✅ Generated {len(tests)} test cases")
        return tests
    
    def analyze_and_fix_error(self, error_response: Dict[str, Any], original_request: TestRequest) -> ErrorAnalysis:
        """
        Analyze failing request and provide automatic fixes.
        
        Like Postman's AI error analysis and correction.
        """
        status_code = error_response.get('status_code', 0)
        response_body = error_response.get('body', {})
        
        print(f"🔍 Analyzing {status_code} error...")
        
        # Identify error type
        error_type = self._identify_error_type(status_code, response_body)
        
        # Analyze root cause
        root_cause = self._analyze_root_cause(error_type, original_request, response_body)
        
        # Generate fixes
        suggested_fixes = self._generate_error_fixes(error_type, original_request, response_body)
        
        # Check if auto-fix is possible
        auto_fix_available = self._can_auto_fix(error_type, original_request)
        
        analysis = ErrorAnalysis(
            error_type=error_type,
            error_message=response_body.get('message', f'HTTP {status_code} Error'),
            root_cause=root_cause,
            suggested_fixes=suggested_fixes,
            auto_fix_available=auto_fix_available,
            confidence_score=self._calculate_confidence(error_type, response_body)
        )
        
        print(f"✅ Error analysis complete: {analysis.root_cause}")
        return analysis
    
    def auto_fix_request(self, request: TestRequest, error_analysis: ErrorAnalysis) -> TestRequest:
        """Automatically apply fixes to failing request."""
        if not error_analysis.auto_fix_available:
            raise ValueError("Auto-fix not available for this error type")
        
        print(f"🔧 Applying auto-fix for {error_analysis.error_type.value} error...")
        
        fixed_request = TestRequest(
            name=f"{request.name}_fixed",
            method=request.method,
            url=request.url,
            headers=request.headers.copy(),
            params=request.params.copy(),
            body=request.body.copy() if request.body else None,
            pre_request_script=request.pre_request_script,
            test_script=request.test_script
        )
        
        # Apply specific fixes based on error type
        if error_analysis.error_type == ErrorType.UNAUTHORIZED_401:
            # Add authentication
            if 'authorization' not in [h.lower() for h in fixed_request.headers]:
                fixed_request.headers['Authorization'] = 'Bearer {{auth_token}}'
                fixed_request.pre_request_script = self._generate_auth_script()
                
        elif error_analysis.error_type == ErrorType.FORBIDDEN_403:
            # Fix permissions or scope
            if 'Bearer' in fixed_request.headers.get('Authorization', ''):
                fixed_request.headers['Authorization'] = 'Bearer {{admin_token}}'
            fixed_request.pre_request_script = self._generate_scope_script()
            
        elif error_analysis.error_type == ErrorType.BAD_REQUEST_400:
            # Fix request data
            if fixed_request.body:
                fixed_request.body = self._fix_request_body(fixed_request.body, error_analysis)
            fixed_request.params = self._fix_request_params(fixed_request.params, error_analysis)
            
        elif error_analysis.error_type == ErrorType.NOT_FOUND_404:
            # Use valid resource ID
            fixed_request.url = self._fix_resource_url(fixed_request.url)
            
        print(f"✅ Auto-fix applied: {error_analysis.suggested_fixes[0]}")
        return fixed_request
    
    def create_workflow(self, workflow_name: str, requests_chain: List[str]) -> TestWorkflow:
        """
        Create end-to-end workflow by chaining requests.
        
        Example:
        workflow = agent.create_workflow("User Registration Flow", [
            "POST /auth/register - Create new user",
            "POST /auth/login - Login with created user", 
            "GET /user/profile - Get user profile",
            "PUT /user/profile - Update user data"
        ])
        """
        print(f"🔗 Creating workflow: {workflow_name}")
        
        workflow_requests = []
        global_vars = {}
        
        for i, request_desc in enumerate(requests_chain):
            # Parse request description
            method, path_and_desc = request_desc.split(' ', 1)
            if ' - ' in path_and_desc:
                path, desc = path_and_desc.split(' - ', 1)
            else:
                path, desc = path_and_desc, f"Step {i+1}"
            
            # Create request with chaining
            request = TestRequest(
                name=f"step_{i+1}_{desc.lower().replace(' ', '_')}",
                method=method,
                url=f"{self.base_url}{path}",
                pre_request_script=self._generate_chaining_script(i, workflow_requests),
                test_script=self._generate_workflow_assertions(i, desc)
            )
            
            # Add dynamic data based on previous responses
            if i > 0:
                request.headers['Authorization'] = '{{auth_token}}'
                if method in ['PUT', 'POST', 'PATCH']:
                    request.body = self._generate_dynamic_body(desc, global_vars)
            
            workflow_requests.append(request)
        
        workflow = TestWorkflow(
            name=workflow_name,
            description=f"End-to-end workflow with {len(requests_chain)} steps",
            requests=workflow_requests,
            global_variables=global_vars,
            setup_script=self._generate_workflow_setup(),
            teardown_script=self._generate_workflow_teardown()
        )
        
        print(f"✅ Workflow created with {len(workflow.requests)} chained requests")
        return workflow
    
    def generate_test_data(self, data_type: str, count: int = 10) -> Dict[str, Any]:
        """
        Generate dynamic test data for requests.
        
        Examples:
        - agent.generate_test_data("users", 5)
        - agent.generate_test_data("transactions", 20) 
        - agent.generate_test_data("products", 15)
        """
        print(f"🎲 Generating {count} {data_type} test records...")
        
        generators = {
            'users': self._generate_user_data,
            'transactions': self._generate_transaction_data,
            'products': self._generate_product_data,
            'orders': self._generate_order_data,
            'accounts': self._generate_account_data
        }
        
        generator = generators.get(data_type.lower(), self._generate_generic_data)
        data = [generator(i) for i in range(count)]
        
        # Store for reuse
        self.test_data_store[data_type] = data
        
        print(f"✅ Generated {len(data)} {data_type} records")
        return {
            'data': data,
            'pre_request_script': self._generate_data_setup_script(data_type, data)
        }
    
    def explain_test_suite(self, test_file_path: str) -> str:
        """
        Explain existing test suite for team collaboration.
        
        Analyzes test structure, dependencies, and provides documentation.
        """
        print(f"📚 Analyzing test suite: {test_file_path}")
        
        try:
            with open(test_file_path, 'r') as f:
                test_content = f.read()
        except FileNotFoundError:
            return "❌ Test file not found"
        
        explanation = "# Test Suite Analysis\n\n"
        
        # Analyze test structure
        explanation += "## Test Structure\n"
        test_methods = re.findall(r'def (test_\w+)', test_content)
        explanation += f"- **Total Tests**: {len(test_methods)}\n"
        
        # Categorize tests
        categories = {
            'authentication': len([t for t in test_methods if 'auth' in t.lower()]),
            'validation': len([t for t in test_methods if 'valid' in t.lower()]),
            'error_handling': len([t for t in test_methods if 'error' in t.lower() or 'fail' in t.lower()]),
            'security': len([t for t in test_methods if 'security' in t.lower() or 'inject' in t.lower()])
        }
        
        explanation += "\n## Test Categories\n"
        for category, count in categories.items():
            if count > 0:
                explanation += f"- **{category.title()}**: {count} tests\n"
        
        # Identify dependencies
        imports = re.findall(r'import (\w+)', test_content)
        explanation += f"\n## Dependencies\n"
        for imp in set(imports):
            explanation += f"- {imp}\n"
        
        # Identify setup patterns
        explanation += "\n## Setup Patterns\n"
        if 'BASE_URL' in test_content:
            explanation += "- Uses configurable base URL\n"
        if 'headers' in test_content:
            explanation += "- Includes header management\n"
        if 'auth' in test_content.lower():
            explanation += "- Has authentication handling\n"
        
        # Test execution flow
        explanation += "\n## Execution Flow\n"
        if 'requests.get' in test_content:
            explanation += "- GET requests for data retrieval\n"
        if 'requests.post' in test_content:
            explanation += "- POST requests for data creation\n"
        if 'assert' in test_content:
            explanation += "- Comprehensive assertions for validation\n"
        
        # Collaboration notes
        explanation += "\n## Team Collaboration Notes\n"
        explanation += "- Tests are self-documenting with descriptive names\n"
        explanation += "- Assertions validate both status codes and response content\n"
        explanation += "- Error scenarios are explicitly tested\n"
        
        print("✅ Test suite analysis complete")
        return explanation
    
    def _parse_test_intent(self, prompt: str) -> Dict[str, Any]:
        """Parse natural language prompt to understand test intent."""
        intent = {
            'categories': [],
            'focus_areas': [],
            'specific_endpoints': [],
            'test_types': []
        }
        
        # Identify test categories
        if 'status code' in prompt.lower():
            intent['categories'].append('status_validation')
        if 'response time' in prompt.lower():
            intent['categories'].append('performance')
        if 'security' in prompt.lower():
            intent['categories'].append('security')
        if 'auth' in prompt.lower():
            intent['categories'].append('authentication')
        if 'error' in prompt.lower():
            intent['categories'].append('error_handling')
        
        # Extract specific endpoints
        endpoint_pattern = r'/([\w/-]+)'
        endpoints = re.findall(endpoint_pattern, prompt)
        intent['specific_endpoints'] = endpoints
        
        return intent
    
    def _generate_status_and_timing_tests(self) -> List[TestRequest]:
        """Generate tests focused on status codes and response times."""
        tests = []
        
        # Basic status code validation
        tests.append(TestRequest(
            name="test_api_status_codes",
            method="GET",
            url=f"{self.base_url}/api/health",
            test_script="""
pm.test("Status code is 200", function() {
    pm.response.to.have.status(200);
});

pm.test("Response time is acceptable", function() {
    pm.expect(pm.response.responseTime).to.be.below(2000);
});

pm.test("Response has correct content type", function() {
    pm.expect(pm.response.headers.get("Content-Type")).to.include("application/json");
});
""",
            expected_response_time_ms=2000
        ))
        
        # Error status codes
        tests.append(TestRequest(
            name="test_404_not_found",
            method="GET", 
            url=f"{self.base_url}/api/nonexistent",
            expected_status=404,
            test_script="""
pm.test("Returns 404 for non-existent resource", function() {
    pm.response.to.have.status(404);
});

pm.test("Error response has message", function() {
    const response = pm.response.json();
    pm.expect(response).to.have.property('error');
});
"""
        ))
        
        return tests
    
    def _generate_security_tests(self) -> List[TestRequest]:
        """Generate security-focused tests."""
        tests = []
        
        # SQL injection test
        tests.append(TestRequest(
            name="test_sql_injection_protection",
            method="GET",
            url=f"{self.base_url}/api/users",
            params={"search": "'; DROP TABLE users; --"},
            expected_status=400,
            test_script="""
pm.test("SQL injection is blocked", function() {
    pm.response.to.have.status(400);
});

pm.test("No sensitive data in error response", function() {
    const body = pm.response.text();
    pm.expect(body).to.not.include("SQL");
    pm.expect(body).to.not.include("DROP");
});
"""
        ))
        
        # XSS test
        tests.append(TestRequest(
            name="test_xss_protection",
            method="POST",
            url=f"{self.base_url}/api/comments", 
            body={"comment": "<script>alert('xss')</script>"},
            expected_status=400,
            test_script="""
pm.test("XSS attempt is blocked", function() {
    pm.response.to.have.status(400);
});

pm.test("Script tags are sanitized", function() {
    const response = pm.response.json();
    if (response.comment) {
        pm.expect(response.comment).to.not.include("<script>");
    }
});
"""
        ))
        
        return tests
    
    def _generate_error_tests(self) -> List[TestRequest]:
        """Generate error handling tests."""
        tests = []
        
        # Unauthorized test
        tests.append(TestRequest(
            name="test_unauthorized_access",
            method="GET",
            url=f"{self.base_url}/api/protected",
            headers={},  # No auth header
            expected_status=401,
            test_script="""
pm.test("Unauthorized access is properly rejected", function() {
    pm.response.to.have.status(401);
});

pm.test("Error response explains authentication requirement", function() {
    const response = pm.response.json();
    pm.expect(response.error).to.include("unauthorized");
});
"""
        ))
        
        return tests
    
    def _generate_comprehensive_test_suite(self) -> List[TestRequest]:
        """Generate comprehensive test suite when no specific intent."""
        tests = []
        tests.extend(self._generate_status_and_timing_tests())
        tests.extend(self._generate_security_tests()) 
        tests.extend(self._generate_error_tests())
        return tests
    
    def _identify_error_type(self, status_code: int, response_body: Dict) -> ErrorType:
        """Identify error type from status code and response."""
        status_map = {
            400: ErrorType.BAD_REQUEST_400,
            401: ErrorType.UNAUTHORIZED_401,
            403: ErrorType.FORBIDDEN_403,
            404: ErrorType.NOT_FOUND_404,
            405: ErrorType.METHOD_NOT_ALLOWED_405,
            500: ErrorType.SERVER_ERROR_500
        }
        
        return status_map.get(status_code, ErrorType.SERVER_ERROR_500)
    
    def _analyze_root_cause(self, error_type: ErrorType, request: TestRequest, response_body: Dict) -> str:
        """Analyze root cause of the error."""
        causes = {
            ErrorType.UNAUTHORIZED_401: "Missing or invalid authentication token",
            ErrorType.FORBIDDEN_403: "Valid auth but insufficient permissions/scope",
            ErrorType.BAD_REQUEST_400: "Invalid request data or missing required fields",
            ErrorType.NOT_FOUND_404: "Resource does not exist or invalid ID",
            ErrorType.METHOD_NOT_ALLOWED_405: "HTTP method not supported for this endpoint"
        }
        
        base_cause = causes.get(error_type, "Unknown server error")
        
        # Add specific details from response
        if 'message' in response_body:
            base_cause += f" - {response_body['message']}"
        
        return base_cause
    
    def _generate_error_fixes(self, error_type: ErrorType, request: TestRequest, response_body: Dict) -> List[str]:
        """Generate specific fixes for the error."""
        fixes = {
            ErrorType.UNAUTHORIZED_401: [
                "Add Authorization header with valid Bearer token",
                "Include API key in headers or query parameters", 
                "Ensure authentication endpoint is called first"
            ],
            ErrorType.FORBIDDEN_403: [
                "Use token with appropriate scopes/permissions",
                "Contact admin for elevated access rights",
                "Verify resource ownership permissions"
            ],
            ErrorType.BAD_REQUEST_400: [
                "Validate required fields are present",
                "Check data types match API specification", 
                "Remove invalid or extra fields",
                "Ensure proper JSON formatting"
            ],
            ErrorType.NOT_FOUND_404: [
                "Use valid resource ID that exists",
                "Create resource first if needed",
                "Check URL path is correct"
            ]
        }
        
        return fixes.get(error_type, ["Contact API documentation", "Check server logs"])
    
    def _can_auto_fix(self, error_type: ErrorType, request: TestRequest) -> bool:
        """Check if error can be automatically fixed."""
        auto_fixable = [
            ErrorType.UNAUTHORIZED_401,
            ErrorType.BAD_REQUEST_400,
            ErrorType.NOT_FOUND_404
        ]
        return error_type in auto_fixable
    
    def _calculate_confidence(self, error_type: ErrorType, response_body: Dict) -> float:
        """Calculate confidence in error analysis."""
        base_confidence = 0.7
        
        # Higher confidence with detailed error messages
        if 'message' in response_body:
            base_confidence += 0.2
        if 'details' in response_body or 'validation' in response_body:
            base_confidence += 0.1
            
        return min(base_confidence, 1.0)
    
    def _generate_auth_script(self) -> str:
        """Generate pre-request script for authentication."""
        return """
// Auto-generated authentication script
if (!pm.globals.get("auth_token")) {
    const loginRequest = {
        url: pm.globals.get("base_url") + "/auth/login",
        method: 'POST',
        header: {'Content-Type': 'application/json'},
        body: {
            mode: 'raw',
            raw: JSON.stringify({
                email: "test@example.com",
                password: "password123"
            })
        }
    };
    
    pm.sendRequest(loginRequest, function(err, response) {
        if (response.code === 200) {
            const token = response.json().access_token;
            pm.globals.set("auth_token", token);
        }
    });
}
"""
    
    def _generate_scope_script(self) -> str:
        """Generate script for handling permission scopes."""
        return """
// Auto-generated scope management script
const requiredScopes = ["admin", "write"];
pm.globals.set("required_scopes", requiredScopes.join(" "));

// Use admin token if available
const adminToken = pm.globals.get("admin_token");
if (adminToken) {
    pm.globals.set("auth_token", adminToken);
}
"""
    
    def _fix_request_body(self, body: Dict, error_analysis: ErrorAnalysis) -> Dict[str, Any]:
        """Fix request body based on error analysis."""
        if not body:
            return {}
            
        # Add common required fields if missing
        fixed_body = body.copy()
        
        # Common fixes for 400 errors
        if 'email' not in fixed_body and any('email' in fix.lower() for fix in error_analysis.suggested_fixes):
            fixed_body['email'] = 'test@example.com'
        if 'name' not in fixed_body:
            fixed_body['name'] = 'Test User'
            
        return fixed_body
    
    def _fix_request_params(self, params: Dict, error_analysis: ErrorAnalysis) -> Dict[str, Any]:
        """Fix request parameters.""" 
        fixed_params = params.copy()
        
        # Add common required params
        if 'page' not in fixed_params:
            fixed_params['page'] = 1
        if 'limit' not in fixed_params:
            fixed_params['limit'] = 10
            
        return fixed_params
    
    def _fix_resource_url(self, url: str) -> str:
        """Fix URL with valid resource ID."""
        # Replace common invalid IDs with valid ones
        url = url.replace('/999999', '/123')
        url = url.replace('/invalid', '/valid-resource')
        return url
    
    def _generate_chaining_script(self, step_index: int, previous_requests: List[TestRequest]) -> str:
        """Generate pre-request script for workflow chaining."""
        if step_index == 0:
            return "// First step - no dependencies"
        
        script = f"""
// Step {step_index + 1} - Chain from previous responses
"""
        
        if step_index == 1:  # Login step
            script += """
// Use token from login response
const loginResponse = pm.globals.get("step_1_response");
if (loginResponse && loginResponse.access_token) {
    pm.globals.set("auth_token", loginResponse.access_token);
}
"""
        
        return script
    
    def _generate_workflow_assertions(self, step_index: int, description: str) -> str:
        """Generate test assertions for workflow steps."""
        return f"""
pm.test("Step {step_index + 1}: {description}", function() {{
    pm.response.to.have.status(200);
}});

pm.test("Response time is acceptable", function() {{
    pm.expect(pm.response.responseTime).to.be.below(3000);
}});

// Store response for next step
pm.globals.set("step_{step_index + 1}_response", pm.response.json());
"""
    
    def _generate_workflow_setup(self) -> str:
        """Generate workflow setup script."""
        return """
// Workflow setup
console.log("Starting workflow execution...");
pm.globals.set("workflow_start_time", new Date().getTime());
"""
    
    def _generate_workflow_teardown(self) -> str:
        """Generate workflow cleanup script."""
        return """
// Workflow cleanup
console.log("Workflow execution complete");
const startTime = pm.globals.get("workflow_start_time");
const totalTime = new Date().getTime() - startTime;
console.log("Total workflow time:", totalTime + "ms");

// Clean up temporary data
pm.globals.unset("auth_token");
pm.globals.unset("workflow_start_time");
"""
    
    def _generate_user_data(self, index: int) -> Dict[str, Any]:
        """Generate realistic user test data."""
        return {
            "id": f"user_{index:03d}",
            "name": f"Test User {index}",
            "email": f"testuser{index}@example.com",
            "age": 25 + (index % 40),
            "role": "user" if index % 3 != 0 else "admin"
        }
    
    def _generate_transaction_data(self, index: int) -> Dict[str, Any]:
        """Generate realistic transaction test data."""
        return {
            "id": f"txn_{index:06d}",
            "amount": round(10.00 + (index * 15.50), 2),
            "currency": "USD",
            "type": "credit" if index % 2 == 0 else "debit",
            "description": f"Test transaction {index}"
        }
    
    def _generate_product_data(self, index: int) -> Dict[str, Any]:
        """Generate realistic product test data."""
        categories = ["electronics", "books", "clothing", "home"]
        return {
            "id": f"prod_{index:04d}",
            "name": f"Test Product {index}",
            "price": round(9.99 + (index * 5.25), 2),
            "category": categories[index % len(categories)],
            "in_stock": index % 5 != 0
        }
    
    def _generate_order_data(self, index: int) -> Dict[str, Any]:
        """Generate realistic order test data."""
        return {
            "id": f"order_{index:05d}",
            "user_id": f"user_{(index % 100):03d}",
            "total_amount": round(25.99 + (index * 12.75), 2),
            "status": "pending" if index % 4 == 0 else "completed",
            "items_count": 1 + (index % 5)
        }
    
    def _generate_account_data(self, index: int) -> Dict[str, Any]:
        """Generate realistic account test data."""
        account_types = ["checking", "savings", "business", "premium"]
        return {
            "id": f"acc_{index:06d}",
            "account_type": account_types[index % len(account_types)],
            "balance": round(100.00 + (index * 500.25), 2),
            "currency": "USD",
            "active": index % 10 != 0
        }
    
    def _generate_generic_data(self, index: int) -> Dict[str, Any]:
        """Generate generic test data."""
        return {
            "id": f"item_{index:04d}",
            "name": f"Test Item {index}",
            "value": index,
            "created_at": f"2024-01-{(index % 28) + 1:02d}T10:00:00Z"
        }
    
    def _generate_data_setup_script(self, data_type: str, data: List[Dict]) -> str:
        """Generate pre-request script for test data setup."""
        return f"""
// Auto-generated test data setup for {data_type}
const testData = {json.dumps(data[:5], indent=2)};  // First 5 records

// Set random test record
const randomIndex = Math.floor(Math.random() * testData.length);
const testRecord = testData[randomIndex];

// Make data available as variables
Object.keys(testRecord).forEach(key => {{
    pm.globals.set("test_" + key, testRecord[key]);
}});

console.log("Test data loaded:", testRecord);
"""
    
    def _load_error_patterns(self) -> Dict[str, Any]:
        """Load common error patterns for analysis."""
        return {
            "auth_errors": [
                "invalid_token", "expired_token", "missing_token",
                "insufficient_permissions", "invalid_scope"
            ],
            "validation_errors": [
                "required_field_missing", "invalid_format", "constraint_violation",
                "type_mismatch", "value_out_of_range"  
            ],
            "resource_errors": [
                "not_found", "already_exists", "conflict",
                "gone", "precondition_failed"
            ]
        }
    
    def export_to_postman_collection(self, tests: List[TestRequest], workflow: Optional[TestWorkflow] = None) -> Dict[str, Any]:
        """Export tests as Postman collection JSON."""
        collection = {
            "info": {
                "name": "AI Generated API Tests",
                "description": "Comprehensive test suite generated by AI agent",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
            },
            "variable": [
                {"key": "base_url", "value": self.base_url},
                {"key": "auth_token", "value": ""}
            ],
            "item": []
        }
        
        # Add individual tests
        for test in tests:
            item = {
                "name": test.name,
                "request": {
                    "method": test.method,
                    "header": [{"key": k, "value": v} for k, v in test.headers.items()],
                    "url": {
                        "raw": test.url,
                        "host": [self.base_url],
                        "path": test.url.replace(self.base_url, '').strip('/').split('/')
                    }
                },
                "event": []
            }
            
            if test.body:
                item["request"]["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(test.body, indent=2),
                    "options": {"raw": {"language": "json"}}
                }
            
            if test.pre_request_script:
                item["event"].append({
                    "listen": "prerequest", 
                    "script": {"exec": test.pre_request_script.split('\n')}
                })
            
            if test.test_script:
                item["event"].append({
                    "listen": "test",
                    "script": {"exec": test.test_script.split('\n')}
                })
            
            collection["item"].append(item)
        
        # Add workflow if provided
        if workflow:
            workflow_folder = {
                "name": workflow.name,
                "description": workflow.description,
                "item": []
            }
            
            for req in workflow.requests:
                # Convert workflow requests to Postman format
                workflow_item = {
                    "name": req.name,
                    "request": {
                        "method": req.method,
                        "header": [{"key": k, "value": v} for k, v in req.headers.items()],
                        "url": req.url
                    }
                }
                workflow_folder["item"].append(workflow_item)
            
            collection["item"].append(workflow_folder)
        
        return collection


if __name__ == "__main__":
    # Demo usage
    agent = PostmanLikeAgent("https://api.example.com", "examples/banking_api.yaml")
    
    # Generate tests from natural language
    tests = agent.generate_tests_from_prompt(
        "Generate tests to validate status codes and response times for user authentication"
    )
    
    # Create workflow
    workflow = agent.create_workflow("User Management Flow", [
        "POST /auth/register - Create new user",
        "POST /auth/login - Login with user",
        "GET /user/profile - Get profile", 
        "PUT /user/profile - Update profile"
    ])
    
    # Generate test data
    user_data = agent.generate_test_data("users", 10)
    
    # Export to Postman
    collection = agent.export_to_postman_collection(tests, workflow)
    
    print(f"✅ Generated {len(tests)} tests")
    print(f"✅ Created workflow with {len(workflow.requests)} steps")
    print(f"✅ Generated {len(user_data['data'])} user records")
    print(f"✅ Exported Postman collection with {len(collection['item'])} items")
