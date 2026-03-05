#!/usr/bin/env python3
"""
Integration tests for Neo4j tools and graph construction functionality.

These tests require a live Neo4j instance and are marked with
``@pytest.mark.integration`` so they can be excluded from the default
test run::

    pytest -m "not integration"   # skip integration tests
    pytest -m integration         # run only integration tests

Tests are also automatically skipped when Neo4j credentials are absent.

Tests:
- Neo4j connection
- Graph construction with valid packages
- Graph construction with invalid packages
- Case sensitivity handling
- Cypher query execution
"""

import os

import pytest
from dotenv import load_dotenv

from tests.markers import skip_without_neo4j

# Load environment variables
load_dotenv()


@pytest.mark.integration
@skip_without_neo4j
def test_neo4j_connection():
    """Test Neo4j database connection."""
    _require_neo4j()

    from dependencyrag.neo4j_tools import get_graph_schema_func, get_neo4j_connection

    conn = get_neo4j_connection()
    assert conn is not None, "Neo4j connection should be established"

    schema = get_graph_schema_func()
    assert schema, "Schema should not be empty"


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_valid_package():
    """Test graph construction with a valid package."""
    _require_neo4j()

    from dependencyrag.neo4j_tools import construct_dependency_graph_func

    result = construct_dependency_graph_func(
        package_name="chainlit",
        package_version="2.8.0",
        package_type="pypi",
    )
    assert "✓" in result, f"Expected success marker in result, got: {result}"


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_invalid_package():
    """Test graph construction with a non-existent package."""
    _require_neo4j()

    from dependencyrag.neo4j_tools import construct_dependency_graph_func

    result = construct_dependency_graph_func(
        package_name="nonexistent-package-xyz123",
        package_version="1.0.0",
        package_type="pypi",
    )
    assert "✗" in result, (
        f"Expected failure marker in result for non-existent package, got: {result}"
    )


@pytest.mark.integration
@skip_without_neo4j
def test_case_sensitivity():
    """Test case sensitivity in package names (PyPI)."""
    _require_neo4j()

    from dependencyrag.neo4j_tools import construct_dependency_graph_func

    result_lower = construct_dependency_graph_func(
        package_name="chainlit",
        package_version="2.8.0",
        package_type="pypi",
    )
    result_upper = construct_dependency_graph_func(
        package_name="Chainlit",
        package_version="2.8.0",
        package_type="pypi",
    )

    assert "✓" in result_lower, (
        f"Lowercase package name should succeed, got: {result_lower}"
    )
    # PyPI is case-sensitive: an incorrectly cased name should return a failure
    # marker ("✗") or at minimum a warning ("⚠") – both indicate the name was
    # not resolved as-is.
    assert "✗" in result_upper or "⚠" in result_upper, (
        f"Uppercase package name should fail or warn, got: {result_upper}"
    )


@pytest.mark.integration
@skip_without_neo4j
def test_cypher_query():
    """Test executing a Cypher query."""
    _require_neo4j()

    from dependencyrag.neo4j_tools import execute_cypher_query_func

    query = "MATCH (p:Package) RETURN count(p) as package_count LIMIT 1"
    result = execute_cypher_query_func(query)
    assert result is not None, "Cypher query should return a result"
