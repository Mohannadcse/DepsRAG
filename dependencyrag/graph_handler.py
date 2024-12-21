import os
import networkx as nx


class GraphHandler:
    """
    A class to create and manage a directed graph of package dependencies using NetworkX.

    Attributes:
        G (networkx.MultiDiGraph): The directed graph representing the package ecosystem.
    """

    def __init__(self):
        """
        Initialize the GraphHandler with an empty MultiDiGraph.
        """
        self.G = nx.MultiDiGraph()

    def add_packages(self, data):
        """
        Add packages and their relationships (edges) to the graph.

        Parameters:
            data (list): List of dictionaries, each representing a package and its dependencies.
        """
        for package in data:
            # Generate a unique ID for the package node
            package_id = self._generate_node_id(
                package["package_name"], package.get("package_version")
            )

            # Add the package as a node. If the node already exists, update its attributes.
            self.G.add_node(
                package_id,
                name=package["package_name"],
                version=package.get("package_version"),
                ecosystem=package.get("package_ecosystem"),
                size=package.get("main_package_size"),
                total_size=package.get("total_size"),
                native_modules=package.get("native_modules", []),
                error=package.get("error"),
                root=package.get("root", False),
            )

            # Add edges based on the "edges" key
            for edge in package.get("edges", []):
                # Generate unique IDs for the source and target nodes
                from_id = self._generate_node_id(
                    edge["from"]["name"], edge["from"]["version"]
                )
                to_id = self._generate_node_id(
                    edge["to"]["name"], edge["to"]["version"]
                )

                # Add the edge to the graph
                self.G.add_edge(from_id, to_id, requirement=edge.get("requirement", ""))

            # Handle native modules
            self.add_so_packages(package_id, package.get("native_modules", []))

    def add_so_packages(self, package_id, native_modules):
        """
        Add .so file nodes and edges from the containing package to the .so nodes.

        Parameters:
            package_id (str): Unique ID of the package containing the native modules.
            native_modules (list): List of native module paths to process.
        """
        for native_module in native_modules:
            if native_module.endswith(".so"):  # Only process .so files
                so_package_id = os.path.basename(native_module)  # Extract the file name
                self.G.add_node(
                    so_package_id,
                    ecosystem="native",
                    name=so_package_id,  # Use the file name as the name
                    is_native_module=True,  # Custom flag for easy identification
                )
                self.G.add_edge(
                    package_id, so_package_id, requirement=""
                )  # Add edge without requirement

    def _generate_node_id(self, name, version):
        """
        Generate a unique ID for a node based on package name and version.

        Parameters:
            name (str): The name of the package.
            version (str): The version of the package.

        Returns:
            str: A unique ID in the format "name:version".
        """
        return f"{name}:{version}" if version else name

    def upload_graph(self, graph):
        for node, data in graph.nodes(data=True):
            node_type = data.get("type", "Node")
            query = f"""
                    MERGE (n:{node_type} {{id: $node}})
                    SET n += $attributes
                    """
            self.driver.execute_query(
                query_=query, node=node, attributes=data, database_="neo4j"
            )

        for source, target, data in graph.edges(data=True):
            edge_type = data["relation"]
            query = f"""
                    MATCH (n1 {{id: $source}})
                    WITH n1
                    MATCH (n2 {{id: $target}})
                    MERGE (n1)-[r:{edge_type}]->(n2)
                    SET r += $attributes
                    """

            self.driver.execute_query(
                query_=query,
                source=source,
                target=target,
                attributes=data,
                database_="neo4j",
            )


"""
# Path to JSON file
json_file_path = "json_file.json"  # Replace with the actual path to the JSON file

# Load JSON data from the file
with open(json_file_path, "r") as file:
    data = json.load(file)

# Create and populate the graph
graph_handler = GraphHandler()
graph_handler.add_packages(data)

# Draw the graph
# graph_handler.draw_graph()
# graph_handler.upload_graph(graph_handler.G)
"""
