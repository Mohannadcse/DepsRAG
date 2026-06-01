"""
DepsRAG Team - Multi-agent orchestration for dependency analysis.
Migrated from Langroid to Agno.
"""

from typing import Optional
from agno.team import Team, TeamMode
from agno.db.sqlite import SqliteDb

from dependencyrag.model_factory import create_model
from dependencyrag.agno_agents import (
    create_dependency_graph_agent,
    create_search_agent,
    create_critic_agent,
)


def create_depsrag_team(
    model_id: str = "gpt-4o",
    provider: Optional[str] = None,
    db_file: str = "depsrag.db",
) -> Team:
    """
    Create the DepsRAG multi-agent team.
    
    The team consists of:
    - DependencyGraphAgent: Handles Neo4j graph operations
    - SearchAgent: Handles web search and vulnerability checks
    - CriticAgent: Provides feedback on answers
    
    Args:
        model_id: Model ID to use (default: gpt-4o)
        provider: LLM provider ("openai", "azure", "google") or None for auto-detect
        db_file: SQLite database file for conversation storage
    
    Returns:
        Team: Configured DepsRAG team
    """
    # Initialize the model (explicit provider or auto-detect)
    model = create_model(model_id, provider=provider)
    
    # Initialize the database
    db = SqliteDb(db_file=db_file) if db_file else None
    
    # Create specialized worker agents. Team-level instructions drive orchestration.
    dependency_agent = create_dependency_graph_agent(model=model, db=db)
    search_agent = create_search_agent(model=model, db=db)
    critic = create_critic_agent(model=model, db=db)
    
    # Create the team with specialized worker members.
    team = Team(
        name="DepsRAG",
        model=model,  # Use Azure or OpenAI model
        db=db,  # Database for conversation history
        members=[dependency_agent, search_agent, critic],
        mode=TeamMode.coordinate,  # Team coordinator routes work to member agents
        description="""Multi-agent system for analyzing software dependency graphs.
        
The team works together to:
1. Construct dependency graphs from package information
2. Answer questions about dependencies using graph queries
3. Search for vulnerability information
4. Validate answers through critical review

Workflow:
- The team coordinator receives user queries and orchestrates member delegation
- DependencyGraphAgent constructs graphs and executes queries
- SearchAgent finds vulnerability and package information  
- CriticAgent reviews all final answers before delivery to ensure accuracy

The coordinator MUST consult CriticAgent to validate answers before responding to the user.
""",
        instructions=[
            "If package name, version, or ecosystem are missing, ask for them before dependency graph construction.",
            "Delegate dependency graph creation to DependencyGraphAgent, then verify the response indicates success before any follow-up analysis.",
            "If graph creation fails or errors, stop analysis, explain the failure clearly, and ask the user to verify package details.",
            "Route Neo4j graph construction, schema exploration, and graph query tasks to DependencyGraphAgent.",
            "Route web and vulnerability questions to SearchAgent.",
            "Break complex user requests into clear, self-contained subtasks for delegated members.",
            "Synthesize delegated results into one coherent answer instead of concatenating raw member outputs.",
            "Before responding to the user, ALWAYS delegate to CriticAgent for validation.",
            "If CriticAgent finds issues, revise the answer and re-validate when needed.",
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
