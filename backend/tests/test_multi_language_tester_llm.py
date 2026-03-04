import json

import pytest

from spec_test_pilot.multi_language_tester import (
    HumanTesterSimulator,
    MultiLanguageTestGenerator,
    TestScenario as Scenario,
    TestType as ScenarioType,
)


@pytest.fixture
def auth_spec():
    return {
        "openapi": "3.0.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "security": [{"bearerAuth": []}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"}
            }
        },
        "paths": {
            "/orders": {
                "get": {
                    "responses": {"200": {"description": "ok"}, "401": {"description": "unauthorized"}},
                }
            }
        },
    }


def test_prompt_generation_falls_back_to_heuristic_when_llm_disabled(monkeypatch, auth_spec):
    monkeypatch.setenv("QA_SCENARIO_LLM_MODE", "off")
    sim = HumanTesterSimulator(auth_spec, "http://localhost:8000")

    scenarios = sim.think_like_tester("Generate authentication checks for this API")

    assert sim.llm_enabled is False
    assert sim.last_generation_engine in {
        "heuristic_prompt_mode",
        "heuristic_prompt_to_default",
        "heuristic_default",
    }
    assert isinstance(scenarios, list)
    assert len(scenarios) > 0


def test_python_script_generation_uses_python_literals_not_json_null():
    scenario = Scenario(
        name="test_post__orders_no_auth_rl_learned_below_min_quantity",
        description="Boundary check with optional payload field",
        test_type=ScenarioType.BOUNDARY_TESTING,
        endpoint="/orders",
        method="POST",
        headers={"Authorization": "Bearer invalid"},
        params={"_rl_case": "learned_below_min_quantity"},
        body={"productId": "prod_123", "quantity": None},
        expected_status=400,
    )
    generator = MultiLanguageTestGenerator([scenario], "http://127.0.0.1:8000")

    code = generator.generate_python_tests()

    assert " = null" not in code
    assert "None" in code


def test_python_script_generation_renders_path_params_into_endpoint():
    scenario = Scenario(
        name="test_get_order_by_id",
        description="Path parameter should be rendered into URL path",
        test_type=ScenarioType.HAPPY_PATH,
        endpoint="/orders/{orderId}",
        method="GET",
        params={"orderId": "ord_42", "expand": "items"},
        expected_status=200,
    )
    generator = MultiLanguageTestGenerator([scenario], "http://127.0.0.1:8000")

    code = generator.generate_python_tests()

    assert 'url = BASE_URL + "/orders/ord_42"' in code
    assert "params = {'expand': 'items'}" in code
    assert "orderId" not in code.split("params = ", 1)[1].splitlines()[0]


def test_happy_path_body_generation_uses_request_schema_required_fields():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "paths": {
            "/orders": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["productId", "quantity"],
                                    "properties": {
                                        "productId": {"type": "string"},
                                        "quantity": {"type": "integer", "minimum": 1},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                }
            }
        },
    }
    sim = HumanTesterSimulator(spec, "http://localhost:8000")
    endpoint = next(item for item in sim.endpoints if item.path == "/orders" and item.method == "POST")

    scenario = sim._create_happy_path_tests(endpoint)[0]
    assert isinstance(scenario.body, dict)
    assert scenario.body.get("productId")
    assert int(scenario.body.get("quantity")) >= 1


def test_llm_scenarios_accept_non_default_json_keys_and_operation_hints(monkeypatch):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "paths": {
            "/orders/{orderId}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/orders": {
                "post": {
                    "responses": {"201": {"description": "created"}},
                }
            },
        },
    }

    monkeypatch.setenv("QA_SCENARIO_LLM_MODE", "off")
    sim = HumanTesterSimulator(spec, "http://localhost:8000")

    content = (
        '{'
        '"tests": ['
        '{"name":"llm_get_order","operation":"GET /orders/{order_id}","test_type":"happy_path","expected_status":200},'
        '{"name":"llm_post_order","method":"POST","url":"http://localhost:8000/orders","type":"happy_path","expected_status":201,'
        '"payload":{"productId":"p1","quantity":1}}'
        "]}"
    )

    class _FakeCompletions:
        def __init__(self, payload: str):
            self.payload = payload

        def create(self, **kwargs):
            message = type("Message", (), {"content": self.payload})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeClient:
        def __init__(self, payload: str):
            self.chat = type("Chat", (), {"completions": _FakeCompletions(payload)})()

    sim._llm_client = _FakeClient(content)
    sim.llm_enabled = True

    scenarios = sim._generate_from_nlp_prompt_llm("Generate comprehensive QA tests")

    assert len(scenarios) >= 2
    endpoints = {scenario.endpoint for scenario in scenarios}
    assert "/orders/{orderId}" in endpoints
    assert "/orders" in endpoints
    assert sim.llm_stats.get("scenario_success", 0) >= 1


