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
- Multi-ecosystem graph construction (npm, cargo, go)
"""

import pytest
import requests
from dotenv import load_dotenv
from urllib.parse import quote

from tests.markers import skip_without_neo4j

# Load environment variables
load_dotenv()


def _require_neo4j():
    """Verify Neo4j connection is available."""
    from dependencyrag.neo4j_tools import get_neo4j_connection
    
    try:
        conn = get_neo4j_connection()
        # Test connectivity with a simple query
        conn.execute_query("RETURN 1 as test")
    except Exception as exc:
        pytest.skip(f"Neo4j connection failed: {exc}")


def _select_resolvable_go_candidate():
    """Return the first Go module/version resolvable from deps.dev in this environment."""
    from dependencyrag.neo4j_tools import _http_get

    candidates = [
        ("github.com/gin-gonic/gin", "v1.10.0"),
        ("github.com/google/uuid", "v1.6.0"),
        ("github.com/pkg/errors", "v0.9.1"),
        ("golang.org/x/text", "v0.16.0"),
        ("gopkg.in/yaml.v3", "v3.0.1"),
    ]

    for package_name, package_version in candidates:
        url = (
            "https://api.deps.dev/v3alpha/systems/go/packages/"
            f"{quote(package_name, safe='')}/versions/"
            f"{quote(package_version, safe='')}:dependencies"
        )
        try:
            response = _http_get(url, timeout=20)
            if response.status_code == 200:
                return package_name, package_version
        except requests.RequestException:
            continue

    return None


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

    # Query for the specific package/version we just constructed
    query = "MATCH (p:Package {name: 'chainlit', version: '2.8.0'}) RETURN count(p) as count"
    result = execute_cypher_query_func(query)
    assert result is not None, "Cypher query result should not be None"
    assert "count" in result, "Result should contain 'count' field"
    # Verify the result contains a numeric count (basic validation)
    assert "'count':" in result or '"count":' in result, "Result should contain count field with value"


@pytest.mark.integration
@skip_without_neo4j
def test_cross_lang_native_edges():
    """Test cross-language enrichment via Package->Native dependency edges."""
    from dependencyrag.neo4j_tools import (
        construct_dependency_graph_func,
        get_neo4j_connection,
    )

    package_name = "numpy"
    package_version = "1.26.4"
    package_type = "pypi"

    conn = get_neo4j_connection()

    # Ensure this test uses a fresh root package node so construction re-runs.
    conn.execute_query(
        """
        MATCH (p:Package {name: $name, version: $version, ecosystem: $ecosystem})
        DETACH DELETE p
        """,
        {"name": package_name, "version": package_version, "ecosystem": package_type},
    )
    conn.execute_query(
        "MATCH (n:Native {package_name: $name}) DETACH DELETE n",
        {"name": package_name},
    )

    construct_result = construct_dependency_graph_func(
        package_name=package_name,
        package_version=package_version,
        package_type=package_type,
    )
    if "✗" in construct_result:
        pytest.skip(f"Graph construction failed, skipping cross-lang test: {construct_result}")

    result = conn.execute_query(
        """
        MATCH (p:Package {name: $name, version: $version, ecosystem: $ecosystem})
              -[:DEPENDS_ON]->(n:Native {ecosystem: 'native'})
        RETURN count(DISTINCT n) AS nativeCount
        """,
        {"name": package_name, "version": package_version, "ecosystem": package_type},
    )

    native_count = result[0].get("nativeCount", 0) if result else 0
    assert native_count > 0, (
        "Expected at least one cross-language Package->Native edge, "
        f"found {native_count}"
    )


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_npm_ecosystem():
    """Test graph construction for an npm package with ecosystem labeling."""
    from dependencyrag.neo4j_tools import construct_dependency_graph_func, get_neo4j_connection

    package_name = "react"
    package_version = "18.2.0"
    package_type = "npm"

    result = construct_dependency_graph_func(
        package_name=package_name,
        package_version=package_version,
        package_type=package_type,
    )
    if "✗" in result:
        pytest.skip(f"npm graph construction unavailable for {package_name}@{package_version}: {result}")

    conn = get_neo4j_connection()
    row = conn.execute_query(
        """
        MATCH (p:Package {name: $name, version: $version, ecosystem: $ecosystem})
        RETURN p.root AS root
        """,
        {"name": package_name, "version": package_version, "ecosystem": package_type},
    )
    assert row, "Expected npm root package node to exist"
    assert row[0].get("root") is True, "Expected npm root package node to be marked as root"


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_cargo_ecosystem():
    """Test graph construction for a cargo package with ecosystem labeling."""
    from dependencyrag.neo4j_tools import construct_dependency_graph_func, get_neo4j_connection

    package_name = "tokio"
    package_version = "1.37.0"
    package_type = "cargo"

    result = construct_dependency_graph_func(
        package_name=package_name,
        package_version=package_version,
        package_type=package_type,
    )
    if "✗" in result:
        pytest.skip(f"cargo graph construction unavailable for {package_name}@{package_version}: {result}")

    conn = get_neo4j_connection()
    row = conn.execute_query(
        """
        MATCH (p:Package {name: $name, version: $version, ecosystem: $ecosystem})
        RETURN p.root AS root
        """,
        {"name": package_name, "version": package_version, "ecosystem": package_type},
    )
    assert row, "Expected cargo root package node to exist"
    assert row[0].get("root") is True, "Expected cargo root package node to be marked as root"


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_cargo_native_nodes():
    """Test that cargo graph construction persists native nodes for a fresh root."""
    from dependencyrag.neo4j_tools import construct_dependency_graph_func, get_neo4j_connection

    package_name = "ring"
    package_version = "0.17.8"
    package_type = "cargo"

    conn = get_neo4j_connection()

    conn.execute_query(
        """
        MATCH (p:Package {name: $name, version: $version, ecosystem: $ecosystem})
        DETACH DELETE p
        """,
        {"name": package_name, "version": package_version, "ecosystem": package_type},
    )
    conn.execute_query(
        "MATCH (n:Native {package_name: $name}) DETACH DELETE n",
        {"name": package_name},
    )

    result = construct_dependency_graph_func(
        package_name=package_name,
        package_version=package_version,
        package_type=package_type,
    )
    if "✗" in result:
        pytest.skip(f"cargo native graph construction unavailable for {package_name}@{package_version}: {result}")

    rows = conn.execute_query(
        """
        MATCH (p:Package {name: $name, version: $version, ecosystem: $ecosystem})-[:DEPENDS_ON]->(n:Native)
        RETURN count(DISTINCT n) AS nativeCount, collect(n.name)[0..10] AS sample
        """,
        {"name": package_name, "version": package_version, "ecosystem": package_type},
    )
    assert rows, "Expected cargo native query to return a row"
    native_count = rows[0].get("nativeCount", 0)
    assert native_count > 0, f"Expected cargo graph to persist native nodes, found {native_count}"

    root_rows = conn.execute_query(
        """
        MATCH (p:Package {name: $name, version: $version, ecosystem: $ecosystem})
        RETURN p.root AS root, size(coalesce(p.native_modules, [])) AS native_count
        """,
        {"name": package_name, "version": package_version, "ecosystem": package_type},
    )
    assert root_rows, "Expected cargo root package node to exist after rebuild"
    assert root_rows[0].get("root") is True, "Expected cargo root package node to be marked as root"
    assert root_rows[0].get("native_count", 0) > 0, "Expected cargo root package to record native module metadata"


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_go_ecosystem():
    """Test graph construction for a Go module with ecosystem labeling."""
    from dependencyrag.neo4j_tools import construct_dependency_graph_func, get_neo4j_connection

    go_candidate = _select_resolvable_go_candidate()
    if go_candidate is None:
        pytest.skip("No deps.dev-resolvable Go module/version found in this environment")

    package_name, package_version = go_candidate
    package_type = "go"

    result = construct_dependency_graph_func(
        package_name=package_name,
        package_version=package_version,
        package_type=package_type,
    )
    if "✗" in result:
        pytest.skip(f"go graph construction unavailable for {package_name}@{package_version}: {result}")

    conn = get_neo4j_connection()
    row = conn.execute_query(
        """
        MATCH (p:Package {name: $name, version: $version, ecosystem: $ecosystem})
        RETURN p.root AS root
        """,
        {"name": package_name, "version": package_version, "ecosystem": package_type},
    )
    assert row, "Expected go root package node to exist"
    assert row[0].get("root") is True, "Expected go root package node to be marked as root"


def run_all_tests():
    """Run all Neo4j tool tests (manual runner, not collected by pytest)."""
    import traceback

    tests = [
        ("Neo4j Connection", test_neo4j_connection),
        ("Valid Package", test_graph_construction_valid_package),
        ("Invalid Package", test_graph_construction_invalid_package),
        ("Case Sensitivity", test_case_sensitivity),
        ("Cypher Query", test_cypher_query),
        ("Cross-Lang Native Edges", test_cross_lang_native_edges),
        ("NPM Ecosystem", test_graph_construction_npm_ecosystem),
        ("Cargo Ecosystem", test_graph_construction_cargo_ecosystem),
        ("Cargo Native Nodes", test_graph_construction_cargo_native_nodes),
        ("Go Ecosystem", test_graph_construction_go_ecosystem),
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
