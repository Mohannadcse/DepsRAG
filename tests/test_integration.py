#!/usr/bin/env python3
"""
Integration tests for DepsRAG individual components.

Tests:
1. Neo4j connection
2. Individual tools
3. Individual agents
4. Team coordination
"""

import os

import pytest
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def _require_neo4j():
    """Skip test if Neo4j environment variables are not configured."""
    if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
        pytest.skip(
            "Neo4j credentials not configured "
            "(NEO4J_URI and NEO4J_PASSWORD environment variables required)"
        )


def _require_llm():
    """Skip test if no LLM API key is configured."""
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_azure = bool(os.getenv("AZURE_OPENAI_API_KEY"))
    has_google = bool(os.getenv("GOOGLE_API_KEY"))
    if not (has_openai or has_azure or has_google):
        pytest.skip(
            "No LLM API key configured "
            "(OPENAI_API_KEY, AZURE_OPENAI_API_KEY, or GOOGLE_API_KEY required)"
        )


def test_neo4j_connection():
    """Test Neo4j database connection."""
    _require_neo4j()

    from dependencyrag.neo4j_tools import get_neo4j_connection, get_graph_schema_func

    conn = get_neo4j_connection()
    assert conn is not None, "Neo4j connection should be established"

    schema = get_graph_schema_func()
    assert schema, "Schema should not be empty"


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


def test_team_creation():
    """Test team creation."""
    _require_llm()

    from dependencyrag import create_depsrag_team

    team = create_depsrag_team(model_id="gpt-4o", db_file="test.db")
    assert team is not None, "Team should be created"
    assert team.name, "Team should have a name"
    assert team.leader is not None, "Team should have a leader"
    assert len(team.members) > 0, "Team should have at least one member"


def test_simple_query():
    """Test a simple query with the team."""
    _require_neo4j()
    _require_llm()

    from dependencyrag import create_depsrag_team

    team = create_depsrag_team(model_id="gpt-4o", db_file="test.db")
    response = team.run("Hello, can you help me analyze dependencies?")
    assert response is not None, "Team should return a response"
    assert response.content, "Response should have content"
