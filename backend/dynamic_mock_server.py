#!/usr/bin/env python3
"""
Dynamic Mock API Server - Automatically implements ANY OpenAPI spec.

This server dynamically creates endpoints based on the OpenAPI specification:
1. Reads OpenAPI spec (YAML/JSON)
2. Creates FastAPI routes for ALL endpoints automatically
3. Generates realistic responses based on schemas
4. Handles all HTTP methods (GET, POST, PUT, DELETE, PATCH)
5. Validates requests according to spec
6. Returns proper error codes

Usage:
    python dynamic_mock_server.py --spec any_api.yaml --port 8000
    
Works with ANY valid OpenAPI 3.0+ specification!
"""

import json
import yaml
import argparse
import asyncio
import os
import time
import uvicorn
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, get_args
from datetime import datetime
import logging
import re
from urllib.parse import urlparse

# FastAPI
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, create_model

from spec_test_pilot.runtime_settings import get_runtime_settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DynamicMockServer")
RUNTIME_SETTINGS = get_runtime_settings()

SQLI_PATTERN = re.compile(
    r"('(?:\s*;)?\s*--|\bunion\b\s+\bselect\b|\bdrop\b\s+\btable\b|\bor\b\s+1\s*=\s*1)",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)


class DynamicResponseGenerator:
    """Generate realistic responses based on OpenAPI schemas."""
    
    @staticmethod
    def generate_from_schema(schema: Dict, operation_id: str = "", path: str = "") -> Any:
        """Generate data from OpenAPI schema."""
        if not schema:
            return {"message": "success", "timestamp": datetime.now().isoformat()}
        
        schema_type = schema.get("type", "object")
        
        if schema_type == "object":
            return DynamicResponseGenerator._generate_object(schema, operation_id, path)
        elif schema_type == "array":
            items_schema = schema.get("items", {})
            item = DynamicResponseGenerator.generate_from_schema(items_schema, operation_id, path)
            return [item] * 2  # Return 2 items
        elif schema_type == "string":
            return DynamicResponseGenerator._generate_string_value(schema, path)
        elif schema_type == "integer":
            return schema.get("example", 123)
        elif schema_type == "number":
            return schema.get("example", 12.34)
        elif schema_type == "boolean":
            return schema.get("example", True)
        else:
            return {"data": "generated"}
    
    @staticmethod
    def _generate_object(schema: Dict, operation_id: str, path: str) -> Dict:
        """Generate object from schema."""
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        result = {}
        
        # Generate required fields
        for field_name in required:
            if field_name in properties:
                field_schema = properties[field_name]
                result[field_name] = DynamicResponseGenerator.generate_from_schema(
                    field_schema, operation_id, path
                )
        
        # Generate some optional fields
        for field_name, field_schema in list(properties.items())[:5]:  # Limit to 5 fields
            if field_name not in result:
                result[field_name] = DynamicResponseGenerator.generate_from_schema(
                    field_schema, operation_id, path
                )
        
        # Add common fields based on context
        if "list" in operation_id.lower() or "get" in operation_id.lower():
            if "id" not in result:
                result["id"] = DynamicResponseGenerator._generate_id(path)
        
        # Add timestamps
        if not any(field in result for field in ["created_at", "updated_at", "timestamp"]):
            result["created_at"] = datetime.now().isoformat()
        
        return result
    
    @staticmethod
    def _generate_string_value(schema: Dict, path: str) -> str:
        """Generate string value based on schema and context."""
        # Check for enum values
        enum_values = schema.get("enum", [])
        if enum_values:
            return enum_values[0]
        
        # Check for examples
        example = schema.get("example")
        if example:
            return str(example)
        
        # Generate based on field name context
        path_lower = path.lower()
        
        if "email" in path_lower:
            return "test@example.com"
        elif "name" in path_lower:
            return "Test Name"
        elif "status" in path_lower:
            return "active"
        elif "url" in path_lower:
            return "https://example.com"
        elif "id" in path_lower:
            return "test_id_123"
        else:
            return "sample_value"
    
    @staticmethod
    def _generate_id(path: str) -> Union[int, str]:
        """Generate ID based on path context."""
        path_lower = path.lower()
        
        if "user" in path_lower:
            return 456
        elif "pet" in path_lower:
            return 123  
        elif "order" in path_lower:
            return 789
        else:
            return 1001


