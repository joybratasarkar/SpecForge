#!/usr/bin/env python3
"""
Agent Lightning training harness for SpecTestPilot.

Provides:
- Mock mode for local training without external API keys
- agent_run(task) function that runs the LangGraph agent
- Reward computation using gold standard
- Training loop with configurable hyperparameters
"""

import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Callable
from pathlib import Path

import numpy as np
from tqdm import tqdm

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# OpenAI client (optional, for real model training)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from spec_test_pilot.graph import run_agent, create_initial_state, compile_graph
from spec_test_pilot.reward import compute_reward_with_gold, RewardBreakdown
from spec_test_pilot.openapi_parse import parse_openapi_spec


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class TrainingConfig:
    """Training configuration."""
    # Data
    train_data_path: str = "data/train.jsonl"
    test_data_path: str = "data/test.jsonl"
    
    # Training
    epochs: int = 10
    batch_size: int = 32
    learning_rate: float = 1e-4
    
    # RL specific
    gamma: float = 0.99  # Discount factor
    epsilon: float = 0.1  # Exploration rate
    
    # Mock mode
    mock_mode: bool = True
    
    # Logging
    log_interval: int = 10
    eval_interval: int = 50
    save_interval: int = 100
    
    # Output
    output_dir: str = "checkpoints"
    
    # Reproducibility
    seed: int = 42


@dataclass
class TrainingMetrics:
    """Training metrics tracker."""
    epoch: int = 0
    step: int = 0
    total_reward: float = 0.0
    avg_reward: float = 0.0
    rewards_history: List[float] = field(default_factory=list)
    eval_rewards: List[float] = field(default_factory=list)
    
    def update(self, reward: float) -> None:
        """Update metrics with new reward."""
        self.step += 1
        self.total_reward += reward
        self.rewards_history.append(reward)
        self.avg_reward = self.total_reward / self.step
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "epoch": self.epoch,
            "step": self.step,
            "total_reward": self.total_reward,
            "avg_reward": self.avg_reward,
            "recent_avg": np.mean(self.rewards_history[-100:]) if self.rewards_history else 0.0
        }


# ============================================================================
# Mock LLM for local training
# ============================================================================

class MockLLM:
    """
    Deterministic stub LLM for mock mode training.
    
    Returns consistent, deterministic outputs based on input hashing.
    """
    
    def __init__(self, seed: int = 42):
        """Initialize mock LLM."""
        self.seed = seed
        self.call_count = 0
    
    def __call__(self, prompt: str) -> str:
        """Generate deterministic response based on prompt."""
        self.call_count += 1
        
        # Use hash of prompt for deterministic randomness
        prompt_hash = hash(prompt) % (2**32)
        rng = random.Random(prompt_hash + self.seed)
        
        # Generate mock response based on prompt content
        if "test case" in prompt.lower() or "generate" in prompt.lower():
            return self._generate_test_response(rng)
        elif "plan" in prompt.lower():
            return self._generate_plan_response(rng)
        elif "reflect" in prompt.lower():
            return self._generate_reflect_response(rng)
        else:
            return self._generate_generic_response(rng)
    
    def _generate_test_response(self, rng: random.Random) -> str:
        """Generate mock test case response."""
        return json.dumps({
            "test_id": f"T{rng.randint(1, 999):03d}",
            "name": "Mock test case",
            "objective": "Verify endpoint behavior"
        })
    
    def _generate_plan_response(self, rng: random.Random) -> str:
        """Generate mock plan response."""
        plans = [
            "Search for REST API testing conventions",
            "Find authentication patterns",
            "Look for validation testing examples"
        ]
        return json.dumps(rng.sample(plans, k=rng.randint(1, 3)))
    
    def _generate_reflect_response(self, rng: random.Random) -> str:
        """Generate mock reflection response."""
        return "Research complete. Found relevant patterns for test generation."
    
    def _generate_generic_response(self, rng: random.Random) -> str:
        """Generate generic response."""
        return "Acknowledged."


