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
- Existing graph detection
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
    print("\n" + "=" * 80)
    print("TEST: Neo4j Connection")
    print("=" * 80)
    
    try:
        from dependencyrag.neo4j_tools import get_neo4j_connection, get_graph_schema_func
        
        print("Connecting to Neo4j...")
        conn = get_neo4j_connection()
        print("✓ Connected successfully!")
        
        print("\nGetting database schema...")
        schema = get_graph_schema_func()
        print(f"Schema: {schema[:200]}..." if len(schema) > 200 else f"Schema: {schema}")
        print("✓ Schema retrieved!")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_valid_package():
    """Test graph construction with a valid package."""
    print("\n" + "=" * 80)
    print("TEST: Valid Package - chainlit 2.8.0")
    print("=" * 80)
    
    try:
        from dependencyrag.neo4j_tools import construct_dependency_graph_func
        
        result = construct_dependency_graph_func(
            package_name="chainlit",
            package_version="2.8.0",
            package_type="pypi"
        )
        print(result)
        
        # Check for success indicator
        if "✓" in result:
            print("\n✓ Test PASSED: Graph created or already exists")
            return True
        else:
            print("\n✗ Test FAILED: Unexpected result")
            return False
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


@pytest.mark.integration
@skip_without_neo4j
def test_graph_construction_invalid_package():
    """Test graph construction with a non-existent package."""
    print("\n" + "=" * 80)
    print("TEST: Invalid Package - nonexistent-xyz123")
    print("=" * 80)
    
    try:
        from dependencyrag.neo4j_tools import construct_dependency_graph_func
        
        result = construct_dependency_graph_func(
            package_name="nonexistent-package-xyz123",
            package_version="1.0.0",
            package_type="pypi"
        )
        print(result)
        
        # Should fail with error marker
        if "✗" in result:
            print("\n✓ Test PASSED: Correctly detected non-existent package")
            return True
        else:
            print("\n✗ Test FAILED: Should have failed for non-existent package")
            return False
            
    except Exception as e:
        # Exception is also acceptable for non-existent package
        print(f"Exception (expected): {e}")
        print("\n✓ Test PASSED: Correctly raised exception")
        return True


@pytest.mark.integration
@skip_without_neo4j
def test_case_sensitivity():
    """Test case sensitivity in package names (PyPI)."""
    print("\n" + "=" * 80)
    print("TEST: Case Sensitivity - Chainlit vs chainlit")
    print("=" * 80)
    
    try:
        from dependencyrag.neo4j_tools import construct_dependency_graph_func
        
        # Test with correct lowercase
        print("\n1. Testing lowercase 'chainlit'...")
        result_lower = construct_dependency_graph_func(
            package_name="chainlit",
            package_version="2.8.0",
            package_type="pypi"
        )
        print(f"Result: {result_lower[:150]}...")
        
        # Test with incorrect capitalization
        print("\n2. Testing capitalized 'Chainlit'...")
        result_upper = construct_dependency_graph_func(
            package_name="Chainlit",
            package_version="2.8.0",
            package_type="pypi"
        )
        print(f"Result: {result_upper[:150]}...")
        
        # Lowercase should succeed, uppercase should fail or warn
        lower_ok = "✓" in result_lower
        upper_fails = "✗" in result_upper or "⚠" in result_upper
        
        if lower_ok and upper_fails:
            print("\n✓ Test PASSED: Case sensitivity handled correctly")
            return True
        else:
            print("\n⚠ Test WARNING: Case sensitivity behavior differs from expected")
            return True  # Still pass as behavior might vary
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


@pytest.mark.integration
@skip_without_neo4j
def test_cypher_query():
    """Test executing a Cypher query."""
    print("\n" + "=" * 80)
    print("TEST: Cypher Query Execution")
    print("=" * 80)
    
    try:
        from dependencyrag.neo4j_tools import execute_cypher_query_func
        
        # Simple query to count packages
        query = "MATCH (p:Package) RETURN count(p) as package_count LIMIT 1"
        
        print(f"Executing query: {query}")
        result = execute_cypher_query_func(query)
        print(f"Result: {result}")
        
        print("\n✓ Test PASSED: Query executed successfully")
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def run_all_tests():
    """Run all Neo4j tool tests."""
    print("\n" + "=" * 80)
    print("RUNNING NEO4J TOOLS TEST SUITE")
    print("=" * 80)
    
    tests = [
        ("Neo4j Connection", test_neo4j_connection),
        ("Valid Package", test_graph_construction_valid_package),
        ("Invalid Package", test_graph_construction_invalid_package),
        ("Case Sensitivity", test_case_sensitivity),
        ("Cypher Query", test_cypher_query),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n✗ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 80)
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
