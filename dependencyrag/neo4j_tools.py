"""
Neo4j tools for Agno agents.
Provides tools for interacting with Neo4j graph database.
"""

import os
from typing import Optional, Dict,  List, Any
from neo4j import GraphDatabase
from pyvis.network import Network

from agno.tools import tool
from agno.tools.function import ToolResult

from dependencyrag.cypher_message import CONSTRUCT_DEPENDENCY_GRAPH


class Neo4jConnection:
    """Neo4j database connection manager."""
    
    def __init__(self, uri: str, username: str, password: str, database: str = "neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.database = database
    
    def close(self):
        """Close the database connection."""
        if self.driver:
            self.driver.close()
    
    def execute_query(self, query: str, parameters: Optional[Dict] = None):
        """Execute a Cypher query."""
        with self.driver.session(database=self.database) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
    
    def execute_write_query(self, query: str, parameters: Optional[Dict] = None):
        """Execute a write query."""
        with self.driver.session(database=self.database) as session:
            result = session.write_transaction(lambda tx: tx.run(query, parameters or {}))
            return result


# Global Neo4j connection (will be initialized when needed)
_neo4j_connection: Optional[Neo4jConnection] = None


def get_neo4j_connection() -> Neo4jConnection:
    """Get or create Neo4j connection."""
    global _neo4j_connection
    
    if _neo4j_connection is None:
        uri = os.getenv("NEO4J_URI")
        username = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        if not all([uri, username, password]):
            raise ValueError(
                "Neo4j credentials not found. Please set NEO4J_URI, "
                "NEO4J_USERNAME, and NEO4J_PASSWORD environment variables."
            )
        
        _neo4j_connection = Neo4jConnection(uri, username, password, database)
    
    return _neo4j_connection


def construct_dependency_graph_func(
    package_name: str,
    package_version: str,
    package_type: str
) -> str:
    """
    Construct the dependency graph for a given package.
    
    Args:
        package_name: Name of the package
        package_version: Version of the package
        package_type: Type/ecosystem of the package (pypi, npm, cargo, go)
    
    Returns:
        str: Status message indicating success or failure
    """
    conn = get_neo4j_connection()
    
    # Check if database already exists
    check_db_exist = (
        "MATCH (n) WHERE n.name = $name AND n.version = $version RETURN n LIMIT 1"
    )
    
    try:
        result = conn.execute_query(
            check_db_exist,
            {"name": package_name, "version": package_version}
        )
        
        if result:
            # Graph exists, but verify it has dependencies
            count_query = """
            MATCH (root:Package {name: $name, version: $version})
            OPTIONAL MATCH (root)-[:DEPENDS_ON*]->(dep:Package)
            WITH root, count(DISTINCT dep) as depCount
            OPTIONAL MATCH (root)-[r:DEPENDS_ON]->()
            RETURN count(DISTINCT root) as packages, count(r) as rels, depCount as totalDeps
            """
            stats = conn.execute_query(count_query, {"name": package_name, "version": package_version})
            
            if stats and len(stats) > 0:
                stat = stats[0]
                num_rels = stat.get('rels', 0)
                total_deps = stat.get('totalDeps', 0)
                
                if num_rels > 0 or total_deps > 0:
                    return (
                        f"✓ Graph already exists for {package_name} version {package_version}\n"
                        f"  - Found existing dependency graph with {total_deps} total dependencies\n"
                        f"  - Ready for queries"
                    )
                else:
                    return (
                        f"⚠ Warning: Graph exists for {package_name} version {package_version} but has no dependencies.\n"
                        f"  This may indicate the package has no dependencies or the graph creation previously failed.\n"
                        f"  You can still query basic package information."
                    )
            
            return f"✓ Graph already exists for {package_name} version {package_version}"
        
        # Determine package type system
        package_type_system_map = {
            "npm": "NPM",
            "pypi": "PyPi",
            "go": "GO",
            "cargo": "CARGO"
        }
        package_type_system = package_type_system_map.get(package_type.lower(), "")
        
        if not package_type_system:
            return f"Unsupported package type: {package_type}"
        
        # Construct the graph
        construct_query = CONSTRUCT_DEPENDENCY_GRAPH.format(
            package_type=package_type.lower(),
            package_name=package_name,
            package_version=package_version,
            package_type_system=package_type_system,
        )
        
        result = conn.execute_query(construct_query)
        
        # Check if graph was actually created by examining the result
        if result and len(result) > 0:
            record = result[0]
            num_packages = record.get('numPackages', 0)
            num_rels = record.get('numRels', 0)
            
            if num_packages > 1:  # More than just the root package
                return (
                    f"✓ SUCCESS: Dependency graph created for {package_name} version {package_version}!\n"
                    f"  - Created {num_packages} package nodes\n"
                    f"  - Created {num_rels} dependency relationships"
                )
            elif num_packages == 1 and num_rels == 0:
                return (
                    f"✗ FAILED: Package found but has no dependencies: {package_name} version {package_version}.\n"
                    f"  This usually means:\n"
                    f"  1. The package name or version is incorrect (check capitalization for PyPI packages)\n"
                    f"  2. The deps.dev API doesn't have dependency data for this version\n"
                    f"  3. The package truly has no dependencies (rare)\n"
                    f"  \n"
                    f"  For PyPI packages, try using lowercase package names.\n"
                    f"  Please verify the package name and version, then try again."
                )
            else:
                return (
                    f"✗ FAILED: Could not create dependency graph for {package_name} version {package_version}.\n"
                    f"  Reason: No packages were found. This usually means:\n"
                    f"  1. The package name or version is incorrect\n"
                    f"  2. The package doesn't exist in {package_type.upper()}\n"
                    f"  3. The deps.dev API doesn't have data for this package\n"
                    f"  Please verify the package name and version, then try again."
                )
        else:
            return (
                f"✗ FAILED: Could not create dependency graph for {package_name} version {package_version}.\n"
                f"  Reason: Query returned no results. The package might not exist or deps.dev API is unavailable.\n"
                f"  Please verify the package exists and try again."
            )
            
    except Exception as e:
        error_msg = str(e)
        return (
            f"✗ ERROR: Failed to construct dependency graph for {package_name} version {package_version}.\n"
            f"  Error: {error_msg}\n"
            f"  Please check your Neo4j connection and try again."
        )


def execute_cypher_query_func(query: str) -> str:
    """
    Execute a Cypher query on the Neo4j database.
    
    Args:
        query: The Cypher query to execute
    
    Returns:
        str: Query results as a formatted string
    """
    conn = get_neo4j_connection()
    
    try:
        result = conn.execute_query(query)
        
        if not result:
            return "Query executed successfully but returned no results."
        
        # Format results
        formatted_results = []
        for record in result:
            formatted_results.append(str(record))
        
        return "\n".join(formatted_results)
        
    except Exception as e:
        return f"Error executing query: {str(e)}"


def get_graph_schema_func() -> str:
    """
    Get the schema of the Neo4j graph database.
    
    Returns:
        str: Database schema information
    """
    conn = get_neo4j_connection()
    
    try:
        # Get node labels
        labels_query = "CALL db.labels()"
        labels_result = conn.execute_query(labels_query)
        labels = [record['label'] for record in labels_result]
        
        # Get relationship types
        rels_query = "CALL db.relationshipTypes()"
        rels_result = conn.execute_query(rels_query)
        rel_types = [record['relationshipType'] for record in rels_result]
        
        # Get property keys
        props_query = "CALL db.propertyKeys()"
        props_result = conn.execute_query(props_query)
        properties = [record['propertyKey'] for record in props_result]
        
        schema_info = f"""
Graph Schema:
- Node Labels: {', '.join(labels) if labels else 'None'}
- Relationship Types: {', '.join(rel_types) if rel_types else 'None'}
- Property Keys: {', '.join(properties) if properties else 'None'}
"""
        return schema_info.strip()
        
    except Exception as e:
        return f"Error retrieving schema: {str(e)}"


def visualize_dependency_graph_func(
    package_name: str,
    package_version: str,
    output_file: str = "dependency_graph.html"
) -> str:
    """
    Visualize the dependency graph.
    
    Args:
        package_name: Name of the package
        package_version: Version of the package
        output_file: Output HTML file path
    
    Returns:
        str: Status message and file path
    """
    conn = get_neo4j_connection()
    
    try:
        query = """
        MATCH (n)
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN n, r, m
        """
        
        result = conn.execute_query(query)
        
        if not result:
            return "No graph data found to visualize."
        
        nt = Network(notebook=False, height="750px", width="100%", directed=True)
        node_set = set()
        
        for record in result:
            # Process node 'n'
            if "n" in record and record["n"] is not None:
                node = record["n"]
                node_name = node.get("name", "Unknown Node")
                node_version = node.get("version", "N/A")
                node_id = f"{node_name}@{node_version}"
                node_title = f"Version: {node_version}"
                node_color = "blue"
                
                if node_id not in node_set:
                    nt.add_node(
                        node_id,
                        label=node_name,
                        title=node_title,
                        color=node_color,
                    )
                    node_set.add(node_id)
            
            # Process relationships
            if (
                "r" in record and record["r"] is not None
                and "m" in record and record["m"] is not None
            ):
                source = record["n"]
                target = record["m"]
                
                source_name = source.get("name", "Unknown Node")
                source_version = source.get("version", "N/A")
                source_id = f"{source_name}@{source_version}"
                
                target_name = target.get("name", "Unknown Node")
                target_version = target.get("version", "N/A")
                target_id = f"{target_name}@{target_version}"
                
                if target_id not in node_set:
                    target_title = f"Version: {target_version}"
                    nt.add_node(
                        target_id,
                        label=target_name,
                        title=target_title,
                        color="blue",
                    )
                    node_set.add(target_id)
                
                nt.add_edge(source_id, target_id)
        
        nt.save_graph(output_file)
        return f"Graph visualization saved to {output_file}"
        
    except Exception as e:
        return f"Error visualizing graph: {str(e)}"
