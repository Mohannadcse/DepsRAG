import os
import json
from typing import Optional

from pyvis.network import Network

import langroid as lr
from langroid import ChatDocument
from langroid.utils.constants import DONE
from langroid.agent.special.neo4j.neo4j_chat_agent import Neo4jChatAgent
from langroid.agent.special.neo4j.tools import cypher_retrieval_tool_name
from langroid.agent.tools.orchestration import AgentDoneTool

from dependencyrag.deps_construct_upload import (
    recursive_fetch_dependencies,
    save_to_json,
)
from dependencyrag.tools import (
    ConstructDepsGraphTool,
    VisualizeGraph,
    QuestionTool,
    AnswerTool,
    AnswerToolGraphConstruction,
)

from dependencyrag.graph_handler import GraphHandler


from langroid.pydantic_v1 import BaseModel


class QuestionQueryAnswer(BaseModel):
    question: str
    cypher_query: str
    answer: str


class DependencyGraphAgent(Neo4jChatAgent):
    curr_query: str | None = None
    expecting_search_results: bool = False
    expecting_search_tool: bool = False
    # Following attributes are for analytical purposes
    num_corrected_cypher_queries: int = 0
    question_query_answers: list[QuestionQueryAnswer] = []

    def construct_dependency_graph(
        self, msg: ConstructDepsGraphTool
    ) -> Optional[ChatDocument]:
        self.answer_construct_graph = True
        check_db_exist = (
            "MATCH (n) WHERE n.name = $name AND n.version = $version RETURN n LIMIT 1"
        )
        response = self.read_query(
            check_db_exist, {"name": msg.package_name, "version": msg.package_version}
        )
        if response.success and response.data:
            self.config.database_created = True
            answer = f"Graph Database Exists for {msg.package_name}"
            ans_tool = AnswerToolGraphConstruction(answer=answer)
        else:
            package_type_system = {
                "npm": "NPM",
                "pypi": "PyPi",
                "go": "GO",
                "cargo": "CARGO",
            }.get(msg.package_type.lower(), "")

            # Steps to construct JSON dependency and process dependencies recursively

            results = recursive_fetch_dependencies(
                msg.package_type, msg.package_name, msg.package_version
            )
            deps_meta_json_file_path = (
                f"{msg.package_name}_{msg.package_version}_{msg.package_type}.json"
            )
            # Save results to file
            save_to_json(results, deps_meta_json_file_path)
            print(f"Results saved to {deps_meta_json_file_path}")

            # Load JSON data from the file
            with open(deps_meta_json_file_path, "r") as file:
                data = json.load(file)

            # Create and populate the graph
            graph_handler = GraphHandler()
            graph_handler.add_packages(data)
            graph = graph_handler.G

            # Upload nodes
            for node, data in graph.nodes(data=True):
                # Check if the node is a native module
                is_native = data.get("is_native_module", False)

                if is_native:
                    # Query for native nodes
                    query = f"""
                        MERGE (n:Native {{package_name: $package_name}})
                        SET n += $attributes
                    """
                    # Parameters for native nodes
                    node_parameters = {
                        "package_name": data.get("name"),
                        "attributes": {
                            k: v for k, v in data.items() if k != "version"
                        },  # Exclude version
                    }
                else:
                    # Query for package nodes
                    query = f"""
                        MERGE (n:Package {{package_name: $package_name, package_version: $package_version}})
                        SET n += $attributes
                    """
                    # Parameters for package nodes
                    node_parameters = {
                        "package_name": data.get("name"),
                        "package_version": data.get("version"),
                        "attributes": data,
                    }

                # Write node to Neo4j
                node_response = self.write_query(
                    query=query, parameters=node_parameters
                )

            # Upload edges
            for source, target, data in graph.edges(data=True):
                # Extract attributes for the source and target
                source_data = graph.nodes[source]
                target_data = graph.nodes[target]

                # Handle source and target node types
                source_is_native = source_data.get("is_native_module", False)
                target_is_native = target_data.get("is_native_module", False)

                # Extract source and target attributes
                source_name = source_data.get("name")
                source_version = (
                    source_data.get("version") if not source_is_native else None
                )
                target_name = target_data.get("name")
                target_version = (
                    target_data.get("version") if not target_is_native else None
                )

                # Skip if any critical data is missing
                if not source_name or not target_name:
                    print(
                        f"Skipping edge due to missing data: source={source}, target={target}"
                    )
                    continue

                # Prepare query for edge creation
                if source_is_native and target_is_native:
                    # Native to Native edges
                    query = f"""
                        MATCH (n1:Native {{package_name: $source_name}})
                        MATCH (n2:Native {{package_name: $target_name}})
                        MERGE (n1)-[r:DEPENDS_ON]->(n2)
                        SET r += $attributes
                    """
                elif source_is_native:
                    # Native to Package edge
                    query = f"""
                        MATCH (n1:Native {{package_name: $source_name}})
                        MATCH (n2:Package {{package_name: $target_name, package_version: $target_version}})
                        MERGE (n1)-[r:DEPENDS_ON]->(n2)
                        SET r += $attributes
                    """
                elif target_is_native:
                    # Package to Native edge
                    query = f"""
                        MATCH (n1:Package {{package_name: $source_name, package_version: $source_version}})
                        MATCH (n2:Native {{package_name: $target_name}})
                        MERGE (n1)-[r:DEPENDS_ON]->(n2)
                        SET r += $attributes
                    """
                else:
                    # Package to Package edge
                    query = f"""
                        MATCH (n1:Package {{package_name: $source_name, package_version: $source_version}})
                        MATCH (n2:Package {{package_name: $target_name, package_version: $target_version}})
                        MERGE (n1)-[r:DEPENDS_ON]->(n2)
                        SET r += $attributes
                    """

                # Parameters for edge creation
                edge_parameters = {
                    "source_name": source_name,
                    "source_version": source_version,
                    "target_name": target_name,
                    "target_version": target_version,
                    "attributes": data,
                }

                # Write edge to Neo4j
                edge_response = self.write_query(
                    query=query, parameters=edge_parameters
                )

            if node_response.success and edge_response.success:
                self.config.database_created = True
                answer = f"Database is created! {DONE}"
            else:
                answer = f"""
                    Database is not created!
                    Seems the package {msg.package_name} is not found,
                    {DONE}
                    """

            ans_tool = AnswerToolGraphConstruction(answer=answer)

        # obtain the schema if the graph is created
        # we will not use the default schema retreival approach since it doesn't
        # return a detailed schema
        if self.config.database_created:
            query = """
            CALL apoc.meta.schema()
            YIELD value
            RETURN value
            """
            response = self.read_query(query)
            if response.success and response.data:
                schema = response.data[0]["value"]
                self.config.kg_schema = schema
                self.tried_schema = True

        return self.create_llm_response(tool_messages=[ans_tool])

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
        self.expecting_search_tool = True

        self.config.kg_schema = """
            ### Nodes:
            - `Package`
            - `Native`

            ### Node Properties
            **Package**:  
            - `error`: STRING  
            - `root`: BOOLEAN  
            - `total_size`: STRING  
            - `name`: STRING  
            - `native_modules`: LIST  
            - `ecosystem`: STRING, either `pypi` or `native`  
            - `package_name`: STRING  
            - `package_version`: STRING  
            - `size`: STRING  
            - `version`: STRING  

            **Native**:  
            - `name`: STRING  
            - `package_name`: STRING  
            - `ecosystem`: STRING  
            - `is_native_module`: BOOLEAN  
            ---
            ### Relationship Properties
            **DEPENDS_ON**:  
            - `requirement`: STRING  
            ---
            ### The relationships are the following (Explanation of the relationship is after //):
            - (:Package)-[:DEPENDS_ON]->(:Package) // Package depends on another package
            - (:Package)-[:DEPENDS_ON]->(:Native) // Package depends on a native module
        """

        return f"""
        The user asked: {msg.question}

        Generate a **correct and efficient Cypher query** to retrieve the necessary information required to answer the user's question accurately.

        ### Graph Schema:
        {self.config.kg_schema}

        ---

        ### Requirements for the Cypher Query:

        1. **Accurate Traversal and Calculation:**
        - Separate graph traversal logic from the calculation of metrics such as in-degree, out-degree, or path-based statistics.
        - Clearly define the purpose of each `MATCH` clause:
            - Use one `MATCH` for finding nodes or traversing paths.
            - Use another `MATCH` to calculate specific metrics (e.g., counting incoming or outgoing relationships).
        - Avoid mixing traversal and metric calculation in a single step to prevent inflated or incorrect results.

        2. **Avoid Overcounting:**
        - Deduplicate nodes and relationships wherever applicable using `DISTINCT`.
        - Be cautious of paths with cycles or multiple routes to the same node that may lead to duplicate counts.

        3. **In-Degree and Out-Degree Specifics:**
        - To calculate **in-degree**, match all incoming relationships to a node using a pattern like `MATCH ()-[r:RELATIONSHIP_TYPE]->(targetNode)`.
        - To calculate **out-degree**, match all outgoing relationships from a node using a pattern like `MATCH (sourceNode)-[r:RELATIONSHIP_TYPE]->()`.
        - For metrics involving paths, use patterns like `[:RELATIONSHIP_TYPE*]` but ensure proper deduplication of nodes and relationships.

        4. **Efficient Query Design:**
        - Avoid retrieving unrelated data or fields that are not necessary for the calculation.
        - Minimize the use of `COLLECT` and `UNWIND`, unless explicitly needed for aggregating or flattening data.
        - Ensure the query captures **all relevant relationships and nodes** without introducing Cartesian products.

        ---

        ### Response Expectations:
        - Present a **clear and concise Cypher query** that adheres to the above requirements.
        - Explain how the query ensures:
        1. Accurate traversal of the graph.
        2. Correct calculation of metrics (e.g., in-degree or out-degree).
        3. Avoidance of common pitfalls such as overcounting or mixing traversal with metric calculations.
        - Ensure that the response includes only the necessary information to answer the user's question and avoids redundant calculations or extraneous data retrieval.
"""

    def llm_response(
        self, message: Optional[str | ChatDocument] = None
    ) -> Optional[ChatDocument]:
        if (
            self.expecting_search_results
            and "There was an error in your Cypher Query" not in message.content
        ):
            # must be search results from the retreival tool,
            # so let the LLM compose a response based on the search results
            curr_query = self.curr_query
            # reset state
            self.curr_query = None
            self.expecting_search_results = False
            self.expecting_search_tool = False
            evidence = f"Here is the used query: {self.current_retrieval_cypher_query}"
            self.question_query_answers.append(
                QuestionQueryAnswer(
                    question=curr_query, cypher_query=evidence, answer=message.content
                )
            )
            # Augment the LLM's composed answer with a helpful nudge
            # back to the Assistant

            answer = f"""
            Here are the results for the question: {curr_query}.
            ===
            {message.content}
            ===
            {evidence}
            Decide if you want to ask any further questions, for the
            user's original question.
            """
            ans_tool = AnswerTool(answer=answer)
            # cannot return a tool, so use this to create a ChatDocument
            return self.create_llm_response(tool_messages=[ans_tool])

        if "There was an error in your Cypher Query" in message.content:
            self.num_corrected_cypher_queries += 1
            message.content = f"""
            **Task:** Fix the Cypher query and generate a new, correct query.

            **Error Message:**
            {message.content}

            **Original Query:**
            {self.curr_query}

            **Graph Schema:**
            {self.config.kg_schema}

            **Instructions:**
            1. Analyze the provided error message and identify the issue in the original query.
            2. Use the given graph schema to generate a corrected Cypher query.
            3. Ensure the new query avoids repeating the same error described in the error message.
            4. The corrected query should adhere to proper Cypher syntax and align with the provided graph schema.

            **Output:**
            Provide the corrected Cypher query.
            """
        # Handling query from user (or other agent) => expecting a search tool
        result = super().llm_response_forget(message)
        self.expecting_search_results = True
        return result

    def handle_message_fallback(
        self, msg: str | ChatDocument
    ) -> str | ChatDocument | None:
        if (
            isinstance(msg, ChatDocument)
            and msg.metadata.sender == lr.Entity.LLM
            and self.expecting_search_tool
        ):
            question_tool_name = QuestionTool.default_value("request")
            return f"""
            You forgot to use the tool {question_tool_name} to answer the
            user's question : {self.curr_query} based on this graph database schema
            {self.config.kg_schema}.
            """

    def answer_tool(self, msg: AnswerTool) -> AgentDoneTool:
        # signal DONE, and return the AnswerTool
        return AgentDoneTool(tools=[msg])

    def answer_tool_graph(self, msg: AnswerToolGraphConstruction) -> AgentDoneTool:
        # signal DONE, and return the AnswerToolGraphConstruction
        return AgentDoneTool(tools=[msg])
