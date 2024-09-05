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
from typing import Optional

import langroid as lr
from langroid import ChatDocument
import langroid.language_models as lm
from langroid.agent.tools.orchestration import (
    ForwardTool,
    SendTool,
    AgentDoneTool,
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
from langroid.utils.constants import AT

from dependencyrag.dependency_agent import DependencyGraphAgent

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


class AssistantAgent(lr.ChatAgent):
    def init_state(self):
        super().init_state()
        self.expecting_question_tool: bool = False
        self.expecting_question_or_final_answer: bool = False  # expecting one of these
        # tools
        self.expecting_search_answer: bool = False
        self.original_query: str | None = None  # user's original query
        # indicates the dependency graph is constructed
        self.done_construct_graph: bool = False
        self.accept_new_question: bool = False  # allows the user to ask questions

    def handle_message_fallback(
        self, msg: str | ChatDocument
    ) -> str | ChatDocument | None:
        if self.expecting_question_or_final_answer:
            return f"""
            You may have intended to use a tool, but your JSON format may be wrong.

            REMINDER: You must do one of the following:
            - If you are ready with the final answer to the user's ORIGINAL QUERY
                [ Remember it was: {self.original_query} ],
              then present your reasoning steps and final answer using the
              `final_answer_tool` in the specified JSON format.
            - If you still need to ask a question, then use the `question_tool`
              to ask a SINGLE question that can be answered by the appropriate agent.
            """
        elif self.accept_new_question:
            new_q_tool = AskNewQuestionTool(question="")
            return self.create_llm_response(tool_messages=[new_q_tool])
        elif self.expecting_question_tool:
            return f"""
            You must ask a question using the `question_tool` in the specified format,
            to break down the user's original query: {self.original_query} into
            smaller questions that can be answered by the approporiate agent.
            """

    def question_tool(self, msg: QuestionTool) -> str | ForwardTool:
        self.expecting_search_answer = True
        self.expecting_question_tool = False
        return ForwardTool(agent=msg.target_agent)

    def answer_tool(self, msg: AnswerTool) -> str:
        self.expecting_question_or_final_answer = True
        self.expecting_search_answer = False
        return f"""
        Here is the answer to your question:
        {msg.answer}
        Now decide whether you want to:
        - present your FINAL answer to the user's ORIGINAL QUERY, OR
        - ask another question using the `question_tool`
            (Maybe REPHRASE the question to get BETTER search results).
        """

    def answer_tool_graph(self, msg: AnswerToolGraphConstruction) -> str:
        self.done_construct_graph = True
        self.original_query = None  # reset the query
        self.accept_new_question = True
        msg = f"""{msg.answer} Now you can take user's questions? by addressing the
        "User" using {AT}User"""
        return super().llm_response_forget(msg)

    def final_answer_tool(self, msg: FinalAnswerTool) -> ForwardTool | str:
        if not self.expecting_question_or_final_answer:
            return ""
        self.expecting_question_or_final_answer = False
        # insert the original query into the tool, in case LLM forgot to do so.
        msg.query = self.original_query
        # fwd to critic
        return ForwardTool(agent="Critic")

    def ask_new_question_tool(self, msg: AskNewQuestionTool) -> str:
        self.accept_new_question = True
        msg = super().user_response("Please ask your question")
        self.accept_new_question = False
        self.original_query = None
        return msg

    def feedback_tool(self, msg: FeedbackTool) -> str:
        if msg.suggested_fix == "":
            self.original_query = None
            self.accept_new_question = True
            self.expecting_question_tool = False
            return "No more suggestions."
        else:
            self.expecting_question_or_final_answer = True
            # reset question count since feedback may initiate new questions
            return f"""
            Below is feedback about your answer. Take it into account to
            improve your answer, EITHER by:
            - using the `final_answer_tool` again but with improved REASONING, OR
            - asking another question using the `question_tool`, and when you're
                ready, present your final answer again using the `final_answer_tool`.

            FEEDBACK: {msg.feedback}
            SUGGESTED FIX: {msg.suggested_fix}
            """

    def llm_response(
        self, message: Optional[str | ChatDocument] = None
    ) -> Optional[ChatDocument]:
        if self.original_query is None:
            self.original_query = (
                message if isinstance(message, str) else message.content
            )
            # just received user query, so we expect a constructing the dependency graph
            # by using the tool `construct_dependency_graph`.
            # OR, this query is after constructing the dependency graph, so we need
            # to enable the flag `expecting_question_tool`
            if self.done_construct_graph and not self.accept_new_question:
                self.expecting_question_tool = True
            else:
                return super().llm_response(message)

        if self.expecting_question_or_final_answer or self.expecting_question_tool:
            return super().llm_response(message)


class RetrieverAgent(lr.ChatAgent):
    def init_state(self):
        super().init_state()
        self.curr_query: str | None = None
        self.expecting_search_results: bool = False
        self.expecting_search_tool: bool = False

    def handle_message_fallback(
        self, msg: str | ChatDocument
    ) -> str | ChatDocument | None:
        if isinstance(msg, ChatDocument) and msg.metadata.sender == lr.Entity.LLM:
            return """
            You may have intended to use a tool, but your JSON format may be wrong.
            Re-try your response using the CORRECT format of the tool/function.
            """

    def question_tool(self, msg: QuestionTool) -> str:
        self.curr_query = msg.question
        self.expecting_search_tool = True
        return f"""
        User asked this question: {msg.question}.
        Use the `vulnerability_check` tool if the question is about vulnerabilities.
        Otherwise, perform a web search using the `duckduckgo_search` tool
        using the specified JSON format, to find the answer.
        """

    def vulnerability_check(self, msg: VulnerabilityCheck) -> str:
        """Override the VulnerabilityCheck handler to update state"""
        self.expecting_search_results = True
        self.expecting_search_tool = False
        return msg.handle()

    def answer_tool(self, msg: AnswerTool) -> AgentDoneTool:
        # signal DONE, and return the AnswerTool
        return AgentDoneTool(tools=[msg])

    def duckduckgo_search(self, msg: DuckduckgoSearchTool) -> str:
        """Override the DDG handler to update state"""
        self.expecting_search_results = True
        self.expecting_search_tool = False
        msg.num_results = 3
        return msg.handle()

    def llm_response(
        self, message: Optional[str | ChatDocument] = None
    ) -> Optional[ChatDocument]:
        if self.expecting_search_results:
            # message must be search results from the web search tool,
            # vulnerability tool, or graph database.
            # so let the LLM compose a response based on the search results

            curr_query = self.curr_query
            # reset state
            self.curr_query = None
            self.expecting_search_results = False
            self.expecting_search_tool = False

            result = super().llm_response_forget(message)

            # return an AnswerTool containing the answer,
            # with a nudge meant for the Assistant
            answer = f"""
                Here are the web-search results for the question: {curr_query}.
                ===
                {result.content}
                """

            ans_tool = AnswerTool(answer=answer)
            # cannot return a tool, so use this to create a ChatDocument
            return self.create_llm_response(tool_messages=[ans_tool])

        # Handling query from user (or other agent) => expecting a search tool
        result = super().llm_response_forget(message)
        return result


class CriticAgent(lr.ChatAgent):
    def init_state(self):
        super().init_state()
        self.expecting_feedback_tool: bool = False

    def final_answer_tool(self, msg: FinalAnswerTool) -> str:
        # received from Assistant. Extract the components as plain text,
        # so that the Critic LLM can provide feedback
        self.expecting_feedback_tool = True

        return f"""
        The user has presented the following query, intermediate steps and final answer
        shown below. Please provide feedback using the `feedback_tool`,
        with the `feedback` field containing your feedback, and
        the `suggested_fix` field containing a suggested fix, such as fixing how
        the answer or the steps, or how it was obtained from the steps, or
        asking new questions.

        REMEMBER to set the `suggested_fix` field to an EMPTY string if the answer is
        VALID.

        QUERY: {msg.query}

        STEPS: {msg.steps}

        ANSWER: {msg.answer}
        """

    def feedback_tool(self, msg: FeedbackTool) -> FeedbackTool:
        # validate, signal DONE, include the tool
        self.expecting_feedback_tool = False
        return AgentDoneTool(tools=[msg])

    def handle_message_fallback(
        self, msg: str | ChatDocument
    ) -> str | ChatDocument | None:
        if self.expecting_feedback_tool:
            return """
            You forgot to provide feedback using the `feedback_tool`
            on the user's reasoning steps and final answer.
            """


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
              different agents.

            First, ask the user to provide the name of the package, version, and ecosystem,
             they want to analyze.
            Then, use the TOOL: `{construct_dependency_graph_tool_name}` to
            construct the dependency graph.
            After constructing the dependency graph, the user will ask their questions.
            You must ask me (the user) each question ONE BY ONE, using the
               {question_tool_name} in the specified format, and I will retreive information
                either from the constructed dependency graph, the web, or the
                vulnerability database. Provide ALL package name, version, and type when
                you ask the question about vulnerabilities.
            Once you have enough information to answer my original (complex) question,
              you MUST present your INTERMEDIATE STEPS and FINAL ANSWER using the
               `final_answer_tool` in the specified JSON format. You will then receive
                FEEDBACK from the Critic, and if needed you should try to improve your
                answer based on this feedback.
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

    retriever_agent = RetrieverAgent(
        config=lr.ChatAgentConfig(
            name="RetrieverAgent",
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
        You excel at logical reasoning and combining pieces of information.
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

    retriever_agent.enable_message(DuckduckgoSearchTool)
    retriever_agent.enable_message(VulnerabilityCheck)
    retriever_agent.enable_message(QuestionTool, use=False, handle=True)
    # agent is producing AnswerTool, so LLM should not be allowed to "use" it
    retriever_agent.enable_message(AnswerTool, use=False, handle=True)

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

    retriever_task = lr.Task(
        retriever_agent,
        interactive=False,
        llm_delegate=True,
        single_round=False,
    )

    assistant_task = lr.Task(
        assistant_agent,
        interactive=False,
        restart=True,
    )

    critic_task = lr.Task(
        critic_agent,
        interactive=False,
    )

    assistant_task.add_sub_task([dependency_task, retriever_task, critic_task])
    assistant_task.run("chainlit version 1.1.200 pypi")


if __name__ == "__main__":
    app()
