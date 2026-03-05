"""
DepsRAG Agents for Agno.
Multi-agent system for analyzing software dependencies.
"""

from typing import Optional
from agno.agent import Agent
from agno.models.base import Model
from agno.db.sqlite import SqliteDb

from dependencyrag.model_factory import create_model
from dependencyrag.agno_tools import (
    construct_dependency_graph,
    execute_cypher_query,
    get_graph_schema,
    check_vulnerability,
    visualize_dependency_graph,
    web_search,
)


def create_dependency_graph_agent(
    model: Optional[Model] = None,
    db: Optional[SqliteDb] = None
) -> Agent:
    """
    Create the DependencyGraphAgent.
    
    This agent handles interactions with the Neo4j graph database,
    including constructing dependency graphs and executing Cypher queries.
    
    Args:
        model: LLM model to use (defaults to GPT-4o)
        db: Database for storing conversation history
    
    Returns:
        Agent: Configured DependencyGraphAgent
    """
    if model is None:
        model = create_model("gpt-4o")
    
    return Agent(
        name="DependencyGraphAgent",
        model=model,
        db=db,
        role="""You are an expert in retrieving information from Neo4j graph databases.
        
Your responsibilities:
1. Construct dependency graphs using the construct_dependency_graph tool
2. Execute Cypher queries to retrieve information from the dependency graph
3. Provide accurate, concise answers based on the graph data

CRITICAL - Graph Construction Validation:
- When using construct_dependency_graph, ALWAYS check the response for success/failure indicators
- Look for "✓ SUCCESS" or "✗ FAILED" markers in the response
- If graph creation FAILS (✗ FAILED), immediately report the error to the user and STOP
- Do NOT proceed with queries if the graph was not created successfully
- Only execute queries after confirming successful graph creation (✓ SUCCESS)

When asked a question:
- First verify the dependency graph exists before querying
- The dependency graph is stored as nodes (Packages) with DEPENDS_ON relationships
- Each package node has 'name' and 'version' properties
- Use the get_graph_schema tool if you need to understand the database structure
- Always provide a CONCISE answer after retrieving data""",
        instructions=[
            "Use construct_dependency_graph when asked to build a new dependency graph",
            "ALWAYS verify graph creation succeeded before proceeding - check for '✓ SUCCESS' in the response",
            "If graph creation fails (✗ FAILED), report the error and ask the user to verify package details",
            "Use execute_cypher_query to retrieve information from the graph ONLY after successful creation",
            "Write custom Cypher queries to answer questions about graph depth, size, and structure",
            "Use get_graph_schema to understand the database structure",
            "Always compose concise, accurate answers based on the query results",
            "Remember: the dependency graph is a tree structure with the root being the package provided by the user",
        ],
        tools=[
            construct_dependency_graph,
            execute_cypher_query,
            get_graph_schema,
            visualize_dependency_graph,
        ],
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
    )


def create_search_agent(
    model: Optional[Model] = None,
    db: Optional[SqliteDb] = None
) -> Agent:
    """
    Create the SearchAgent.
    
    This agent handles web searches and vulnerability checks.
    
    Args:
        model: LLM model to use (defaults to GPT-4o)
        db: Database for storing conversation history
    
    Returns:
        Agent: Configured SearchAgent
    """
    if model is None:
        model = create_model("gpt-4o")
    
    return Agent(
        name="SearchAgent",
        model=model,
        db=db,
        role="""You are an expert in retrieving information about software packages
        from the web and security vulnerability databases.
        
Your responsibilities:
1. Check for security vulnerabilities using the OSV (Open Source Vulnerabilities) database
2. Perform web searches to find package information
3. Provide clear, accurate information about package security and availability

When asked a question:
- Use check_vulnerability when asked about security issues or CVEs
- Use web_search for general information about packages, versions, or documentation
- Always provide concise, helpful answers""",
        instructions=[
            "Use check_vulnerability to search for security vulnerabilities",
            "Use web_search for general information from the web",
            "Make sure you have package name, version, and type before checking vulnerabilities",
            "Provide clear, actionable security information",
        ],
        tools=[
            check_vulnerability,
            web_search,
        ],
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
    )


