#!/usr/bin/env python3
"""
Synthetic dataset generator for SpecTestPilot training.

Generates:
- data/train.jsonl with >= 500 rows
- data/test.jsonl with >= 100 rows

Each row contains:
{
    "task_id": "...",
    "openapi_yaml": "...",
    "gold": {
        "title": "...",
        "version": "...",
        "base_url": "...",
        "auth_type": "...",
        "endpoints": [{"method":"GET","path":"/x","operation_id":"..."}],
        "notes": "..."
    }
}
"""

import json
import random
import string
import os
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import yaml


# Seed for reproducibility
RANDOM_SEED = 42

# Configuration
TRAIN_SIZE = 500
TEST_SIZE = 100

# Vocabulary for generating realistic names
NOUNS = [
    "user", "product", "order", "item", "customer", "account", "payment",
    "invoice", "cart", "category", "review", "comment", "post", "article",
    "tag", "notification", "message", "file", "document", "report", "task",
    "project", "team", "member", "role", "permission", "setting", "config",
    "event", "session", "token", "key", "secret", "webhook", "subscription"
]

VERBS = [
    "get", "list", "create", "update", "delete", "search", "find", "fetch",
    "add", "remove", "modify", "cancel", "approve", "reject", "submit",
    "process", "validate", "verify", "activate", "deactivate", "archive"
]

ADJECTIVES = [
    "active", "pending", "completed", "cancelled", "draft", "published",
    "private", "public", "internal", "external", "primary", "secondary"
]

# Schema types
SCHEMA_TYPES = ["string", "integer", "number", "boolean", "array", "object"]

# Auth types
AUTH_TYPES = ["none", "apiKey", "bearer", "oauth2"]

# HTTP methods with weights
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
METHOD_WEIGHTS = [0.35, 0.25, 0.15, 0.1, 0.15]


@dataclass
class GeneratedEndpoint:
    """Generated endpoint data."""
    method: str
    path: str
    operation_id: str
    summary: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    request_body: Optional[Dict[str, Any]] = None
    responses: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


@dataclass
class GeneratedSpec:
    """Generated OpenAPI spec data."""
    title: str
    version: str
    base_url: str
    description: str
    auth_type: str
    auth_details: Dict[str, Any]
    endpoints: List[GeneratedEndpoint]
    schemas: Dict[str, Any]
    is_incomplete: bool = False
    incomplete_reason: str = ""


def generate_id(prefix: str = "task") -> str:
    """Generate a unique task ID."""
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}_{suffix}"


def generate_api_name() -> str:
    """Generate a realistic API name."""
    patterns = [
        lambda: f"{random.choice(NOUNS).title()} API",
        lambda: f"{random.choice(NOUNS).title()} Service",
        lambda: f"{random.choice(NOUNS).title()} Management API",
        lambda: f"{random.choice(ADJECTIVES).title()} {random.choice(NOUNS).title()} API",
    ]
    return random.choice(patterns)()


def generate_version() -> str:
    """Generate a semantic version."""
    major = random.randint(1, 3)
    minor = random.randint(0, 9)
    patch = random.randint(0, 20)
    return f"{major}.{minor}.{patch}"


def generate_base_url() -> str:
    """Generate a base URL."""
    domains = ["api.example.com", "api.acme.io", "service.internal", "gateway.prod"]
    prefixes = ["", "/v1", "/v2", "/api", "/api/v1"]
    return f"https://{random.choice(domains)}{random.choice(prefixes)}"


def generate_path(noun: str, has_id: bool = False, nested: Optional[str] = None) -> str:
    """Generate an API path."""
    base = f"/{noun}s"
    
    if has_id:
        base += f"/{{{noun}_id}}"
    
    if nested:
        base += f"/{nested}s"
        if random.random() > 0.5:
            base += f"/{{{nested}_id}}"
    
    return base


def generate_operation_id(method: str, noun: str, action: Optional[str] = None) -> str:
    """Generate an operation ID."""
    if action:
        return f"{action}_{noun}"
    
    method_actions = {
        "GET": ["get", "list", "fetch"],
        "POST": ["create", "add"],
        "PUT": ["update", "replace"],
        "PATCH": ["update", "modify"],
        "DELETE": ["delete", "remove"]
    }
    
    action = random.choice(method_actions.get(method, ["handle"]))
    return f"{action}_{noun}"


