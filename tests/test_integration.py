#!/usr/bin/env python3
"""
Integration tests for DepsRAG individual components.

These tests require external services (Neo4j, LLM API keys) and are marked
with ``@pytest.mark.integration`` so they can be excluded from the default
test run::

    pytest -m "not integration"   # skip integration tests
    pytest -m integration         # run only integration tests

Tests are also automatically skipped when the required credentials are absent.

Tests:
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


def _require_neo4j():
    """
    Runtime check: verify Neo4j connection actually works.
    
    The @skip_without_neo4j decorator checks env vars exist (fast),
    but this validates the connection is live and credentials are valid.
    """
    from dependencyrag.neo4j_tools import get_neo4j_connection
    
    conn = get_neo4j_connection()
    if conn is None:
        pytest.skip("Neo4j connection failed (check credentials/service)")


def _require_llm():
    """
    Runtime check: verify OpenAI API key is available.
    
    The @skip_without_llm decorator checks if ANY LLM provider exists,
    but these tests specifically use OpenAI models, so verify that key.
    """
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("Tests require OPENAI_API_KEY (uses OpenAIChat model)")


@pytest.mark.integration
@skip_without_neo4j
def test_individual_tools():
    """Test individual Agno tools."""
    _require_neo4j()

    from dependencyrag.agno_tools import (
        ConstructGraphRequest,
        construct_dependency_graph,
        web_search,
    )
    from dependencyrag.neo4j_tools import construct_dependency_graph_func

    request = ConstructGraphRequest(
        package_name="requests",
        package_version="2.31.0",
        package_type="pypi",
    )
    result = construct_dependency_graph_func(
        package_name=request.package_name,
        package_version=request.package_version,
        package_type=request.package_type,
    )
    assert result, "Graph construction should return a non-empty result"

    # Verify Agno tool wrappers are importable (they wrap the functions above)
    assert construct_dependency_graph is not None
    assert web_search is not None


@pytest.mark.integration
@skip_without_llm
def test_individual_agents():
    """Test individual agents."""
    _require_llm()

    from agno.models.openai import OpenAIChat

    from dependencyrag.agno_agents import (
        create_dependency_graph_agent,
        create_search_agent,
    )

    dep_agent = create_dependency_graph_agent(model=OpenAIChat(id="gpt-4o"))
    assert dep_agent is not None, "DependencyGraphAgent should be created"
    assert dep_agent.name, "DependencyGraphAgent should have a name"

    search_agent = create_search_agent(model=OpenAIChat(id="gpt-4o"))
    assert search_agent is not None, "SearchAgent should be created"
    assert search_agent.name, "SearchAgent should have a name"


@pytest.mark.integration
@skip_without_llm
def test_team_creation():
    """Test team creation."""
    _require_llm()

    from dependencyrag import create_depsrag_team

    team = create_depsrag_team(model_id="gpt-4o", db_file="test.db")
    assert team is not None, "Team should be created"
    assert team.name, "Team should have a name"
    assert len(team.members) > 0, "Team should have at least one member"
    assert team.model is not None, "Team should have a model"


@pytest.mark.integration
@skip_without_llm
@skip_without_neo4j
def test_simple_query():
    """Test a simple query with the team."""
    _require_neo4j()
    _require_llm()

    from dependencyrag import create_depsrag_team

    team = create_depsrag_team(model_id="gpt-4o", db_file="test.db")
    response = team.run("Hello, can you help me analyze dependencies?")
    assert response is not None, "Team should return a response"
    assert response.content, "Response should have content"
