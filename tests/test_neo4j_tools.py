#!/usr/bin/env python3
"""
Test Neo4j tools and graph construction functionality.

Tests:
- Neo4j connection
- Graph construction with valid packages
- Graph construction with invalid packages
- Case sensitivity handling
- Existing graph detection
- Cypher query execution
"""

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def test_neo4j_connection():
    """Test Neo4j database connection."""
    from dependencyrag.neo4j_tools import get_neo4j_connection, get_graph_schema_func

    conn = get_neo4j_connection()
    assert conn is not None, "Neo4j connection should not be None"

    schema = get_graph_schema_func()
    assert schema is not None, "Schema should not be None"
    assert isinstance(schema, str), "Schema should be a string"


def test_graph_construction_valid_package():
    """Test graph construction with a valid package."""
    from dependencyrag.neo4j_tools import construct_dependency_graph_func

    result = construct_dependency_graph_func(
        package_name="chainlit",
        package_version="2.8.0",
        package_type="pypi"
    )
    assert "✓" in result, f"Expected success marker in result, got: {result}"


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


def test_case_sensitivity():
    """Test case sensitivity in package names (PyPI)."""
    from dependencyrag.neo4j_tools import construct_dependency_graph_func

    result_lower = construct_dependency_graph_func(
        package_name="chainlit",
        package_version="2.8.0",
        package_type="pypi"
    )
    assert "✓" in result_lower, (
        f"Lowercase package name should succeed, got: {result_lower}"
    )

    result_upper = construct_dependency_graph_func(
        package_name="Chainlit",
        package_version="2.8.0",
        package_type="pypi"
    )
    assert "✗" in result_upper or "⚠" in result_upper, (
        f"Capitalized package name should fail or warn, got: {result_upper}"
    )


def test_cypher_query():
    """Test executing a Cypher query."""
    from dependencyrag.neo4j_tools import execute_cypher_query_func

    query = "MATCH (p:Package) RETURN count(p) as package_count LIMIT 1"
    result = execute_cypher_query_func(query)
    assert result is not None, "Cypher query result should not be None"


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
