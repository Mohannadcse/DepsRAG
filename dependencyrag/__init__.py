"""
DepsRAG - Dependency Analysis Chatbot (Agno Version)

Multi-agent system for analyzing software dependencies using Neo4j knowledge graphs.
"""

__version__ = "0.2.0"

from dependencyrag.agno_agents import (
    create_dependency_graph_agent,
    create_search_agent,
    create_critic_agent,
)

from dependencyrag.depsrag_team import create_depsrag_team

__all__ = [
    "create_dependency_graph_agent",
    "create_search_agent",
    "create_critic_agent",
    "create_depsrag_team",
]
