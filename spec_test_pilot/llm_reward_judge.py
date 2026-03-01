"""
LLM-based Reward Judge for SpecTestPilot.

Uses an LLM to evaluate the quality of generated test cases instead of 
purely rule-based scoring. This provides more nuanced evaluation that
considers context, API domain, and testing best practices.

The LLM judge evaluates:
1. Completeness - Are all endpoints adequately tested?
2. Correctness - Do the tests make sense for this specific API?
3. Best Practices - Do tests follow API testing conventions?
4. Edge Cases - Are important edge cases covered?
"""

import json
import time
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass

from spec_test_pilot.openapi_parse import ParsedSpec
from agent_lightning_integration.llm_client import get_llm_client


@dataclass
class LLMJudgeScore:
    """Detailed score from LLM judge."""
    # Overall score
    total_score: float  # 0-1
    
    # Component scores
    completeness: float = 0.0      # 0-1
    correctness: float = 0.0       # 0-1
    best_practices: float = 0.0    # 0-1
    edge_cases: float = 0.0        # 0-1
    
    # Analysis
    feedback: str = ""
    strengths: List[str] = None
    weaknesses: List[str] = None
    suggestions: List[str] = None
    
    def __post_init__(self):
        if self.strengths is None:
            self.strengths = []
        if self.weaknesses is None:
            self.weaknesses = []
        if self.suggestions is None:
            self.suggestions = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_score": self.total_score,
            "components": {
                "completeness": self.completeness,
                "correctness": self.correctness,
                "best_practices": self.best_practices,
                "edge_cases": self.edge_cases
            },
            "feedback": self.feedback,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions
        }


class LLMRewardJudge:
    """
    LLM-based reward judge for test case quality.
    
    This judge uses a language model to evaluate the quality of generated
    test cases in the context of the specific API being tested.
    """
    
    def __init__(self, model: str = "gpt-4", temperature: float = 0.1):
        """
        Initialize the LLM judge.
        
        Args:
            model: Model to use for evaluation
            temperature: Low temperature for consistent scoring
        """
        self.model = model
        self.temperature = temperature
        self.llm_client = get_llm_client()
        
        # Configure for consistent evaluation
        self.llm_client.configure(
            model=model,
            temperature=temperature,
            max_tokens=2048
        )
    
    def judge_test_quality(
        self,
        output_json: Dict[str, Any],
        spec_text: str,
        parsed_spec: ParsedSpec,
        context: Optional[str] = None
    ) -> LLMJudgeScore:
        """
        Judge the quality of generated test cases using LLM.
        
        Args:
            output_json: Generated test cases
            spec_text: Original OpenAPI spec
            parsed_spec: Parsed spec object
            context: Optional context about the API domain
            
        Returns:
            Detailed LLM score and feedback
        """
        # Build evaluation prompt
        prompt = self._build_evaluation_prompt(
            output_json, spec_text, parsed_spec, context
        )
        
        try:
            # Get LLM evaluation
            response = self.llm_client.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                model=self.model,
                temperature=self.temperature
            )
            
            # Parse LLM response
            return self._parse_llm_response(response)
            
        except Exception as e:
            print(f"⚠️  LLM judge failed: {e}")
            # Fallback to rule-based scoring
            from spec_test_pilot.reward import compute_reward
            reward, breakdown = compute_reward(output_json, parsed_spec)
            
            return LLMJudgeScore(
                total_score=reward,
                completeness=breakdown.endpoint_coverage,
                correctness=1.0 if breakdown.pydantic_valid else 0.0,
                best_practices=breakdown.negative_quality,
                edge_cases=breakdown.auth_negative,
                feedback=f"LLM judge failed, used rule-based scoring: {reward:.3f}",
                weaknesses=["LLM evaluation unavailable"]
            )
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for LLM judge."""
        return """You are an expert API testing consultant. Your job is to evaluate the quality of automatically generated API test cases.

You will be given:
1. An OpenAPI specification (the API documentation)
2. Generated test cases in JSON format

Evaluate the test cases on these criteria:

**Completeness (0-1)**: Are all endpoints adequately tested? Each endpoint should have:
- At least 1 happy path test
- At least 1 error/validation test  
- Auth tests if authentication is required

**Correctness (0-1)**: Do the tests make sense for this specific API?
- Are HTTP methods correct?
- Are expected status codes realistic?
- Do request bodies match the API schema?
- Are path parameters handled correctly?

**Best Practices (0-1)**: Do tests follow API testing conventions?
- Include boundary testing?
- Test required vs optional fields?
- Cover different auth scenarios?
- Include proper error messages validation?

**Edge Cases (0-1)**: Are important edge cases covered?
- Invalid data types?
- Missing required fields?
- Malformed requests?
- Boundary values?

