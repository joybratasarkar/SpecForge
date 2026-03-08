"""Isolated generated-script execution harness.

This module is executed in a subprocess by the QA specialist agent so
generated scripts cannot run in the orchestrator process.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlparse

from fastapi.testclient import TestClient


class _ScriptResponseProxy:
    def __init__(self, response: Any):
        self._response = response
        self.status_code = int(getattr(response, "status_code", 0))
        self.text = getattr(response, "text", "")
        self.headers = getattr(response, "headers", {})

    def json(self) -> Any:
        return self._response.json()


GENERATED_PYTHON_ALLOWED_IMPORTS = {"json", "pytest", "requests"}
GENERATED_PYTHON_BLOCKED_CALLS = {
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "__import__",
}
GENERATED_PYTHON_BLOCKED_ATTRIBUTE_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "run"),
}


class _MockRequestsAdapter:
    def __init__(self, client: TestClient):
        self.client = client

    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> _ScriptResponseProxy:
        parsed = urlparse(str(url))
        path = parsed.path or "/"
        merged_params: Dict[str, Any] = {}
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            merged_params[str(key)] = value
        if isinstance(params, dict):
            merged_params.update(params)
        response = self.client.request(
            method=str(method).upper(),
            url=path,
            headers=headers or {},
            params=merged_params or None,
            json=json,
        )
        return _ScriptResponseProxy(response)

    def get(self, url: str, **kwargs: Any) -> _ScriptResponseProxy:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _ScriptResponseProxy:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> _ScriptResponseProxy:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> _ScriptResponseProxy:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> _ScriptResponseProxy:
        return self.request("DELETE", url, **kwargs)


class _LiveRequestsAdapter:
    def __init__(self, base_url: str, timeout_sec: float):
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout_sec = max(0.1, float(timeout_sec))
        self._session = None

    def __enter__(self) -> "_LiveRequestsAdapter":
        import requests

        self._session = requests.Session()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None

    def _absolute_url(self, url: str) -> str:
        raw = str(url or "").strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if raw.startswith("/"):
            return f"{self.base_url}{raw}"
        return f"{self.base_url}/{raw}"

    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        if self._session is None:
            raise RuntimeError("Live adapter session is not open")
        request_timeout = float(timeout) if timeout is not None else float(self.timeout_sec)
        return self._session.request(
            method=str(method).upper(),
            url=self._absolute_url(url),
            headers=headers or {},
            params=params or None,
            json=json,
            timeout=request_timeout,
            **kwargs,
        )

    def get(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Any:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self.request("DELETE", url, **kwargs)


def _assert_generated_python_script_safe(script_path: Path) -> None:
    source = script_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(script_path))
    except SyntaxError as exc:
        raise RuntimeError(f"Generated python script syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = str(alias.name).split(".", 1)[0]
                if root not in GENERATED_PYTHON_ALLOWED_IMPORTS:
                    raise RuntimeError(f"Unsafe python script import blocked: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module_root = str(node.module or "").split(".", 1)[0]
            if module_root not in GENERATED_PYTHON_ALLOWED_IMPORTS:
                raise RuntimeError(
                    f"Unsafe python script import blocked: {node.module or ''}"
                )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in GENERATED_PYTHON_BLOCKED_CALLS:
                    raise RuntimeError(f"Unsafe python script call blocked: {node.func.id}")
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                pair = (str(node.func.value.id), str(node.func.attr))
                if pair in GENERATED_PYTHON_BLOCKED_ATTRIBUTE_CALLS:
                    raise RuntimeError(
                        f"Unsafe python script call blocked: {pair[0]}.{pair[1]}"
                    )

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            raise RuntimeError("Unsafe top-level python call blocked")
        if isinstance(node, (ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While, ast.Try)):
            raise RuntimeError("Unsafe top-level python control flow blocked")


@contextmanager
def _install_requests_shim(adapter: Any):
    class _Session:
        def __init__(self, proxied: Any):
            self._proxied = proxied

        def request(self, method: str, url: str, **kwargs: Any) -> Any:
            return self._proxied.request(method, url, **kwargs)

        def get(self, url: str, **kwargs: Any) -> Any:
            return self._proxied.get(url, **kwargs)

        def post(self, url: str, **kwargs: Any) -> Any:
            return self._proxied.post(url, **kwargs)

        def put(self, url: str, **kwargs: Any) -> Any:
            return self._proxied.put(url, **kwargs)

        def patch(self, url: str, **kwargs: Any) -> Any:
            return self._proxied.patch(url, **kwargs)

        def delete(self, url: str, **kwargs: Any) -> Any:
            return self._proxied.delete(url, **kwargs)

        def close(self) -> None:
            return None

    shim = types.ModuleType("requests")
    shim.request = adapter.request
    shim.get = adapter.get
    shim.post = adapter.post
    shim.put = adapter.put
    shim.patch = adapter.patch
    shim.delete = adapter.delete
    shim.Session = lambda: _Session(adapter)
    shim.__dict__["__doc__"] = "SpecTestPilot requests shim for generated script isolation"

    previous = sys.modules.get("requests")
    sys.modules["requests"] = shim
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = previous


def _execute_module_tests(module: Any) -> Dict[str, Any]:
    test_class = getattr(module, "TestAPI", None)
    if test_class is None:
        raise RuntimeError("Generated python script missing TestAPI class")

    test_instance = test_class()
    test_methods = sorted(
        name
        for name in dir(test_instance)
        if name.startswith("test_") and callable(getattr(test_instance, name))
    )

    method_results: List[Dict[str, Any]] = []
    passed_count = 0
    for method_name in test_methods:
        fn = getattr(test_instance, method_name)
        method_started = time.perf_counter()
        try:
            fn()
            passed = True
            error_msg = ""
        except AssertionError as exc:
            passed = False
            error_msg = str(exc) or "AssertionError"
        except Exception as exc:
            passed = False
            error_msg = f"{type(exc).__name__}: {exc}"

        duration_ms = (time.perf_counter() - method_started) * 1000.0
        if passed:
            passed_count += 1
        method_results.append(
            {
                "name": method_name,
                "passed": bool(passed),
                "error": str(error_msg),
                "duration_ms": round(duration_ms, 3),
            }
        )

    total_count = len(method_results)
    failed_count = total_count - passed_count
    return {
        "results": method_results,
        "total_tests": int(total_count),
        "passed_tests": int(passed_count),
        "failed_tests": int(failed_count),
        "pass_rate": round((passed_count / total_count), 4) if total_count else 0.0,
    }


def _load_generated_module(script_path: Path, requests_adapter: Any, base_url: str) -> Any:
    _assert_generated_python_script_safe(script_path)
    module_name = f"generated_python_tests_subprocess_{int(time.time() * 1000)}"
    module_spec = importlib.util.spec_from_file_location(module_name, str(script_path))
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("Unable to load generated python test module")
    module = importlib.util.module_from_spec(module_spec)
    setattr(module, "requests", requests_adapter)
    setattr(module, "BASE_URL", str(base_url))
    with _install_requests_shim(requests_adapter):
        module_spec.loader.exec_module(module)
    return module


def _run_mock_mode(
    *,
    script_path: Path,
    spec_path: Path,
    base_url_hint: str,
) -> Dict[str, Any]:
    from dynamic_mock_server import DynamicMockServer

    with TestClient(DynamicMockServer(str(spec_path), host="127.0.0.1", port=0).app) as client:
        adapter = _MockRequestsAdapter(client)
        module = _load_generated_module(
            script_path,
            requests_adapter=adapter,
            base_url=str(base_url_hint),
        )
        return _execute_module_tests(module)


def _run_live_mode(
    *,
    script_path: Path,
    base_url: str,
    request_timeout_sec: float,
) -> Dict[str, Any]:
    with _LiveRequestsAdapter(base_url, timeout_sec=request_timeout_sec) as client:
        module = _load_generated_module(
            script_path,
            requests_adapter=client,
            base_url=str(base_url),
        )
        return _execute_module_tests(module)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated generated-script runner")
    parser.add_argument("--script-path", required=True, help="Path to generated python script")
    parser.add_argument("--mode", required=True, choices=["mock", "live"])
    parser.add_argument("--base-url", required=True, help="Base URL for script execution")
    parser.add_argument("--spec-path", default="", help="OpenAPI spec path (mock mode)")
    parser.add_argument(
        "--request-timeout-sec",
        type=float,
        default=12.0,
        help="Default per-request timeout for live mode",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    script_path = Path(args.script_path).expanduser().resolve()
    if not script_path.is_file():
        print(
            json.dumps(
                {
                    "status": "error",
                    "executed": False,
                    "error": f"script_not_found:{script_path}",
                },
                ensure_ascii=True,
            )
        )
        return 2

    started = time.perf_counter()
    try:
        if args.mode == "mock":
            spec_path = Path(str(args.spec_path or "")).expanduser().resolve()
            if not spec_path.is_file():
                raise RuntimeError(f"spec_not_found:{spec_path}")
            payload = _run_mock_mode(
                script_path=script_path,
                spec_path=spec_path,
                base_url_hint=str(args.base_url),
            )
        else:
            payload = _run_live_mode(
                script_path=script_path,
                base_url=str(args.base_url),
                request_timeout_sec=float(args.request_timeout_sec),
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        payload.update(
            {
                "status": "executed",
                "executed": True,
                "execution_ms": round(elapsed_ms, 3),
            }
        )
        print(json.dumps(payload, ensure_ascii=True))
        return 0
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        print(
            json.dumps(
                {
                    "status": "error",
                    "executed": False,
                    "error": str(exc),
                    "execution_ms": round(elapsed_ms, 3),
                },
                ensure_ascii=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
