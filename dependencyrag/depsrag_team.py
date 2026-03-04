"""
DepsRAG Team - Multi-agent orchestration for dependency analysis.
Migrated from Langroid to Agno.
"""

import os
from typing import Optional, Union
from agno.team import Team, TeamMode
from agno.models.openai import OpenAIChat
from agno.models.azure import AzureOpenAI
from agno.models.google import Gemini
from agno.models.base import Model
from agno.db.sqlite import SqliteDb

from dependencyrag.agno_agents import (
    create_assistant_agent,
    create_dependency_graph_agent,
    create_search_agent,
    create_critic_agent,
)


def _create_model(model_id: str = "gpt-4o", provider: Optional[str] = None) -> Model:
    """
    Create appropriate LLM model based on provider or auto-detect from environment.
    
    Args:
        model_id: Model ID to use (default: gpt-4o)
        provider: Explicit provider ("openai", "azure", "google") or None for auto-detect
        
    Returns:
        Model: Configured model instance (OpenAIChat, AzureOpenAI, or Gemini)
    """
    # Explicit provider specified
    if provider == "google":
        # Use GOOGLE_MODEL_ID from env if model_id is default
        gemini_model = os.getenv("GOOGLE_MODEL_ID", "gemini-2.0-flash-exp") if model_id == "gpt-4o" else model_id
        return Gemini(id=gemini_model)
    elif provider == "azure":
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or model_id
        return AzureOpenAI(
            id=model_id,
            azure_deployment=deployment,
        )
    elif provider == "openai":
        return OpenAIChat(id=model_id)
    
    # Auto-detect based on environment variables
    if os.getenv("AZURE_OPENAI_API_KEY"):
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or model_id
        return AzureOpenAI(
            id=model_id,
            azure_deployment=deployment,
        )
    elif os.getenv("GOOGLE_API_KEY"):
        gemini_model = os.getenv("GOOGLE_MODEL_ID", "gemini-2.0-flash-exp") if model_id == "gpt-4o" else model_id
        return Gemini(id=gemini_model)
    
    # Default to OpenAI
    return OpenAIChat(id=model_id)


def create_depsrag_team(
    model_id: str = "gpt-4o",
    provider: Optional[str] = None,
    db_file: str = "depsrag.db",
    enable_tracing: bool = False
) -> Team:
    """
    Create the DepsRAG multi-agent team.
    
    The team consists of:
    - AssistantAgent: Main orchestrator
    - DependencyGraphAgent: Handles Neo4j graph operations
    - SearchAgent: Handles web search and vulnerability checks
    - CriticAgent: Provides feedback on answers
    
    Args:
        model_id: Model ID to use (default: gpt-4o)
        provider: LLM provider ("openai", "azure", "google") or None for auto-detect
        db_file: SQLite database file for conversation storage
        enable_tracing: Whether to enable tracing
    
    Returns:
        Team: Configured DepsRAG team
    """
    # Initialize the model (explicit provider or auto-detect)
    model = _create_model(model_id, provider=provider)
    
    # Initialize the database
    db = SqliteDb(db_file=db_file) if db_file else None
    
    # Create the agents
    assistant = create_assistant_agent(model=model, db=db)
    dependency_agent = create_dependency_graph_agent(model=model, db=db)
    search_agent = create_search_agent(model=model, db=db)
    critic = create_critic_agent(model=model, db=db)
    
    # Create the team with all agents as members
    # The assistant will coordinate with other agents
    team = Team(
        name="DepsRAG",
        model=model,  # Use Azure or OpenAI model
        db=db,  # Database for conversation history
        members=[assistant, dependency_agent, search_agent, critic],
        mode=TeamMode.coordinate,  # Assistant coordinates member agents
        description="""Multi-agent system for analyzing software dependency graphs.
        
The team works together to:
1. Construct dependency graphs from package information
2. Answer questions about dependencies using graph queries
3. Search for vulnerability information
4. Validate answers through critical review

Workflow:
- AssistantAgent receives user queries and coordinates the team
- DependencyGraphAgent constructs graphs and executes queries
- SearchAgent finds vulnerability and package information  
- CriticAgent reviews all final answers before delivery to ensure accuracy

The AssistantAgent MUST consult CriticAgent to validate answers before responding to the user.
""",
        instructions=[
            "The AssistantAgent coordinates all interactions and MUST involve CriticAgent for answer validation",
            "DependencyGraphAgent handles all Neo4j graph operations (construction, queries, statistics)",
            "SearchAgent handles web searches and vulnerability checks",
            "CriticAgent MUST review and validate all answers before they are returned to the user",
            "Work together to provide comprehensive, accurate, validated answers",
            "Never skip the CriticAgent review step - it ensures answer quality",
        ],
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
    )
    
    return team


def create_simple_depsrag_workflow(
    model_id: str = "gpt-4o",
    db_file: str = "depsrag.db"
):
    """
    Create a simpler workflow-based version of DepsRAG.
    
    This version uses a sequential workflow instead of a team,
    which can be more predictable for certain use cases.
    
    Args:
        model_id: OpenAI/Azure model ID to use
        db_file: SQLite database file for conversation storage
    
    Returns:
        Team: A team configured to work in a workflow-like manner
    """
    from agno.workflow import Workflow
    
    model = _create_model(model_id)
    db = SqliteDb(db_file=db_file) if db_file else None
    
    # Create specialized agents
    dependency_agent = create_dependency_graph_agent(model=model, db=db)
    search_agent = create_search_agent(model=model, db=db)
    
    # For a workflow, we can create a simpler setup
    # where tasks flow sequentially
    workflow = Workflow(
        name="DepsRAG Workflow",
        steps=[dependency_agent, search_agent],
        description="""Sequential workflow for dependency analysis:
        1. Build and query the dependency graph
        2. Search for additional information and vulnerabilities
        """,
    )
    
    return workflow
