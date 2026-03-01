"""
RL-friendly reward function for SpecTestPilot.

Implements:
- Hard gates (return 0.0 if fail)
- Positive components (sum then clip to [0,1])
- Optional intermediate reward hooks per node
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from pydantic import ValidationError

from spec_test_pilot.schemas import SpecTestPilotOutput, validate_output
from spec_test_pilot.openapi_parse import parse_openapi_spec, ParsedSpec


@dataclass
class RewardBreakdown:
    """Detailed breakdown of reward components."""
    # Hard gates
    valid_json: bool = False
    pydantic_valid: bool = False
    no_invented_endpoints: bool = False
    
    # Positive components
    endpoint_coverage: float = 0.0
    negative_quality: float = 0.0
    auth_negative: float = 0.0
    missing_info_quality: float = 0.0
    
    # Final reward
    total_reward: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hard_gates": {
                "valid_json": self.valid_json,
                "pydantic_valid": self.pydantic_valid,
                "no_invented_endpoints": self.no_invented_endpoints
            },
            "positive_components": {
                "endpoint_coverage": self.endpoint_coverage,
                "negative_quality": self.negative_quality,
                "auth_negative": self.auth_negative,
                "missing_info_quality": self.missing_info_quality
            },
            "total_reward": self.total_reward
        }


def compute_reward(
    output_json: Dict[str, Any],
    parsed_spec: ParsedSpec,
    gold: Optional[Dict[str, Any]] = None
) -> Tuple[float, RewardBreakdown]:
    """
    Compute reward for agent output.
    
    Args:
        output_json: Agent output as dictionary
        parsed_spec: Parsed OpenAPI specification
        gold: Optional gold standard for comparison
        
    Returns:
        Tuple of (reward_float, RewardBreakdown)
    """
    breakdown = RewardBreakdown()
    
    # ========== HARD GATES ==========
    # Gate 1: Valid JSON (already a dict, so this passes)
    breakdown.valid_json = isinstance(output_json, dict)
    if not breakdown.valid_json:
        return 0.0, breakdown
    
    # Gate 2: Pydantic validation
    try:
        validated = validate_output(output_json)
        breakdown.pydantic_valid = True
    except ValidationError:
        breakdown.pydantic_valid = False
        return 0.0, breakdown
    
    # Gate 3: No invented endpoints
    spec_endpoints = {(e.method, e.path) for e in parsed_spec.endpoints}
    test_endpoints = {
        (t.endpoint.method, t.endpoint.path) 
        for t in validated.test_suite
    }
    
    invented = test_endpoints - spec_endpoints
    breakdown.no_invented_endpoints = len(invented) == 0
    
    if not breakdown.no_invented_endpoints:
        return 0.0, breakdown
    
    # ========== POSITIVE COMPONENTS ==========
    
    # Component 1: Endpoint coverage
    # Fraction of endpoints that have >= 3 tests (1 happy + 2 negative)
    breakdown.endpoint_coverage = _compute_endpoint_coverage(
        validated, spec_endpoints
    )
    
    # Component 2: Negative quality
    # Has missing-field + invalid-type/format negatives
    breakdown.negative_quality = _compute_negative_quality(validated)
    
    # Component 3: Auth negative
    # If auth exists, includes auth-negative test per endpoint
    breakdown.auth_negative = _compute_auth_negative(
        validated, parsed_spec, spec_endpoints
    )
    
    # Component 4: Missing info quality
    # If spec incomplete, missing_info contains required items
    breakdown.missing_info_quality = _compute_missing_info_quality(
        validated, parsed_spec
    )
    
    # Sum and clip to [0, 1]
    raw_sum = (
        breakdown.endpoint_coverage * 0.4 +
        breakdown.negative_quality * 0.2 +
        breakdown.auth_negative * 0.2 +
        breakdown.missing_info_quality * 0.2
    )
    
    breakdown.total_reward = max(0.0, min(1.0, raw_sum))
    
    return breakdown.total_reward, breakdown


def _compute_endpoint_coverage(
    validated: SpecTestPilotOutput,
    spec_endpoints: set
) -> float:
    """
    Compute endpoint coverage score.
    
    Fraction of endpoints that have >= 3 tests.
    """
    if not spec_endpoints:
        return 1.0  # No endpoints to cover
    
    # Count tests per endpoint
    tests_per_endpoint: Dict[Tuple[str, str], int] = {}
    for test in validated.test_suite:
        key = (test.endpoint.method, test.endpoint.path)
        tests_per_endpoint[key] = tests_per_endpoint.get(key, 0) + 1
    
    # Count endpoints with >= 3 tests
    well_covered = sum(
        1 for ep in spec_endpoints
        if tests_per_endpoint.get(ep, 0) >= 3
    )
    
    return well_covered / len(spec_endpoints)


def _compute_negative_quality(validated: SpecTestPilotOutput) -> float:
    """
    Compute negative test quality score.
    
    Checks for:
    - Missing field tests (400 status)
    - Invalid type/format tests
    """
    if not validated.test_suite:
        return 0.0
    
    has_missing_field = False
    has_invalid_type = False
    
    for test in validated.test_suite:
        name_lower = test.name.lower()
        objective_lower = test.objective.lower()
        
        # Check for missing field tests
        if any(term in name_lower or term in objective_lower 
               for term in ["missing", "required", "validation"]):
            for assertion in test.assertions:
                if assertion.type == "status_code" and assertion.expected == 400:
                    has_missing_field = True
                    break
        
        # Check for invalid type tests
        if any(term in name_lower or term in objective_lower
               for term in ["invalid", "type", "format"]):
            for assertion in test.assertions:
                if assertion.type == "status_code" and assertion.expected == 400:
                    has_invalid_type = True
                    break
    
    score = 0.0
    if has_missing_field:
        score += 0.5
    if has_invalid_type:
        score += 0.5
    
    # Also give partial credit for any 400 tests
    has_any_400 = any(
        any(a.type == "status_code" and a.expected == 400 for a in t.assertions)
        for t in validated.test_suite
    )
    if has_any_400 and score < 0.5:
        score = 0.5
    
    return score


def _compute_auth_negative(
    validated: SpecTestPilotOutput,
    parsed_spec: ParsedSpec,
    spec_endpoints: set
) -> float:
    """
    Compute auth negative test score.
    
    If auth exists, checks for auth-negative tests (401) per endpoint.
    """
    # Check if auth is required
    auth_type = parsed_spec.auth.type
    if auth_type in ["none", "unknown"]:
        return 1.0  # No auth required, full score
    
    if not spec_endpoints:
        return 1.0
    
    # Find endpoints with auth-negative tests
    endpoints_with_auth_test = set()
    
    for test in validated.test_suite:
        name_lower = test.name.lower()
        objective_lower = test.objective.lower()
        
        # Check if this is an auth test
        is_auth_test = any(
            term in name_lower or term in objective_lower
            for term in ["auth", "unauthorized", "401", "403", "token", "credential"]
        )
        
        if is_auth_test:
            for assertion in test.assertions:
                if assertion.type == "status_code" and assertion.expected in [401, 403]:
                    endpoints_with_auth_test.add(
                        (test.endpoint.method, test.endpoint.path)
                    )
                    break
    
    # Calculate coverage
    coverage = len(endpoints_with_auth_test) / len(spec_endpoints)
    return coverage


def _compute_missing_info_quality(
    validated: SpecTestPilotOutput,
    parsed_spec: ParsedSpec
) -> float:
    """
    Compute missing info quality score.
    
    If spec is incomplete, missing_info should contain required items.
    """
    # Check if spec is incomplete
    is_incomplete = (
        not parsed_spec.is_valid or
        parsed_spec.title == "unknown" or
        not parsed_spec.endpoints
    )
    
    if not is_incomplete:
        # Spec is complete, check that missing_info is minimal
        if len(validated.missing_info) <= 1:
            return 1.0
        return 0.8  # Slight penalty for unnecessary missing_info
    
    # Spec is incomplete - check for required items
    required_items = [
        "api spec",
        "openapi",
        "swagger",
        "yaml",
        "json",
        "auth",
        "authentication",
        "base url",
        "environment",
        "header"
    ]
    
    missing_info_text = " ".join(validated.missing_info).lower()
    
    found_items = sum(
        1 for item in required_items
        if item in missing_info_text
    )
    
    # Need at least 3 of the required items mentioned
    return min(1.0, found_items / 3)


# ========== INTERMEDIATE REWARD HOOKS ==========

def reward_parse_spec(state: Dict[str, Any]) -> float:
    """Intermediate reward for parse_spec node."""
    parsed_spec = state.get("parsed_spec")
    if not parsed_spec:
        return 0.0
    
    if parsed_spec.get("is_valid", False):
        return 0.5
    
    # Partial credit for partial parsing
    score = 0.0
    if parsed_spec.get("title") != "unknown":
        score += 0.1
    if parsed_spec.get("version") != "unknown":
        score += 0.1
    if parsed_spec.get("base_url") != "unknown":
        score += 0.1
    
    return score


def reward_detect_endpoints(state: Dict[str, Any]) -> float:
    """Intermediate reward for detect_endpoints node."""
    endpoints = state.get("endpoints", [])
    if not endpoints:
        return 0.0
    
    # More endpoints = higher reward (up to a point)
    return min(1.0, len(endpoints) * 0.15)


def reward_deep_research(state: Dict[str, Any]) -> float:
    """Intermediate reward for deep research nodes."""
    excerpts = state.get("memory_excerpts", [])
    plan = state.get("research_plan", [])
    
    score = 0.0
    
    # Reward for having a plan
    if plan:
        score += 0.2
    
    # Reward for excerpts
    if excerpts:
        score += min(0.5, len(excerpts) * 0.1)
    
    # Reward for diverse sources
    sources = set(e.get("source", "") for e in excerpts)
    score += min(0.3, len(sources) * 0.1)
    
    return min(1.0, score)


def reward_generate_tests(state: Dict[str, Any]) -> float:
    """Intermediate reward for generate_tests node."""
    draft = state.get("draft_output")
    if not draft:
        return 0.0
    
    test_suite = draft.get("test_suite", [])
    endpoints = state.get("endpoints", [])
    
    if not endpoints:
        # No endpoints, but we have output
        return 0.3
    
    # Tests per endpoint ratio
    ratio = len(test_suite) / len(endpoints) if endpoints else 0
    
    return min(1.0, ratio * 0.3)


def reward_finalize(state: Dict[str, Any]) -> float:
    """Intermediate reward for finalization/validation node."""
    if state.get("validated_output"):
        return 1.0
    return 0.0


def compute_intermediate_reward(node_name: str, state: Dict[str, Any]) -> float:
    """
    Compute node-level intermediate reward using canonical node names.

    Accepts both graph node names and legacy aliases.
    """
    normalized_name = node_name.strip().lower()

    reward_by_node = {
        # Parse + detect
        "parse_spec": reward_parse_spec,
        "parse_spec_node": reward_parse_spec,
        "detect_endpoints": reward_detect_endpoints,
        "detect_endpoints_node": reward_detect_endpoints,
        # Research
        "research_plan": reward_deep_research,
        "deep_research_plan": reward_deep_research,
        "research_search": reward_deep_research,
        "deep_research_search": reward_deep_research,
        "research_integrate": reward_deep_research,
        "deep_research_integrate": reward_deep_research,
        "research_reflect": reward_deep_research,
        "deep_research_reflect": reward_deep_research,
        # Generation + finalize
        "generate_tests": reward_generate_tests,
        "generate_tests_node": reward_generate_tests,
        "finalize": reward_finalize,
        "finalize_and_validate": reward_finalize,
        "finalize_and_validate_node": reward_finalize,
        "finalize_and_validate_json": reward_finalize,
    }

    reward_fn = reward_by_node.get(normalized_name)
    if not reward_fn:
        return 0.0
    return reward_fn(state)


# ========== REWARD FROM GOLD COMPARISON ==========

def compute_reward_with_gold(
    output_json: Dict[str, Any],
    spec_text: str,
    gold: Dict[str, Any]
) -> Tuple[float, RewardBreakdown]:
    """
    Compute reward comparing against gold standard.
    
    Args:
        output_json: Agent output
        spec_text: Original spec text
        gold: Gold standard with expected values
        
    Returns:
        Tuple of (reward, breakdown)
    """
    parsed_spec = parse_openapi_spec(spec_text)
    reward, breakdown = compute_reward(output_json, parsed_spec, gold)
    
    # Additional gold comparison if available
    if gold and reward > 0:
        gold_bonus = _compare_with_gold(output_json, gold)
        # Blend original reward with gold comparison
        reward = 0.7 * reward + 0.3 * gold_bonus
        breakdown.total_reward = reward
    
    return reward, breakdown


def _compare_with_gold(output: Dict[str, Any], gold: Dict[str, Any]) -> float:
    """Compare output with gold standard."""
    score = 0.0
    
    spec_summary = output.get("spec_summary", {})
    
    # Title match
    if spec_summary.get("title") == gold.get("title"):
        score += 0.2
    
    # Version match
    if spec_summary.get("version") == gold.get("version"):
        score += 0.1
    
    # Base URL match
    if spec_summary.get("base_url") == gold.get("base_url"):
        score += 0.1
    
    # Auth type match
    auth = spec_summary.get("auth", {})
    if auth.get("type") == gold.get("auth_type"):
        score += 0.2
    
    # Endpoint count match
    detected = spec_summary.get("endpoints_detected", [])
    gold_endpoints = gold.get("endpoints", [])
    
    if len(detected) == len(gold_endpoints):
        score += 0.2
    elif detected and gold_endpoints:
        # Partial credit
        score += 0.1 * min(len(detected), len(gold_endpoints)) / max(len(detected), len(gold_endpoints))
    
    # Endpoint path/method match
    detected_set = {(e.get("method"), e.get("path")) for e in detected}
    gold_set = {(e.get("method"), e.get("path")) for e in gold_endpoints}
    
    if detected_set and gold_set:
        overlap = len(detected_set & gold_set)
        score += 0.2 * overlap / len(gold_set)
    
    return min(1.0, score)