Respond in JSON format:
{
  "completeness": 0.85,
  "correctness": 0.92,
  "best_practices": 0.78,
  "edge_cases": 0.65,
  "total_score": 0.80,
  "feedback": "Overall assessment...",
  "strengths": ["Good coverage of auth scenarios", "..."],
  "weaknesses": ["Missing boundary testing", "..."], 
  "suggestions": ["Add tests for invalid ID formats", "..."]
}

Be objective and consistent. Focus on API testing quality, not JSON formatting."""
    
    def _build_evaluation_prompt(
        self,
        output_json: Dict[str, Any],
        spec_text: str,
        parsed_spec: ParsedSpec,
        context: Optional[str] = None
    ) -> str:
        """Build the evaluation prompt."""
        # Extract key info
        spec_summary = output_json.get("spec_summary", {})
        test_suite = output_json.get("test_suite", [])
        endpoints = spec_summary.get("endpoints_detected", [])
        
        # Build prompt
        prompt_parts = [
            "# API Testing Quality Evaluation",
            "",
            "## OpenAPI Specification Summary",
            f"**API**: {spec_summary.get('title', 'Unknown API')}",
            f"**Base URL**: {spec_summary.get('base_url', 'unknown')}",
            f"**Auth Type**: {spec_summary.get('auth', {}).get('type', 'unknown')}",
            f"**Endpoints**: {len(endpoints)} endpoints detected",
            "",
            "### Endpoints in Spec:",
        ]
        
        for ep in endpoints[:10]:  # Limit for prompt size
            prompt_parts.append(f"- {ep.get('method')} {ep.get('path')} ({ep.get('operation_id', 'no ID')})")
        
        if len(endpoints) > 10:
            prompt_parts.append(f"... and {len(endpoints) - 10} more endpoints")
        
        prompt_parts.extend([
            "",
            "## Generated Test Cases",
            f"**Total Tests**: {len(test_suite)}",
            "",
        ])
        
        # Add sample test cases
        for i, test in enumerate(test_suite[:8]):  # Show first 8 tests
            prompt_parts.extend([
                f"### Test {i+1}: {test.get('name', 'Unnamed')}",
                f"- **Endpoint**: {test.get('endpoint', {}).get('method')} {test.get('endpoint', {}).get('path')}",
                f"- **Objective**: {test.get('objective', 'No objective')}",
                f"- **Expected Status**: {[a.get('expected') for a in test.get('assertions', []) if a.get('type') == 'status_code']}",
                ""
            ])
        
        if len(test_suite) > 8:
            prompt_parts.append(f"... and {len(test_suite) - 8} more tests")
        
        # Add context if provided
        if context:
            prompt_parts.extend([
                "",
                f"## Additional Context",
                context
            ])
        
        prompt_parts.extend([
            "",
            "## Your Task",
            "Evaluate the quality of these generated test cases for this specific API.",
            "Consider the API's domain, endpoints, authentication, and expected usage patterns.",
            "Provide scores (0-1) for completeness, correctness, best_practices, and edge_cases.",
            "Calculate a weighted total_score and provide constructive feedback."
        ])
        
        return "\n".join(prompt_parts)
    
    def _parse_llm_response(self, response: str) -> LLMJudgeScore:
        """Parse LLM response into structured score."""
        try:
            # Try to extract JSON from response
            response = response.strip()
            if response.startswith("```json"):
                response = response.split("```json")[1].split("```")[0]
            elif response.startswith("```"):
                response = response.split("```")[1].split("```")[0]
            
            data = json.loads(response)
            
            # Extract scores
            completeness = float(data.get("completeness", 0))
            correctness = float(data.get("correctness", 0))
            best_practices = float(data.get("best_practices", 0))
            edge_cases = float(data.get("edge_cases", 0))
            
            # Calculate total score if not provided
            total_score = data.get("total_score")
            if total_score is None:
                # Weighted average
                total_score = (
                    completeness * 0.3 +
                    correctness * 0.3 +
                    best_practices * 0.25 +
                    edge_cases * 0.15
                )
            
            return LLMJudgeScore(
                total_score=max(0.0, min(1.0, float(total_score))),
                completeness=max(0.0, min(1.0, completeness)),
                correctness=max(0.0, min(1.0, correctness)),
                best_practices=max(0.0, min(1.0, best_practices)),
                edge_cases=max(0.0, min(1.0, edge_cases)),
                feedback=data.get("feedback", ""),
                strengths=data.get("strengths", []),
                weaknesses=data.get("weaknesses", []),
                suggestions=data.get("suggestions", [])
            )
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"⚠️  Failed to parse LLM judge response: {e}")
            print(f"Response: {response[:200]}...")
            
            # Fallback score
            return LLMJudgeScore(
                total_score=0.5,
                feedback=f"Failed to parse LLM response: {str(e)[:100]}",
                weaknesses=["LLM response parsing failed"]
            )


def compute_llm_reward(
    output_json: Dict[str, Any],
    spec_text: str,
    gold: Optional[Dict[str, Any]] = None,
    context: Optional[str] = None
) -> Tuple[float, LLMJudgeScore]:
    """
    Compute reward using LLM as judge.
    
    Args:
        output_json: Generated test cases
        spec_text: Original OpenAPI spec
        gold: Optional gold standard (not used by LLM judge)
        context: Optional context about the API
        
    Returns:
        Tuple of (reward_float, detailed_score)
    """
    # First do basic validation
    from spec_test_pilot.reward import compute_reward
    from spec_test_pilot.openapi_parse import parse_openapi_spec
    
    parsed_spec = parse_openapi_spec(spec_text)
    rule_reward, rule_breakdown = compute_reward(output_json, parsed_spec)
    
    # If basic validation fails, don't bother with LLM
    if rule_reward == 0.0:
        return rule_reward, LLMJudgeScore(
            total_score=0.0,
            feedback="Failed basic validation (hard gates)",
            weaknesses=[
                f"Valid JSON: {rule_breakdown.valid_json}",
                f"Schema valid: {rule_breakdown.pydantic_valid}",
                f"No invented endpoints: {rule_breakdown.no_invented_endpoints}"
            ]
        )
    
    # Use LLM judge for quality evaluation
    judge = LLMRewardJudge()
    llm_score = judge.judge_test_quality(output_json, spec_text, parsed_spec, context)
    
    # Blend LLM score with rule-based score (70% LLM, 30% rules)
    blended_score = 0.7 * llm_score.total_score + 0.3 * rule_reward
    llm_score.total_score = max(0.0, min(1.0, blended_score))
    
    return llm_score.total_score, llm_score


def compare_reward_systems(
    output_json: Dict[str, Any],
    spec_text: str
) -> Dict[str, Any]:
    """
    Compare rule-based vs LLM-based scoring for analysis.
    
    Returns:
        Comparison results
    """
    from spec_test_pilot.reward import compute_reward
    from spec_test_pilot.openapi_parse import parse_openapi_spec
    
    parsed_spec = parse_openapi_spec(spec_text)
    
    # Rule-based scoring
    rule_start = time.time()
    rule_reward, rule_breakdown = compute_reward(output_json, parsed_spec)
    rule_time = time.time() - rule_start
    
    # LLM-based scoring
    llm_start = time.time()
    llm_reward, llm_score = compute_llm_reward(output_json, spec_text)
    llm_time = time.time() - llm_start
    
    return {
        "rule_based": {
            "reward": rule_reward,
            "breakdown": rule_breakdown.to_dict(),
            "evaluation_time": rule_time
        },
        "llm_based": {
            "reward": llm_reward,
            "breakdown": llm_score.to_dict(),
            "evaluation_time": llm_time
        },
        "difference": {
            "reward_diff": llm_reward - rule_reward,
            "time_diff": llm_time - rule_time,
            "speed_ratio": rule_time / llm_time if llm_time > 0 else float('inf')
        }
    }


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    
    async def test_llm_judge():
        """Test the LLM judge on sample data."""
        # Load sample spec
        spec_path = Path("sample_api.yaml")
        if not spec_path.exists():
            print("❌ sample_api.yaml not found")
            return
        
        spec_text = spec_path.read_text()
        
        # Load sample output
        output_path = Path("example_output.json")
        if not output_path.exists():
            print("❌ example_output.json not found")
            return
        
        with open(output_path) as f:
            output_json = json.load(f)
        
        # Compare scoring systems
        print("🧪 Comparing Rule-based vs LLM-based Scoring...")
        comparison = compare_reward_systems(output_json, spec_text)
        
        print("\n📊 Results:")
        print(f"Rule-based Score: {comparison['rule_based']['reward']:.4f}")
        print(f"LLM-based Score:  {comparison['llm_based']['reward']:.4f}")
        print(f"Difference:       {comparison['difference']['reward_diff']:+.4f}")
        
        print(f"\nLLM Feedback: {comparison['llm_based']['breakdown']['feedback']}")
        
        if comparison['llm_based']['breakdown']['strengths']:
            print("\n✅ Strengths:")
            for strength in comparison['llm_based']['breakdown']['strengths']:
                print(f"   • {strength}")
        
        if comparison['llm_based']['breakdown']['weaknesses']:
            print("\n⚠️  Weaknesses:")
            for weakness in comparison['llm_based']['breakdown']['weaknesses']:
                print(f"   • {weakness}")
    
    asyncio.run(test_llm_judge())
