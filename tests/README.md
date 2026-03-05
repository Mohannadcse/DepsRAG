# DepsRAG Tests

This directory contains test suites for the DepsRAG dependency analysis system.

## Test Files

### `test_neo4j_tools.py`
Comprehensive tests for Neo4j database tools and graph construction.

**Tests:**
- Neo4j connection and schema retrieval
- Graph construction with valid packages (success markers)
- Graph construction with invalid packages (failure markers)
- Case sensitivity handling (PyPI packages)
- Cypher query execution

**Run:**
```bash
python tests/test_neo4j_tools.py
```

### `test_integration.py`
Integration tests for the complete DepsRAG system.

**Tests:**
- Neo4j database connection
- Individual tool functionality
- Individual agent creation and configuration
- Team creation and coordination
- Simple query execution through the full system

**Run:**
```bash
python tests/test_integration.py
```

## Requirements

### Environment Variables
Tests require the following environment variables (set in `.env`):
```bash
# Neo4j Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j

# LLM Provider (choose one or more)
# OpenAI
OPENAI_API_KEY=your_openai_key
# OR Azure OpenAI
AZURE_OPENAI_API_KEY=your_azure_key
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
# OR Anthropic
ANTHROPIC_API_KEY=your_anthropic_key
# OR Google Gemini
GOOGLE_API_KEY=your_google_key
```

### Running All Tests
```bash
# Run standalone
python tests/test_neo4j_tools.py

# Or using pytest (recommended)
pytest tests/ -v
```

### With Pytest
If you prefer using pytest, install it first:
```bash
pip install pytest pytest-cov
```

Then run:
```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=dependencyrag

# Run specific test file
pytest tests/test_neo4j_tools.py -v
```

## Integration Tests

For comprehensive integration tests of the full DepsRAG system, see:
- `examples/basic_example.py` - Tests agents and team coordination

Run integration tests:
```bash
python examples/basic_example.py
```

## Notes

- Tests that connect to Neo4j require a running Neo4j instance
- Some tests may create test data in the database
- Tests use the `chainlit` package (version 2.8.0) as a known good test case
- Test files use direct imports and can be run standalone or with pytest


**Unit Tests (test_neo4j_tools.py):**
- ✅ Neo4j connection
- ✅ Graph construction (success and failure cases)
- ✅ Error handling with clear markers (✓ SUCCESS, ✗ FAILED)
- ✅ Case sensitivity (PyPI package names)
- ✅ Cypher query execution
- ✅ Existing graph detection

**Integration Tests (test_integration.py):**
- ✅ Full system initialization
- ✅ Agent creation and tool registration
- ✅ Team coordination
- ✅ End-to-end query processing

For usage examples, see the `examples/`
- ✅ Existing graph detection

For agent and team testing, see the examples directory.
