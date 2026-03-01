#!/usr/bin/env python3
"""
Official Agent Lightning Implementation
Based on Microsoft Agent Lightning documentation: 
https://microsoft.github.io/agent-lightning/latest/how-to/train-first-agent/

Core concepts from the official docs:
- Tasks: Specific input/problem statements
- Rollouts: Complete execution traces from task to reward
- Spans: Individual units of work (LLM calls, tool usage, etc.)
- Prompt Templates: Reusable instructions that get optimized
- APO Algorithm: Automatic Prompt Optimization via textual gradients
- Trainer: Central orchestrator that manages the training loop
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Callable, Union
from enum import Enum
import logging
from collections import defaultdict
import openai

# Optional ML dependencies for advanced training
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


@dataclass
class Task:
    """
    A specific input or problem statement given to the agent.
    From docs: "defines what the agent needs to accomplish"
    """
    task_id: str
    input_data: Dict[str, Any]
    expected_output: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class Span:
    """
    A single unit of work within a rollout.
    From docs: "building blocks of a trace" with start/end times
    """
    span_id: str
    rollout_id: str
    operation_type: str  # "llm_call", "tool_use", "reward_calculation"
    start_time: float
    end_time: float
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_span_id: Optional[str] = None


@dataclass
class Rollout:
    """
    A single, complete execution of an agent attempting to solve a task.
    From docs: "captures a full trace of the agent's execution"
    """
    rollout_id: str
    task: Task
    spans: List[Span]
    final_reward: float
    status: str  # "completed", "failed", "timeout"
    start_time: float
    end_time: float
    agent_output: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptTemplate:
    """
    A reusable instruction for the agent with placeholders.
    From docs: "key resource that the algorithm learns and improves"
    """
    template_id: str
    content: str
    version: int = 1
    performance_score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class APOAlgorithm:
    """
    Automatic Prompt Optimization Algorithm
    From docs: Evaluate → Critique → Rewrite cycle using LLMs
    """
    
    def __init__(self, openai_client: openai.AsyncOpenAI):
        self.openai_client = openai_client
        self.logger = logging.getLogger(__name__)
    
    async def evaluate_prompt(
        self, 
        prompt_template: PromptTemplate,
        rollouts: List[Rollout]
    ) -> float:
        """Step 1: Evaluate current prompt performance."""
        if not rollouts:
            return 0.0
        
        total_reward = sum(r.final_reward for r in rollouts)
        avg_reward = total_reward / len(rollouts)
        
        self.logger.info(f"Prompt evaluation: {avg_reward:.3f} avg reward from {len(rollouts)} rollouts")
        return avg_reward
    
    async def critique_prompt(
        self,
        prompt_template: PromptTemplate,
        rollouts: List[Rollout]
    ) -> str:
        """Step 2: Generate textual gradient critique."""
        
        # Analyze rollout patterns
        failed_rollouts = [r for r in rollouts if r.final_reward < 0.5]
        successful_rollouts = [r for r in rollouts if r.final_reward >= 0.8]
        
        critique_prompt = f"""
        Analyze this agent prompt and its performance:
        
        PROMPT: {prompt_template.content}
        
        PERFORMANCE DATA:
        - Total rollouts: {len(rollouts)}
        - Failed rollouts: {len(failed_rollouts)}
        - Successful rollouts: {len(successful_rollouts)}
        - Average reward: {sum(r.final_reward for r in rollouts) / len(rollouts):.3f}
        
        Provide a detailed critique of what's wrong with this prompt and how to improve it.
        Focus on clarity, specificity, and task guidance.
        """
        
        response = await self.openai_client.chat.completions.create(
            model="gpt-4",  # Use gpt-4 for critique as per docs
            messages=[{"role": "user", "content": critique_prompt}],
            temperature=0.3
        )
        
        critique = response.choices[0].message.content
        self.logger.info(f"Generated critique: {critique[:100]}...")
        return critique
    
    async def rewrite_prompt(
        self,
        original_prompt: PromptTemplate,
        critique: str
    ) -> PromptTemplate:
        """Step 3: Apply critique to generate improved prompt."""
        
        rewrite_prompt = f"""
        You are an expert prompt engineer. Improve this agent prompt based on the critique:
        
        ORIGINAL PROMPT:
        {original_prompt.content}
        
        CRITIQUE:
        {critique}
        
        INSTRUCTIONS:
        1. Keep the core functionality intact
        2. Address the specific issues mentioned in the critique
        3. Make the prompt clearer and more specific
        4. Maintain any placeholders ({{variable}}) that exist
        
        Return ONLY the improved prompt, nothing else.
        """
        
        response = await self.openai_client.chat.completions.create(
            model="gpt-4",  # Use gpt-4 for rewriting
            messages=[{"role": "user", "content": rewrite_prompt}],
            temperature=0.5
        )
        
        improved_content = response.choices[0].message.content
        
        improved_template = PromptTemplate(
            template_id=str(uuid.uuid4()),
            content=improved_content,
            version=original_prompt.version + 1,
            metadata={"parent_template": original_prompt.template_id, "critique": critique}
        )
        
        self.logger.info(f"Generated improved prompt v{improved_template.version}")
        return improved_template


class AgentRunner:
    """
    Executes agent rollouts and captures spans.
    Integrates with existing SpecTestPilot agent.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def execute_rollout(
        self, 
        agent_function: Callable,
        task: Task,
        prompt_template: PromptTemplate
    ) -> Rollout:
        """Execute a complete agent rollout with span capture."""
        
        rollout_id = str(uuid.uuid4())
        start_time = time.time()
        spans = []
        
        try:
            # Create task execution span
            task_span = Span(
                span_id=str(uuid.uuid4()),
                rollout_id=rollout_id,
                operation_type="task_execution",
                start_time=start_time,
                end_time=start_time,  # Will update
                input_data={
                    "task": task.input_data,
                    "prompt_template": prompt_template.content
                }
            )
            
            # Prepare input with prompt template
            enhanced_input = task.input_data.copy()
            enhanced_input['nlp_prompt'] = prompt_template.content.format(**task.input_data)
            
            # Execute the agent
            self.logger.info(f"Executing rollout {rollout_id} for task {task.task_id}")
            
            # Import and run existing SpecTestPilot agent
            from .sandbox import AgentLightningSandbox
            sandbox = AgentLightningSandbox()
            
            agent_start = time.time()
            result = sandbox.execute_agent_task(enhanced_input)
            agent_end = time.time()
            
            # Update task span
            task_span.end_time = agent_end
            task_span.output_data = result
            spans.append(task_span)
            
            # Create agent execution span
            agent_span = Span(
                span_id=str(uuid.uuid4()),
                rollout_id=rollout_id,
                operation_type="agent_execution",
                start_time=agent_start,
                end_time=agent_end,
                input_data=enhanced_input,
                output_data=result,
                parent_span_id=task_span.span_id
            )
            spans.append(agent_span)
            
            # Calculate reward based on agent performance
            reward_start = time.time()
            reward = self._calculate_reward(result, task)
            reward_end = time.time()
            
            # Create reward span
            reward_span = Span(
                span_id=str(uuid.uuid4()),
                rollout_id=rollout_id,
                operation_type="reward_calculation",
                start_time=reward_start,
                end_time=reward_end,
                input_data={"result": result, "task": task.input_data},
                output_data={"reward": reward},
                parent_span_id=task_span.span_id
            )
            spans.append(reward_span)
            
            end_time = time.time()
            
            rollout = Rollout(
                rollout_id=rollout_id,
                task=task,
                spans=spans,
                final_reward=reward,
                status="completed",
                start_time=start_time,
                end_time=end_time,
                agent_output=result
            )
            
            self.logger.info(f"Rollout {rollout_id} completed: reward={reward:.3f}, duration={end_time-start_time:.2f}s")
            return rollout
            
        except Exception as e:
            self.logger.error(f"Rollout {rollout_id} failed: {e}")
            
            # Create failure rollout
            return Rollout(
                rollout_id=rollout_id,
                task=task,
                spans=spans,
                final_reward=0.0,
                status="failed",
                start_time=start_time,
                end_time=time.time(),
                metadata={"error": str(e)}
            )
    
    def _calculate_reward(self, result: Dict[str, Any], task: Task) -> float:
        """Calculate reward based on agent performance."""
        base_reward = 0.5
        
        # Success bonus
        if result.get("success", False):
            base_reward += 0.3
        
        # Quality bonus
        if "quality_score" in result:
            base_reward += result["quality_score"] * 0.2
        
        # Efficiency bonus (faster execution = higher reward)
        processing_time = result.get("processing_time", 2.0)
        if processing_time < 1.0:
            base_reward += 0.1
        
        return min(1.0, max(0.0, base_reward))


