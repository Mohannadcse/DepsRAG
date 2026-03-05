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

import pytest
from dotenv import load_dotenv

from tests.markers import skip_without_neo4j

# Load environment variables
load_dotenv()


def _require_neo4j():
    """Verify Neo4j connection is available."""
    from dependencyrag.neo4j_tools import get_neo4j_connection
    
    conn = get_neo4j_connection()
    if conn is None:
        pytest.skip("Neo4j connection not available")


@pytest.mark.integration
@skip_without_neo4j
def test_neo4j_connection():
    """Test Neo4j database connection."""
    from dependencyrag.neo4j_tools import get_neo4j_connection, get_graph_schema_func

    conn = get_neo4j_connection()
    assert conn is not None, "Neo4j connection should not be None"

    schema = get_graph_schema_func()
    assert schema is not None, "Schema should not be None"
    assert isinstance(schema, str), "Schema should be a string"


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_valid_package():
    """Test graph construction with a valid package."""
    from dependencyrag.neo4j_tools import construct_dependency_graph_func

    result = construct_dependency_graph_func(
        package_name="chainlit",
        package_version="2.8.0",
        package_type="pypi"
    )
    assert "✓" in result, f"Expected success marker in result, got: {result}"

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
    from dependencyrag.neo4j_tools import construct_dependency_graph_func

    result = construct_dependency_graph_func(
        package_name="nonexistent-package-xyz123",
        package_version="1.0.0",
        package_type="pypi"
    )
    assert "✗" in result, (
        f"Expected failure marker for non-existent package, got: {result}"
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
    """Test executing a Cypher query with known test data."""
    from dependencyrag.neo4j_tools import construct_dependency_graph_func, execute_cypher_query_func

    # Ensure test data exists
    construct_result = construct_dependency_graph_func(
        package_name="chainlit",
        package_version="2.8.0",
        package_type="pypi"
    )
    if "✗" in construct_result:
        pytest.skip("Graph construction failed, skipping query test")

    # Query for the specific package we just constructed
    query = "MATCH (p:Package {name: 'chainlit'}) RETURN count(p) as count"
    result = execute_cypher_query_func(query)
    assert result is not None, "Cypher query result should not be None"
    assert "count" in result, "Result should contain 'count' field"


def run_all_tests():
    """Run all Neo4j tool tests (manual runner, not collected by pytest)."""
    import traceback

    tests = [
        ("Neo4j Connection", test_neo4j_connection),
        ("Valid Package", test_graph_construction_valid_package),
        ("Invalid Package", test_graph_construction_invalid_package),
        ("Case Sensitivity", test_case_sensitivity),
        ("Cypher Query", test_cypher_query),
    ]

    passed = 0
    for test_name, test_func in tests:
        try:
            test_func()
            print(f"PASS: {test_name}")
            passed += 1
        except Exception:
            print(f"FAIL: {test_name}")
            traceback.print_exc()

    total = len(tests)
    print(f"\nTotal: {passed}/{total} tests passed")
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
