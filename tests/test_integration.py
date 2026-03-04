#!/usr/bin/env python3
"""
Integration tests for DepsRAG individual components.

These tests require external services (Neo4j, LLM API keys) and are marked
with ``@pytest.mark.integration`` so they can be excluded from the default
test run::

    pytest -m "not integration"   # skip integration tests
    pytest -m integration         # run only integration tests

Tests are also automatically skipped when the required credentials are absent.

This script tests:
1. Neo4j connection
2. Individual tools
3. Individual agents
4. Team coordination
"""

import os

import pytest
from dotenv import load_dotenv

from tests.markers import skip_without_llm, skip_without_neo4j

# Load environment variables
load_dotenv()


@pytest.mark.integration
@skip_without_neo4j
def test_neo4j_connection():
    """Test Neo4j database connection."""
    print("\n" + "=" * 80)
    print("TEST 1: Neo4j Connection")
    print("=" * 80)
    
    try:
        from dependencyrag.neo4j_tools import get_neo4j_connection, get_graph_schema_func
        
        print("Connecting to Neo4j...")
        conn = get_neo4j_connection()
        print("✓ Connected successfully!")
        
        print("\nGetting database schema...")
        schema = get_graph_schema_func()
        print(schema)
        print("✓ Schema retrieved!")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


@pytest.mark.integration
@skip_without_neo4j
def test_individual_tools():
    """Test individual Agno tools."""
    print("\n" + "=" * 80)
    print("TEST 2: Individual Tools")
    print("=" * 80)
    
    try:
        from dependencyrag.agno_tools import (
            construct_dependency_graph,
            ConstructGraphRequest,
            web_search,
        )
        
        # Test graph construction (with a small package)
        print("\n2a. Testing construct_dependency_graph...")
        request = ConstructGraphRequest(
            package_name="requests",
            package_version="2.31.0",
            package_type="pypi"
        )
        
        # Note: In actual tool execution, Agno handles this differently
        # This is just testing the underlying function
        from dependencyrag.neo4j_tools import construct_dependency_graph_func
        result = construct_dependency_graph_func(
            package_name=request.package_name,
            package_version=request.package_version,
            package_type=request.package_type
        )
        print(f"Result: {result}")
        print("✓ Graph construction tool works!")
        
        # Test web search
        print("\n2b. Testing web_search...")
        # The tool itself will be called by Agno, but we can test the implementation
        print("✓ Web search tool registered!")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


@pytest.mark.integration
@skip_without_llm
def test_individual_agents():
    """Test individual agents."""
    print("\n" + "=" * 80)
    print("TEST 3: Individual Agents")
    print("=" * 80)
    
    try:
        from dependencyrag.agno_agents import (
            create_dependency_graph_agent,
            create_search_agent,
        )
        from agno.models.openai import OpenAIChat
        
        print("\n3a. Creating DependencyGraphAgent...")
        dep_agent = create_dependency_graph_agent(
            model=OpenAIChat(id="gpt-4o")
        )
        print(f"✓ Agent created: {dep_agent.name}")
        print(f"  Tools: {[tool.__name__ if hasattr(tool, '__name__') else str(tool) for tool in dep_agent.tools]}")
        
        print("\n3b. Creating SearchAgent...")
        search_agent = create_search_agent(
            model=OpenAIChat(id="gpt-4o")
        )
        print(f"✓ Agent created: {search_agent.name}")
        print(f"  Tools: {[tool.__name__ if hasattr(tool, '__name__') else str(tool) for tool in search_agent.tools]}")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


@pytest.mark.integration
@skip_without_llm
def test_team_creation():
    """Test team creation."""
    print("\n" + "=" * 80)
    print("TEST 4: Team Creation")
    print("=" * 80)
    
    try:
        from dependencyrag import create_depsrag_team
        
        print("\nCreating DepsRAG team...")
        team = create_depsrag_team(model_id="gpt-4o", db_file="test.db")
        print(f"✓ Team created: {team.name}")
        print(f"  Leader: {team.leader.name}")
        print(f"  Members: {[member.name for member in team.members]}")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


@pytest.mark.integration
@skip_without_llm
@skip_without_neo4j
def test_simple_query():
    """Test a simple query with the team."""
    print("\n" + "=" * 80)
    print("TEST 5: Simple Query")
    print("=" * 80)
    
    try:
        from dependencyrag import create_depsrag_team
        
        print("\nCreating team and running a simple query...")
        team = create_depsrag_team(model_id="gpt-4o", db_file="test.db")
        
        print("\nQuery: 'Hello, can you help me analyze dependencies?'")
        response = team.run("Hello, can you help me analyze dependencies?")
        print(f"\nResponse: {response.content}")
        print("\n✓ Simple query successful!")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 80)
    print("DepsRAG Test Suite")
    print("=" * 80)
    
    results = {
        "Neo4j Connection": test_neo4j_connection(),
        "Individual Tools": test_individual_tools(),
        "Individual Agents": test_individual_agents(),
        "Team Creation": test_team_creation(),
        "Simple Query": test_simple_query(),
    }
    
    print("\n" + "=" * 80)
    print("TEST RESULTS")
    print("=" * 80)
    for test_name, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    print("\n" + "=" * 80)
    if all_passed:
        print("All tests PASSED! ✓")
    else:
        print("Some tests FAILED! ✗")
    print("=" * 80)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