def generate_parameter(name: str, location: str, required: bool = False) -> Dict[str, Any]:
    """Generate a parameter definition."""
    schema_type = random.choice(["string", "integer"])
    
    param = {
        "name": name,
        "in": location,
        "required": required,
        "schema": {"type": schema_type}
    }
    
    if random.random() > 0.5:
        param["description"] = f"The {name.replace('_', ' ')}"
    
    if schema_type == "string" and random.random() > 0.7:
        param["schema"]["format"] = random.choice(["uuid", "date", "date-time", "email"])
    
    return param


def generate_schema(name: str, depth: int = 0) -> Dict[str, Any]:
    """Generate a schema definition."""
    if depth > 2:
        return {"type": "string"}
    
    schema = {
        "type": "object",
        "properties": {}
    }
    
    # Add common fields
    common_fields = ["id", "created_at", "updated_at"]
    for field_name in common_fields:
        if random.random() > 0.3:
            if field_name == "id":
                schema["properties"][field_name] = {"type": "string", "format": "uuid"}
            else:
                schema["properties"][field_name] = {"type": "string", "format": "date-time"}
    
    # Add random fields
    num_fields = random.randint(2, 6)
    for _ in range(num_fields):
        field_name = f"{random.choice(NOUNS)}_{random.choice(['name', 'value', 'status', 'type', 'count'])}"
        field_type = random.choice(["string", "integer", "boolean", "number"])
        schema["properties"][field_name] = {"type": field_type}
    
    # Add required fields
    if schema["properties"]:
        required = random.sample(
            list(schema["properties"].keys()),
            k=min(3, len(schema["properties"]))
        )
        schema["required"] = required
    
    return schema


def generate_request_body(noun: str) -> Dict[str, Any]:
    """Generate a request body definition."""
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "$ref": f"#/components/schemas/{noun.title()}Input"
                }
            }
        }
    }


def generate_responses(noun: str, method: str) -> Dict[str, Dict[str, Any]]:
    """Generate response definitions."""
    responses = {}
    
    # Success response
    if method == "GET":
        responses["200"] = {
            "description": f"Successful response",
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{noun.title()}"}
                }
            }
        }
    elif method == "POST":
        responses["201"] = {
            "description": "Created",
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{noun.title()}"}
                }
            }
        }
    elif method in ["PUT", "PATCH"]:
        responses["200"] = {
            "description": "Updated",
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{noun.title()}"}
                }
            }
        }
    elif method == "DELETE":
        responses["204"] = {"description": "Deleted"}
    
    # Error responses
    if random.random() > 0.3:
        responses["400"] = {"description": "Bad Request"}
    if random.random() > 0.5:
        responses["404"] = {"description": "Not Found"}
    if random.random() > 0.6:
        responses["500"] = {"description": "Internal Server Error"}
    
    return responses


def generate_auth_scheme(auth_type: str) -> Tuple[Dict[str, Any], List[Dict[str, List[str]]]]:
    """Generate authentication scheme and security requirement."""
    if auth_type == "none":
        return {}, []
    
    if auth_type == "apiKey":
        scheme = {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": random.choice(["header", "query"]),
                "name": random.choice(["X-API-Key", "api_key", "Authorization"])
            }
        }
        security = [{"ApiKeyAuth": []}]
        
    elif auth_type == "bearer":
        scheme = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT"
            }
        }
        security = [{"BearerAuth": []}]
        
    elif auth_type == "oauth2":
        scheme = {
            "OAuth2": {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": "https://auth.example.com/authorize",
                        "tokenUrl": "https://auth.example.com/token",
                        "scopes": {
                            "read": "Read access",
                            "write": "Write access"
                        }
                    }
                }
            }
        }
        security = [{"OAuth2": ["read", "write"]}]
    else:
        return {}, []
    
    return scheme, security


