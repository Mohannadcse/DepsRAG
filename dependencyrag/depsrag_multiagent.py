"""
Multi-agent to use to chat with a Neo4j knowledge-graph (KG)
that models a dependency graph of Python packages.

This scenario comprises 4 agents:
- AssistantAgent: orchestrates between other agents and breaks down complex questions
 into smaller steps.
- SearchAgent: retreive information from the web or the vulnerability database.
- DependencyGraphAgent: builds a dependency graph using Neo4j. It also translates natural
 language to Cypher queries and executes them on the KG to answer user's queries.
- CriticAgent: provides feedback to the user based on the assistant's response.

The workflow as follows.
1-> User provides package name, version, and ecosystem
2-> AssistantAgent sends these details to the DependencyGraphAgent to build the
 dependency graph using Neo4j.
3-> user asks natural language query about dependencies
4-> AssistantAgent simplifies these question into steps and sends them to the targeted
 agents: DependencyGraphAgent and/or SearchAgent.
5-> Query results returned to the AssistantAgent, if there are remaining steps, the
 AssistantAgent will repeat step 4 until receiving answers upon all steps.
6-> AssistantAgent summarizes the answers and send them to the CriticAgent to get
 a feedback. Then, the AssistantAgent can take new questions from the user if the
 CriticAgent accepts the answer, otherwise, the AssistantAgent tries to fix the answer
 based on the feedback.

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
python3 dependencyrag/depsrag_multiagent.py
```
"""

import typer

from dotenv import load_dotenv
from rich.prompt import Prompt

import langroid as lr
import langroid.language_models as lm
from langroid.agent.tools.orchestration import (
    ForwardTool,
    SendTool,
)
from langroid.agent.special.neo4j.neo4j_chat_agent import (
    Neo4jChatAgentConfig,
    Neo4jSettings,
    GraphSchemaTool,
    CypherCreationTool,
)
from langroid.agent.tools.duckduckgo_search_tool import DuckduckgoSearchTool
from langroid.utils.configuration import set_global, Settings

from dependencyrag.dependency_agent import DependencyGraphAgent
from dependencyrag.critic_agent import CriticAgent
from dependencyrag.assistant_agent import AssistantAgent
from dependencyrag.search_agent import SearchAgent

from dependencyrag.tools import (
    ConstructDepsGraphTool,
    VulnerabilityCheck,
    QuestionTool,
    FinalAnswerTool,
    FeedbackTool,
    AnswerTool,
    AnswerToolGraphConstruction,
    AskNewQuestionTool,
)

app = typer.Typer()

