"""
Multi-agent to use to chat with a Neo4j knowledge-graph (KG)
that models a dependency graph of Python packages.

This scenario comprises 4 agents:
- AssistantAgent: orchestrates between other agents and breaks down complex questions
 into smaller steps.
- RetrieverAgent: retreive information from the web or the vulnerability database.
- DependencyGraphAgent: builds a dependency graph using Neo4j. It alsotranslates natural
 language to Cypher queries and executes them on the KG to answer user's queries.
- CriticAgent: provides feedback to the user based on the assistant's response.

The workflow as follows.
1-> User provides package name, version, and ecosystem
2-> AssistantAgent sends these details to the DependencyGraphAgent to build the
 dependency graph using Neo4j.
3-> user asks natural language query about dependencies
4-> AssistantAgent simplifies these question into steps and sends them to the targeted
 agents: DependencyGraphAgent and/or RetrieverAgent.
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

import langroid as lr
from langroid import ChatDocument
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
from langroid.agent.tools.google_search_tool import GoogleSearchTool
from langroid.agent.tools.duckduckgo_search_tool import DuckduckgoSearchTool
from langroid.utils.configuration import set_global, Settings

from dependencyrag.dependency_agent import DependencyGraphAgent

from dependencyrag.tools import (
    ConstructDepsGraphTool,
    VulnerabilityCheck,
    QuestionTool,
    FinalAnswerTool,
    FeedbackTool,
)

app = typer.Typer()

send_tool_name = SendTool.default_value("request")
forward_tool_name = ForwardTool.default_value("request")
question_tool_name = QuestionTool.default_value("request")
construct_dependency_graph_tool_name = ConstructDepsGraphTool.default_value("request")


class AssistantAgent(lr.ChatAgent):
    # def __init__(self, config: lr.ChatAgentConfig):
    #     super().__init__(config)

    def question_tool(self, msg: QuestionTool) -> str:
        return msg.to_json()

    def final_answer_tool(self, msg: FinalAnswerTool) -> str:
        """
        if not self.has_asked or self.n_questions > 1:
            # not yet asked any questions, or LLM is currently asking
            # a question (and this is the second one in this turn, and so should
            # be ignored), ==>
            # cannot present final answer yet (LLM may have hallucinated this json)
            return ""
        """
        # valid final answer tool: PASS it on so Critic gets it
        return lr.utils.constants.PASS_TO + "Critic"

    def feedback_tool(self, msg: FeedbackTool) -> str:
        if msg.feedback == "":
            return lr.utils.constants.DONE
        else:
            return f"""
            Below is feedback about your answer. Take it into account to
            improve your answer, and present it again using the `final_answer_tool`.

            FEEDBACK:

            {msg.feedback}
            """


class RetrieverAgent(lr.ChatAgent):
    def handle_message_fallback(
        self, msg: str | ChatDocument
    ) -> str | ChatDocument | None:
        if isinstance(msg, ChatDocument) and msg.metadata.sender == lr.Entity.LLM:
            return """
            You may have intended to use a tool, but your JSON format may be wrong.
            Re-try your response using the CORRECT format of the tool/function.
            """


class CriticAgent(lr.ChatAgent):
    def final_answer_tool(self, msg: FinalAnswerTool) -> str:
        # received from Assistant. Extract the components as plain text,
        # so that the Critic LLM can provide feedback
        return f"""
        The user has presented the following intermediate steps and final answer
        shown below. Please provide feedback using the `feedback_tool`.
        Remember to set the `feedback` field to an empty string if the answer is valid,
        otherwise give specific feedback on what the issues are and how the answer
         can be improved.

        STEPS: {msg.steps}

        ANSWER: {msg.answer}
        """

    def feedback_tool(self, msg: FeedbackTool) -> str:
        # say DONE and PASS to the feedback goes back to Assistant to handle
        return lr.utils.constants.DONE + " " + lr.utils.constants.PASS


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
            llm = lm.azure_openai.AzureConfig()
        else:
            llm = lm.OpenAIGPTConfig(chat_model=model)
    else:
        llm = lm.OpenAIGPTConfig(chat_model=lm.OpenAIChatModel.GPT4o)

    llm = lm.azure_openai.AzureConfig()

    match provider:
        case "google":
            search_tool_class = GoogleSearchTool
        case "ddg":
            search_tool_class = DuckduckgoSearchTool
        case _:
            raise ValueError(f"Unsupported provider {provider} specified.")

    search_tool_handler_method = search_tool_class.default_value("request")

    assistant_agent = AssistantAgent(
        lr.ChatAgentConfig(
            name="AssistantAgent",
            llm=llm,
            system_message=f"""
            You are a resourceful assistant, able to think step by step to answer
             complex questions from the user about software dependency graph.
            Your task is to:
             (1) coordinate the other agents to construct and analyze
             dependency graphs for software packages.
             (2) Answer user's questions. You must break down complex questions into
              simpler questions that can be answered by retreieving information from
              different sources.
              You must ask me (the user) each question ONE BY ONE, using the
               `question_tool` in the specified format, and I will retreive information
                from the constructed dependency graph, the web, or the vulnerability database.
              Once you receive the information and send you a brief answer.
              Once you have enough information to answer my original (complex) question,
              you MUST present your INTERMEDIATE STEPS and FINAL ANSWER using the
               `final_answer_tool` in the specified JSON format. You will then receive
                FEEDBACK from the Critic, and if needed you should try to improve your
                answer based on this feedback.

            First, ask the user to provide the name of the package, version, and ecosystem,
             they want to analyze.
            Then, use the TOOL: `{construct_dependency_graph_tool_name}` to
            construct the dependency graph.
            After constructing the dependency graph, ask the user if they have any
             other questions or if they want to quit.
            Once you receive the User's query, process it like this:
            - Use the TOOL: `{send_tool_name}` to send the query `RetrieverAgent` Agent
            If you need to retreive information about the vulnerabilities.
            ALSO, send the query to `RetrieverAgent` Agent if you need to retreive
             information from the web.
            - Use the TOOL: {question_tool_name} to send the query, if the query
             requires analyzing or retreiving information from the dependency graph.
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
            system_message=f"""You are an expert in Dependency graphs and analyzing
             them using Neo4j.
            - Use the tool/function `construct_dependency_graph` to construct the
              dependency graph.
            - Use the tool/function `{question_tool_name}` to get relevant information from the
             graph database about the dependency graph. Once you receive the results,
              you must compose a CONCISE answer and say DONE and show the answer to me,
               in this format: DONE [... your CONCISE answer here ...]
            """,
        )
    )

    retriever_agent = RetrieverAgent(
        config=lr.ChatAgentConfig(
            name="RetrieverAgent",
            show_stats=False,
            use_tools=tools,
            use_functions_api=not tools,
            llm=llm,
            system_message=f"""You are an expert in retreiving information about
             security vulnerabilitiy for packages and performing web search.
            - Use the tool/function `vulnerability_check` to retrieve vulnerabilitiy
             information about the provided package name and package version.
            MAKE SURE you have these information before using this tool/function.
            - Use the tool/function `{search_tool_handler_method}` to retreive
             information from the web.
            """,
        )
    )

    critic_agent_config = lr.ChatAgentConfig(
        llm=llm,
        vecdb=None,
        name="Critic",
        system_message="""
        You excel at logical reasoning and combining pieces of information.
        The user will send you a summary of the intermediate steps and final answer.
        You must examine these and provide feedback to the user, using the
        `feedback_tool`, as follows:
        - If you think the answer is valid,
            simply set the `feedback` field to an empty string "".
        - Otherwise set the `feedback` field to a reason why the answer is invalid,
            and suggest how the user can improve the answer.
        """,
    )
    critic_agent = CriticAgent(critic_agent_config)

    retriever_agent.enable_message(search_tool_class)
    retriever_agent.enable_message(VulnerabilityCheck)

    dependency_agent.enable_message(ConstructDepsGraphTool, use=False, handle=True)
    dependency_agent.enable_message(QuestionTool, use=False, handle=True)
    dependency_agent.disable_message_use(GraphSchemaTool)
    dependency_agent.disable_message_use(CypherCreationTool)

    assistant_agent.enable_message(SendTool, use=True, handle=True)
    assistant_agent.enable_message(QuestionTool, use=True, handle=True)
    assistant_agent.enable_message(ConstructDepsGraphTool, use=True, handle=True)
    assistant_agent.enable_message(FinalAnswerTool)
    assistant_agent.enable_message(FeedbackTool, use=False, handle=True)

    critic_agent.enable_message(FeedbackTool)
    critic_agent.enable_message(FinalAnswerTool, use=False, handle=True)

    dependency_task = lr.Task(
        dependency_agent,
        interactive=False,
        llm_delegate=True,
    )

    retriever_task = lr.Task(
        retriever_agent, interactive=False, done_if_response=[lr.Entity.AGENT]
    )

    assistant_task = lr.Task(
        assistant_agent,
        interactive=True,
    )

    critic_task = lr.Task(
        critic_agent,
        # name="Critic",
        interactive=False,
    )

    assistant_task.add_sub_task([dependency_task, retriever_task, critic_task])
    assistant_task.run("chainlit version 1.1.200 pypi")


if __name__ == "__main__":
    app()