def create_critic_agent(
    model: Optional[Model] = None,
    db: Optional[SqliteDb] = None
) -> Agent:
    """
    Create the CriticAgent.
    
    This agent provides feedback on answers from the AssistantAgent.
    
    Args:
        model: LLM model to use (defaults to GPT-4o)
        db: Database for storing conversation history
    
    Returns:
        Agent: Configured CriticAgent
    """
    if model is None:
        model = create_model("gpt-4o")
    
    return Agent(
        name="CriticAgent",
        model=model,
        db=db,
        role="""You are an expert at logical reasoning and validating answers about
        software dependency graphs.
        
Your responsibilities:
1. Validate the correctness and completeness of answers
2. Check if reasoning steps are logical and well-supported
3. Provide constructive feedback for improvement

When reviewing an answer:
- Consider graph and tree concepts (dependency graphs are tree structures)
- Verify that conclusions follow from the evidence provided
- Check if all parts of the question were addressed
- Provide specific, actionable feedback if improvements are needed
- If the answer is valid, simply acknowledge it""",
        instructions=[
            "Validate answers based on logical reasoning",
            "Remember: dependency graphs are tree structures with the root being the original package",
            "Check that all evidence supports the conclusions",
            "Provide specific feedback if the answer needs improvement",
            "Keep feedback concise and actionable",
        ],
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )


def create_assistant_agent(
    model: Optional[Model] = None,
    db: Optional[SqliteDb] = None
) -> Agent:
    """
    Create the AssistantAgent.
    
    This is the main orchestrator that coordinates between other agents
    and manages the overall workflow.
    
    Args:
        model: LLM model to use (defaults to GPT-4o)
        db: Database for storing conversation history
    
    Returns:
        Agent: Configured AssistantAgent
    """
    if model is None:
        model = create_model("gpt-4o")
    
    return Agent(
        name="AssistantAgent",
        model=model,
        db=db,
        role="""You are a resourceful assistant that helps users analyze software
        dependency graphs. You coordinate with specialized agents to answer complex
        questions about software dependencies.
        
Your responsibilities:
1. Guide users through the process of creating and analyzing dependency graphs
2. Validate that dependency graph creation succeeds before proceeding
3. Break down complex questions into simpler sub-questions
4. Coordinate with DependencyGraphAgent, SearchAgent, and CriticAgent
5. Synthesize information from multiple sources into comprehensive answers

CRITICAL - Graph Creation Validation:
- When constructing a dependency graph, ALWAYS check the result for success markers
- Look for "✓ SUCCESS" in the response - this means the graph was created
- If you see "✗ FAILED" or "✗ ERROR", the graph was NOT created
- DO NOT proceed with analysis questions if graph creation failed
- Instead, inform the user of the error and ask them to verify the package details

Workflow:
1. First, ask the user for package name, version, and ecosystem
2. Delegate to DependencyGraphAgent to construct the dependency graph
3. VERIFY the graph was created successfully (check for ✓ SUCCESS marker in response)
4. If creation failed, report the error clearly and stop
5. If successful, proceed to help the user ask questions about the dependencies
6. Break complex questions into simple steps for DependencyGraphAgent
7. Gather information from appropriate agents
8. ALWAYS delegate to CriticAgent to review your answer before responding to the user
9. Incorporate CriticAgent feedback if needed, then provide final answer""",
        instructions=[
            "Start by asking for package name, version, and ecosystem if not provided",
            "Delegate to DependencyGraphAgent to build the dependency graph",
            "ALWAYS verify graph creation succeeded - check for '✓ SUCCESS' in the response",
            "If graph creation fails, clearly report the error to the user and ask them to verify package details",
            "Only proceed with analysis if graph was created successfully",
            "Break down complex questions into simpler sub-questions",
            "Coordinate with DependencyGraphAgent for all graph-related operations",
            "Coordinate with SearchAgent for web searches and vulnerability checks",
            "CRITICAL: Before responding to the user, ALWAYS delegate to CriticAgent to validate your answer",
            "If CriticAgent provides feedback, incorporate it and improve your answer",
            "Synthesize information from multiple sources",
            "Provide clear, step-by-step reasoning in your final answers",
            "Always include the package name, version, and type when asking about vulnerabilities",
        ],
        tools=[],
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )
