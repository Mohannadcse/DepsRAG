"""
DepsRAG Team - Multi-agent orchestration for dependency analysis.
Migrated from Langroid to Agno.
"""

from typing import Optional
from agno.team import Team, TeamMode
from agno.db.sqlite import SqliteDb

from dependencyrag.model_factory import create_model
from dependencyrag.agno_agents import (
    create_assistant_agent,
    create_dependency_graph_agent,
    create_search_agent,
    create_critic_agent,
)


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
    model = create_model(model_id, provider=provider)
    
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
