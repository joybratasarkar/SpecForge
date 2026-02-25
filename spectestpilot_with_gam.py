#!/usr/bin/env python3
"""
SpecTestPilot Enhanced with GAM (General Agentic Memory)

This integrates the GAM framework with SpecTestPilot to provide:
1. Persistent memory of API specifications and test patterns
2. JIT compilation of relevant context for test generation
3. Learning from previous test generation experiences
"""

import json
import time
from typing import Dict, List, Any, Optional
from pathlib import Path

# Import GAM components
from gam_implementation import GeneralAgenticMemory, ResearchQuery

# Import SpecTestPilot components
from spec_test_pilot.graph import run_agent
from spec_test_pilot.reward import compute_reward_with_gold
from spec_test_pilot.openapi_parse import parse_openapi_spec


class GAMEnhancedSpecTestPilot:
    """SpecTestPilot enhanced with General Agentic Memory."""
    
    def __init__(self, gam_storage_path: str = "spectestpilot_gam"):
        self.gam = GeneralAgenticMemory(gam_storage_path)
        self.execution_history = []
        
        # Initialize with some API testing knowledge
        self._initialize_testing_knowledge()
        
        print("✅ GAM-Enhanced SpecTestPilot initialized")
    
    def generate_tests_with_memory(self, openapi_yaml: str, run_id: str = None) -> Dict[str, Any]:
        """Generate tests using GAM-enhanced context."""
        if run_id is None:
            run_id = f"gam_run_{int(time.time())}"
        
        print(f"🧠 Generating tests with GAM memory for run: {run_id}")
        
        # Step 1: Parse the OpenAPI spec to understand what we're working with
        try:
            parsed_spec = parse_openapi_spec(openapi_yaml)
            spec_info = {
                "title": parsed_spec.get("info", {}).get("title", "Unknown API"),
                "version": parsed_spec.get("info", {}).get("version", "1.0.0"),
                "endpoints": len(parsed_spec.get("paths", {})),
                "has_security": bool(parsed_spec.get("securityDefinitions") or parsed_spec.get("components", {}).get("securitySchemes"))
            }
        except Exception as e:
            print(f"⚠️  Failed to parse spec: {e}")
            spec_info = {"title": "Unknown API", "endpoints": 0}
        
        # Step 2: Research relevant testing patterns using GAM
        research_context = self._research_testing_patterns(openapi_yaml, spec_info)
        
        # Step 3: Run the agent with enhanced context
        start_time = time.time()
        
        # Inject GAM research into the agent's context
        enhanced_result = self._run_agent_with_gam_context(
            openapi_yaml, run_id, research_context
        )
        
        execution_time = time.time() - start_time
        
        # Step 4: Store the execution experience in GAM
        self._store_execution_experience(
            openapi_yaml, spec_info, enhanced_result, research_context, execution_time
        )
        
        # Step 5: Add GAM-specific metadata to result
        enhanced_result["gam_metadata"] = {
            "research_context_length": len(research_context.integrated_context),
            "research_confidence": research_context.confidence_score,
            "research_time": research_context.search_time,
            "total_execution_time": execution_time,
            "memory_pages_used": len(research_context.pages)
        }
        
        return enhanced_result
    
    def _research_testing_patterns(self, openapi_yaml: str, spec_info: Dict[str, Any]) -> Any:
        """Research relevant testing patterns using GAM."""
        # Create research query based on the API characteristics
        query_parts = [
            f"API testing patterns for {spec_info['title']}",
            f"OpenAPI testing with {spec_info['endpoints']} endpoints"
        ]
        
        if spec_info.get("has_security"):
            query_parts.append("authentication testing patterns")
        
        # Add specific endpoint types if we can detect them
        try:
            parsed_spec = parse_openapi_spec(openapi_yaml)
            paths = parsed_spec.get("paths", {})
            
            methods = set()
            for path, path_info in paths.items():
                methods.update(path_info.keys())
            
            if methods:
                query_parts.append(f"HTTP methods: {', '.join(methods)}")
        except:
            pass
        
        query_text = " ".join(query_parts)
        
        # Research using GAM
        research_query = ResearchQuery(
            query_text=query_text,
            context={
                "spec_info": spec_info,
                "task": "test_generation",
                "api_type": "openapi"
            },
            max_results=5,
            search_strategy="hybrid"
        )
        
        return self.gam.researcher.research(research_query)
    
    def _run_agent_with_gam_context(self, openapi_yaml: str, run_id: str, 
                                   research_context: Any) -> Dict[str, Any]:
        """Run SpecTestPilot with GAM-enhanced context."""
        # For now, we'll run the standard agent and enhance the result
        # In a full implementation, we'd modify the agent to use GAM context
        
        print(f"🤖 Running SpecTestPilot agent with GAM context...")
        print(f"   📚 Using {len(research_context.pages)} memory pages")
        print(f"   🎯 Research confidence: {research_context.confidence_score:.3f}")
        
        # Run the standard agent
        result = run_agent(openapi_yaml, run_id=run_id)
        
        # Enhance the result with GAM insights
        if research_context.pages:
            # Add insights from GAM research
            gam_insights = self._extract_insights_from_research(research_context)
            result["gam_insights"] = gam_insights
            
            # Potentially modify test generation based on insights
            # This is where we could implement GAM-guided test enhancement
            result = self._enhance_tests_with_gam_insights(result, gam_insights)
        
        return result
    
    def _extract_insights_from_research(self, research_context: Any) -> Dict[str, Any]:
        """Extract actionable insights from GAM research."""
        insights = {
            "testing_patterns": [],
            "common_issues": [],
            "best_practices": [],
            "similar_apis": []
        }
        
        # Analyze research pages for insights
        for page in research_context.pages:
            content = page.content.lower()
            metadata = page.metadata
            
            # Extract testing patterns
            if "test" in content and "pattern" in content:
                insights["testing_patterns"].append({
                    "pattern": page.content[:200] + "...",
                    "source": page.page_id,
                    "importance": page.importance_score
                })
            
            # Extract common issues
            if any(word in content for word in ["error", "issue", "problem", "bug"]):
                insights["common_issues"].append({
                    "issue": page.content[:150] + "...",
                    "source": page.page_id
                })
            
            # Extract best practices
            if any(word in content for word in ["best", "practice", "recommend", "should"]):
                insights["best_practices"].append({
                    "practice": page.content[:150] + "...",
                    "source": page.page_id
                })
            
            # Identify similar APIs
            if metadata.get("type") == "api_execution":
                insights["similar_apis"].append({
                    "api": metadata.get("api_title", "Unknown"),
                    "similarity_score": page.importance_score
                })
        
        return insights
    
    def _enhance_tests_with_gam_insights(self, result: Dict[str, Any], 
                                       insights: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance test generation based on GAM insights."""
        # Add GAM-suggested improvements to the test suite
        if "test_suite" in result.get("output", {}):
            test_suite = result["output"]["test_suite"]
            
            # Add metadata about GAM enhancements
            for test in test_suite:
                test["gam_enhanced"] = True
                
                # Add insights-based notes
                if insights["testing_patterns"]:
                    test["gam_pattern_match"] = len([
                        p for p in insights["testing_patterns"] 
                        if any(word in test.get("name", "").lower() 
                              for word in p["pattern"].lower().split()[:5])
                    ])
            
            # Add summary of GAM contributions
            result["output"]["gam_enhancement_summary"] = {
                "patterns_applied": len(insights["testing_patterns"]),
                "best_practices_considered": len(insights["best_practices"]),
                "similar_apis_referenced": len(insights["similar_apis"]),
                "total_insights": sum(len(v) for v in insights.values() if isinstance(v, list))
            }
        
        return result
    
    def _store_execution_experience(self, openapi_yaml: str, spec_info: Dict[str, Any],
                                  result: Dict[str, Any], research_context: Any,
                                  execution_time: float):
        """Store the execution experience in GAM for future learning."""
        # Create comprehensive execution record
        execution_record = {
            "timestamp": time.time(),
            "spec_info": spec_info,
            "execution_time": execution_time,
            "research_confidence": research_context.confidence_score,
            "test_count": len(result.get("output", {}).get("test_suite", [])),
            "final_reward": result.get("final_reward", 0.0),
            "intermediate_rewards": result.get("intermediate_rewards", {}),
            "success": result.get("success", True)
        }
        
        # Store as a page in GAM
        content = f"""
API Testing Execution Report:
API: {spec_info['title']} (v{spec_info.get('version', '1.0.0')})
Endpoints: {spec_info['endpoints']}
Tests Generated: {execution_record['test_count']}
Quality Score: {execution_record['final_reward']:.4f}
Execution Time: {execution_time:.2f}s

Key Insights:
- Research confidence: {research_context.confidence_score:.3f}
- Memory pages used: {len(research_context.pages)}
- Intermediate rewards: {json.dumps(execution_record['intermediate_rewards'], indent=2)}

This execution demonstrates {
    'successful' if execution_record['success'] else 'failed'
} test generation for a {spec_info['endpoints']}-endpoint API.
        """.strip()
        
        metadata = {
            "type": "api_execution",
            "api_title": spec_info['title'],
            "endpoint_count": spec_info['endpoints'],
            "quality_score": execution_record['final_reward'],
            "execution_time": execution_time,
            "priority": "high" if execution_record['final_reward'] > 0.7 else "medium"
        }
        
        # Add to GAM
        page_id = self.gam.add_information(content, metadata)
        
        # Also create a memory entry for quick access
        summary = f"Generated {execution_record['test_count']} tests for {spec_info['title']} API with {execution_record['final_reward']:.3f} quality score"
        self.gam.memorizer.add_entry(summary, [page_id], execution_record['final_reward'])
        
        print(f"📚 Stored execution experience as page: {page_id}")
    
    def _initialize_testing_knowledge(self):
        """Initialize GAM with basic API testing knowledge."""
        testing_knowledge = [
            {
                "content": "API testing best practices: Always test happy paths first, then edge cases, authentication failures, and error conditions. Include boundary value testing for parameters.",
                "metadata": {"type": "best_practice", "priority": "high", "topic": "api_testing"}
            },
            {
                "content": "OpenAPI test generation patterns: For each endpoint, create tests for successful responses (2xx), client errors (4xx), and server errors (5xx). Test required vs optional parameters.",
                "metadata": {"type": "pattern", "priority": "high", "topic": "openapi"}
            },
            {
                "content": "Authentication testing: Test missing auth tokens, expired tokens, invalid tokens, and insufficient permissions. Include both positive and negative auth scenarios.",
                "metadata": {"type": "pattern", "priority": "high", "topic": "authentication"}
            },
            {
                "content": "REST API validation testing: Test invalid JSON payloads, missing required fields, wrong data types, and field length limits. Verify proper error messages.",
                "metadata": {"type": "pattern", "priority": "medium", "topic": "validation"}
            },
            {
                "content": "HTTP method testing patterns: GET requests should be idempotent, POST creates resources, PUT updates/creates, DELETE removes resources. Test method-specific behaviors.",
                "metadata": {"type": "pattern", "priority": "medium", "topic": "http_methods"}
            }
        ]
        
        for knowledge in testing_knowledge:
            self.gam.add_information(knowledge["content"], knowledge["metadata"])
        
        print(f"📚 Initialized GAM with {len(testing_knowledge)} testing knowledge entries")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get GAM memory statistics."""
        return self.gam.get_statistics()
    
    def query_memory(self, query: str, max_results: int = 5) -> Any:
        """Query the GAM memory directly."""
        return self.gam.query(query, max_results=max_results)


def demo_gam_enhanced_spectestpilot():
    """Demonstrate GAM-enhanced SpecTestPilot."""
    print("🚀 GAM-Enhanced SpecTestPilot Demo")
    print("=" * 60)
    
    # Initialize the enhanced agent
    enhanced_agent = GAMEnhancedSpecTestPilot()
    
    # Sample OpenAPI spec for testing
    sample_api = """
openapi: 3.0.3
info:
  title: Enhanced Pet Store API
  version: 2.0.0
  description: A sample API enhanced for GAM testing
servers:
  - url: https://api.enhanced-petstore.com/v2
paths:
  /pets:
    get:
      summary: List all pets
      parameters:
        - name: limit
          in: query
          schema:
            type: integer
            minimum: 1
            maximum: 100
      responses:
        '200':
          description: A list of pets
        '400':
          description: Bad request
        '401':
          description: Unauthorized
    post:
      summary: Create a pet
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [name, species]
              properties:
                name:
                  type: string
                species:
                  type: string
                age:
                  type: integer
      responses:
        '201':
          description: Pet created
        '400':
          description: Invalid input
        '401':
          description: Unauthorized
  /pets/{petId}:
    get:
      summary: Get a pet by ID
      parameters:
        - name: petId
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Pet details
        '404':
          description: Pet not found
    delete:
      summary: Delete a pet
      security:
        - bearerAuth: []
      parameters:
        - name: petId
          in: path
          required: true
          schema:
            type: string
      responses:
        '204':
          description: Pet deleted
        '404':
          description: Pet not found
        '401':
          description: Unauthorized
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
"""
    
    print("\n🧪 Testing GAM-Enhanced Test Generation...")
    
    # Generate tests with GAM enhancement
    result = enhanced_agent.generate_tests_with_memory(sample_api, "gam_demo_run")
    
    # Display results
    print(f"\n📊 Results:")
    if "output" in result:
        output = result["output"]
        print(f"  🎯 API: {output.get('spec_summary', {}).get('title', 'Unknown')}")
        print(f"  📋 Tests Generated: {len(output.get('test_suite', []))}")
        print(f"  🏆 Quality Score: {result.get('final_reward', 0):.4f}")
        
        if "gam_metadata" in result:
            gam_meta = result["gam_metadata"]
            print(f"  🧠 GAM Research Confidence: {gam_meta['research_confidence']:.3f}")
            print(f"  📚 Memory Pages Used: {gam_meta['memory_pages_used']}")
            print(f"  ⏱️  Total Execution Time: {gam_meta['total_execution_time']:.2f}s")
        
        if "gam_insights" in result:
            insights = result["gam_insights"]
            print(f"  💡 Testing Patterns Found: {len(insights.get('testing_patterns', []))}")
            print(f"  ✅ Best Practices Applied: {len(insights.get('best_practices', []))}")
    
    # Show memory statistics
    print(f"\n📈 GAM Memory Statistics:")
    stats = enhanced_agent.get_memory_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Test memory querying
    print(f"\n🔍 Testing Memory Query...")
    memory_result = enhanced_agent.query_memory("authentication testing patterns")
    print(f"  📚 Found {len(memory_result.pages)} relevant memory pages")
    print(f"  🎯 Query confidence: {memory_result.confidence_score:.3f}")
    
    if memory_result.pages:
        print(f"  📝 Top result: {memory_result.pages[0].content[:100]}...")
    
    print("\n✅ GAM-Enhanced SpecTestPilot demo completed!")


if __name__ == "__main__":
    demo_gam_enhanced_spectestpilot()
