"""
QA specialist agent orchestration.

End-to-end flow:
1. Parse OpenAPI spec and generate human-like QA scenarios
2. Generate multi-language test files
3. Execute all scenarios in an isolated in-memory API sandbox
4. Store run context in GAM memory
5. Run Agent Lightning RL update from execution outcomes
6. Emit JSON + Markdown reports
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi.testclient import TestClient

from spec_test_pilot.agent_lightning_v2 import AgentLightningTrainer as LightningTrainerV2
from spec_test_pilot.memory.gam import GAMMemorySystem
from spec_test_pilot.multi_language_tester import (
    HumanTesterSimulator,
    MultiLanguageTestGenerator,
    TestScenario,
)


PATH_PARAM_PATTERN = re.compile(r"\{([^}]+)\}")


@dataclass
class ScenarioExecutionResult:
    """Runtime execution result for a single scenario."""

    name: str
    test_type: str
    method: str
    endpoint_template: str
    endpoint_resolved: str
    expected_status: int
    actual_status: Optional[int]
    passed: bool
    duration_ms: float
    error: str = ""
    response_excerpt: str = ""


class QASpecialistAgent:
    """QA-focused orchestrator with isolation, GAM memory, and RL feedback."""

    def __init__(
        self,
        spec_path: str,
        nlp_prompt: Optional[str] = None,
        tenant_id: str = "default_tenant",
        base_url: str = "http://localhost:8000",
        output_dir: Optional[str] = None,
        max_scenarios: int = 200,
        pass_threshold: float = 0.70,
    ):
        self.spec_path = str(spec_path)
        self.nlp_prompt = nlp_prompt
        self.tenant_id = tenant_id
        self.base_url = base_url.rstrip("/")
        self.max_scenarios = max(1, int(max_scenarios))
        self.pass_threshold = max(0.0, min(1.0, float(pass_threshold)))

        if output_dir:
            self.output_dir = Path(output_dir).resolve()
            self.output_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.output_dir = Path(
                tempfile.mkdtemp(prefix="qa_specialist_run_")
            ).resolve()

        self.gam = GAMMemorySystem(use_vector_search=False)
        self.rl_trainer = LightningTrainerV2(gam_memory_system=self.gam)
        self.rl_trainer.register_agent("qa_specialist", self._qa_agent_feedback)

    def run(self) -> Dict[str, Any]:
        """Run the full QA specialist workflow."""
        started_at = time.time()
        spec = self._load_spec()
        spec_title = spec.get("info", {}).get("title", "Unknown API")
        spec_version = spec.get("info", {}).get("version", "unknown")

        session_id = self.gam.start_session(
            tenant_id=self.tenant_id,
            metadata={
                "spec_path": self.spec_path,
                "spec_title": spec_title,
                "spec_version": spec_version,
                "mode": "qa_specialist",
            },
        )
        self.gam.add_to_session(
            session_id,
            "user",
            "Run full QA-specialist API testing pipeline.",
            tool_outputs=[
                {
                    "tool": "qa_agent.init",
                    "output": {
                        "spec_path": self.spec_path,
                        "tenant_id": self.tenant_id,
                        "nlp_prompt": self.nlp_prompt or "comprehensive_default",
                    },
                }
            ],
        )

        research_context = {
            "spec_title": spec_title,
            "auth_type": self._infer_auth_type(spec),
            "endpoints": self._extract_endpoint_metadata(spec),
            "tenant_id": self.tenant_id,
        }
        research_result = self.gam.research(research_context)
        self.gam.add_to_session(
            session_id,
            "assistant",
            "Completed GAM deep-research planning and retrieval for test strategy.",
            tool_outputs=[
                {
                    "tool": "gam.research",
                    "output": {
                        "plan": research_result.plan,
                        "reflection": research_result.reflection,
                        "excerpt_count": len(research_result.memory_excerpts),
                    },
                }
            ],
        )

        simulator = HumanTesterSimulator(spec, self.base_url)
        effective_prompt = self._compose_effective_prompt(
            self.nlp_prompt, research_result.memory_excerpts
        )
        scenarios = simulator.think_like_tester(effective_prompt)
        scenarios = scenarios[: self.max_scenarios]

        generated_files = self._generate_test_files(scenarios)
        execution_results = self._execute_in_isolated_mock(spec, scenarios)
        summary = self._build_summary(spec, scenarios, execution_results)

        self.gam.add_to_session(
            session_id,
            "assistant",
            "Executed generated scenarios in isolated sandbox and produced summary.",
            tool_outputs=[
                {"tool": "qa_agent.execution", "output": summary},
            ],
            artifacts=[
                {"name": "qa_summary.json", "type": "json", "content": json.dumps(summary)},
            ],
        )

        issues_found = [f["name"] for f in summary["failed_examples"][:10]]
        key_decisions = [
            f"Generated {summary['total_scenarios']} QA scenarios",
            "Executed scenarios using in-memory FastAPI TestClient isolation",
            f"Pass threshold set to {self.pass_threshold:.2f}",
        ]

        lossless_pages, memo_page = self.gam.end_session_with_memo(
            session_id=session_id,
            spec_title=spec_title,
            endpoints_count=summary["detected_endpoints"],
            tests_generated=summary["total_scenarios"],
            key_decisions=key_decisions,
            issues_found=issues_found,
        )

        rl_report_path = self.output_dir / "qa_execution_report.json"
        rl_data = self._run_agent_lightning_training(
            spec_title=spec_title,
            summary=summary,
            report_path=str(rl_report_path),
        )

        report = {
            "metadata": {
                "spec_path": self.spec_path,
                "spec_title": spec_title,
                "spec_version": spec_version,
                "tenant_id": self.tenant_id,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "execution_seconds": round(time.time() - started_at, 3),
                "isolation_mode": "in_memory_fastapi_testclient",
            },
            "summary": summary,
            "generated_test_files": generated_files,
            "scenario_results": [asdict(r) for r in execution_results],
            "gam": {
                "session_id": session_id,
                "memo_page_id": memo_page.id,
                "memo_title": memo_page.title,
                "lossless_page_ids": [p.id for p in lossless_pages],
                "research_plan": research_result.plan,
                "research_reflection": research_result.reflection,
                "research_excerpt_count": len(research_result.memory_excerpts),
            },
            "agent_lightning": rl_data,
            "paper_references": {
                "agent_lightning": "https://arxiv.org/pdf/2508.03680",
                "gam": "https://arxiv.org/pdf/2511.18423",
            },
        }

        report_paths = self._write_reports(report)
        report["report_files"] = report_paths

        # Persist final report including file references.
        with open(report_paths["json"], "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        return report

    def _load_spec(self) -> Dict[str, Any]:
        spec_path = Path(self.spec_path)
        if not spec_path.exists():
            raise FileNotFoundError(f"Spec file not found: {self.spec_path}")

        content = spec_path.read_text(encoding="utf-8")
        if spec_path.suffix.lower() in [".yaml", ".yml"]:
            parsed = yaml.safe_load(content)
        else:
            parsed = json.loads(content)

        if not isinstance(parsed, dict):
            raise ValueError("OpenAPI spec must parse to a JSON/YAML object.")
        return parsed

    def _generate_test_files(self, scenarios: List[TestScenario]) -> Dict[str, str]:
        generator = MultiLanguageTestGenerator(scenarios, self.base_url)
        tests_dir = self.output_dir / "generated_tests"
        tests_dir.mkdir(parents=True, exist_ok=True)

        file_map = {
            "python_pytest": tests_dir / "test_api.py",
            "javascript_jest": tests_dir / "test_api.test.js",
            "curl_script": tests_dir / "test_api.sh",
            "java_restassured": tests_dir / "APITests.java",
        }

        file_map["python_pytest"].write_text(
            generator.generate_python_tests(), encoding="utf-8"
        )
        file_map["javascript_jest"].write_text(
            generator.generate_javascript_tests(), encoding="utf-8"
        )
        file_map["curl_script"].write_text(
            generator.generate_curl_tests(), encoding="utf-8"
        )
        file_map["java_restassured"].write_text(
            generator.generate_java_tests(), encoding="utf-8"
        )

        return {k: str(v) for k, v in file_map.items()}

    def _execute_in_isolated_mock(
        self, spec: Dict[str, Any], scenarios: List[TestScenario]
    ) -> List[ScenarioExecutionResult]:
        # Imported lazily so this module can be used without server startup paths.
        from agent_lightning_server import DynamicMockServer

        spec_copy = self.output_dir / "openapi_under_test.yaml"
        spec_copy.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")

        server = DynamicMockServer(str(spec_copy), host="127.0.0.1", port=0)
        results: List[ScenarioExecutionResult] = []

        with TestClient(server.app) as client:
            for scenario in scenarios:
                results.append(self._execute_one_scenario(client, scenario))

        return results

    def _execute_one_scenario(
        self, client: TestClient, scenario: TestScenario
    ) -> ScenarioExecutionResult:
        method = scenario.method.upper()
        endpoint_resolved = self._resolve_endpoint_path(
            scenario.endpoint, scenario.params, scenario.expected_status
        )
        headers = self._render_headers(scenario.headers)
        query_params = self._strip_path_params(scenario.endpoint, scenario.params)
        body = scenario.body if method in {"POST", "PUT", "PATCH"} else None

        started = time.perf_counter()
        try:
            response = client.request(
                method=method,
                url=endpoint_resolved,
                headers=headers,
                params=query_params,
                json=body,
            )
            duration_ms = (time.perf_counter() - started) * 1000.0
            actual_status = int(response.status_code)
            passed = actual_status == int(scenario.expected_status)
            response_excerpt = self._response_excerpt(response)

            return ScenarioExecutionResult(
                name=scenario.name,
                test_type=scenario.test_type.value,
                method=method,
                endpoint_template=scenario.endpoint,
                endpoint_resolved=endpoint_resolved,
                expected_status=int(scenario.expected_status),
                actual_status=actual_status,
                passed=passed,
                duration_ms=round(duration_ms, 3),
                response_excerpt=response_excerpt,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000.0
            return ScenarioExecutionResult(
                name=scenario.name,
                test_type=scenario.test_type.value,
                method=method,
                endpoint_template=scenario.endpoint,
                endpoint_resolved=endpoint_resolved,
                expected_status=int(scenario.expected_status),
                actual_status=None,
                passed=False,
                duration_ms=round(duration_ms, 3),
                error=str(exc),
                response_excerpt="",
            )

    def _resolve_endpoint_path(
        self, endpoint: str, params: Dict[str, Any], expected_status: int
    ) -> str:
        resolved = endpoint
        for param_name in PATH_PARAM_PATTERN.findall(endpoint):
            value = params.get(param_name)
            if value is None:
                value = "999" if expected_status == 404 else "123"
            resolved = resolved.replace("{" + param_name + "}", str(value))
        return resolved

    def _strip_path_params(
        self, endpoint_template: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        # Query params should not include params used in path placeholders.
        path_param_names = set(PATH_PARAM_PATTERN.findall(endpoint_template))
        return {
            key: value
            for key, value in (params or {}).items()
            if key not in path_param_names
        }

    def _render_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        rendered: Dict[str, str] = {}
        for k, v in (headers or {}).items():
            value = str(v)
            value = value.replace("{{auth_token}}", "valid_token_123")
            value = value.replace("{{admin_token}}", "admin_token_123")
            rendered[k] = value
        return rendered

    def _response_excerpt(self, response) -> str:
        try:
            payload = response.json()
            text = json.dumps(payload, ensure_ascii=True)
        except Exception:
            text = response.text or ""
        if len(text) > 300:
            text = text[:300] + "..."
        return text

    def _build_summary(
        self,
        spec: Dict[str, Any],
        scenarios: List[TestScenario],
        results: List[ScenarioExecutionResult],
    ) -> Dict[str, Any]:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        pass_rate = (passed / total) if total else 0.0
        avg_duration_ms = (
            sum(r.duration_ms for r in results) / total if total else 0.0
        )

        by_type: Dict[str, Dict[str, Any]] = {}
        for result in results:
            item = by_type.setdefault(
                result.test_type, {"total": 0, "passed": 0, "failed": 0}
            )
            item["total"] += 1
            if result.passed:
                item["passed"] += 1
            else:
                item["failed"] += 1

        failed_examples = [
            {
                "name": r.name,
                "method": r.method,
                "endpoint": r.endpoint_resolved,
                "expected_status": r.expected_status,
                "actual_status": r.actual_status,
                "error": r.error,
            }
            for r in results
            if not r.passed
        ][:25]

        detected_endpoints = 0
        if isinstance(spec.get("paths"), dict):
            for _, path_info in spec["paths"].items():
                if isinstance(path_info, dict):
                    detected_endpoints += sum(
                        1
                        for method in path_info.keys()
                        if method.lower() in {"get", "post", "put", "patch", "delete"}
                    )

        return {
            "total_scenarios": total,
            "passed_scenarios": passed,
            "failed_scenarios": failed,
            "pass_rate": round(pass_rate, 4),
            "pass_threshold": self.pass_threshold,
            "meets_quality_gate": pass_rate >= self.pass_threshold,
            "average_duration_ms": round(avg_duration_ms, 3),
            "detected_endpoints": detected_endpoints,
            "scenario_count_generated": len(scenarios),
            "test_type_breakdown": by_type,
            "failed_examples": failed_examples,
        }

    def _compose_effective_prompt(
        self, base_prompt: Optional[str], memory_excerpts: List[Dict[str, str]]
    ) -> Optional[str]:
        if not base_prompt:
            return None
        if not memory_excerpts:
            return base_prompt

        focus_points = []
        for excerpt in memory_excerpts[:2]:
            text = excerpt.get("excerpt", "").replace("\n", " ").strip()
            if text:
                focus_points.append(text[:140])
        if not focus_points:
            return base_prompt

        return base_prompt + " Focus additionally on: " + " | ".join(focus_points)

    def _extract_endpoint_metadata(self, spec: Dict[str, Any]) -> List[Dict[str, str]]:
        endpoints: List[Dict[str, str]] = []
        for path, path_info in (spec.get("paths") or {}).items():
            if not isinstance(path_info, dict):
                continue
            for method in path_info.keys():
                if method.lower() in {"get", "post", "put", "patch", "delete"}:
                    endpoints.append({"method": method.upper(), "path": path})
        return endpoints

    def _infer_auth_type(self, spec: Dict[str, Any]) -> str:
        components = (spec.get("components") or {}).get("securitySchemes", {})
        if not components:
            return "none"
        for _, scheme in components.items():
            stype = (scheme or {}).get("type", "").lower()
            if stype == "http" and (scheme or {}).get("scheme", "").lower() == "bearer":
                return "bearer"
            if stype == "apikey":
                return "apiKey"
            if stype == "oauth2":
                return "oauth2"
        return "unknown"

    def _run_agent_lightning_training(
        self, spec_title: str, summary: Dict[str, Any], report_path: str
    ) -> Dict[str, Any]:
        task_payload = {
            "spec_title": spec_title,
            "tenant_id": self.tenant_id,
            "pass_rate": summary["pass_rate"],
            "pass_threshold": summary["pass_threshold"],
            "total_scenarios": summary["total_scenarios"],
            "failed_scenarios": summary["failed_scenarios"],
            "report_path": report_path,
            "summary": summary,
        }

        training_result = self._run_async(
            self.rl_trainer.train_agent("qa_specialist", task_payload)
        )
        training_stats = self.rl_trainer.get_training_stats()
        return {
            "training_result": training_result,
            "training_stats": training_stats,
        }

    def _qa_agent_feedback(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Adapter output used by Agent Lightning RL."""
        pass_rate = float(task_data.get("pass_rate", 0.0))
        threshold = float(task_data.get("pass_threshold", self.pass_threshold))
        success = pass_rate >= threshold
        return {
            "success": success,
            "quality_score": pass_rate,
            "summary": task_data.get("summary", {}),
            "report_path": task_data.get("report_path"),
        }

    def _write_reports(self, report: Dict[str, Any]) -> Dict[str, str]:
        json_path = self.output_dir / "qa_execution_report.json"
        md_path = self.output_dir / "qa_execution_report.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        md_path.write_text(self._to_markdown(report), encoding="utf-8")
        return {"json": str(json_path), "markdown": str(md_path)}

    def _to_markdown(self, report: Dict[str, Any]) -> str:
        summary = report["summary"]
        metadata = report["metadata"]

        lines = [
            "# QA Specialist Execution Report",
            "",
            "## Run Metadata",
            f"- Spec: `{metadata['spec_title']}` ({metadata['spec_version']})",
            f"- Spec Path: `{metadata['spec_path']}`",
            f"- Tenant: `{metadata['tenant_id']}`",
            f"- Isolation: `{metadata['isolation_mode']}`",
            f"- Generated At: `{metadata['generated_at']}`",
            f"- Execution Time: `{metadata['execution_seconds']}s`",
            "",
            "## Summary",
            f"- Total Scenarios: `{summary['total_scenarios']}`",
            f"- Passed: `{summary['passed_scenarios']}`",
            f"- Failed: `{summary['failed_scenarios']}`",
            f"- Pass Rate: `{summary['pass_rate']}`",
            f"- Quality Gate ({summary['pass_threshold']}): `{summary['meets_quality_gate']}`",
            f"- Avg Duration: `{summary['average_duration_ms']} ms`",
            "",
            "## Test Type Breakdown",
        ]

        for test_type, counts in summary["test_type_breakdown"].items():
            lines.append(
                f"- `{test_type}`: total={counts['total']}, passed={counts['passed']}, failed={counts['failed']}"
            )

        lines.extend(
            [
                "",
                "## Top Failures",
            ]
        )
        if summary["failed_examples"]:
            for failure in summary["failed_examples"][:10]:
                lines.append(
                    f"- `{failure['name']}` expected={failure['expected_status']} actual={failure['actual_status']} endpoint={failure['endpoint']}"
                )
        else:
            lines.append("- None")

        gam = report.get("gam", {})
        lines.extend(
            [
                "",
                "## GAM Memory",
                f"- Session ID: `{gam.get('session_id', '')}`",
                f"- Memo Page ID: `{gam.get('memo_page_id', '')}`",
                f"- Memo Title: `{gam.get('memo_title', '')}`",
                f"- Research Excerpts: `{gam.get('research_excerpt_count', 0)}`",
                f"- Research Reflection: `{gam.get('research_reflection', '')}`",
                "",
            ]
        )

        rl = report.get("agent_lightning", {})
        training_stats = rl.get("training_stats", {})
        lines.extend(
            [
                "## Agent Lightning RL",
                f"- Registered Agents: `{training_stats.get('registered_agents', 0)}`",
                f"- Traces Collected: `{training_stats.get('total_traces', 0)}`",
                f"- Replay Buffer Size: `{training_stats.get('rl_buffer_size', 0)}`",
                f"- Training Steps: `{training_stats.get('rl_training_steps', 0)}`",
                f"- Training Enabled: `{training_stats.get('training_enabled', False)}`",
            ]
        )

        references = report.get("paper_references", {})
        if references:
            lines.extend(
                [
                    "",
                    "## References",
                    f"- Agent Lightning: {references.get('agent_lightning', '')}",
                    f"- GAM: {references.get('gam', '')}",
                ]
            )

        return "\n".join(lines) + "\n"

    def _run_async(self, coroutine):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)
        raise RuntimeError(
            "Cannot call synchronous runner from an active event loop. "
            "Use the async Agent Lightning API directly."
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="QA specialist agent with isolated execution + GAM + Agent Lightning RL."
    )
    parser.add_argument("--spec", required=True, help="Path to OpenAPI spec (yaml/json)")
    parser.add_argument("--prompt", default=None, help="Optional natural-language QA prompt")
    parser.add_argument("--tenant-id", default="default_tenant", help="Tenant id for GAM memory")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL used when generating test scripts",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated tests and reports (default: temp dir)",
    )
    parser.add_argument(
        "--max-scenarios",
        type=int,
        default=200,
        help="Maximum number of scenarios to execute",
    )
    parser.add_argument(
        "--pass-threshold",
        type=float,
        default=0.70,
        help="Minimum pass-rate required for quality gate",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    agent = QASpecialistAgent(
        spec_path=args.spec,
        nlp_prompt=args.prompt,
        tenant_id=args.tenant_id,
        base_url=args.base_url,
        output_dir=args.output_dir,
        max_scenarios=args.max_scenarios,
        pass_threshold=args.pass_threshold,
    )

    report = agent.run()
    summary = report["summary"]
    files = report["report_files"]

    print("QA specialist run complete")
    print(f"Spec: {report['metadata']['spec_title']}")
    print(
        f"Scenarios: total={summary['total_scenarios']} "
        f"passed={summary['passed_scenarios']} failed={summary['failed_scenarios']}"
    )
    print(f"Pass rate: {summary['pass_rate']}")
    print(f"Quality gate met: {summary['meets_quality_gate']}")
    print(f"JSON report: {files['json']}")
    print(f"Markdown report: {files['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
