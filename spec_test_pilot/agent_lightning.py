#!/usr/bin/env python3
"""
Agent Lightning: Train ANY AI Agents with Reinforcement Learning
Implementation based on arXiv:2508.03680 and Microsoft Research

Complete RL framework for agent optimization with:
- Server-client architecture with sidecar design
- Non-intrusive trace collection  
- Credit assignment and hierarchical RL
- Integration with GAM memory system
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Callable, Union
from enum import Enum
import threading
from concurrent.futures import ThreadPoolExecutor
import logging
import numpy as np
from collections import deque, defaultdict

# Optional ML dependencies
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"  
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class TraceType(Enum):
    """Types of execution traces."""
    STATE = "state"
    ACTION = "action"
    REWARD = "reward"
    ERROR = "error"
    TOOL_CALL = "tool_call"
    MEMORY_ACCESS = "memory_access"


@dataclass
class Task:
    """A task for agent execution."""
    task_id: str
    task_type: str
    input_data: Dict[str, Any]
    tenant_id: Optional[str] = None
    priority: int = 1
    timeout: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class ExecutionTrace:
    """Single execution trace event."""
    trace_id: str
    task_id: str
    timestamp: float
    trace_type: TraceType
    agent_id: str
    state: Dict[str, Any]
    action: Optional[Dict[str, Any]] = None
    reward: Optional[float] = None
    next_state: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tenant_id: Optional[str] = None


@dataclass
class TransitionTuple:
    """RL transition tuple: (s_t, a_t, r_t, s_{t+1})."""
    state: Dict[str, Any]
    action: Dict[str, Any] 
    reward: float
    next_state: Dict[str, Any]
    done: bool
    task_id: str
    agent_id: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class CreditAssignmentModule:
    """Credit assignment for hierarchical RL in agent systems."""
    
    def __init__(self, discount_factor: float = 0.95, trace_back_steps: int = 10):
        """
        Initialize credit assignment module.
        
        Args:
            discount_factor: Gamma for temporal discount
            trace_back_steps: How many steps to trace back for credit
        """
        self.gamma = discount_factor
        self.trace_back_steps = trace_back_steps
    
    def assign_credit(
        self, 
        traces: List[ExecutionTrace], 
        final_reward: float,
        task_success: bool
    ) -> List[float]:
        """
        Assign credit across execution traces.
        
        Args:
            traces: Sequence of execution traces
            final_reward: Final task reward
            task_success: Whether task succeeded
            
        Returns:
            List of assigned rewards for each trace
        """
        if not traces:
            return []
        
        rewards = [0.0] * len(traces)
        
        # Terminal reward assignment
        if task_success:
            rewards[-1] = final_reward
        else:
            # Negative reward for failure
            rewards[-1] = -abs(final_reward) if final_reward > 0 else final_reward
        
        # Backward propagation of rewards with discount
        for i in range(len(traces) - 2, -1, -1):
            # Discount factor application
            future_reward = rewards[i + 1] * self.gamma
            
            # Add immediate reward if available
            immediate = traces[i].reward or 0.0
            rewards[i] = immediate + future_reward
            
            # Apply credit assignment decay
            if len(traces) - i > self.trace_back_steps:
                rewards[i] *= 0.1  # Decay for distant actions
        
        return rewards


class SidecarMonitor:
    """Non-intrusive sidecar monitoring for agent execution."""
    
    def __init__(self, buffer_size: int = 1000):
        """
        Initialize sidecar monitor.
        
        Args:
            buffer_size: Maximum traces to buffer
        """
        self.traces = deque(maxlen=buffer_size)
        self.active_tasks: Dict[str, Task] = {}
        self.task_traces: Dict[str, List[ExecutionTrace]] = defaultdict(list)
        self._lock = threading.Lock()
        
    def start_task_monitoring(self, task: Task) -> str:
        """Start monitoring a task."""
        with self._lock:
            self.active_tasks[task.task_id] = task
            self.task_traces[task.task_id] = []
            return task.task_id
    
    def record_trace(
        self,
        task_id: str,
        trace_type: TraceType,
        agent_id: str,
        state: Dict[str, Any],
        action: Optional[Dict[str, Any]] = None,
        reward: Optional[float] = None,
        next_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Record an execution trace."""
        trace_id = str(uuid.uuid4())
        
        trace = ExecutionTrace(
            trace_id=trace_id,
            task_id=task_id,
            timestamp=time.time(),
            trace_type=trace_type,
            agent_id=agent_id,
            state=state,
            action=action,
            reward=reward,
            next_state=next_state,
            metadata=metadata or {},
            tenant_id=self.active_tasks.get(task_id, Task("", "", {})).tenant_id
        )
        
        with self._lock:
            self.traces.append(trace)
            self.task_traces[task_id].append(trace)
            
        return trace_id
    
    def end_task_monitoring(
        self, 
        task_id: str, 
        final_reward: float,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> List[ExecutionTrace]:
        """End task monitoring and return all traces."""
        with self._lock:
            if task_id in self.active_tasks:
                task = self.active_tasks[task_id]
                task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
                task.result = result
                task.error = error
                
                traces = self.task_traces[task_id].copy()
                
                # Clean up
                del self.active_tasks[task_id]
                # Keep traces for training
                
                return traces
            return []
    
    def get_task_traces(self, task_id: str) -> List[ExecutionTrace]:
        """Get traces for a specific task."""
        with self._lock:
            return self.task_traces.get(task_id, []).copy()


class TrajectoryOrganizer:
    """Organizes execution traces into training-ready trajectories."""
    
    def __init__(self, credit_assignment: CreditAssignmentModule):
        """
        Initialize trajectory organizer.
        
        Args:
            credit_assignment: Credit assignment module
        """
        self.credit_assignment = credit_assignment
    
    def organize_trajectory(
        self,
        traces: List[ExecutionTrace],
        final_reward: float,
        task_success: bool
    ) -> List[TransitionTuple]:
        """
        Convert execution traces to RL transition tuples.
        
        Args:
            traces: Execution traces from task
            final_reward: Final task reward
            task_success: Whether task succeeded
            
        Returns:
            List of RL transition tuples
        """
        if len(traces) < 2:
            return []
        
        # Assign credit across traces
        rewards = self.credit_assignment.assign_credit(traces, final_reward, task_success)
        
        transitions = []
        for i in range(len(traces) - 1):
            current_trace = traces[i]
            next_trace = traces[i + 1]
            
            # Skip non-action traces
            if (current_trace.trace_type != TraceType.ACTION or 
                current_trace.action is None):
                continue
            
            transition = TransitionTuple(
                state=current_trace.state,
                action=current_trace.action,
                reward=rewards[i],
                next_state=next_trace.state,
                done=(i == len(traces) - 2),
                task_id=current_trace.task_id,
                agent_id=current_trace.agent_id,
                timestamp=current_trace.timestamp,
                metadata={
                    "trace_id": current_trace.trace_id,
                    "task_success": task_success,
                    "trace_type": current_trace.trace_type.value,
                    "tenant_id": current_trace.tenant_id
                }
            )
            transitions.append(transition)
        
        return transitions
    
    def batch_trajectories(
        self, 
        transitions: List[TransitionTuple],
        batch_size: int = 32
    ) -> List[List[TransitionTuple]]:
        """Batch transitions for training."""
        batches = []
        for i in range(0, len(transitions), batch_size):
            batch = transitions[i:i + batch_size]
            batches.append(batch)
        return batches


class LightningRLAlgorithm:
    """Hierarchical RL algorithm for agent training."""
    
    def __init__(
        self,
        learning_rate: float = 1e-4,
        batch_size: int = 32,
        buffer_size: int = 10000,
        target_update_freq: int = 100
    ):
        """
        Initialize LightningRL algorithm.
        
        Args:
            learning_rate: Learning rate for optimization
            batch_size: Training batch size
            buffer_size: Experience replay buffer size
            target_update_freq: Target network update frequency
        """
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.buffer_size = buffer_size
        self.target_update_freq = target_update_freq
        
        self.experience_buffer = deque(maxlen=buffer_size)
        self.training_step = 0
        
        # Initialize models if PyTorch available
        if TORCH_AVAILABLE:
            self._init_models()
    
    def _init_models(self):
        """Initialize neural network models."""
        # Simple value network for demonstration
        self.value_net = nn.Sequential(
            nn.Linear(512, 256),  # Adjust based on state representation
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, 1)
        )
        
        self.optimizer = optim.Adam(self.value_net.parameters(), lr=self.learning_rate)
        self.criterion = nn.MSELoss()
    
    def add_transition(self, transition: TransitionTuple):
        """Add transition to experience buffer."""
        self.experience_buffer.append(transition)
    
    def train_step(self) -> Dict[str, float]:
        """Execute one training step."""
        if not TORCH_AVAILABLE:
            return {"status": "skipped", "reason": "PyTorch not available"}
        
        if len(self.experience_buffer) < self.batch_size:
            return {"status": "skipped", "reason": "insufficient_data"}
        
        # Sample batch
        batch_indices = np.random.choice(
            len(self.experience_buffer), 
            size=self.batch_size, 
            replace=False
        )
        batch = [self.experience_buffer[i] for i in batch_indices]
        
        # Convert to training format (simplified)
        states = []
        rewards = []
        
        for transition in batch:
            # Convert state to fixed-size vector (simplified)
            state_vector = self._state_to_vector(transition.state)
            states.append(state_vector)
            rewards.append(transition.reward)
        
        states_tensor = torch.FloatTensor(states)
        rewards_tensor = torch.FloatTensor(rewards)
        
        # Forward pass
        predicted_values = self.value_net(states_tensor).squeeze()
        
        # Compute loss
        loss = self.criterion(predicted_values, rewards_tensor)
        
        # Backward pass
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        self.training_step += 1
        
        return {
            "loss": float(loss.item()),
            "batch_size": len(batch),
            "training_step": self.training_step
        }
    
    def _state_to_vector(self, state: Dict[str, Any]) -> List[float]:
        """Convert state dict to fixed-size vector."""
        # Simplified state representation
        vector = [0.0] * 512
        
        # Hash key features to vector positions
        features = [
            str(state.get("spec_title", "")),
            str(state.get("auth_type", "")),
            str(state.get("endpoints_count", 0)),
            str(state.get("current_step", "")),
        ]
        
        for i, feature in enumerate(features):
            if feature:
                # Simple feature hashing
                hash_val = hash(feature) % 512
                vector[hash_val] = 1.0
                
        return vector