class AgentLightningTrainer:
    """
    Central orchestrator that manages the training loop.
    From docs: "connects everything and manages the entire workflow"
    """
    
    def __init__(
        self,
        algorithm: APOAlgorithm,
        n_runners: int = 4,
        initial_resources: Dict[str, Any] = None
    ):
        self.algorithm = algorithm
        self.n_runners = n_runners
        self.runners = [AgentRunner() for _ in range(n_runners)]
        self.current_prompt_template = None
        self.training_history = []
        self.logger = logging.getLogger(__name__)
        
        # Set initial prompt template
        if initial_resources and "prompt_template" in initial_resources:
            self.current_prompt_template = initial_resources["prompt_template"]
        else:
            # Default prompt template for SpecTestPilot
            self.current_prompt_template = PromptTemplate(
                template_id=str(uuid.uuid4()),
                content="""You are an expert API testing agent. 

Your task is to {nlp_prompt} for the API specification: {spec_title}

Generate comprehensive, high-quality tests that cover:
- Security vulnerabilities and edge cases
- Authentication and authorization scenarios  
- Input validation and boundary conditions
- Error handling and recovery paths
- Performance and load considerations

Focus on practical, executable tests that provide maximum coverage and reliability."""
            )
    
    async def fit(
        self,
        agent_function: Callable,
        train_dataset: List[Dict[str, Any]],
        val_dataset: List[Dict[str, Any]] = None,
        max_iterations: int = 5
    ) -> Dict[str, Any]:
        """
        Main training loop - the heart of Agent Lightning!
        From docs: "A single call to trainer.fit() kicks off the entire process!"
        """
        
        self.logger.info(f"Starting Agent Lightning training with {len(train_dataset)} tasks")
        self.logger.info(f"Using {self.n_runners} parallel runners")
        
        best_prompt = self.current_prompt_template
        best_score = 0.0
        
        for iteration in range(max_iterations):
            print(f"\n🔄 AGENT LIGHTNING ITERATION {iteration + 1}/{max_iterations}")
            print("=" * 50)
            
            # Step 1: Execute rollouts with current prompt
            print(f"📊 Executing rollouts with prompt v{self.current_prompt_template.version}")
            
            tasks = [
                Task(
                    task_id=str(uuid.uuid4()),
                    input_data=task_data
                )
                for task_data in train_dataset[:8]  # Use subset for faster training
            ]
            
            # Run rollouts in parallel
            rollout_tasks = []
            for i, task in enumerate(tasks):
                runner = self.runners[i % self.n_runners]
                rollout_task = runner.execute_rollout(
                    agent_function, task, self.current_prompt_template
                )
                rollout_tasks.append(rollout_task)
            
            rollouts = await asyncio.gather(*rollout_tasks)
            
            # Step 2: Evaluate current prompt performance
            current_score = await self.algorithm.evaluate_prompt(
                self.current_prompt_template, rollouts
            )
            
            print(f"   Current prompt score: {current_score:.3f}")
            print(f"   Completed rollouts: {len([r for r in rollouts if r.status == 'completed'])}")
            print(f"   Average reward: {sum(r.final_reward for r in rollouts) / len(rollouts):.3f}")
            
            # Track best prompt
            if current_score > best_score:
                best_score = current_score
                best_prompt = self.current_prompt_template
                print(f"   🎉 New best prompt! Score: {best_score:.3f}")
            
            # Step 3: Generate critique and improve prompt
            if iteration < max_iterations - 1:  # Don't improve on last iteration
                print("🔍 Generating critique...")
                critique = await self.algorithm.critique_prompt(
                    self.current_prompt_template, rollouts
                )
                
                print("✨ Generating improved prompt...")
                improved_prompt = await self.algorithm.rewrite_prompt(
                    self.current_prompt_template, critique
                )
                
                self.current_prompt_template = improved_prompt
                print(f"   Created prompt v{improved_prompt.version}")
            
            # Store training history
            self.training_history.append({
                "iteration": iteration + 1,
                "prompt_template": self.current_prompt_template,
                "rollouts": rollouts,
                "score": current_score,
                "critique": critique if iteration < max_iterations - 1 else None
            })
        
        print(f"\n🏆 TRAINING COMPLETED!")
        print(f"Best prompt score: {best_score:.3f}")
        print(f"Prompt evolution: v1 → v{best_prompt.version}")
        
        return {
            "best_prompt_template": best_prompt,
            "best_score": best_score,
            "final_score": current_score,
            "training_history": self.training_history,
            "total_rollouts": sum(len(h["rollouts"]) for h in self.training_history)
        }


