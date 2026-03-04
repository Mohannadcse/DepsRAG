"""
Reusable pytest skip markers for DepsRAG integration tests.

Import these in test modules to conditionally skip tests when the required
external service credentials are not available::

    from tests.markers import skip_without_neo4j, skip_without_llm

    @pytest.mark.integration
    @skip_without_neo4j
    def test_something():
        ...
"""

import os

import pytest
from dotenv import load_dotenv

# Load .env so that credential checks reflect locally configured values
load_dotenv()

# ---------------------------------------------------------------------------
# Credential availability checks (evaluated once at collection time)
# ---------------------------------------------------------------------------

_has_neo4j = all(
    os.getenv(k) for k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"]
)

_has_llm = any(
    os.getenv(k)
    for k in ["OPENAI_API_KEY", "GOOGLE_API_KEY", "AZURE_OPENAI_API_KEY"]
)

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

skip_without_neo4j = pytest.mark.skipif(
    not _has_neo4j,
    reason="Neo4j credentials not set (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD required)",
)

skip_without_llm = pytest.mark.skipif(
    not _has_llm,
    reason=(
        "LLM API credentials not set "
        "(OPENAI_API_KEY, GOOGLE_API_KEY, or AZURE_OPENAI_API_KEY required)"
    ),
)