class DynamicMockServer:
    """Completely dynamic mock server that works with ANY OpenAPI spec."""
    
    def __init__(
        self,
        spec_file: str,
        host: str = str(RUNTIME_SETTINGS.dynamic_mock_host),
        port: int = int(RUNTIME_SETTINGS.dynamic_mock_port),
    ):
        """Initialize dynamic mock server."""
        self.runtime_settings = get_runtime_settings()
        self.host = host
        self.port = port
        self.spec_file = spec_file
        
        # Load and parse OpenAPI spec
        self.spec = self._load_spec(spec_file)
        self.api_info = self.spec.get("info", {})
        self.paths = self.spec.get("paths", {})
        self.components = self.spec.get("components", {})
        self.security = self.spec.get("security", [])
        
        # Create FastAPI app
        self.app = FastAPI(
            title=self.api_info.get("title", "Dynamic Mock API"),
            description=self.api_info.get("description", "Automatically generated from OpenAPI spec"),
            version=self.api_info.get("version", "1.0.0"),
            docs_url="/docs",
            redoc_url="/redoc"
        )
        
        # Add CORS
        raw_allowed_origins = str(
            os.getenv(
                "QA_MOCK_ALLOWED_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            )
        ).strip()
        allowed_origins = [
            item.strip()
            for item in raw_allowed_origins.split(",")
            if item.strip()
        ] or ["http://localhost:3000", "http://127.0.0.1:3000"]
        allow_credentials = str(
            os.getenv("QA_MOCK_CORS_ALLOW_CREDENTIALS", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}
        if "*" in allowed_origins and allow_credentials:
            allow_credentials = False
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Request logging
        self.request_log = []
        self._chaos_once_seen: set[str] = set()
        self._chaos_concurrency_seen: set[str] = set()
        
        # Setup middleware and routes
        self._setup_middleware()
        self._setup_dynamic_routes()
        
        logger.info(f"🚀 Dynamic Mock Server initialized")
        logger.info(f"📋 API: {self.api_info.get('title', 'Unknown')} v{self.api_info.get('version', '1.0.0')}")
        logger.info(f"📍 Loaded {len(self.paths)} paths with {self._count_operations()} operations")
    
    def _load_spec(self, spec_file: str) -> Dict:
        """Load OpenAPI specification from file."""
        path = Path(spec_file)
        
        if not path.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_file}")
        
        content = path.read_text()
        
        try:
            if spec_file.endswith(('.yaml', '.yml')):
                return yaml.safe_load(content)
            else:
                return json.loads(content)
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid spec file format: {e}")

    def _resolve_local_ref(self, ref: str) -> Any:
        ref_text = str(ref or "").strip()
        if not ref_text.startswith("#/"):
            return None
        node: Any = self.spec
        for token in ref_text[2:].split("/"):
            key = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    def _resolve_refs(self, node: Any, max_depth: int = 12) -> Any:
        if max_depth <= 0:
            return node
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node.get("$ref"), str):
                resolved = self._resolve_local_ref(str(node.get("$ref")))
                if isinstance(resolved, dict):
                    merged = dict(resolved)
                    for key, value in node.items():
                        if key != "$ref":
                            merged[key] = value
                    return self._resolve_refs(merged, max_depth=max_depth - 1)
            return {
                str(key): self._resolve_refs(value, max_depth=max_depth - 1)
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [self._resolve_refs(item, max_depth=max_depth - 1) for item in node]
        return node
    
    def _count_operations(self) -> int:
        """Count total operations across all paths."""
        count = 0
        for path_config in self.paths.values():
            for method in ["get", "post", "put", "patch", "delete", "head", "options"]:
                if method in path_config:
                    count += 1
        return count
    
    def _setup_middleware(self):
        """Setup request logging middleware."""
        @self.app.middleware("http")
        async def log_requests(request: Request, call_next):
            start_time = time.time()
            
            # Log request
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "method": request.method,
                "path": request.url.path,
                "query_params": dict(request.query_params),
                "headers": self._sanitize_headers_for_log(dict(request.headers)),
                "ip": request.client.host if request.client else "unknown"
            }
            
            self.request_log.append(log_entry)
            logger.info(f"📥 {request.method} {request.url.path}")
            
            # Process request
            response = await call_next(request)
            
            # Add timing header
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            
            return response

    def _sanitize_headers_for_log(self, headers: Dict[str, Any]) -> Dict[str, str]:
        sanitized: Dict[str, str] = {}
        for key, value in (headers or {}).items():
            key_text = str(key)
            if key_text.lower() in {"authorization", "cookie", "x-api-key"}:
                sanitized[key_text] = "***"
            else:
                sanitized[key_text] = str(value)
        return sanitized
    
    def _setup_dynamic_routes(self):
        """Dynamically create routes from OpenAPI spec."""
        # Add health check
        @self.app.get("/health")
        async def health_check():
            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "api": self.api_info.get("title", "Unknown API"),
                "version": self.api_info.get("version", "1.0.0"),
                "endpoints": self._count_operations(),
                "requests_handled": len(self.request_log)
            }
        
        # Create routes for each path and method
        for path, path_config in self.paths.items():
            if not isinstance(path_config, dict):
                continue
            path_level_parameters = path_config.get("parameters", [])
            for method, operation in path_config.items():
                if method.upper() in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
                    self._create_dynamic_route(
                        path,
                        method.upper(),
                        operation,
                        path_level_parameters=path_level_parameters,
                    )
        
        logger.info(f"📍 Created {self._count_operations()} dynamic routes")
    
    def _create_dynamic_route(
        self,
        path: str,
        method: str,
        operation: Dict,
        path_level_parameters: Optional[List[Dict]] = None,
    ):
        """Create a single dynamic route."""
        operation = self._resolve_refs(operation if isinstance(operation, dict) else {})
        operation_id = operation.get("operationId", f"{method.lower()}_{path.replace('/', '_').replace('{', '').replace('}', '')}")
        
        async def dynamic_handler(request: Request):
            return await self._handle_dynamic_request(
                request,
                path,
                method,
                operation,
                path_level_parameters=path_level_parameters,
            )
        
        # Register the route with FastAPI
        if method == "GET":
            self.app.add_api_route(path, dynamic_handler, methods=["GET"])
        elif method == "POST":
            self.app.add_api_route(path, dynamic_handler, methods=["POST"])
        elif method == "PUT":
            self.app.add_api_route(path, dynamic_handler, methods=["PUT"])
        elif method == "PATCH":
            self.app.add_api_route(path, dynamic_handler, methods=["PATCH"])
        elif method == "DELETE":
            self.app.add_api_route(path, dynamic_handler, methods=["DELETE"])
        
        logger.info(f"   📌 {method} {path} ({operation_id})")
    
    async def _handle_dynamic_request(
        self,
        request: Request,
        path: str,
        method: str,
        operation: Dict,
        path_level_parameters: Optional[List[Dict]] = None,
    ) -> Any:
        """Handle any dynamic request based on OpenAPI operation."""
        try:
            # Check authentication if required
            await self._check_auth_if_required(request, operation)
            await self._apply_chaos_injection(
                request=request,
                path=path,
                method=method,
                operation=operation,
            )
            
            # Validate path parameters
            path_params = self._extract_path_params(request.url.path, path)
            self._validate_path_params(
                path_params=path_params,
                operation=operation,
                path_level_parameters=path_level_parameters,
            )
            await self._validate_query_params(
                request=request,
                operation=operation,
                path_level_parameters=path_level_parameters,
            )
            
            # Handle special test cases (404s, etc.)
            await self._handle_special_cases(request, path, method, path_params)
            
            # Validate request body for POST/PUT/PATCH
            if method in ["POST", "PUT", "PATCH"]:
                body = await self._validate_request_body(request, operation)
            else:
                body = None
            
            # Generate response
            return await self._generate_dynamic_response(request, path, method, operation, path_params, body)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error in {method} {path}: {e}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    def _chaos_key(self, request: Request, path: str, method: str) -> str:
        explicit_key = str(request.headers.get("x-qa-chaos-key", "")).strip()
        if explicit_key:
            return explicit_key
        query_text = str(request.url.query or "")
        return f"{method}:{path}:{query_text}"

    async def _apply_chaos_injection(
        self,
        *,
        request: Request,
        path: str,
        method: str,
        operation: Dict,
    ) -> None:
        chaos_mode = str(request.headers.get("x-qa-chaos", "")).strip().lower()
        if not chaos_mode:
            return

        key = self._chaos_key(request, path, method)
        once_key = f"{chaos_mode}:{key}"

        if chaos_mode == str(self.runtime_settings.chaos_once_503_mode):
            if once_key not in self._chaos_once_seen:
                self._chaos_once_seen.add(once_key)
                raise HTTPException(status_code=503, detail="Chaos injection: temporary upstream failure")
            return

        if chaos_mode == str(self.runtime_settings.chaos_once_timeout_mode):
            if once_key not in self._chaos_once_seen:
                self._chaos_once_seen.add(once_key)
                # Long enough to trigger client timeout probes.
                await asyncio.sleep(1.25)
            return

        if chaos_mode == str(self.runtime_settings.chaos_concurrency_mode):
            # First request wins, subsequent request with same key conflicts.
            if once_key in self._chaos_concurrency_seen:
                raise HTTPException(status_code=409, detail="Concurrency conflict detected")
            self._chaos_concurrency_seen.add(once_key)
            return

        # Unknown chaos mode: ignore instead of failing user traffic.
        return

    def _collect_operation_parameters(
        self,
        operation: Dict,
        path_level_parameters: Optional[List[Dict]],
    ) -> List[Dict]:
        merged: Dict[tuple, Dict] = {}

        if isinstance(path_level_parameters, list):
            for param in path_level_parameters:
                param = self._resolve_refs(param)
                if not isinstance(param, dict):
                    continue
                location = str(param.get("in", "")).lower()
                name = str(param.get("name", ""))
                if location and name:
                    merged[(location, name)] = param

        operation_params = operation.get("parameters", [])
        if isinstance(operation_params, list):
            for param in operation_params:
                param = self._resolve_refs(param)
                if not isinstance(param, dict):
                    continue
                location = str(param.get("in", "")).lower()
                name = str(param.get("name", ""))
                if location and name:
                    merged[(location, name)] = param

        return list(merged.values())

    def _validate_path_params(
        self,
        *,
        path_params: Dict[str, str],
        operation: Dict,
        path_level_parameters: Optional[List[Dict]] = None,
    ) -> None:
        parameters = self._collect_operation_parameters(operation, path_level_parameters)
        path_specs = [
            p for p in parameters if str((p or {}).get("in", "")).lower() == "path"
        ]
        for param in path_specs:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name", "")).strip()
            if not name:
                continue
            if bool(param.get("required", False)) and name not in path_params:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required path parameter: {name}",
                )
            if name in path_params:
                self._validate_path_param_value(name, str(path_params[name]), param)

    def _validate_path_param_value(self, name: str, raw_value: str, param: Dict) -> None:
        schema = self._resolve_refs(param.get("schema", {}))
        if not isinstance(schema, dict):
            return

        enum_values = schema.get("enum", [])
        if isinstance(enum_values, list) and enum_values:
            allowed = {str(v) for v in enum_values}
            if str(raw_value) not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid value for path parameter '{name}': {raw_value}",
                )

        value_type = str(schema.get("type", "string")).lower()
        if value_type == "integer":
            if re.fullmatch(r"[+-]?\d+", str(raw_value)) is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Path parameter '{name}' must be an integer",
                )
            numeric_value = int(str(raw_value))
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and numeric_value < int(minimum):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path parameter '{name}' must be >= {minimum}",
                )
            if maximum is not None and numeric_value > int(maximum):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path parameter '{name}' must be <= {maximum}",
                )
            return

        if value_type == "number":
            try:
                numeric_value = float(str(raw_value))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Path parameter '{name}' must be numeric",
                )
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and numeric_value < float(minimum):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path parameter '{name}' must be >= {minimum}",
                )
            if maximum is not None and numeric_value > float(maximum):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path parameter '{name}' must be <= {maximum}",
                )
            return

        if value_type == "boolean":
            if str(raw_value).lower() not in {"true", "false", "1", "0"}:
                raise HTTPException(
                    status_code=400,
                    detail=f"Path parameter '{name}' must be boolean",
                )
            return

    async def _validate_query_params(
        self,
        request: Request,
        operation: Dict,
        path_level_parameters: Optional[List[Dict]] = None,
    ) -> None:
        parameters = self._collect_operation_parameters(operation, path_level_parameters)
        query_specs = [
            p for p in parameters if str((p or {}).get("in", "")).lower() == "query"
        ]
        query_spec_map = {
            str((p or {}).get("name", "")): p
            for p in query_specs
            if str((p or {}).get("name", ""))
        }
        security_query_params = self._allowed_security_query_params(operation)
        allowed_query_names = set(query_spec_map.keys()) | set(security_query_params)
        incoming = dict(request.query_params)

        if incoming and not allowed_query_names:
            unknown = ", ".join(sorted(incoming.keys())[:5])
            raise HTTPException(
                status_code=400,
                detail=f"Unexpected query parameter(s): {unknown}",
            )

        for name in incoming.keys():
            if name not in allowed_query_names:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unexpected query parameter: {name}",
                )

        for name, param in query_spec_map.items():
            if bool(param.get("required", False)) and name not in incoming:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required query parameter: {name}",
                )
            if name in incoming:
                self._validate_query_param_value(name, incoming[name], param)

    def _allowed_security_query_params(self, operation: Dict[str, Any]) -> set[str]:
        security = operation.get("security", self.security)
        if not security:
            return set()
        requirements = security if isinstance(security, list) else [security]
        schemes = self._security_schemes()
        names: set[str] = set()
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            for scheme_name in requirement.keys():
                payload = schemes.get(str(scheme_name), {})
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("type", "")).strip().lower() != "apikey":
                    continue
                if str(payload.get("in", "")).strip().lower() != "query":
                    continue
                name = str(payload.get("name", "")).strip()
                if name:
                    names.add(name)
        return names

    def _validate_query_param_value(self, name: str, raw_value: str, param: Dict) -> None:
        schema = self._resolve_refs(param.get("schema", {}))
        if not isinstance(schema, dict):
            return

        enum_values = schema.get("enum", [])
        if isinstance(enum_values, list) and enum_values:
            allowed = {str(v) for v in enum_values}
            if str(raw_value) not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid value for query parameter '{name}': {raw_value}",
                )

        value_type = str(schema.get("type", "string")).lower()
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        exclusive_maximum = schema.get("exclusiveMaximum")

        if value_type == "integer":
            try:
                parsed = int(str(raw_value))
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Query parameter '{name}' must be an integer",
                )
            self._validate_numeric_boundaries(
                name,
                parsed,
                minimum,
                maximum,
                exclusive_minimum,
                exclusive_maximum,
            )
            return

        if value_type == "number":
            try:
                parsed = float(str(raw_value))
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Query parameter '{name}' must be a number",
                )
            self._validate_numeric_boundaries(
                name,
                parsed,
                minimum,
                maximum,
                exclusive_minimum,
                exclusive_maximum,
            )
            return

        if value_type == "boolean":
            if str(raw_value).lower() not in {"true", "false", "1", "0"}:
                raise HTTPException(
                    status_code=400,
                    detail=f"Query parameter '{name}' must be a boolean",
                )
            return

        if value_type == "string":
            text = str(raw_value)
            min_length = schema.get("minLength")
            max_length = schema.get("maxLength")
            if min_length is not None and len(text) < int(min_length):
                raise HTTPException(
                    status_code=400,
                    detail=f"Query parameter '{name}' is shorter than minLength={min_length}",
                )
            if max_length is not None and len(text) > int(max_length):
                raise HTTPException(
                    status_code=400,
                    detail=f"Query parameter '{name}' is longer than maxLength={max_length}",
                )
            return

    def _validate_numeric_boundaries(
        self,
        name: str,
        value: Union[int, float],
        minimum: Any,
        maximum: Any,
        exclusive_minimum: Any,
        exclusive_maximum: Any,
    ) -> None:
        if minimum is not None and value < float(minimum):
            raise HTTPException(
                status_code=400,
                detail=f"Query parameter '{name}' must be >= {minimum}",
            )
        if maximum is not None and value > float(maximum):
            raise HTTPException(
                status_code=400,
                detail=f"Query parameter '{name}' must be <= {maximum}",
            )
        if isinstance(exclusive_minimum, (int, float)):
            if value <= float(exclusive_minimum):
                raise HTTPException(
                    status_code=400,
                    detail=f"Query parameter '{name}' must be > {exclusive_minimum}",
                )
        elif exclusive_minimum is True and minimum is not None and value <= float(minimum):
            raise HTTPException(
                status_code=400,
                detail=f"Query parameter '{name}' must be > {minimum}",
            )
        if isinstance(exclusive_maximum, (int, float)):
            if value >= float(exclusive_maximum):
                raise HTTPException(
                    status_code=400,
                    detail=f"Query parameter '{name}' must be < {exclusive_maximum}",
                )
        elif exclusive_maximum is True and maximum is not None and value >= float(maximum):
            raise HTTPException(
                status_code=400,
                detail=f"Query parameter '{name}' must be < {maximum}",
            )

    def _security_schemes(self) -> Dict[str, Any]:
        components = self.components if isinstance(self.components, dict) else {}
        schemes = components.get("securitySchemes", {})
        return schemes if isinstance(schemes, dict) else {}

    def _credential_looks_invalid(self, value: str) -> bool:
        token = str(value or "").strip().lower()
        if not token:
            return True
        invalid_markers = {
            str(self.runtime_settings.auth_token_invalid).strip().lower(),
            str(self.runtime_settings.auth_token_expired).strip().lower(),
            str(os.getenv("QA_AUTH_API_KEY_INVALID_VALUE", "invalid_api_key")).strip().lower(),
            "invalid",
            "expired",
        }
        return any(marker and marker in token for marker in invalid_markers)

    def _request_satisfies_security_scheme(
        self, request: Request, scheme_name: str, scheme: Dict[str, Any]
    ) -> bool:
        payload = scheme if isinstance(scheme, dict) else {}
        scheme_type = str(payload.get("type", "")).strip().lower()

        if scheme_type == "http" and str(payload.get("scheme", "")).strip().lower() == "bearer":
            auth_header = str(request.headers.get("authorization", "")).strip()
            if not auth_header.lower().startswith("bearer "):
                return False
            token = auth_header.split(" ", 1)[1] if " " in auth_header else ""
            return not self._credential_looks_invalid(token)

        if scheme_type == "apikey":
            key_name = str(payload.get("name", "")).strip() or "X-API-Key"
            key_in = str(payload.get("in", "header")).strip().lower() or "header"
            credential = ""
            if key_in == "query":
                credential = str(request.query_params.get(key_name, "")).strip()
            elif key_in == "cookie":
                credential = str(request.cookies.get(key_name, "")).strip()
            else:
                credential = str(request.headers.get(key_name, "")).strip()
            return not self._credential_looks_invalid(credential)

        # Fallback: accept bearer-style credential for unknown schemes.
        auth_header = str(request.headers.get("authorization", "")).strip()
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1] if " " in auth_header else ""
            return not self._credential_looks_invalid(token)
        fallback = str(request.headers.get(str(scheme_name), "")).strip()
        return not self._credential_looks_invalid(fallback)

    async def _check_auth_if_required(self, request: Request, operation: Dict):
        """Check authentication if required by operation."""
        security = operation.get("security", self.security)
        if security is None:
            return
        if not security:
            return

        requirements = security if isinstance(security, list) else [security]
        schemes = self._security_schemes()
        for requirement in requirements:
            if requirement in ({}, None):
                return
            if not isinstance(requirement, dict) or not requirement:
                continue
            requirement_ok = True
            for scheme_name in requirement.keys():
                scheme_payload = schemes.get(str(scheme_name), {})
                if not self._request_satisfies_security_scheme(
                    request=request,
                    scheme_name=str(scheme_name),
                    scheme=scheme_payload if isinstance(scheme_payload, dict) else {},
                ):
                    requirement_ok = False
                    break
            if requirement_ok:
                return

        raise HTTPException(status_code=401, detail="Missing or invalid authentication credentials")
    
    def _extract_path_params(self, request_path: str, spec_path: str) -> Dict[str, str]:
        """Extract path parameters from request URL."""
        # Convert spec path to regex
        path_regex = spec_path
        param_names = []
        
        # Find all parameters {param}
        for match in re.finditer(r'\{([^}]+)\}', spec_path):
            param_name = match.group(1)
            param_names.append(param_name)
            path_regex = path_regex.replace(f'{{{param_name}}}', r'([^/]+)')
        
        # Match against request path
        match = re.match(f'^{path_regex}$', request_path)
        if match and param_names:
            return dict(zip(param_names, match.groups()))
        
        return {}
    
    async def _handle_special_cases(self, request: Request, path: str, method: str, path_params: Dict):
        """Handle special test cases for specific parameter values."""
        auth_header = str(request.headers.get("authorization", "")).strip()
        tenant_header = str(request.headers.get("x-tenant-id", "")).strip().lower()

        if auth_header.lower().startswith("bearer ") and tenant_header in {
            "unauthorized_tenant",
            "other_tenant",
            "cross_tenant",
            "tenant_b",
        }:
            raise HTTPException(status_code=403, detail="Cross-tenant access is forbidden")

        # BOLA-style probe: valid token with a cross-tenant/forbidden resource id.
        for param_name, param_value in path_params.items():
            value_text = str(param_value).strip().lower()
            if any(marker in value_text for marker in ("other_tenant", "cross_tenant", "forbidden")):
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied for resource identifier: {param_name}",
                )

        # Simulate 404 for specific test values
        for param_name, param_value in path_params.items():
            value = str(param_value).strip()
            value_lower = value.lower()
            contains_not_found_token = any(
                token in value_lower
                for token in ("nonexistent", "notfound", "missing", "invalid")
            )
            is_not_found_token = value_lower in {
                "999",
                "9999",
                "99999",
                "999999",
                "nonexistent",
                "invalid",
                "notfound",
            }
            is_high_nines_id = bool(re.fullmatch(r"9{3,}", value))
            if is_not_found_token or is_high_nines_id or contains_not_found_token:
                resource_name = param_name.replace("Id", "").replace("_id", "")
                raise HTTPException(
                    status_code=404,
                    detail=f"{resource_name.title()} not found: {param_value}"
                )
            # For unconstrained order IDs in mock mode, map invalid/suspicious IDs
            # to deterministic not-found behavior rather than returning 200.
            if str(param_name).lower() in {"orderid", "order_id"}:
                has_disallowed_chars = re.fullmatch(r"[A-Za-z0-9_-]+", value) is None
                is_excessive_length = len(value) > 32
                if has_disallowed_chars or is_excessive_length:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Order not found: {param_value}",
                    )
        
        # Simulate conflict for POST with specific values
        if method == "POST":
            body = None
            try:
                body = await request.json()
            except Exception:
                body = None
            if isinstance(body, dict) and body.get("name") == "duplicate":
                raise HTTPException(status_code=409, detail="Resource already exists")
    
    async def _validate_request_body(self, request: Request, operation: Dict) -> Optional[Dict]:
        """Validate request body against OpenAPI schema."""
        request_body_spec = self._resolve_refs(operation.get("requestBody", {}))
        if not request_body_spec:
            return None
        
        # Get JSON content type schema
        content = request_body_spec.get("content", {})
        json_content = content.get("application/json", {})
        schema = self._resolve_refs(json_content.get("schema", {}))
        
        if not schema:
            return None
        
        try:
            body = await request.json()
        except:
            raise HTTPException(status_code=400, detail="Invalid JSON in request body")

        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")
        
        # Basic validation - check required fields
        required = schema.get("required", [])
        for field in required:
            if field not in body or body[field] is None or body[field] == "":
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

        # Validate known schema properties with lightweight OpenAPI checks.
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for field_name, field_schema in properties.items():
                if field_name not in body:
                    continue
                self._validate_request_body_field(
                    field_name=str(field_name),
                    value=body[field_name],
                    schema=(
                        self._resolve_refs(field_schema)
                        if isinstance(field_schema, dict)
                        else {}
                    ),
                )
        
        return body

    def _validate_request_body_field(self, field_name: str, value: Any, schema: Dict[str, Any]) -> None:
        """Apply common OpenAPI constraints for request body fields."""
        if not isinstance(schema, dict):
            return

        schema_type = str(schema.get("type", "")).lower()
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values and value not in enum_values:
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field_name}' must be one of {enum_values}",
            )

        if schema_type == "string":
            if not isinstance(value, str):
                raise HTTPException(status_code=400, detail=f"Field '{field_name}' must be a string")
            normalized_value = value.strip()
            field_format = str(schema.get("format", "") or "").strip().lower()
            field_name_lower = str(field_name or "").strip().lower()
            # Many customer specs omit `format: email`; fallback to field-name intent.
            if field_format == "email" or "email" in field_name_lower:
                if EMAIL_PATTERN.fullmatch(normalized_value) is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Field '{field_name}' must be a valid email address",
                    )
            if SQLI_PATTERN.search(value):
                raise HTTPException(
                    status_code=400,
                    detail=f"Potentially unsafe input detected for field '{field_name}'",
                )
            url_text = value.strip().lower()
            ssrf_host = (
                urlparse(str(self.runtime_settings.ssrf_probe_url)).hostname or ""
            ).strip().lower()
            if url_text.startswith(("http://", "https://", "file://", "gopher://")):
                ssrf_markers = [
                    marker
                    for marker in (
                        ssrf_host,
                        "169.254.169.254",
                        "metadata.google.internal",
                        "127.0.0.1",
                        "localhost",
                        "0.0.0.0",
                        "::1",
                        "kubernetes.default",
                        ".internal",
                    )
                    if str(marker).strip()
                ]
                if any(
                    marker in url_text
                    for marker in ssrf_markers
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Potential SSRF payload rejected for field '{field_name}'",
                    )
            min_length = schema.get("minLength")
            max_length = schema.get("maxLength")
            if isinstance(min_length, int) and len(value) < min_length:
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field_name}' is shorter than minLength={min_length}",
                )
            if isinstance(max_length, int) and len(value) > max_length:
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field_name}' exceeds maxLength={max_length}",
                )
            pattern = schema.get("pattern")
            if isinstance(pattern, str):
                try:
                    if re.fullmatch(pattern, value) is None:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Field '{field_name}' does not match required pattern",
                        )
                except re.error:
                    pass
            return

        if schema_type == "integer":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise HTTPException(status_code=400, detail=f"Field '{field_name}' must be an integer")
            if isinstance(value, float) and not value.is_integer():
                raise HTTPException(status_code=400, detail=f"Field '{field_name}' must be an integer")
            self._validate_request_body_numeric_bounds(
                field_name=field_name,
                value=float(value),
                schema=schema,
            )
            return

        if schema_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise HTTPException(status_code=400, detail=f"Field '{field_name}' must be a number")
            self._validate_request_body_numeric_bounds(
                field_name=field_name,
                value=float(value),
                schema=schema,
            )
            return

        if schema_type == "boolean":
            if not isinstance(value, bool):
                raise HTTPException(status_code=400, detail=f"Field '{field_name}' must be a boolean")
            return

        if schema_type == "array":
            if not isinstance(value, list):
                raise HTTPException(status_code=400, detail=f"Field '{field_name}' must be an array")
            min_items = schema.get("minItems")
            max_items = schema.get("maxItems")
            if isinstance(min_items, int) and len(value) < min_items:
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field_name}' must contain at least {min_items} item(s)",
                )
            if isinstance(max_items, int) and len(value) > max_items:
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field_name}' must contain at most {max_items} item(s)",
                )
            return

        if schema_type == "object" and not isinstance(value, dict):
            raise HTTPException(status_code=400, detail=f"Field '{field_name}' must be an object")

    def _validate_request_body_numeric_bounds(
        self,
        *,
        field_name: str,
        value: float,
        schema: Dict[str, Any],
    ) -> None:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        exclusive_maximum = schema.get("exclusiveMaximum")

        if minimum is not None and value < float(minimum):
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field_name}' must be >= {minimum}",
            )
        if maximum is not None and value > float(maximum):
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field_name}' must be <= {maximum}",
            )
        if isinstance(exclusive_minimum, (int, float)):
            if value <= float(exclusive_minimum):
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field_name}' must be > {exclusive_minimum}",
                )
        elif exclusive_minimum is True and minimum is not None and value <= float(minimum):
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field_name}' must be > {minimum}",
            )
        if isinstance(exclusive_maximum, (int, float)):
            if value >= float(exclusive_maximum):
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field_name}' must be < {exclusive_maximum}",
                )
        elif exclusive_maximum is True and maximum is not None and value >= float(maximum):
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field_name}' must be < {maximum}",
            )
    
    async def _generate_dynamic_response(
        self, 
        request: Request, 
        path: str, 
        method: str, 
        operation: Dict, 
        path_params: Dict,
        body: Optional[Dict]
    ) -> Any:
        """Generate response dynamically based on operation definition."""
        responses = self._resolve_refs(operation.get("responses", {}))

        # Determine success status code from documented operation responses.
        success_code = self._pick_success_status_code(method=method, responses=responses)
        success_status = int(success_code)
        
        # Get success response schema
        success_response = self._resolve_refs(
            responses.get(success_code, responses.get("200", {}))
        )
        content = success_response.get("content", {})
        json_content = content.get("application/json", {})
        schema = self._resolve_refs(json_content.get("schema", {}))
        
        # Generate response data
        if schema:
            response_data = DynamicResponseGenerator.generate_from_schema(
                schema, 
                operation.get("operationId", ""),
                path
            )
        else:
            # Fallback response
            response_data = self._generate_fallback_response(method, path, path_params, body)
        
        # Add path parameters to response
        for param_name, param_value in path_params.items():
            if param_name.endswith("Id") or param_name.endswith("_id"):
                if isinstance(response_data, dict):
                    id_field = param_name if param_name in response_data else "id"
                    existing_value = response_data.get(id_field)
                    # Preserve schema-generated response types when possible.
                    if isinstance(existing_value, str):
                        response_data[id_field] = str(param_value)
                    elif isinstance(existing_value, int) and str(param_value).isdigit():
                        response_data[id_field] = int(param_value)
                    elif isinstance(existing_value, float):
                        try:
                            response_data[id_field] = float(param_value)
                        except Exception:
                            response_data[id_field] = existing_value
                    else:
                        response_data[id_field] = param_value

        if success_status in {204, 205, 304}:
            return Response(status_code=success_status)
        return JSONResponse(status_code=success_status, content=response_data)

    def _pick_success_status_code(self, *, method: str, responses: Dict[str, Any]) -> str:
        documented_success: List[int] = []
        if isinstance(responses, dict):
            for raw_code in responses.keys():
                code_text = str(raw_code).strip()
                if not code_text.isdigit():
                    continue
                code_int = int(code_text)
                if 200 <= code_int < 300:
                    documented_success.append(code_int)
        if documented_success:
            ordered_unique = sorted(set(documented_success))
            preferred_map = {
                "POST": [201, 200, 202, 204],
                "DELETE": [204, 200, 202],
                "PUT": [200, 201, 202, 204],
                "PATCH": [200, 204, 202],
                "GET": [200, 206, 204],
            }
            preferred = preferred_map.get(str(method).upper(), [200, 201, 202, 204])
            for code in preferred:
                if code in ordered_unique:
                    return str(code)
            return str(ordered_unique[0])
        if str(method).upper() == "POST":
            return "201"
        if str(method).upper() == "DELETE":
            return "204"
        return "200"

    def _generate_fallback_response(self, method: str, path: str, path_params: Dict, body: Optional[Dict]) -> Dict:
        """Generate fallback response when no schema is available."""
        base_response = {
            "message": f"{method} {path} executed successfully",
            "timestamp": datetime.now().isoformat()
        }
        
        # Add path params
        if path_params:
            base_response.update(path_params)
        
        # For list endpoints, return array
        if method == "GET" and not path_params:
            resource_name = path.strip("/").split("/")[0]
            base_response = {
                resource_name: [
                    {"id": 1, "name": "Sample Item 1"},
                    {"id": 2, "name": "Sample Item 2"}
                ],
                "total": 2,
                "page": 1
            }
        
        # For POST/PUT, echo back the body with an ID
        if method in ["POST", "PUT"] and body:
            base_response = {
                "id": 1001,
                **body,
                "message": f"Resource {method.lower()}ed successfully"
            }
        
        return base_response
    
    def run(self, debug: bool = True):
        """Start the dynamic mock server."""
        print(f"\n{'='*70}")
        print(f"🚀 Dynamic Mock API Server")
        print(f"{'='*70}")
        print(f"📋 API: {self.api_info.get('title', 'Unknown API')} v{self.api_info.get('version', '1.0.0')}")
        print(f"📁 Spec: {self.spec_file}")
        print(f"🌐 URL: http://{self.host}:{self.port}")
        print(f"📖 Docs: http://{self.host}:{self.port}/docs")
        print(f"📊 Endpoints: {self._count_operations()} operations across {len(self.paths)} paths")
        
        # Show all endpoints
        print(f"\n📍 Available Endpoints:")
        for path, path_config in self.paths.items():
            methods = []
            for method in ["get", "post", "put", "patch", "delete"]:
                if method in path_config:
                    methods.append(method.upper())
            if methods:
                print(f"   {', '.join(methods)} {path}")
        
        print(f"\n🧪 Authentication: Bearer tokens (any token except 'invalid')")
        print(f"🔧 Special test values: '999'/'nonexistent' → 404, 'duplicate' → 409")
        print(
            "🔧 Chaos headers: X-QA-Chaos="
            + f"{self.runtime_settings.chaos_once_503_mode}|"
            + f"{self.runtime_settings.chaos_once_timeout_mode}|"
            + f"{self.runtime_settings.chaos_concurrency_mode}"
        )
        print(f"🔧 Security probes: X-Tenant-Id=unauthorized_tenant → 403, SSRF-style URL fields → 400")
        print(f"{'='*70}\n")
        
        try:
            uvicorn.run(
                self.app,
                host=self.host,
                port=self.port,
                log_level="info" if debug else "warning"
            )
        except KeyboardInterrupt:
            logger.info("🛑 Server stopped by user")