class AgentLightningServer:
    """Lightning Server for agent optimization."""
    
    def __init__(
        self,
        max_workers: int = 4,
        credit_assignment_config: Optional[Dict[str, Any]] = None,
        rl_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize Agent Lightning server.
        
        Args:
            max_workers: Maximum concurrent agent executions
            credit_assignment_config: Credit assignment configuration
            rl_config: RL algorithm configuration
        """
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # Core components
        self.monitor = SidecarMonitor()
        self.credit_assignment = CreditAssignmentModule(
            **(credit_assignment_config or {})
        )
        self.trajectory_organizer = TrajectoryOrganizer(self.credit_assignment)
        self.rl_algorithm = LightningRLAlgorithm(**(rl_config or {}))
        
        # Task management
        self.task_queue = deque()
        self.completed_tasks = deque(maxlen=1000)
        self.training_data = []
        
        # Agent registry
        self.registered_agents: Dict[str, Callable] = {}
        self.reward_functions: Dict[str, Callable] = {}
        
        self._running = False
        self.logger = logging.getLogger(__name__)
    
    def register_agent(
        self, 
        agent_id: str, 
        agent_function: Callable,
        reward_function: Optional[Callable] = None
    ):
        """
        Register an agent for optimization.
        
        Args:
            agent_id: Unique agent identifier
            agent_function: Agent execution function
            reward_function: Custom reward function
        """
        self.registered_agents[agent_id] = agent_function
        if reward_function:
            self.reward_functions[agent_id] = reward_function
    
    def submit_task(self, task: Task) -> str:
        """Submit task to execution queue."""
        self.task_queue.append(task)
        return task.task_id
    
    async def execute_agent_with_monitoring(
        self, 
        task: Task, 
        agent_id: str
    ) -> Tuple[Dict[str, Any], List[ExecutionTrace]]:
        """
        Execute agent with full monitoring and trace collection.
        
        Args:
            task: Task to execute
            agent_id: Agent to use
            
        Returns:
            (result, traces) tuple
        """
        if agent_id not in self.registered_agents:
            raise ValueError(f"Agent {agent_id} not registered")
        
        agent_function = self.registered_agents[agent_id]
        
        # Start monitoring
        self.monitor.start_task_monitoring(task)
        
        try:
            # Record initial state
            initial_state = {
                "task_type": task.task_type,
                "input_data": task.input_data,
                "timestamp": time.time(),
                "agent_id": agent_id
            }
            
            self.monitor.record_trace(
                task.task_id, TraceType.STATE, agent_id, initial_state
            )
            
            # Execute agent (this is where your SpecTestPilot runs)
            start_time = time.time()
            result = await self._execute_with_tracing(
                agent_function, task, agent_id
            )
            execution_time = time.time() - start_time
            
            # Calculate reward
            reward = self._calculate_reward(task, result, execution_time, agent_id)
            success = self._is_task_successful(task, result)
            
            # Record final state
            final_state = {
                "result": result,
                "execution_time": execution_time,
                "success": success,
                "timestamp": time.time()
            }
            
            self.monitor.record_trace(
                task.task_id, TraceType.REWARD, agent_id, 
                final_state, reward=reward
            )
            
            # End monitoring and get all traces
            traces = self.monitor.end_task_monitoring(
                task.task_id, reward, success, result
            )
            
            return result, traces
            
        except Exception as e:
            self.logger.error(f"Agent execution failed: {e}")
            
            # Record error
            error_state = {
                "error": str(e),
                "timestamp": time.time()
            }
            
            self.monitor.record_trace(
                task.task_id, TraceType.ERROR, agent_id, error_state
            )
            
            traces = self.monitor.end_task_monitoring(
                task.task_id, -1.0, False, error=str(e)
            )
            
            raise e
    
    async def _execute_with_tracing(
        self, 
        agent_function: Callable, 
        task: Task, 
        agent_id: str
    ) -> Dict[str, Any]:
        """Execute agent function with step-by-step tracing."""
        
        # This is where we integrate with your existing agent
        # For SpecTestPilot, this would call run_agent()
        
        # Record start of execution
        self.monitor.record_trace(
            task.task_id, 
            TraceType.ACTION, 
            agent_id,
            {"action": "start_execution", "task_data": task.input_data},
            action={"type": "execute", "agent": agent_id}
        )
        
        # Execute the actual agent
        if asyncio.iscoroutinefunction(agent_function):
            result = await agent_function(task.input_data)
        else:
            result = agent_function(task.input_data)
        
        # Record tool calls if any
        if isinstance(result, dict) and "tool_calls" in result:
            for tool_call in result["tool_calls"]:
                self.monitor.record_trace(
                    task.task_id,
                    TraceType.TOOL_CALL,
                    agent_id,
                    {"tool_call": tool_call}
                )
        
        return result
    
    def _calculate_reward(
        self, 
        task: Task, 
        result: Dict[str, Any], 
        execution_time: float,
        agent_id: str
    ) -> float:
        """Calculate reward for agent performance."""
        
        # Use custom reward function if available
        if agent_id in self.reward_functions:
            return self.reward_functions[agent_id](task, result, execution_time)
        
        # Default reward function
        base_reward = 1.0
        
        # Reward based on result quality
        if isinstance(result, dict):
            if result.get("success", False):
                base_reward += 0.5
            
            # Reward for test generation quality  
            if "generated_tests" in result:
                tests = result["generated_tests"]
                if isinstance(tests, list):
                    base_reward += len(tests) * 0.1  # More tests = higher reward
                elif isinstance(tests, str):
                    base_reward += len(tests.split("def test_")) * 0.1
            
            # Penalty for errors
            if result.get("errors"):
                base_reward -= len(result["errors"]) * 0.2
        
        # Time efficiency bonus
        if execution_time < 30:  # Fast execution
            base_reward += 0.2
        elif execution_time > 120:  # Slow execution
            base_reward -= 0.1
        
        return max(0.1, base_reward)  # Minimum positive reward
    
    def _is_task_successful(self, task: Task, result: Dict[str, Any]) -> bool:
        """Determine if task execution was successful."""
        if isinstance(result, dict):
            return result.get("success", True) and not result.get("errors")
        return True
    
    def process_trajectory_for_training(
        self, 
        traces: List[ExecutionTrace],
        final_reward: float,
        task_success: bool
    ) -> List[TransitionTuple]:
        """Process trajectory and add to training data."""
        
        # Organize into RL transitions
        transitions = self.trajectory_organizer.organize_trajectory(
            traces, final_reward, task_success
        )
        
        # Add to training buffer
        for transition in transitions:
            self.rl_algorithm.add_transition(transition)
        
        # Store for analysis
        self.training_data.extend(transitions)
        
        return transitions
    
    def train_model(self) -> Dict[str, Any]:
        """Execute model training step."""
        return self.rl_algorithm.train_step()
    
    def get_training_stats(self) -> Dict[str, Any]:
        """Get training statistics."""
        total_transitions = len(self.training_data)
        recent_rewards = [t.reward for t in self.training_data[-100:]]
        
        return {
            "total_transitions": total_transitions,
            "buffer_size": len(self.rl_algorithm.experience_buffer),
            "training_steps": self.rl_algorithm.training_step,
            "recent_avg_reward": np.mean(recent_rewards) if recent_rewards else 0.0,
            "recent_max_reward": np.max(recent_rewards) if recent_rewards else 0.0,
        }


class AgentLightningClient:
    """Client interface for Agent Lightning integration."""
    
    def __init__(self, server: AgentLightningServer, agent_id: str):
        """
        Initialize client.
        
        Args:
            server: Lightning server instance
            agent_id: Agent identifier
        """
        self.server = server
        self.agent_id = agent_id
    
    def submit_and_train(
        self,
        task_type: str,
        input_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        enable_training: bool = True
    ) -> Dict[str, Any]:
        """
        Submit task, execute with monitoring, and optionally train.
        
        Args:
            task_type: Type of task
            input_data: Task input data
            tenant_id: Tenant identifier
            enable_training: Whether to use results for training
            
        Returns:
            Task result with training info
        """
        
        # Create task
        task = Task(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            input_data=input_data,
            tenant_id=tenant_id
        )
        
        # Execute with monitoring
        try:
            result, traces = asyncio.run(
                self.server.execute_agent_with_monitoring(task, self.agent_id)
            )
            
            if enable_training and traces:
                # Calculate final reward
                final_reward = self.server._calculate_reward(
                    task, result, time.time() - task.created_at, self.agent_id
                )
                success = self.server._is_task_successful(task, result)
                
                # Process for training
                transitions = self.server.process_trajectory_for_training(
                    traces, final_reward, success
                )
                
                # Execute training step
                training_result = self.server.train_model()
                
                return {
                    "task_result": result,
                    "training_enabled": True,
                    "transitions_created": len(transitions),
                    "training_stats": training_result,
                    "traces_collected": len(traces),
                    "final_reward": final_reward,
                    "task_success": success
                }
            else:
                return {
                    "task_result": result,
                    "training_enabled": False,
                    "traces_collected": len(traces)
                }
                
        except Exception as e:
            return {
                "task_result": None,
                "error": str(e),
                "training_enabled": False
            }


# Integration with existing GAM system
class GAMAgentLightningAdapter:
    """Adapter to integrate GAM with Agent Lightning."""
    
    def __init__(self, gam_memory_system, lightning_server: AgentLightningServer, sandbox_mode: bool = True):
        """
        Initialize adapter.
        
        Args:
            gam_memory_system: GAM memory system instance
            lightning_server: Agent Lightning server
            sandbox_mode: Use sandbox for safe testing
        """
        self.gam = gam_memory_system
        self.lightning = lightning_server
        self.sandbox_mode = sandbox_mode
        
        # Initialize sandbox if enabled
        if sandbox_mode:
            from .sandbox import AgentLightningSandbox, create_sandbox_agent_function, create_sandbox_reward_function
            self.sandbox = AgentLightningSandbox()
            self.sandbox_agent_function = create_sandbox_agent_function(self.sandbox)
            self.sandbox_reward_function = create_sandbox_reward_function()
        else:
            self.sandbox = None
    
    def create_spec_test_agent(self) -> str:
        """Create and register SpecTestPilot agent with GAM integration."""
        
        async def spec_test_agent_function(input_data: Dict[str, Any]) -> Dict[str, Any]:
            """SpecTestPilot agent with GAM session tracking."""
            
            # Start GAM session
            session_id = self.gam.start_session(
                tenant_id=input_data.get("tenant_id"),
                metadata={"task_type": "spec_test_generation", "agent": "spec_test_pilot"}
            )
            
            try:
                # Add initial context to GAM
                self.gam.add_to_session(
                    session_id, "user", 
                    f"Generate tests for: {input_data.get('spec_title', 'API')}"
                )
                
                # Execute SpecTestPilot (sandbox or real)
                if self.sandbox_mode and self.sandbox:
                    # Use sandbox for safe execution
                    result = self.sandbox.execute_agent_task(input_data)
                else:
                    # Real SpecTestPilot execution
                    from spec_test_pilot.graph import run_agent
                    result = run_agent({
                        "openapi_spec": input_data.get("openapi_spec", ""),
                        "output_format": input_data.get("output_format", "pytest")
                    })
                
                # Add result to GAM
                self.gam.add_to_session(
                    session_id, "assistant",
                    f"Generated {result.get('test_count', 0)} tests",
                    tool_outputs=[{"tool": "test_generator", "output": result}],
                    artifacts=[{"name": "tests.py", "content": result.get("generated_tests", ""), "type": "python"}]
                )
                
                # End GAM session
                lossless_pages, memo = self.gam.end_session_with_memo(
                    session_id,
                    input_data.get("spec_title", "Unknown API"),
                    result.get("endpoint_count", 0),
                    result.get("test_count", 0),
                    ["Generated comprehensive tests"],
                    []
                )
                
                return {
                    "success": True,
                    "generated_tests": result.get("generated_tests", ""),
                    "test_count": result.get("test_count", 0),
                    "endpoint_count": result.get("endpoint_count", 0),
                    "gam_session_id": session_id,
                    "gam_pages": len(lossless_pages),
                    "gam_memo_id": memo.id
                }
                
            except Exception as e:
                # Record error in GAM
                self.gam.add_to_session(
                    session_id, "system", f"Error: {str(e)}"
                )
                
                # End session with error
                self.gam.end_session_with_memo(
                    session_id, "Failed Task", 0, 0, [], [str(e)]
                )
                
                return {
                    "success": False,
                    "error": str(e),
                    "gam_session_id": session_id
                }
        
        # Custom reward function for SpecTestPilot
        def spec_test_reward_function(
            task: Task, 
            result: Dict[str, Any], 
            execution_time: float
        ) -> float:
            """Reward function tailored for test generation quality."""
            
            if not result.get("success", False):
                return 0.1  # Minimum reward for attempt
            
            reward = 1.0
            
            # Reward for test count
            test_count = result.get("test_count", 0)
            reward += test_count * 0.1
            
            # Reward for endpoint coverage
            endpoint_count = result.get("endpoint_count", 0)
            if endpoint_count > 0 and test_count > 0:
                coverage_ratio = test_count / endpoint_count
                reward += coverage_ratio * 0.5
            
            # Time efficiency
            if execution_time < 30:
                reward += 0.3
            elif execution_time > 90:
                reward -= 0.2
            
            # GAM integration bonus
            if result.get("gam_pages", 0) > 0:
                reward += 0.2  # Bonus for memory integration
            
            return max(0.1, reward)
        
        # Register the agent with appropriate reward function
        agent_id = "spec_test_pilot_gam"
        reward_func = self.sandbox_reward_function if self.sandbox_mode else spec_test_reward_function
        
        self.lightning.register_agent(
            agent_id, 
            spec_test_agent_function,
            reward_func
        )
        
        return agent_id


# Main interface for easy integration
class AgentLightningTrainer:
    """Main interface for Agent Lightning training."""
    
    def __init__(
        self,
        gam_memory_system,
        max_workers: int = 2,
        enable_torch: bool = True,
        sandbox_mode: bool = True
    ):
        """
        Initialize Agent Lightning trainer.
        
        Args:
            gam_memory_system: GAM memory system
            max_workers: Concurrent executions
            enable_torch: Enable PyTorch training
        """
        
        # Initialize server
        server_config = {
            "max_workers": max_workers,
            "rl_config": {} if enable_torch and TORCH_AVAILABLE else {}
        }
        
        self.server = AgentLightningServer(**server_config)
        self.adapter = GAMAgentLightningAdapter(gam_memory_system, self.server, sandbox_mode)
        
        # Create SpecTestPilot agent
        self.agent_id = self.adapter.create_spec_test_agent()
        self.client = AgentLightningClient(self.server, self.agent_id)
        
        self.logger = logging.getLogger(__name__)
    
    def train_on_task(
        self,
        openapi_spec: str,
        spec_title: str = "API",
        tenant_id: Optional[str] = None,
        output_format: str = "pytest",
        nlp_prompt: Optional[str] = None,
        enable_error_fixing: bool = False,
        enable_workflow_chains: bool = False
    ) -> Dict[str, Any]:
        """
        Train agent on a single task with enhanced Postman-like capabilities.
        
        Args:
            openapi_spec: OpenAPI specification
            spec_title: API title
            tenant_id: Tenant identifier
            output_format: Output format
            nlp_prompt: Natural language prompt for test generation
            enable_error_fixing: Enable automatic error analysis and fixing
            enable_workflow_chains: Enable workflow orchestration
            
        Returns:
            Training result with enhanced features
        """
        
        input_data = {
            "openapi_spec": openapi_spec,
            "spec_title": spec_title,
            "output_format": output_format,
            "tenant_id": tenant_id,
            "nlp_prompt": nlp_prompt,  # Enhanced: NLP prompt support
            "enable_error_fixing": enable_error_fixing,  # Enhanced: Error fixing
            "enable_workflow_chains": enable_workflow_chains  # Enhanced: Workflows
        }
        
        result = self.client.submit_and_train(
            task_type="test_generation",
            input_data=input_data,
            tenant_id=tenant_id,
            enable_training=True
        )
        
        return result
    
    def batch_train(
        self,
        tasks: List[Dict[str, Any]],
        training_epochs: int = 1
    ) -> Dict[str, Any]:
        """
        Train on multiple tasks for multiple epochs.
        
        Args:
            tasks: List of task configurations
            training_epochs: Number of training epochs
            
        Returns:
            Batch training results
        """
        
        results = []
        training_stats = []
        
        for epoch in range(training_epochs):
            self.logger.info(f"Starting training epoch {epoch + 1}/{training_epochs}")
            
            epoch_results = []
            for i, task_config in enumerate(tasks):
                self.logger.info(f"Processing task {i + 1}/{len(tasks)}")
                
                result = self.train_on_task(**task_config)
                epoch_results.append(result)
                
                # Training step after each task
                if result.get("training_enabled", False):
                    train_result = self.server.train_model()
                    training_stats.append(train_result)
            
            results.append(epoch_results)
        
        return {
            "epochs": training_epochs,
            "tasks_per_epoch": len(tasks),
            "results": results,
            "training_stats": training_stats,
            "final_stats": self.server.get_training_stats()
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive training statistics."""
        return self.server.get_training_stats()


if __name__ == "__main__":
    # Example usage
    from spec_test_pilot.memory.gam import GAMMemorySystem
    
    # Initialize GAM + Agent Lightning
    gam = GAMMemorySystem(use_vector_search=False)
    trainer = AgentLightningTrainer(gam, max_workers=1, enable_torch=TORCH_AVAILABLE)
    
    # Train on sample task
    result = trainer.train_on_task(
        openapi_spec="examples/banking_api.yaml",
        spec_title="Banking API",
        tenant_id="demo_bank",
        output_format="pytest"
    )
    
    print("🚀 Agent Lightning + GAM Training Result:")
    print(json.dumps(result, indent=2))
    print(f"\n📊 Training Stats: {trainer.get_stats()}")
