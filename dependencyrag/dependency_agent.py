import os
from typing import Optional

# from rich import print
# from rich.prompt import Prompt

from pyvis.network import Network

import langroid as lr
from langroid import ChatDocument
from langroid.agent.special.neo4j.neo4j_chat_agent import (
    Neo4jChatAgent,
    CypherRetrievalTool,
)
from langroid.utils.constants import DONE

from dependencyrag.cypher_message import CONSTRUCT_DEPENDENCY_GRAPH
from dependencyrag.tools import (
    ConstructDepsGraphTool,
    VisualizeGraph,
    QuestionTool,
)


class DependencyGraphAgent(Neo4jChatAgent):
    n_searches: int = 0
    curr_query: str | None = None

    def construct_dependency_graph(self, msg: ConstructDepsGraphTool) -> None:
        check_db_exist = (
            "MATCH (n) WHERE n.name = $name AND n.version = $version RETURN n LIMIT 1"
        )
        response = self.read_query(
            check_db_exist, {"name": msg.package_name, "version": msg.package_version}
        )
        if response.success and response.data:
            # self.config.database_created = True
            return "Database Exists" + " " + lr.utils.constants.DONE
        else:
            if msg.package_type.lower() == "npm":
                package_type_system = "NPM"
            elif msg.package_type.lower() == "pypi":
                package_type_system = "PyPi"
            elif msg.package_type.lower() == "go":
                package_type_system = "GO"
            elif msg.package_type.lower() == "cargo":
                package_type_system = "CARGO"
            else:
                package_type_system = ""
            construct_dependency_graph = CONSTRUCT_DEPENDENCY_GRAPH.format(
                package_type=msg.package_type.lower(),
                package_name=msg.package_name,
                package_version=msg.package_version,
                package_type_system=package_type_system,
            )
            response = self.write_query(construct_dependency_graph)
            if response.success:
                self.config.database_created = True
                return f"Database is created! {DONE}"
            else:
                return f"""
                    Database is not created!
                    Seems the package {msg.package_name} is not found,
                    {DONE}
                    """

    def visualize_dependency_graph(self, msg: VisualizeGraph) -> str:
        """
        Visualizes the dependency graph based on the provided message.

        Args:
            msg (VisualizeGraph): The message containing the package info.

        Returns:
            str: response indicates whether the graph is displayed.
        """
        # Query to fetch nodes and relationships
        # TODO: make this function more general to return customized graphs
        # i.e, displays paths or subgraphs
        try:
            query = """
            MATCH (n)
            OPTIONAL MATCH (n)-[r]->(m)
            RETURN n, r, m
            """

            query_result = self.read_query(query)
            nt = Network(notebook=False, height="750px", width="100%", directed=True)

            node_set = set()  # To keep track of added nodes

            for record in query_result.data:
                # Process node 'n'
                if "n" in record and record["n"] is not None:
                    node = record["n"]
                    # node_id = node.get("id", None)  # Assuming each node has a unique 'id'
                    node_label = node.get("name", "Unknown Node")
                    node_title = f"Version: {node.get('version', 'N/A')}"
                    node_color = "blue"
                    # if node.get("imported", False) else "green"

                    # Check if node has been added before
                    if node_label not in node_set:
                        nt.add_node(
                            node_label,
                            label=node_label,
                            title=node_title,
                            color=node_color,
                        )
                        node_set.add(node_label)

                # Process relationships and node 'm'
                if (
                    "r" in record
                    and record["r"] is not None
                    and "m" in record
                    and record["m"] is not None
                ):
                    source = record["n"]
                    target = record["m"]
                    relationship = record["r"]

                    source_label = source.get("name", "Unknown Node")
                    target_label = target.get("name", "Unknown Node")
                    relationship_label = (
                        relationship[1]
                        if isinstance(relationship, tuple) and len(relationship) > 1
                        else "Unknown Relationship"
                    )

                    # Ensure both source and target nodes are added before adding the edge
                    if source_label not in node_set:
                        source_title = f"Version: {source.get('version', 'N/A')}"
                        source_color = "blue"
                        nt.add_node(
                            source_label,
                            label=source_label,
                            title=source_title,
                            color=source_color,
                        )
                        node_set.add(source_label)
                    if target_label not in node_set:
                        target_title = f"Version: {target.get('version', 'N/A')}"
                        target_color = "blue"
                        nt.add_node(
                            target_label,
                            label=target_label,
                            title=target_title,
                            color=target_color,
                        )
                        node_set.add(target_label)

                    nt.add_edge(source_label, target_label, title=relationship_label)

                nt.options.edges.font = {"size": 12, "align": "top"}
                nt.options.physics.enabled = True
                nt.show_buttons(filter_=["physics"])

                output_file_path = "/app/html/neo4j_graph.html"
                nt.write_html(output_file_path)
                # Construct the host path using the environment variable
                host_html_path = os.getenv("HOST_HTML_PATH", "/app/html")
                abs_file_path = os.path.join(host_html_path, "neo4j_graph.html")
                return f"file:///{abs_file_path}"

        except Exception as e:
            return f"Failed to create visualization: {str(e)}"

    def question_tool(self, msg: QuestionTool) -> str:
        self.curr_query = msg.question
        if self.config.kg_schema is None:
            schema_summary = self.llm_response_forget(
                f"""Provide a consise summary of nodes and edges WITHOUT any explanation
                 for this graph schema {self.get_schema(None)}"""
            )
            self.config.kg_schema = schema_summary.content.replace(
                lr.utils.constants.DONE, ""
            )
        return f"""
        User asked this question: {msg.question}.
        Perform a retreival from the graph database ONLY using the
        `retrieval_query` tool.
        Use this graph schema is: {self.config.kg_schema} tool for generating the Cypher
         Query.
        """

    def llm_response(
        self, message: Optional[str | ChatDocument] = None
    ) -> Optional[ChatDocument]:
        if (
            isinstance(message, ChatDocument)
            and message.metadata.sender == lr.Entity.AGENT
            and self.n_searches > 0
            and "There was an error in your Cypher Query" not in message.content
        ):
            # must be search results from the retreival tool,
            # so let the LLM compose a response based on the search results
            self.n_searches = 0  # reset search count
            message.content = "Provide concsie answer: " + message.content
            result = super().llm_response_forget(message)
            # Augment the LLM's composed answer with a helpful nudge
            # back to the Assistant
            result.content = f"""
            Here are the retrieval_query results for the question: {self.curr_query}.
            ===
            {result.content}
            ===
            Decide if you want to ask any further questions, for the
            user's original question.
            """
            self.curr_query = None
            return result

        if "There was an error in your Cypher Query" in message.content:
            message.content = f"""FIX the Cypher Query and make another trial:
            Here is the error message: {message.content}.
            ===
            Remember the query: {self.curr_query}
            and the graph schema: {self.config.kg_schema} to generate a correct Cypher
            Query.
            """
        # Handling query from user (or other agent)
        result = super().llm_response_forget(message)
        if result is None:
            return result
        tools = self.get_tool_messages(result)
        if all(not isinstance(t, CypherRetrievalTool) for t in tools):
            # LLM did not use search tool;
            # Replace its response with a placeholder message
            # and the agent fallback_handler will remind the LLM
            result.content = "Did not use retrieval_query tool."
            return result

        self.n_searches += 1
        # result includes a search tool,
        return result

    def handle_message_fallback(
        self, msg: str | ChatDocument
    ) -> str | ChatDocument | None:
        if (
            isinstance(msg, ChatDocument)
            and msg.metadata.sender == lr.Entity.LLM
            and self.n_searches == 0
        ):
            question_tool_name = QuestionTool.default_value("request")
            return f"""
            You forgot to use the tool {question_tool_name} to answer the
            user's question : {self.curr_query} based on this graph database schema
            {self.config.kg_schema}.
            """
