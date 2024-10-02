"""
Single-agent to use to chat with a Neo4j knowledge-graph (KG)
that models a dependency graph of Python packages.

This is a chainlit UI version of dependencyrag/dependency_chatbot.py

Run like this:
```
chainlit run dependencyrag/dependency_chatbot.py
```

The requirements are described in
 `https://github.com/Mohannadcse/DependencyRAG/blob/main/README.md`
"""

import typer

import langroid as lr
import langroid.language_models as lm
import chainlit as cl
from langroid.agent.callbacks.chainlit import (
    add_instructions,
    make_llm_settings_widgets,
    setup_llm,
    update_llm,
)
from textwrap import dedent

from langroid.utils.configuration import set_global, Settings
from langroid.agent.tools.google_search_tool import GoogleSearchTool
from langroid.agent.task import Task
from langroid.agent.special.neo4j.neo4j_chat_agent import (
    Neo4jChatAgentConfig,
    Neo4jSettings,
    GraphSchemaTool,
    CypherCreationTool,
)
from langroid.agent.tools.duckduckgo_search_tool import DuckduckgoSearchTool

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


async def setup_agent_task():
    """Set up Agent and Task from session settings state."""

    # set up LLM and LLMConfig from settings state
    await setup_llm()
    llm_config = cl.user_session.get("llm_config")

    set_global(
        Settings(
            debug=False,
            cache=True,
        )
    )

    neo4j_settings = Neo4jSettings()
    question_tool_name = QuestionTool.default_value("request")
    construct_dependency_graph_tool_name = ConstructDepsGraphTool.default_value(
        "request"
    )

    assistant_agent = AssistantAgent(
        lr.ChatAgentConfig(
            name="AssistantAgent",
            llm=llm_config,
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
            # use_tools=tools,
            # use_functions_api=not tools,
            llm=llm_config,
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
            # use_tools=tools,
            # use_functions_api=not tools,
            llm=llm_config,
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
        llm=llm_config,
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

    cl.user_session.set("assistant_agent", assistant_agent)
    cl.user_session.set("assistant_task", assistant_task)


@cl.on_settings_update
async def on_update(settings):
    await update_llm(settings)
    await setup_agent_task()


@cl.on_chat_start
async def chat() -> None:
    await add_instructions(
        title="Welcome to Python Dependency chatbot!",
        content=dedent(
            """
        Ask any questions about Python packages, and I will try my best to answer them.
        But first, the user specifies package name
        -> agent gets version number and type of package using google search
        -> agent builds dependency graph using Neo4j
        -> user asks natural language query about dependencies
        -> LLM translates to Cypher query to get info from KG
        -> Query results returned to LLM
        -> LLM translates to natural language response
        """
        ),
    )

    await make_llm_settings_widgets(
        lm.OpenAIGPTConfig(
            timeout=180,
            chat_context_length=16_000,
            chat_model="",
            temperature=0.1,
        )
    )
    await setup_agent_task()


@cl.on_message
async def on_message(message: cl.Message):
    task = cl.user_session.get("assistant_task")
    lr.ChainlitTaskCallbacks(task, message)
    await task.run_async(message.content)
