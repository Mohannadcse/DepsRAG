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
from logging import getLogger

import langroid as lr
import langroid.language_models as lm
from langroid.utils.constants import SEND_TO
from langroid.agent.tools.orchestration import (
    ForwardTool,
    SendTool,
)
from langroid.agent.special.neo4j.neo4j_chat_agent import (
    Neo4jChatAgentConfig,
    Neo4jSettings,
    CypherCreationTool,
)
from langroid.agent.tools.duckduckgo_search_tool import DuckduckgoSearchTool
from langroid.utils.configuration import set_global, Settings

from dependencyrag.dependency_agent import DependencyGraphAgent
from dependencyrag.critic_agent import CriticAgent
from dependencyrag.assistant_agent import AssistantAgent
from dependencyrag.search_agent import SearchAgent
from dependencyrag.iteration_analysis import store_and_reset_analytics_attributes
from dependencyrag.tools import (
    ConstructDepsGraphTool,
    VulnerabilitySearchTool,
    QuestionTool,
    FinalAnswerTool,
    FeedbackTool,
    AnswerTool,
    AnswerToolGraphConstruction,
    AskNewQuestionTool,
    feedback_tool_name,
    construct_dependency_graph_tool_name,
    question_tool_name,
    final_answer_tool_name,
    vulnerability_search_tool_name,
)

app = typer.Typer()
logger = getLogger(__name__)

send_tool_name = SendTool.default_value("request")
forward_tool_name = ForwardTool.default_value("request")
duckduckgo_search_tool_name = DuckduckgoSearchTool.default_value("request")


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

    llm = lm.azure_openai.AzureConfig(
        chat_context_length=128_000,
    )
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
               `{question_tool_name}` in the specified format, and I will retreive the
               approporiate information from the constructed dependency graph, the web,
               and/or the vulnerability database.
               Provide ALL package name, version, and type when you ask a question
               about vulnerabilities.
            Once you have enough information to answer my original (complex) question,
              you MUST present your INTERMEDIATE STEPS and FINAL ANSWER using the
               `{final_answer_tool_name}` in the specified JSON format.
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
            system_message=f"""You are an expert in querying and retrieving precise information from a Neo4j graph database.

- Use the `{construct_dependency_graph_tool_name}` tool to construct the dependency graph.
- Ensure that your Cypher queries are optimized and retrieve only the necessary information to address the user's query.
- After receiving the results from the graph database, compose a **clear, concise, and accurate answer**. Ensure your response directly addresses the user's question without ambiguity.
- If the query results are incomplete, ambiguous, or inconsistent, **identify the issue** and explain it clearly to the user.
- Your final response must provide value to the user by delivering a precise answer based on the query results. Avoid generic responses or assumptions.
- Include the key details from the graph database results in a structured and easy-to-understand format, such as a list or short paragraph.
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
            system_message=f"""You are an expert in retreiving information about
             security vulnerabilitiy for packages and performing web search.
            - Use the tool/function `{vulnerability_search_tool_name}` to retrieve vulnerabilitiy
             information about the provided package name and package version.
            MAKE SURE you have these information before using this tool/function.
            - Use the tool/function `{duckduckgo_search_tool_name}` to retreive
             information from the web.
            """,
        )
    )

    critic_agent_config = lr.ChatAgentConfig(
        llm=llm,
        vecdb=None,
        name="Critic",
        system_message=f"""
        You are an expert in logical reasoning about software dependency graphs
        represented as a knolwedge graph using Neo4j.
        Your task is to analyze and validate answers and data retrieved.

        ### Your Objective:
        - Evaluate the correctness of the user's proposed answer and reasoning process.
        - Provide clear, actionable feedback.

        ### Key Instructions:
        1. **Understand and verify the accuracy of the retreived Data**:
        - ANY computations and retreived data MUST be grounded and aligend with the characteristics
        of the `Dependency Graph Database` considering ALL nodes and edges in the graph.
        - Use information from all data sources holistically, incorporating graph theory
        principles where applicable.

        2. **Feedback Workflow**:
        - The user will provide a summary of intermediate steps and a final answer for validation.
        - Your evaluation should assess logical reasoning, completeness, and alignment
        with the aforementioned characteristics of the graph databased.
        - Use the `{feedback_tool_name}` to provide your feedback.

        3. **Feedback Guidelines**:
        - If the answer is valid:
            - Set the `suggested_fix` field to an empty string (`""`).
        - If the answer is invalid:
            - Provide a clear explanation in the `feedback` field, detailing why the
             answer is incorrect.
            - Use the `suggested_fix` field to propose specific improvements, such as:
            - Alternative reasoning paths.
            - Additional data queries or computations.
            - Reframing the problem for better clarity or accuracy.
            - If the Cypher query is provided, provide a feedback to refine the Cypher
             query accurate information from the graph database.
        Ensure your feedback is concise, constructive, and actionable.
        """,
    )
    critic_agent = CriticAgent(critic_agent_config)

    search_agent.enable_message(DuckduckgoSearchTool)
    search_agent.enable_message(VulnerabilitySearchTool)
    search_agent.enable_message(QuestionTool, use=False, handle=True)
    # agent is producing AnswerTool, so LLM should not be allowed to "use" it
    search_agent.enable_message(AnswerTool, use=False, handle=True)

    dependency_agent.enable_message(ConstructDepsGraphTool, use=False, handle=True)
    dependency_agent.enable_message(QuestionTool, use=False, handle=True)
    # dependency_agent.disable_message_use(GraphSchemaTool)
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
        config=lr.TaskConfig(inf_loop_cycle_len=0, addressing_prefix=SEND_TO),
    )

    critic_task = lr.Task(
        critic_agent,
        interactive=False,
    )

    assistant_task.add_sub_task([dependency_task, search_task, critic_task])

    questions_list = {
        1: """Construct the dependency graph for the package 'chainlit' version 1.1.200 in the PyPI ecosystem,
          then answer this question based on the constructed graph: What is the density of the graph?""",
        2: """Construct the dependency graph for the package 'chainlit' version 1.1.200 in the PyPI ecosystem,
           then answer this question: which packages have the highest in-degree (i.e., the most dependencies relying on them)?
           Additionally, what risks are associated with vulnerabilities in these packages?""",
        3: """Construct the dependency graph for the package 'chainlit' version 1.1.200 in the PyPI ecosystem,
        then answer this question: Are there any multi-version conflicts in the dependency graph
           where different packages depend on different versions of the same package?
           If such conflicts exist, provide examples along with all paths leading to these packages from the root node.""",
    }
    # assistant_task.run(question)

    for question_no, question_str in questions_list.items():
        for i in range(1):  # the number of iterations
            assistant_task.run(question_str)
            store_and_reset_analytics_attributes(
                iteration=i,  # The iteration count
                dep_agent=dependency_agent,
                asst_agent=assistant_agent,
                critic_agent=critic_agent,
                search_agent=search_agent,
                question_no=question_no,
                question_str=question_str,
            )


if __name__ == "__main__":
    app()