def main():
    """CLI interface for dynamic mock server."""
    parser = argparse.ArgumentParser(
        description="Dynamic Mock API Server - Works with ANY OpenAPI spec",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Pet Store API
    python dynamic_mock_server.py --spec sample_api.yaml --port 8000
    
    # Custom API
    python dynamic_mock_server.py --spec customer_api.yaml --port 9000
    
    # Banking API  
    python dynamic_mock_server.py --spec banking_api.yaml --port 8080
        """
    )
    
    parser.add_argument("--spec", "-s", required=True,
                       help="OpenAPI specification file (YAML or JSON)")
    parser.add_argument("--host", default=str(RUNTIME_SETTINGS.dynamic_mock_host),
                       help=f"Server host (default: {RUNTIME_SETTINGS.dynamic_mock_host})")
    parser.add_argument("--port", "-p", type=int, default=int(RUNTIME_SETTINGS.dynamic_mock_port),
                       help=f"Server port (default: {RUNTIME_SETTINGS.dynamic_mock_port})")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug mode")
    
    args = parser.parse_args()
    
    try:
        # Create and start dynamic server
        server = DynamicMockServer(args.spec, args.host, args.port)
        server.run(debug=args.debug)
        
    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("💡 Make sure the OpenAPI spec file exists")
    except ValueError as e:
        print(f"❌ {e}")
        print("💡 Check that the spec file is valid YAML or JSON")
    except Exception as e:
        print(f"❌ Failed to start server: {e}")


if __name__ == "__main__":
    main()