def generate_endpoint(noun: str, method: str, has_id: bool = False) -> GeneratedEndpoint:
    """Generate a single endpoint."""
    path = generate_path(noun, has_id)
    operation_id = generate_operation_id(method, noun)
    
    parameters = []
    
    # Path parameters
    if has_id:
        parameters.append(generate_parameter(f"{noun}_id", "path", required=True))
    
    # Query parameters for GET
    if method == "GET" and not has_id:
        if random.random() > 0.5:
            parameters.append(generate_parameter("page", "query"))
            parameters.append(generate_parameter("limit", "query"))
        if random.random() > 0.6:
            parameters.append(generate_parameter("sort", "query"))
        if random.random() > 0.7:
            parameters.append(generate_parameter("filter", "query"))
    
    # Request body for POST/PUT/PATCH
    request_body = None
    if method in ["POST", "PUT", "PATCH"]:
        request_body = generate_request_body(noun)
    
    responses = generate_responses(noun, method)
    
    return GeneratedEndpoint(
        method=method,
        path=path,
        operation_id=operation_id,
        summary=f"{method} {noun}",
        parameters=parameters,
        request_body=request_body,
        responses=responses,
        tags=[noun]
    )


def generate_spec(
    num_endpoints: int = None,
    auth_type: str = None,
    is_incomplete: bool = False
) -> GeneratedSpec:
    """Generate a complete OpenAPI spec."""
    if num_endpoints is None:
        num_endpoints = random.randint(1, 8)
    
    if auth_type is None:
        auth_type = random.choice(AUTH_TYPES)
    
    title = generate_api_name()
    version = generate_version()
    base_url = generate_base_url()
    description = f"API for managing {random.choice(NOUNS)}s"
    
    # Generate auth
    auth_schemes, security = generate_auth_scheme(auth_type)
    
    # Generate endpoints
    endpoints = []
    schemas = {}
    
    # Pick random nouns for resources
    resource_nouns = random.sample(NOUNS, k=min(4, num_endpoints))
    
    for noun in resource_nouns:
        # Generate schema for this resource
        schemas[noun.title()] = generate_schema(noun)
        schemas[f"{noun.title()}Input"] = generate_schema(f"{noun}_input")
        
        # Generate CRUD endpoints
        methods_to_generate = random.sample(METHODS, k=random.randint(1, 4))
        
        for method in methods_to_generate:
            if len(endpoints) >= num_endpoints:
                break
            
            # Decide if this endpoint needs an ID
            has_id = method in ["GET", "PUT", "PATCH", "DELETE"] and random.random() > 0.3
            
            # For list endpoints
            if method == "GET" and random.random() > 0.5:
                has_id = False
            
            endpoint = generate_endpoint(noun, method, has_id)
            endpoints.append(endpoint)
    
    # Handle incomplete specs
    incomplete_reason = ""
    if is_incomplete:
        incomplete_type = random.choice(["no_endpoints", "no_auth_details", "partial"])
        
        if incomplete_type == "no_endpoints":
            endpoints = []
            incomplete_reason = "No endpoints defined"
        elif incomplete_type == "no_auth_details":
            auth_schemes = {}
            incomplete_reason = "Auth type specified but no details"
        else:
            # Remove some required fields
            if random.random() > 0.5:
                title = ""
                incomplete_reason = "Missing title"
            elif random.random() > 0.5:
                base_url = ""
                incomplete_reason = "Missing base URL"
    
    return GeneratedSpec(
        title=title,
        version=version,
        base_url=base_url,
        description=description,
        auth_type=auth_type,
        auth_details=auth_schemes,
        endpoints=endpoints,
        schemas=schemas,
        is_incomplete=is_incomplete,
        incomplete_reason=incomplete_reason
    )


