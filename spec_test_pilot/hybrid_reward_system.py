"""
Hybrid Reward System for SpecTestPilot.

Combines rule-based and LLM-based scoring for optimal evaluation:

1. Rule-based (Fast): Basic validation and structural checks
2. LLM-based (Smart): Context-aware quality evaluation  
3. Hybrid (Best): Blends both approaches

Customers can choose their preferred scoring method based on:
- Speed requirements
- Cost considerations  
- Evaluation accuracy needs
"""

import time
from typing import Dict, List, Any, Tuple, Optional, Literal
from dataclasses import dataclass

from spec_test_pilot.reward import compute_reward, RewardBreakdown
from spec_test_pilot.llm_reward_judge import compute_llm_reward, LLMJudgeScore
from spec_test_pilot.openapi_parse import parse_openapi_spec, ParsedSpec


@dataclass
class HybridRewardScore:
    """Combined scoring result with multiple perspectives."""
    # Final scores
    rule_score: float
    llm_score: float
    hybrid_score: float
    
    # Component breakdowns
    rule_breakdown: RewardBreakdown
    llm_breakdown: LLMJudgeScore
    
    # Metadata
    evaluation_time: float
    method_used: str
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_scores": {
                "rule_based": self.rule_score,
                "llm_based": self.llm_score,
                "hybrid": self.hybrid_score
            },
            "rule_breakdown": self.rule_breakdown.to_dict(),
            "llm_breakdown": self.llm_breakdown.to_dict(),
            "metadata": {
                "evaluation_time": self.evaluation_time,
                "method_used": self.method_used,
                "confidence": self.confidence
            }
        }