def test_llm_request_prefers_json_schema_then_falls_back_to_json_object(monkeypatch):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "paths": {
            "/orders/{orderId}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }

    monkeypatch.setenv("QA_SCENARIO_LLM_MODE", "off")
    sim = HumanTesterSimulator(spec, "http://localhost:8000")

    call_modes = []

    class _FakeCompletions:
        def create(self, **kwargs):
            response_format = kwargs.get("response_format", {})
            mode = str(response_format.get("type", "plain"))
            call_modes.append(mode)
            if mode == "json_schema":
                raise RuntimeError("json_schema unsupported")
            message = type(
                "Message",
                (),
                {
                    "content": (
                        '{"scenarios":[{"name":"llm_get_order","method":"GET","endpoint":"/orders/{orderId}",'
                        '"test_type":"happy_path","expected_status":200}]}'
                    )
                },
            )()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": _FakeCompletions()})()

    sim._llm_client = _FakeClient()
    sim.llm_enabled = True

    scenarios = sim._generate_from_nlp_prompt_llm("Generate comprehensive QA tests")

    assert len(scenarios) >= 1
    assert call_modes[:2] == ["json_schema", "json_object"]
    assert sim.llm_stats.get("scenario_success", 0) >= 1
    assert sim.last_llm_generation_diagnostics.get("status") == "accepted"
    assert sim.last_llm_generation_diagnostics.get("response_mode") == "json_object"


def test_llm_request_json_schema_payload_uses_non_strict_items(monkeypatch):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "paths": {
            "/orders/{orderId}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }

    monkeypatch.setenv("QA_SCENARIO_LLM_MODE", "off")
    sim = HumanTesterSimulator(spec, "http://localhost:8000")

    captured = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            response_format = kwargs.get("response_format", {})
            if str(response_format.get("type", "")) == "json_schema":
                captured["response_format"] = response_format
            message = type(
                "Message",
                (),
                {
                    "content": (
                        '{"scenarios":[{"name":"llm_get_order","method":"GET","endpoint":"/orders/{orderId}",'
                        '"test_type":"happy_path","expected_status":200}]}'
                    )
                },
            )()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": _FakeCompletions()})()

    sim._llm_client = _FakeClient()
    sim.llm_enabled = True

    scenarios = sim._generate_from_nlp_prompt_llm("Generate comprehensive QA tests")

    assert len(scenarios) >= 1
    schema_payload = captured.get("response_format", {}).get("json_schema", {})
    assert schema_payload.get("strict") is False
    scenario_items = (
        schema_payload.get("schema", {})
        .get("properties", {})
        .get("scenarios", {})
        .get("items", {})
    )
    assert scenario_items.get("additionalProperties") is False


def test_llm_parser_recovers_trailing_commas_payload(monkeypatch):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "paths": {
            "/orders/{orderId}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }

    monkeypatch.setenv("QA_SCENARIO_LLM_MODE", "off")
    sim = HumanTesterSimulator(spec, "http://localhost:8000")

    content = (
        "{\n"
        '  "scenarios": [\n'
        '    {"name":"llm_get_order","method":"GET","endpoint":"/orders/{orderId}",'
        '"test_type":"happy_path","expected_status":200,},\n'
        "  ],\n"
        "}\n"
    )

    class _FakeCompletions:
        def __init__(self, payload: str):
            self.payload = payload

        def create(self, **kwargs):
            message = type("Message", (), {"content": self.payload})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeClient:
        def __init__(self, payload: str):
            self.chat = type("Chat", (), {"completions": _FakeCompletions(payload)})()

    sim._llm_client = _FakeClient(content)
    sim.llm_enabled = True

    scenarios = sim._generate_from_nlp_prompt_llm("Generate comprehensive QA tests")

    assert len(scenarios) >= 1
    assert scenarios[0].endpoint == "/orders/{orderId}"
    assert sim.llm_stats.get("scenario_success", 0) >= 1


def test_llm_parser_recovers_truncated_payload(monkeypatch):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "paths": {
            "/orders/{orderId}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }

    monkeypatch.setenv("QA_SCENARIO_LLM_MODE", "off")
    sim = HumanTesterSimulator(spec, "http://localhost:8000")

    # Simulates a completion cut near EOF after ":" in the final object.
    content = (
        "{\n"
        '  "scenarios": [\n'
        '    {"name":"llm_get_order","method":"GET","endpoint":"/orders/{orderId}",'
        '"test_type":"happy_path","expected_status":200},\n'
        '    {"name":"llm_get_order_2","method":"GET","endpoint":"/orders/{orderId}",'
        '"test_type":"happy_path","expected_status":200,"body":\n'
    )

    class _FakeCompletions:
        def __init__(self, payload: str):
            self.payload = payload

        def create(self, **kwargs):
            message = type("Message", (), {"content": self.payload})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeClient:
        def __init__(self, payload: str):
            self.chat = type("Chat", (), {"completions": _FakeCompletions(payload)})()

    sim._llm_client = _FakeClient(content)
    sim.llm_enabled = True

    scenarios = sim._generate_from_nlp_prompt_llm("Generate comprehensive QA tests")

    assert len(scenarios) >= 1
    assert sim.last_llm_generation_diagnostics.get("status") == "accepted"
    assert (
        sim.last_llm_generation_diagnostics.get("parse_diagnostics", {}).get("strategy")
        in {"repaired", "repaired_bracketed"}
    )


def test_llm_rejection_logs_no_candidates_reason(monkeypatch, tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "paths": {
            "/orders/{orderId}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }

    monkeypatch.setenv("QA_SCENARIO_LLM_MODE", "off")
    debug_log = tmp_path / "llm_debug.jsonl"
    sim = HumanTesterSimulator(
        spec,
        "http://localhost:8000",
        llm_debug_log_path=str(debug_log),
    )

    content = '{"meta":{"note":"not a scenarios payload"}}'

    class _FakeCompletions:
        def __init__(self, payload: str):
            self.payload = payload

        def create(self, **kwargs):
            message = type("Message", (), {"content": self.payload})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeClient:
        def __init__(self, payload: str):
            self.chat = type("Chat", (), {"completions": _FakeCompletions(payload)})()

    sim._llm_client = _FakeClient(content)
    sim.llm_enabled = True

    scenarios = sim._generate_from_nlp_prompt_llm("Generate comprehensive QA tests")

    assert scenarios == []
    assert sim.llm_stats.get("scenario_schema_rejections", 0) >= 1
    assert sim.last_llm_generation_diagnostics.get("status") == "rejected"
    assert sim.last_llm_generation_diagnostics.get("response_mode") in {"json_schema", "json_object", "plain"}

    events = [json.loads(line) for line in debug_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    rejected = [row for row in events if row.get("event") == "planner_rejected"]
    assert rejected, "Expected planner_rejected event in debug log"
    drop_counts = rejected[-1].get("drop_counts", {})
    assert int(drop_counts.get("no_candidates_extracted", 0)) >= 1


def test_llm_security_attack_expected_status_is_normalized_to_negative(monkeypatch):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "E-commerce API", "version": "1.0.0"},
        "paths": {
            "/products": {
                "get": {
                    "responses": {
                        "200": {"description": "ok"},
                        "401": {"description": "unauthorized"},
                    }
                },
                "post": {
                    "responses": {
                        "201": {"description": "created"},
                        "400": {"description": "bad request"},
                        "401": {"description": "unauthorized"},
                    }
                },
            }
        },
    }

    monkeypatch.setenv("QA_SCENARIO_LLM_MODE", "off")
    sim = HumanTesterSimulator(spec, "http://localhost:8000")

    content = json.dumps(
        {
            "scenarios": [
                {
                    "name": "Get Products - SQL Injection Attempt",
                    "description": "Probe SQL injection",
                    "test_type": "security",
                    "method": "GET",
                    "endpoint": "/products",
                    "expected_status": 200,
                    "params": {"search": "'; DROP TABLE products;--"},
                },
                {
                    "name": "Post Products - Cross Site Scripting Payload",
                    "description": "XSS payload",
                    "test_type": "security",
                    "method": "POST",
                    "endpoint": "/products",
                    "expected_status": 400,
                    "body": {"name": "<script>alert(1)</script>", "price": 10},
                },
            ]
        },
        ensure_ascii=True,
    )

    class _FakeCompletions:
        def __init__(self, payload: str):
            self.payload = payload

        def create(self, **kwargs):
            message = type("Message", (), {"content": self.payload})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeClient:
        def __init__(self, payload: str):
            self.chat = type("Chat", (), {"completions": _FakeCompletions(payload)})()

    sim._llm_client = _FakeClient(content)
    sim.llm_enabled = True

    scenarios = sim._generate_from_nlp_prompt_llm("Generate security tests")

    assert len(scenarios) == 2
    sqli = next(item for item in scenarios if "SQL Injection" in item.name)
    xss = next(item for item in scenarios if "Cross Site Scripting" in item.name)
    assert sqli.expected_status == 400
    assert xss.expected_status == 400