# Convenience functions for easy usage
def create_official_agent_lightning(openai_api_key: str = None):
    """Create Agent Lightning system following official methodology."""
    
    # Initialize OpenAI client
    if openai_api_key:
        client = openai.AsyncOpenAI(api_key=openai_api_key)
    else:
        client = openai.AsyncOpenAI()  # Uses OPENAI_API_KEY env var
    
    # Create APO algorithm
    algorithm = APOAlgorithm(client)
    
    # Create trainer
    trainer = AgentLightningTrainer(
        algorithm=algorithm,
        n_runners=4,  # Parallel execution as per docs
        initial_resources={
            "prompt_template": PromptTemplate(
                template_id="initial",
                content="""You are a professional API testing specialist.

Task: {nlp_prompt}
API: {spec_title}

Generate comprehensive test suites that include:
- Security testing (SQL injection, XSS, authentication bypass)
- Input validation (boundary values, malformed data)
- Error scenarios (invalid requests, server errors)
- Performance testing (response times, load handling)

Create practical, executable tests with clear assertions and expected outcomes."""
            )
        }
    )
    
    return trainer


async def train_spec_test_pilot_official():
    """Train SpecTestPilot using official Agent Lightning methodology."""
    
    print("🚀 OFFICIAL AGENT LIGHTNING TRAINING")
    print("Based on Microsoft Research Documentation")
    print("=" * 50)
    
    # Create trainer
    trainer = create_official_agent_lightning()
    
    # Prepare training dataset
    train_dataset = [
        {
            "spec_title": "Banking API",
            "nlp_prompt": "Generate comprehensive security tests with SQL injection protection",
            "openapi_spec": "examples/banking_api.yaml",
            "tenant_id": "banking_corp"
        },
        {
            "spec_title": "E-commerce API", 
            "nlp_prompt": "Create authentication and authorization test scenarios",
            "openapi_spec": "examples/ecommerce_api.yaml",
            "tenant_id": "shop_corp"
        },
        {
            "spec_title": "Social Media API",
            "nlp_prompt": "Test input validation and boundary conditions",
            "openapi_spec": "examples/social_api.yaml", 
            "tenant_id": "social_corp"
        },
        {
            "spec_title": "Payment Gateway",
            "nlp_prompt": "Generate error handling and recovery tests",
            "openapi_spec": "examples/payment_api.yaml",
            "tenant_id": "payment_corp"
        }
    ]
    
    # Dummy agent function (will use SpecTestPilot via sandbox)
    async def spec_test_pilot_agent(task_data):
        return {"status": "executed", "task": task_data}
    
    # Run official training
    results = await trainer.fit(
        agent_function=spec_test_pilot_agent,
        train_dataset=train_dataset,
        max_iterations=3  # Keep small for demo
    )
    
    print("\n📊 TRAINING RESULTS:")
    print(f"Best prompt score: {results['best_score']:.3f}")
    print(f"Total rollouts executed: {results['total_rollouts']}")
    print(f"Prompt evolved from v1 to v{results['best_prompt_template'].version}")
    
    print("\n✨ FINAL OPTIMIZED PROMPT:")
    print("-" * 30)
    print(results['best_prompt_template'].content)
    
    return results


if __name__ == "__main__":
    # Demo the official implementation
    asyncio.run(train_spec_test_pilot_official())
