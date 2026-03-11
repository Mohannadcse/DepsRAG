"""
Agno tools for DepsRAG.
Migrated from Langroid to Agno.
"""

import json
import requests
from pydantic import BaseModel, Field

from agno.tools import tool

from dependencyrag.neo4j_tools import (
    construct_dependency_graph_func,
    execute_cypher_query_func,
    get_graph_schema_func,
    visualize_dependency_graph_func,
)


# ============================================================================
# Pydantic Models for Tool Parameters
# ============================================================================

class ConstructGraphRequest(BaseModel):
    """Request to construct a dependency graph."""
    package_name: str = Field(description="Name of the package")
    package_version: str = Field(description="Version of the package")
    package_type: str = Field(
        description="Package ecosystem: pypi, npm, cargo, or go (lowercase)"
    )


class VulnerabilityRequest(BaseModel):
    """Request to check for vulnerabilities."""
    package_name: str = Field(description="Name of the package")
    package_version: str = Field(description="Version of the package")
    package_type: str = Field(
        description="Package ecosystem: PyPI, NPM, etc."
    )


class CypherQueryRequest(BaseModel):
    """Request to execute a Cypher query."""
    query: str = Field(description="The Cypher query to execute")


class VisualizeGraphRequest(BaseModel):
    """Request to visualize the dependency graph."""
    package_name: str = Field(description="Name of the package")
    package_version: str = Field(description="Version of the package")
    output_file: str = Field(
        default="dependency_graph.html",
        description="Output HTML file path"
    )


# ============================================================================
# Tool Functions
# ============================================================================

@tool
def construct_dependency_graph(request: ConstructGraphRequest) -> str:
    """
    Construct the dependency graph for a given package version.
    
    This tool builds a knowledge graph of all dependencies (direct and transitive)
    for the specified package using the deps.dev API and stores it in Neo4j.
    
    IMPORTANT: Always check the response for success/failure indicators:
    - "✓ SUCCESS" means the graph was created successfully
    - "✗ FAILED" means graph creation failed (package might not exist)
    - "✗ ERROR" means there was a technical error
    
    Do NOT proceed with queries if graph creation failed.
    
    Args:
        request: Contains package_name, package_version, and package_type
    
    Returns:
        str: Status message with success/failure indicator and detailed information
    """
    return construct_dependency_graph_func(
        package_name=request.package_name,
        package_version=request.package_version,
        package_type=request.package_type
    )


@tool
def execute_cypher_query(request: CypherQueryRequest) -> str:
    """
    Execute a Cypher query on the Neo4j dependency graph database.
    
    Use this to retrieve information from the dependency graph, such as:
    - Finding all dependencies
    - Calculating graph depth
    - Finding paths between packages
    - Analyzing dependency relationships
    
    Args:
        request: Contains the Cypher query to execute
    
    Returns:
        str: Query results formatted as a string
    """
    return execute_cypher_query_func(request.query)


@tool
def get_graph_schema() -> str:
    """
    Get the schema of the Neo4j knowledge graph.
    
    This returns information about node labels, relationship types,
    and property keys in the database.
    
    Returns:
        str: Schema information including labels, relationships, and properties
    """
    return get_graph_schema_func()


@tool
def check_vulnerability(request: VulnerabilityRequest) -> str:
    """
    Check for security vulnerabilities in a package using the OSV database.
    
    This tool queries the Open Source Vulnerability (OSV) database
    to find known security vulnerabilities for the specified package.
    
    Args:
        request: Contains package_name, package_version, and package_type
    
    Returns:
        str: Vulnerability information in JSON format
    """
    # Map package type to OSV ecosystem
    ecosystem_map = {
        "pypi": "PyPI",
        "npm": "npm",
        "cargo": "crates.io",
        "go": "Go",
    }
    ecosystem = ecosystem_map.get(request.package_type.lower(), request.package_type)
    
    # Prepare data payload
    data = {
        "version": request.package_version,
        "package": {
            "name": request.package_name,
            "ecosystem": ecosystem
        },
    }
    
    # Send request to OSV API
    url = "https://api.osv.dev/v1/query"
    
    try:
        response = requests.post(url, data=json.dumps(data))
        response_data = response.json()
        
        # Clean up response to reduce size
        if "vulns" in response_data:
            for vuln in response_data["vulns"]:
                # Remove references to reduce payload size
                if "references" in vuln:
                    del vuln["references"]
                # Remove version lists to reduce size
                if "affected" in vuln:
                    for affected in vuln["affected"]:
                        if "versions" in affected:
                            del affected["versions"]
        
        return f"Vulnerability check results:\n{json.dumps(response_data, indent=2)}"
        
    except Exception as e:
        return f"Error checking vulnerabilities: {str(e)}"


@tool
def visualize_dependency_graph(request: VisualizeGraphRequest) -> str:
    """
    Create an interactive HTML visualization of the dependency graph.
    
    This generates an HTML file with an interactive network visualization
    of all packages and their dependencies.
    
    Args:
        request: Contains package_name, package_version, and optional output_file
    
    Returns:
        str: Status message with the output file path
    """
    return visualize_dependency_graph_func(
        package_name=request.package_name,
        package_version=request.package_version,
        output_file=request.output_file
    )


@tool
def web_search(query: str, num_results: int = 3) -> str:
    """
    Search the web using DuckDuckGo for information.
    
    Use this to find information about:
    - Package versions and availability
    - Package documentation
    - General questions about software dependencies
    
    Args:
        query: The search query
        num_results: Number of results to return (default: 3)
    
    Returns:
        str: Search results
    """
    try:
        from duckduckgo_search import DDGS
        
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=num_results))
        
        if not results:
            return "No search results found."
        
        formatted_results = []
        for i, result in enumerate(results, 1):
            formatted_results.append(
                f"{i}. {result.get('title', 'No title')}\n"
                f"   {result.get('body', 'No description')}\n"
                f"   URL: {result.get('href', 'No URL')}"
            )
        
        return "\n\n".join(formatted_results)
        
    except ImportError:
        return "DuckDuckGo search library not installed. Please install duckduckgo-search."
    except Exception as e:
        return f"Error performing web search: {str(e)}"