class HybridRewardSystem:
    """
    Configurable reward system supporting multiple evaluation methods.
    
    Methods:
    - "rule": Fast rule-based scoring (0.001s)
    - "llm": LLM-based evaluation (2-5s, costs API calls)
    - "hybrid": Blend both methods (2-5s)
    - "adaptive": Choose method based on spec complexity
    """
    
    def __init__(
        self,
        method: Literal["rule", "llm", "hybrid", "adaptive"] = "hybrid",
        llm_weight: float = 0.7,
        rule_weight: float = 0.3,
        adaptive_threshold: int = 5  # Endpoints
    ):
        """
        Initialize hybrid reward system.
        
        Args:
            method: Scoring method to use
            llm_weight: Weight for LLM score in hybrid mode
            rule_weight: Weight for rule score in hybrid mode  
            adaptive_threshold: Endpoint count threshold for adaptive mode
        """
        self.method = method
        self.llm_weight = llm_weight
        self.rule_weight = rule_weight
        self.adaptive_threshold = adaptive_threshold
        
        # Validate weights
        if abs(llm_weight + rule_weight - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0, got {llm_weight + rule_weight}")
        
        # Statistics
        self.stats = {
            "total_evaluations": 0,
            "rule_count": 0,
            "llm_count": 0,
            "hybrid_count": 0,
            "total_time": 0.0,
            "avg_rule_score": 0.0,
            "avg_llm_score": 0.0
        }
    
    def compute_reward(
        self,
        output_json: Dict[str, Any],
        spec_text: str,
        gold: Optional[Dict[str, Any]] = None,
        context: Optional[str] = None
    ) -> Tuple[float, HybridRewardScore]:
        """
        Compute reward using the configured method.
        
        Returns:
            (final_reward, detailed_score)
        """
        start_time = time.time()
        parsed_spec = parse_openapi_spec(spec_text)
        
        # Choose evaluation method
        actual_method = self._choose_method(parsed_spec)
        
        # Get rule-based score (always computed for fallback)
        rule_reward, rule_breakdown = compute_reward(output_json, parsed_spec, gold)
        
        if actual_method == "rule":
            # Rule-based only
            hybrid_score = HybridRewardScore(
                rule_score=rule_reward,
                llm_score=rule_reward,  # Use rule score
                hybrid_score=rule_reward,
                rule_breakdown=rule_breakdown,
                llm_breakdown=self._create_mock_llm_score(rule_reward),
                evaluation_time=time.time() - start_time,
                method_used="rule_only"
            )
            self.stats["rule_count"] += 1
            
        elif actual_method == "llm":
            # LLM-based only
            llm_reward, llm_breakdown = compute_llm_reward(
                output_json, spec_text, gold, context
            )
            
            hybrid_score = HybridRewardScore(
                rule_score=rule_reward,
                llm_score=llm_reward,
                hybrid_score=llm_reward,
                rule_breakdown=rule_breakdown,
                llm_breakdown=llm_breakdown,
                evaluation_time=time.time() - start_time,
                method_used="llm_only"
            )
            self.stats["llm_count"] += 1
            
        else:  # hybrid
            # Blend both methods
            llm_reward, llm_breakdown = compute_llm_reward(
                output_json, spec_text, gold, context
            )
            
            # Calculate hybrid score
            blended_reward = (
                self.llm_weight * llm_reward +
                self.rule_weight * rule_reward
            )
            
            hybrid_score = HybridRewardScore(
                rule_score=rule_reward,
                llm_score=llm_reward,
                hybrid_score=blended_reward,
                rule_breakdown=rule_breakdown,
                llm_breakdown=llm_breakdown,
                evaluation_time=time.time() - start_time,
                method_used="hybrid",
                confidence=self._calculate_confidence(rule_reward, llm_reward)
            )
            self.stats["hybrid_count"] += 1
        
        # Update statistics
        self._update_stats(hybrid_score)
        
        return hybrid_score.hybrid_score, hybrid_score
    
    def _choose_method(self, parsed_spec: ParsedSpec) -> str:
        """Choose evaluation method based on configuration and spec complexity."""
        if self.method != "adaptive":
            return self.method
        
        # Adaptive method selection
        num_endpoints = len(parsed_spec.endpoints)
        
        if num_endpoints <= 2:
            return "rule"  # Simple APIs - rule-based is sufficient
        elif num_endpoints <= self.adaptive_threshold:
            return "hybrid"  # Medium complexity - blend both
        else:
            return "llm"  # Complex APIs - LLM evaluation needed
    
    def _create_mock_llm_score(self, rule_reward: float) -> LLMJudgeScore:
        """Create mock LLM score when only using rule-based."""
        return LLMJudgeScore(
            total_score=rule_reward,
            completeness=rule_reward,
            correctness=rule_reward,
            best_practices=rule_reward,
            edge_cases=rule_reward,
            feedback="Rule-based evaluation only (no LLM)",
            strengths=["Fast evaluation"],
            weaknesses=["Limited context awareness"]
        )
    
    def _calculate_confidence(self, rule_score: float, llm_score: float) -> float:
        """Calculate confidence based on agreement between methods."""
        diff = abs(rule_score - llm_score)
        # High confidence when scores agree, low when they disagree
        confidence = max(0.1, 1.0 - (diff * 2))
        return confidence
    
    def _update_stats(self, score: HybridRewardScore):
        """Update running statistics."""
        self.stats["total_evaluations"] += 1
        self.stats["total_time"] += score.evaluation_time
        
        # Running averages
        n = self.stats["total_evaluations"]
        self.stats["avg_rule_score"] = (
            (self.stats["avg_rule_score"] * (n-1) + score.rule_score) / n
        )
        self.stats["avg_llm_score"] = (
            (self.stats["avg_llm_score"] * (n-1) + score.llm_score) / n
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get evaluation statistics."""
        n = max(self.stats["total_evaluations"], 1)
        return {
            **self.stats,
            "avg_evaluation_time": self.stats["total_time"] / n,
            "method_distribution": {
                "rule": self.stats["rule_count"] / n,
                "llm": self.stats["llm_count"] / n, 
                "hybrid": self.stats["hybrid_count"] / n
            }
        }


# Factory functions for easy customer configuration
def create_fast_reward_system() -> HybridRewardSystem:
    """Create fast rule-based system for high-volume scenarios."""
    return HybridRewardSystem(method="rule")


def create_accurate_reward_system() -> HybridRewardSystem:
    """Create LLM-based system for maximum accuracy.""" 
    return HybridRewardSystem(method="llm")


def create_balanced_reward_system() -> HybridRewardSystem:
    """Create balanced hybrid system (recommended)."""
    return HybridRewardSystem(method="hybrid", llm_weight=0.7, rule_weight=0.3)


def create_adaptive_reward_system(simple_threshold: int = 3) -> HybridRewardSystem:
    """Create adaptive system that chooses method based on API complexity."""
    return HybridRewardSystem(method="adaptive", adaptive_threshold=simple_threshold)


# Example demonstration
if __name__ == "__main__":
    import json
    from pathlib import Path
    
    def demo_all_systems():
        """Demo all reward systems on the same test case."""
        print("🧪 Reward System Comparison Demo\n")
        
        # Load test data
        with open("example_output.json", "r") as f:
            output = json.load(f)
        with open("sample_api.yaml", "r") as f:
            spec = f.read()
        
        # Test all systems
        systems = {
            "Fast (Rules Only)": create_fast_reward_system(),
            "Accurate (LLM Only)": create_accurate_reward_system(),
            "Balanced (Hybrid)": create_balanced_reward_system(),
            "Adaptive": create_adaptive_reward_system()
        }
        
        results = {}
        for name, system in systems.items():
            print(f"Testing {name}...")
            reward, score = system.compute_reward(output, spec)
            results[name] = {
                "reward": reward,
                "time": score.evaluation_time,
                "method": score.method_used
            }
        
        # Print comparison
        print("\n📊 Results Comparison:")
        print(f"{'System':<20} {'Score':<8} {'Time':<8} {'Method'}")
        print("-" * 50)
        for name, result in results.items():
            print(f"{name:<20} {result['reward']:.4f}   {result['time']:.3f}s  {result['method']}")
        
        return results
    
    demo_all_systems()