def spec_to_openapi_yaml(spec: GeneratedSpec) -> str:
    """Convert GeneratedSpec to OpenAPI YAML string."""
    openapi = {
        "openapi": "3.0.3",
        "info": {
            "title": spec.title or "Untitled API",
            "version": spec.version,
            "description": spec.description
        },
        "servers": [{"url": spec.base_url}] if spec.base_url else [],
        "paths": {},
        "components": {
            "schemas": spec.schemas
        }
    }
    
    # Add security schemes
    if spec.auth_details:
        openapi["components"]["securitySchemes"] = spec.auth_details
        # Add global security
        security_names = list(spec.auth_details.keys())
        if security_names:
            openapi["security"] = [{name: []} for name in security_names]
    
    # Add paths
    for endpoint in spec.endpoints:
        if endpoint.path not in openapi["paths"]:
            openapi["paths"][endpoint.path] = {}
        
        operation = {
            "operationId": endpoint.operation_id,
            "summary": endpoint.summary,
            "tags": endpoint.tags,
            "responses": endpoint.responses
        }
        
        if endpoint.parameters:
            operation["parameters"] = endpoint.parameters
        
        if endpoint.request_body:
            operation["requestBody"] = endpoint.request_body
        
        openapi["paths"][endpoint.path][endpoint.method.lower()] = operation
    
    return yaml.dump(openapi, default_flow_style=False, sort_keys=False)


def spec_to_gold(spec: GeneratedSpec) -> Dict[str, Any]:
    """Convert GeneratedSpec to gold standard format."""
    return {
        "title": spec.title or "unknown",
        "version": spec.version,
        "base_url": spec.base_url or "unknown",
        "auth_type": spec.auth_type,
        "endpoints": [
            {
                "method": ep.method,
                "path": ep.path,
                "operation_id": ep.operation_id
            }
            for ep in spec.endpoints
        ],
        "notes": spec.incomplete_reason if spec.is_incomplete else ""
    }


def generate_dataset_row(task_id: str, is_incomplete: bool = False) -> Dict[str, Any]:
    """Generate a single dataset row."""
    spec = generate_spec(is_incomplete=is_incomplete)
    
    return {
        "task_id": task_id,
        "openapi_yaml": spec_to_openapi_yaml(spec),
        "gold": spec_to_gold(spec)
    }


def generate_dataset(
    output_dir: str = "data",
    train_size: int = TRAIN_SIZE,
    test_size: int = TEST_SIZE,
    seed: int = RANDOM_SEED
) -> None:
    """
    Generate training and test datasets.
    
    Args:
        output_dir: Output directory
        train_size: Number of training examples
        test_size: Number of test examples
        seed: Random seed for reproducibility
    """
    random.seed(seed)
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate training data
    train_path = os.path.join(output_dir, "train.jsonl")
    print(f"Generating {train_size} training examples...")
    
    with open(train_path, "w") as f:
        for i in range(train_size):
            task_id = generate_id(f"train_{i:04d}")
            # 10% incomplete specs
            is_incomplete = random.random() < 0.1
            row = generate_dataset_row(task_id, is_incomplete)
            f.write(json.dumps(row) + "\n")
            
            if (i + 1) % 100 == 0:
                print(f"  Generated {i + 1}/{train_size} training examples")
    
    print(f"Saved training data to {train_path}")
    
    # Generate test data with different seed
    random.seed(seed + 1000)
    test_path = os.path.join(output_dir, "test.jsonl")
    print(f"Generating {test_size} test examples...")
    
    with open(test_path, "w") as f:
        for i in range(test_size):
            task_id = generate_id(f"test_{i:04d}")
            # 15% incomplete specs in test set
            is_incomplete = random.random() < 0.15
            row = generate_dataset_row(task_id, is_incomplete)
            f.write(json.dumps(row) + "\n")
            
            if (i + 1) % 50 == 0:
                print(f"  Generated {i + 1}/{test_size} test examples")
    
    print(f"Saved test data to {test_path}")
    
    # Print statistics
    print("\nDataset Statistics:")
    print(f"  Training examples: {train_size}")
    print(f"  Test examples: {test_size}")
    print(f"  Random seed: {seed}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate synthetic dataset for SpecTestPilot")
    parser.add_argument("--output-dir", default="data", help="Output directory")
    parser.add_argument("--train-size", type=int, default=TRAIN_SIZE, help="Training set size")
    parser.add_argument("--test-size", type=int, default=TEST_SIZE, help="Test set size")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED, help="Random seed")
    
    args = parser.parse_args()
    
    generate_dataset(
        output_dir=args.output_dir,
        train_size=args.train_size,
        test_size=args.test_size,
        seed=args.seed
    )


if __name__ == "__main__":
    main()
