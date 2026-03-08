"""Execution-pipeline safety and runtime-cap regression tests."""

from __future__ import annotations

import time
from pathlib import Path

from spec_test_pilot.multi_language_tester import (
    TestScenario as ScenarioModel,
    TestType as ScenarioType,
)
from spec_test_pilot.qa_specialist_agent import QASpecialistAgent


class _ClientResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = int(status_code)
        self._payload = dict(payload or {"ok": True})
        self.text = "{}"
        self.headers = {}

    def json(self) -> dict:
        return dict(self._payload)


class _FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, **_: object) -> _ClientResponse:
        self.calls += 1
        return _ClientResponse(status_code=200)


class _NoContentResponse:
    def __init__(self, status_code: int = 204) -> None:
        self.status_code = int(status_code)
        self.text = ""
        self.headers = {}

    def json(self) -> dict:
        raise ValueError("no JSON body")


def _scenario_get_ok() -> ScenarioModel:
    return ScenarioModel(
        name="test_get_products_happy",
        description="happy path",
        test_type=ScenarioType.HAPPY_PATH,
        endpoint="/products",
        method="GET",
        expected_status=200,
    )


def test_execute_one_scenario_returns_blocked_when_deadline_elapsed(tmp_path: Path) -> None:
    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        max_runtime_sec=1,
    )
    client = _FakeClient()
    result = agent._execute_one_scenario(
        client,
        _scenario_get_ok(),
        deadline=time.perf_counter() - 0.01,
    )

    assert result.verdict == "blocked"
    assert result.error == "runtime_cap_exceeded_1s"
    assert client.calls == 0
    assert agent._runtime_cap_hit is True
    assert agent._runtime_skipped_count == 1


def test_execute_generated_python_script_blocks_unsafe_import(tmp_path: Path) -> None:
    script_path = tmp_path / "unsafe_test_api.py"
    script_path.write_text(
        "import os\n\n"
        "class TestAPI:\n"
        "    def test_blocked(self):\n"
        "        assert True\n",
        encoding="utf-8",
    )

    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        script_kind="python_pytest",
        max_runtime_sec=5,
    )
    result = agent._execute_generated_script(
        {},
        {"python_pytest": str(script_path)},
    )

    assert result["status"] == "error"
    assert result["executed"] is False
    assert "Unsafe python script import blocked" in str(result.get("error", ""))


def test_execute_generated_python_script_blocks_top_level_calls(tmp_path: Path) -> None:
    script_path = tmp_path / "unsafe_top_level_test_api.py"
    script_path.write_text(
        "import requests\n\n"
        "requests.get('http://example.com')\n\n"
        "class TestAPI:\n"
        "    def test_blocked(self):\n"
        "        assert True\n",
        encoding="utf-8",
    )

    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        script_kind="python_pytest",
        max_runtime_sec=5,
    )
    result = agent._execute_generated_script(
        {},
        {"python_pytest": str(script_path)},
    )

    assert result["status"] == "error"
    assert result["executed"] is False
    assert "Unsafe top-level python call blocked" in str(result.get("error", ""))


def test_execute_generated_javascript_script_is_validated(tmp_path: Path) -> None:
    script_path = tmp_path / "test_api.test.js"
    script_path.write_text(
        "const axios = require('axios');\n"
        "describe('API Tests', () => {\n"
        "  test('ok', async () => { expect(200).toBe(200); });\n"
        "});\n",
        encoding="utf-8",
    )

    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        script_kind="javascript_jest",
    )
    result = agent._execute_generated_script(
        {},
        {"javascript_jest": str(script_path)},
    )

    assert result["status"] == "validated"
    assert result["executed"] is False
    assert result["validated"] is True