send_tool_name = SendTool.default_value("request")
forward_tool_name = ForwardTool.default_value("request")
question_tool_name = QuestionTool.default_value("request")
construct_dependency_graph_tool_name = ConstructDepsGraphTool.default_value("request")


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", "-d", help="debug mode"),
    model: str = typer.Option("", "--model", "-m", help="model name"),
    tools: bool = typer.Option(
        False, "--tools", "-t", help="use langroid tools instead of function-calling"
    ),
    nocache: bool = typer.Option(False, "--nocache", "-nc", help="don't use cache"),
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
            llm = lm.azure_openai.AzureConfig()
        else:
            llm = lm.OpenAIGPTConfig(chat_model=model)
    else:
        llm = lm.OpenAIGPTConfig(chat_model=lm.OpenAIChatModel.GPT4o)

    # llm = lm.azure_openai.AzureConfig()
    # llm = lm.OpenAIGPTConfig(chat_model='groq/llama3-70b-8192')

    assistant_agent = AssistantAgent(
        lr.ChatAgentConfig(
            name="AssistantAgent",
            llm=llm,
            system_message=f"""
            You are a resourceful assistant, able to think step by step to answer
             complex questions from the user about software dependency graphs.
            Your task is to:
             (1) coordinate the other agents to construct and analyze
             dependency graphs for software packages.
             (2) Answer user's questions. You must break down complex questions into
              simpler questions that can be answered by retreieving information from
              different agents.

            First, ask the user to provide the name of the package, version, and ecosystem,
             they want to analyze.
            Then, use the TOOL: `{construct_dependency_graph_tool_name}` to
            construct the dependency graph.
            After constructing the dependency graph, the user will ask their questions.
            You must ask me (the user) each question ONE BY ONE, using the
               {question_tool_name} in the specified format, and I will retreive the
               approporiate information from the constructed dependency graph, the web,
               and/or the vulnerability database.
               Provide ALL package name, version, and type when you ask a question
               about vulnerabilities.
            Once you have enough information to answer my original (complex) question,
              you MUST present your INTERMEDIATE STEPS and FINAL ANSWER using the
               `final_answer_tool` in the specified JSON format.
            You will then receive FEEDBACK from the Critic, and if needed you should
              try to improve your answer based on this feedback.
            """,
        )
    )

    dependency_agent = DependencyGraphAgent(
        config=Neo4jChatAgentConfig(
            name="DependencyGraphAgent",
            neo4j_settings=neo4j_settings,
            show_stats=False,
            use_tools=tools,
            use_functions_api=not tools,
            llm=llm,
            system_message="""You are an expert in retreiving information from Neo4j
            graph database.
            - Use the tool/function `construct_dependency_graph` to construct the
              dependency graph.
            - Once you receive the results from the graph database about the dependency
             graph you must compose a CONCISE answer and say DONE and show the answer
             to me, in this format: DONE [... your CONCISE answer here ...]
            """,
        )
    )

    search_agent = SearchAgent(
        config=lr.ChatAgentConfig(
            name="SearchAgent",
            show_stats=False,
            use_tools=tools,
            use_functions_api=not tools,
            llm=llm,
            system_message="""You are an expert in retreiving information about
             security vulnerabilitiy for packages and performing web search.
            - Use the tool/function `vulnerability_check` to retrieve vulnerabilitiy
             information about the provided package name and package version.
            MAKE SURE you have these information before using this tool/function.
            - Use the tool/function `duckduckgo_search` to retreive
             information from the web.
            """,
        )
    )

    critic_agent_config = lr.ChatAgentConfig(
        llm=llm,
        vecdb=None,
        name="Critic",
        system_message="""
        You excel at logical reasoning and combining pieces of information retrieved from:
        - the dependency graph database
        - the web search
        - the vulnerability database
        To validate the correctness of the answer, YOU NEED to consider graph and Tree
        concepts because the dependecy graph is a Tree structure, where the root node
        is the package name provided by the user.
        The user will send you a summary of the intermediate steps and final answer.
        You must examine these and provide feedback to the user, using the
        `feedback_tool`, as follows:
        - If you think the answer is valid,
            simply set the `suggested_fix` field to an empty string "".
        - Otherwise set the `feedback` field to a reason why the answer is invalid,
            and in the `suggested_fix` field indicate how the user can improve the
            answer, for example by reasoning differently, or asking different questions.
        """,
    )
    critic_agent = CriticAgent(critic_agent_config)

    search_agent.enable_message(DuckduckgoSearchTool)
    search_agent.enable_message(VulnerabilityCheck)
    search_agent.enable_message(QuestionTool, use=False, handle=True)
    # agent is producing AnswerTool, so LLM should not be allowed to "use" it
    search_agent.enable_message(AnswerTool, use=False, handle=True)

    dependency_agent.enable_message(ConstructDepsGraphTool, use=False, handle=True)
    dependency_agent.enable_message(QuestionTool, use=False, handle=True)
    dependency_agent.disable_message_use(GraphSchemaTool)
    dependency_agent.disable_message_use(CypherCreationTool)
    dependency_agent.enable_message(QuestionTool, use=False, handle=True)
    # agent is producing AnswerTool, so LLM should not be allowed to "use" it
    dependency_agent.enable_message(AnswerTool, use=False, handle=True)
    dependency_agent.enable_message(AnswerToolGraphConstruction, use=False, handle=True)

    assistant_agent.enable_message(QuestionTool, use=True, handle=True)
    assistant_agent.enable_message(ConstructDepsGraphTool, use=True, handle=True)
    assistant_agent.enable_message(FinalAnswerTool)
    assistant_agent.enable_message(FeedbackTool, use=False, handle=True)
    assistant_agent.enable_message(AnswerTool, use=False, handle=True)  #
    assistant_agent.enable_message(AnswerToolGraphConstruction, use=False, handle=True)
    assistant_agent.enable_message(AskNewQuestionTool, use=False, handle=True)

    critic_agent.enable_message(FeedbackTool)
    critic_agent.enable_message(FinalAnswerTool, use=False, handle=True)

    dependency_task = lr.Task(
        dependency_agent,
        llm_delegate=True,
        single_round=False,
        interactive=False,
    )

    search_task = lr.Task(
        search_agent,
        interactive=False,
        llm_delegate=True,
        single_round=False,
    )

    assistant_task = lr.Task(
        assistant_agent,
        interactive=False,
        restart=True,
        config=lr.TaskConfig(inf_loop_cycle_len=0),
    )

    critic_task = lr.Task(
        critic_agent,
        interactive=False,
    )

    assistant_task.add_sub_task([dependency_task, search_task, critic_task])
    question = Prompt.ask(
        """Ask the question and provide the package information: Name, Version,
        and Ecosystem"""
    )
    assistant_task.run(question)


if __name__ == "__main__":
    app()