class OpenAILLM:
    """
    Real OpenAI LLM for production training.
    
    Uses the OpenAI API with the key from environment variables.
    """
    
    def __init__(
        self,
        model: str = "gpt-4",
        temperature: float = 0.7,
        max_tokens: int = 4096
    ):
        """
        Initialize OpenAI LLM.
        
        Args:
            model: Model name (gpt-4, gpt-3.5-turbo, etc.)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package not installed. Run: pip install openai")
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment. "
                "Set it in .env file or export it."
            )
        
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.call_count = 0
        self.total_tokens = 0
    
    def __call__(self, prompt: str, system_prompt: str = None) -> str:
        """
        Generate response using OpenAI API.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            
        Returns:
            Generated text response
        """
        self.call_count += 1
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            # Track token usage
            if response.usage:
                self.total_tokens += response.usage.total_tokens
            
            return response.choices[0].message.content
            
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return ""
    
    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return {
            "call_count": self.call_count,
            "total_tokens": self.total_tokens,
            "model": self.model
        }


def get_llm(mock_mode: bool = True, **kwargs) -> Any:
    """
    Get appropriate LLM based on mode.
    
    Args:
        mock_mode: If True, return MockLLM; otherwise return OpenAILLM
        **kwargs: Additional arguments for the LLM
        
    Returns:
        LLM instance
    """
    if mock_mode:
        return MockLLM(seed=kwargs.get("seed", 42))
    else:
        return OpenAILLM(
            model=kwargs.get("model", "gpt-4"),
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4096)
        )


# ============================================================================
# Agent Runner
# ============================================================================

@dataclass
class AgentRunResult:
    """Result of an agent run."""
    output: Dict[str, Any]
    reward: float
    breakdown: RewardBreakdown
    trace: List[Tuple[str, float]]  # (call_description, intermediate_reward)
    run_time: float
    run_id: str


def agent_run(
    task: Dict[str, Any],
    mock_llm: Optional[MockLLM] = None,
    verbose: bool = False
) -> AgentRunResult:
    """
    Run the LangGraph agent on a task.
    
    Args:
        task: Task dictionary with openapi_yaml and gold
        mock_llm: Optional mock LLM for testing
        verbose: Whether to print verbose output
        
    Returns:
        AgentRunResult with output, reward, and trace
    """
    start_time = time.time()
    
    # Extract task data
    task_id = task.get("task_id", "unknown")
    openapi_yaml = task.get("openapi_yaml", "")
    gold = task.get("gold", {})
    
    # Run the agent
    result = run_agent(openapi_yaml, run_id=task_id, verbose=verbose)
    
    # Compute reward
    output = result.get("output", {})
    reward, breakdown = compute_reward_with_gold(output, openapi_yaml, gold)
    
    # Build trace from intermediate rewards
    intermediate = result.get("intermediate_rewards", {})
    trace = [(name, value) for name, value in intermediate.items()]
    
    run_time = time.time() - start_time
    
    return AgentRunResult(
        output=output,
        reward=reward,
        breakdown=breakdown,
        trace=trace,
        run_time=run_time,
        run_id=task_id
    )


# ============================================================================
# Data Loading
# ============================================================================

def load_jsonl(path: str) -> List[Dict[str, Any]]:
    """Load JSONL file."""
    data = []
    with open(path, "r") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def create_batches(
    data: List[Dict[str, Any]],
    batch_size: int,
    shuffle: bool = True,
    seed: int = 42
) -> List[List[Dict[str, Any]]]:
    """Create batches from data."""
    if shuffle:
        rng = random.Random(seed)
        data = data.copy()
        rng.shuffle(data)
    
    batches = []
    for i in range(0, len(data), batch_size):
        batches.append(data[i:i + batch_size])
    
    return batches


# ============================================================================
# Training Loop
# ============================================================================

class AgentLightningTrainer:
    """
    Agent Lightning training harness.
    
    Supports mock mode for local training without external API keys.
    """
    
    def __init__(self, config: TrainingConfig):
        """Initialize trainer."""
        self.config = config
        self.metrics = TrainingMetrics()
        self.mock_llm = MockLLM(seed=config.seed) if config.mock_mode else None
        
        # Set random seeds
        random.seed(config.seed)
        np.random.seed(config.seed)
        
        # Create output directory
        os.makedirs(config.output_dir, exist_ok=True)
    
    def load_data(self) -> Tuple[List[Dict], List[Dict]]:
        """Load training and test data."""
        train_data = load_jsonl(self.config.train_data_path)
        test_data = load_jsonl(self.config.test_data_path)
        
        print(f"Loaded {len(train_data)} training examples")
        print(f"Loaded {len(test_data)} test examples")
        
        return train_data, test_data
    
    def train_step(self, batch: List[Dict[str, Any]]) -> List[AgentRunResult]:
        """Run a single training step on a batch."""
        results = []
        
        for task in batch:
            result = agent_run(task, mock_llm=self.mock_llm)
            results.append(result)
            self.metrics.update(result.reward)
        
        return results
    
    def evaluate(self, test_data: List[Dict[str, Any]], num_samples: int = 50) -> float:
        """Evaluate on test data."""
        # Sample subset for evaluation
        samples = random.sample(test_data, min(num_samples, len(test_data)))
        
        rewards = []
        for task in tqdm(samples, desc="Evaluating", leave=False):
            result = agent_run(task, mock_llm=self.mock_llm)
            rewards.append(result.reward)
        
        avg_reward = np.mean(rewards)
        self.metrics.eval_rewards.append(avg_reward)
        
        return avg_reward
    
    def save_checkpoint(self, epoch: int) -> str:
        """Save training checkpoint."""
        checkpoint = {
            "epoch": epoch,
            "metrics": self.metrics.to_dict(),
            "config": {
                "epochs": self.config.epochs,
                "batch_size": self.config.batch_size,
                "learning_rate": self.config.learning_rate,
                "mock_mode": self.config.mock_mode
            }
        }
        
        path = os.path.join(self.config.output_dir, f"checkpoint_epoch_{epoch}.json")
        with open(path, "w") as f:
            json.dump(checkpoint, f, indent=2)
        
        return path
    
    def train(self) -> TrainingMetrics:
        """Run full training loop."""
        print("=" * 60)
        print("Agent Lightning Training")
        print("=" * 60)
        print(f"Mock mode: {self.config.mock_mode}")
        print(f"Epochs: {self.config.epochs}")
        print(f"Batch size: {self.config.batch_size}")
        print("=" * 60)
        
        # Load data
        train_data, test_data = self.load_data()
        
        # Initial evaluation
        print("\nInitial evaluation...")
        initial_reward = self.evaluate(test_data)
        print(f"Initial avg reward: {initial_reward:.4f}")
        
        # Training loop
        for epoch in range(1, self.config.epochs + 1):
            self.metrics.epoch = epoch
            print(f"\n{'='*60}")
            print(f"Epoch {epoch}/{self.config.epochs}")
            print(f"{'='*60}")
            
            # Create batches
            batches = create_batches(
                train_data,
                self.config.batch_size,
                shuffle=True,
                seed=self.config.seed + epoch
            )
            
            # Train on batches
            epoch_rewards = []
            pbar = tqdm(batches, desc=f"Epoch {epoch}")
            
            for batch_idx, batch in enumerate(pbar):
                results = self.train_step(batch)
                batch_rewards = [r.reward for r in results]
                epoch_rewards.extend(batch_rewards)
                
                # Update progress bar
                pbar.set_postfix({
                    "batch_reward": f"{np.mean(batch_rewards):.4f}",
                    "avg_reward": f"{self.metrics.avg_reward:.4f}"
                })
                
                # Periodic evaluation
                if (batch_idx + 1) % self.config.eval_interval == 0:
                    eval_reward = self.evaluate(test_data, num_samples=20)
                    print(f"\n  Eval reward at step {self.metrics.step}: {eval_reward:.4f}")
            
            # End of epoch stats
            epoch_avg = np.mean(epoch_rewards)
            print(f"\nEpoch {epoch} complete:")
            print(f"  Avg reward: {epoch_avg:.4f}")
            print(f"  Total steps: {self.metrics.step}")
            
            # Save checkpoint
            if epoch % (self.config.epochs // 5 + 1) == 0:
                path = self.save_checkpoint(epoch)
                print(f"  Saved checkpoint: {path}")
        
        # Final evaluation
        print("\n" + "=" * 60)
        print("Final evaluation...")
        final_reward = self.evaluate(test_data, num_samples=100)
        print(f"Final avg reward: {final_reward:.4f}")
        print(f"Improvement: {final_reward - initial_reward:+.4f}")
        
        # Save final checkpoint
        self.save_checkpoint(self.config.epochs)
        
        return self.metrics


# ============================================================================
# Real Model Endpoint Configuration (Placeholder)
# ============================================================================

@dataclass
class ModelEndpointConfig:
    """
    Configuration for real model endpoint.
    
    Placeholder for when you want to use a real LLM API.
    """
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""  # Set via environment variable
    model_name: str = "gpt-4"
    max_tokens: int = 4096
    temperature: float = 0.7
    
    @classmethod
    def from_env(cls) -> "ModelEndpointConfig":
        """Create config from environment variables."""
        return cls(
            api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model_name=os.getenv("MODEL_NAME", "gpt-4"),
            max_tokens=int(os.getenv("MAX_TOKENS", "4096")),
            temperature=float(os.getenv("TEMPERATURE", "0.7"))
        )


# ============================================================================
# CLI
# ============================================================================

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Agent Lightning training harness for SpecTestPilot"
    )
    
    # Mode
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode (no external API keys required)"
    )
    
    # Data
    parser.add_argument(
        "--train-data",
        default="data/train.jsonl",
        help="Path to training data"
    )
    parser.add_argument(
        "--test-data",
        default="data/test.jsonl",
        help="Path to test data"
    )
    
    # Training
    parser.add_argument(
        "--epochs",
        type=int,
        default=10,
        help="Number of training epochs"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size"
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=1e-4,
        help="Learning rate"
    )
    
    # Output
    parser.add_argument(
        "--output-dir",
        default="checkpoints",
        help="Output directory for checkpoints"
    )
    
    # Reproducibility
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed"
    )
    
    args = parser.parse_args()
    
    # Create config
    config = TrainingConfig(
        train_data_path=args.train_data,
        test_data_path=args.test_data,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        mock_mode=args.mock,
        output_dir=args.output_dir,
        seed=args.seed
    )
    
    # Check for data files
    if not os.path.exists(config.train_data_path):
        print(f"Training data not found: {config.train_data_path}")
        print("Run 'python data/generate_dataset.py' first to generate the dataset.")
        return
    
    if not os.path.exists(config.test_data_path):
        print(f"Test data not found: {config.test_data_path}")
        print("Run 'python data/generate_dataset.py' first to generate the dataset.")
        return
    
    # Run training
    trainer = AgentLightningTrainer(config)
    metrics = trainer.train()
    
    print("\n" + "=" * 60)
    print("Training Complete!")
    print("=" * 60)
    print(f"Final metrics: {json.dumps(metrics.to_dict(), indent=2)}")


if __name__ == "__main__":
    main()
