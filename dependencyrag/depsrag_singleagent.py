"""
Single-agent to use to chat with a Neo4j knowledge-graph (KG)
that models a dependency graph of Python packages.

User specifies package name
-> agent gets version number and type of package using google search
-> agent builds dependency graph using Neo4j
-> user asks natural language query about dependencies
-> LLM translates to Cypher query to get info from KG
-> Query results returned to LLM
-> LLM translates to natural language response

This example relies on neo4j. The easiest way to get access to neo4j is by
creating a cloud account at `https://neo4j.com/cloud/platform/aura-graph-database/`

Upon creating the account successfully, neo4j will create a text file that contains
account settings, please provide the following information (uri, username, password) as
described here
`https://github.com/Mohannadcse/DependencyRAG/blob/main/README.md#requirements`

The rest of requirements are described in
 `https://github.com/Mohannadcse/DependencyRAG/blob/main/README.md`

Run like this:
```
python3 dependencyrag/depsrag_singleagent.py
```
"""

import typer
from dotenv import load_dotenv
from rich.prompt import Prompt

import langroid as lr
from langroid.utils.configuration import set_global, Settings
from langroid.language_models.openai_gpt import OpenAIGPTConfig, OpenAIChatModel
from langroid.language_models.azure_openai import AzureConfig
from langroid.agent.tools.google_search_tool import GoogleSearchTool
from langroid.agent.tools.duckduckgo_search_tool import DuckduckgoSearchTool
from langroid.utils.constants import NO_ANSWER, SEND_TO

from langroid.agent.special.neo4j.neo4j_chat_agent import (
    Neo4jChatAgentConfig,
    Neo4jSettings,
)

from dependencyrag.dependency_agent import DependencyGraphAgent

from dependencyrag.tools import (
    ConstructDepsGraphTool,
    VulnerabilityCheck,
    VisualizeGraph,
)

app = typer.Typer()


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", "-d", help="debug mode"),
    model: str = typer.Option("", "--model", "-m", help="model name"),
    tools: bool = typer.Option(
        False, "--tools", "-t", help="use langroid tools instead of function-calling"
    ),
    nocache: bool = typer.Option(False, "--nocache", "-nc", help="don't use cache"),
    provider: str = typer.Option(
        "ddg",
        "--provider",
        "-p",
        help="search provider name (google, ddg)",
    ),
) -> None:
    set_global(
        Settings(
            debug=debug,
            cache=nocache,
        )
    )

    print(
        """
        [blue]Welcome to DepsRAG Analysis chatbot!
        Enter x or q to quit at any point.
        """
    )

    load_dotenv()

    neo4j_settings = Neo4jSettings()

    if model:
        if model.lower() == "azure":
            llm = AzureConfig()
        else:
            llm = OpenAIGPTConfig(chat_model=model)
    else:
        llm = OpenAIGPTConfig(chat_model=OpenAIChatModel.GPT4o)

    match provider:
        case "google":
            search_tool_class = GoogleSearchTool
        case "ddg":
            search_tool_class = DuckduckgoSearchTool
        case _:
            raise ValueError(f"Unsupported provider {provider} specified.")

    search_tool_handler_method = search_tool_class.default_value("request")

    dependency_agent = DependencyGraphAgent(
        config=Neo4jChatAgentConfig(
            neo4j_settings=neo4j_settings,
            show_stats=False,
            use_tools=tools,
            use_functions_api=not tools,
            llm=llm,
            addressing_prefix=SEND_TO,
        ),
    )

    system_message = f"""You are an expert in Dependency graphs and analyzing them using
    Neo4j.

    FIRST, I'll give you the name of the package that I want to analyze.

    THEN, you can also use the `{search_tool_handler_method}` tool/function to find out information about a package,
      such as version number and package type (PyPi, NPM, Cargo, or GO).

    If unable to get this info, you can ask me and I can tell you.

    DON'T forget to include the package name in your questions.

    After receiving this information, make sure the package version is a number and the
    package type.
    THEN ask the user if they want to construct the dependency graph,
    and if so, use the tool/function `construct_dependency_graph` to construct
      the dependency graph. Otherwise, say `Couldn't retrieve package type or version`
      and {NO_ANSWER}.
    After constructing the dependency graph successfully, you will have access to Neo4j
    graph database, which contains dependency graph.
    You will try your best to answer my questions. Note that:
    1. You can use the tool `get_schema` to get node label and relationships in the
    dependency graph.
    2. You can use the tool `retrieval_query` to get relevant information from the
      graph database. I will execute this query and send you back the result.
      Make sure your queries comply with the database schema.
    3. Use the `{search_tool_handler_method}` tool/function to get information if needed.
    To display the dependency graph use this tool `visualize_dependency_graph`.
    4. Use the `vulnerability_check` tool to check for vulnerabilities in the package.
    """
    task = lr.Task(
        dependency_agent,
        name="DependencyAgent",
        system_message=system_message,
        interactive=False,
    )

    dependency_agent.enable_message(ConstructDepsGraphTool)
    dependency_agent.enable_message(search_tool_class)
    dependency_agent.enable_message(VisualizeGraph)
    dependency_agent.enable_message(VulnerabilityCheck)

    task.run()

    # check if the user wants to delete the database
    if dependency_agent.config.database_created:
        if Prompt.ask("[blue] Do you want to delete the database? (y/n)") == "y":
            dependency_agent.remove_database()


if __name__ == "__main__":
    app()
