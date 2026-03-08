"""Regression tests for strict dynamic mock server validation behavior."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from dynamic_mock_server import DynamicMockServer


def _write_spec(path: Path, spec: dict) -> None:
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")


def test_post_duplicate_name_returns_conflict(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Products API", "version": "1.0.0"},
            "paths": {
                "/products": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["name"],
                                        "properties": {"name": {"type": "string"}},
                                    }
                                }
                            },
                        },
                        "responses": {"201": {"description": "created"}},
                    }
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        response = client.post("/products", json={"name": "duplicate"})
    assert response.status_code == 409


def test_api_key_header_security_is_enforced(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Header API Key API", "version": "1.0.0"},
            "paths": {
                "/secure/orders": {
                    "get": {
                        "security": [{"apiKeyAuth": []}],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
            "components": {
                "securitySchemes": {
                    "apiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        missing = client.get("/secure/orders")
        invalid = client.get("/secure/orders", headers={"X-API-Key": "invalid_key"})
        valid = client.get("/secure/orders", headers={"X-API-Key": "live_key_123"})
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200


def test_api_key_query_security_is_enforced(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Query API Key API", "version": "1.0.0"},
            "paths": {
                "/secure/search": {
                    "get": {
                        "security": [{"apiKeyQuery": []}],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
            "components": {
                "securitySchemes": {
                    "apiKeyQuery": {"type": "apiKey", "in": "query", "name": "api_key"}
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        missing = client.get("/secure/search")
        invalid = client.get("/secure/search?api_key=invalid_key")
        valid = client.get("/secure/search?api_key=query_live_123")
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200


def test_integer_path_param_rejects_string(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Orders API", "version": "1.0.0"},
            "paths": {
                "/orders/{orderId}": {
                    "parameters": [
                        {
                            "in": "path",
                            "name": "orderId",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "get": {"responses": {"200": {"description": "ok"}}},
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        response = client.get("/orders/not-a-number")
    assert response.status_code == 400


def test_ref_request_body_validation_is_enforced(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Ref API", "version": "1.0.0"},
            "paths": {
                "/resources": {
                    "post": {
                        "requestBody": {"$ref": "#/components/requestBodies/CreateResourceBody"},
                        "responses": {"201": {"description": "created"}},
                    }
                }
            },
            "components": {
                "requestBodies": {
                    "CreateResourceBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {"name": {"type": "string"}},
                                }
                            }
                        },
                    }
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        response = client.post("/resources", json={})
    assert response.status_code == 400


def test_post_rejects_sqli_like_name_payload(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Products API", "version": "1.0.0"},
            "paths": {
                "/products": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["name", "price"],
                                        "properties": {
                                            "name": {"type": "string"},
                                            "price": {"type": "number"},
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {"201": {"description": "created"}, "400": {"description": "bad request"}},
                    }
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        response = client.post(
            "/products",
            json={"name": "Product'; DROP TABLE products;--", "price": 10},
        )
    assert response.status_code == 400
    assert "unsafe input" in str(response.text).lower()


def test_unconstrained_order_id_invalid_or_long_returns_not_found(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Orders API", "version": "1.0.0"},
            "paths": {
                "/orders/{orderId}": {
                    "parameters": [
                        {
                            "in": "path",
                            "name": "orderId",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "get": {
                        "responses": {
                            "200": {"description": "ok"},
                            "404": {"description": "not found"},
                        }
                    },
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        invalid = client.get("/orders/!nv@l!d")
        too_long = client.get("/orders/a1234567890123456789012345678901234567890")
    assert invalid.status_code == 404
    assert too_long.status_code == 404


def test_delete_uses_documented_success_status_200_when_available(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Delete API", "version": "1.0.0"},
            "paths": {
                "/items/{itemId}": {
                    "parameters": [
                        {
                            "in": "path",
                            "name": "itemId",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "delete": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"ok": {"type": "boolean"}},
                                        }
                                    }
                                },
                            },
                            "404": {"description": "not found"},
                        }
                    },
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        response = client.delete("/items/abc123")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)


def test_delete_204_returns_empty_body(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(
        spec_path,
        {
            "openapi": "3.0.3",
            "info": {"title": "Delete No Content API", "version": "1.0.0"},
            "paths": {
                "/items/{itemId}": {
                    "parameters": [
                        {
                            "in": "path",
                            "name": "itemId",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "delete": {
                        "responses": {
                            "204": {"description": "no content"},
                        }
                    },
                }
            },
        },
    )
    app = DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app
    with TestClient(app) as client:
        response = client.delete("/items/abc123")
    assert response.status_code == 204
    assert str(response.text or "").strip() == ""