def test_execute_generated_script_skips_when_runtime_budget_exhausted(tmp_path: Path) -> None:
    script_path = tmp_path / "test_api.test.js"
    script_path.write_text(
        "const axios = require('axios');\n"
        "describe('API Tests', () => { test('ok', async () => { expect(1).toBe(1); }); });\n",
        encoding="utf-8",
    )

    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        script_kind="javascript_jest",
        max_runtime_sec=2,
    )
    result = agent._execute_generated_script(
        {},
        {"javascript_jest": str(script_path)},
        max_exec_sec=0.0,
    )

    assert result["status"] == "skipped"
    assert result["executed"] is False
    assert result["reason"] == "runtime_cap_exceeded_2s"


def test_execute_generated_curl_script_blocks_cross_host_target(tmp_path: Path) -> None:
    script_path = tmp_path / "test_api.curl"
    script_path.write_text(
        "curl -X GET https://example.com/health\n",
        encoding="utf-8",
    )

    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        script_kind="curl_script",
        environment_profile="staging",
        base_url="http://127.0.0.1:8000",
    )
    result = agent._execute_generated_script(
        {},
        {"curl_script": str(script_path)},
    )

    assert result["status"] == "error"
    error_text = str(result.get("error", ""))
    assert error_text.startswith("unsafe_curl_command:url_")
    assert any(
        token in error_text
        for token in ("scheme_mismatch", "host_mismatch", "port_mismatch")
    )


def test_load_spec_invalid_json_returns_value_error(tmp_path: Path) -> None:
    spec_path = tmp_path / "broken_spec.json"
    spec_path.write_text(
        '{"openapi":"3.0.3","info":{"title":"broken"},"paths":{"/x":{"get":{"responses":{"200":{"description":123}}}}}',
        encoding="utf-8",
    )
    agent = QASpecialistAgent(
        spec_path=str(spec_path),
        output_dir=str(tmp_path / "out"),
    )
    try:
        agent._load_spec()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Invalid JSON OpenAPI spec" in str(exc)


def test_live_execution_preflight_blocks_all_scenarios_when_unreachable(tmp_path: Path) -> None:
    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        environment_profile="staging",
        base_url="http://127.0.0.1:9",
    )
    scenarios = [_scenario_get_ok()]
    results = agent._execute_against_live_api(scenarios)
    assert len(results) == 1
    result = results[0]
    assert result.verdict == "blocked"
    assert str(result.error).startswith("environment_preflight_failed:")


def test_verify_then_correct_accepts_equivalent_documented_success_status(tmp_path: Path) -> None:
    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        environment_profile="mock",
    )
    scenario = ScenarioModel(
        name="test_delete_item_success",
        description="delete happy path",
        test_type=ScenarioType.HAPPY_PATH,
        endpoint="/items/{itemId}",
        method="DELETE",
        expected_status=200,
        params={"itemId": "123"},
    )
    op_key = f"{scenario.method} {scenario.endpoint}"
    agent._operation_index = {
        op_key: {
            "response_statuses": [200, 204, 400],
            "response_schemas": {"200": {"type": "object"}, "204": {"type": "boolean"}},
            "path_param_names": ["itemId"],
        }
    }
    verification = agent._verify_then_correct_result(
        scenario=scenario,
        actual_status=204,
        response=_NoContentResponse(status_code=204),
        query_params={},
        body=None,
    )
    assert verification["verdict"] == "pass"
    assert verification["status_check"]["matched"] is True
    assert verification["status_check"]["equivalent_success_status"] is True


def test_real_life_bola_probe_not_added_without_path_params(tmp_path: Path) -> None:
    agent = QASpecialistAgent(
        spec_path=str(tmp_path / "spec.yaml"),
        output_dir=str(tmp_path / "out"),
        max_scenarios=4,
    )
    operation_key = "GET /products"
    agent._operation_index = {
        operation_key: {
            "path_param_names": [],
            "query_param_names": ["q"],
            "request_schema": {},
            "required_fields": [],
            "response_statuses": [200, 401, 404],
            "response_schemas": {"200": {"type": "object"}},
        }
    }
    agent._auth_required_ops = {operation_key}
    scenarios, _ = agent._inject_real_life_guardrail_scenarios([])
    assert all("bola_probe" not in str(item.name) for item in scenarios)
